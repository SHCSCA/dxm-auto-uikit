import asyncio
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.core.config import DATA_DIR
from src.db import init_db
from src.execution.dxm_live import DxmLiveClient
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.playwright_engine import PlaywrightEngine
from src.execution.v1_runner import V1TaskRunner
from src.models import (
    AIConfigUpdateRequest,
    DraftBoxActionRequest,
    HealthResponse,
    LoginContinueRequest,
    LoginNavigateRequest,
    LoginStartRequest,
    ProductCreate,
    ProductImportRequest,
    SelectorProfileValidateRequest,
    StoreCreate,
    TaskCreate,
    TitleGenerateRequest,
    TemplateCreate,
)
from src.repository import Repository
from src.services.title_ai import TitleAIService
from src.services.selector_profile import SelectorProfileService
from src.ws import ConnectionManager

app = FastAPI(title='dxm-auto-uikit backend', version='0.1.0')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.mount('/artifacts', StaticFiles(directory=DATA_DIR), name='artifacts')

init_db()
repo = Repository()
manager = ConnectionManager()
engine = PlaywrightEngine()
live_client = DxmLiveClient()
login_flow = DxmLoginFlow(live_client)
workflow_adapter = DxmWorkflowAdapter(login_flow)
runner = V1TaskRunner(repo, manager, workflow_adapter=workflow_adapter)
title_ai_service = TitleAIService()
selector_profile_service = SelectorProfileService()


@app.get('/health', response_model=HealthResponse)
def health():
    return HealthResponse(status='ok')


@app.get('/api/engine')
def get_engine():
    return engine.describe()


@app.get('/api/dxm/live-status')
def dxm_live_status():
    result = live_client.probe_session()
    return normalize_artifact_paths(result)


@app.get('/api/dxm/login-state')
def dxm_login_state():
    return normalize_artifact_paths(login_flow.get_state())


@app.get('/api/dxm/workflow/check-login')
def dxm_workflow_check_login():
    return normalize_artifact_paths(_workflow_adapter().check_login_state())


@app.post('/api/dxm/login/start')
def dxm_login_start(payload: LoginStartRequest):
    result = login_flow.start_login(payload.username, payload.password)
    return normalize_artifact_paths(result)


@app.post('/api/dxm/login/continue')
def dxm_login_continue(payload: LoginContinueRequest):
    if not payload.confirm:
        return normalize_artifact_paths(login_flow.get_state())
    result = login_flow.continue_login()
    return normalize_artifact_paths(result)


@app.post('/api/dxm/navigate')
def dxm_navigate(payload: LoginNavigateRequest):
    result = login_flow.navigate_post_login(payload.target)
    return normalize_artifact_paths(result)


@app.post('/api/dxm/workflow/open-draft-box')
def dxm_workflow_open_draft_box():
    return normalize_artifact_paths(_workflow_adapter().open_draft_box())


@app.post('/api/dxm/draft-box/action')
def dxm_draft_box_action(payload: DraftBoxActionRequest):
    result = login_flow.perform_draft_box_action(
        payload.action,
        note_text=payload.note_text,
        product_query=payload.product_query,
        store_name=payload.store_name,
    )
    return normalize_artifact_paths(result)


@app.post('/api/dxm/workflow/claim-product')
def dxm_workflow_claim_product(payload: DraftBoxActionRequest):
    return normalize_artifact_paths(_workflow_adapter().claim_product(
        payload.note_text or 'AI认领',
        product_query=payload.product_query,
        store_name=payload.store_name,
    ))


@app.post('/api/dxm/workflow/open-editor')
def dxm_workflow_open_editor(payload: DraftBoxActionRequest | None = None):
    payload = payload or DraftBoxActionRequest(action='edit')
    return normalize_artifact_paths(_workflow_adapter().open_editor(
        product_query=payload.product_query,
        store_name=payload.store_name,
    ))


@app.get('/api/ai/config')
def get_ai_config():
    return title_ai_service.get_config()


@app.post('/api/ai/config')
def update_ai_config(payload: AIConfigUpdateRequest):
    return title_ai_service.save_config(api_key=payload.api_key, model=payload.model)


@app.post('/api/ai/title/generate')
def generate_ai_title(payload: TitleGenerateRequest):
    return title_ai_service.generate_title(
        source_title=payload.source_title,
        title_style=payload.title_style,
        max_length=payload.max_length,
    )


@app.get('/api/stores')
def list_stores():
    return repo.list_stores()


@app.post('/api/stores/connect')
def create_store(payload: StoreCreate):
    return repo.create_store(payload.name, payload.platform)


@app.get('/api/templates')
def list_templates():
    return repo.list_templates()


@app.post('/api/templates')
def create_template(payload: TemplateCreate):
    return repo.create_template(payload.model_dump())


@app.get('/api/products')
def list_products():
    return repo.list_products()


@app.post('/api/products')
def create_product(payload: ProductCreate):
    return repo.create_product(payload.model_dump())


@app.post('/api/products/import')
def import_products(payload: ProductImportRequest):
    return repo.bulk_import_products(payload.rows)


@app.get('/api/tasks')
def list_tasks():
    return repo.list_tasks()


@app.get('/api/tasks/{task_id}')
def get_task(task_id: int):
    return repo.get_task(task_id)


@app.post('/api/tasks')
def create_task(payload: TaskCreate):
    return repo.create_task(payload.model_dump())


@app.post('/api/tasks/{task_id}/start')
async def start_task(task_id: int):
    asyncio.create_task(runner.run_task(task_id))
    return {'ok': True, 'taskId': task_id}


@app.post('/api/tasks/{task_id}/pause')
def pause_task(task_id: int):
    repo.update_task_status(task_id, 'paused')
    return {'ok': True, 'taskId': task_id, 'status': 'paused'}


@app.post('/api/tasks/{task_id}/resume')
def resume_task(task_id: int):
    repo.update_task_status(task_id, 'running')
    return {'ok': True, 'taskId': task_id, 'status': 'running'}


@app.post('/api/tasks/{task_id}/stop')
def stop_task(task_id: int):
    repo.update_task_status(task_id, 'cancelled')
    return {'ok': True, 'taskId': task_id, 'status': 'cancelled'}


@app.get('/api/exceptions')
def list_exceptions():
    return repo.list_exceptions()


@app.get('/api/reports')
def list_reports(task_id: int | None = None):
    return normalize_artifact_paths(repo.list_reports(task_id))


@app.get('/api/reports/tasks/{task_id}')
def list_task_reports(task_id: int):
    return normalize_artifact_paths(repo.list_reports(task_id))


@app.get('/api/selector-profiles')
def list_selector_profiles():
    return selector_profile_service.list_profiles()


@app.get('/api/selector-profiles/{page_key}')
def get_selector_profile(page_key: str):
    return selector_profile_service.get_profile(page_key)


@app.post('/api/selector-profiles/{page_key}/validate')
def validate_selector_profile(page_key: str, payload: SelectorProfileValidateRequest):
    return selector_profile_service.validate_page(
        page_key,
        payload.url,
        payload.body_text,
        payload.visible_buttons,
    )


@app.get('/api/logs')
def list_logs(task_id: int | None = None):
    return repo.list_logs(task_id)


@app.get('/api/evidences')
def list_evidences(task_id: int | None = None):
    return normalize_artifact_paths(repo.list_evidences(task_id))


@app.websocket('/ws/tasks/{task_id}')
async def task_ws(websocket: WebSocket, task_id: int):
    await manager.connect(task_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(task_id, websocket)


def normalize_artifact_paths(data):
    if isinstance(data, list):
        return [normalize_artifact_paths(item) for item in data]
    if isinstance(data, dict):
        normalized = {}
        for key, value in data.items():
            if isinstance(value, str) and value.startswith(str(DATA_DIR)):
                normalized[key] = value
                normalized[f'{key}_url'] = '/artifacts/' + Path(value).relative_to(DATA_DIR).as_posix()
            else:
                normalized[key] = normalize_artifact_paths(value)
        return normalized
    return data


def _workflow_adapter():
    return DxmWorkflowAdapter(login_flow)


def build_login_state(data: dict):
    if data.get('logged_in'):
        return {
            'stage': 'login_success',
            'label': '已登录',
            'message': '已检测到真实店小秘登录态，可以继续进入数据采集、采集箱和编辑流程。',
            'next_action': '继续同步当前页面并执行真实业务步骤。',
            'requires_user_action': False,
            'screenshot_url': data.get('home_screenshot_url') or data.get('product_page', {}).get('screenshot_url'),
            'page_title': data.get('title') or data.get('product_page', {}).get('title'),
            'page_url': data.get('final_url') or data.get('product_page', {}).get('url'),
        }

    if data.get('reason') == 'cookie_file_missing':
        return {
            'stage': 'opening_login_page',
            'label': '待登录',
            'message': '还没有真实店小秘会话，应该从官网登录开始。',
            'next_action': '打开官网登录页，填账号密码，进入验证码等待态。',
            'requires_user_action': True,
            'screenshot_url': None,
            'page_title': '店小秘官网登录页',
            'page_url': 'https://www.dianxiaomi.com/',
        }

    return {
        'stage': 'waiting_captcha',
        'label': '待确认',
        'message': '已能读取页面，但登录状态还不稳定；需要把验证码等待态和继续登录动作显式接入。',
        'next_action': '补充 continue 登录动作，并确认登录成功后的页面状态。',
        'requires_user_action': True,
        'screenshot_url': data.get('home_screenshot_url') or data.get('product_page', {}).get('screenshot_url'),
        'page_title': data.get('title') or data.get('product_page', {}).get('title'),
        'page_url': data.get('final_url') or data.get('product_page', {}).get('url') or 'https://www.dianxiaomi.com/',
    }
