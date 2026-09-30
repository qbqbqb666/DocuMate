import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_chunk_to_message,
)
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from src.backend.agent.context import (
    AgentContext,
    PermissionMode,
    build_model_context,
    permission_description,
    summarize_state_messages,
    write_status,
)
from src.backend.agent.document import DOCUMENT_TOOL_NAMES
from src.backend.agent.model_resolver import model_resolver
from src.backend.agent.path_policy import external_tool_paths, resolve_tool_paths
from src.backend.agent.prompts import (
    PROMPT_FILE_NAME,
    build_system_prompt,
    load_prompt_file,
)
from src.backend.agent.state import AgentState
from src.backend.agent.tools import (
    ALL_MUTATING_TOOLS,
    ALL_READ_ONLY_TOOLS,
    ALL_TOOLS,
)
from src.backend.services.recorder import extract_execution_metadata
from src.backend.services.cancellation import RunCancelledError
from src.backend.services.workspace_lock import workspace_lock


tools = ALL_TOOLS


READ_ONLY_TOOL_NAMES = frozenset(tool.name for tool in ALL_READ_ONLY_TOOLS)
MUTATING_TOOL_NAMES = frozenset(tool.name for tool in ALL_MUTATING_TOOLS)
MAX_TOOL_ROUNDS = 8
REPEATED_FAILURE_WARNING_AT = 2


def prepare_node(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict:
    """校验本轮输入并生成稳定的系统提示词快照。"""
    write_status(runtime, stage="context", message="正在准备模型上下文")
    workspace_path = Path(runtime.context.workspace_path).expanduser().resolve()
    if not workspace_path.exists():
        raise ValueError(f"工作区不存在：{workspace_path}")
    if not workspace_path.is_dir():
        raise ValueError(f"工作区不是文件夹：{workspace_path}")
    for accessible in runtime.context.accessible_paths:
        accessible_path = Path(accessible).expanduser().resolve()
        if not accessible_path.is_dir():
            raise ValueError(f"可访问文件夹不存在：{accessible_path}")

    prepare = _validate_turn_input(state)
    global_prompt = load_prompt_file(runtime.context.global_prompt_path)
    workspace_prompt = load_prompt_file(
        workspace_path / ".documate" / PROMPT_FILE_NAME
    )
    system_prompt = build_system_prompt(
        workspace_path=str(workspace_path),
        accessible_paths=runtime.context.accessible_paths,
        permission_description=permission_description(runtime.context.permission),
        global_instructions=global_prompt.content if global_prompt else None,
        workspace_instructions=(
            workspace_prompt.content if workspace_prompt else None
        ),
    )
    return {
        "prepare": {
            **prepare,
            "workspace_path": str(workspace_path),
            "instructions": {
                "system_prompt": system_prompt,
                "global_source": _prompt_source(global_prompt),
                "workspace_source": _prompt_source(workspace_prompt),
            },
        }
    }


def _validate_turn_input(state: AgentState) -> dict[str, Any]:
    prepare = state.get("prepare")
    if not isinstance(prepare, dict):
        raise ValueError("当前 turn 缺少 prepare 基础信息")

    turn_number = prepare.get("turn_number")
    if (
        isinstance(turn_number, bool)
        or not isinstance(turn_number, int)
        or turn_number < 1
    ):
        raise ValueError("prepare.turn_number 必须是正整数")
    input_message_id = prepare.get("input_message_id")
    if not isinstance(input_message_id, str) or not input_message_id.strip():
        raise ValueError("prepare.input_message_id 必须是非空字符串")
    if not any(
        isinstance(message, HumanMessage) and message.id == input_message_id
        for message in state.get("messages", [])
    ):
        raise ValueError(f"找不到本轮输入消息：{input_message_id}")

    selected = prepare.get("selected_attachment_ids")
    if not isinstance(selected, list) or any(
        not isinstance(attachment_id, str) or not attachment_id
        for attachment_id in selected
    ):
        raise ValueError("prepare.selected_attachment_ids 必须是字符串数组")
    attachments = state.get("attachments", {})
    for attachment_id in selected:
        attachment = attachments.get(attachment_id)
        if not isinstance(attachment, dict):
            raise ValueError(f"State 中找不到附件：{attachment_id}")
        _validate_selected_attachment(attachment_id, attachment)
    return {
        "turn_number": turn_number,
        "input_message_id": input_message_id,
        "selected_attachment_ids": list(selected),
    }


def _validate_selected_attachment(
    attachment_id: str,
    attachment: dict[str, Any],
) -> None:
    string_fields = ("attachment_id", "message_id", "name", "mime_type", "url")
    for field in string_fields:
        value = attachment.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"附件 {attachment_id} 缺少有效字段：{field}")
    if attachment["attachment_id"] != attachment_id:
        raise ValueError(f"附件 ID 与 State 索引不一致：{attachment_id}")
    if not attachment["mime_type"].startswith("image/"):
        raise ValueError(f"当前附件不是图片：{attachment_id}")
    size = attachment.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError(f"附件 {attachment_id} 缺少有效字段：size")


def _prompt_source(prompt: Any) -> dict[str, str] | None:
    if prompt is None:
        return None
    return {"path": prompt.path, "sha256": prompt.sha256}


def summarize_node(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict:
    """在模型调用前按 Token 阈值压缩并持久更新消息 State。"""
    write_status(runtime, stage="summary", message="正在检查上下文长度")
    resolved = model_resolver.resolve(
        runtime.context.provider,
        runtime.context.model_name,
    )
    return summarize_state_messages(state, runtime, resolved.summarizer)


def model_node(
    state: AgentState,
    config: RunnableConfig,
    runtime: Runtime[AgentContext],
) -> dict:
    """调用模型，并把模型回复追加到 messages。"""
    write_status(runtime, stage="model", message="正在请求模型")
    resolved = model_resolver.resolve(
        runtime.context.provider,
        runtime.context.model_name,
    )
    configurable = config.get("configurable", {})
    configured_thread_id = configurable.get("thread_id")
    thread_id = configured_thread_id if isinstance(configured_thread_id, str) else None
    messages = build_model_context(
        state,
        runtime,
        thread_id=thread_id,
    )
    force_final_response = bool(
        (state.get("tool_loop") or {}).get("force_final_response")
    )
    if force_final_response:
        messages = _force_final_response_context(messages)
    available_tools = [] if force_final_response else tools
    recorder = runtime.context.recorder
    handle = None
    if recorder:
        handle = recorder.model_started(
            provider=resolved.provider.value,
            model=resolved.model_name,
            messages=messages,
            tools=[
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.args,
                }
                for tool in available_tools
            ],
            parameters={
                "temperature": getattr(resolved.model, "temperature", None)
            },
            execution=extract_execution_metadata(runtime),
        )
    try:
        model = resolved.model if force_final_response else resolved.model_with_tools
        response_chunk = None
        stream = model.stream(messages, config=config)
        try:
            for chunk in stream:
                runtime.context.cancellation.raise_if_cancelled()
                response_chunk = (
                    chunk if response_chunk is None else response_chunk + chunk
                )
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()
        runtime.context.cancellation.raise_if_cancelled()
        response = (
            message_chunk_to_message(response_chunk)
            if response_chunk is not None
            else AIMessage(content="")
        )
    except BaseException as error:
        if recorder and handle:
            recorder.model_failed(handle, error)
        raise
    if force_final_response and getattr(response, "tool_calls", []):
        update: dict[str, Any] = {"tool_calls": []}
        if not response.content:
            update["content"] = (
                "本轮工具调用已达到上限，无法继续执行。"
                "请调整请求或补充信息后重试。"
            )
        response = response.model_copy(update=update)
    if _is_blank_model_response(response):
        error = RuntimeError(
            "模型返回了空响应；请重试，或在个人中心切换其他对话模型"
        )
        if recorder and handle:
            recorder.model_failed(handle, error)
        raise error
    if recorder and handle:
        recorder.model_succeeded(
            handle,
            response=response,
            usage=response.usage_metadata,
        )
        response = recorder.message_created(response)
    return {"messages": [response]}


def _is_blank_model_response(response: Any) -> bool:
    content = getattr(response, "content", None)
    blank_content = not content.strip() if isinstance(content, str) else not content
    return blank_content and not getattr(response, "tool_calls", [])


def _force_final_response_context(messages: list[Any]) -> list[Any]:
    instruction = (
        "\n\n[工具循环限制]\n"
        "本轮已达到工具调用轮数上限。不要再调用工具；"
        "请直接说明已完成的内容、失败原因和需要用户补充的信息。"
    )
    result = list(messages)
    if result and isinstance(result[0], SystemMessage):
        result[0] = result[0].model_copy(
            update={"content": f"{result[0].content}{instruction}"}
        )
    return result


def route_after_model(
    state: AgentState,
) -> Literal["finalize", "approval"]:
    """根据模型回复类型决定下一节点。"""
    latest_message = state["messages"][-1]
    tool_calls = getattr(latest_message, "tool_calls", [])
    if (state.get("tool_loop") or {}).get("force_final_response"):
        return "finalize"
    if not tool_calls:
        return "finalize"

    return "approval"


def approval_node(
    state: AgentState,
    runtime: Runtime[AgentContext],
) -> dict[str, Any]:
    """按模型生成顺序审批修改操作和项目外路径，不在本节点执行工具。"""
    write_status(runtime, stage="approval", message="正在检查工具权限")
    latest = state["messages"][-1]
    if not isinstance(latest, AIMessage) or not latest.tool_calls:
        raise ValueError("approval 节点未找到待处理的工具调用")
    if not latest.id:
        raise ValueError("待审批的 AIMessage 缺少 message_id")

    decisions: dict[str, Literal["execute", "deny"]] = {}
    path_grants: dict[str, list[str]] = {}
    for call in latest.tool_calls:
        tool_call_id = call["id"]
        name = call["name"]
        if tool_call_id in decisions:
            raise ValueError(f"工具调用 ID 重复：{tool_call_id}")
        if name not in READ_ONLY_TOOL_NAMES | MUTATING_TOOL_NAMES:
            decisions[tool_call_id] = "deny"
            continue
        paths = resolve_tool_paths(runtime.context, name, call["args"])
        external_paths = external_tool_paths(runtime.context, paths)
        if runtime.context.permission == PermissionMode.FULL_ACCESS:
            decisions[tool_call_id] = "execute"
            continue
        if not external_paths and name in READ_ONLY_TOOL_NAMES:
            decisions[tool_call_id] = "execute"
            continue

        write_status(
            runtime,
            stage="approval",
            message=(
                "正在等待项目外路径授权"
                if external_paths
                else "正在等待批准"
            ),
            tool_call_id=tool_call_id,
            tool_name=name,
        )
        response = interrupt(
            {
                "type": "tool_approval",
                "tool_call_id": tool_call_id,
                "name": name,
                "args": call["args"],
                "reason": "external_path" if external_paths else "mutation",
                "paths": [
                    item.as_dict()
                    for item in (external_paths if external_paths else paths)
                ],
            }
        )
        decision = _approval_decision(
            response,
            expected_tool_call_id=tool_call_id,
        )
        decisions[tool_call_id] = decision
        if decision == "execute" and external_paths:
            path_grants[tool_call_id] = [item.path for item in external_paths]

    plan: dict[str, Any] = {
        "source_message_id": latest.id,
        "decisions": decisions,
    }
    if path_grants:
        plan["path_grants"] = path_grants
    return {"tool_execution_plan": plan}


def _approval_decision(
    response: Any,
    *,
    expected_tool_call_id: str,
) -> Literal["execute", "deny"]:
    if not isinstance(response, dict):
        raise ValueError("审批结果必须是对象")
    if response.get("tool_call_id") != expected_tool_call_id:
        raise ValueError("审批结果与当前工具调用不匹配")
    decision = response.get("decision")
    if decision == "allow":
        return "execute"
    if decision == "deny":
        return "deny"
    raise ValueError("审批决定必须是 allow 或 deny")


def route_after_approval(state: AgentState) -> Literal["tools", "document"]:
    """根据已审批批次中的工具类型选择执行节点。"""
    plan = state.get("tool_execution_plan")
    if not plan:
        raise ValueError("审批后缺少 tool_execution_plan")
    latest = next(
        (
            message
            for message in reversed(state["messages"])
            if isinstance(message, AIMessage)
            and message.id == plan["source_message_id"]
        ),
        None,
    )
    if latest is None:
        raise ValueError("找不到执行计划对应的 AIMessage")
    if any(call["name"] in DOCUMENT_TOOL_NAMES for call in latest.tool_calls):
        return "document"
    return "tools"


def document_node(
    state: AgentState,
    config: RunnableConfig,
    runtime: Runtime[AgentContext],
) -> dict:
    """在工作区锁内执行包含专业文档工具的已审批批次。"""
    runtime.context.cancellation.raise_if_cancelled()
    lock = workspace_lock(runtime.context.workspace_path)
    with lock:
        return _execute_tool_plan(state, config, runtime)


def finalize_node(state: AgentState) -> dict:
    """校验 Graph 终态并生成统一的本轮完成结果。"""
    if state.get("tool_execution_plan") is not None:
        raise ValueError("finalize 时仍存在未清理的工具执行计划")
    latest = state["messages"][-1] if state.get("messages") else None
    if not isinstance(latest, AIMessage):
        raise ValueError("finalize 未找到最终 AIMessage")
    if not latest.id:
        raise ValueError("最终 AIMessage 缺少 message_id")
    if latest.tool_calls:
        raise ValueError("最终 AIMessage 仍包含未处理的工具调用")

    tool_loop = state.get("tool_loop") or {}
    tool_call_ids = set(tool_loop.get("tool_call_ids", []))
    artifact_ids = [
        artifact_id
        for artifact_id, artifact in state.get("artifacts", {}).items()
        if artifact["tool_call_id"] in tool_call_ids
    ]
    return {
        "finalization": {
            "status": "completed",
            "message": {
                "message_id": latest.id,
                "role": "assistant",
                "content": _message_content_text(latest.content),
            },
            "tools": {
                "total": int(tool_loop.get("total_calls", 0)),
                "succeeded": int(tool_loop.get("succeeded_calls", 0)),
                "failed": int(tool_loop.get("failed_calls", 0)),
                "denied": int(tool_loop.get("denied_calls", 0)),
                "rounds": int(tool_loop.get("round_count", 0)),
                "limit_reached": bool(
                    tool_loop.get("force_final_response", False)
                ),
            },
            "artifact_ids": artifact_ids,
        }
    }


def _message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(
        content,
        ensure_ascii=False,
        separators=(",", ":"),
    )


_tool_executor = ToolNode(tools)


def tool_node(
    state: AgentState,
    config: RunnableConfig,
    runtime: Runtime[AgentContext],
) -> dict:
    """在工作区锁内按原始顺序执行当前工具批次。"""
    runtime.context.cancellation.raise_if_cancelled()
    lock = workspace_lock(runtime.context.workspace_path)
    with lock:
        return _execute_tool_plan(state, config, runtime)


def _execute_tool_plan(
    state: AgentState,
    config: RunnableConfig,
    runtime: Runtime[AgentContext],
) -> dict:
    plan = state.get("tool_execution_plan")
    if not plan:
        raise ValueError("工具节点缺少 tool_execution_plan")
    latest = next(
        (
            message
            for message in reversed(state["messages"])
            if isinstance(message, AIMessage)
            and message.id == plan["source_message_id"]
        ),
        None,
    )
    if latest is None:
        raise ValueError("找不到执行计划对应的 AIMessage")
    calls = latest.tool_calls
    recorder = runtime.context.recorder
    normalized_messages: list[ToolMessage] = []
    artifacts: dict[str, Any] = {}
    previous_loop = state.get("tool_loop") or {}
    round_count = int(previous_loop.get("round_count", 0)) + 1
    failure_counts = dict(previous_loop.get("failure_counts", {}))
    total_calls = int(previous_loop.get("total_calls", 0))
    succeeded_calls = int(previous_loop.get("succeeded_calls", 0))
    failed_calls = int(previous_loop.get("failed_calls", 0))
    denied_calls = int(previous_loop.get("denied_calls", 0))
    tool_call_ids = list(previous_loop.get("tool_call_ids", []))
    for call in calls:
        runtime.context.cancellation.raise_if_cancelled()
        total_calls += 1
        tool_call_ids.append(call["id"])
        decision = plan["decisions"].get(call["id"])
        if decision is None:
            raise ValueError(f"执行计划缺少工具调用：{call['id']}")
        if decision == "deny":
            denied_calls += 1
            error_code = (
                "unknown_tool"
                if call["name"] not in READ_ONLY_TOOL_NAMES | MUTATING_TOOL_NAMES
                else "approval_denied"
            )
            message = _tool_result_message(
                call,
                status="denied",
                error={
                    "code": error_code,
                    "message": (
                        "未知工具，程序已拒绝执行"
                        if error_code == "unknown_tool"
                        else "该工具调用未获批准"
                    ),
                    "retryable": False,
                },
            )
            if recorder:
                message = recorder.message_created(message)
            normalized_messages.append(message)
            continue
        if decision != "execute":
            raise ValueError(f"无效的工具执行决策：{decision}")

        write_status(
            runtime,
            stage="tool",
            message=(
                "正在读取文件"
                if call["name"] in READ_ONLY_TOOL_NAMES
                else "正在执行工具"
            ),
            tool_call_id=call["id"],
            tool_name=call["name"],
        )
        handle = recorder.tool_started(
            tool_call_id=call["id"],
            name=call["name"],
            args=call["args"],
            execution=extract_execution_metadata(runtime),
        ) if recorder else None
        filtered_message = latest.model_copy(update={"tool_calls": [call]})
        execution_state = {
            **state,
            "messages": [*state["messages"][:-1], filtered_message],
        }
        try:
            result = _tool_executor.invoke(execution_state, config)
            runtime.context.cancellation.raise_if_cancelled()
        except RunCancelledError:
            raise
        except Exception as error:
            failed_calls += 1
            if recorder and handle:
                recorder.tool_failed(handle, name=call["name"], error=error)
            message, failure_counts = _failed_tool_message(
                call,
                error,
                failure_counts,
            )
            if recorder:
                message = recorder.message_created(message)
            normalized_messages.append(message)
            continue
        messages: list[ToolMessage] = result.get("messages", [])
        if len(messages) != 1:
            raise RuntimeError("单个工具调用未返回唯一 ToolMessage")
        message = messages[0]
        parsed_result = _parse_tool_result(message.content)
        if message.status == "error":
            failed_calls += 1
            error = RuntimeError(str(message.content))
            if recorder and handle:
                recorder.tool_failed(
                    handle,
                    name=call["name"],
                    error=error,
                )
            message, failure_counts = _failed_tool_message(
                call,
                error,
                failure_counts,
                message_id=message.id,
            )
        else:
            succeeded_calls += 1
            if recorder and handle:
                recorder.tool_succeeded(
                    handle,
                    name=call["name"],
                    result=parsed_result,
                )
            message = _tool_result_message(
                call,
                status="success",
                data=parsed_result,
                message_id=message.id,
            )
        if recorder:
            message = recorder.message_created(message)
        normalized_messages.append(message)

        produced_artifacts = (
            _artifacts_from_tool_result(call, parsed_result)
            if message.status == "success"
            else []
        )
        for artifact in produced_artifacts:
            artifacts[artifact["artifact_id"]] = artifact
            if recorder:
                recorder.artifact_recorded(**artifact)

    output: dict[str, Any] = {
        "messages": normalized_messages,
        "tool_execution_plan": None,
        "tool_loop": {
            "round_count": round_count,
            "failure_counts": failure_counts,
            "force_final_response": round_count >= MAX_TOOL_ROUNDS,
            "total_calls": total_calls,
            "succeeded_calls": succeeded_calls,
            "failed_calls": failed_calls,
            "denied_calls": denied_calls,
            "tool_call_ids": tool_call_ids,
        },
    }
    if artifacts:
        output["artifacts"] = artifacts
    return output


def _tool_result_message(
    call: dict[str, Any],
    *,
    status: Literal["success", "error", "denied"],
    data: Any = None,
    error: dict[str, Any] | None = None,
    message_id: str | None = None,
) -> ToolMessage:
    payload = {
        "ok": status == "success",
        "status": status,
        "tool_call_id": call["id"],
        "tool": call["name"],
        "data": data if status == "success" else None,
        "error": error,
    }
    return ToolMessage(
        id=message_id or str(uuid4()),
        tool_call_id=call["id"],
        status="success" if status == "success" else "error",
        content=json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


def _failed_tool_message(
    call: dict[str, Any],
    error: Exception,
    failure_counts: dict[str, int],
    *,
    message_id: str | None = None,
) -> tuple[ToolMessage, dict[str, int]]:
    error_code = _tool_error_code(error)
    signature = _failure_signature(call, error_code)
    updated_counts = dict(failure_counts)
    attempts = updated_counts.get(signature, 0) + 1
    updated_counts[signature] = attempts
    strategy_change_required = attempts >= REPEATED_FAILURE_WARNING_AT
    message = str(error) or type(error).__name__
    if strategy_change_required:
        message = (
            f"{message}。相同方案在本轮已失败 {attempts} 次，"
            "请更换工具、路径或处理方式，不要重复相同调用"
        )
    return (
        _tool_result_message(
            call,
            status="error",
            error={
                "code": error_code,
                "message": message,
                "retryable": not strategy_change_required,
                "attempts": attempts,
                "strategy_change_required": strategy_change_required,
            },
            message_id=message_id,
        ),
        updated_counts,
    )


def _tool_error_code(error: Exception) -> str:
    if isinstance(error, FileNotFoundError):
        return "file_not_found"
    if isinstance(error, FileExistsError):
        return "already_exists"
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, UnicodeError):
        return "invalid_encoding"
    if isinstance(error, ValueError):
        return "invalid_operation"
    if isinstance(error, OSError):
        return "io_error"
    return "tool_execution_error"


def _failure_signature(call: dict[str, Any], error_code: str) -> str:
    serialized = json.dumps(
        {
            "tool": call["name"],
            "args": call["args"],
            "error_code": error_code,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_tool_result(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def _artifacts_from_tool_result(
    call: dict[str, Any],
    result: Any,
) -> list[dict[str, Any]]:
    if not isinstance(result, dict):
        return []
    declared = result.get("artifacts")
    if isinstance(declared, list):
        artifacts: list[dict[str, Any]] = []
        for item in declared:
            if not isinstance(item, dict):
                continue
            url = item.get("path")
            operation = item.get("operation", "created")
            if not isinstance(url, str) or operation not in {"created", "modified"}:
                continue
            artifacts.append(_build_artifact(call, url, operation))
        return artifacts
    name = call["name"]
    if name == "write_text_file":
        url = result.get("path")
        operation = "modified" if result.get("overwritten") else "created"
    elif name == "replace_text_in_file":
        url = result.get("path")
        operation = "modified"
    elif name == "copy_file":
        url = result.get("destination")
        operation = "created"
    elif name in {"move_file", "rename_file"}:
        url = result.get("destination")
        operation = "modified"
    else:
        return []
    if not isinstance(url, str):
        return []
    return [_build_artifact(call, url, operation)]


def _build_artifact(
    call: dict[str, Any],
    url: str,
    operation: Literal["created", "modified"],
) -> dict[str, Any]:
    return {
        "artifact_id": str(uuid4()),
        "name": Path(url).name,
        "mime_type": mimetypes.guess_type(url)[0] or "application/octet-stream",
        "url": url,
        "operation": operation,
        "tool_call_id": call["id"],
    }
