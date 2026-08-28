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
import time
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Mapping, NoReturn
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.core.config import DATA_DIR
from src.services.operation_audit import (
    OperationAuditError,
    get_audit_service,
    record_best_effort,
)
from src.services.runtime_bootstrap import ensure_runtime_bootstrap


APP_VERSION = '0.3.0'
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
from src.execution.browser_agent_protocol import (
    MutationCommandContractError,
    canonical_frozen_target_identity,
    canonical_mutation_target_payload,
    mutation_target_hash,
    validate_browser_agent_command,
)
from src.execution.batch_command_contract import (
    BatchCommandContractError,
    validate_current_batch_queue_guard,
)
from src.execution.batch_dispatch_authority import LiveDispatchFacts
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.playwright_engine import PlaywrightEngine
from src.execution.v1_runner import V1TaskRunner
from src.models import (
    AIConfigUpdateRequest,
    AgentConsoleBrowserDiagnosticsRequest,
    AgentConsoleControlRequest,
    AgentConsoleHudRequest,
    AgentConsoleStartRequest,
    DraftBoxActionRequest,
    DraftBoxScopeSnapshotCreate,
    DxmTemplateShopSyncRequest,
    DxmTemplateRefSyncRequest,
    EditBatchApproveAndStartRequest,
    EditBatchCreate,
    EditBatchBundleComposeRequest,
    EditBatchManualApprovalRequest,
    EditBatchStopRequest,
    HealthResponse,
    LoginContinueRequest,
    LoginNavigateRequest,
    LoginStartRequest,
    LocalPlanTemplateRequest,
    PlanSnapshotRequest,
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
from src.batch_edit import (
    BatchEditContractError,
    BatchEditCoordinator,
    BundleComposerError,
    EditBatchBundleComposer,
)
from src.batch_edit.plan_contract import E2PlanService, PlanContractError
from src.batch_edit.plan_snapshot_compiler import (
    PLAN_PATH_EXECUTION_NOT_RELEASED,
    WorkflowMandatoryCapabilityChecker,
    is_plan_execution_path_released,
)
from src.batch_edit.frozen_execution_contract import (
    FrozenExecutionContractError,
    compile_frozen_execution_payload,
    validate_frozen_execution_defaults,
)
from src.batch_edit.plan_schema_contract import PlanSchemaError
from src.repository import Repository
from src.services.config_defaults import DEFAULT_TEMPLATE_TYPES
from src.services.title_ai import TitleAIService
from src.services.selector_profile import SelectorProfileService
from src.services.delivery_workspace import build_delivery_workspace, l2_real_probe_gate
from src.services.agent_console import AgentConsoleService
from src.services.config_preview import ConfigPreviewService
from src.services.dxm_reference_templates import (
    configured_unsupported_reference_sections,
    resolve_dxm_reference_templates,
)
from src.services.dxm_draft_reader import DxmDraftReader, DxmDraftReaderError
from src.services.dxm_plan_reader import DxmPlanReader, DxmPlanReaderError
from src.services.dxm_editor_model import build_dxm_editor_models
from src.services.template_center import template_center_metadata
from src.state_machine.batch_draft_authorization import (
    BatchDraftAuthorizationError,
    authorization_context_fingerprint as batch_authorization_context_fingerprint,
    build_authorization_context as build_batch_authorization_context,
    build_batch_draft_save_task_facts,
)
from src.state_machine.save_authorization import (
    SaveOnlyContractError,
    build_authorization_context as build_save_authorization_context,
    build_save_task_facts,
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
login_flow_api_lock = Lock()
workflow_adapter = DxmWorkflowAdapter(login_flow)


def _mutation_dispatch_live_facts() -> LiveDispatchFacts:
    git_summary = _current_git_summary()
    l2_gate = l2_real_probe_gate()
    return LiveDispatchFacts(
        runtime_instance_id=str(runtime_identity.instance_id),
        browser_runtime_id=browser_agent_runtime.runtime_id,
        browser_session_id=str(workflow_adapter.browser_session_id() or ""),
        git_head=str(git_summary.get("head") or ""),
        worktree_identity=_current_execution_worktree_identity(git_summary),
        l2_status=str(l2_gate.get("status") or ""),
        l2_evidence_fingerprint=_l2_authorization_fingerprint(l2_gate),
        account_ref_hash=workflow_adapter.refresh_account_context_hash(),
    )


mutation_dispatch_ledger = MutationDispatchLedger(
    live_facts_provider=_mutation_dispatch_live_facts,
)
browser_agent_runtime = BrowserAgentRuntime(
    workflow_adapter,
    mutation_ledger=mutation_dispatch_ledger,
)


def _current_batch_l2_verification() -> dict[str, str]:
    """Return the current L2 state through the batch runtime's narrow contract."""

    gate = l2_real_probe_gate()
    return {
        'status': str(gate.get('status') or ''),
        'fingerprint': _l2_authorization_fingerprint(gate),
    }


def _reject_batch_command_authorization(reason_code: str) -> dict[str, Any]:
    return {'ok': False, 'reason_code': reason_code}


def _verify_batch_draft_save_command_authorization(
    command: Any,
    context: Any,
) -> dict[str, Any]:
    """Bind the JIT grant to the exact frozen job command being dispatched."""

    try:
        validate_browser_agent_command(command)
    except (MutationCommandContractError, TypeError, ValueError):
        return _reject_batch_command_authorization('AUTH_COMMAND_CONTRACT_INVALID')
    if (
        command.state != 'SAVE_ONLY'
        or command.action != 'save_only'
        or command.execution_mode != 'batch_draft_save'
        or command.expected_page != 'editor'
        or not isinstance(command.params, dict)
    ):
        return _reject_batch_command_authorization('AUTH_COMMAND_MODE_MISMATCH')
    if (
        not isinstance(context, Mapping)
        or context.get('mutation_action') != 'save_only_click'
    ):
        return _reject_batch_command_authorization('AUTH_COMMAND_MUTATION_MISMATCH')
    if (
        isinstance(command.task_id, bool)
        or not isinstance(command.task_id, int)
        or command.task_id <= 0
        or isinstance(command.job_id, bool)
        or not isinstance(command.job_id, int)
        or command.job_id <= 0
    ):
        return _reject_batch_command_authorization('AUTH_COMMAND_JOB_MISMATCH')

    task = repo.get_task_private(command.task_id)
    if not isinstance(task, Mapping):
        return _reject_batch_command_authorization('AUTH_TASK_NOT_FOUND')
    if str(task.get('mode') or '').strip() != 'batch_draft_save':
        return _reject_batch_command_authorization('AUTH_COMMAND_MODE_MISMATCH')
    try:
        snapshot = E2PlanService().assert_task_snapshot_binding(task)
    except PlanContractError:
        return _reject_batch_command_authorization('AUTH_COMMAND_SNAPSHOT_MISMATCH')

    jobs = task.get('jobs') if isinstance(task.get('jobs'), list) else []
    matching_jobs = [
        (index, job)
        for index, job in enumerate(jobs)
        if isinstance(job, Mapping) and job.get('id') == command.job_id
    ]
    if len(matching_jobs) != 1:
        return _reject_batch_command_authorization('AUTH_COMMAND_JOB_MISMATCH')
    queue_index, job = matching_jobs[0]
    item_snapshots = (
        snapshot.get('item_snapshots')
        if isinstance(snapshot.get('item_snapshots'), list)
        else []
    )
    if queue_index >= len(item_snapshots) or not isinstance(item_snapshots[queue_index], Mapping):
        return _reject_batch_command_authorization('AUTH_COMMAND_JOB_MISMATCH')
    item_snapshot = item_snapshots[queue_index]
    product_id = job.get('product_id')
    if (
        isinstance(product_id, bool)
        or not isinstance(product_id, int)
        or product_id <= 0
        or str(item_snapshot.get('product_id') or '') != str(product_id)
    ):
        return _reject_batch_command_authorization('AUTH_COMMAND_JOB_MISMATCH')
    try:
        validate_current_batch_queue_guard(
            task,
            command.job_id,
            command.params.get('batch_queue_guard'),
        )
    except BatchCommandContractError:
        return _reject_batch_command_authorization(
            'AUTH_COMMAND_QUEUE_STATE_MISMATCH'
        )
    try:
        expected_execution_payload = compile_frozen_execution_payload(task, job)
        actual_execution_payload = validate_frozen_execution_defaults(
            command.params.get('defaults'),
            expected_payload=expected_execution_payload,
        )
    except FrozenExecutionContractError:
        return _reject_batch_command_authorization(
            'AUTH_COMMAND_EXECUTION_MISMATCH'
        )
    if not hmac.compare_digest(
        str(command.execution_payload_hash or '').casefold(),
        str(actual_execution_payload.get('payload_hash') or '').casefold(),
    ):
        return _reject_batch_command_authorization(
            'AUTH_COMMAND_EXECUTION_MISMATCH'
        )

    payload = task.get('payload') if isinstance(task.get('payload'), Mapping) else {}
    approval = (
        payload.get('manual_approval')
        if isinstance(payload.get('manual_approval'), Mapping)
        else {}
    )
    stored_context = (
        approval.get('authorization_context')
        if isinstance(approval.get('authorization_context'), Mapping)
        else {}
    )
    stage_facts = (
        approval.get('stage_task_facts')
        if isinstance(approval.get('stage_task_facts'), Mapping)
        else {}
    )
    try:
        expected_authorization_fingerprint = batch_authorization_context_fingerprint(stored_context)
    except BatchDraftAuthorizationError:
        return _reject_batch_command_authorization('AUTH_COMMAND_AUTHORIZATION_MISMATCH')
    if (
        str(command.authorization_lease_id or '') != str(approval.get('lease_id') or '')
        or not hmac.compare_digest(
            str(command.authorization_fingerprint or '').casefold(),
            expected_authorization_fingerprint.casefold(),
        )
        or not hmac.compare_digest(
            str(command.stage_task_facts_fingerprint or '').casefold(),
            str(stage_facts.get('fingerprint') or '').casefold(),
        )
    ):
        return _reject_batch_command_authorization('AUTH_COMMAND_AUTHORIZATION_MISMATCH')

    session_context = (
        snapshot.get('session_context')
        if isinstance(snapshot.get('session_context'), Mapping)
        else {}
    )
    store_name = str(session_context.get('shop_name') or '').strip()
    if not store_name:
        return _reject_batch_command_authorization('AUTH_COMMAND_SNAPSHOT_MISMATCH')
    try:
        frozen_target = canonical_frozen_target_identity(
            item_snapshot.get('target_identity'),
            store_name=store_name,
        )
        actual_target = canonical_mutation_target_payload(
            command.action,
            command.params,
        )
        expected_target = canonical_mutation_target_payload(
            'save_only',
            {
                'store_name': store_name,
                'target_identity': frozen_target,
            },
        )
        recomputed_target_hash = mutation_target_hash(command.action, command.params)
    except MutationCommandContractError:
        return _reject_batch_command_authorization('AUTH_COMMAND_TARGET_MISMATCH')
    if (
        frozen_target is None
        or actual_target != expected_target
        or command.params.get('target_identity') != frozen_target
        or command.params.get('target_source_urls') != frozen_target.get('source_urls')
        or command.params.get('product_query') != str(product_id)
        or command.params.get('store_name') != store_name
        or not hmac.compare_digest(
            str(command.target_hash or '').casefold(),
            recomputed_target_hash.casefold(),
        )
    ):
        return _reject_batch_command_authorization('AUTH_COMMAND_TARGET_MISMATCH')
    if (
        stored_context.get('schema') != 'dxm.authorization.context.v2'
        or not isinstance(stored_context.get('worktree_identity'), Mapping)
    ):
        return _reject_batch_command_authorization(
            'AUTH_WORKTREE_IDENTITY_REQUIRED'
        )

    return _verify_runner_authorization(
        command.task_id,
        'batch_draft_save',
        command.state,
    )


def _authorize_browser_mutation(command: Any, context: Any) -> dict[str, Any]:
    try:
        task_id = int(command.task_id)
    except (TypeError, ValueError):
        return _reject_batch_command_authorization('AUTH_COMMAND_JOB_MISMATCH')
    task = repo.get_task_private(task_id)
    if not isinstance(task, Mapping):
        return _reject_batch_command_authorization('AUTH_TASK_NOT_FOUND')
    persisted_mode = str(task.get('mode') or '').strip()
    command_mode = str(command.execution_mode or '').strip()
    if command_mode != persisted_mode:
        return _reject_batch_command_authorization('AUTH_COMMAND_MODE_MISMATCH')
    if persisted_mode == 'batch_draft_save':
        return _verify_batch_draft_save_command_authorization(command, context)
    if persisted_mode != 'single_save' or command.state != 'SAVE_ONLY':
        return _reject_batch_command_authorization('AUTH_COMMAND_MODE_MISMATCH')
    return _verify_runner_authorization(
        task_id,
        persisted_mode,
        command.state,
    )


browser_agent_runtime.set_mutation_authorizer(_authorize_browser_mutation)
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

REAL_DXM_MUTATION_MODES = {'single_save', 'batch_save', 'batch_draft_save'}
RELEASED_REAL_DXM_MUTATION_MODES = {'single_save', 'batch_draft_save'}
AUTHORIZATION_LEASE_TTL_SECONDS = 5 * 60
REAL_WRITE_START_MODES = REAL_DXM_MUTATION_MODES
ALLOWED_START_MODES = {'probe', 'dry_run', 'single_save', 'batch_save', 'batch_draft_save'}
SAVE_ONLY_PUBLISH_SCENE = 'SMT_SEMI_MANAGED_SAVE_ONLY'
L3_CONFIRMATION = 'CONFIRM_DXM_SAVE_ONLY'
UNRELEASED_REAL_DXM_MODE_DETAIL = (
    'Only controlled single_save and batch_draft_save are released for real DXM mutation; '
    'batch_save remains unreleased'
)
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
    mutation_dispatch_ledger.recover_inflight()
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
            unknown_jobs = _mark_real_jobs_after_runtime_recovery(full_task, mode=mode)
            repo.add_log(task_id, None, 'warning', '启动恢复：真实任务已转人工复核', {
                'previous_status': previous_status,
                'mode': mode,
                'reason': (
                    'mutation_outcome_unknown'
                    if unknown_jobs
                    else 'backend_restarted_while_task_active'
                ),
                'unknown_job_ids': unknown_jobs,
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


def _mark_real_jobs_after_runtime_recovery(
    task: dict[str, Any],
    *,
    mode: str,
) -> list[int]:
    unknown_job_ids: list[int] = []
    preserve_pending_tail = mode == 'batch_draft_save'
    for job in task.get('jobs') or []:
        job_status = str(job.get('status') or '')
        if job_status not in {'running', 'pending'}:
            continue
        job_id = int(job['id'])
        classification = mutation_dispatch_ledger.job_recovery_classification(
            task['id'],
            job_id,
        )
        if classification == 'UNKNOWN':
            mutation_dispatch_ledger.mark_incomplete_job_unknown(
                task['id'],
                job_id,
            )
            repo.update_job(
                job_id,
                status='unknown',
                current_step_code='RUNTIME_RECOVERY_UNKNOWN',
                current_step_name='保存结果待人工核对',
                error_code='UNKNOWN',
                error_message='保存动作已派发但结果不确定；批次已停止，禁止自动重试。请先在店小秘草稿箱人工核对该商品。',
            )
            unknown_job_ids.append(job_id)
            continue
        if preserve_pending_tail and job_status == 'pending':
            continue
        repo.update_job(
            job_id,
            status='failed',
            current_step_code='RUNTIME_RECOVERY',
            current_step_name='后台重启恢复',
            error_code='E901',
            error_message='上次真实浏览器任务没有正常结束，已停止自动执行并转入人工复核；请确认店小秘页面状态后重新打开执行浏览器再重试。',
        )
    return unknown_job_ids


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
    _assert_batch_browser_available()
    # Verify the same Playwright objects Reader will use, on their owner thread.
    # The probe does not navigate or call DXM.  It also never queues behind a
    # long login call: busy is a first-class reason_code instead of stale green.
    try:
        live_state = getattr(login_flow, 'get_live_state', None)
        result = dict(_run_login_flow(
            live_state if callable(live_state) else login_flow.get_state,
            fail_if_busy=True,
        ))
    except DxmSessionBusyError:
        result = {
            **dict(login_flow.get_state()),
            'ok': False,
            'reason_code': 'DXM_SESSION_BUSY',
            'logged_in': False,
            'reader_ready': False,
            'message': '真实可见浏览器正在处理登录或上一条只读操作；本次状态请求未排队。',
            'next_action': '等待当前操作返回后重新检测；不要重复提交登录。',
            'requires_user_action': False,
        }
    result.setdefault('logged_in', False)
    result.setdefault('reader_ready', False)
    result.setdefault(
        'reason_code',
        'LOGIN_READER_READY'
        if result['logged_in'] is True and result['reader_ready'] is True
        else 'BROWSER_SESSION_UNAVAILABLE',
    )
    return normalize_artifact_paths(result)


@app.get('/api/dxm/login-state')
def dxm_login_state():
    return normalize_artifact_paths(login_flow.get_state())


@app.get('/api/dxm/workflow/check-login')
def dxm_workflow_check_login():
    _assert_batch_browser_available()
    return normalize_artifact_paths(_run_login_flow(_workflow_adapter().check_login_state))


@app.post('/api/dxm/login/start')
def dxm_login_start(payload: LoginStartRequest):
    _assert_batch_browser_available()
    try:
        result = _run_login_flow(login_flow.start_login, payload.username, payload.password)
    except Exception as exc:
        result = _login_flow_failure_state(
            label='打开失败',
            message='真实店小秘登录浏览器启动失败。请按下一步处理，原始错误已保留到诊断字段和实时日志。',
            next_action='请关闭旧的 DXM Agent Console 或旧浏览器进程后重试；账号密码不会用于保存或发布。',
            raw_error=str(exc),
        )
    waiting_for_operator = (
        result.get('stage') == 'waiting_captcha'
        or result.get('reason_code') == 'LOGIN_INTERACTION_REQUIRED'
    )
    audit_state = record_best_effort({
        'actor': 'operator',
        'component': 'dxm_access',
        'action': 'login_start',
        'phase': 'waiting_user' if waiting_for_operator else 'completed' if result.get('ok') is not False else 'failed',
        'status': 'pending' if waiting_for_operator else 'ok' if result.get('ok') is not False else 'failed',
        'correlation_id': 'login-start',
        'root_correlation_id': 'login',
        'input': {'username_length': len(payload.username or '')},
        'output': {
            'reason_code': result.get('reason_code'),
            'logged_in': result.get('logged_in') is True,
        },
    })
    if audit_state.get('degraded'):
        result = {**result, 'audit_degraded': True}
    return normalize_artifact_paths(result)


@app.post('/api/dxm/login/continue')
def dxm_login_continue(payload: LoginContinueRequest):
    if not payload.confirm:
        return normalize_artifact_paths(login_flow.get_state())
    _assert_batch_browser_available()
    try:
        result = _run_login_flow(login_flow.continue_login)
    except Exception as exc:
        result = _login_flow_failure_state(
            label='检测失败',
            message='真实店小秘登录态检测失败。请按下一步处理，原始错误已保留到诊断字段和实时日志。',
            next_action='请确认真实浏览器窗口仍然打开，完成验证码或账号修正后再次检测；必要时重新打开登录页。',
            raw_error=str(exc),
        )
    record_best_effort({
        'actor': 'operator',
        'component': 'dxm_access',
        'action': 'login_continue',
        'phase': 'completed',
        'status': 'ok' if result.get('logged_in') is True else 'pending',
        'correlation_id': 'login-continue',
        'root_correlation_id': 'login',
        'output': {
            'reason_code': result.get('reason_code'),
            'reader_ready': result.get('reader_ready') is True,
        },
    })
    return normalize_artifact_paths(result)


@app.post('/api/dxm/logout')
def dxm_logout():
    """Close the visible DXM session and make the next login use a clean account."""

    _assert_batch_browser_available()
    try:
        result = dict(_run_login_flow(login_flow.logout, fail_if_busy=True))
    except DxmSessionBusyError:
        record_best_effort({
            'actor': 'operator',
            'component': 'dxm_access',
            'action': 'logout',
            'phase': 'failed',
            'status': 'failed',
            'reason': 'DXM_SESSION_BUSY',
            'correlation_id': 'logout',
            'root_correlation_id': 'login',
        })
        raise _dxm_session_busy_http_exception()
    except Exception as exc:  # noqa: BLE001 - keep a recoverable operator state.
        result = _login_flow_failure_state(
            label='退出失败',
            message='退出店小秘登录态失败；请检查真实浏览器窗口并查看日志。',
            next_action='确认没有正在执行的读取或保存操作后，再重试退出登录。',
            raw_error=str(exc),
        )
        result['reason_code'] = 'DXM_LOGOUT_FAILED'
        record_best_effort({
            'actor': 'operator',
            'component': 'dxm_access',
            'action': 'logout',
            'phase': 'failed',
            'status': 'failed',
            'reason': 'DXM_LOGOUT_FAILED',
            'correlation_id': 'logout',
            'root_correlation_id': 'login',
            'output': {'raw_error': str(exc)[:240]},
        })
        return normalize_artifact_paths(result)

    logout_ok = result.get('reason_code') == 'DXM_LOGGED_OUT'
    record_best_effort({
        'actor': 'operator',
        'component': 'dxm_access',
        'action': 'logout',
        'phase': 'completed' if logout_ok else 'failed',
        'status': 'ok' if logout_ok else 'failed',
        'reason': result.get('reason_code'),
        'correlation_id': 'logout',
        'root_correlation_id': 'login',
        'output': {
            'logged_in': result.get('logged_in') is True,
            'reader_ready': result.get('reader_ready') is True,
        },
    })
    return normalize_artifact_paths(result)


@app.post('/api/dxm/navigate')
def dxm_navigate(payload: LoginNavigateRequest):
    _assert_batch_browser_available()
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
    _assert_batch_browser_available()
    return normalize_artifact_paths(_run_login_flow(_workflow_adapter().open_draft_box))


@app.get('/api/dxm/draft-reader/shops')
def dxm_draft_reader_shops():
    _assert_batch_browser_available()
    try:
        return _run_login_flow(
            DxmDraftReader(workflow_adapter).list_shops,
            fail_if_busy=True,
        )
    except DxmSessionBusyError as exc:
        raise _dxm_session_busy_http_exception() from exc
    except DxmDraftReaderError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': exc.reason_code,
                'message': str(exc),
            },
        ) from exc


@app.get('/api/dxm/draft-reader/products')
def dxm_draft_reader_products(
    shop_id: str = Query(default='-1', min_length=1, max_length=32),
    page_no: int = Query(default=1, ge=1, le=100_000),
    page_size: int = Query(default=100, ge=1, le=200),
):
    _assert_batch_browser_available()
    try:
        return _run_login_flow(
            DxmDraftReader(workflow_adapter).list_products,
            shop_id=shop_id,
            page_no=page_no,
            page_size=page_size,
            fail_if_busy=True,
        )
    except DxmSessionBusyError as exc:
        raise _dxm_session_busy_http_exception() from exc
    except DxmDraftReaderError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': exc.reason_code,
                'message': str(exc),
            },
        ) from exc


def _dxm_category_query_exception_mapping(exc: Exception) -> HTTPException:
    if isinstance(exc, DxmSessionBusyError):
        return _dxm_session_busy_http_exception()
    if isinstance(exc, DxmDraftReaderError):
        return HTTPException(
            status_code=409,
            detail={
                'reason_code': exc.reason_code,
                'message': str(exc),
            },
        )
    raise exc


@app.get('/api/dxm/category/children')
def dxm_category_children(
    pcid: str = Query(default='', max_length=24),
):
    _assert_batch_browser_available()
    try:
        return _run_login_flow(
            workflow_adapter.read_category_children,
            pcid=pcid,
            fail_if_busy=True,
        )
    except Exception as exc:
        raise _dxm_category_query_exception_mapping(exc) from exc


@app.get('/api/dxm/category/search')
def dxm_category_search(
    keyword: str = Query(min_length=1, max_length=64),
):
    _assert_batch_browser_available()
    try:
        return _run_login_flow(
            workflow_adapter.search_categories,
            keyword=keyword,
            fail_if_busy=True,
        )
    except Exception as exc:
        raise _dxm_category_query_exception_mapping(exc) from exc


@app.get('/api/dxm/category/get')
def dxm_category_get(
    category_id: str = Query(min_length=1, max_length=24),
):
    _assert_batch_browser_available()
    try:
        return _run_login_flow(
            workflow_adapter.get_category_by_id,
            category_id=category_id,
            fail_if_busy=True,
        )
    except Exception as exc:
        raise _dxm_category_query_exception_mapping(exc) from exc


def _active_agent_console_browser() -> dict[str, Any] | None:
    console_status = agent_console_service.status()
    console_owns_browser = (
        console_status.get('browser_visible') is True
        or console_status.get('browser_launching') is True
        or (
            console_status.get('active') is True
            and console_status.get('launch_browser') is True
        )
    )
    return console_status if console_owns_browser else None


def _assert_agent_console_browser_released(message: str) -> None:
    if _active_agent_console_browser() is not None:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'AGENT_CONSOLE_ACTIVE',
                'message': message,
            },
        )


def _assert_batch_browser_available() -> None:
    """Keep interactive browser work off an executing shared browser session."""

    _assert_agent_console_browser_released(
        '已有单任务浏览器现场。请先关闭该现场，再进入商品箱整批流程。',
    )
    active_task = repo.get_active_task_execution()
    if active_task is not None:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'LEGACY_TASK_ACTIVE',
                'message': (
                    f"任务 #{active_task['id']} 正在使用自动浏览器。"
                    '请等待任务结束后再读取或批准批次。'
                ),
            },
        )
    active_batch = repo.get_active_edit_batch_execution()
    if active_batch is not None:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'ANOTHER_EDIT_BATCH_ACTIVE',
                'message': (
                    f"批次 #{active_batch['id']} 正在使用自动浏览器。"
                    '请等待完成或停止该批次后再继续。'
                ),
            },
        )


@app.post('/api/dxm/draft-box/scope-snapshots', status_code=201)
def create_draft_box_scope_snapshot(payload: DraftBoxScopeSnapshotCreate):
    _assert_batch_browser_available()
    capture = _run_login_flow(
        workflow_adapter.capture_draft_box_scope,
        payload.max_items,
    )
    try:
        identity = runtime_identity.as_dict()
        return BatchEditCoordinator(
            repo,
            l2_verifier=_current_batch_l2_verification,
        ).persist_scope_capture(
            capture,
            requested_max_items=payload.max_items,
            runtime_context={
                "instance_id": identity["instanceId"],
                "browser_runtime_id": browser_agent_runtime.runtime_id,
                "git_head": identity["gitHead"],
            },
            expected_browser_session_id=workflow_adapter.browser_session_id(),
        )
    except (BatchEditContractError, SaveOnlyContractError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"reason_code": exc.reason_code, "message": str(exc)},
        ) from exc


@app.post('/api/edit-batches', status_code=410)
def create_edit_batch(payload: EditBatchCreate):
    raise HTTPException(
        status_code=410,
        detail={
            'reason_code': 'BATCH_EXECUTION_RUNTIME_REMOVED',
            'message': 'BatchExecutionRuntime has been removed. Use V1TaskRunner for batch execution.',
        },
    )


@app.post('/api/edit-batches/{batch_id}/manual-approval', status_code=410)
def approve_edit_batch(batch_id: int, _payload: EditBatchManualApprovalRequest):
    if not repo.get_edit_batch(batch_id):
        raise HTTPException(status_code=404, detail='Edit batch not found')
    raise HTTPException(
        status_code=409,
        detail={
            'reason_code': 'BATCH_APPROVAL_REQUIRES_ATOMIC_START',
            'message': '整批批准必须与启动原子完成，请使用“批准并开始”。',
        },
    )


@app.post('/api/edit-batches/{batch_id}/approve-and-start', status_code=410)
async def approve_and_start_edit_batch(
    batch_id: int,
    payload: EditBatchApproveAndStartRequest,
):
    raise HTTPException(
        status_code=410,
        detail={
            'reason_code': 'BATCH_EXECUTION_RUNTIME_REMOVED',
            'message': 'BatchExecutionRuntime has been removed. Use V1TaskRunner for batch execution.',
        },
    )


@app.post('/api/edit-batches/{batch_id}/stop', status_code=410)
def request_edit_batch_stop(batch_id: int, payload: EditBatchStopRequest):
    raise HTTPException(
        status_code=410,
        detail={
            'reason_code': 'BATCH_EXECUTION_RUNTIME_REMOVED',
            'message': 'BatchExecutionRuntime has been removed. Use V1TaskRunner for batch execution.',
        },
    )


@app.get('/api/edit-batches/{batch_id}')
def get_edit_batch(batch_id: int):
    batch = repo.get_edit_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail='Edit batch not found')
    return batch


@app.get('/api/edit-batches')
def list_edit_batches():
    return repo.list_edit_batches()


@app.post('/api/dxm/draft-box/action')
def dxm_draft_box_action(payload: DraftBoxActionRequest):
    _assert_direct_real_dxm_mutation_allowed(payload)


@app.post('/api/dxm/workflow/open-editor')
def dxm_workflow_open_editor(payload: DraftBoxActionRequest | None = None):
    payload = payload or DraftBoxActionRequest(action='edit')
    _assert_direct_real_dxm_mutation_allowed(payload)


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


@app.get('/api/template-center/edit-batch-bundle-options')
def get_edit_batch_bundle_options(
    store_id: int = Query(gt=0),
    category_name: str | None = Query(default=None, max_length=200),
):
    try:
        return EditBatchBundleComposer().options(
            store_id=store_id,
            category_name=category_name,
        )
    except BundleComposerError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                'reason_code': exc.reason_code,
                'message': str(exc),
                'missing': exc.missing,
            },
        ) from exc


@app.post('/api/template-center/edit-batch-bundles', status_code=201)
def compose_edit_batch_bundle(payload: EditBatchBundleComposeRequest):
    try:
        return EditBatchBundleComposer().compose(payload.model_dump())
    except BundleComposerError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                'reason_code': exc.reason_code,
                'message': str(exc),
                'missing': exc.missing,
            },
        ) from exc


def _editor_source_section(path: Any) -> str:
    normalized = str(path or '')
    if 'attribute' in normalized.casefold():
        return 'attribute_info'
    if 'adjustprice' in normalized.casefold():
        return 'regional_pricing'
    if 'sizechart' in normalized.casefold():
        return 'description_info'
    if 'msr/' in normalized.casefold() or 'manufacture/' in normalized.casefold() or 'qualification' in normalized.casefold():
        return 'compliance_info'
    if 'shopinfosync/list' in normalized.casefold() or 'templatelistformodule' in normalized.casefold():
        return 'template_main'
    if 'edit.json' in normalized.casefold():
        return 'basic_info'
    return 'other_info'


@app.post('/api/dxm-template-refs/sync', status_code=201)
def sync_dxm_template_refs(payload: DxmTemplateRefSyncRequest):
    sync_started = time.perf_counter()
    sync_correlation_id = f'dxm-template-sync-{uuid.uuid4().hex}'
    sync_input = {
        "shop_id": payload.shop_id,
        "category_count": len(payload.category_ids),
    }
    record_best_effort({
        "actor": "operator",
        "component": "dxm_template_sync",
        "action": "sync",
        "phase": "started",
        "status": "running",
        "correlation_id": sync_correlation_id,
        "root_correlation_id": sync_correlation_id,
        "input": sync_input,
    })
    try:
        read_result = _run_login_flow(
            DxmPlanReader(workflow_adapter).read_scope,
            shop_id=payload.shop_id,
            category_ids=payload.category_ids,
            representative_product_ids=payload.representative_product_ids,
            fail_if_busy=True,
        )
        refs = E2PlanService().sync_dxm_template_refs(
            read_result["template_records"],
            shop_id=read_result["shop_id"],
            category_ids=read_result["category_ids"],
        )
        editor_models = build_dxm_editor_models(
            category_schemas=read_result["category_schemas"],
            template_records=read_result["template_records"],
            refs=refs,
            representative_products=read_result.get("representative_products", {}),
            data_sources=[
                {
                    "section": _editor_source_section(item.get("path")),
                    **item,
                }
                for item in (read_result.get("request_trace") or [])
                if isinstance(item, Mapping)
            ],
        )
        editor_section_count = sum(
            len(model["sections"])
            for model in editor_models.values()
        )
        editor_field_count = sum(
            len(section["field_keys"])
            for model in editor_models.values()
            for section in model["sections"]
        )
        editor_template_binding_count = sum(
            len(section["templates"])
            for model in editor_models.values()
            for section in model["sections"]
        )
        template_record_count = len(read_result["template_records"])
        category_schema_count = len(read_result.get("category_schemas") or {})
        request_trace = read_result.get("request_trace") or []
        elapsed_ms = round((time.perf_counter() - sync_started) * 1000, 1)
        sync_status = "synced" if refs else "empty"
        empty_reason = None if refs else "DXM_RETURNED_NO_TEMPLATE_RECORDS"
        record_best_effort({
            "actor": "operator",
            "component": "dxm_template_sync",
            "action": "sync",
            "phase": "completed",
            "status": sync_status,
            "correlation_id": sync_correlation_id,
            "root_correlation_id": sync_correlation_id,
            "input": sync_input,
            "output": {
                "source": read_result["source"],
                "template_record_count": template_record_count,
                "template_ref_count": len(refs),
                "category_schema_count": category_schema_count,
                "editor_section_count": editor_section_count,
                "editor_field_count": editor_field_count,
                "editor_template_binding_count": editor_template_binding_count,
                "empty_reason": empty_reason,
                "elapsed_ms": elapsed_ms,
                "request_trace": request_trace,
            },
        })
        return {
            "source": read_result["source"],
            "session_bound": read_result["session_bound"],
            "session_ref": read_result["session_ref"],
            "shop_id": read_result["shop_id"],
            "category_ids": read_result["category_ids"],
            "category_schemas": read_result["category_schemas"],
            "editor_models": editor_models,
            "category_capabilities": read_result.get("category_capabilities", {}),
            "sync_status": sync_status,
            "template_record_count": template_record_count,
            "template_ref_count": len(refs),
            "category_schema_count": category_schema_count,
            "editor_section_count": editor_section_count,
            "editor_field_count": editor_field_count,
            "editor_template_binding_count": editor_template_binding_count,
            "empty_reason": empty_reason,
            "elapsed_ms": elapsed_ms,
            "sync_correlation_id": sync_correlation_id,
            "request_trace": request_trace,
            "refs": refs,
        }
    except DxmSessionBusyError as exc:
        record_best_effort({
            "actor": "operator",
            "component": "dxm_template_sync",
            "action": "sync",
            "phase": "failed",
            "status": "failed",
            "reason": "DXM_SESSION_BUSY",
            "correlation_id": sync_correlation_id,
            "root_correlation_id": sync_correlation_id,
            "input": sync_input,
            "output": {"elapsed_ms": round((time.perf_counter() - sync_started) * 1000, 1)},
        })
        raise _dxm_session_busy_http_exception() from exc
    except DxmPlanReaderError as exc:
        record_best_effort({
            "actor": "operator",
            "component": "dxm_template_sync",
            "action": "sync",
            "phase": "failed",
            "status": "failed",
            "reason": exc.reason_code,
            "correlation_id": sync_correlation_id,
            "root_correlation_id": sync_correlation_id,
            "input": sync_input,
            "output": {"elapsed_ms": round((time.perf_counter() - sync_started) * 1000, 1)},
        })
        raise HTTPException(
            status_code=409,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc
    except DxmDraftReaderError as exc:
        record_best_effort({
            "actor": "operator",
            "component": "dxm_template_sync",
            "action": "sync",
            "phase": "failed",
            "status": "failed",
            "reason": exc.reason_code,
            "correlation_id": sync_correlation_id,
            "root_correlation_id": sync_correlation_id,
            "input": sync_input,
            "output": {"elapsed_ms": round((time.perf_counter() - sync_started) * 1000, 1)},
        })
        raise HTTPException(
            status_code=409,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc
    except PlanContractError as exc:
        record_best_effort({
            "actor": "operator",
            "component": "dxm_template_sync",
            "action": "sync",
            "phase": "failed",
            "status": "failed",
            "reason": exc.reason_code,
            "correlation_id": sync_correlation_id,
            "root_correlation_id": sync_correlation_id,
            "input": sync_input,
            "output": {"elapsed_ms": round((time.perf_counter() - sync_started) * 1000, 1)},
        })
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.post('/api/dxm-template-refs/sync-shop', status_code=201)
def sync_dxm_template_refs_for_shop(payload: DxmTemplateShopSyncRequest):
    """Synchronize the complete management-center index for one DXM shop."""

    sync_started = time.perf_counter()
    sync_correlation_id = f'dxm-template-shop-sync-{uuid.uuid4().hex}'
    sync_input = {"shop_id": payload.shop_id, "scope": "shop"}
    record_best_effort({
        "actor": "operator",
        "component": "dxm_template_sync",
        "action": "sync_shop",
        "phase": "started",
        "status": "running",
        "correlation_id": sync_correlation_id,
        "root_correlation_id": sync_correlation_id,
        "input": sync_input,
    })
    try:
        read_result = _run_login_flow(
            DxmPlanReader(workflow_adapter).read_template_library,
            shop_id=payload.shop_id,
            fail_if_busy=True,
        )
        refs = E2PlanService().sync_dxm_template_refs_for_shop(
            read_result["template_records"],
            shop_id=read_result["shop_id"],
        )
        template_record_count = len(read_result["template_records"])
        request_trace = read_result.get("request_trace") or []
        elapsed_ms = round((time.perf_counter() - sync_started) * 1000, 1)
        sync_status = "synced" if refs else "empty"
        empty_reason = None if refs else "DXM_RETURNED_NO_TEMPLATE_RECORDS"
        output = {
            "source": read_result["source"],
            "template_record_count": template_record_count,
            "template_ref_count": len(refs),
            "category_count": len(read_result["category_ids"]),
            "empty_reason": empty_reason,
            "elapsed_ms": elapsed_ms,
            "request_trace": request_trace,
        }
        record_best_effort({
            "actor": "operator",
            "component": "dxm_template_sync",
            "action": "sync_shop",
            "phase": "completed",
            "status": sync_status,
            "correlation_id": sync_correlation_id,
            "root_correlation_id": sync_correlation_id,
            "input": sync_input,
            "output": output,
        })
        return {
            "source": read_result["source"],
            "session_bound": read_result["session_bound"],
            "session_ref": read_result["session_ref"],
            "shop_id": read_result["shop_id"],
            "sync_scope": "shop",
            "category_ids": read_result["category_ids"],
            "category_schemas": {},
            "editor_models": {},
            "sync_status": sync_status,
            "template_record_count": template_record_count,
            "template_ref_count": len(refs),
            "category_schema_count": 0,
            "empty_reason": empty_reason,
            "elapsed_ms": elapsed_ms,
            "sync_correlation_id": sync_correlation_id,
            "request_trace": request_trace,
            "refs": refs,
        }
    except DxmSessionBusyError as exc:
        record_best_effort({
            "actor": "operator",
            "component": "dxm_template_sync",
            "action": "sync_shop",
            "phase": "failed",
            "status": "failed",
            "reason": "DXM_SESSION_BUSY",
            "correlation_id": sync_correlation_id,
            "root_correlation_id": sync_correlation_id,
            "input": sync_input,
            "output": {"elapsed_ms": round((time.perf_counter() - sync_started) * 1000, 1)},
        })
        raise _dxm_session_busy_http_exception() from exc
    except (DxmPlanReaderError, DxmDraftReaderError, PlanContractError) as exc:
        reason_code = getattr(exc, "reason_code", type(exc).__name__)
        record_best_effort({
            "actor": "operator",
            "component": "dxm_template_sync",
            "action": "sync_shop",
            "phase": "failed",
            "status": "failed",
            "reason": reason_code,
            "correlation_id": sync_correlation_id,
            "root_correlation_id": sync_correlation_id,
            "input": sync_input,
            "output": {"elapsed_ms": round((time.perf_counter() - sync_started) * 1000, 1)},
        })
        status_code = getattr(exc, "status_code", 409)
        raise HTTPException(
            status_code=status_code,
            detail={"reason_code": reason_code, "message": str(exc)},
        ) from exc


@app.get('/api/dxm-template-refs')
def list_dxm_template_refs():
    return E2PlanService().list_dxm_template_refs()


@app.patch('/api/dxm-template-refs/{_ref_id}')
def reject_dxm_template_ref_mutation(_ref_id: int, _payload: dict[str, Any]):
    raise HTTPException(
        status_code=405,
        detail={
            'reason_code': 'DXM_TEMPLATE_REF_READ_ONLY',
            'message': '店小秘模板引用只允许从只读同步结果更新。',
        },
    )


@app.post('/api/local-plan-templates', status_code=201)
def create_local_plan_template(payload: LocalPlanTemplateRequest):
    try:
        return E2PlanService().create_local_plan(payload.model_dump())
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.get('/api/local-plan-templates')
def list_local_plan_templates():
    return E2PlanService().list_local_plans()


@app.get('/api/local-plan-templates/{plan_id}')
def get_local_plan_template(plan_id: int):
    try:
        return E2PlanService().get_local_plan(plan_id)
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.patch('/api/local-plan-templates/{plan_id}')
def reject_local_plan_in_place_mutation(plan_id: int, _payload: dict[str, Any]):
    try:
        E2PlanService().get_local_plan(plan_id)
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc
    raise HTTPException(
        status_code=409,
        detail={
            'reason_code': 'LOCAL_PLAN_VERSION_IMMUTABLE',
            'message': '本地方案版本不可原地修改；请创建新版本。',
        },
    )


@app.post('/api/local-plan-templates/{plan_id}/versions', status_code=201)
def create_local_plan_template_version(plan_id: int, payload: LocalPlanTemplateRequest):
    try:
        return E2PlanService().create_local_plan(
            payload.model_dump(),
            supersedes_id=plan_id,
        )
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.delete('/api/local-plan-templates/{plan_id}')
def archive_local_plan_template(plan_id: int):
    try:
        return E2PlanService().archive_local_plan(plan_id)
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.post('/api/plan-snapshots/preview')
def preview_plan_snapshot(payload: PlanSnapshotRequest):
    try:
        authoritative = _run_login_flow(
            DxmPlanReader(workflow_adapter).build_snapshot_request,
            local_plan_template_id=payload.local_plan_template_id,
            shop_id=payload.shop_id,
            product_ids=payload.product_ids,
            expected_session_ref=payload.session_ref,
            target_category_id=payload.target_category_id,
            target_category_name=payload.target_category_name,
            target_category_match=payload.target_category_match,
            fail_if_busy=True,
        )
        service = E2PlanService(
            capability_checker=WorkflowMandatoryCapabilityChecker(workflow_adapter)
        )
        service.sync_dxm_template_refs(
            authoritative["template_records"],
            shop_id=authoritative["request"]["shop_id"],
            category_ids=authoritative["category_ids"],
        )
        snapshot = service.build_plan_snapshot(authoritative["request"])
        record_best_effort({
            'actor': 'operator',
            'component': 'plan',
            'action': 'preview',
            'phase': 'completed',
            'status': 'ok',
            'correlation_id': f"preview-{payload.local_plan_template_id}",
            'root_correlation_id': f"plan-{payload.local_plan_template_id}",
            'store_id': payload.shop_id,
            'snapshot_id': snapshot.get('snapshot_hash') if isinstance(snapshot, Mapping) else None,
            'input': {
                'product_count': len(payload.product_ids or []),
                'plan_id': payload.local_plan_template_id,
            },
        })
        return snapshot
    except DxmSessionBusyError as exc:
        record_best_effort({
            'actor': 'operator',
            'component': 'plan',
            'action': 'preview',
            'phase': 'blocked',
            'status': 'blocked',
            'reason': 'DXM_SESSION_BUSY',
            'correlation_id': f"preview-{payload.local_plan_template_id}",
            'root_correlation_id': f"plan-{payload.local_plan_template_id}",
            'store_id': payload.shop_id,
            'input': {
                'product_count': len(payload.product_ids or []),
                'plan_id': payload.local_plan_template_id,
            },
        })
        raise _dxm_session_busy_http_exception() from exc
    except (DxmPlanReaderError, DxmDraftReaderError, PlanContractError, PlanSchemaError) as exc:
        record_best_effort({
            'actor': 'operator',
            'component': 'plan',
            'action': 'preview',
            'phase': 'blocked',
            'status': 'blocked',
            'reason': exc.reason_code,
            'correlation_id': f"preview-{payload.local_plan_template_id}",
            'root_correlation_id': f"plan-{payload.local_plan_template_id}",
            'store_id': payload.shop_id,
            'input': {
                'product_count': len(payload.product_ids or []),
                'plan_id': payload.local_plan_template_id,
            },
        })
        raise HTTPException(
            status_code=getattr(exc, "status_code", 409),
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.post('/api/plan-snapshots', status_code=201)
def freeze_plan_snapshot(payload: PlanSnapshotRequest):
    try:
        if payload.expected_snapshot_hash is None:
            raise PlanContractError(
                "PLAN_SNAPSHOT_PREVIEW_REQUIRED",
                "冻结前必须提交刚刚预览得到的 snapshot hash",
            )
        if payload.idempotency_key is None:
            raise PlanContractError(
                "PLAN_SNAPSHOT_IDEMPOTENCY_REQUIRED",
                "冻结与建任务必须提交稳定的 idempotency_key",
            )
        authoritative = _run_login_flow(
            DxmPlanReader(workflow_adapter).build_snapshot_request,
            local_plan_template_id=payload.local_plan_template_id,
            shop_id=payload.shop_id,
            product_ids=payload.product_ids,
            expected_session_ref=payload.session_ref,
            target_category_id=payload.target_category_id,
            target_category_name=payload.target_category_name,
            target_category_match=payload.target_category_match,
            fail_if_busy=True,
        )
        service = E2PlanService(
            capability_checker=WorkflowMandatoryCapabilityChecker(workflow_adapter)
        )
        service.sync_dxm_template_refs(
            authoritative["template_records"],
            shop_id=authoritative["request"]["shop_id"],
            category_ids=authoritative["category_ids"],
        )
        return service.freeze_plan_snapshot(
            authoritative["request"],
            expected_snapshot_hash=payload.expected_snapshot_hash,
            idempotency_key=payload.idempotency_key,
        )
    except DxmSessionBusyError as exc:
        raise _dxm_session_busy_http_exception() from exc
    except (DxmPlanReaderError, DxmDraftReaderError, PlanContractError, PlanSchemaError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 409),
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.get('/api/plan-snapshots/{snapshot_id}')
def get_plan_snapshot(snapshot_id: int):
    try:
        return E2PlanService().get_plan_snapshot(snapshot_id)
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.post('/api/plan-snapshots/{snapshot_id}/tasks', status_code=201)
def create_batch_draft_save_task(snapshot_id: int):
    try:
        return E2PlanService().create_task_from_snapshot(snapshot_id, repo)
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.post('/api/templates')
def create_template(payload: TemplateCreate):
    data = payload.model_dump()
    if str(data.get('template_type') or '').strip().lower() == 'edit_batch_bundle':
        raise HTTPException(
            status_code=409,
            detail='edit_batch_bundle templates can only be created by the bundle composer',
        )
    data['payload'] = _normalize_template_payload(data.get('template_type'), data.get('payload'))
    _assert_executable_dxm_reference_payload(data.get('template_type'), data.get('payload'))
    return repo.create_template(data)


@app.patch('/api/templates/{template_id}')
def update_template(template_id: int, payload: TemplateUpdate):
    data = payload.model_dump(exclude_unset=True)
    current = repo.get_template(template_id)
    if not current:
        raise HTTPException(status_code=404, detail='Template not found')
    if current.get('template_type') == 'edit_batch_bundle':
        if set(data) != {'is_enabled'} or not isinstance(data.get('is_enabled'), bool):
            raise HTTPException(
                status_code=409,
                detail='edit_batch_bundle content is immutable; only is_enabled may be patched',
            )
    elif str(data.get('template_type') or '').strip().lower() == 'edit_batch_bundle':
        raise HTTPException(
            status_code=409,
            detail='templates cannot be converted to edit_batch_bundle',
        )
    if 'payload' in data:
        template_type = data.get('template_type')
        if template_type is None:
            template_type = current.get('template_type') if current else None
        data['payload'] = _normalize_template_payload(template_type, data.get('payload'))
    effective_template_type = data.get('template_type', current.get('template_type'))
    effective_payload = data.get('payload', current.get('payload'))
    _assert_executable_dxm_reference_payload(effective_template_type, effective_payload)
    template = repo.update_template(template_id, data)
    return template


@app.get('/api/config/preview')
def config_preview(task_id: int | None = None):
    return config_preview_service.build(repo, task_id)


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
def list_tasks(
    mode: str | None = Query(default=None, min_length=1, max_length=64),
    view: str = Query(default='full', pattern=r'^(?:full|summary)$'),
):
    if view == 'summary':
        return repo.list_task_summaries(mode=mode)
    tasks = repo.list_tasks()
    if mode is not None:
        tasks = [task for task in tasks if str(task.get('mode') or '') == mode]
    return [_with_public_worker_control(task) for task in tasks]


@app.get('/api/tasks/{task_id}')
def get_task(task_id: int):
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return _with_public_worker_control(task)


def _with_public_worker_control(task: dict | None) -> dict | None:
    if not task:
        return task
    control = repo.public_task_worker_control(task)
    if control is None:
        return task
    public = dict(task)
    public['workerControl'] = control
    return public


@app.post('/api/tasks')
def create_task(payload: TaskCreate):
    _assert_task_create_scope(payload)
    data = payload.model_dump()
    return repo.create_task(data)


@app.patch('/api/tasks/{task_id}/config-overrides')
def update_task_config_overrides(task_id: int, payload: TaskConfigOverrideRequest):
    candidate = repo.get_task(task_id)
    if not candidate:
        raise HTTPException(status_code=404, detail='Task not found')
    if str(candidate.get('mode') or '') == 'batch_draft_save':
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_PLAN_SNAPSHOT_IMMUTABLE',
                'message': '冻结后的批量草稿任务不接受配置覆盖；请重新预览并冻结新快照。',
            },
        )
    section = payload.section.strip().lower().replace('-', '_').replace(' ', '_')
    if section not in DEFAULT_TEMPLATE_TYPES:
        raise HTTPException(status_code=400, detail=f'Unsupported config override section: {payload.section}')
    values = _normalize_config_override_values(section, payload.values)
    _assert_executable_dxm_reference_payload(section, values)
    return repo.update_task_template_override(task_id, section, values)


@app.post('/api/tasks/{task_id}/manual-approval')
def approve_task_for_real_dxm(task_id: int, payload: TaskManualApprovalRequest):
    candidate = repo.get_task_private(task_id)
    if not candidate:
        raise HTTPException(status_code=404, detail='Task not found')
    if str(candidate.get('mode') or '') == 'batch_draft_save':
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_APPROVAL_REQUIRES_ATOMIC_START',
                'message': '批量草稿只保存必须使用原子“批准并开始”，不会签发可悬置令牌。',
            },
        )
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
    approval_result = repo.set_task_manual_approval(
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
    if not approval_result.ok:
        if approval_result.reason_code == 'TASK_NOT_FOUND':
            status_code = 404
        elif approval_result.reason_code in {
            'TASK_APPROVAL_INPUT_INVALID',
            'TASK_APPROVAL_TIME_INVALID',
        }:
            status_code = 400
        else:
            status_code = 409
        raise HTTPException(
            status_code=status_code,
            detail={
                'reason_code': approval_result.reason_code,
                'message': '任务批准状态已变化；系统没有覆盖现有授权。',
            },
        )
    task = approval_result.task
    if not isinstance(task, dict):
        raise HTTPException(
            status_code=500,
            detail={
                'reason_code': 'TASK_APPROVAL_RESULT_MISSING',
                'message': '任务已批准，但无法读取批准后的任务状态。',
            },
        )
    private_task = repo.get_task_private(task_id)
    private_approval = (
        (private_task.get('payload') or {}).get('manual_approval')
        if isinstance(private_task, Mapping)
        else None
    )
    if not isinstance(private_approval, Mapping):
        raise HTTPException(
            status_code=500,
            detail={
                'reason_code': 'TASK_APPROVAL_EVIDENCE_MISSING',
                'message': '任务已批准，但无法读取授权租约证据。',
            },
        )
    approval = {
        key: value
        for key, value in private_approval.items()
        if key != 'token_hash'
    }
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


@app.post('/api/tasks/{task_id}/approve-and-start')
async def approve_and_start_task_for_real_dxm(
    task_id: int,
    payload: TaskManualApprovalRequest,
):
    required_confirmation = _assert_task_can_receive_manual_approval(task_id, payload)
    _assert_workflow_runtime_healthy()
    record_best_effort({
        'actor': 'operator',
        'component': 'task',
        'action': 'approve_and_start',
        'phase': 'requested',
        'status': 'ok',
        'correlation_id': f"approve-{task_id}",
        'root_correlation_id': f"task-{task_id}",
        'task_id': str(task_id),
        'input': {'confirmation_length': len(getattr(payload, 'confirmation', '') or '')},
    })
    task = repo.get_task_private(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    if str(task.get('mode') or '') != 'batch_draft_save':
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'ATOMIC_START_BATCH_DRAFT_ONLY',
                'message': '原子批准并开始当前仅供 batch_draft_save 使用。',
            },
        )
    l2_gate = l2_real_probe_gate()
    if l2_gate.get('status') != 'passed':
        raise HTTPException(
            status_code=403,
            detail=f"L2 readonly probe gate is not passed: {l2_gate.get('status')}",
        )
    authorization_context = _build_task_authorization_context(
        task,
        approved_by=payload.approved_by.strip(),
        l2_gate=l2_gate,
    )
    issued_at = _authorization_now()
    consumed_at = issued_at
    expires_at = issued_at + timedelta(seconds=AUTHORIZATION_LEASE_TTL_SECONDS)
    result = repo.approve_and_start_task_with_authorization(
        task_id,
        token=secrets.token_urlsafe(24),
        confirmation=required_confirmation,
        approved_by=payload.approved_by.strip(),
        authorization_context=authorization_context,
        lease_id=uuid.uuid4().hex,
        issued_at=issued_at.isoformat(),
        expires_at=expires_at.isoformat(),
        consumed_at=consumed_at.isoformat(),
    )
    if not result.ok:
        status_code = 404 if result.reason_code == 'AUTH_TASK_NOT_FOUND' else 409
        raise HTTPException(
            status_code=status_code,
            detail={
                'reason_code': result.reason_code,
                'message': '原子批准并开始失败；任务未被部分批准或重复派发。',
            },
        )
    asyncio.create_task(runner.run_task(task_id))
    return {
        'ok': True,
        'taskId': task_id,
        'status': 'running',
        'authorizationConsumed': True,
        'confirmation': required_confirmation,
        'approvedBy': payload.approved_by.strip(),
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
        active_batch = repo.get_active_edit_batch_execution()
        if active_batch is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    'reason_code': 'EDIT_BATCH_ACTIVE',
                    'message': f"批次 #{active_batch['id']} 正在占用自动浏览器，请先等待完成或停止批次。",
                },
            )
        raise HTTPException(status_code=409, detail='Task is already running')
    asyncio.create_task(runner.run_task(task_id))
    return {'ok': True, 'taskId': task_id}


@app.post('/api/tasks/{task_id}/pause')
def pause_task(task_id: int):
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    result = repo.request_pause_task(task_id)
    if not result.ok:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': result.reason_code,
                'message': 'Task cannot be paused in its current state',
                'status': result.status or task.get('status'),
            },
        )
    public = result.as_public_dict()
    repo.add_log(
        task_id,
        None,
        'info',
        '操作员请求暂停；等待 worker 在商品安全点确认',
        {
            'reason_code': result.reason_code,
            'status': result.status,
            'worker_control': public.get('workerControl'),
        },
    )
    return {
        'ok': True,
        'taskId': task_id,
        'status': result.status,
        'reasonCode': result.reason_code,
        'applied': result.applied,
        'idempotent': result.idempotent,
        'workerControl': public.get('workerControl'),
        'message': '暂停已请求；worker 确认前任务仍可能完成当前商品',
    }


@app.post('/api/tasks/{task_id}/resume')
async def resume_task(task_id: int):
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    result = repo.request_resume_task(task_id)
    if not result.ok:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': result.reason_code,
                'message': 'Task cannot be resumed until pause is worker-acked and task is paused',
                'status': result.status or task.get('status'),
            },
        )
    public = result.as_public_dict()
    repo.add_log(
        task_id,
        None,
        'info',
        '操作员继续任务；runner 将跳过已完成商品',
        {
            'reason_code': result.reason_code,
            'status': result.status,
            'worker_control': public.get('workerControl'),
        },
    )
    asyncio.create_task(runner.run_task(task_id))
    return {
        'ok': True,
        'taskId': task_id,
        'status': result.status,
        'reasonCode': result.reason_code,
        'applied': result.applied,
        'idempotent': result.idempotent,
        'workerControl': public.get('workerControl'),
        'message': '已从暂停点继续；已完成保存不会重做',
    }


@app.post('/api/tasks/{task_id}/stop')
def stop_task(task_id: int):
    task = repo.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    result = repo.request_stop_task(task_id)
    if not result.ok:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': result.reason_code,
                'message': 'Task cannot be stopped in its current state',
                'status': result.status or task.get('status'),
            },
        )
    public = result.as_public_dict()
    repo.add_log(
        task_id,
        None,
        'warning',
        '操作员请求停止；等待 worker 安全收敛后确认',
        {
            'reason_code': result.reason_code,
            'status': result.status,
            'worker_control': public.get('workerControl'),
        },
    )
    return {
        'ok': True,
        'taskId': task_id,
        'status': result.status,
        'reasonCode': result.reason_code,
        'applied': result.applied,
        'idempotent': result.idempotent,
        'workerControl': public.get('workerControl'),
        'message': '停止已请求；当前商品安全收敛后不再派发新商品',
    }


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


@app.get('/api/operation-audit/events')
def list_operation_audit_events(
    status: str | None = None,
    task_id: str | None = None,
    product_id: str | None = None,
    component: str | None = None,
    phase: str | None = None,
    reason: str | None = None,
    limit: int = 200,
    offset: int = 0,
):
    listed = get_audit_service().list_events(
        status=status,
        task_id=task_id,
        product_id=product_id,
        component=component,
        phase=phase,
        reason=reason,
        limit=limit,
        offset=offset,
    )
    listed['chain'] = get_audit_service().verify_chain()
    return listed


@app.post('/api/operation-audit/client-events')
def record_operation_audit_client_event(payload: dict[str, Any]):
    event = dict(payload or {})
    event.setdefault('actor', 'operator')
    event.setdefault('component', 'workbench')
    event.setdefault('action', 'page_switch')
    event.setdefault('phase', 'completed')
    event.setdefault('status', 'ok')
    stored = record_best_effort(event)
    if stored.get('degraded'):
        return {'ok': False, 'audit_degraded': True, 'reason_code': 'AUDIT_DEGRADED'}
    return {'ok': True, 'event': stored}


@app.post('/api/operation-audit/export')
def export_operation_audit_package():
    export_dir = DATA_DIR / 'operation-audit'
    export_dir.mkdir(parents=True, exist_ok=True)
    dest = export_dir / f"dxm-audit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
    try:
        result = get_audit_service().export_diagnostic_zip(dest)
    except OperationAuditError as exc:
        raise HTTPException(
            status_code=409,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc
    return result


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
            'reasonCode': dxm_state.get('reason_code'),
            'loggedIn': dxm_state.get('logged_in') is True,
            'readerReady': dxm_state.get('reader_ready') is True,
            'currentUrl': dxm_state.get('current_url') or dxm_state.get('url') or dxm_state.get('page_url'),
            'pageTitle': dxm_state.get('page_title') or dxm_state.get('title'),
            'browserVisible': bool(dxm_state.get('browser_visible')),
            'lastError': dxm_state.get('last_error') or dxm_state.get('error'),
            'message': dxm_state.get('message'),
            'nextAction': dxm_state.get('next_action'),
        },
        'operationAudit': get_audit_service().verify_chain(),
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
            'message': '真实浏览器执行器需要重启后才能继续商品箱保存任务。',
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


def _assert_runtime_disruption_allowed(action: str) -> None:
    active_batch = repo.get_active_edit_batch_execution()
    if active_batch is not None:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'EDIT_BATCH_ACTIVE',
                'message': (
                    f"批次 #{active_batch['id']} 仍在执行，不能执行当前运行时操作。"
                    '请使用批次停止按钮并等待安全收口。'
                ),
                'action': action,
            },
        )
    active_task = repo.get_active_task_execution()
    if active_task is not None:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'LEGACY_TASK_ACTIVE',
                'message': (
                    f"任务 #{active_task['id']} 仍在执行，不能重置或停止共享浏览器。"
                    '请等待任务完成；异常时先转入人工复核。'
                ),
                'action': action,
            },
        )


@app.post('/api/runtime/control')
def runtime_control(payload: RuntimeControlRequest):
    action = payload.action.strip().lower()
    if action not in RUNTIME_CONTROL_ACTIONS:
        raise HTTPException(status_code=400, detail=f'Unknown runtime control action: {payload.action}')
    if action in {'restart_backend', 'stop_agent_console', 'reset_workflow_runtime'}:
        _assert_runtime_disruption_allowed(action)

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
            'message': '已启动 L2 商品箱真实只读复验；请在执行控制台查看启动器日志',
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
        candidates = [
            task
            for task in repo.list_tasks()
            if task.get('status') in {'running', 'pause_requested', 'stop_requested', 'paused'}
        ]
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
        active_task = repo.get_active_task_execution()
        if active_task is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    'reason_code': 'LEGACY_TASK_ACTIVE',
                    'message': (
                        f"任务 #{active_task['id']} 正在占用自动浏览器。"
                        '请等待任务结束后再打开新的执行浏览器。'
                    ),
                },
            )
        active_batch = repo.get_active_edit_batch_execution()
        if active_batch is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    'reason_code': 'EDIT_BATCH_ACTIVE',
                    'message': f"批次 #{active_batch['id']} 正在占用自动浏览器，请先等待完成或停止批次。",
                },
            )
        if task is None:
            raise HTTPException(
                status_code=403,
                detail='Agent execution browser start requires a selected controlled single_save task',
            )
        mode = str(task.get('mode') or (task.get('payload') or {}).get('execution_mode') or '')
        if mode not in RELEASED_REAL_DXM_MUTATION_MODES:
            raise HTTPException(status_code=403, detail=UNRELEASED_REAL_DXM_MODE_DETAIL)
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
    _assert_runtime_disruption_allowed('update_agent_console_hud')
    return normalize_artifact_paths(agent_console_service.update_hud(payload.step.model_dump(exclude_none=True)))


@app.post('/api/agent-console/snapshot')
def snapshot_agent_console():
    return normalize_artifact_paths(agent_console_service.snapshot())


@app.post('/api/agent-console/frame')
def refresh_agent_console_frame():
    return normalize_artifact_paths(agent_console_service.refresh_frame())


@app.post('/api/agent-console/control')
def control_agent_console_browser(payload: AgentConsoleControlRequest):
    _assert_runtime_disruption_allowed('control_agent_console_browser')
    return normalize_artifact_paths(agent_console_service.control_browser(payload.model_dump(exclude_none=True)))


@app.post('/api/agent-console/takeover')
def request_agent_console_takeover():
    _assert_runtime_disruption_allowed('request_agent_console_takeover')
    return normalize_artifact_paths(agent_console_service.request_manual_takeover())


@app.post('/api/agent-console/release')
def release_agent_console_takeover():
    _assert_runtime_disruption_allowed('release_agent_console_takeover')
    return normalize_artifact_paths(agent_console_service.release_manual_takeover())


@app.post('/api/agent-console/stop')
def stop_agent_console():
    _assert_runtime_disruption_allowed('stop_agent_console')
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


def _assert_executable_dxm_reference_payload(template_type: Any, payload: Any) -> None:
    normalized_type = str(template_type or '').strip().lower().replace('-', '_').replace(' ', '_')
    if normalized_type != 'dxm_reference' or not isinstance(payload, dict):
        return
    resolved = resolve_dxm_reference_templates(payload)
    unsupported = configured_unsupported_reference_sections(resolved)
    if unsupported:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'DXM_REFERENCE_SECTION_UNSUPPORTED',
                'message': (
                    '这些店小秘引用项尚无可验证的真实控件，不能进入执行配置：'
                    + '、'.join(unsupported)
                ),
            },
        )


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
        f"started L2 readonly product-box probe run_id={run_id} pid={process.pid} task={task_id or 'none'}"
    )
    return {
        'runId': run_id,
        'pid': process.pid,
        'logPath': str(log_path),
        'targets': ['draft_box'],
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


_FINAL_SINGLE_SAVE_REQUIRED_CHECKS = (
    'save_task_mode_valid',
    'save_task_completed',
    'product_present',
    'product_box_snapshot_valid',
    'single_save_target_bound',
    'manual_approval_consumed',
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


def _strict_final_single_save_ready(
    acceptance: dict[str, Any],
    readiness: dict[str, Any],
) -> bool:
    checks = acceptance.get('checks')
    return (
        acceptance.get('schema') == 'dxm_single_save_acceptance.v1'
        and acceptance.get('passed') is True
        and acceptance.get('status') == 'passed'
        and all(
            _is_positive_json_integer(acceptance.get(field))
            for field in ('save_task_id', 'product_id')
        )
        and acceptance.get('product_box_snapshot_error') is None
        and _is_positive_json_integer(acceptance.get('save_report_count'))
        and isinstance(acceptance.get('evidence_count'), int)
        and not isinstance(acceptance.get('evidence_count'), bool)
        and acceptance.get('evidence_count') >= 2
        and _is_empty_json_array(acceptance.get('missing_codes'))
        and _is_empty_json_array(acceptance.get('state_violation_codes'))
        and isinstance(checks, dict)
        and all(checks.get(field) is True for field in _FINAL_SINGLE_SAVE_REQUIRED_CHECKS)
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
    single_save_acceptance = payload.get('singleSaveAcceptance') if isinstance(payload.get('singleSaveAcceptance'), dict) else {}
    single_save_acceptance_readiness = payload.get('singleSaveAcceptanceReadiness') if isinstance(payload.get('singleSaveAcceptanceReadiness'), dict) else {}
    state_consistency = payload.get('stateConsistency') if isinstance(payload.get('stateConsistency'), dict) else {}
    state_consistency_readiness = payload.get('stateConsistencyReadiness') if isinstance(payload.get('stateConsistencyReadiness'), dict) else {}
    report_single_save_end_to_end = (
        payload.get('realDxmSingleSaveEndToEnd')
        or ('passed' if single_save_acceptance.get('passed') is True else 'pending_live_dxm_validation')
    )
    expected_single_save_end_to_end = payload.get('expectedRealDxmSingleSaveEndToEnd') or report_single_save_end_to_end
    single_save_acceptance_matches_expected = payload.get('singleSaveAcceptanceMatchesExpected')
    if single_save_acceptance_matches_expected is None and expected_single_save_end_to_end:
        single_save_acceptance_matches_expected = report_single_save_end_to_end == expected_single_save_end_to_end
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
    report_single_save_ready = (
        report_schema_ready
        and _strict_final_single_save_ready(
            single_save_acceptance,
            single_save_acceptance_readiness,
        )
        and payload.get('realDxmSingleSaveEndToEnd') == 'passed'
    )
    current_single_save_ready = (
        current_gate.get('single_save_ready') is True
        and current_gate.get('single_save_status') == 'passed'
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
        effective_single_save_end_to_end = 'pending_live_dxm_validation'
    elif current_readiness not in {'READY', 'BLOCKED'}:
        effective_readiness = 'BLOCKED'
        effective_blocked_reason = (
            current_gate.get('blocked_reason')
            or '当前运行门禁不可读取；不可依据旧自检报告启动真实写入。'
        )
        effective_mutation_allowed = False
        effective_single_save_end_to_end = 'pending_live_dxm_validation'
    else:
        effective_readiness = current_readiness
        effective_blocked_reason = (
            current_gate.get('blocked_reason')
            if effective_readiness == 'BLOCKED' and current_gate.get('blocked_reason')
            else payload.get('realDxmWriteBlockedReason')
        )
        effective_mutation_allowed = payload.get('realDxmMutationAllowed') is True and effective_readiness == 'READY'
        effective_single_save_end_to_end = (
            'passed'
            if report_single_save_ready and current_single_save_ready
            else 'pending_live_dxm_validation'
        )
    if not report_single_save_ready or not current_single_save_ready:
        if effective_readiness != 'BLOCKED' or not effective_blocked_reason:
            if not report_single_save_ready:
                effective_blocked_reason = (
                    'Single-save acceptance is missing, contradictory, or not passed in the final-check report; '
                    'READY remains blocked.'
                )
            else:
                effective_blocked_reason = (
                    current_gate.get('blocked_reason')
                    or 'Single-save acceptance is missing, contradictory, or not passed in the current workspace; READY remains blocked.'
                )
        effective_readiness = 'BLOCKED'
        effective_mutation_allowed = False
        effective_single_save_end_to_end = 'pending_live_dxm_validation'
    if not report_state_consistent:
        state_codes = ', '.join(str(code) for code in state_consistency.get('violation_codes') or [])
        if effective_readiness != 'BLOCKED' or not effective_blocked_reason:
            effective_blocked_reason = f"State consistency is not passed: {state_codes or 'state consistency unavailable'}; READY remains blocked."
        effective_readiness = 'BLOCKED'
        effective_mutation_allowed = False
        effective_single_save_end_to_end = 'pending_live_dxm_validation'
    effective_mutation_scope = payload.get('realDxmMutationScope') if effective_mutation_allowed else 'none'
    expected_readiness = payload.get('expectedRealDxmWriteReadiness') or report_readiness
    effective_readiness_matches_expected = (
        None
        if not expected_readiness or not effective_readiness
        else effective_readiness == expected_readiness
    )
    production_delivery_ready = (
        payload.get('productionDeliveryReady') is True
        and effective_single_save_end_to_end == 'passed'
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
        'real_dxm_single_save_end_to_end': report_single_save_end_to_end,
        'expected_real_dxm_single_save_end_to_end': expected_single_save_end_to_end,
        'effective_real_dxm_single_save_end_to_end': effective_single_save_end_to_end,
        'single_save_acceptance': single_save_acceptance,
        'single_save_acceptance_readiness': single_save_acceptance_readiness,
        'single_save_acceptance_matches_expected': single_save_acceptance_matches_expected,
        'state_consistency': state_consistency,
        'state_consistency_readiness': state_consistency_readiness,
        'current_state_consistent': current_gate.get('state_consistent'),
        'current_state_violation_codes': current_gate.get('state_violation_codes') or [],
        'current_single_save_ready': current_gate.get('single_save_ready'),
        'current_single_save_status': current_gate.get('single_save_status'),
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
            stderr=subprocess.DEVNULL,
        ).decode('utf-8', errors='strict').strip()
        status_raw = subprocess.check_output(
            [
                'git', '-C', str(REPO_ROOT), 'status',
                '--porcelain=v1', '-z', '-uall',
            ],
            stderr=subprocess.DEVNULL,
        )
        source_paths_raw = subprocess.check_output(
            [
                'git', '-C', str(REPO_ROOT), 'ls-files', '-z',
                '--cached', '--others', '--exclude-standard', '--',
                'app/backend/src',
            ],
            stderr=subprocess.DEVNULL,
        )
        source_paths = sorted(
            {
                value.decode('utf-8', errors='strict').replace('\\', '/')
                for value in source_paths_raw.split(b'\0')
                if value
            }
        )
        source_root = (REPO_ROOT / 'app' / 'backend' / 'src').resolve()
        tree_hasher = hashlib.sha256()
        source_file_count = 0
        for relative in source_paths:
            candidate = (REPO_ROOT / Path(relative)).resolve()
            try:
                candidate.relative_to(source_root)
            except ValueError as exc:
                raise OSError('execution source path escaped app/backend/src') from exc
            if not candidate.is_file():
                continue
            content_digest = hashlib.sha256(candidate.read_bytes()).digest()
            encoded_path = relative.encode('utf-8')
            tree_hasher.update(len(encoded_path).to_bytes(8, 'big'))
            tree_hasher.update(encoded_path)
            tree_hasher.update(content_digest)
            source_file_count += 1
        status_entries = [value for value in status_raw.split(b'\0') if value]
    except (OSError, UnicodeError, subprocess.CalledProcessError):
        return {
            'head': None,
            'status_short': None,
            'is_dirty': None,
            'status_count': None,
            'status_sha256': None,
            'execution_file_count': None,
            'execution_tree_sha256': None,
        }
    return {
        'head': head,
        'status_short': status_raw.decode('utf-8', errors='replace').replace('\0', '\n').strip(),
        'is_dirty': bool(status_entries),
        'status_count': len(status_entries),
        'status_sha256': hashlib.sha256(status_raw).hexdigest().upper(),
        'execution_file_count': source_file_count,
        'execution_tree_sha256': tree_hasher.hexdigest().upper(),
    }


def _current_execution_worktree_identity(
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    summary = summary if isinstance(summary, Mapping) else _current_git_summary()
    identity = {
        'schema': 'dxm.git-worktree.identity.v1',
        'git_head': summary.get('head'),
        'git_dirty': summary.get('is_dirty'),
        'status_count': summary.get('status_count'),
        'status_sha256': summary.get('status_sha256'),
        'execution_file_count': summary.get('execution_file_count'),
        'execution_tree_sha256': summary.get('execution_tree_sha256'),
    }
    if (
        not isinstance(identity['git_head'], str)
        or type(identity['git_dirty']) is not bool
        or type(identity['status_count']) is not int
        or not isinstance(identity['status_sha256'], str)
        or type(identity['execution_file_count']) is not int
        or not isinstance(identity['execution_tree_sha256'], str)
    ):
        raise HTTPException(
            status_code=409,
            detail='AUTH_WORKTREE_IDENTITY_UNAVAILABLE: exact execution worktree identity is required',
        )
    return identity


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
            'single_save_ready': False,
            'single_save_status': None,
            'state_consistent': False,
            'state_violation_codes': [],
        }
    gates = workspace.get('regression_gates') if isinstance(workspace, dict) else []
    l2_gate = _workspace_gate(gates, 'L2')
    l3_gate = _workspace_gate(gates, 'L3')
    delivery_readiness = workspace.get('delivery_readiness') if isinstance(workspace, dict) else {}
    delivery_ready = delivery_readiness.get('ready') is True if isinstance(delivery_readiness, dict) else False
    single_save_acceptance = workspace.get('single_save_acceptance') if isinstance(workspace, dict) else {}
    single_save_ready = single_save_acceptance.get('passed') is True if isinstance(single_save_acceptance, dict) else False
    single_save_status = single_save_acceptance.get('status') if isinstance(single_save_acceptance, dict) else None
    state_consistency = workspace.get('state_consistency') if isinstance(workspace, dict) else {}
    state_consistent = state_consistency.get('consistent') is True if isinstance(state_consistency, dict) else False
    state_violation_codes = list(state_consistency.get('violation_codes') or []) if isinstance(state_consistency, dict) else []
    l2_status = l2_gate.get('status') if l2_gate else None
    l3_status = l3_gate.get('status') if l3_gate else None
    if l2_status == 'passed' and l3_status == 'passed' and delivery_ready and single_save_ready and state_consistent:
        return {
            'readiness': 'READY',
            'blocked_reason': '',
            'l2_status': l2_status,
            'l3_status': l3_status,
            'delivery_ready': delivery_ready,
            'single_save_ready': single_save_ready,
            'single_save_status': single_save_status,
            'state_consistent': state_consistent,
            'state_violation_codes': state_violation_codes,
        }
    if not l2_gate or not l3_gate:
        reason = '当前运行门禁缺少 L2/L3 记录；不可依据旧自检报告启动真实写入。'
    elif l2_status != 'passed':
        reason = f"L2 gate is {l2_status}; {l2_gate.get('detail') or 'real DXM writes require fresh product-box readonly evidence.'}"
    elif l3_status != 'passed':
        reason = f"L3 gate is {l3_status}; {l3_gate.get('detail') or 'real DXM writes require fresh single_save canary evidence.'}"
    elif not single_save_ready:
        reason = f"Single-save acceptance is not passed: {single_save_status or 'missing'}; product-box, save, and unpublished proof are required."
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
        'single_save_ready': single_save_ready,
        'single_save_status': single_save_status,
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
    mode = str(task.get('mode') or payload.get('execution_mode') or '')
    try:
        if mode == 'batch_draft_save':
            return build_batch_draft_save_task_facts(
                task_id=int(task['id']),
                store_id=int(task['store_id']),
                product_ids=payload.get('product_ids') or [job.get('product_id') for job in jobs],
                plan_snapshot_id=int(payload.get('plan_snapshot_id') or 0),
                plan_snapshot_hash=str(
                    payload.get('plan_snapshot_hash')
                    or ((payload.get('plan_snapshot') or {}).get('snapshot_hash') if isinstance(payload.get('plan_snapshot'), dict) else '')
                    or ''
                ),
                path=str(payload.get('path') or ((payload.get('plan_snapshot') or {}).get('path') if isinstance(payload.get('plan_snapshot'), dict) else 'A') or 'A'),
            )
        if mode != 'single_save':
            raise HTTPException(
                status_code=409,
                detail='AUTH_TASK_MODE_MISMATCH: task is not an authorized save-only mode',
            )
        if len(jobs) != 1:
            raise HTTPException(status_code=409, detail='AUTH_TASK_JOB_SHAPE_MISMATCH: exactly one job is required')
        job = jobs[0]
        product = repo.get_product(int(job['product_id']))
        if not product:
            raise HTTPException(status_code=409, detail='AUTH_PRODUCT_NOT_FOUND: product-box item is unavailable')
        snapshot_error = repo.single_save_product_box_snapshot_error(task, product)
        if snapshot_error:
            raise HTTPException(
                status_code=409,
                detail=f'AUTH_PRODUCT_BOX_SNAPSHOT_MISMATCH: {snapshot_error}',
            )
        return build_save_task_facts(
            task_id=int(task['id']),
            job_id=int(job['id']),
            store_id=int(task['store_id']),
            product_id=int(product['id']),
            product_box_snapshot_fingerprint=str(payload['product_box_snapshot_fingerprint']),
        )
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError, SaveOnlyContractError, BatchDraftAuthorizationError) as exc:
        reason_code = getattr(exc, 'reason_code', 'AUTH_TASK_FACTS_INVALID')
        raise HTTPException(status_code=409, detail=f'{reason_code}: exact save-only task facts are invalid') from exc


def _build_task_authorization_context(
    task: dict[str, Any],
    *,
    approved_by: str,
    l2_gate: dict[str, Any],
) -> dict[str, Any]:
    git_summary = _current_git_summary()
    git_head = str(git_summary.get('head') or '').strip()
    mode = str(
        task.get('mode')
        or (
            task.get('payload', {}).get('execution_mode')
            if isinstance(task.get('payload'), Mapping)
            else ''
        )
        or ''
    ).strip()
    try:
        common = {
            'stage_task_facts': _build_task_stage_facts(task),
            'runtime_instance_id': str(runtime_identity.instance_id),
            'browser_session_id': _current_browser_session_id(),
            'git_head': git_head,
            'l2_evidence_fingerprint': _l2_authorization_fingerprint(l2_gate),
            'approved_by': approved_by,
        }
        if mode == 'batch_draft_save':
            return build_batch_authorization_context(
                **common,
                worktree_identity=_current_execution_worktree_identity(git_summary),
            )
        return build_save_authorization_context(**common)
    except (SaveOnlyContractError, BatchDraftAuthorizationError) as exc:
        raise HTTPException(status_code=409, detail=f'{exc.reason_code}: authorization context is invalid') from exc


def _verify_runner_authorization(task_id: int, mode: str, state: str) -> dict[str, Any]:
    required_state = {
        'single_save': 'SAVE_ONLY',
        'batch_draft_save': 'SAVE_ONLY',
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
    _assert_agent_console_browser_released(
        '已有旧 Agent Console 浏览器现场。请先关闭该现场，再批准真实任务。',
    )
    active_task = repo.get_active_task_execution()
    if active_task is not None and int(active_task['id']) != int(task_id):
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'LEGACY_TASK_ACTIVE',
                'message': (
                    f"任务 #{active_task['id']} 正在占用自动浏览器。"
                    '请等待任务结束后再批准下一项任务。'
                ),
            },
        )
    active_batch = repo.get_active_edit_batch_execution()
    if active_batch is not None:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'EDIT_BATCH_ACTIVE',
                'message': (
                    f"批次 #{active_batch['id']} 正在占用自动浏览器。"
                    '请等待完成或停止批次后再批准单商品任务。'
                ),
            },
        )
    mode = str(task.get('mode') or (task.get('payload') or {}).get('execution_mode') or '')
    if mode not in REAL_DXM_MUTATION_MODES:
        raise HTTPException(status_code=400, detail=f'Manual approval is only available for real DXM mutation modes: {mode}')
    if mode not in RELEASED_REAL_DXM_MUTATION_MODES:
        raise HTTPException(status_code=403, detail=UNRELEASED_REAL_DXM_MODE_DETAIL)
    if task.get('status') != 'draft':
        raise HTTPException(status_code=409, detail=f"Task cannot be approved from status: {task.get('status')}")
    if mode == 'batch_draft_save':
        _assert_batch_draft_save_task_scope(task)
    else:
        _assert_single_save_product_count(task.get('payload') or {}, status_code=409)
        _assert_single_save_uses_product_box_item((task.get('payload') or {}).get('product_ids') or [])
        if str(task.get('publish_scene') or '') != SAVE_ONLY_PUBLISH_SCENE:
            raise HTTPException(status_code=403, detail='Real DXM mutation task requires save-only publish scene')
    required_confirmation = L3_CONFIRMATION
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

    active_task = repo.get_active_task_execution()
    if active_task is not None and int(active_task['id']) != int(task_id):
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'LEGACY_TASK_ACTIVE',
                'message': (
                    f"任务 #{active_task['id']} 正在占用自动浏览器。"
                    '请等待任务结束后再启动下一项任务。'
                ),
            },
        )
    active_batch = repo.get_active_edit_batch_execution()
    if active_batch is not None:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'EDIT_BATCH_ACTIVE',
                'message': f"批次 #{active_batch['id']} 正在占用自动浏览器，请先等待完成或停止批次。",
            },
        )

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
    _assert_agent_console_browser_released(
        '已有旧 Agent Console 浏览器现场。请先关闭该现场，再启动真实任务。',
    )
    _assert_workflow_runtime_healthy()
    if mode not in RELEASED_REAL_DXM_MUTATION_MODES:
        raise HTTPException(status_code=403, detail=UNRELEASED_REAL_DXM_MODE_DETAIL)
    if mode == 'batch_draft_save':
        _assert_batch_draft_save_task_scope(task)
    else:
        _assert_single_save_product_count(task.get('payload') or {}, status_code=409)
        _assert_single_save_uses_product_box_item(payload.get('product_ids') or [])
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
    required_confirmation = L3_CONFIRMATION
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
    if mode in RELEASED_REAL_DXM_MUTATION_MODES and (
        isinstance(payload.store_id, bool)
        or not isinstance(payload.store_id, int)
        or payload.store_id <= 0
    ):
        raise HTTPException(
            status_code=400,
            detail='真实店小秘任务必须绑定一个明确店铺。',
        )
    if mode == 'single_save':
        _assert_single_save_product_count({'product_ids': payload.product_ids}, status_code=400)
        _assert_single_save_uses_product_box_item(
            payload.product_ids,
            expected_store_id=payload.store_id,
        )
    if mode == 'batch_draft_save':
        raise HTTPException(
            status_code=403,
            detail={
                'reason_code': 'BATCH_DRAFT_SAVE_CREATE_VIA_SNAPSHOT_ONLY',
                'message': 'batch_draft_save tasks must be created from a frozen plan_snapshot, not /api/tasks',
            },
        )


def _assert_batch_draft_save_task_scope(task: dict[str, Any]) -> None:
    payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
    if str(task.get('publish_scene') or '') != SAVE_ONLY_PUBLISH_SCENE:
        raise HTTPException(status_code=403, detail='Real DXM mutation task requires save-only publish scene')
    plan = payload.get('plan_snapshot') if isinstance(payload.get('plan_snapshot'), dict) else {}
    payload_path = str(payload.get('path') or '').strip().upper()
    snapshot_path = str(plan.get('path') or '').strip().upper()
    snapshot_hash = str(payload.get('plan_snapshot_hash') or plan.get('snapshot_hash') or '').strip()
    snapshot_id = payload.get('plan_snapshot_id')
    if (
        not plan
        or not snapshot_hash
        or not isinstance(snapshot_id, int)
        or isinstance(snapshot_id, bool)
        or snapshot_id <= 0
    ):
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_PLAN_SNAPSHOT_REQUIRED',
                'message': 'batch_draft_save requires a frozen plan_snapshot id and hash',
            },
        )
    if plan and str(plan.get('snapshot_hash') or '').strip() and str(plan.get('snapshot_hash')).strip() != snapshot_hash:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_PLAN_SNAPSHOT_HASH_MISMATCH',
                'message': 'task plan_snapshot_hash does not match embedded plan_snapshot',
            },
        )
    if payload_path not in ('A', 'B') or snapshot_path not in ('A', 'B'):
        raise HTTPException(
            status_code=403,
            detail={
                'reason_code': 'BATCH_PATH_REQUIRED',
                'message': 'batch_draft_save requires path=A or path=B',
            },
        )
    if (
        not is_plan_execution_path_released(payload_path)
        or not is_plan_execution_path_released(snapshot_path)
    ):
        raise HTTPException(
            status_code=403,
            detail={
                'reason_code': 'BATCH_PATH_B_FORBIDDEN',
                'contract_reason_code': PLAN_PATH_EXECUTION_NOT_RELEASED,
                'message': 'Path B 双保存授权、派发、账本和证据合同尚未完整接通，真实执行保持锁定。',
            },
        )
    if payload_path != snapshot_path:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_PATH_MISMATCH',
                'message': '任务路径必须与冻结方案路径完全一致。',
            },
        )
    if payload.get('publish_allowed') is True or plan.get('publish_allowed') is True:
        raise HTTPException(
            status_code=403,
            detail={
                'reason_code': 'BATCH_PUBLISH_FORBIDDEN',
                'message': 'batch_draft_save forbids publish_allowed=true',
            },
        )
    try:
        E2PlanService().assert_task_snapshot_binding(task)
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                'reason_code': exc.reason_code,
                'message': str(exc),
            },
        ) from exc
    product_ids = payload.get('product_ids')
    if not isinstance(product_ids, list) or not product_ids:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_PRODUCT_IDS_REQUIRED',
                'message': 'batch_draft_save requires one or more product_ids from the frozen snapshot',
            },
        )
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in product_ids):
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_PRODUCT_IDS_INVALID',
                'message': 'batch_draft_save product_ids must be positive integers',
            },
        )
    if len(set(product_ids)) != len(product_ids):
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_PRODUCT_DUPLICATE',
                'message': 'batch_draft_save product_ids must be unique',
            },
        )
    jobs = task.get('jobs') if isinstance(task.get('jobs'), list) else []
    job_product_ids = [
        int(job['product_id'])
        for job in jobs
        if isinstance(job, dict) and not isinstance(job.get('product_id'), bool) and isinstance(job.get('product_id'), int)
    ]
    if job_product_ids != [int(value) for value in product_ids]:
        raise HTTPException(
            status_code=409,
            detail={
                'reason_code': 'BATCH_JOB_PRODUCT_MISMATCH',
                'message': 'batch_draft_save jobs must match frozen product_ids',
            },
        )
    if payload.get('publish_allowed') is True:
        raise HTTPException(
            status_code=403,
            detail={
                'reason_code': 'BATCH_PUBLISH_FORBIDDEN',
                'message': 'batch_draft_save forbids publish_allowed=true',
            },
        )


def _assert_single_save_uses_product_box_item(
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
    source = str(product.get('source') or '').strip()
    if status != 'ready_for_edit':
        raise HTTPException(
            status_code=409,
            detail=(
                '编辑保存必须从商品箱里的真实商品开始。'
                '请刷新当前商品箱现场并重新选择商品。'
            ),
        )
    if source != 'dxm_draft_box':
        raise HTTPException(
            status_code=409,
            detail=(
                '编辑保存必须从真实店小秘商品箱现场读取商品。'
                '手工创建或本地导入商品不能启动真实保存。'
            ),
        )
    if payload.get('draft_box_verified') is not True:
        raise HTTPException(
            status_code=409,
            detail=(
                '编辑保存必须先确认商品当前仍在商品箱。'
                '请刷新商品箱现场后重新创建单商品只保存任务。'
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
                '请刷新商品箱现场，并确认能唯一匹配本次商品后再创建任务。'
            ),
        )
    product_store_id = payload.get('store_id')
    if expected_store_id is not None and (
        isinstance(expected_store_id, bool)
        or isinstance(product_store_id, bool)
        or not isinstance(product_store_id, int)
        or product_store_id != int(expected_store_id)
    ):
        raise HTTPException(
            status_code=409,
            detail='单商品只保存的店铺与商品箱现场店铺不一致；请从当前店铺商品箱重新选择。',
        )


def _assert_single_save_product_count(payload: dict[str, Any], *, status_code: int) -> None:
    product_ids = payload.get('product_ids') if isinstance(payload, dict) else None
    product_count = len(product_ids) if isinstance(product_ids, list) else 0
    product_id = product_ids[0] if product_count == 1 else None
    if (
        product_count != 1
        or isinstance(product_id, bool)
        or not isinstance(product_id, int)
        or product_id <= 0
    ):
        raise HTTPException(
            status_code=status_code,
            detail='single_save requires exactly one product with a positive product id',
        )


def _assert_direct_real_dxm_mutation_allowed(_payload: DraftBoxActionRequest) -> NoReturn:
    raise HTTPException(
        status_code=403,
        detail={
            'reason_code': 'DIRECT_MUTATION_ROUTE_DISABLED',
            'message': (
                '旧直连写入口已关闭。真实店小秘变更只能通过受控单任务运行器，'
                '或“范围冻结→整批模板→一次批准→严格串行”的商品箱批次执行。'
            ),
        },
    )


# ============================================================
# 批量保存安全门禁
# ============================================================


class BatchPauseError(Exception):
    """批量执行暂停异常"""
    def __init__(self, reason: str, rollback_required: bool = False, field_changes: list = None):
        super().__init__(reason)
        self.reason = reason
        self.rollback_required = rollback_required
        self.field_changes = field_changes or []


class BatchRollbackCompleteError(Exception):
    """批量回滚完成异常"""
    def __init__(self, reason: str, field_changes: list):
        super().__init__(reason)
        self.reason = reason
        self.field_changes = field_changes


def _assert_semi_managed_detect_allowed(detect_result: dict) -> None:
    """半托管检测失败门禁 - 检测失败必须暂停并回滚"""
    if not detect_result.get("pass", False):
        error_type = detect_result.get("error_type", "unknown")
        error_message = detect_result.get("error_message", "未知错误")

        if error_type == "product_missing":
            raise BatchPauseError(
                reason=f"店小秘返回：仿品检测未通过 - {error_message}",
                rollback_required=True,
            )
        else:
            raise BatchPauseError(
                reason=f"半托管检测失败：{error_message}",
                rollback_required=True,
            )


def _assert_video_generation_failure_handled(
    error_type: str,
    strategy: str,
    error_message: str,
) -> None:
    """视频生成失败处理门禁"""
    if error_type == "quota_exhausted":
        if strategy == "pause":
            raise BatchPauseError(
                reason=f"店小秘返回：免费额度已用完，根据策略暂停执行 - {error_message}",
                rollback_required=False,
            )
        # else: strategy == "ignore"，继续执行
    elif error_type in ("program_error", "timeout", "page_error"):
        # 程序问题失败必须暂停
        raise BatchPauseError(
            reason=f"视频生成失败（{error_type}）：{error_message}",
            rollback_required=True,
        )


def _assert_translate_allowed(translate_result: dict) -> None:
    """翻译失败门禁"""
    if not translate_result.get("success", True):
        raise BatchPauseError(
            reason=f"翻译执行失败：{translate_result.get('error_message', '未知错误')}",
            rollback_required=False,
        )


def _assert_batch_rollback_completed(
    rollback_result: dict,
    reason: str,
) -> None:
    """回滚完成门禁"""
    if not rollback_result.get("success", True):
        raise BatchRollbackCompleteError(
            reason=f"回滚未完成：{rollback_result.get('error_message', '未知错误')}。原暂停原因：{reason}",
            field_changes=rollback_result.get("field_changes", []),
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


class DxmSessionBusyError(RuntimeError):
    """The visible Playwright session is already serving another API call."""


def _dxm_session_busy_http_exception() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            'reason_code': 'DXM_SESSION_BUSY',
            'message': '真实可见浏览器正在处理上一条会话操作；请求未排队，请稍后重试。',
        },
    )


def _run_login_flow(func, *args, fail_if_busy: bool = False, **kwargs):
    acquired = login_flow_api_lock.acquire(blocking=not fail_if_busy)
    if not acquired:
        raise DxmSessionBusyError('DXM_SESSION_BUSY')
    try:
        return browser_agent_runtime.run_session_operation(func, *args, **kwargs)
    finally:
        login_flow_api_lock.release()


def _login_flow_failure_state(label: str, message: str, next_action: str, raw_error: str | None = None) -> dict[str, Any]:
    return {
        'ok': False,
        'stage': 'login_failed',
        'reason_code': 'VISIBLE_SESSION_OPERATION_FAILED',
        'logged_in': False,
        'reader_ready': False,
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
            'message': '已检测到真实店小秘登录态；受控单商品只保存可在商品箱现场校验后启动。',
            'next_action': '先完成配置预检和 L2 复验，再按人工审批启动；batch_save 和发布仍关闭。',
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
