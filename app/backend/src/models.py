from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt


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
    model_config = ConfigDict(extra="forbid")

    template_type: str | None = None
    template_name: str | None = None
    binding_scope: str | None = None
    payload: dict[str, Any] | None = None
    is_enabled: bool | None = None


class DraftBoxScopeSnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_items: StrictInt = Field(ge=1, le=100)


class EditBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_snapshot_id: StrictInt = Field(gt=0)
    template_id: StrictInt = Field(gt=0)


class EditBatchManualApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1, max_length=200)
    confirmation: str = Field(min_length=1, max_length=64)


class EditBatchApproveAndStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1, max_length=200)
    confirmation: str = Field(min_length=1, max_length=64)


class EditBatchStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_token: str = Field(min_length=1, max_length=256)


class EditBatchStopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_by: str = Field(min_length=1, max_length=200, pattern=r".*\S.*")
    reason: str | None = Field(default=None, max_length=500)


class EditBatchBundleSourceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_id: StrictInt = Field(gt=0)
    source_digest: str = Field(pattern=r"^[0-9A-Fa-f]{64}$")


class EditBatchBundleSectionTemplates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: EditBatchBundleSourceSelection
    sku: EditBatchBundleSourceSelection
    pricing: EditBatchBundleSourceSelection
    logistics: EditBatchBundleSourceSelection
    image: EditBatchBundleSourceSelection
    compliance: EditBatchBundleSourceSelection
    semi_managed: EditBatchBundleSourceSelection
    dxm_reference: EditBatchBundleSourceSelection


class EditBatchBundleComposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_name: str = Field(min_length=1, max_length=120, pattern=r".*\S.*")
    version: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$",
    )
    store_id: StrictInt = Field(gt=0)
    category_name: str | None = Field(default=None, max_length=200)
    section_templates: EditBatchBundleSectionTemplates


class ProductCreate(BaseModel):
    title: str
    category_name: str = "未分类"
    price: float = 0
    currency: str = "USD"
    sku_count: int = 1
    image_count: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class AcquisitionClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: StrictInt = Field(gt=0)
    source_url: str = Field(min_length=1, max_length=2048, pattern=r".*\S.*")
    keyword: str | None = Field(default=None, max_length=300)
    category_name: str | None = Field(default=None, max_length=200)
    claim_mark: str = Field(min_length=1, max_length=200, pattern=r".*\S.*")
    template_id: StrictInt | None = Field(default=None, gt=0)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200, pattern=r".*\S.*")
    store_id: StrictInt | None = Field(default=None, gt=0)
    mode: Literal["probe", "dry_run", "claim_only", "single_save", "batch_save"] = "single_save"
    publish_scene: str = Field(
        default="SMT_SEMI_MANAGED_SAVE_ONLY",
        min_length=1,
        max_length=64,
    )
    product_ids: list[StrictInt] = Field(default_factory=list, max_length=100)
    claim_mark: str = Field(default="AI认领", min_length=1, max_length=200, pattern=r".*\S.*")
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_approval: bool = False
    approval_token: str | None = Field(default=None, max_length=256)
    approved_by: str | None = Field(default=None, max_length=200)
    confirmation: str | None = Field(default=None, max_length=64)


class TaskManualApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1, max_length=200, pattern=r".*\S.*")
    confirmation: str = Field(min_length=1, max_length=64)


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
