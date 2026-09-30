from collections.abc import Mapping
from typing import Annotated, Literal, NotRequired, TypeVar, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ImageAttachment(TypedDict):
    """用户消息关联的外部本地图片。"""

    attachment_id: str
    message_id: str
    name: str
    mime_type: str
    url: str
    size: int


class Artifact(TypedDict):
    """Agent 通过工具创建或修改的文件。"""

    artifact_id: str
    name: str
    mime_type: str
    url: str
    operation: Literal["created", "modified"]
    tool_call_id: str


class PreparedPromptSource(TypedDict):
    """本轮已读取的外部提示词来源。"""

    path: str
    sha256: str


class PreparedInstructions(TypedDict):
    """本轮固定使用的系统提示词快照。"""

    system_prompt: str
    global_source: PreparedPromptSource | None
    workspace_source: PreparedPromptSource | None


class PrepareResult(TypedDict):
    """prepare 节点为当前轮次生成的结果。"""

    turn_number: int
    input_message_id: str
    selected_attachment_ids: list[str]
    # Coordinator 传入的基础 prepare 和旧 checkpoint/JSONL 重建结果
    # 不含以下字段；prepare_node 在新 turn 开始时补齐它们。
    workspace_path: NotRequired[str]
    instructions: NotRequired[PreparedInstructions]


class ToolExecutionPlan(TypedDict):
    """当前 AIMessage 中每个工具调用的临时执行决策。"""

    source_message_id: str
    decisions: dict[str, Literal["execute", "deny"]]
    path_grants: NotRequired[dict[str, list[str]]]


class ToolLoopState(TypedDict):
    """当前 turn 的工具循环和重复失败计数。"""

    round_count: int
    failure_counts: dict[str, int]
    force_final_response: bool
    total_calls: NotRequired[int]
    succeeded_calls: NotRequired[int]
    failed_calls: NotRequired[int]
    denied_calls: NotRequired[int]
    tool_call_ids: NotRequired[list[str]]


class FinalMessageResult(TypedDict):
    """对外返回前已标准化的最终助手消息。"""

    message_id: str
    role: Literal["assistant"]
    content: str


class FinalToolSummary(TypedDict):
    """当前 turn 的工具执行摘要。"""

    total: int
    succeeded: int
    failed: int
    denied: int
    rounds: int
    limit_reached: bool


class FinalizationResult(TypedDict):
    """finalize 节点产生的 Graph 统一终态。"""

    status: Literal["completed"]
    message: FinalMessageResult
    tools: FinalToolSummary
    artifact_ids: list[str]


Record = TypeVar("Record")


def merge_records(
    current: Mapping[str, Record] | None,
    updates: Mapping[str, Record] | None,
) -> dict[str, Record]:
    """按记录 ID 合并字典；同一 ID 使用最新值。"""
    return {**(current or {}), **(updates or {})}


class AgentState(TypedDict):
    """Agent 图在节点之间传递的状态。"""

    messages: Annotated[list[AnyMessage], add_messages]
    attachments: Annotated[
        dict[str, ImageAttachment],
        merge_records,
    ]
    artifacts: Annotated[
        dict[str, Artifact],
        merge_records,
    ]
    prepare: PrepareResult | None
    tool_execution_plan: ToolExecutionPlan | None
    tool_loop: ToolLoopState | None
    finalization: FinalizationResult | None
