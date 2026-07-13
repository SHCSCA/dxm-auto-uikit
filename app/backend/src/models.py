from typing import Any
from pydantic import BaseModel, Field


class RuntimeIdentityResponse(BaseModel):
    schemaVersion: str
    instanceId: str
    gitHead: str
    gitDirty: bool
    buildId: str
    packageVersion: str
    packageSha256: str | None
    backendPid: int
    browserAgentPid: int
    browserExecutionModel: str
    dataDir: str
    workflowProfileDir: str
    resourceRoot: str
    startedAt: str
    fingerprint: str


class HealthResponse(BaseModel):
    status: str
    instanceId: str
    runtimeIdentity: RuntimeIdentityResponse


class StoreCreate(BaseModel):
    name: str
    platform: str = "AliExpress"


class TemplateCreate(BaseModel):
    template_type: str
    template_name: str
    binding_scope: str
    payload: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class TemplateUpdate(BaseModel):
    template_type: str | None = None
    template_name: str | None = None
    binding_scope: str | None = None
    payload: dict[str, Any] | None = None
    is_enabled: bool | None = None


class ProductCreate(BaseModel):
    title: str
    category_name: str = "未分类"
    price: float = 0
    currency: str = "USD"
    sku_count: int = 1
    image_count: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class AcquisitionClaimRequest(BaseModel):
    store_id: int
    source_url: str | None = None
    keyword: str | None = None
    category_name: str | None = None
    claim_mark: str
    template_id: int | None = None


class TaskCreate(BaseModel):
    name: str
    store_id: int | None = None
    mode: str = "single_save"
    publish_scene: str = "SMT_SEMI_MANAGED_SAVE_ONLY"
    product_ids: list[int] = Field(default_factory=list)
    claim_mark: str = "AI认领"
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskStartRequest(BaseModel):
    manual_approval: bool = False
    approval_token: str | None = None
    approved_by: str | None = None
    confirmation: str | None = None


class TaskManualApprovalRequest(BaseModel):
    approved_by: str
    confirmation: str


class TaskConfigOverrideRequest(BaseModel):
    section: str
    values: dict[str, Any] = Field(default_factory=dict)


class RuntimeControlRequest(BaseModel):
    action: str
    task_id: int | None = None


class AgentConsoleStep(BaseModel):
    title: str | None = None
    label: str | None = None
    state: str | None = None
    code: str | None = None
    action: str | None = None
    detail: str | None = None
    line1: str | None = None
    line2: str | None = None
    next_step: str | None = None
    store_name: str | None = None
    guard: str | None = None
    phase: str | None = None
    progress_index: int | None = None
    progress_total: int | None = None
    severity: str | None = None
    human_title: str | None = None
    human_action: str | None = None
    human_next: str | None = None
    recent_actions: list[str] | None = None
    requires_user_action: bool | None = None
    maintenance_detail: str | None = None


class AgentConsoleStartRequest(BaseModel):
    task_id: int | None = None
    target_url: str | None = None
    launch_browser: bool = True
    step: AgentConsoleStep | None = None


class AgentConsoleBrowserDiagnosticsRequest(BaseModel):
    target_url: str | None = None
    launch_browser: bool = False


class AgentConsoleHudRequest(BaseModel):
    step: AgentConsoleStep = Field(default_factory=AgentConsoleStep)


class AgentConsoleControlRequest(BaseModel):
    action: str
    x: int | None = None
    y: int | None = None
    selector: str | None = None
    text: str | None = None
    key: str | None = None
    url: str | None = None
    delta_x: int = 0
    delta_y: int = 0


class ProductImportRequest(BaseModel):
    rows: list[dict[str, Any]]


class LoginStartRequest(BaseModel):
    username: str
    password: str


class LoginContinueRequest(BaseModel):
    confirm: bool = True


class LoginNavigateRequest(BaseModel):
    target: str


class DraftBoxActionRequest(BaseModel):
    action: str
    note_text: str | None = None
    product_query: str | None = None
    store_name: str | None = None
    target_source_urls: list[str] = Field(default_factory=list)
    task_id: int | None = None
    manual_approval: bool = False
    approval_token: str | None = None
    approved_by: str | None = None
    confirmation: str | None = None


class SelectorProfileValidateRequest(BaseModel):
    url: str
    body_text: str = ""
    visible_buttons: list[str] = Field(default_factory=list)


class AIConfigUpdateRequest(BaseModel):
    api_key: str
    model: str = 'deepseek-chat'


class TitleGenerateRequest(BaseModel):
    source_title: str
    title_style: str = 'clear, searchable, non-hype'
    max_length: int = 110
