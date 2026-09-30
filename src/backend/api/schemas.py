from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    """对外 API 数据模型的统一基类。"""

    model_config = ConfigDict(extra="forbid")


class SaveApiKeyRequest(ApiModel):
    api_key: str = Field(min_length=1)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("API Key 不能为空")
        return value.strip()


class InternalTokenRequest(ApiModel):
    access_token: str = Field(min_length=1)
    username: str | None = None


class ApiKeyStatusResponse(ApiModel):
    provider: Literal["siliconflow", "deepseek"]
    configured: bool
    last4: str | None


class CreateThreadRequest(ApiModel):
    workspace_path: str = Field(min_length=1)
    project_id: str | None = None

    @field_validator("workspace_path")
    @classmethod
    def validate_workspace_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workspace_path 不能为空")
        return value


class CreateThreadResponse(ApiModel):
    thread_id: str


class ThreadSummaryResponse(ApiModel):
    thread_id: str
    project_id: str | None = None
    title: str = "新对话"
    created_at: str
    updated_at: str
    last_turn_number: int
    message_count: int
    preview: str
    last_turn_status: Literal["running", "success", "error"] | None


class RenameThreadRequest(ApiModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("对话名称不能为空")
        return value.strip()


class CreateProjectRequest(ApiModel):
    name: str = Field(min_length=1, max_length=80)
    folder_paths: list[str] = Field(min_length=1)


class ProjectResponse(ApiModel):
    id: str
    name: str
    folder_paths: list[str]
    primary_path: str
    created_at: str
    is_active: bool = False


class PendingApprovalResponse(ApiModel):
    approval_id: str
    tool_call_id: str
    name: str
    args: dict[str, Any]
    reason: Literal["mutation", "external_path"] = "mutation"
    paths: list[dict[str, str]] = Field(default_factory=list)
    turn_number: int
    requested_at: str


class ThreadDetailResponse(ApiModel):
    thread_id: str
    project_id: str | None = None
    title: str | None = None
    created_at: str
    updated_at: str
    last_turn_number: int
    pending_approval: PendingApprovalResponse | None


class MessageResponse(ApiModel):
    message_id: str
    turn_number: int
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: list[dict[str, Any]] | None
    tool_call_id: str | None
    created_at: str


class MessageListResponse(ApiModel):
    messages: list[MessageResponse]


class ArtifactResponse(ApiModel):
    artifact_id: str
    turn_number: int
    name: str
    mime_type: str
    url: str
    operation: Literal["created", "modified"]
    tool_call_id: str
    created_at: str
    updated_at: str


class ArtifactListResponse(ApiModel):
    artifacts: list[ArtifactResponse]


class WorkspaceInfoResponse(ApiModel):
    path: str
    is_user_set: bool
    is_dev_default: bool
    documents_dir: str
    generated_dir: str
    vectors_dir: str
    config_file: str


class RecentWorkspaceResponse(ApiModel):
    path: str
    name: str
    exists: bool
    is_current: bool


class SwitchWorkspaceRequest(ApiModel):
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("工作区路径不能为空")
        return value


class SwitchWorkspaceResponse(ApiModel):
    info: WorkspaceInfoResponse


class AppSettingsResponse(ApiModel):
    trust_agent: bool
    provider: Literal["siliconflow", "deepseek"]
    model_name: str


class UpdateSettingsRequest(ApiModel):
    trust_agent: bool | None = None
    provider: Literal["siliconflow", "deepseek"] | None = None
    model_name: str | None = Field(default=None, min_length=1)

    @field_validator("model_name")
    @classmethod
    def validate_model_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("模型名称不能为空")
        return value


class ModelOptionResponse(ApiModel):
    provider: Literal["siliconflow", "deepseek"]
    model_name: str
    display_name: str
    max_input_tokens: int


class WorkspaceStatsResponse(ApiModel):
    document_count: int
    thread_count: int
    total_tokens: int


class DocumentResponse(ApiModel):
    id: str
    filename: str
    doc_type: Literal["docx", "pdf", "xlsx"]
    mime_type: str
    size_bytes: int
    char_count: int
    uploaded_at: str
    saved_path: str
    used_ocr: bool


class DocumentDetailResponse(DocumentResponse):
    text: str


class SearchRequest(ApiModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=20, ge=1, le=100)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("搜索内容不能为空")
        return value


class SearchHitResponse(ApiModel):
    chunk_id: str
    text: str
    doc_id: str
    doc_filename: str
    chunk_index: int


class SearchResponse(ApiModel):
    hits: list[SearchHitResponse]


class CreateTurnRequest(ApiModel):
    workspace_path: str = Field(min_length=1)
    project_id: str | None = None
    content: str = Field(min_length=1)
    referenced_attachment_ids: list[str] = Field(default_factory=list)
    permission: Literal["request_approval", "full_access"] = "request_approval"
    provider: Literal["siliconflow", "deepseek"] = "siliconflow"
    model_name: str = Field(default="Qwen/Qwen3.5-4B", min_length=1)
    run_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("workspace_path", "content", "model_name")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value

    @field_validator("referenced_attachment_ids")
    @classmethod
    def validate_attachment_ids(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("附件 ID 不能为空")
        return list(dict.fromkeys(values))


class ApprovalDecisionRequest(ApiModel):
    workspace_path: str = Field(min_length=1)
    project_id: str | None = None
    tool_call_id: str = Field(min_length=1)
    decision: Literal["allow", "deny"]
    run_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("workspace_path", "tool_call_id")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段不能为空")
        return value


class ApprovalResponse(ApiModel):
    approval_id: str
    tool_call_id: str
    name: str
    args: dict[str, Any]
    reason: Literal["mutation", "external_path"] = "mutation"
    paths: list[dict[str, str]] = Field(default_factory=list)


class FinalMessageResponse(ApiModel):
    message_id: str
    role: Literal["assistant"]
    content: str


class ToolSummaryResponse(ApiModel):
    total: int
    succeeded: int
    failed: int
    denied: int
    rounds: int
    limit_reached: bool


class FinalizationResponse(ApiModel):
    status: Literal["completed"]
    message: FinalMessageResponse
    tools: ToolSummaryResponse
    artifact_ids: list[str]


class ModelExecutionResponse(ApiModel):
    calls: int
    succeeded: int
    failed: int
    duration_ms: float
    input_tokens: int
    output_tokens: int
    total_tokens: int


class ToolExecutionResponse(ApiModel):
    total: int
    succeeded: int
    failed: int
    denied: int
    rounds: int
    limit_reached: bool
    duration_ms: float


class ApprovalExecutionResponse(ApiModel):
    requested: int
    allowed: int
    denied: int


class TurnExecutionResponse(ApiModel):
    duration_ms: float
    model: ModelExecutionResponse
    tools: ToolExecutionResponse
    approvals: ApprovalExecutionResponse


class TurnResultResponse(ApiModel):
    thread_id: str
    turn_number: int
    input_message_id: str
    status: Literal["completed", "awaiting_approval"]
    final_message_id: str | None
    approval: ApprovalResponse | None
    finalization: FinalizationResponse | None
    execution: TurnExecutionResponse | None


class StatusEventResponse(ApiModel):
    stage: Literal["context", "model", "approval", "tool", "summary"]
    message: str
    tool_call_id: str | None = None
    tool_name: str | None = None


class ModelChunkEventResponse(ApiModel):
    text: str
    message_id: str | None = None
    node: str | None = None


class ApprovalEventResponse(ApiModel):
    approval: ApprovalResponse
    turn: TurnResultResponse


class ErrorDetail(ApiModel):
    code: str
    message: str
    error_type: str | None = None
    details: list[dict[str, Any]] | None = None


class ErrorResponse(ApiModel):
    error: ErrorDetail
