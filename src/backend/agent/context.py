import base64
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.runtime import Runtime

from src.backend.agent.prompts import (
    DEFAULT_GLOBAL_PROMPT_PATH,
    build_system_prompt,
)
from src.backend.agent.state import AgentState
from src.backend.services.event_log import EventLogService, event_log
from src.backend.services.recorder import RunRecorder, extract_execution_metadata
from src.backend.services.cancellation import CancellationToken


# 摘要阈值使用模型上下文窗口的比例。SummarizationMiddleware 会读取
# ``model.profile["max_input_tokens"]``，因此更换模型后不需要改这里的
# 固定 Token 数值。
SUMMARY_TRIGGER_FRACTION = 0.75
SUMMARY_KEEP_FRACTION = 0.25
TOOL_MESSAGE_MAX_CHARS = 12_000
TOOL_MESSAGE_TRUNCATION_NOTICE = (
    "\n\n[工具结果过长，已仅为本次模型调用截断；完整结果仍保存在历史中。]"
)


class PermissionMode(StrEnum):
    """Agent 对修改类工具的执行权限。"""

    REQUEST_APPROVAL = "request_approval"
    FULL_ACCESS = "full_access"


class ModelProvider(StrEnum):
    """当前支持的模型供应商。"""

    SILICONFLOW = "siliconflow"
    DEEPSEEK = "deepseek"


class StatusEvent(TypedDict):
    """仅用于当前实时连接的统一阶段状态。"""

    type: Literal["status"]
    stage: Literal["context", "model", "approval", "tool", "summary"]
    message: str
    tool_call_id: str | None
    tool_name: str | None


def write_status(
    runtime: Runtime["AgentContext"],
    *,
    stage: Literal["context", "model", "approval", "tool", "summary"],
    message: str,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
) -> None:
    """通过 custom stream 发送状态，不写入 State 或持久化层。"""
    runtime.context.cancellation.raise_if_cancelled()
    runtime.stream_writer(
        StatusEvent(
            type="status",
            stage=stage,
            message=message,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )
    )


@dataclass
class AgentContext:
    """一次 Agent 运行期间保持不变的环境信息。"""

    user_id: str
    workspace_path: str
    accessible_paths: tuple[str, ...] = ()
    global_prompt_path: str | None = str(DEFAULT_GLOBAL_PROMPT_PATH)
    permission: PermissionMode = PermissionMode.REQUEST_APPROVAL
    provider: ModelProvider = ModelProvider.SILICONFLOW
    model_name: str = "Qwen/Qwen3.5-4B"
    recorder: RunRecorder | None = None
    cancellation: CancellationToken = field(default_factory=CancellationToken)


def create_summarization_middleware(
    model: BaseChatModel,
) -> SummarizationMiddleware:
    """创建对话摘要器。

    这是 Lifecycle Context：它在每次模型调用前检查完整的
    ``state.messages``，达到阈值时用“历史摘要 + 最近消息”持久替换消息
    State。它不是 Model Context Builder；后者只负责临时构造本次模型
    实际看到的内容，不应把临时裁剪或图片 Base64 写回 State。
    """
    return SummarizationMiddleware(
        model=model,
        trigger=("fraction", SUMMARY_TRIGGER_FRACTION),
        keep=("fraction", SUMMARY_KEEP_FRACTION),
        # 不把待总结历史额外裁成中间件默认的小片段，避免摘要遗漏较早的
        # 重要决定。真正的上限由当前摘要模型的 Profile 决定。
        trim_tokens_to_summarize=None,
    )


def summarize_state_messages(
    state: AgentState,
    runtime: Runtime[AgentContext],
    summarizer: SummarizationMiddleware,
) -> dict[str, Any]:
    """执行模型调用前的 Lifecycle Context 摘要步骤。

    未达到阈值时不更新 State；达到阈值时，官方中间件返回
    ``RemoveMessage``、摘要消息和需要保留的最近消息。AgentState 的
    ``add_messages`` reducer 会应用这次替换，SqliteSaver 随后保存新的
    checkpoint。
    """
    update = summarizer.before_model(state, runtime) or {}
    recorder = runtime.context.recorder if runtime is not None else None
    replacement = update.get("messages")
    if not recorder or not replacement:
        return update

    old_message_ids = [message.id for message in state["messages"] if message.id]
    preserved_message_ids = [
        message.id
        for message in replacement
        if not isinstance(message, RemoveMessage)
        and message.id
        and message.id in old_message_ids
    ]
    summary_index = next(
        (
            index
            for index, message in enumerate(replacement)
            if isinstance(message, HumanMessage)
            and message.additional_kwargs.get("lc_source") == "summarization"
        ),
        None,
    )
    if summary_index is None:
        return update

    summarized_message_ids = [
        message_id
        for message_id in old_message_ids
        if message_id not in preserved_message_ids
    ]
    summary_message = recorder.context_compacted(
        summary_message=replacement[summary_index],
        summarized_message_ids=summarized_message_ids,
        preserved_message_ids=preserved_message_ids,
        execution=extract_execution_metadata(runtime),
    )
    normalized_replacement = list(replacement)
    normalized_replacement[summary_index] = summary_message
    return {**update, "messages": normalized_replacement}


def build_model_context(
    state: AgentState,
    runtime: Runtime[AgentContext],
    *,
    thread_id: str | None = None,
    event_log_service: EventLogService = event_log,
) -> list[AnyMessage]:
    """构造本次模型实际看到的临时消息列表。

    这是 Model Context：它从已经过 Lifecycle Context 整理的 State 中读取
    消息，动态加入系统信息、截断过长工具结果，并只加载本轮明确选择的图片。
    返回值不会写回 State，因此临时裁剪和图片 Base64 不会进入 checkpoint。
    """
    prepare = state.get("prepare")
    instructions = prepare.get("instructions") if prepare else None
    if instructions:
        system_prompt = instructions["system_prompt"]
    else:
        # 兼容旧 checkpoint 和旧 JSONL 重建出的基础 prepare。
        # 该降级路径不读取外部文件，避免在审批恢复时改变同一 turn 的上下文。
        workspace_path = Path(runtime.context.workspace_path).expanduser().resolve()
        system_prompt = build_system_prompt(
            workspace_path=str(workspace_path),
            accessible_paths=runtime.context.accessible_paths,
            permission_description=permission_description(
                runtime.context.permission
            ),
        )
    messages = [_truncate_tool_message(message) for message in state["messages"]]
    messages = _inject_selected_images(
        messages,
        state,
        thread_id=thread_id,
        event_log_service=event_log_service,
    )
    return [SystemMessage(content=system_prompt), *messages]


def permission_description(permission: PermissionMode) -> str:
    if permission == PermissionMode.FULL_ACCESS:
        return "完全访问：工作区内外的读取和修改工具均可直接执行，无需逐次批准"
    return (
        "请求批准：修改型工具需要逐个批准；项目外路径的读取或修改"
        "会显示规范化绝对路径并请求一次性授权"
    )


def _truncate_tool_message(message: AnyMessage) -> AnyMessage:
    """只在模型视图中截断过长的纯文本 ToolMessage。"""
    if not isinstance(message, ToolMessage):
        return message
    if not isinstance(message.content, str):
        return message
    if len(message.content) <= TOOL_MESSAGE_MAX_CHARS:
        return message
    return message.model_copy(
        update={
            "content": (
                message.content[:TOOL_MESSAGE_MAX_CHARS]
                + TOOL_MESSAGE_TRUNCATION_NOTICE
            )
        }
    )


def _inject_selected_images(
    messages: list[AnyMessage],
    state: AgentState,
    *,
    thread_id: str | None,
    event_log_service: EventLogService,
) -> list[AnyMessage]:
    prepare = state.get("prepare")
    if not prepare or not prepare["selected_attachment_ids"]:
        return messages

    input_message_id = prepare["input_message_id"]
    target_index = next(
        (
            index
            for index, message in enumerate(messages)
            if isinstance(message, HumanMessage) and message.id == input_message_id
        ),
        None,
    )
    if target_index is None:
        raise ValueError(
            f"找不到本轮输入消息：{input_message_id}，无法注入图片"
        )

    image_blocks: list[dict[str, str]] = []
    seen_attachment_ids: set[str] = set()
    for attachment_id in prepare["selected_attachment_ids"]:
        if attachment_id in seen_attachment_ids:
            continue
        seen_attachment_ids.add(attachment_id)
        attachment = state["attachments"].get(attachment_id)
        if attachment is None:
            raise ValueError(f"State 中找不到附件：{attachment_id}")
        if not attachment["mime_type"].startswith("image/"):
            raise ValueError(f"当前附件不是图片：{attachment_id}")
        image_blocks.append(
            {
                "type": "image",
                "base64": _load_attachment_base64(
                    attachment_id=attachment_id,
                    path=attachment["url"],
                    thread_id=thread_id,
                    event_log_service=event_log_service,
                ),
                "mime_type": attachment["mime_type"],
                "id": attachment_id,
            }
        )

    target = messages[target_index]
    if isinstance(target.content, str):
        content: list[dict[str, Any]] = []
        if target.content:
            content.append({"type": "text", "text": target.content})
    else:
        content = [dict(block) for block in target.content]
    content.extend(image_blocks)

    result = list(messages)
    result[target_index] = target.model_copy(update={"content": content})
    return result


def _load_attachment_base64(
    *,
    attachment_id: str,
    path: str,
    thread_id: str | None,
    event_log_service: EventLogService,
) -> str:
    attachment_path = Path(path).expanduser()
    if attachment_path.is_file():
        return base64.b64encode(attachment_path.read_bytes()).decode("ascii")

    if thread_id is not None:
        event = event_log_service.find_attachment_event(thread_id, attachment_id)
        if event is not None:
            return event["payload"]["base64_data"]

    raise FileNotFoundError(
        f"附件路径失效且无法从 JSONL 回源：{attachment_id} ({path})"
    )
