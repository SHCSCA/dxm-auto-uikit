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
    mode: str = "save_draft"
    publish_scene: str = "POP"
    product_ids: list[int] = Field(default_factory=list)


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


class AIConfigUpdateRequest(BaseModel):
    api_key: str
    model: str = 'deepseek-chat'


class TitleGenerateRequest(BaseModel):
    source_title: str
    title_style: str = 'clear, searchable, non-hype'
    max_length: int = 110
