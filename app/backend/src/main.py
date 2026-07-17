import asyncio
import hashlib
import hmac
import json
import os
import shutil
import socket
import secrets
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.core.config import DATA_DIR
from src.services.runtime_bootstrap import ensure_runtime_bootstrap


APP_VERSION = '0.1.0'
REPO_ROOT = Path(__file__).resolve().parents[3]
runtime_bootstrap_state = ensure_runtime_bootstrap(
    data_dir=DATA_DIR,
    repo_root=REPO_ROOT,
    package_version=APP_VERSION,
)
runtime_identity = runtime_bootstrap_state.runtime_identity


from src.db import init_db
from src.execution.dxm_live import DxmLiveClient
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.playwright_engine import PlaywrightEngine
from src.execution.v1_runner import V1TaskRunner
from src.models import (
    AIConfigUpdateRequest,
    AcquisitionClaimRequest,
    AgentConsoleBrowserDiagnosticsRequest,
    AgentConsoleControlRequest,
    AgentConsoleHudRequest,
    AgentConsoleStartRequest,
    DraftBoxActionRequest,
    HealthResponse,
    LoginContinueRequest,
    LoginNavigateRequest,
    LoginStartRequest,
    ProductCreate,
    ProductImportRequest,
    RuntimeControlRequest,
    SelectorProfileValidateRequest,
    StoreCreate,
    TaskConfigOverrideRequest,
    TaskCreate,
    TaskManualApprovalRequest,
    TaskStartRequest,
    TitleGenerateRequest,
    TemplateCreate,
    TemplateUpdate,
)
from src.repository import Repository
from src.services.config_defaults import DEFAULT_TEMPLATE_TYPES
from src.services.title_ai import TitleAIService
from src.services.selector_profile import SelectorProfileService
from src.services.delivery_workspace import build_delivery_workspace, l2_real_probe_gate
from src.services.agent_console import AgentConsoleService
from src.services.config_preview import ConfigPreviewService
from src.services.template_center import template_center_metadata
from src.state_machine.two_stage import (
    TwoStageContractError,
    build_authorization_context,
    build_stage_a_task_facts,
    build_stage_b_task_facts,
    canonical_claim_target_identity,
)
from src.ws import ConnectionManager

@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    _append_backend_runtime_log(f'DXM backend runtime started pid={os.getpid()} owner={_runtime_control_owner()}')
    try:
        recovery = _recover_orphaned_runtime_tasks()
        if recovery.get('recovered') or recovery.get('cancelled'):
            _append_backend_runtime_log(
                f"startup task recovery recovered={','.join(map(str, recovery.get('recovered', []))) or 'none'} "
                f"cancelled={','.join(map(str, recovery.get('cancelled', []))) or 'none'}"
            )
    except Exception as exc:
        _append_backend_runtime_log(f'Startup task recovery failed: {exc}')
    try:
        yield
    finally:
        _append_backend_runtime_log('DXM backend runtime stopping; closing visible browser sessions')
        try:
            agent_console_service.stop()
        except Exception as exc:
            _append_backend_runtime_log(f'Agent console cleanup failed: {exc}')
        try:
            browser_shutdown = browser_agent_runtime.shutdown()
            if isinstance(browser_shutdown, dict) and browser_shutdown.get('ok') is not True:
                _append_backend_runtime_log(
                    'Browser Agent cleanup incomplete '
                    f"status={browser_shutdown.get('status') or 'unknown'} "
                    f"reason={browser_shutdown.get('reasonCode') or 'unknown'}"
                )
        except Exception as exc:
            _append_backend_runtime_log(f'Browser Agent cleanup failed: {exc}')


app = FastAPI(title='dxm-auto-uikit backend', version=APP_VERSION, lifespan=app_lifespan)
LOOPBACK_CORS_ORIGIN_RE = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
PUBLIC_ARTIFACT_ROOTS = {
    'screenshots': DATA_DIR / 'screenshots',
    'evidences': DATA_DIR / 'evidences',
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=['null'],
    allow_origin_regex=LOOPBACK_CORS_ORIGIN_RE,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
for public_name, public_root in PUBLIC_ARTIFACT_ROOTS.items():
    public_root.mkdir(parents=True, exist_ok=True)
    app.mount(f'/artifacts/{public_name}', StaticFiles(directory=public_root), name=f'artifacts-{public_name}')

init_db()
repo = Repository()
manager = ConnectionManager()
engine = PlaywrightEngine()
live_client = DxmLiveClient()
login_flow = DxmLoginFlow(live_client)
login_flow_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dxm-login-flow')
workflow_adapter = DxmWorkflowAdapter(login_flow)
mutation_dispatch_ledger = MutationDispatchLedger()
browser_agent_runtime = BrowserAgentRuntime(
    workflow_adapter,
    mutation_ledger=mutation_dispatch_ledger,
)
browser_agent_runtime.set_mutation_authorizer(
    lambda command, _context: _verify_runner_authorization(
        int(command.task_id),
        'claim_only' if command.state == 'CLAIM_TO_DRAFT_BOX' else 'single_save',
        command.state,
    )
)
title_ai_service = TitleAIService()
selector_profile_service = SelectorProfileService()
agent_console_service = AgentConsoleService()
config_preview_service = ConfigPreviewService()
runner = V1TaskRunner(
    repo,
    manager,
    workflow_adapter=workflow_adapter,
    agent_console=agent_console_service,
    browser_agent_runtime=browser_agent_runtime,
    authorization_verifier=lambda task_id, mode, state: _verify_runner_authorization(task_id, mode, state),
    workflow_executor=login_flow_executor,
)

REAL_DXM_MUTATION_MODES = {'claim_only', 'single_save', 'batch_save'}
RELEASED_REAL_DXM_MUTATION_MODES = {'claim_only', 'single_save'}
AUTHORIZATION_LEASE_TTL_SECONDS = 5 * 60
REAL_WRITE_START_MODES = REAL_DXM_MUTATION_MODES
ALLOWED_START_MODES = {'probe', 'dry_run', 'claim_only', 'single_save', 'batch_save'}
SAVE_ONLY_PUBLISH_SCENE = 'SMT_SEMI_MANAGED_SAVE_ONLY'
CLAIM_TO_DRAFT_PUBLISH_SCENE = 'CONTROLLED_CLAIM_TO_DRAFT_ONLY'
CLAIM_CONFIRMATION = '确认将该已有商品认领到商品箱'
L3_CONFIRMATION = 'CONFIRM_DXM_SAVE_ONLY'
UNRELEASED_REAL_DXM_MODE_DETAIL = 'Only controlled claim_only and single_save are released for real DXM mutation'
FINAL_DELIVERY_CHECK_JSON = REPO_ROOT / 'outputs' / 'final-delivery-check' / 'final-delivery-check.json'
RUNTIME_LAUNCHER_LOG_FILE = Path(
    os.environ.get('DXM_LAUNCHER_LOG_FILE')
    or DATA_DIR / ('desktop-main.log' if runtime_bootstrap_state.owner == 'electron_desktop' else 'start-mvp.log')
)
RUNTIME_LOG_SOURCES = {
    'backend': DATA_DIR / 'backend.log',
    'frontend': DATA_DIR / 'frontend.log',
    'launcher': RUNTIME_LAUNCHER_LOG_FILE,
    'npm': DATA_DIR / 'npm-install.log',
}
RUNTIME_CONTROL_COMMAND_FILE = Path(
    os.environ.get('DXM_RUNTIME_CONTROL_COMMAND_FILE') or DATA_DIR / 'runtime-control-command.json'
)
RUNTIME_CONTROL_MANAGED_BY_LAUNCHER = bool(os.environ.get('DXM_RUNTIME_CONTROL_COMMAND_FILE'))
RUNTIME_DESKTOP_MODE = runtime_bootstrap_state.owner == 'electron_desktop'
RUNTIME_BACKEND_INSTANCE_ID = runtime_identity.instance_id
RUNTIME_VIRTUAL_LOG_SOURCES = {'task', 'agent'}
RUNTIME_LOG_LEVELS = {'info', 'warning', 'error'}
RUNTIME_LOG_STALE_SECONDS = 30 * 60
RUNTIME_CONTROL_ACTIONS = {
    'stop_agent_console',
    'reset_workflow_runtime',
    'clear_stuck_tasks',
    'mark_real_task_manual_review',
    'restart_backend',
    'restart_frontend',
    'run_l2_readonly_probe',
    'browser_agent_takeover',
    'browser_agent_resume',
}
L2_READONLY_PROBE_RUNNER = REPO_ROOT / 'tools' / 'probes' / 'l2_readonly_probe_runner.py'
L2_READONLY_PROBE_SCRIPT = REPO_ROOT / 'tools' / 'probes' / 'l2_readonly_probe.py'
L2_READONLY_PROBE_COOKIE_FILE = DATA_DIR / 'sessions' / 'dianxiaomi_cookies.json'
L2_READONLY_PROBE_OUTPUT_DIR = DATA_DIR / 'l2_readonly_probe'
L2_READONLY_PROBE_ALLOWLIST_FILE = REPO_ROOT / 'config' / 'l2_readonly_allowlist.json'
L2_READONLY_PROBE_LOCK_FILE = L2_READONLY_PROBE_OUTPUT_DIR / 'runner.lock'
L2_READONLY_PROBE_LOCK_TTL_SECONDS = 60 * 60
RUNTIME_LOG_TAG_PATTERNS = {
    '启动': ('starting', 'started', 'running on', 'vite', 'ready in', 'launcher'),
    '登录检测': ('login', 'check-login', '登录'),
    '配置校验': ('precheck', 'config', '配置'),
    '打开 DXM': ('dianxiaomi.com', 'open-draft', 'navigate'),
    '点击': ('click', '点击'),
    '填写': ('fill', 'input', '填写'),
    '保存': ('save', '保存', 'add.json'),
    '网络响应': ('http/', 'response', 'status', 'network', 'har'),
    '报告生成': ('report', '报告'),
}


def _recover_orphaned_runtime_tasks() -> dict[str, list[int]]:
    recovered: list[int] = []
    cancelled: list[int] = []
    for task in repo.list_tasks():
        previous_status = str(task.get('status') or '')
        if previous_status not in {'running', 'paused'}:
            continue
        task_id = int(task['id'])
        full_task = repo.get_task_private(task_id) or task
        mode = str(task.get('mode') or (task.get('payload') or {}).get('execution_mode') or '')
        if mode in REAL_WRITE_START_MODES:
            repo.update_task_status(task_id, 'needs_manual_review')
            _mark_unfinished_jobs_after_runtime_recovery(
                full_task,
                status='failed',
                error_code='E901',
                error_message='上次真实浏览器任务没有正常结束，已停止自动执行并转入人工复核；请确认店小秘页面状态后重新打开执行浏览器再重试。',
            )
            repo.add_log(task_id, None, 'warning', '启动恢复：真实任务已转人工复核', {
                'previous_status': previous_status,
                'mode': mode,
                'reason': 'backend_restarted_while_task_active',
            })
            recovered.append(task_id)
            continue
        repo.update_task_status(task_id, 'cancelled')
        _mark_unfinished_jobs_after_runtime_recovery(
            full_task,
            status='cancelled',
            error_code='E901',
            error_message='上次任务随后台重启中断，已自动取消；请重新创建或启动任务。',
        )
        repo.add_log(task_id, None, 'warning', '启动恢复：已取消上次未结束任务', {
            'previous_status': previous_status,
            'mode': mode,
            'reason': 'backend_restarted_while_task_active',
        })
        cancelled.append(task_id)
    return {'recovered': recovered, 'cancelled': cancelled}


def _mark_unfinished_jobs_after_runtime_recovery(
    task: dict[str, Any],
    *,
    status: str,
    error_code: str,
    error_message: str,
) -> None:
    for job in task.get('jobs') or []:
        if str(job.get('status') or '') not in {'running', 'pending'}:
            continue
        repo.update_job(
            int(job['id']),
            status=status,
            current_step_code='RUNTIME_RECOVERY',
            current_step_name='后台重启恢复',
            error_code=error_code,
            error_message=error_message,
        )


@app.get('/health', response_model=HealthResponse)
def health():
    identity = runtime_identity.as_dict()
    return HealthResponse(status='ok', instanceId=identity['instanceId'], runtimeIdentity=identity)


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
    return normalize_artifact_paths(_run_login_flow(_workflow_adapter().check_login_state))


@app.post('/api/dxm/login/start')
def dxm_login_start(payload: LoginStartRequest):
    try:
        result = _run_login_flow(login_flow.start_login, payload.username, payload.password)
    except Exception as exc:
        result = _login_flow_failure_state(
            label='打开失败',
            message='真实店小秘登录浏览器启动失败。请按下一步处理，原始错误已保留到诊断字段和实时日志。',
            next_action='请关闭旧的 DXM Agent Console 或旧浏览器进程后重试；账号密码不会用于保存或发布。',
            raw_error=str(exc),
        )
    return normalize_artifact_paths(result)


@app.post('/api/dxm/login/continue')
def dxm_login_continue(payload: LoginContinueRequest):
    if not payload.confirm:
        return normalize_artifact_paths(login_flow.get_state())
    try:
        result = _run_login_flow(login_flow.continue_login)
    except Exception as exc:
        result = _login_flow_failure_state(
            label='检测失败',
            message='真实店小秘登录态检测失败。请按下一步处理，原始错误已保留到诊断字段和实时日志。',
            next_action='请确认真实浏览器窗口仍然打开，完成验证码或账号修正后再次检测；必要时重新打开登录页。',
            raw_error=str(exc),
        )
    return normalize_artifact_paths(result)


@app.post('/api/dxm/navigate')
def dxm_navigate(payload: LoginNavigateRequest):
    try:
        result = _run_login_flow(login_flow.navigate_post_login, payload.target)
    except Exception as exc:
        result = _workflow_navigation_failure_state(
            target=payload.target,
            raw_error=str(exc),
        )
    return normalize_artifact_paths(result)


@app.post('/api/dxm/workflow/open-draft-box')
def dxm_workflow_open_draft_box():
    return normalize_artifact_paths(_run_login_flow(_workflow_adapter().open_draft_box))


@app.post('/api/dxm/draft-box/action')
def dxm_draft_box_action(payload: DraftBoxActionRequest):
    _assert_direct_real_dxm_mutation_allowed(payload)
    result = _run_login_flow(
        login_flow.perform_draft_box_action,
        payload.action,
        note_text=payload.note_text,
        product_query=payload.product_query,
        store_name=payload.store_name,
        target_source_urls=payload.target_source_urls or None,
    )
    return normalize_artifact_paths(result)


@app.post('/api/dxm/workflow/claim-product')
def dxm_workflow_claim_product(payload: DraftBoxActionRequest):
    _assert_direct_real_dxm_mutation_allowed(payload)
    return normalize_artifact_paths(_run_login_flow(
        _workflow_adapter().claim_product,
        payload.note_text or 'AI认领',
        product_query=payload.product_query,
        store_name=payload.store_name,
        target_source_urls=payload.target_source_urls,
    ))


@app.post('/api/dxm/workflow/open-editor')
def dxm_workflow_open_editor(payload: DraftBoxActionRequest | None = None):
    payload = payload or DraftBoxActionRequest(action='edit')
    _assert_direct_real_dxm_mutation_allowed(payload)
    return normalize_artifact_paths(_run_login_flow(
        _workflow_adapter().open_editor,
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


@app.get('/api/template-center/metadata')
def get_template_center_metadata():
    return template_center_metadata()


@app.post('/api/templates')
def create_template(payload: TemplateCreate):
    data = payload.model_dump()
    data['payload'] = _normalize_template_payload(data.get('template_type'), data.get('payload'))
    return repo.create_template(data)


@app.patch('/api/templates/{template_id}')
def update_template(template_id: int, payload: TemplateUpdate):
    data = payload.model_dump(exclude_unset=True)
    if 'payload' in data:
        template_type = data.get('template_type')
        if template_type is None:
            current = repo.get_template(template_id)
            template_type = current.get('template_type') if current else None
        data['payload'] = _normalize_template_payload(template_type, data.get('payload'))
    template = repo.update_template(template_id, data)
    if not template:
        raise HTTPException(status_code=404, detail='Template not found')
    return template


@app.get('/api/config/preview')
def config_preview(task_id: int | None = None):
    return config_preview_service.build(repo, task_id)


@app.get('/api/products')
def list_products():
    return repo.list_products()


@app.get('/api/acquisition/claimed-products')
def list_acquisition_claimed_products():
    return repo.list_claimed_draft_products()


@app.post('/api/products')
def create_product(payload: ProductCreate):
    return repo.create_product(payload.model_dump())


@app.post('/api/products/import')
def import_products(payload: ProductImportRequest):
    return repo.bulk_import_products(payload.rows)


@app.post('/api/acquisition/claim-requests')
def create_acquisition_claim_request(payload: AcquisitionClaimRequest):
    task = repo.create_acquisition_claim_request(_normalize_acquisition_claim_request(payload))
    task_payload = task.get('payload') or {}
    return {
        'id': task.get('id'),
        'task_id': task.get('id'),
        'stage': task_payload.get('stage') or 'pending_acquisition_claim',
        'status': task_payload.get('status') or 'pending',
        'store_id': task_payload.get('store_id'),
        'source_url': task_payload.get('source_url'),
        'keyword': task_payload.get('keyword'),
        'category_name': task_payload.get('category_name'),
        'claim_mark': task_payload.get('claim_mark'),
        'template_id': task_payload.get('template_id'),
        'claimed_product_id': task_payload.get('claimed_product_id'),
        'claimed_product_title': task_payload.get('claimed_product_title'),
        'claimed_product_status': task_payload.get('claimed_product_status'),
        'claimed_product_source': task_payload.get('claimed_product_source'),
        'claimed_product_source_url': task_payload.get('claimed_product_source_url'),
        'claimed_product_category_name': task_payload.get('claimed_product_category_name'),
        'draft_box_verified': task_payload.get('draft_box_verified'),
        'next_step': task_payload.get('next_step'),
        'completed_at': task_payload.get('completed_at'),
        'task_status': task.get('status'),
    }


def _normalize_acquisition_claim_request(payload: AcquisitionClaimRequest) -> dict[str, Any]:
    data = payload.model_dump()
    source_url = str(data.get('source_url') or '').strip()
    keyword = str(data.get('keyword') or '').strip()
    category_name = str(data.get('category_name') or '').strip()
    claim_mark = str(data.get('claim_mark') or '').strip()
    if not claim_mark:
        raise HTTPException(status_code=400, detail='请填写认领标记。')
    if not keyword and not category_name and not source_url:
        raise HTTPException(status_code=400, detail='请填写商品关键词、商品类目或选择一条待认领商品，自动浏览器才能在店小秘已有待认领商品中定位目标。')
    data['source_url'] = source_url or None
    data['keyword'] = keyword or None
    data['category_name'] = category_name or None
    data['claim_mark'] = claim_mark
    return data


@app.get('/api/tasks')
def list_tasks():
    return repo.list_tasks()


@app.get('/api/tasks/{task_id}')
def get_task(task_id: int):
    return repo.get_task(task_id)


@app.post('/api/tasks')
def create_task(payload: TaskCreate):
    _assert_task_create_scope(payload)
    return repo.create_task(payload.model_dump())


@app.patch('/api/tasks/{task_id}/config-overrides')
def update_task_config_overrides(task_id: int, payload: TaskConfigOverrideRequest):
    section = payload.section.strip().lower().replace('-', '_').replace(' ', '_')
    if section not in DEFAULT_TEMPLATE_TYPES:
        raise HTTPException(status_code=400, detail=f'Unsupported config override section: {payload.section}')
    values = _normalize_config_override_values(section, payload.values)
    task = repo.update_task_template_override(task_id, section, values)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@app.post('/api/tasks/{task_id}/manual-approval')
def approve_task_for_real_dxm(task_id: int, payload: TaskManualApprovalRequest):
    required_confirmation = _assert_task_can_receive_manual_approval(task_id, payload)
    task_before_approval = repo.get_task_private(task_id)
    if not task_before_approval:
        raise HTTPException(status_code=404, detail='Task not found')
    l2_gate = l2_real_probe_gate()
    authorization_context = _build_task_authorization_context(
        task_before_approval,
        approved_by=payload.approved_by.strip(),
        l2_gate=l2_gate,
    )
    issued_at = _authorization_now()
    expires_at = issued_at + timedelta(seconds=AUTHORIZATION_LEASE_TTL_SECONDS)
    token = secrets.token_urlsafe(24)
    task = repo.set_task_manual_approval(
        task_id,
        approved=True,
        token=token,
        approved_by=payload.approved_by.strip(),
        confirmation=required_confirmation,
        authorization_context=authorization_context,
        lease_id=uuid.uuid4().hex,
        issued_at=issued_at.isoformat(),
        expires_at=expires_at.isoformat(),
    )
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    approval = (task.get('payload') or {}).get('manual_approval') or {}
    return {
        'ok': True,
        'taskId': task_id,
        'approvalToken': token,
        'confirmation': required_confirmation,
        'approvedBy': approval.get('approved_by'),
        'approvedAt': approval.get('approved_at'),
        'l2GateStatus': 'passed',
        'manualApproval': approval,
    }


@app.post('/api/tasks/{task_id}/start')
async def start_task(task_id: int, payload: TaskStartRequest | None = None):
    payload = payload or TaskStartRequest()
    authorization_context = _assert_task_can_start(task_id, payload)
    if authorization_context is not None:
        result = repo.try_start_task_with_authorization(
            task_id,
            token=str(payload.approval_token or ''),
            confirmation=str(payload.confirmation or ''),
            approved_by=str(payload.approved_by or '').strip(),
            authorization_context=authorization_context,
            consumed_at=_authorization_now().isoformat(),
        )
        if not result.ok:
            raise HTTPException(status_code=409, detail=f'{result.reason_code}: authorization lease rejected')
    elif not repo.try_start_task(task_id):
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
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    if task.get('mode') in REAL_WRITE_START_MODES:
        raise HTTPException(status_code=409, detail='Real save task stop is disabled until worker stop acknowledgements are implemented')
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


@app.get('/api/runtime/logs')
def runtime_logs(
    source: str = 'backend',
    cursor: int = 0,
    limit: int = 200,
    level: str | None = None,
    q: str | None = None,
    task_id: int | None = None,
):
    if source not in RUNTIME_LOG_SOURCES and source not in RUNTIME_VIRTUAL_LOG_SOURCES:
        raise HTTPException(status_code=400, detail=f'Unknown runtime log source: {source}')
    normalized_level = level.strip().lower() if level else None
    if normalized_level and normalized_level not in RUNTIME_LOG_LEVELS:
        raise HTTPException(status_code=400, detail=f'Unknown runtime log level: {level}')
    limit = max(1, min(limit, 500))
    cursor = max(0, cursor)
    query = q.strip().lower() if q else ''
    if source == 'task':
        return _runtime_task_logs(task_id=task_id, cursor=cursor, limit=limit, level=normalized_level, query=query)
    if source == 'agent':
        return _runtime_agent_logs(cursor=cursor, limit=limit, level=normalized_level, query=query)
    path = RUNTIME_LOG_SOURCES[source]
    if not path.exists():
        return {
            'source': source,
            'path': str(path),
            'exists': False,
            'cursor': cursor,
            'nextCursor': cursor,
            'items': [],
            'lines': [],
            'modifiedAt': None,
            'ageSeconds': None,
            'stale': False,
        }
    try:
        stat = path.stat()
        size = stat.st_size
        modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        start = min(cursor, size) if cursor else max(0, size - 262_144)
        with path.open('rb') as handle:
            handle.seek(start)
            data = handle.read(262_144)
            next_cursor = handle.tell()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f'Could not read runtime log: {exc}') from exc

    text = data.decode('utf-8-sig', errors='replace')
    items = [_runtime_log_item(line) for line in text.splitlines()]
    if normalized_level:
        items = [item for item in items if item['level'] == normalized_level]
    if query:
        items = [item for item in items if query in item['line'].lower()]
    if len(items) > limit:
        items = items[-limit:]
    age_seconds = max(0, int((datetime.now(timezone.utc) - modified_at).total_seconds()))
    return {
        'source': source,
        'path': str(path),
        'exists': True,
        'cursor': start,
        'nextCursor': next_cursor,
        'items': items,
        'lines': [item['line'] for item in items],
        'truncated': len(data) >= 262_144,
        'modifiedAt': modified_at.isoformat(),
        'ageSeconds': age_seconds,
        'stale': age_seconds > RUNTIME_LOG_STALE_SECONDS,
    }


def _runtime_control_owner() -> str:
    if RUNTIME_CONTROL_MANAGED_BY_LAUNCHER:
        return 'start_mvp'
    if RUNTIME_DESKTOP_MODE:
        return 'desktop'
    return 'direct'


def _runtime_control_detail() -> str:
    owner = _runtime_control_owner()
    if owner == 'start_mvp':
        return '由 start-mvp 启动器托管，可在 UI 内重启后端/前端'
    if owner == 'desktop':
        return '由 DXM Agent Console 免安装版启动；后端随桌面控制台关闭，服务重启请关闭并重新打开免安装版 exe。'
    return '当前后端不是由 DXM Agent Console 或 start-mvp 启动器托管，UI 不能重启服务；请关闭当前 Python 进程后重新打开免安装版 exe。'


def _runtime_control_restart_block_detail() -> str:
    if _runtime_control_owner() == 'desktop':
        return 'DXM Agent Console 免安装版当前不支持 UI 内重启后端。请关闭并重新打开免安装版 exe；真实保存不会自动发布。'
    return '当前后端不是由 DXM Agent Console 或 start-mvp 启动器托管，无法通过 UI 重启服务。请关闭当前 Python 进程后重新打开免安装版 exe。'


@app.get('/api/runtime/status')
def runtime_status(frontend_url: str | None = None):
    frontend_url = _runtime_frontend_url(frontend_url)
    backend_url = os.environ.get('DXM_BACKEND_URL') or f"http://127.0.0.1:{os.environ.get('DXM_BACKEND_PORT', '8000')}"
    agent_status = agent_console_service.status()
    dxm_state = normalize_artifact_paths(login_flow.get_state())
    real_browser_status = _runtime_real_browser_status(agent_status, dxm_state)
    identity = runtime_identity.as_dict()
    return {
        'runtimeIdentity': identity,
        'backend': {
            'status': 'ok',
            'url': backend_url,
            'port': _url_port(backend_url),
            'instanceId': identity['instanceId'],
            'runtimeIdentity': identity,
            'detail': 'Backend API is responding',
        },
        'frontend': _runtime_http_service_status('frontend', frontend_url),
        'agentConsole': {
            'status': 'running' if agent_status.get('active') else 'idle',
            'active': bool(agent_status.get('active')),
            'browserVisible': bool(agent_status.get('browser_visible')),
            'browserLaunching': bool(agent_status.get('browser_launching')),
            'currentUrl': agent_status.get('current_url') or agent_status.get('target_url'),
            'profileDir': agent_status.get('profile_dir'),
            'lastError': agent_status.get('last_error'),
        },
        'browserAgent': browser_agent_runtime.status(),
        'realBrowser': real_browser_status,
        'dxmLogin': {
            'status': str(dxm_state.get('status') or dxm_state.get('stage') or 'unknown'),
            'currentUrl': dxm_state.get('current_url') or dxm_state.get('url') or dxm_state.get('page_url'),
            'pageTitle': dxm_state.get('page_title') or dxm_state.get('title'),
            'browserVisible': bool(dxm_state.get('browser_visible')),
            'lastError': dxm_state.get('last_error') or dxm_state.get('error'),
            'message': dxm_state.get('message'),
            'nextAction': dxm_state.get('next_action'),
        },
        'l2ReadonlyProbe': _l2_probe_lock_status(),
        'dependencies': {
            'python': {
                'status': 'ok' if Path(sys.executable).exists() else 'missing',
                'path': sys.executable,
            },
            'node': {
                'status': 'ok' if shutil.which('node') else 'missing',
                'path': shutil.which('node'),
            },
            **_l2_readonly_probe_dependency_status(),
        },
        'runtimeControl': {
            'owner': _runtime_control_owner(),
            'managedByLauncher': RUNTIME_CONTROL_MANAGED_BY_LAUNCHER,
            'managedByDesktop': RUNTIME_DESKTOP_MODE and not RUNTIME_CONTROL_MANAGED_BY_LAUNCHER,
            'restartAvailable': RUNTIME_CONTROL_MANAGED_BY_LAUNCHER,
            'commandFile': str(RUNTIME_CONTROL_COMMAND_FILE),
            'detail': _runtime_control_detail(),
        },
        'workflowRuntime': _workflow_runtime_status(),
        'paths': {
            'data_dir': str(DATA_DIR),
            'dataDir': str(DATA_DIR),
            'l2_readonly_probe_dir': str(L2_READONLY_PROBE_OUTPUT_DIR),
            'l2ReadonlyProbeDir': str(L2_READONLY_PROBE_OUTPUT_DIR),
            'resource_root': str(REPO_ROOT),
            'resourceRoot': str(REPO_ROOT),
        },
    }


def _runtime_real_browser_status(agent_status: dict[str, Any], dxm_state: dict[str, Any]) -> dict[str, Any]:
    browser_agent_status = browser_agent_runtime.status()
    browser_agent_active = bool(browser_agent_status.get('active'))
    browser_agent_visible = bool(browser_agent_status.get('browserVisible'))
    if browser_agent_active or browser_agent_visible or str(browser_agent_status.get('status') or '') not in {'idle', 'stopped'}:
        return {
            'status': browser_agent_status.get('status') or 'known',
            'active': browser_agent_active,
            'browserVisible': browser_agent_visible,
            'browserLaunching': False,
            'source': 'browser_agent',
            'currentUrl': browser_agent_status.get('currentUrl'),
            'pageTitle': browser_agent_status.get('pageTitle'),
            'currentStep': browser_agent_status.get('currentStep'),
            'lastError': browser_agent_status.get('lastError'),
            'message': browser_agent_status.get('message'),
            'nextAction': browser_agent_status.get('nextAction'),
        }

    dxm_stage = str(dxm_state.get('stage') or dxm_state.get('status') or '').strip()
    dxm_url = dxm_state.get('current_url') or dxm_state.get('url') or dxm_state.get('page_url')
    dxm_browser_visible = bool(dxm_state.get('browser_visible'))
    dxm_business_state_seen = bool(
        dxm_stage
        and dxm_stage not in {'opening_login_page', 'unknown'}
        and (dxm_browser_visible or (isinstance(dxm_url, str) and 'dianxiaomi.com' in dxm_url))
    )
    if dxm_browser_visible or dxm_business_state_seen:
        return {
            'status': 'running' if dxm_browser_visible else 'known',
            'active': dxm_browser_visible,
            'browserVisible': dxm_browser_visible,
            'browserLaunching': False,
            'source': 'dxm_flow',
            'currentUrl': dxm_url,
            'pageTitle': dxm_state.get('page_title') or dxm_state.get('title'),
            'currentStep': dxm_state.get('label') or dxm_stage,
            'lastError': dxm_state.get('last_error') or dxm_state.get('error'),
            'message': dxm_state.get('message'),
            'nextAction': dxm_state.get('next_action'),
        }

    agent_active = bool(agent_status.get('active'))
    agent_visible = bool(agent_status.get('browser_visible'))
    agent_launching = bool(agent_status.get('browser_launching'))
    if agent_active or agent_visible or agent_launching:
        hud = agent_status.get('hud') if isinstance(agent_status.get('hud'), dict) else {}
        return {
            'status': 'launching' if agent_launching else 'running' if agent_active else 'known',
            'active': agent_active,
            'browserVisible': agent_visible,
            'browserLaunching': agent_launching,
            'source': 'agent_console',
            'currentUrl': agent_status.get('current_url') or agent_status.get('target_url'),
            'pageTitle': agent_status.get('page_title'),
            'currentStep': hud.get('title') or hud.get('label') or agent_status.get('last_step_name'),
            'lastError': agent_status.get('last_error'),
            'message': hud.get('action') or hud.get('detail'),
            'nextAction': hud.get('next_step'),
        }

    return {
        'status': 'idle',
        'active': False,
        'browserVisible': False,
        'browserLaunching': False,
        'source': 'none',
        'currentUrl': dxm_url or agent_status.get('target_url') or 'https://www.dianxiaomi.com/',
        'pageTitle': dxm_state.get('page_title') or dxm_state.get('title') or agent_status.get('page_title'),
        'currentStep': dxm_state.get('label') or dxm_stage or '待启动',
        'lastError': dxm_state.get('last_error') or dxm_state.get('error') or agent_status.get('last_error'),
        'message': dxm_state.get('message'),
        'nextAction': dxm_state.get('next_action'),
    }


def _runtime_frontend_url(frontend_url: str | None = None) -> str:
    if frontend_url:
        return frontend_url
    env_frontend_url = os.environ.get('DXM_FRONTEND_URL')
    if env_frontend_url:
        return env_frontend_url
    if RUNTIME_DESKTOP_MODE:
        return 'file://'
    return f"http://127.0.0.1:{os.environ.get('DXM_FRONTEND_PORT', '5173')}"


def _workflow_runtime_status() -> dict[str, Any]:
    reason = str(getattr(runner, 'workflow_runtime_unhealthy_reason', '') or '').strip() or _browser_agent_unhealthy_reason()
    if reason:
        return {
            'status': 'needs_restart',
            'healthy': False,
            'unhealthyReason': reason,
            'resetAction': 'reset_workflow_runtime',
            'message': '真实浏览器执行器需要重启后才能继续真实认领或保存任务。',
            'nextAction': '点击“重启真实浏览器执行器”，再重新打开执行浏览器后重试。',
        }
    return {
        'status': 'ready',
        'healthy': True,
        'unhealthyReason': None,
        'resetAction': None,
        'message': '真实浏览器执行器可用。',
        'nextAction': None,
    }


def _browser_agent_unhealthy_reason() -> str:
    try:
        status = browser_agent_runtime.status()
    except Exception as exc:
        return f'自动浏览器状态无法读取：{exc}'
    if status.get('healthy') is False:
        return str(status.get('lastError') or '自动浏览器运行时不可用，需要重启后继续。')
    return ''


def _shutdown_executor_without_wait(executor: ThreadPoolExecutor | None) -> None:
    if executor is None:
        return
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        executor.shutdown(wait=False)


_workflow_runtime_reset_lock = RLock()


def _reset_workflow_runtime() -> dict[str, Any]:
    global login_flow, workflow_adapter, login_flow_executor

    with _workflow_runtime_reset_lock:
        previous_reason = str(getattr(runner, 'workflow_runtime_unhealthy_reason', '') or '').strip() or _browser_agent_unhealthy_reason()
        old_executor = login_flow_executor
        candidate_executor: ThreadPoolExecutor | None = None
        try:
            candidate_flow = DxmLoginFlow(live_client)
            candidate_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dxm-login-flow')
            candidate_adapter = DxmWorkflowAdapter(candidate_flow)
            browser_reset = browser_agent_runtime.reset(candidate_adapter)
            if not isinstance(browser_reset, dict) or browser_reset.get('ok') is not True:
                raise RuntimeError('BROWSER_AGENT_RESET_REJECTED: browser runtime did not accept candidate adapter')
        except Exception:
            _shutdown_executor_without_wait(candidate_executor)
            raise

        login_flow = candidate_flow
        login_flow_executor = candidate_executor
        workflow_adapter = candidate_adapter
        runner.workflow_adapter = candidate_adapter
        runner._workflow_executor = candidate_executor
        runner.browser_agent_runtime = browser_agent_runtime
        runner.workflow_runtime_unhealthy_reason = None
        _shutdown_executor_without_wait(old_executor)

    return {
        'workflowRuntime': _workflow_runtime_status(),
        'browserAgent': browser_agent_runtime.status(),
        'previousUnhealthyReason': previous_reason or None,
        'oldRuntimeDetached': bool(previous_reason),
    }


@app.post('/api/runtime/control')
def runtime_control(payload: RuntimeControlRequest):
    action = payload.action.strip().lower()
    if action not in RUNTIME_CONTROL_ACTIONS:
        raise HTTPException(status_code=400, detail=f'Unknown runtime control action: {payload.action}')

    if action in {'restart_backend', 'restart_frontend'}:
        if not RUNTIME_CONTROL_MANAGED_BY_LAUNCHER:
            raise HTTPException(
                status_code=409,
                detail=_runtime_control_restart_block_detail(),
            )
        command = _write_runtime_control_command(action=action, task_id=payload.task_id)
        _append_runtime_control_log(f"queued launcher restart action={action} command_id={command['id']}")
        return {
            'ok': True,
            'action': action,
            'command': command,
            'message': '已请求启动器托管重启；请查看启动器日志确认完成',
        }

    if action == 'run_l2_readonly_probe':
        result = _start_l2_readonly_probe(payload.task_id)
        return {
            'ok': True,
            'action': action,
            **result,
            'message': '已启动 L2 双目标真实只读复验；请在执行控制台查看启动器日志',
        }

    if action == 'stop_agent_console':
        before = agent_console_service.status()
        result = agent_console_service.stop()
        task_id = before.get('task_id')
        if isinstance(task_id, int):
            repo.add_log(task_id, before.get('job_id'), 'info', '运行时控制：已停止自动浏览器', {
                'action': action,
                'session_id': before.get('session_id'),
            })
        _append_runtime_control_log(f"stop_agent_console task={task_id or 'none'} session={before.get('session_id') or 'none'}")
        return normalize_artifact_paths({
            'ok': True,
            'action': action,
            'agentConsole': result,
            'message': '自动浏览器已停止',
        })

    if action == 'browser_agent_takeover':
        result = browser_agent_runtime.request_manual_takeover()
        _append_runtime_control_log("browser_agent_takeover")
        takeover_ok = result.get('ok') is True
        return normalize_artifact_paths({
            'ok': takeover_ok,
            'action': action,
            'browserAgent': result,
            'message': (
                '已进入人工接管；请在真实浏览器里检查或修正当前页面'
                if takeover_ok
                else '尚未进入人工接管；当前命令仍在安全收口，请等待或重启真实浏览器执行器'
            ),
        })

    if action == 'browser_agent_resume':
        result = browser_agent_runtime.resume()
        _append_runtime_control_log("browser_agent_resume")
        resume_ok = result.get('ok') is True
        return normalize_artifact_paths({
            'ok': resume_ok,
            'action': action,
            'browserAgent': result,
            'message': (
                '真实浏览器已交还自动浏览器，可继续执行'
                if resume_ok
                else '真实浏览器尚未交还；请等待当前命令收口或重启真实浏览器执行器'
            ),
        })

    if action == 'reset_workflow_runtime':
        result = _reset_workflow_runtime()
        _append_runtime_control_log(
            f"reset_workflow_runtime previous_unhealthy={result.get('previousUnhealthyReason') or 'none'}"
        )
        return normalize_artifact_paths({
            'ok': True,
            'action': action,
            **result,
            'message': '真实浏览器执行器已重启；请重新打开执行浏览器后再启动任务',
        })

    if action == 'clear_stuck_tasks':
        cleared: list[dict] = []
        skipped: list[dict] = []
        candidates = [task for task in repo.list_tasks() if task.get('status') in {'running', 'paused'}]
        for task in candidates:
            task_id = task.get('id')
            mode = str(task.get('mode') or (task.get('payload') or {}).get('execution_mode') or '')
            if mode in REAL_WRITE_START_MODES:
                skipped.append({'id': task_id, 'mode': mode, 'status': task.get('status'), 'reason': 'real_write_protected'})
                continue
            repo.update_task_status(task_id, 'cancelled')
            repo.add_log(task_id, None, 'warning', '运行时控制：已清理卡住任务会话', {
                'action': action,
                'previous_status': task.get('status'),
                'mode': mode,
            })
            cleared.append({'id': task_id, 'mode': mode, 'previousStatus': task.get('status')})
        _append_runtime_control_log(
            f"clear_stuck_tasks cleared={','.join(str(item['id']) for item in cleared) or 'none'} "
            f"skipped={','.join(str(item['id']) for item in skipped) or 'none'}"
        )
        return {
            'ok': True,
            'action': action,
            'clearedTaskIds': [item['id'] for item in cleared],
            'clearedTasks': cleared,
            'skippedTasks': skipped,
            'message': f"已清理 {len(cleared)} 个非真实写入任务；保护 {len(skipped)} 个真实写入任务",
        }

    if action == 'mark_real_task_manual_review':
        if payload.task_id is None:
            raise HTTPException(status_code=400, detail='task_id is required to mark a real task for manual review')
        task = repo.get_task(payload.task_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        mode = str(task.get('mode') or (task.get('payload') or {}).get('execution_mode') or '')
        if mode not in REAL_WRITE_START_MODES:
            raise HTTPException(status_code=409, detail='Only real DXM write tasks can be marked for manual review')
        previous_status = str(task.get('status') or '')
        if previous_status not in {'running', 'paused', 'failed', 'partial_success'}:
            raise HTTPException(status_code=409, detail=f'Task status cannot be marked for manual review: {previous_status}')
        if not repo.try_update_task_status(
            payload.task_id,
            'needs_manual_review',
            expected_statuses=(previous_status,),
        ):
            current = repo.get_task(payload.task_id)
            current_status = str((current or {}).get('status') or 'missing')
            raise HTTPException(
                status_code=409,
                detail=f'Task status changed before manual review transition: {previous_status} -> {current_status}',
            )
        repo.add_log(payload.task_id, None, 'warning', '运行时控制：真实写入任务已转人工复核', {
            'action': action,
            'previous_status': previous_status,
            'mode': mode,
            'reason': 'manual_review_requested',
        })
        marked = [{
            'id': payload.task_id,
            'mode': mode,
            'previousStatus': previous_status,
            'status': 'needs_manual_review',
            'reason': 'manual_review_requested',
        }]
        _append_runtime_control_log(f"mark_real_task_manual_review task={payload.task_id} previous_status={previous_status} mode={mode}")
        return {
            'ok': True,
            'action': action,
            'markedTasks': marked,
            'message': '已将真实写入任务转入人工复核；未取消真实浏览器执行进程',
        }

    raise HTTPException(status_code=400, detail=f'Unhandled runtime control action: {payload.action}')


@app.get('/api/evidences')
def list_evidences(task_id: int | None = None):
    return normalize_artifact_paths(repo.list_evidences(task_id))


@app.get('/api/delivery/workspace')
def get_delivery_workspace(task_id: int | None = None):
    workspace = build_delivery_workspace(repo, task_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail='Task not found')
    return normalize_artifact_paths(workspace)


@app.get('/api/delivery/final-check')
def get_final_delivery_check_summary():
    return _read_final_delivery_check_summary()


@app.get('/api/agent-console/status')
def get_agent_console_status():
    return normalize_artifact_paths(agent_console_service.status())


@app.post('/api/agent-console/browser-diagnostics')
def run_agent_console_browser_diagnostics(payload: AgentConsoleBrowserDiagnosticsRequest):
    target_url = payload.target_url or 'https://www.dianxiaomi.com/'
    parsed = urlparse(target_url)
    host = (parsed.hostname or '').casefold()
    allowed_host = host == 'dianxiaomi.com' or host.endswith('.dianxiaomi.com')
    if parsed.scheme not in {'http', 'https'} or not allowed_host:
        raise HTTPException(status_code=403, detail='Browser diagnostics target must be a dianxiaomi.com URL')
    if payload.launch_browser:
        raise HTTPException(status_code=403, detail='Diagnostics cannot launch a real DXM browser; start a gated task browser first')
    result = agent_console_service.browser_diagnostics(
        target_url=target_url,
        launch_browser=False,
    )
    return normalize_artifact_paths(result)


@app.post('/api/agent-console/start')
def start_agent_console(payload: AgentConsoleStartRequest):
    task = repo.get_task(payload.task_id) if payload.task_id is not None else None
    if payload.task_id is not None and task is None:
        raise HTTPException(status_code=404, detail='Task not found')
    if payload.launch_browser:
        if task is None:
            raise HTTPException(
                status_code=403,
                detail='Agent execution browser start requires a selected controlled claim_only or single_save task',
            )
        mode = str(task.get('mode') or (task.get('payload') or {}).get('execution_mode') or '')
        if mode not in RELEASED_REAL_DXM_MUTATION_MODES:
            raise HTTPException(status_code=403, detail=UNRELEASED_REAL_DXM_MODE_DETAIL)
        if mode == 'claim_only' and str(task.get('publish_scene') or '') != CLAIM_TO_DRAFT_PUBLISH_SCENE:
            raise HTTPException(status_code=403, detail='Controlled claim_only task requires claim-to-draft scene')
        if mode == 'claim_only':
            _assert_claim_only_acquisition_task(task)
        task_status = str(task.get('status') or '')
        if task_status == 'running':
            raise HTTPException(status_code=409, detail='Task is already running')
        if task_status != 'draft':
            raise HTTPException(status_code=409, detail=f'Task cannot start execution browser from status: {task_status}')
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
        launch_browser_async=payload.launch_browser,
        step=step,
    )
    return normalize_artifact_paths(result)


@app.post('/api/agent-console/hud')
def update_agent_console_hud(payload: AgentConsoleHudRequest):
    return normalize_artifact_paths(agent_console_service.update_hud(payload.step.model_dump(exclude_none=True)))


@app.post('/api/agent-console/snapshot')
def snapshot_agent_console():
    return normalize_artifact_paths(agent_console_service.snapshot())


@app.post('/api/agent-console/frame')
def refresh_agent_console_frame():
    return normalize_artifact_paths(agent_console_service.refresh_frame())


@app.post('/api/agent-console/control')
def control_agent_console_browser(payload: AgentConsoleControlRequest):
    return normalize_artifact_paths(agent_console_service.control_browser(payload.model_dump(exclude_none=True)))


@app.post('/api/agent-console/takeover')
def request_agent_console_takeover():
    return normalize_artifact_paths(agent_console_service.request_manual_takeover())


@app.post('/api/agent-console/release')
def release_agent_console_takeover():
    return normalize_artifact_paths(agent_console_service.release_manual_takeover())


@app.post('/api/agent-console/stop')
def stop_agent_console():
    return normalize_artifact_paths(agent_console_service.stop())


def _normalize_config_override_values(section: str, values: dict[str, Any]) -> dict[str, Any]:
    if section != 'dxm_reference':
        return values
    return _normalize_dxm_reference_override(values)


def _normalize_template_payload(template_type: Any, payload: Any) -> Any:
    normalized_type = str(template_type or '').strip().lower().replace('-', '_').replace(' ', '_')
    if normalized_type != 'dxm_reference':
        return payload
    return _normalize_dxm_reference_override(payload)


def _normalize_dxm_reference_override(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, child in value.items():
            if key in {'names', 'templates', 'template_names', 'priorities'}:
                normalized[key] = _split_reference_names(child)
            elif key == 'name':
                normalized['names'] = _split_reference_names(child)
            elif key == 'dxm_reference_templates':
                normalized[key] = _normalize_dxm_reference_override(child)
            elif isinstance(child, (dict, list)):
                normalized[key] = _normalize_dxm_reference_override(child)
            else:
                normalized[key] = child
        return normalized
    if isinstance(value, list):
        return [_normalize_dxm_reference_override(item) for item in value]
    return value


def _split_reference_names(value: Any) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]
    names: list[str] = []
    for raw in raw_values:
        text = str(raw or '').strip()
        if not text:
            continue
        for separator in ('\r\n', '\n', ' / ', '，', ',', '；', ';'):
            text = text.replace(separator, '\n')
        for item in text.split('\n'):
            name = item.strip()
            if name and name not in names:
                names.append(name)
    return names


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
                artifact_url = _public_artifact_url(value)
                if artifact_url:
                    normalized[f'{key}_url'] = artifact_url
            else:
                normalized[key] = normalize_artifact_paths(value)
        return normalized
    return data


def _public_artifact_url(value: str) -> str | None:
    try:
        path = Path(value).resolve()
    except OSError:
        return None
    for public_name, public_root in PUBLIC_ARTIFACT_ROOTS.items():
        try:
            relative = path.relative_to(public_root.resolve())
        except ValueError:
            continue
        return f'/artifacts/{public_name}/{relative.as_posix()}'
    return None


def _runtime_log_item(line: str) -> dict:
    normalized = line.lower()
    if any(token in normalized for token in (' error', 'error:', 'traceback', 'exception', ' failed', ' 500 ')):
        level = 'error'
    elif any(token in normalized for token in ('warn', 'warning', 'blocked', 'forbidden', ' 403 ', ' 409 ')):
        level = 'warning'
    else:
        level = 'info'
    tags = [
        tag
        for tag, patterns in RUNTIME_LOG_TAG_PATTERNS.items()
        if any(pattern.lower() in normalized for pattern in patterns)
    ]
    if _is_runtime_access_log(line):
        tags.append('access')
    if _is_runtime_log_poll_noise(line):
        tags.append('polling')
    return {'line': line, 'level': level, 'tags': tags}


def _is_runtime_access_log(line: str) -> bool:
    return line.startswith('INFO:') and '"GET /api/' in line and 'HTTP/1.1"' in line


def _is_runtime_log_poll_noise(line: str) -> bool:
    return _is_runtime_access_log(line) and (
        '/api/runtime/logs?' in line
        or '/api/runtime/status?' in line
        or '/api/agent-console/status' in line
    )


def _runtime_task_logs(task_id: int | None, cursor: int, limit: int, level: str | None, query: str) -> dict:
    rows = repo.list_logs(task_id)
    rows = sorted(rows, key=lambda item: int(item.get('id') or 0))
    if cursor:
        rows = [row for row in rows if int(row.get('id') or 0) > cursor]

    items = []
    for row in rows:
        row_level = str(row.get('level') or 'info').lower()
        line = _format_task_log_line(row)
        item = _runtime_log_item(line)
        item['level'] = row_level if row_level in RUNTIME_LOG_LEVELS else item['level']
        if level and item['level'] != level:
            continue
        if query and query not in item['line'].lower():
            continue
        items.append(item)

    if len(items) > limit:
        items = items[-limit:]
    next_cursor = max([cursor, *[int(row.get('id') or 0) for row in rows]], default=cursor)
    return {
        'source': 'task',
        'path': f'job_logs{f"?task_id={task_id}" if task_id else ""}',
        'exists': True,
        'cursor': cursor,
        'nextCursor': next_cursor,
        'items': items,
        'lines': [item['line'] for item in items],
        'truncated': len(rows) > limit,
    }


def _runtime_agent_logs(cursor: int, limit: int, level: str | None, query: str) -> dict:
    status = agent_console_service.status()
    history = list(status.get('step_history') or [])
    action_events = list(status.get('action_events') or [])
    events = []
    if not history and not action_events:
        events.append({
            'index': 1,
            'line': _format_agent_status_line(status),
        })
    else:
        for index, event in enumerate(history, start=1):
            events.append({
                'index': index,
                'line': _format_agent_history_line(event),
            })
        offset = len(events)
        for index, event in enumerate(action_events, start=1):
            events.append({
                'index': offset + index,
                'line': _format_agent_action_line(event),
            })
        if status.get('last_error'):
            events.append({
                'index': len(events) + 1,
                'line': f"[{status.get('updated_at') or ''}] ERROR Agent Console: {status.get('last_error')}",
            })

    if cursor:
        events = [event for event in events if int(event.get('index') or 0) > cursor]

    items = []
    for event in events:
        item = _runtime_log_item(str(event.get('line') or ''))
        if level and item['level'] != level:
            continue
        if query and query not in item['line'].lower():
            continue
        items.append(item)
    if len(items) > limit:
        items = items[-limit:]
    next_cursor = max([cursor, *[int(event.get('index') or 0) for event in events]], default=cursor)
    return {
        'source': 'agent',
        'path': 'agent_console.events',
        'exists': True,
        'cursor': cursor,
        'nextCursor': next_cursor,
        'items': items,
        'lines': [item['line'] for item in items],
        'truncated': len(events) > limit,
    }


def _format_task_log_line(row: dict) -> str:
    task_id = row.get('task_id')
    job_id = row.get('job_id')
    level = str(row.get('level') or 'info').upper()
    created_at = row.get('created_at') or ''
    context = row.get('context') if isinstance(row.get('context'), dict) else {}
    tags = []
    if context.get('action'):
        tags.append(f"action={context.get('action')}")
    if context.get('step') or context.get('step_code'):
        tags.append(f"step={context.get('step') or context.get('step_code')}")
    suffix = f" [{' '.join(tags)}]" if tags else ''
    return f"[{created_at}] {level} task#{task_id}{f' job#{job_id}' if job_id else ''}: {row.get('message')}{suffix}"


def _format_agent_status_line(status: dict) -> str:
    state = status.get('hud') if isinstance(status.get('hud'), dict) else {}
    active = 'running' if status.get('active') else 'idle'
    visible = 'visible' if status.get('browser_visible') else 'hidden'
    return (
        f"[{status.get('updated_at') or status.get('created_at') or ''}] "
        f"Agent Console {active}/{visible}: {state.get('title') or '待命'} "
        f"url={status.get('current_url') or status.get('target_url') or '-'}"
    )


def _format_agent_history_line(event: dict) -> str:
    field_domain = event.get('field_domain')
    mode = event.get('mode')
    field_part = f" / {field_domain}" if field_domain else ''
    mode_part = f" / {mode}" if mode else ''
    return (
        f"[{event.get('updated_at') or ''}] Agent action task#{event.get('task_id')}: "
        f"{event.get('step_code') or 'STEP'} / {event.get('step_name') or '状态推进'}"
        f"{field_part}{mode_part}"
    )


def _format_agent_action_line(event: dict) -> str:
    action_type = event.get('type') or 'workflow_action'
    action = event.get('action') or 'action'
    state = event.get('step_code') or event.get('state') or 'STEP'
    target = event.get('target')
    status = event.get('status') or 'ok'
    target_part = f" target={target}" if target else ''
    return (
        f"[{event.get('timestamp') or ''}] Agent action task#{event.get('task_id')}: "
        f"{state} / {action_type} / {action} status={status}{target_part}"
    )


def _append_runtime_control_log(message: str) -> None:
    path = RUNTIME_LOG_SOURCES.get('launcher') or (DATA_DIR / 'start-mvp.log')
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"[runtime-control] {message}"
    try:
        with path.open('a', encoding='utf-8') as handle:
            handle.write(line + '\n')
    except OSError:
        pass


def _append_backend_runtime_log(message: str) -> None:
    path = RUNTIME_LOG_SOURCES.get('backend') or (DATA_DIR / 'backend.log')
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        with path.open('a', encoding='utf-8') as handle:
            handle.write(f'[{timestamp}] {message}\n')
    except OSError:
        pass


def _resource_root_candidates() -> list[Path]:
    roots: list[Path] = []
    for raw in (os.environ.get('DXM_RESOURCE_ROOT'), os.environ.get('DXM_REPO_ROOT')):
        if raw:
            roots.append(Path(raw))
    roots.extend([
        REPO_ROOT,
        Path.cwd(),
        Path(__file__).resolve().parents[3],
    ])
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            key = str(root.resolve())
        except OSError:
            key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _resource_path_candidates(default_path: Path, relative_path: str) -> list[Path]:
    candidates = [default_path]
    candidates.extend(root / relative_path for root in _resource_root_candidates())
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve())
        except OSError:
            key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _resolve_resource_path(default_path: Path, relative_path: str) -> Path:
    for candidate in _resource_path_candidates(default_path, relative_path):
        if candidate.exists():
            return candidate
    return default_path


def _resource_dependency_status(default_path: Path, relative_path: str) -> dict[str, Any]:
    resolved = _resolve_resource_path(default_path, relative_path)
    checked_paths = _resource_path_candidates(default_path, relative_path)
    status = 'ok' if resolved.exists() else 'missing'
    info = _resource_dependency_user_info(relative_path)
    return {
        'status': status,
        'path': str(resolved),
        'checkedPaths': [str(path) for path in checked_paths],
        **info,
        'userMessage': ''
        if status == 'ok'
        else f"真实只读检查组件未安装完整：缺少{info['label']}。",
    }


def _resource_dependency_user_info(relative_path: str) -> dict[str, Any]:
    labels = {
        'tools/probes/l2_readonly_probe_runner.py': '只读页面检查启动器',
        'tools/probes/l2_readonly_probe.py': '只读页面检查脚本',
        'config/l2_readonly_allowlist.json': '只读安全名单',
    }
    label = labels.get(relative_path, '运行依赖文件')
    return {
        'label': label,
        'requiredFor': '运行真实只读检查（只读，不保存）',
        'repairAction': '关闭旧后台进程后重新打开免安装版',
        'repairSteps': [
            '关闭所有旧的 DXM Agent Console 窗口。',
            '如果任务管理器里仍有 python.exe、uvicorn 或 DXM-Agent-Console，结束旧后台进程。',
            '使用 Portable 单文件版时，直接重新打开 exe；不要继续操作残留窗口。',
            '使用目录版时，必须保留同目录 resources 文件夹。',
            '如果仍缺失，请重新打包免安装版后再启动。',
        ],
    }


def _l2_readonly_probe_paths() -> dict[str, Path]:
    return {
        'runner': _resolve_resource_path(L2_READONLY_PROBE_RUNNER, 'tools/probes/l2_readonly_probe_runner.py'),
        'script': _resolve_resource_path(L2_READONLY_PROBE_SCRIPT, 'tools/probes/l2_readonly_probe.py'),
        'allowlist': _resolve_resource_path(L2_READONLY_PROBE_ALLOWLIST_FILE, 'config/l2_readonly_allowlist.json'),
        'cookie_file': L2_READONLY_PROBE_COOKIE_FILE,
        'output_dir': L2_READONLY_PROBE_OUTPUT_DIR,
        'lock_file': L2_READONLY_PROBE_LOCK_FILE,
    }


def _l2_readonly_probe_dependency_status() -> dict[str, dict[str, Any]]:
    return {
        'l2_readonly_probe_runner': _resource_dependency_status(
            L2_READONLY_PROBE_RUNNER,
            'tools/probes/l2_readonly_probe_runner.py',
        ),
        'l2_readonly_probe_script': _resource_dependency_status(
            L2_READONLY_PROBE_SCRIPT,
            'tools/probes/l2_readonly_probe.py',
        ),
        'l2_readonly_probe_allowlist': _resource_dependency_status(
            L2_READONLY_PROBE_ALLOWLIST_FILE,
            'config/l2_readonly_allowlist.json',
        ),
    }


def _raise_l2_probe_dependency_error(missing: list[tuple[str, Path]]) -> None:
    detail = '; '.join(f'{label}: {path}' for label, path in missing)
    checked = '; '.join(
        str(path)
        for default_path, relative_path in (
            (L2_READONLY_PROBE_RUNNER, 'tools/probes/l2_readonly_probe_runner.py'),
            (L2_READONLY_PROBE_SCRIPT, 'tools/probes/l2_readonly_probe.py'),
            (L2_READONLY_PROBE_ALLOWLIST_FILE, 'config/l2_readonly_allowlist.json'),
        )
        for path in _resource_path_candidates(default_path, relative_path)
    )
    raise HTTPException(
        status_code=424,
        detail=f'L2 readonly probe resources are missing: {detail}. Checked: {checked}',
    )


def _start_l2_readonly_probe(task_id: int | None) -> dict:
    probe_paths = _l2_readonly_probe_paths()
    missing = [
        (label, probe_paths[key])
        for key, label in (
            ('runner', 'runner'),
            ('script', 'script'),
            ('allowlist', 'allowlist'),
        )
        if not probe_paths[key].exists()
    ]
    if missing:
        _raise_l2_probe_dependency_error(missing)
    run_id = 'l2-real-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:8]
    _acquire_l2_probe_lock(run_id=run_id, task_id=task_id)
    log_path = RUNTIME_LOG_SOURCES.get('launcher') or (DATA_DIR / 'start-mvp.log')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        '-u',
        str(probe_paths['runner']),
        '--run-id',
        run_id,
        '--python',
        sys.executable,
        '--script',
        str(probe_paths['script']),
        '--cookie-file',
        str(probe_paths['cookie_file']),
        '--output-dir',
        str(probe_paths['output_dir']),
        '--allowlist-file',
        str(probe_paths['allowlist']),
        '--lock-file',
        str(probe_paths['lock_file']),
        '--headed',
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    try:
        with log_path.open('ab') as handle:
            process = subprocess.Popen(
                command,
                cwd=str(REPO_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
    except OSError as exc:
        _release_l2_probe_lock(run_id)
        raise HTTPException(status_code=500, detail=f'Could not start L2 readonly probe: {exc}') from exc
    try:
        _write_l2_probe_lock(run_id=run_id, task_id=task_id, pid=process.pid)
    except OSError as exc:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            kill = getattr(process, 'kill', None)
            if callable(kill):
                try:
                    kill()
                except Exception:
                    pass
        _release_l2_probe_lock(run_id)
        raise HTTPException(status_code=500, detail=f'Could not record L2 readonly probe lock: {exc}') from exc
    _append_runtime_control_log(
        f"started L2 readonly dual-target probe run_id={run_id} pid={process.pid} task={task_id or 'none'}"
    )
    return {
        'runId': run_id,
        'pid': process.pid,
        'logPath': str(log_path),
        'targets': ['data_acquisition', 'draft_box'],
    }


def _acquire_l2_probe_lock(run_id: str, task_id: int | None) -> None:
    L2_READONLY_PROBE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if L2_READONLY_PROBE_LOCK_FILE.exists():
        if not _l2_probe_lock_is_stale():
            raise HTTPException(status_code=409, detail='L2 readonly probe is already running')
        L2_READONLY_PROBE_LOCK_FILE.unlink(missing_ok=True)
    payload = _l2_probe_lock_payload(run_id=run_id, task_id=task_id, pid=None)
    try:
        fd = os.open(str(L2_READONLY_PROBE_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail='L2 readonly probe is already running') from exc
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)


def _write_l2_probe_lock(run_id: str, task_id: int | None, pid: int | None) -> None:
    payload = _l2_probe_lock_payload(run_id=run_id, task_id=task_id, pid=pid)
    L2_READONLY_PROBE_LOCK_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def _release_l2_probe_lock(run_id: str) -> None:
    try:
        payload = json.loads(L2_READONLY_PROBE_LOCK_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if payload.get('run_id') in (None, run_id):
        L2_READONLY_PROBE_LOCK_FILE.unlink(missing_ok=True)


def _l2_probe_lock_payload(run_id: str, task_id: int | None, pid: int | None) -> dict[str, Any]:
    return {
        'schema': 'dxm_l2_readonly_probe_lock.v1',
        'run_id': run_id,
        'task_id': task_id,
        'pid': pid,
        'created_at': datetime.now(timezone.utc).isoformat(),
    }


def _l2_probe_lock_is_stale() -> bool:
    try:
        payload = json.loads(L2_READONLY_PROBE_LOCK_FILE.read_text(encoding='utf-8'))
        created_at = datetime.fromisoformat(str(payload.get('created_at')))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return True
    return (datetime.now(timezone.utc) - created_at).total_seconds() > L2_READONLY_PROBE_LOCK_TTL_SECONDS


def _l2_probe_lock_status() -> dict[str, Any]:
    base = {
        'running': False,
        'stale': False,
        'runId': None,
        'taskId': None,
        'pid': None,
        'createdAt': None,
        'lockFile': str(L2_READONLY_PROBE_LOCK_FILE),
    }
    try:
        payload = json.loads(L2_READONLY_PROBE_LOCK_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return base
    stale = _l2_probe_lock_is_stale()
    return {
        **base,
        'running': not stale,
        'stale': stale,
        'runId': payload.get('run_id'),
        'taskId': payload.get('task_id'),
        'pid': payload.get('pid'),
        'createdAt': payload.get('created_at'),
    }


def _write_runtime_control_command(action: str, task_id: int | None) -> dict:
    RUNTIME_CONTROL_COMMAND_FILE.parent.mkdir(parents=True, exist_ok=True)
    command = {
        'schema': 'dxm_runtime_control_command.v1',
        'id': uuid.uuid4().hex,
        'source': 'backend-api',
        'action': action,
        'task_id': task_id,
        'requested_at': datetime.now(timezone.utc).isoformat(),
    }
    tmp_path = RUNTIME_CONTROL_COMMAND_FILE.with_suffix('.tmp')
    tmp_path.write_text(json.dumps(command, ensure_ascii=False), encoding='utf-8')
    tmp_path.replace(RUNTIME_CONTROL_COMMAND_FILE)
    return command


def _runtime_http_service_status(name: str, url: str) -> dict:
    if url.startswith('file://'):
        return {
            'status': 'ok',
            'url': url,
            'port': None,
            'detail': f'{name} 使用 Electron 桌面内置页面，无需监听前端端口。',
        }
    port = _url_port(url)
    reachable = _port_open('127.0.0.1', port) if port else False
    return {
        'status': 'ok' if reachable else 'down',
        'url': url,
        'port': port,
        'detail': f'{name} port is listening' if reachable else f'{name} port is not listening',
    }


def _url_port(url: str) -> int | None:
    try:
        if ':' not in url.rsplit('/', 1)[0]:
            return 443 if url.startswith('https://') else 80
        return int(url.rsplit(':', 1)[1].split('/', 1)[0])
    except (IndexError, ValueError):
        return None


def _port_open(host: str, port: int | None) -> bool:
    if not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


_FINAL_TWO_STAGE_REQUIRED_CHECKS = (
    'claim_task_present',
    'claim_completed',
    'save_task_completed',
    'claimed_product_present',
    'claim_provenance_valid',
    'single_save_claim_snapshot_valid',
    'claim_product_matches',
    'draft_box_verified',
    'single_save_linked_to_claim',
    'save_success',
    'unpublished_proof',
    'save_evidence_integrity',
    'unpublished_evidence_integrity',
    'publish_guard_safe',
    'state_consistent',
)


def _is_positive_json_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_empty_json_array(value: Any) -> bool:
    return isinstance(value, list) and not value


def _strict_final_two_stage_ready(
    acceptance: dict[str, Any],
    readiness: dict[str, Any],
) -> bool:
    checks = acceptance.get('checks')
    return (
        acceptance.get('schema') == 'dxm_two_stage_acceptance.v1'
        and acceptance.get('passed') is True
        and acceptance.get('status') == 'passed'
        and all(
            _is_positive_json_integer(acceptance.get(field))
            for field in ('claim_task_id', 'save_task_id', 'claimed_product_id')
        )
        and _is_empty_json_array(acceptance.get('missing_codes'))
        and _is_empty_json_array(acceptance.get('state_violation_codes'))
        and isinstance(checks, dict)
        and all(checks.get(field) is True for field in _FINAL_TWO_STAGE_REQUIRED_CHECKS)
        and readiness.get('ready') is True
        and readiness.get('status') == 'passed'
        and _is_empty_json_array(readiness.get('missing'))
        and isinstance(readiness.get('acceptance'), dict)
        and readiness.get('acceptance') == acceptance
    )


def _strict_final_state_consistency_ready(
    state_consistency: dict[str, Any],
    readiness: dict[str, Any],
) -> bool:
    audited_task_ids = state_consistency.get('audited_task_ids')
    return (
        state_consistency.get('schema') == 'dxm_state_consistency.v1'
        and state_consistency.get('consistent') is True
        and _is_empty_json_array(state_consistency.get('violation_codes'))
        and _is_empty_json_array(state_consistency.get('violations'))
        and isinstance(audited_task_ids, list)
        and bool(audited_task_ids)
        and all(_is_positive_json_integer(task_id) for task_id in audited_task_ids)
        and readiness.get('ready') is True
        and _is_empty_json_array(readiness.get('missing'))
        and isinstance(readiness.get('stateConsistency'), dict)
        and readiness.get('stateConsistency') == state_consistency
    )


def _read_final_delivery_check_summary():
    json_path = _final_delivery_check_json_path()
    if not json_path.exists():
        return {
            'status': 'not_run',
            'summary_path': None,
            'json_path': str(json_path),
        }
    try:
        payload = json.loads(json_path.read_text(encoding='utf-8-sig'))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            'status': 'unreadable',
            'summary_path': None,
            'json_path': str(json_path),
            'error': str(exc),
        }
    artifacts = payload.get('artifacts') if isinstance(payload.get('artifacts'), dict) else {}
    browser_qa = payload.get('browserQa') if isinstance(payload.get('browserQa'), dict) else {}
    browser_qa_manifest = browser_qa.get('manifest') if isinstance(browser_qa.get('manifest'), dict) else {}
    post_final_report_qa = payload.get('postFinalReportQa') if isinstance(payload.get('postFinalReportQa'), dict) else {}
    l2_allowlist_review_template = payload.get('l2AllowlistReviewTemplate') if isinstance(payload.get('l2AllowlistReviewTemplate'), dict) else {}
    l2_allowlist_review_candidates = l2_allowlist_review_template.get('candidates')
    l2_allowlist_review_template_hashes = payload.get('l2AllowlistReviewTemplateHashes') if isinstance(payload.get('l2AllowlistReviewTemplateHashes'), dict) else {}
    two_stage_acceptance = payload.get('twoStageAcceptance') if isinstance(payload.get('twoStageAcceptance'), dict) else {}
    two_stage_acceptance_readiness = payload.get('twoStageAcceptanceReadiness') if isinstance(payload.get('twoStageAcceptanceReadiness'), dict) else {}
    state_consistency = payload.get('stateConsistency') if isinstance(payload.get('stateConsistency'), dict) else {}
    state_consistency_readiness = payload.get('stateConsistencyReadiness') if isinstance(payload.get('stateConsistencyReadiness'), dict) else {}
    report_two_stage_end_to_end = (
        payload.get('realDxmTwoStageEndToEnd')
        or ('passed' if two_stage_acceptance.get('passed') is True else 'pending_live_dxm_validation')
    )
    expected_two_stage_end_to_end = payload.get('expectedRealDxmTwoStageEndToEnd') or report_two_stage_end_to_end
    two_stage_acceptance_matches_expected = payload.get('twoStageAcceptanceMatchesExpected')
    if two_stage_acceptance_matches_expected is None and expected_two_stage_end_to_end:
        two_stage_acceptance_matches_expected = report_two_stage_end_to_end == expected_two_stage_end_to_end
    current_git = _current_git_summary()
    current_gate = _current_real_dxm_gate_summary()
    report_git_head = payload.get('gitHead')
    browser_qa_git_head = browser_qa_manifest.get('gitHead')
    report_readiness = payload.get('realDxmWriteReadiness')
    current_readiness = current_gate.get('readiness')
    report_schema_ready = payload.get('schema') == 'dxm_final_delivery_check.v1'
    report_state_consistent = (
        report_schema_ready
        and _strict_final_state_consistency_ready(
            state_consistency,
            state_consistency_readiness,
        )
    )
    report_two_stage_ready = (
        report_schema_ready
        and _strict_final_two_stage_ready(
            two_stage_acceptance,
            two_stage_acceptance_readiness,
        )
        and payload.get('realDxmTwoStageEndToEnd') == 'passed'
    )
    current_two_stage_ready = (
        current_gate.get('two_stage_ready') is True
        and current_gate.get('two_stage_status') == 'passed'
    )
    matches_current = (
        bool(report_git_head)
        and report_git_head == current_git.get('head')
        and current_git.get('is_dirty') is False
    )
    final_check_freshness = _final_check_freshness(report_git_head, current_git)
    dirty_worktree_is_source_package_only = (
        final_check_freshness == 'dirty_worktree'
        and payload.get('requireCleanWorktree') is not True
        and payload.get('sourcePackageCheck') == 'NOT_REQUIRED'
    )
    stale_final_check_reason = (
        None
        if matches_current or dirty_worktree_is_source_package_only
        else _final_check_stale_blocked_reason(final_check_freshness)
    )
    runtime_gate_matches_report = bool(report_readiness and current_readiness and report_readiness == current_readiness)
    runtime_gate_freshness = (
        'current'
        if runtime_gate_matches_report
        else 'stale_gate'
        if report_readiness == 'READY' and current_readiness == 'BLOCKED'
        else 'unknown'
    )
    if stale_final_check_reason:
        effective_readiness = 'BLOCKED'
        effective_blocked_reason = stale_final_check_reason
        effective_mutation_allowed = False
        effective_two_stage_end_to_end = 'pending_live_dxm_validation'
    elif current_readiness not in {'READY', 'BLOCKED'}:
        effective_readiness = 'BLOCKED'
        effective_blocked_reason = (
            current_gate.get('blocked_reason')
            or '当前运行门禁不可读取；不可依据旧自检报告启动真实写入。'
        )
        effective_mutation_allowed = False
        effective_two_stage_end_to_end = 'pending_live_dxm_validation'
    else:
        effective_readiness = current_readiness
        effective_blocked_reason = (
            current_gate.get('blocked_reason')
            if effective_readiness == 'BLOCKED' and current_gate.get('blocked_reason')
            else payload.get('realDxmWriteBlockedReason')
        )
        effective_mutation_allowed = payload.get('realDxmMutationAllowed') is True and effective_readiness == 'READY'
        effective_two_stage_end_to_end = (
            'passed'
            if report_two_stage_ready and current_two_stage_ready
            else 'pending_live_dxm_validation'
        )
    if not report_two_stage_ready or not current_two_stage_ready:
        if effective_readiness != 'BLOCKED' or not effective_blocked_reason:
            if not report_two_stage_ready:
                effective_blocked_reason = (
                    'Two-stage acceptance is missing, contradictory, or not passed in the final-check report; '
                    'READY remains blocked.'
                )
            else:
                effective_blocked_reason = (
                    current_gate.get('blocked_reason')
                    or 'Two-stage acceptance is missing, contradictory, or not passed in the current workspace; READY remains blocked.'
                )
        effective_readiness = 'BLOCKED'
        effective_mutation_allowed = False
        effective_two_stage_end_to_end = 'pending_live_dxm_validation'
    if not report_state_consistent:
        state_codes = ', '.join(str(code) for code in state_consistency.get('violation_codes') or [])
        if effective_readiness != 'BLOCKED' or not effective_blocked_reason:
            effective_blocked_reason = f"State consistency is not passed: {state_codes or 'state consistency unavailable'}; READY remains blocked."
        effective_readiness = 'BLOCKED'
        effective_mutation_allowed = False
        effective_two_stage_end_to_end = 'pending_live_dxm_validation'
    effective_mutation_scope = payload.get('realDxmMutationScope') if effective_mutation_allowed else 'none'
    expected_readiness = payload.get('expectedRealDxmWriteReadiness') or report_readiness
    effective_readiness_matches_expected = (
        None
        if not expected_readiness or not effective_readiness
        else effective_readiness == expected_readiness
    )
    production_delivery_ready = (
        payload.get('productionDeliveryReady') is True
        and effective_two_stage_end_to_end == 'passed'
        and effective_readiness == 'READY'
    )
    return {
        'status': 'available',
        'checked_at': payload.get('checkedAt'),
        'local_workbench_check': payload.get('localWorkbenchCheck'),
        'real_dxm_write_readiness': report_readiness,
        'current_real_dxm_write_readiness': current_readiness,
        'current_real_dxm_write_blocked_reason': current_gate.get('blocked_reason'),
        'current_l2_gate_status': current_gate.get('l2_status'),
        'current_l3_gate_status': current_gate.get('l3_status'),
        'final_check_runtime_gate_matches_report': runtime_gate_matches_report,
        'final_check_runtime_gate_freshness': runtime_gate_freshness,
        'effective_real_dxm_write_readiness': effective_readiness,
        'effective_real_dxm_write_blocked_reason': effective_blocked_reason,
        'effective_real_dxm_mutation_allowed': effective_mutation_allowed,
        'effective_real_dxm_mutation_scope': effective_mutation_scope,
        'real_dxm_two_stage_end_to_end': report_two_stage_end_to_end,
        'expected_real_dxm_two_stage_end_to_end': expected_two_stage_end_to_end,
        'effective_real_dxm_two_stage_end_to_end': effective_two_stage_end_to_end,
        'two_stage_acceptance': two_stage_acceptance,
        'two_stage_acceptance_readiness': two_stage_acceptance_readiness,
        'two_stage_acceptance_matches_expected': two_stage_acceptance_matches_expected,
        'state_consistency': state_consistency,
        'state_consistency_readiness': state_consistency_readiness,
        'current_state_consistent': current_gate.get('state_consistent'),
        'current_state_violation_codes': current_gate.get('state_violation_codes') or [],
        'current_two_stage_ready': current_gate.get('two_stage_ready'),
        'current_two_stage_status': current_gate.get('two_stage_status'),
        'production_delivery_ready': production_delivery_ready,
        'final_delivery_completed': production_delivery_ready,
        'production_real_write_ready': payload.get('productionRealWriteReady'),
        'real_dxm_write_blocked_reason': payload.get('realDxmWriteBlockedReason'),
        'l3_evidence_readiness': payload.get('l3EvidenceReadiness'),
        'ok_scope': payload.get('okScope'),
        'real_dxm_mutation_allowed': payload.get('realDxmMutationAllowed'),
        'real_dxm_mutation_scope': payload.get('realDxmMutationScope'),
        'controlled_single_save_ready': payload.get('controlledSingleSaveReady'),
        'batch_unattended_publish_allowed': payload.get('batchUnattendedPublishAllowed'),
        'real_mode_release_plan': payload.get('realModeReleasePlan'),
        'expected_real_dxm_write_readiness': expected_readiness,
        'real_dxm_write_readiness_matches_expected': payload.get('realDxmWriteReadinessMatchesExpected'),
        'effective_real_dxm_write_readiness_matches_expected': effective_readiness_matches_expected,
        'source_package_readiness': payload.get('sourcePackageReadiness'),
        'source_package_check': payload.get('sourcePackageCheck'),
        'require_clean_worktree': payload.get('requireCleanWorktree'),
        'git_head': report_git_head,
        'current_git_head': current_git.get('head'),
        'current_git_status_short': current_git.get('status_short'),
        'current_git_is_dirty': current_git.get('is_dirty'),
        'final_check_matches_current_worktree': matches_current,
        'final_check_freshness': final_check_freshness,
        'browser_qa_ok': browser_qa.get('ok'),
        'browser_qa_checked_at': browser_qa.get('checkedAt'),
        'browser_qa_git_head': browser_qa_git_head,
        'browser_qa_git_status_short': browser_qa_manifest.get('gitStatusShort'),
        'browser_qa_matches_report_git_head': bool(report_git_head and browser_qa_git_head and report_git_head == browser_qa_git_head),
        'browser_qa_screenshot_hashes': browser_qa.get('screenshotHashes'),
        'post_final_report_qa_ok': post_final_report_qa.get('ok'),
        'post_final_report_qa_checked_at': post_final_report_qa.get('checkedAt'),
        'post_final_report_qa_screenshot_hashes': post_final_report_qa.get('screenshotHashes'),
        'qa_services': payload.get('qaServices'),
        'gates': payload.get('gates'),
        'summary_path': artifacts.get('summary'),
        'final_report_center_screenshot_path': artifacts.get('finalReportCenterScreenshot'),
        'post_final_report_qa_json_path': artifacts.get('postFinalReportQaJson'),
        'l2_allowlist_review_template_state': l2_allowlist_review_template.get('reviewState'),
        'l2_allowlist_review_template_candidate_count': len(l2_allowlist_review_candidates) if isinstance(l2_allowlist_review_candidates, list) else 0,
        'l2_allowlist_review_template_markdown_path': artifacts.get('l2AllowlistReviewTemplateMarkdown'),
        'l2_allowlist_review_template_json_path': artifacts.get('l2AllowlistReviewTemplateJson'),
        'l2_allowlist_review_template_markdown_sha256': l2_allowlist_review_template_hashes.get('markdown_sha256'),
        'l2_allowlist_review_template_json_sha256': l2_allowlist_review_template_hashes.get('json_sha256'),
        'json_path': str(json_path),
    }


def _final_delivery_check_json_path():
    configured = os.environ.get('DXM_FINAL_DELIVERY_CHECK_JSON')
    if configured:
        return Path(configured).expanduser().resolve()
    return FINAL_DELIVERY_CHECK_JSON


def _current_git_summary():
    try:
        head = subprocess.check_output(
            ['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        status_short = subprocess.check_output(
            ['git', '-C', str(REPO_ROOT), 'status', '--short'],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return {
            'head': None,
            'status_short': None,
            'is_dirty': None,
        }
    return {
        'head': head,
        'status_short': status_short,
        'is_dirty': bool(status_short),
    }


def _current_real_dxm_gate_summary():
    try:
        workspace = build_delivery_workspace(repo)
    except Exception:
        return {
            'readiness': 'BLOCKED',
            'blocked_reason': '当前运行门禁不可读取；不可依据旧自检报告启动真实写入。',
            'l2_status': None,
            'l3_status': None,
            'delivery_ready': False,
            'two_stage_ready': False,
            'two_stage_status': None,
            'state_consistent': False,
            'state_violation_codes': [],
        }
    gates = workspace.get('regression_gates') if isinstance(workspace, dict) else []
    l2_gate = _workspace_gate(gates, 'L2')
    l3_gate = _workspace_gate(gates, 'L3')
    delivery_readiness = workspace.get('delivery_readiness') if isinstance(workspace, dict) else {}
    delivery_ready = delivery_readiness.get('ready') is True if isinstance(delivery_readiness, dict) else False
    two_stage_acceptance = workspace.get('two_stage_acceptance') if isinstance(workspace, dict) else {}
    two_stage_ready = two_stage_acceptance.get('passed') is True if isinstance(two_stage_acceptance, dict) else False
    two_stage_status = two_stage_acceptance.get('status') if isinstance(two_stage_acceptance, dict) else None
    state_consistency = workspace.get('state_consistency') if isinstance(workspace, dict) else {}
    state_consistent = state_consistency.get('consistent') is True if isinstance(state_consistency, dict) else False
    state_violation_codes = list(state_consistency.get('violation_codes') or []) if isinstance(state_consistency, dict) else []
    l2_status = l2_gate.get('status') if l2_gate else None
    l3_status = l3_gate.get('status') if l3_gate else None
    if l2_status == 'passed' and l3_status == 'passed' and delivery_ready and two_stage_ready and state_consistent:
        return {
            'readiness': 'READY',
            'blocked_reason': '',
            'l2_status': l2_status,
            'l3_status': l3_status,
            'delivery_ready': delivery_ready,
            'two_stage_ready': two_stage_ready,
            'two_stage_status': two_stage_status,
            'state_consistent': state_consistent,
            'state_violation_codes': state_violation_codes,
        }
    if not l2_gate or not l3_gate:
        reason = '当前运行门禁缺少 L2/L3 记录；不可依据旧自检报告启动真实写入。'
    elif l2_status != 'passed':
        reason = f"L2 gate is {l2_status}; {l2_gate.get('detail') or 'real DXM writes require fresh dual-target readonly evidence.'}"
    elif l3_status != 'passed':
        reason = f"L3 gate is {l3_status}; {l3_gate.get('detail') or 'real DXM writes require fresh single_save canary evidence.'}"
    elif not two_stage_ready:
        reason = f"Two-stage acceptance is not passed: {two_stage_status or 'missing'}; claim and save proof are both required."
    elif not state_consistent:
        codes = ', '.join(str(code) for code in state_violation_codes)
        reason = f"State consistency is not passed: {codes or 'state consistency unavailable'}; READY remains blocked."
    else:
        reason = 'Delivery readiness is incomplete in the current workspace.'
    return {
        'readiness': 'BLOCKED',
        'blocked_reason': reason,
        'l2_status': l2_status,
        'l3_status': l3_status,
        'delivery_ready': delivery_ready,
        'two_stage_ready': two_stage_ready,
        'two_stage_status': two_stage_status,
        'state_consistent': state_consistent,
        'state_violation_codes': state_violation_codes,
    }


def _workspace_gate(gates, level: str):
    for gate in gates or []:
        if isinstance(gate, dict) and gate.get('level') == level:
            return gate
    return None


def _final_check_freshness(report_git_head, current_git):
    current_head = current_git.get('head')
    if not report_git_head or not current_head:
        return 'unknown'
    if report_git_head != current_head:
        return 'stale_head'
    if current_git.get('is_dirty') is True:
        return 'dirty_worktree'
    if current_git.get('is_dirty') is False:
        return 'current'
    return 'unknown'


def _final_check_stale_blocked_reason(freshness: str) -> str:
    if freshness == 'dirty_worktree':
        return '最终验收未覆盖当前代码：当前工作区还有未提交改动，请重新运行最终验收后再启动真实保存。'
    if freshness == 'stale_head':
        return '最终验收未覆盖当前代码：报告对应的代码版本不是当前版本，请重新运行最终验收后再启动真实保存。'
    return '最终验收未覆盖当前代码：无法确认报告与当前代码一致，请重新运行最终验收后再启动真实保存。'


def _authorization_now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_authorization_value(value: Any) -> Any:
    volatile_keys = {
        'ageseconds',
        'checkedat',
        'detail',
        'earliest',
        'latestat',
        'now',
        'newestageseconds',
        'skewseconds',
        'timestamp',
        'updatedat',
    }
    if isinstance(value, dict):
        return {
            str(key): _stable_authorization_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key).replace('_', '').casefold() not in volatile_keys
        }
    if isinstance(value, list):
        return [_stable_authorization_value(item) for item in value]
    return value


def _l2_authorization_fingerprint(l2_gate: dict[str, Any]) -> str:
    canonical = json.dumps(
        _stable_authorization_value(l2_gate),
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest().upper()


def _current_browser_session_id() -> str:
    status = browser_agent_runtime.status()
    session_id = str(status.get('sessionId') or '').strip() if isinstance(status, dict) else ''
    if not session_id:
        raise HTTPException(status_code=409, detail='AUTH_BROWSER_SESSION_MISSING: browser authorization session is unavailable')
    return session_id


def _build_task_stage_facts(task: dict[str, Any]) -> dict[str, Any]:
    payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
    jobs = task.get('jobs') if isinstance(task.get('jobs'), list) else []
    if len(jobs) != 1:
        raise HTTPException(status_code=409, detail='AUTH_TASK_JOB_SHAPE_MISMATCH: exactly one job is required')
    job = jobs[0]
    try:
        if task.get('mode') == 'claim_only':
            target_identity = canonical_claim_target_identity(
                payload.get('source_url'),
                payload.get('source_urls') or (),
                keyword=payload.get('keyword'),
                category_name=payload.get('category_name'),
            )
            return build_stage_a_task_facts(
                task_id=int(task['id']),
                job_id=int(job['id']),
                store_id=int(task['store_id']),
                target_identity=target_identity,
            )
        product = repo.get_product(int(job['product_id']))
        if not product:
            raise HTTPException(status_code=409, detail='AUTH_PRODUCT_NOT_FOUND: Stage B product is unavailable')
        snapshot_error = repo.single_save_claim_snapshot_error(task, product)
        if snapshot_error:
            raise HTTPException(
                status_code=409,
                detail=f'AUTH_STAGE_B_SNAPSHOT_MISMATCH: {snapshot_error}',
            )
        return build_stage_b_task_facts(
            task_id=int(task['id']),
            job_id=int(job['id']),
            store_id=int(task['store_id']),
            product_id=int(product['id']),
            stage_a_task_facts=payload['stage_a_task_facts'],
            draft_box_proof=payload['draft_box_proof'],
        )
    except (KeyError, TypeError, ValueError, TwoStageContractError) as exc:
        reason_code = getattr(exc, 'reason_code', 'AUTH_TASK_FACTS_INVALID')
        raise HTTPException(status_code=409, detail=f'{reason_code}: exact two-stage task facts are invalid') from exc


def _build_task_authorization_context(
    task: dict[str, Any],
    *,
    approved_by: str,
    l2_gate: dict[str, Any],
) -> dict[str, Any]:
    git_head = str(_current_git_summary().get('head') or '').strip()
    try:
        return build_authorization_context(
            stage_task_facts=_build_task_stage_facts(task),
            runtime_instance_id=str(runtime_identity.instance_id),
            browser_session_id=_current_browser_session_id(),
            git_head=git_head,
            l2_evidence_fingerprint=_l2_authorization_fingerprint(l2_gate),
            approved_by=approved_by,
        )
    except TwoStageContractError as exc:
        raise HTTPException(status_code=409, detail=f'{exc.reason_code}: authorization context is invalid') from exc


def _verify_runner_authorization(task_id: int, mode: str, state: str) -> dict[str, Any]:
    required_state = {
        'claim_only': 'CLAIM_TO_DRAFT_BOX',
        'single_save': 'SAVE_ONLY',
    }.get(mode)
    if required_state is None or state != required_state:
        return {'ok': False, 'reason_code': 'AUTH_MUTATION_SCOPE_MISMATCH'}
    task = repo.get_task_private(task_id)
    if not task:
        return {'ok': False, 'reason_code': 'AUTH_TASK_NOT_FOUND'}
    payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
    approval = payload.get('manual_approval') if isinstance(payload.get('manual_approval'), dict) else {}
    approved_by = str(approval.get('approved_by') or '').strip()
    if not approved_by:
        return {'ok': False, 'reason_code': 'AUTH_APPROVER_MISSING'}
    l2_gate = l2_real_probe_gate()
    if l2_gate.get('status') != 'passed':
        return {'ok': False, 'reason_code': 'AUTH_L2_GATE_NOT_PASSED'}
    try:
        current_context = _build_task_authorization_context(
            task,
            approved_by=approved_by,
            l2_gate=l2_gate,
        )
    except HTTPException as exc:
        detail = str(exc.detail or '')
        reason_code = detail.split(':', 1)[0] if ':' in detail else 'AUTH_CONTEXT_REBUILD_FAILED'
        return {'ok': False, 'reason_code': reason_code}
    result = repo.verify_consumed_task_authorization(
        task_id,
        authorization_context=current_context,
        checked_at=_authorization_now().isoformat(),
    )
    return {'ok': result.ok, 'reason_code': result.reason_code}


def _assert_task_can_receive_manual_approval(task_id: int, request: TaskManualApprovalRequest) -> str:
    task = repo.get_task_private(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    mode = str(task.get('mode') or (task.get('payload') or {}).get('execution_mode') or '')
    if mode not in REAL_DXM_MUTATION_MODES:
        raise HTTPException(status_code=400, detail=f'Manual approval is only available for real DXM mutation modes: {mode}')
    if mode not in RELEASED_REAL_DXM_MUTATION_MODES:
        raise HTTPException(status_code=403, detail=UNRELEASED_REAL_DXM_MODE_DETAIL)
    if task.get('status') != 'draft':
        raise HTTPException(status_code=409, detail=f"Task cannot be approved from status: {task.get('status')}")
    if mode == 'claim_only':
        if str(task.get('publish_scene') or '') != CLAIM_TO_DRAFT_PUBLISH_SCENE:
            raise HTTPException(status_code=403, detail='Controlled claim_only task requires claim-to-draft scene')
        _assert_claim_only_acquisition_task(task)
    else:
        _assert_single_save_product_count(task.get('payload') or {}, status_code=409)
        _assert_single_save_uses_claimed_draft_product((task.get('payload') or {}).get('product_ids') or [])
        if str(task.get('publish_scene') or '') != SAVE_ONLY_PUBLISH_SCENE:
            raise HTTPException(status_code=403, detail='Real DXM mutation task requires save-only publish scene')
    required_confirmation = CLAIM_CONFIRMATION if mode == 'claim_only' else L3_CONFIRMATION
    if not request.approved_by or not request.approved_by.strip():
        raise HTTPException(status_code=400, detail='approved_by is required')
    if request.confirmation != required_confirmation:
        raise HTTPException(status_code=400, detail=f'confirmation must be {required_confirmation}')
    l2_gate = l2_real_probe_gate()
    if l2_gate.get('status') != 'passed':
        raise HTTPException(
            status_code=403,
            detail=f"L2 readonly probe gate is not passed: {l2_gate.get('status')}",
        )
    return required_confirmation


def _assert_task_can_start(task_id: int, request: TaskStartRequest) -> dict[str, Any] | None:
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
        return None
    _assert_workflow_runtime_healthy()
    if mode not in RELEASED_REAL_DXM_MUTATION_MODES:
        raise HTTPException(status_code=403, detail=UNRELEASED_REAL_DXM_MODE_DETAIL)
    if mode == 'claim_only':
        if str(task.get('publish_scene') or '') != CLAIM_TO_DRAFT_PUBLISH_SCENE:
            raise HTTPException(status_code=403, detail='Controlled claim_only task requires claim-to-draft scene')
        _assert_claim_only_acquisition_task(task)
    else:
        _assert_single_save_product_count(task.get('payload') or {}, status_code=409)
        _assert_single_save_uses_claimed_draft_product(payload.get('product_ids') or [])
        if str(task.get('publish_scene') or '') != SAVE_ONLY_PUBLISH_SCENE:
            raise HTTPException(status_code=403, detail='Real DXM mutation task requires save-only publish scene')

    approval = payload.get('manual_approval') or {}
    if not isinstance(approval, dict):
        approval = {}
    token_hash = approval.get('token_hash')
    request_token_hash = hashlib.sha256(request.approval_token.encode('utf-8')).hexdigest() if request.approval_token else ''
    token_ok = bool(token_hash and hmac.compare_digest(request_token_hash, str(token_hash)))
    request_approver = str(request.approved_by or '').strip()
    stored_approver = str(approval.get('approved_by') or '').strip()
    approver_ok = bool(
        request_approver
        and stored_approver
        and hmac.compare_digest(request_approver.encode('utf-8'), stored_approver.encode('utf-8'))
    )
    required_confirmation = CLAIM_CONFIRMATION if mode == 'claim_only' else L3_CONFIRMATION
    approved = (
        request.manual_approval is True
        and request.confirmation == required_confirmation
        and approver_ok
        and approval.get('approved') is True
        and approval.get('source') == 'server'
        and token_ok
    )
    if not approved:
        raise HTTPException(
            status_code=403,
            detail=(
                f'Manual approval with confirmation {required_confirmation} is required before starting real {mode}; '
                'approved_by must match the stored server approver'
            ),
        )
    l2_gate = l2_real_probe_gate()
    if l2_gate.get('status') != 'passed':
        raise HTTPException(
            status_code=403,
            detail=f"L2 readonly probe gate is not passed: {l2_gate.get('status')}",
        )
    return _build_task_authorization_context(
        task,
        approved_by=request_approver,
        l2_gate=l2_gate,
    )


def _assert_workflow_runtime_healthy() -> None:
    reason = str(getattr(runner, 'workflow_runtime_unhealthy_reason', '') or '').strip() or _browser_agent_unhealthy_reason()
    if not reason:
        return
    raise HTTPException(
        status_code=409,
        detail=f'真实浏览器执行器需要重启：{reason}',
    )


def _assert_task_create_scope(payload: TaskCreate) -> None:
    mode = str(payload.mode or '').strip()
    if mode in REAL_DXM_MUTATION_MODES and mode not in RELEASED_REAL_DXM_MUTATION_MODES:
        raise HTTPException(status_code=403, detail=UNRELEASED_REAL_DXM_MODE_DETAIL)
    if mode == 'claim_only' and str(payload.publish_scene or '') != CLAIM_TO_DRAFT_PUBLISH_SCENE:
        raise HTTPException(status_code=403, detail='Controlled claim_only task requires claim-to-draft scene')
    if mode == 'claim_only' and payload.product_ids:
        raise HTTPException(
            status_code=400,
            detail='Controlled claim_only must be created from acquisition claim request without existing product_ids',
        )
    if mode == 'single_save':
        _assert_single_save_product_count({'product_ids': payload.product_ids}, status_code=400)
        _assert_single_save_uses_claimed_draft_product(
            payload.product_ids,
            expected_store_id=payload.store_id,
        )


def _assert_claim_only_acquisition_task(task: dict[str, Any]) -> None:
    jobs = task.get('jobs') if isinstance(task.get('jobs'), list) else []
    if not jobs:
        raise HTTPException(status_code=409, detail='待认领商品任务缺少认领作业，请重新创建任务。')
    if any(job.get('product_id') is not None for job in jobs if isinstance(job, dict)):
        raise HTTPException(
            status_code=409,
            detail='待认领入箱必须从店小秘已有待认领列表开始，不能直接绑定本地商品。',
        )


def _assert_single_save_uses_claimed_draft_product(
    product_ids: list[int],
    *,
    expected_store_id: int | None = None,
) -> None:
    product_id = int(product_ids[0])
    product = repo.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail=f'Product not found: {product_id}')
    status = str(product.get('status') or '')
    payload = product.get('payload') if isinstance(product.get('payload'), dict) else {}
    source = str(payload.get('source') or product.get('source') or '').strip()
    if status not in {'claimed_to_draft', 'ready_for_edit'}:
        raise HTTPException(
            status_code=409,
            detail=(
                '编辑保存必须从商品箱里的真实商品开始。'
                '请先完成“待认领商品”，确认商品已进入商品箱后，再创建单商品只保存任务。'
            ),
        )
    if source != 'dxm_data_acquisition':
        raise HTTPException(
            status_code=409,
            detail=(
                '编辑保存必须从店小秘已有待认领商品进入商品箱的商品开始。'
                '请先完成“待认领商品”，不要使用手工创建或本地导入商品。'
            ),
        )
    if payload.get('draft_box_verified') is not True:
        raise HTTPException(
            status_code=409,
            detail=(
                '编辑保存必须先确认商品已进入商品箱。'
                '请确认商品已进入商品箱后，再创建单商品只保存任务。'
            ),
        )
    source_url = ''
    for key in ('source_url', 'url'):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            source_url = value.strip()
            break
    if not source_url:
        values = payload.get('source_urls')
        if isinstance(values, list):
            source_url = next((str(value).strip() for value in values if str(value or '').strip()), '')
    if not source_url:
        raise HTTPException(
            status_code=409,
            detail=(
                '编辑保存缺少商品箱身份校验证据。'
                '请重新完成“待认领商品”，并确认商品箱中能唯一匹配本次商品后再创建任务。'
            ),
        )
    if not repo.product_has_completed_claim_provenance(product):
        raise HTTPException(
            status_code=409,
            detail=(
                '编辑保存必须能追溯到已完成的待认领商品任务链。'
                '请先从“待认领商品”完成真实认领，并确认商品进入商品箱后再创建任务。'
            ),
        )
    product_store_id = payload.get('store_id')
    proof = payload.get('draft_box_proof') if isinstance(payload.get('draft_box_proof'), dict) else {}
    proof_store_id = proof.get('store_id')
    if expected_store_id is not None and (
        isinstance(expected_store_id, bool)
        or isinstance(product_store_id, bool)
        or isinstance(proof_store_id, bool)
        or not isinstance(product_store_id, int)
        or not isinstance(proof_store_id, int)
        or product_store_id != int(expected_store_id)
        or proof_store_id != int(expected_store_id)
    ):
        raise HTTPException(
            status_code=409,
            detail='单商品只保存的店铺与认领证明店铺不一致；请在原认领店铺中创建保存任务。',
        )


def _assert_single_save_product_count(payload: dict[str, Any], *, status_code: int) -> None:
    product_ids = payload.get('product_ids') if isinstance(payload, dict) else None
    product_count = len(product_ids) if isinstance(product_ids, list) else 0
    if product_count != 1:
        raise HTTPException(
            status_code=status_code,
            detail=f'single_save requires exactly one product; got {product_count}',
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
    raise HTTPException(
        status_code=403,
        detail='Direct real DXM mutation must run through the task runner evidence chain',
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


def _run_login_flow(func, *args, **kwargs):
    return login_flow_executor.submit(func, *args, **kwargs).result()


def _login_flow_failure_state(label: str, message: str, next_action: str, raw_error: str | None = None) -> dict[str, Any]:
    return {
        'stage': 'login_failed',
        'label': label,
        'message': message,
        'next_action': next_action,
        'raw_error': raw_error,
        'requires_user_action': True,
        'page_title': '店小秘登录浏览器',
        'page_url': 'https://www.dianxiaomi.com/',
        'screenshot_url': None,
        'browser_visible': False,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


def _workflow_navigation_failure_state(target: str, raw_error: str | None = None) -> dict[str, Any]:
    return {
        'stage': 'workflow_navigation_failed',
        'label': '进入失败',
        'message': '真实店小秘业务页进入失败。请按下一步处理，原始错误已保留到诊断字段和实时日志。',
        'next_action': '请确认真实浏览器窗口仍然打开且已登录；必要时重新打开真实登录页，再进入目标业务页。',
        'raw_error': raw_error,
        'requires_user_action': True,
        'target': target,
        'page_title': '店小秘业务页',
        'page_url': 'https://www.dianxiaomi.com/',
        'screenshot_url': None,
        'browser_visible': False,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


def _workflow_adapter():
    return DxmWorkflowAdapter(login_flow)


def build_login_state(data: dict):
    if data.get('logged_in'):
        return {
            'stage': 'login_success',
            'label': '已登录',
            'message': '已检测到真实店小秘登录态；受控 claim_only 可按 Stage A 审批启动，受控 single_save 可按 Stage B 审批启动。',
            'next_action': '先完成配置预检和 L2 复验，再按各自人工审批启动；batch_save 和发布仍关闭。',
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
