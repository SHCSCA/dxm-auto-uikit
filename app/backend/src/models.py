from typing import Any
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class StoreCreate(BaseModel):
    name: str
    platform: str = "AliExpress"


class TemplateCreate(BaseModel):
    template_type: str
    template_name: str
    binding_scope: str
    payload: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class ProductCreate(BaseModel):
    title: str
    category_name: str = "未分类"
    price: float = 0
    currency: str = "USD"
    sku_count: int = 1
    image_count: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


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


class AgentConsoleStep(BaseModel):
    title: str | None = None
    label: str | None = None
    state: str | None = None
    code: str | None = None
    action: str | None = None
    detail: str | None = None
    next_step: str | None = None
    store_name: str | None = None
    guard: str | None = None


class AgentConsoleStartRequest(BaseModel):
    task_id: int | None = None
    target_url: str | None = None
    launch_browser: bool = True
    step: AgentConsoleStep | None = None


class AgentConsoleHudRequest(BaseModel):
    step: AgentConsoleStep = Field(default_factory=AgentConsoleStep)


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
