import asyncio
import hashlib
import hmac
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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
    AgentConsoleHudRequest,
    AgentConsoleStartRequest,
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
    TaskStartRequest,
    TitleGenerateRequest,
    TemplateCreate,
)
from src.repository import Repository
from src.services.title_ai import TitleAIService
from src.services.selector_profile import SelectorProfileService
from src.services.delivery_workspace import build_delivery_workspace, l2_real_probe_gate
from src.services.agent_console import AgentConsoleService
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
title_ai_service = TitleAIService()
selector_profile_service = SelectorProfileService()
agent_console_service = AgentConsoleService()
runner = V1TaskRunner(repo, manager, workflow_adapter=workflow_adapter, agent_console=agent_console_service)

REAL_DXM_MUTATION_MODES = {'claim_only', 'single_save', 'batch_save'}
REAL_WRITE_START_MODES = REAL_DXM_MUTATION_MODES
ALLOWED_START_MODES = {'probe', 'dry_run', 'claim_only', 'single_save', 'batch_save'}
SAVE_ONLY_PUBLISH_SCENE = 'SMT_SEMI_MANAGED_SAVE_ONLY'
L3_CONFIRMATION = 'CONFIRM_DXM_SAVE_ONLY'


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
    _assert_direct_real_dxm_mutation_allowed(payload)
    result = login_flow.perform_draft_box_action(
        payload.action,
        note_text=payload.note_text,
        product_query=payload.product_query,
        store_name=payload.store_name,
    )
    return normalize_artifact_paths(result)


@app.post('/api/dxm/workflow/claim-product')
def dxm_workflow_claim_product(payload: DraftBoxActionRequest):
    _assert_direct_real_dxm_mutation_allowed(payload)
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
async def start_task(task_id: int, payload: TaskStartRequest | None = None):
    payload = payload or TaskStartRequest()
    _assert_task_can_start(task_id, payload)
    if not repo.try_start_task(task_id):
        raise HTTPException(status_code=409, detail='Task is already running')
    asyncio.create_task(runner.run_task(task_id))
    return {'ok': True, 'taskId': task_id}


@app.post('/api/tasks/{task_id}/pause')
def pause_task(task_id: int):
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    if task.get('mode') in REAL_WRITE_START_MODES:
        raise HTTPException(status_code=409, detail='Real save task pause is disabled until worker pause acknowledgements are implemented')
    if not repo.try_pause_task(task_id):
        raise HTTPException(status_code=409, detail='Task is not running')
    return {'ok': True, 'taskId': task_id, 'status': 'paused'}


@app.post('/api/tasks/{task_id}/resume')
def resume_task(task_id: int):
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    raise HTTPException(status_code=409, detail='Resume is disabled until worker resume acknowledgements are implemented')


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


@app.get('/api/delivery/workspace')
def get_delivery_workspace(task_id: int | None = None):
    workspace = build_delivery_workspace(repo, task_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail='Task not found')
    return normalize_artifact_paths(workspace)


@app.get('/api/agent-console/status')
def get_agent_console_status():
    return normalize_artifact_paths(agent_console_service.status())


@app.post('/api/agent-console/start')
def start_agent_console(payload: AgentConsoleStartRequest):
    if payload.task_id is not None and repo.get_task(payload.task_id) is None:
        raise HTTPException(status_code=404, detail='Task not found')
    if payload.launch_browser:
        l2_gate = l2_real_probe_gate()
        if l2_gate.get('status') != 'passed':
            raise HTTPException(
                status_code=403,
                detail=f"Agent console browser start requires passed L2 readonly gate: {l2_gate.get('status')}",
            )
    step = payload.step.model_dump(exclude_none=True) if payload.step else None
    result = agent_console_service.start(
        task_id=payload.task_id,
        target_url=payload.target_url,
        launch_browser=payload.launch_browser,
        step=step,
    )
    return normalize_artifact_paths(result)


@app.post('/api/agent-console/hud')
def update_agent_console_hud(payload: AgentConsoleHudRequest):
    return normalize_artifact_paths(agent_console_service.update_hud(payload.step.model_dump(exclude_none=True)))


@app.post('/api/agent-console/snapshot')
def snapshot_agent_console():
    return normalize_artifact_paths(agent_console_service.snapshot())


@app.post('/api/agent-console/stop')
def stop_agent_console():
    return normalize_artifact_paths(agent_console_service.stop())


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


def _assert_task_can_start(task_id: int, request: TaskStartRequest) -> None:
    task = repo.get_task_private(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')

    payload = task.get('payload') or {}
    mode = str(task.get('mode') or payload.get('execution_mode') or '')
    if mode not in ALLOWED_START_MODES:
        raise HTTPException(status_code=400, detail=f'Unsupported execution mode: {mode}')
    if task.get('status') == 'running':
        raise HTTPException(status_code=409, detail='Task is already running')
    if task.get('status') != 'draft':
        raise HTTPException(status_code=409, detail=f"Task cannot start from status: {task.get('status')}")

    if mode not in REAL_DXM_MUTATION_MODES:
        return

    if str(task.get('publish_scene') or '') != SAVE_ONLY_PUBLISH_SCENE:
        raise HTTPException(status_code=403, detail='Real DXM mutation task requires save-only publish scene')
    if _task_store_name(task) != 'Dang Kang':
        raise HTTPException(status_code=403, detail='Real DXM mutation task requires Dang Kang store')

    approval = payload.get('manual_approval') or {}
    if not isinstance(approval, dict):
        approval = {}
    token_hash = approval.get('token_hash')
    request_token_hash = hashlib.sha256(request.approval_token.encode('utf-8')).hexdigest() if request.approval_token else ''
    token_ok = bool(token_hash and hmac.compare_digest(request_token_hash, str(token_hash)))
    approved = (
        request.manual_approval is True
        and request.confirmation == L3_CONFIRMATION
        and bool(request.approved_by)
        and approval.get('approved') is True
        and approval.get('source') == 'server'
        and token_ok
    )
    if not approved:
        raise HTTPException(
            status_code=403,
            detail='Manual approval is required before starting real claim_only/single_save/batch_save',
        )
    l2_gate = l2_real_probe_gate()
    if l2_gate.get('status') != 'passed':
        raise HTTPException(
            status_code=403,
            detail=f"L2 readonly probe gate is not passed: {l2_gate.get('status')}",
        )


def _assert_direct_real_dxm_mutation_allowed(payload: DraftBoxActionRequest) -> None:
    if payload.task_id is None:
        raise HTTPException(
            status_code=403,
            detail='Direct real DXM mutation requires an approved guarded task',
        )
    _assert_task_can_start(
        payload.task_id,
        TaskStartRequest(
            manual_approval=payload.manual_approval,
            approval_token=payload.approval_token,
            approved_by=payload.approved_by,
            confirmation=payload.confirmation,
        ),
    )


def _task_store_name(task: dict) -> str:
    payload = task.get('payload') or {}
    if payload.get('store_name'):
        return str(payload['store_name'])
    store_id = task.get('store_id')
    if store_id is None:
        return ''
    for store in repo.list_stores():
        if store.get('id') == store_id:
            return str(store.get('name') or '')
    return ''


def _workflow_adapter():
    return DxmWorkflowAdapter(login_flow)


def build_login_state(data: dict):
    if data.get('logged_in'):
        return {
            'stage': 'login_success',
            'label': '已登录',
            'message': '已检测到真实店小秘登录态；当前仅可继续只读诊断，真实变更仍受 L2/L3 门禁阻断。',
            'next_action': '继续同步当前页面并查看只读诊断；不要执行 claim_only/single_save/batch_save。',
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
