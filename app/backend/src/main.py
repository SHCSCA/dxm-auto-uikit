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
    PATH_B_FORMAL_LINEAGE_KEY,
    PATH_B_SAVE1_DISCOVERY_ACTION,
    PATH_B_SAVE1_DISCOVERY_STATE,
    BatchCommandContractError,
    validate_current_batch_queue_guard,
    validate_path_b_save1_discovery_dispatch,
    validate_path_b_formal_lineage,
)
from src.execution.batch_dispatch_authority import LiveDispatchFacts
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.controlled_mutation_dispatch import ControlledMutationDispatch
from src.execution.playwright_engine import PlaywrightEngine
from src.execution.v1_runner import V1TaskRunner
from src.real_dxm_write_scope import (
    RealDxmWriteScopeError,
    canonical_sha256 as real_scope_sha256,
    prepare_real_dxm_write_scope,
    validate_real_dxm_write_authorization,
    validate_real_dxm_write_scope,
)
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
    RealDxmPathBDiscoveryStartRequest,
    RealDxmPathBScopeDeriveRequest,
    RealDxmWriteScopePrepareRequest,
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
from src.batch_edit.plan_snapshot_store import PlanSnapshotStore
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
controlled_mutation_dispatch = ControlledMutationDispatch(
    mutation_dispatch_ledger,
    recover_inflight=False,
)
browser_agent_runtime = BrowserAgentRuntime(
    workflow_adapter,
    mutation_ledger=controlled_mutation_dispatch,
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
    command_contract = {
        'SAVE_ONLY': ('save_only', 'editor', 'save_only_click'),
        'SAVE2_ONLY': ('save_only', 'semi_managed', 'save_only_click'),
        PATH_B_SAVE1_DISCOVERY_STATE: (
            PATH_B_SAVE1_DISCOVERY_ACTION,
            'editor',
            'first_save_intent',
        ),
    }.get(str(command.state or ''))
    if (
        command_contract is None
        or command.action != command_contract[0]
        or command.execution_mode != 'batch_draft_save'
        or command.expected_page != command_contract[1]
        or not isinstance(command.params, dict)
    ):
        return _reject_batch_command_authorization('AUTH_COMMAND_MODE_MISMATCH')
    if (
        not isinstance(context, Mapping)
        or context.get('mutation_action') != command_contract[2]
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
        discovery_profile = validate_path_b_save1_discovery_dispatch(
            task,
            job_id=command.job_id,
            command_state=command.state,
            command_action=command.action,
        )
    except BatchCommandContractError as exc:
        return _reject_batch_command_authorization(exc.reason_code)
    if (
        command.state == PATH_B_SAVE1_DISCOVERY_STATE
        and discovery_profile is None
    ):
        return _reject_batch_command_authorization('DISCOVERY_PROFILE_REQUIRED')
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
    expected_lease_id = str(approval.get('lease_id') or '')
    if stage_facts.get('path') == 'B':
        real_authorization = (
            payload.get('real_dxm_write_authorization')
            if isinstance(payload.get('real_dxm_write_authorization'), Mapping)
            else None
        )
        save_stage = (
            'SAVE1'
            if command.state in {'SAVE_ONLY', 'FIRST_SAVE_INTENT'}
            else 'SAVE2'
        )
        leases = (
            real_authorization.get('save_leases')
            if isinstance(real_authorization, Mapping)
            and isinstance(real_authorization.get('save_leases'), list)
            else []
        )
        matching_leases = [
            item
            for item in leases
            if isinstance(item, Mapping)
            and item.get('product_id') == product_id
            and item.get('save_stage') == save_stage
        ]
        if len(matching_leases) != 1:
            return _reject_batch_command_authorization(
                'AUTH_COMMAND_AUTHORIZATION_MISMATCH'
            )
        expected_lease_id = str(matching_leases[0].get('lease_id') or '')
        expected_lease_fingerprint = real_scope_sha256(dict(matching_leases[0]))
        if not hmac.compare_digest(
            str(command.authorization_lease_fingerprint or '').casefold(),
            expected_lease_fingerprint.casefold(),
        ):
            return _reject_batch_command_authorization(
                'AUTH_COMMAND_AUTHORIZATION_MISMATCH'
            )
    if (
        str(command.authorization_lease_id or '') != expected_lease_id
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
            command.action,
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


def _trusted_real_write_stage_by_field(
    item_snapshot: Mapping[str, Any],
) -> dict[str, str] | None:
    """Read an exact frozen SAVE1/SAVE2 field partition, if one exists.

    Compiler-v3 snapshots derive ``real_write_stage_fields`` only from the
    frozen Reader schema ``ui_section`` facts.  The Prepare surface still
    treats any absent, empty, duplicated, or malformed partition as missing
    authority; it never infers a physical SAVE phase from an operator label or
    field name.
    """

    raw = item_snapshot.get('real_write_stage_fields')
    if not isinstance(raw, Mapping) or set(raw) != {'SAVE1', 'SAVE2'}:
        return None
    result: dict[str, str] = {}
    for stage in ('SAVE1', 'SAVE2'):
        fields = raw.get(stage)
        if not isinstance(fields, list) or not fields:
            return None
        for field in fields:
            if (
                not isinstance(field, str)
                or not field
                or field != field.strip()
                or field in result
            ):
                return None
            result[field] = stage
    return result


def _scope_prepare_snapshot_projection(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Project a plan snapshot to hashes only; never expose frozen field values."""

    session = snapshot.get('session_context') if isinstance(snapshot.get('session_context'), Mapping) else {}
    projected_products: list[dict[str, Any]] = []
    for item in snapshot.get('item_snapshots') or []:
        if not isinstance(item, Mapping):
            continue
        current_values = item.get('current_value_snapshot')
        current_values = current_values if isinstance(current_values, Mapping) else {}
        resolution = item.get('resolution_result') if isinstance(item.get('resolution_result'), Mapping) else {}
        trusted_stages = _trusted_real_write_stage_by_field(item)
        trusted_stages = trusted_stages if trusted_stages is not None else {}
        projected_fields: list[dict[str, Any]] = []
        for field in resolution.get('resolved_fields') or []:
            if not isinstance(field, Mapping) or not isinstance(field.get('field_key'), str):
                continue
            field_key = field['field_key']
            projected = {
                'field': field_key,
                'saveStage': trusted_stages.get(field_key),
                'expectedSha256': (
                    real_scope_sha256(field['resolved_value'])
                    if 'resolved_value' in field
                    else None
                ),
                'preimageAvailable': field_key in current_values,
                'preimageSha256': (
                    real_scope_sha256(current_values[field_key])
                    if field_key in current_values
                    else None
                ),
            }
            projected_fields.append(projected)
        projected_products.append({
            'productId': int(item['product_id']),
            'fieldHashes': projected_fields,
            'fieldHashesSha256': real_scope_sha256(projected_fields),
        })
    return {
        'schemaVersion': 'real_dxm_path_b_scope_prepare_projection.v1',
        **({'snapshotId': int(snapshot['id'])} if isinstance(snapshot.get('id'), int) else {}),
        **({'taskId': int(snapshot['task_id'])} if isinstance(snapshot.get('task_id'), int) else {}),
        'snapshotSha256': str(snapshot.get('snapshot_hash') or ''),
        'path': str(snapshot.get('path') or ''),
        'publishAllowed': snapshot.get('publish_allowed'),
        'shop': {
            'shopId': int(snapshot.get('shop_scope') or 0),
            'shopName': str(session.get('shop_name') or ''),
        },
        'readerSessionRef': str(session.get('session_ref') or ''),
        'accountContextHash': str(session.get('account_ref_hash') or ''),
        'orderedProductIds': [int(value) for value in snapshot.get('product_ids') or []],
        'orderedProducts': projected_products,
        'mutationCount': 0,
        'publishCount': 0,
        'counterEvidence': {
            'source': 'prepare_route_contract_declaration',
            'measured': False,
            'requiredIndependentCheck': 'task_acceptance_export_before_after',
        },
    }


@app.post('/api/plan-snapshots/preview')
def preview_plan_snapshot(
    payload: PlanSnapshotRequest,
    projection: str = Query(default='full', pattern=r'^(?:full|scope_prepare)$'),
):
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
        return (
            _scope_prepare_snapshot_projection(snapshot)
            if projection == 'scope_prepare'
            else snapshot
        )
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
def freeze_plan_snapshot(
    payload: PlanSnapshotRequest,
    projection: str = Query(default='full', pattern=r'^(?:full|scope_prepare)$'),
):
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
        frozen = service.freeze_plan_snapshot(
            authoritative["request"],
            expected_snapshot_hash=payload.expected_snapshot_hash,
            idempotency_key=payload.idempotency_key,
        )
        return (
            _scope_prepare_snapshot_projection(frozen)
            if projection == 'scope_prepare'
            else frozen
        )
    except DxmSessionBusyError as exc:
        raise _dxm_session_busy_http_exception() from exc
    except (DxmPlanReaderError, DxmDraftReaderError, PlanContractError, PlanSchemaError) as exc:
        raise HTTPException(
            status_code=getattr(exc, "status_code", 409),
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.get('/api/plan-snapshots/{snapshot_id}')
def get_plan_snapshot(
    snapshot_id: int,
    projection: str = Query(default='full', pattern=r'^(?:full|scope_prepare)$'),
):
    try:
        snapshot = E2PlanService().get_plan_snapshot(snapshot_id)
        return (
            _scope_prepare_snapshot_projection(snapshot)
            if projection == 'scope_prepare'
            else snapshot
        )
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.post('/api/plan-snapshots/{snapshot_id}/tasks', status_code=201)
def create_batch_draft_save_task(
    snapshot_id: int,
    projection: str = Query(default='full', pattern=r'^(?:full|scope_prepare)$'),
):
    try:
        task = E2PlanService().create_task_from_snapshot(snapshot_id, repo)
        if projection != 'scope_prepare':
            return task
        private_task = repo.get_task_private(int(task['id']))
        if not isinstance(private_task, Mapping):
            raise PlanContractError(
                'PLAN_SNAPSHOT_TASK_NOT_ATOMIC',
                'snapshot task is missing after atomic freeze',
            )
        frozen = E2PlanService().assert_task_snapshot_binding(private_task)
        return {
            **_scope_prepare_snapshot_projection({
                **dict(frozen),
                'id': snapshot_id,
                'task_id': int(task['id']),
            }),
            'taskStatus': private_task.get('status'),
            'jobProductIds': [
                int(job['product_id'])
                for job in private_task.get('jobs') or []
                if isinstance(job, Mapping)
            ],
        }
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc


@app.post('/api/real-dxm/path-b/scopes/prepare')
def prepare_real_dxm_path_b_scope(payload: RealDxmWriteScopePrepareRequest):
    """Validate and register an external, zero-write Path B scope."""

    try:
        canonical_scope = validate_real_dxm_write_scope(payload.scope)
    except RealDxmWriteScopeError as exc:
        _scope_rejected(exc.detail_code, '真实写 scope 合同无效。')
    task_id = int(canonical_scope['snapshot']['taskId'])
    task = repo.get_task_private(task_id)
    if not isinstance(task, Mapping):
        _scope_rejected('TASK_NOT_FOUND', 'scope 指向的冻结任务不存在。')
    _validate_real_scope_task_binding(task, canonical_scope)
    persisted = repo.prepare_real_dxm_write_scope(canonical_scope)
    if persisted.get('ok') is not True:
        _scope_rejected(
            str(persisted.get('detail_code') or 'SCOPE_PERSISTENCE_REJECTED'),
            'scope 无法形成一次性持久绑定。',
        )
    return {
        'ok': True,
        'status': 'SCOPE_PREPARED',
        'reasonCode': 'OK',
        'scopeSha256': canonical_scope['scopeSha256'],
        'taskId': task_id,
        'orderedProductCount': len(canonical_scope['orderedProducts']),
        'mutationCount': 0,
        'publishCount': 0,
        'counterEvidence': {
            'source': 'prepare_route_contract_declaration',
            'measured': False,
            'requiredIndependentCheck': 'task_acceptance_export',
        },
    }


@app.post('/api/real-dxm/path-b/discovery/approve-and-start')
async def approve_and_start_real_dxm_path_b_discovery(
    payload: RealDxmPathBDiscoveryStartRequest,
):
    """Arm exactly one first-product composite SAVE1 and dispatch its runner."""

    task_id = int(payload.taskId)
    task = repo.get_task_private(task_id)
    if not isinstance(task, Mapping):
        raise HTTPException(status_code=404, detail='Task not found')
    _assert_agent_console_browser_released(
        '已有旧 Agent Console 浏览器现场。请先关闭该现场，再批准 Discovery。',
    )
    _assert_workflow_runtime_healthy()
    if (
        task.get('status') != 'draft'
        or str(task.get('mode') or '') != 'batch_draft_save'
        or _task_plan_path(task) != 'B'
        or (task.get('payload') or {}).get('publish_allowed') is not False
    ):
        _scope_rejected(
            'DISCOVERY_TASK_BOUNDARY_INVALID',
            'Discovery 只接受尚未启动且永久禁止发布的 Path B draft task。',
        )
    jobs = task.get('jobs') if isinstance(task.get('jobs'), list) else []
    if (
        len(jobs) != 3
        or any(not isinstance(job, Mapping) for job in jobs)
        or int(jobs[0].get('product_id') or 0) != int(payload.targetProductId)
        or any(str(job.get('status') or '') != 'pending' for job in jobs)
    ):
        _scope_rejected(
            'DISCOVERY_QUEUE_INVALID',
            'Discovery 必须绑定 exact 三商品队列的首商品，且三个 job 均未执行。',
        )
    if payload.confirmation != L3_CONFIRMATION:
        raise HTTPException(
            status_code=400,
            detail=f'confirmation must be {L3_CONFIRMATION}',
        )
    active_task = repo.get_active_task_execution()
    if active_task is not None and int(active_task['id']) != task_id:
        _scope_rejected('AUTH_ANOTHER_TASK_ACTIVE', '已有真实任务占用浏览器。')
    if repo.get_active_edit_batch_execution() is not None:
        _scope_rejected('AUTH_EDIT_BATCH_ACTIVE', '已有编辑批次占用浏览器。')
    l2_gate = l2_real_probe_gate()
    if l2_gate.get('status') != 'passed':
        _scope_rejected('L2_NOT_PASSED', 'Discovery 需要 fresh passed L2。')
    authorization = _validate_real_scope_task_binding(
        task,
        payload.realDxmWriteScope,
        raw_approval=payload.realDxmWriteApproval,
        approved_by=payload.approvedBy,
    )
    scope_sha256 = str(authorization['scope']['scopeSha256'])
    prepared = repo.get_real_dxm_write_scope(scope_sha256)
    if (
        not isinstance(prepared, Mapping)
        or prepared.get('status') != 'prepared'
        or prepared.get('purpose') not in {None, 'general', 'discovery'}
        or prepared.get('lineage_discovery_receipt_sha256') is not None
        or prepared.get('lineage_predecessor_scope_sha256') is not None
    ):
        _scope_rejected(
            'SCOPE_NOT_PREPARED_OR_CONSUMED',
            'Discovery scope 未 Prepare、已消费或误带 Formal 谱系。',
        )
    discovery_key_sha256 = hashlib.sha256(
        payload.discoveryKey.encode('utf-8')
    ).hexdigest().upper()
    request_sha256 = real_scope_sha256(payload.model_dump(mode='json'))
    result = repo.approve_and_start_real_dxm_path_b_discovery(
        task_id,
        scope=authorization['scope'],
        approval=authorization['approval'],
        target_product_id=int(payload.targetProductId),
        discovery_key_sha256=discovery_key_sha256,
        request_sha256=request_sha256,
        token=secrets.token_urlsafe(24),
        confirmation=payload.confirmation,
        approved_by=payload.approvedBy.strip(),
        lease_id=uuid.uuid4().hex,
    )
    if not result.ok:
        _scope_rejected(
            result.reason_code,
            'Discovery attempt 未能原子 arm；没有浏览器动作被派发。',
        )
    asyncio.create_task(runner.run_task(task_id))
    return {
        'ok': True,
        'taskId': task_id,
        'status': 'running',
        'authorizationConsumed': True,
        'discoveryKeySha256': discovery_key_sha256,
        'scopeSha256': scope_sha256,
    }


@app.get(
    '/api/real-dxm/path-b/discovery/by-key-sha256/{discovery_key_sha256}'
)
def get_real_dxm_path_b_discovery_by_key_sha256(
    discovery_key_sha256: str,
):
    """Recover an ambiguous Discovery POST without ever replaying it."""

    normalized = _acceptance_digest(discovery_key_sha256)
    if normalized is None:
        raise HTTPException(
            status_code=400,
            detail={
                'reason_code': 'DISCOVERY_KEY_SHA256_INVALID',
                'message': 'discovery key hash must be 64 uppercase hex characters',
            },
        )
    result = repo.get_real_dxm_path_b_discovery_by_key_sha256(normalized)
    if not isinstance(result, Mapping):
        raise HTTPException(status_code=404, detail='Discovery attempt not found')
    return dict(result)


def _real_path_b_scope_prepare_result(
    scope: Mapping[str, Any],
    *,
    prepare_request_sha256: str,
    reused: bool,
    purpose: str = 'discovery',
    predecessor_scope_sha256: str | None = None,
    discovery_receipt_sha256: str | None = None,
) -> dict[str, Any]:
    return {
        'schemaVersion': 'real_dxm_path_b_scope_prepare_result.v1',
        'ok': True,
        'status': 'SCOPE_PREPARED',
        'reasonCode': 'OK',
        'scope': dict(scope),
        'scopeSha256': scope['scopeSha256'],
        'prepareRequestSha256': prepare_request_sha256,
        'reused': reused,
        'purpose': purpose,
        'predecessorScopeSha256': predecessor_scope_sha256,
        'discoveryReceiptSha256': discovery_receipt_sha256,
        'task': {
            'taskId': scope['snapshot']['taskId'],
            'snapshotId': scope['snapshot']['snapshotId'],
            'snapshotSha256': scope['snapshot']['snapshotSha256'],
            'path': 'B',
            'orderedProductIds': [
                item['productId'] for item in scope['orderedProducts']
            ],
        },
        'provenance': {
            'factsSource': 'current_backend',
            'operatorHashBindingsSha256': real_scope_sha256(
                [item['allowedFields'] for item in scope['orderedProducts']]
            ),
        },
        'counters': {
            'physicalSave': 0,
            'browserMutation': 0,
            'publishRequest': 0,
        },
        'counterEvidence': {
            'source': 'prepare_route_contract_declaration',
            'measured': False,
            'requiredIndependentCheck': 'task_acceptance_export_before_after',
        },
    }


def _assert_formal_scope_continues_discovery(
    scope: Mapping[str, Any],
    discovery_receipt: Mapping[str, Any],
    *,
    predecessor_scope_sha256: str,
) -> None:
    """Require a fresh scope whose first SAVE1 preimage is Discovery output."""

    if (
        _acceptance_digest(scope.get('scopeSha256'))
        == _acceptance_digest(predecessor_scope_sha256)
        or scope.get('account', {}).get('accountContextHash')
        != discovery_receipt.get('account_ref_hash')
        or scope.get('shop', {}).get('shopId') != discovery_receipt.get('shop_id')
        or scope.get('shop', {}).get('shopName')
        != discovery_receipt.get('shop_name')
        or scope.get('git', {}).get('head') != discovery_receipt.get('git_head')
        or scope.get('worktree') != discovery_receipt.get('worktree')
        or scope.get('runtime') != discovery_receipt.get('runtime')
        or [item.get('productId') for item in scope.get('orderedProducts', [])]
        != discovery_receipt.get('ordered_product_ids')
    ):
        _scope_rejected(
            'DISCOVERY_FORMAL_IDENTITY_DRIFT',
            'Formal 必须保持同账号、店铺、HEAD、clean worktree、runtime、browser session 与商品顺序。',
        )
    first_products = [
        item
        for item in scope.get('orderedProducts', [])
        if isinstance(item, Mapping) and item.get('ordinal') == 1
    ]
    raw_readbacks = discovery_receipt.get('field_readbacks')
    if len(first_products) != 1 or not isinstance(raw_readbacks, list) or not raw_readbacks:
        _scope_rejected(
            'DISCOVERY_AFTER_READBACK_MISSING',
            'sealed Discovery 缺少首商品 SAVE1 字段读回。',
        )
    formal_save1 = {
        item.get('field'): item.get('preimageSha256')
        for item in first_products[0].get('allowedFields', [])
        if isinstance(item, Mapping) and item.get('saveStage') == 'SAVE1'
    }
    discovery_after: dict[str, str] = {}
    for item in raw_readbacks:
        if (
            not isinstance(item, Mapping)
            or item.get('readback_proven') is not True
            or not isinstance(item.get('field_key'), str)
            or not str(item.get('field_key') or '').strip()
        ):
            _scope_rejected(
                'DISCOVERY_AFTER_READBACK_INVALID',
                'Discovery 字段读回不是可验证的 canonical readback。',
            )
        field_key = str(item['field_key'])
        if field_key in discovery_after:
            _scope_rejected(
                'DISCOVERY_AFTER_READBACK_DUPLICATE',
                'Discovery 字段读回发生重复。',
            )
        discovery_after[field_key] = _acceptance_sha256(item.get('after_value'))
    if formal_save1 != discovery_after:
        _scope_rejected(
            'DISCOVERY_AFTER_TO_FORMAL_PREIMAGE_MISMATCH',
            'Formal 首商品 SAVE1 preimage 必须精确等于 Discovery 已验证 after value。',
        )


@app.get('/api/tasks/{task_id}/scope-prepare')
def get_real_dxm_path_b_scope_prepare_task(task_id: int):
    """Return only the hash projection needed by the external Prepare script."""

    task = repo.get_task_private(task_id)
    if not isinstance(task, Mapping):
        raise HTTPException(status_code=404, detail='Task not found')
    try:
        frozen = E2PlanService().assert_task_snapshot_binding(task)
    except PlanContractError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={'reason_code': exc.reason_code, 'message': str(exc)},
        ) from exc
    if str(frozen.get('path') or '').upper() != 'B':
        _scope_rejected('TASK_PATH_MISMATCH', 'scope Prepare 只接受冻结 Path B 任务。')
    projection = _scope_prepare_snapshot_projection({
        **dict(frozen),
        'id': int((task.get('payload') or {}).get('plan_snapshot_id') or 0),
        'task_id': task_id,
    })
    return {
        **projection,
        'taskStatus': task.get('status'),
        'jobProductIds': [
            int(job['product_id'])
            for job in task.get('jobs') or []
            if isinstance(job, Mapping)
        ],
    }


@app.post('/api/real-dxm/path-b/scopes/derive-and-prepare')
def derive_and_prepare_real_dxm_path_b_scope(
    payload: RealDxmPathBScopeDeriveRequest,
):
    """Derive current authority facts and persist a zero-real-write Path B scope.

    The caller supplies only an exact, hash-only field allowlist.  Account,
    shop, snapshot, Git/worktree, runtime/browser session, L2, timestamps and
    nonce are all derived by the current backend and revalidated before the
    scope registry is touched.
    """

    request_body = payload.model_dump(mode='json')
    has_predecessor = payload.predecessorScopeSha256 is not None
    has_discovery_receipt = payload.discoveryReceiptSha256 is not None
    if has_predecessor != has_discovery_receipt:
        _scope_rejected(
            'FORMAL_LINEAGE_PAIR_REQUIRED',
            'Formal Prepare 必须同时携带 predecessorScopeSha256 与 discoveryReceiptSha256。',
        )
    purpose = 'formal' if has_predecessor else 'discovery'
    predecessor_scope_sha256 = (
        str(payload.predecessorScopeSha256 or '').upper() or None
    )
    discovery_receipt_sha256 = (
        str(payload.discoveryReceiptSha256 or '').upper() or None
    )
    discovery_lineage: Mapping[str, Any] | None = None
    discovery_receipt: Mapping[str, Any] | None = None
    if purpose == 'formal':
        discovery_lineage = repo.get_real_dxm_path_b_discovery_by_receipt_sha256(
            str(discovery_receipt_sha256)
        )
        discovery_receipt = (
            discovery_lineage.get('receipt')
            if isinstance(discovery_lineage, Mapping)
            and isinstance(discovery_lineage.get('receipt'), Mapping)
            else None
        )
        if (
            not isinstance(discovery_lineage, Mapping)
            or discovery_lineage.get('ok') is not True
            or discovery_lineage.get('status') != 'DISCOVERY_SEALED'
            or not isinstance(discovery_receipt, Mapping)
            or _acceptance_digest(
                discovery_receipt.get('discovery_receipt_sha256')
            )
            != discovery_receipt_sha256
            or _acceptance_digest(discovery_receipt.get('scope_sha256'))
            != predecessor_scope_sha256
        ):
            _scope_rejected(
                'DISCOVERY_RECEIPT_MISSING_OR_INVALID',
                'Formal Prepare 未找到可复验的 sealed Discovery receipt。',
            )
    prepare_request_sha256 = real_scope_sha256(request_body)
    prepare_key_sha256 = hashlib.sha256(
        payload.prepareKey.encode('utf-8')
    ).hexdigest().upper()
    nonce_prefix = (
        f"prepare.{prepare_key_sha256[:24]}."
        f"{prepare_request_sha256[:24]}."
    )
    task = repo.get_task_private(payload.taskId)
    if not isinstance(task, Mapping):
        _scope_rejected('TASK_NOT_FOUND', 'Prepare 指向的冻结任务不存在。')
    if task.get('status') != 'draft':
        _scope_rejected('TASK_NOT_DRAFT', 'Prepare 只接受尚未启动的 draft 任务。')
    try:
        frozen = E2PlanService().assert_task_snapshot_binding(task)
    except PlanContractError as exc:
        _scope_rejected(exc.reason_code, '冻结任务与 plan snapshot 绑定无效。')
    if str(frozen.get('path') or '').upper() != 'B':
        _scope_rejected('TASK_PATH_MISMATCH', 'Prepare 只接受冻结 Path B。')
    if frozen.get('publish_allowed') is not False:
        _scope_rejected('PUBLISH_INTENT_FORBIDDEN', '冻结任务必须永久禁止发布。')
    if purpose == 'formal' and (
        int(discovery_receipt.get('task_id') or 0) == int(payload.taskId)
        or int(discovery_receipt.get('snapshot_id') or 0)
        == int((task.get('payload') or {}).get('plan_snapshot_id') or 0)
        or str(discovery_receipt.get('snapshot_sha256') or '').upper()
        == str((task.get('payload') or {}).get('plan_snapshot_hash') or '').upper()
    ):
        _scope_rejected(
            'FORMAL_TASK_OR_SNAPSHOT_NOT_FRESH',
            'Formal 必须由新的 Reader/preview/freeze/task/snapshot 派生。',
        )

    requested_product_ids = [item.productId for item in payload.orderedProducts]
    task_product_ids = list((task.get('payload') or {}).get('product_ids') or [])
    job_product_ids = [
        int(job['product_id'])
        for job in task.get('jobs') or []
        if isinstance(job, Mapping)
    ]
    if (
        len(requested_product_ids) != 3
        or requested_product_ids != task_product_ids
        or requested_product_ids != job_product_ids
    ):
        _scope_rejected(
            'ORDERED_PRODUCTS_DRIFT',
            'Prepare 商品顺序必须与冻结 task/jobs 完全一致且精确三件。',
        )
    if purpose == 'formal' and requested_product_ids != list(
        discovery_receipt.get('ordered_product_ids') or []
    ):
        _scope_rejected(
            'DISCOVERY_FORMAL_PRODUCT_ORDER_DRIFT',
            'Formal 商品顺序必须与 sealed Discovery 完全一致。',
        )

    ordered_products: list[dict[str, Any]] = []
    for ordinal, product in enumerate(payload.orderedProducts, start=1):
        field_bindings: list[dict[str, Any]] = []
        seen_fields: set[str] = set()
        stage_counts = {'SAVE1': 0, 'SAVE2': 0}
        for binding in product.fieldHashBindings:
            field_name = binding.field
            if field_name != field_name.strip() or field_name in seen_fields:
                _scope_rejected(
                    'FIELD_HASH_BINDING_INVALID',
                    '字段授权必须规范化且不得跨 SAVE 阶段重复。',
                )
            seen_fields.add(field_name)
            if any(token in field_name.casefold() for token in ('publish', '发布')):
                _scope_rejected('PUBLISH_FIELD_FORBIDDEN', '字段授权不得包含发布入口。')
            stage_counts[binding.saveStage] += 1
            field_bindings.append({
                'field': field_name,
                'saveStage': binding.saveStage,
                'preimageSha256': binding.preimageSha256,
                'expectedSha256': binding.expectedSha256,
            })
        if any(count < 1 for count in stage_counts.values()):
            _scope_rejected(
                'SAVE_ALLOWED_FIELDS_REQUIRED',
                '每件商品的 SAVE1 与 SAVE2 都必须有显式字段哈希授权。',
            )
        ordered_products.append({
            'ordinal': ordinal,
            'productId': product.productId,
            'allowedFields': field_bindings,
            'saves': [
                {'stage': 'SAVE1', 'maxPhysicalRequests': 1},
                {'stage': 'SAVE2', 'maxPhysicalRequests': 1},
            ],
        })

    provisional_scope = {'orderedProducts': ordered_products}
    _validate_scope_field_hashes_against_frozen_task(task, provisional_scope)
    session = frozen.get('session_context') if isinstance(frozen.get('session_context'), Mapping) else {}
    try:
        shop_id = int(frozen.get('shop_scope'))
    except (TypeError, ValueError):
        _scope_rejected('SHOP_BINDING_INVALID', '冻结店铺 ID 无效。')
    shop_name = str(session.get('shop_name') or '')
    if not shop_name:
        _scope_rejected('SHOP_BINDING_INVALID', '冻结店铺名称缺失。')

    git_summary = _current_git_summary()
    worktree_identity = _current_execution_worktree_identity(git_summary)
    if git_summary.get('is_dirty') is not False:
        _scope_rejected(
            'WORKTREE_DIRTY',
            '真实 scope Prepare 只接受当前 clean worktree；未触发任何真实写入。',
        )
    _assert_real_scope_data_dir_external()
    adapter_browser_session_id = str(workflow_adapter.browser_session_id() or '')
    try:
        runtime_browser_session_id = _current_browser_session_id()
    except HTTPException:
        _scope_rejected('BROWSER_SESSION_UNAVAILABLE', 'BrowserAgent 当前会话不可用。')
    if (
        not adapter_browser_session_id
        or adapter_browser_session_id != runtime_browser_session_id
    ):
        _scope_rejected(
            'BROWSER_SESSION_IDENTITY_DRIFT',
            'workflow adapter 与 BrowserAgent 会话身份不一致。',
        )
    try:
        account_context_hash = workflow_adapter.refresh_account_context_hash()
    except Exception:
        _scope_rejected('ACCOUNT_CONTEXT_UNAVAILABLE', '无法重读当前账号身份。')
    if str(session.get('account_ref_hash') or '') != account_context_hash:
        _scope_rejected('ACCOUNT_CONTEXT_DRIFT', '当前账号与冻结 Reader 账号不一致。')
    l2_gate = l2_real_probe_gate()
    if l2_gate.get('status') != 'passed':
        _scope_rejected('L2_NOT_PASSED', 'Prepare 需要 fresh passed L2。')

    def persist_derived_scope(scope_value: Mapping[str, Any]) -> dict[str, Any]:
        lineage_sha256 = None
        if purpose == 'formal':
            _assert_formal_scope_continues_discovery(
                scope_value,
                discovery_receipt,
                predecessor_scope_sha256=str(predecessor_scope_sha256),
            )
            lineage_sha256 = real_scope_sha256({
                'schemaVersion': 'real_dxm_path_b_formal_lineage.v1',
                'predecessorScopeSha256': predecessor_scope_sha256,
                'discoveryReceiptSha256': discovery_receipt_sha256,
                'formalScopeSha256': scope_value.get('scopeSha256'),
                'formalTaskId': scope_value.get('snapshot', {}).get('taskId'),
                'formalSnapshotId': scope_value.get('snapshot', {}).get('snapshotId'),
                'formalSnapshotSha256': scope_value.get('snapshot', {}).get(
                    'snapshotSha256'
                ),
            })
        return repo.prepare_real_dxm_write_scope(
            scope_value,
            purpose=purpose,
            lineage_sha256=lineage_sha256,
            lineage_discovery_receipt_sha256=discovery_receipt_sha256,
            lineage_predecessor_scope_sha256=predecessor_scope_sha256,
        )

    existing = repo.get_prepared_real_dxm_write_scope_for_task(payload.taskId)
    if isinstance(existing, Mapping) and isinstance(existing.get('scope'), Mapping):
        existing_scope = existing['scope']
        try:
            validated_existing = validate_real_dxm_write_scope(existing_scope)
        except RealDxmWriteScopeError as exc:
            if exc.detail_code != 'SCOPE_EXPIRED':
                _scope_rejected(exc.detail_code, '现有 prepared scope 已损坏。')
        else:
            if (
                not str(validated_existing.get('nonce') or '').startswith(nonce_prefix)
                or validated_existing.get('orderedProducts') != ordered_products
            ):
                _scope_rejected(
                    'TASK_ACTIVE_SCOPE_CONFLICT',
                    '同一 task 已有另一份仍有效的 prepared scope。',
                )
            if (
                existing.get('purpose') != purpose
                or _acceptance_digest(
                    existing.get('lineage_discovery_receipt_sha256')
                )
                != _acceptance_digest(discovery_receipt_sha256)
                or _acceptance_digest(
                    existing.get('lineage_predecessor_scope_sha256')
                )
                != _acceptance_digest(predecessor_scope_sha256)
            ):
                _scope_rejected(
                    'TASK_ACTIVE_SCOPE_CONFLICT',
                    '同一 task 已有不同用途或谱系的 prepared scope。',
                )
            _validate_real_scope_task_binding(task, validated_existing)
            rechecked = persist_derived_scope(validated_existing)
            if rechecked.get('ok') is not True:
                _scope_rejected(
                    str(rechecked.get('detail_code') or 'SCOPE_PERSISTENCE_REJECTED'),
                    '现有 prepared scope 已不再绑定 draft task。',
                )
            return _real_path_b_scope_prepare_result(
                validated_existing,
                prepare_request_sha256=prepare_request_sha256,
                reused=True,
                purpose=purpose,
                predecessor_scope_sha256=predecessor_scope_sha256,
                discovery_receipt_sha256=discovery_receipt_sha256,
            )

    issued_at = _authorization_now()
    try:
        candidate = prepare_real_dxm_write_scope({
            'schema': 'real_dxm_write_scope.v1',
            'stage': 'execute',
            'path': 'B',
            'issuedAt': issued_at,
            'expiresAt': issued_at + timedelta(seconds=payload.validForSeconds),
            'nonce': nonce_prefix + secrets.token_hex(12),
            'account': {'accountContextHash': account_context_hash},
            'shop': {'shopId': shop_id, 'shopName': shop_name},
            'snapshot': {
                'snapshotId': int((task.get('payload') or {}).get('plan_snapshot_id') or 0),
                'snapshotSha256': str((task.get('payload') or {}).get('plan_snapshot_hash') or ''),
                'taskId': payload.taskId,
            },
            'git': {'head': str(git_summary.get('head') or '')},
            'worktree': worktree_identity,
            'runtime': {
                'runtimeInstanceId': str(runtime_identity.instance_id),
                'browserRuntimeId': str(browser_agent_runtime.runtime_id),
                'browserSessionId': runtime_browser_session_id,
            },
            'l2': {
                'status': 'passed',
                'evidenceFingerprint': _l2_authorization_fingerprint(l2_gate),
            },
            'orderedProducts': ordered_products,
            'publishAllowed': False,
            'maxPhysicalRequestsPerSave': 1,
        }, now=issued_at)
    except RealDxmWriteScopeError as exc:
        _scope_rejected(exc.detail_code, '当前事实无法形成严格的真实写 scope。')
    _validate_real_scope_task_binding(task, candidate)
    persisted = persist_derived_scope(candidate)
    if persisted.get('ok') is not True:
        if persisted.get('detail_code') == 'TASK_ACTIVE_SCOPE_CONFLICT':
            raced = repo.get_prepared_real_dxm_write_scope_for_task(payload.taskId)
            raced_scope = raced.get('scope') if isinstance(raced, Mapping) else None
            if (
                isinstance(raced_scope, Mapping)
                and str(raced_scope.get('nonce') or '').startswith(nonce_prefix)
                and raced_scope.get('orderedProducts') == ordered_products
            ):
                try:
                    validated_raced = validate_real_dxm_write_scope(raced_scope)
                except RealDxmWriteScopeError as exc:
                    _scope_rejected(exc.detail_code, '并发 prepared scope 已无效。')
                _validate_real_scope_task_binding(task, validated_raced)
                if (
                    raced.get('purpose') != purpose
                    or _acceptance_digest(
                        raced.get('lineage_discovery_receipt_sha256')
                    )
                    != _acceptance_digest(discovery_receipt_sha256)
                    or _acceptance_digest(
                        raced.get('lineage_predecessor_scope_sha256')
                    )
                    != _acceptance_digest(predecessor_scope_sha256)
                ):
                    _scope_rejected(
                        'TASK_ACTIVE_SCOPE_CONFLICT',
                        '并发 prepared scope 谱系不匹配。',
                    )
                return _real_path_b_scope_prepare_result(
                    validated_raced,
                    prepare_request_sha256=prepare_request_sha256,
                    reused=True,
                    purpose=purpose,
                    predecessor_scope_sha256=predecessor_scope_sha256,
                    discovery_receipt_sha256=discovery_receipt_sha256,
                )
        _scope_rejected(
            str(persisted.get('detail_code') or 'SCOPE_PERSISTENCE_REJECTED'),
            'derived scope 无法形成一次性持久绑定。',
        )
    return _real_path_b_scope_prepare_result(
        candidate,
        prepare_request_sha256=prepare_request_sha256,
        reused=False,
        purpose=purpose,
        predecessor_scope_sha256=predecessor_scope_sha256,
        discovery_receipt_sha256=discovery_receipt_sha256,
    )


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


def _acceptance_sha256(value: Any) -> str:
    return real_scope_sha256(value)


def _acceptance_digest(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if len(normalized) != 64 or any(
        character not in '0123456789ABCDEF' for character in normalized
    ):
        return None
    return normalized


def _acceptance_opaque_ref(label: str, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return hashlib.sha256(
        f"{label}:{value}".encode('utf-8')
    ).hexdigest().upper()


def _acceptance_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _acceptance_discovery_formal_campaign(
    *,
    task_id: int,
    formal_task: Mapping[str, Any],
    task_payload: Mapping[str, Any],
    formal_scope_sha256: str,
    formal_scope_record: Mapping[str, Any] | None,
    formal_scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate the sealed Discovery -> fresh Formal boundary for export.

    Only opaque identities, hashes, and counters leave this helper.  Missing or
    inconsistent private evidence produces false gates instead of optimistic
    defaults, so the public acceptance route remains fail-closed.
    """

    empty = {
        'lineageConsistent': False,
        'discoveryReceiptValid': False,
        'continuationValid': False,
        'chronologyValid': False,
        'discoveryCountersValid': False,
        'formalLineageSha256': None,
        'predecessorScopeSha256': None,
        'discoveryReceiptSha256': None,
        '_proofHashes': [],
        '_commandId': None,
        '_leaseId': None,
        'chronology': {
            'discoverySealedAt': None,
            'formalSnapshotCreatedAt': None,
            'formalTaskCreatedAt': None,
            'formalScopeIssuedAt': None,
            'formalScopePreparedAt': None,
            'formalApprovalApprovedAt': None,
        },
        'discovery': {
            'taskId': None,
            'snapshotId': None,
            'snapshotSha256': None,
            'scopeSha256': None,
            'productId': None,
            'receiptSha256': None,
            'proofSetSha256': None,
            'counters': {
                'physicalMutation': None,
                'save1': None,
                'save2': None,
                'otherProductMutation': None,
                'publishRequest': None,
                'unknown': None,
            },
        },
    }
    raw_lineage = task_payload.get(PATH_B_FORMAL_LINEAGE_KEY)
    try:
        lineage = validate_path_b_formal_lineage(raw_lineage)
    except (BatchCommandContractError, TypeError, ValueError):
        return empty

    discovery_receipt_sha256 = lineage['discovery_receipt_sha256']
    discovery_reader = getattr(
        repo, 'get_real_dxm_path_b_discovery_by_receipt_sha256', None
    )
    if not callable(discovery_reader):
        return {
            **empty,
            'formalLineageSha256': lineage['lineage_sha256'],
            'predecessorScopeSha256': lineage['predecessor_scope_sha256'],
            'discoveryReceiptSha256': discovery_receipt_sha256,
        }
    discovery_record = discovery_reader(discovery_receipt_sha256)
    receipt = (
        discovery_record.get('receipt')
        if isinstance(discovery_record, Mapping)
        and isinstance(discovery_record.get('receipt'), Mapping)
        else None
    )
    predecessor = repo.get_real_dxm_write_scope(
        lineage['predecessor_scope_sha256']
    )
    if not isinstance(receipt, Mapping) or not isinstance(predecessor, Mapping):
        return {
            **empty,
            'formalLineageSha256': lineage['lineage_sha256'],
            'predecessorScopeSha256': lineage['predecessor_scope_sha256'],
            'discoveryReceiptSha256': discovery_receipt_sha256,
        }

    receipt_sha256 = _acceptance_digest(
        receipt.get('discovery_receipt_sha256')
    )
    unsigned_receipt = {
        key: value
        for key, value in receipt.items()
        if key != 'discovery_receipt_sha256'
    }
    field_readbacks = (
        receipt.get('field_readbacks')
        if isinstance(receipt.get('field_readbacks'), list)
        else []
    )
    unpublished_readback = (
        receipt.get('unpublished_readback')
        if isinstance(receipt.get('unpublished_readback'), Mapping)
        else None
    )
    leaf_proof_manifest = (
        receipt.get('leaf_proof_manifest')
        if isinstance(receipt.get('leaf_proof_manifest'), Mapping)
        else None
    )
    leaf_proof_keys = (
        'network_request_sha256',
        'network_response_sha256',
        'screenshot_sha256',
        'readback_sha256',
        'unpublished_readback_sha256',
    )
    proof_hashes = [
        _acceptance_digest(leaf_proof_manifest.get(key))
        if isinstance(leaf_proof_manifest, Mapping)
        else None
        for key in leaf_proof_keys
    ]
    receipt_valid = bool(
        isinstance(discovery_record, Mapping)
        and discovery_record.get('ok') is True
        and discovery_record.get('status') == 'DISCOVERY_SEALED'
        and receipt.get('schema_version')
        == 'dxm.real-dxm-path-b.save1-discovery-receipt.v1'
        and receipt_sha256 == discovery_receipt_sha256
        and receipt_sha256 == _acceptance_sha256(unsigned_receipt)
        and _acceptance_digest(receipt.get('field_readbacks_sha256'))
        == _acceptance_sha256(field_readbacks)
        and isinstance(unpublished_readback, Mapping)
        and _acceptance_digest(receipt.get('unpublished_readback_sha256'))
        == _acceptance_sha256(unpublished_readback)
        and isinstance(leaf_proof_manifest, Mapping)
        and leaf_proof_manifest.get('schema_version')
        == 'dxm.real-dxm-path-b.discovery-leaf-proof-manifest.v1'
        and _acceptance_digest(
            receipt.get('leaf_proof_manifest_sha256')
        )
        == _acceptance_sha256(leaf_proof_manifest)
        and len(field_readbacks) > 0
        and all(value is not None for value in proof_hashes)
        and len(set(proof_hashes)) == len(proof_hashes)
    )

    first_products = [
        item
        for item in formal_scope.get('orderedProducts', [])
        if isinstance(item, Mapping) and item.get('ordinal') == 1
    ]
    formal_save1 = (
        {
            item.get('field'): item.get('preimageSha256')
            for item in first_products[0].get('allowedFields', [])
            if isinstance(item, Mapping) and item.get('saveStage') == 'SAVE1'
        }
        if len(first_products) == 1
        else {}
    )
    discovery_after: dict[str, str] = {}
    readbacks_valid = bool(field_readbacks)
    for item in field_readbacks:
        if (
            not isinstance(item, Mapping)
            or item.get('readback_proven') is not True
            or not isinstance(item.get('field_key'), str)
            or not str(item.get('field_key') or '').strip()
        ):
            readbacks_valid = False
            continue
        field_key = str(item['field_key'])
        if field_key in discovery_after:
            readbacks_valid = False
            continue
        discovery_after[field_key] = _acceptance_sha256(item.get('after_value'))
    continuation_valid = bool(
        readbacks_valid
        and formal_save1
        and discovery_after == formal_save1
    )

    discovery_counters = {
        'physicalMutation': receipt.get('physical_mutation_count'),
        'save1': receipt.get('save1_count'),
        'save2': receipt.get('save2_count'),
        'otherProductMutation': receipt.get('other_product_mutation_count'),
        'publishRequest': receipt.get('publish_request_count'),
        'unknown': receipt.get('unknown_count'),
    }
    discovery_counters_valid = discovery_counters == {
        'physicalMutation': 1,
        'save1': 1,
        'save2': 0,
        'otherProductMutation': 0,
        'publishRequest': 0,
        'unknown': 0,
    } and receipt.get('published') is False

    formal_snapshot_id = int(task_payload.get('plan_snapshot_id') or 0)
    formal_snapshot_sha256 = str(
        task_payload.get('plan_snapshot_hash') or ''
    ).upper()
    try:
        formal_snapshot_row = PlanSnapshotStore.get(formal_snapshot_id)
    except Exception:
        formal_snapshot_row = None
    manual_approval = (
        task_payload.get('manual_approval')
        if isinstance(task_payload.get('manual_approval'), Mapping)
        else {}
    )
    chronology = {
        'discoverySealedAt': receipt.get('sealed_at'),
        'formalSnapshotCreatedAt': (
            formal_snapshot_row.get('created_at')
            if isinstance(formal_snapshot_row, Mapping)
            else None
        ),
        'formalTaskCreatedAt': formal_task.get('created_at'),
        'formalScopeIssuedAt': formal_scope.get('issuedAt'),
        'formalScopePreparedAt': (
            formal_scope_record.get('prepared_at')
            if isinstance(formal_scope_record, Mapping)
            else None
        ),
        'formalApprovalApprovedAt': manual_approval.get('approved_at'),
    }
    chronology_times = {
        key: _acceptance_timestamp(value) for key, value in chronology.items()
    }
    discovery_sealed_at = chronology_times['discoverySealedAt']
    formal_snapshot_created_at = chronology_times['formalSnapshotCreatedAt']
    formal_task_created_at = chronology_times['formalTaskCreatedAt']
    formal_scope_issued_at = chronology_times['formalScopeIssuedAt']
    formal_scope_prepared_at = chronology_times['formalScopePreparedAt']
    formal_approval_approved_at = chronology_times['formalApprovalApprovedAt']
    chronology_valid = bool(
        isinstance(formal_snapshot_row, Mapping)
        and int(formal_snapshot_row.get('id') or 0) == formal_snapshot_id
        and int(formal_snapshot_row.get('task_id') or 0) == task_id
        and _acceptance_digest(formal_snapshot_row.get('snapshot_hash'))
        == _acceptance_digest(formal_snapshot_sha256)
        and all(value is not None for value in chronology_times.values())
        and all(
            value > discovery_sealed_at
            for key, value in chronology_times.items()
            if key != 'discoverySealedAt'
        )
        and formal_snapshot_created_at <= formal_task_created_at
        and formal_task_created_at
        <= min(formal_scope_issued_at, formal_scope_prepared_at)
        and not (
            formal_scope_prepared_at < formal_scope_issued_at
            and formal_scope_issued_at - formal_scope_prepared_at
            >= timedelta(seconds=1)
        )
        and max(formal_scope_issued_at, formal_scope_prepared_at)
        <= formal_approval_approved_at
        and formal_approval_approved_at <= datetime.now(timezone.utc)
    )
    receipt_order = (
        list(receipt.get('ordered_product_ids'))
        if isinstance(receipt.get('ordered_product_ids'), list)
        else []
    )
    formal_order = [
        item.get('productId')
        for item in formal_scope.get('orderedProducts', [])
        if isinstance(item, Mapping)
    ]
    formal_account = (
        formal_scope.get('account')
        if isinstance(formal_scope.get('account'), Mapping)
        else {}
    )
    formal_shop = (
        formal_scope.get('shop')
        if isinstance(formal_scope.get('shop'), Mapping)
        else {}
    )
    formal_git = (
        formal_scope.get('git')
        if isinstance(formal_scope.get('git'), Mapping)
        else {}
    )
    identity_consistent = bool(
        formal_account.get('accountContextHash') == receipt.get('account_ref_hash')
        and formal_shop.get('shopId') == receipt.get('shop_id')
        and formal_shop.get('shopName') == receipt.get('shop_name')
        and formal_git.get('head') == receipt.get('git_head')
        and formal_scope.get('worktree') == receipt.get('worktree')
        and formal_scope.get('runtime') == receipt.get('runtime')
        and formal_order == receipt_order
        and len(formal_order) == 3
    )
    registry_consistent = bool(
        isinstance(formal_scope_record, Mapping)
        and formal_scope_record.get('status') == 'consumed'
        and formal_scope_record.get('purpose') == 'formal'
        and _acceptance_digest(formal_scope_record.get('scope_sha256'))
        == _acceptance_digest(formal_scope_sha256)
        and _acceptance_digest(formal_scope_record.get('lineage_sha256'))
        == lineage['lineage_sha256']
        and _acceptance_digest(
            formal_scope_record.get('lineage_discovery_receipt_sha256')
        )
        == discovery_receipt_sha256
        and _acceptance_digest(
            formal_scope_record.get('lineage_predecessor_scope_sha256')
        )
        == lineage['predecessor_scope_sha256']
        and predecessor.get('status') == 'discovery_sealed'
        and predecessor.get('purpose') == 'discovery'
        and _acceptance_digest(predecessor.get('scope_sha256'))
        == lineage['predecessor_scope_sha256']
        and _acceptance_digest(predecessor.get('approval_sha256'))
        == _acceptance_digest(receipt.get('approval_sha256'))
        and _acceptance_digest(formal_scope_record.get('approval_sha256'))
        is not None
        and _acceptance_digest(formal_scope_record.get('approval_sha256'))
        != _acceptance_digest(receipt.get('approval_sha256'))
    )
    freshness_consistent = bool(
        lineage['formal_task_id'] == task_id
        and lineage['formal_snapshot_id'] == formal_snapshot_id
        and lineage['formal_snapshot_sha256'] == formal_snapshot_sha256
        and lineage['formal_scope_sha256']
        == _acceptance_digest(formal_scope_sha256)
        and lineage['discovery_task_id'] == receipt.get('task_id')
        and lineage['discovery_snapshot_id'] == receipt.get('snapshot_id')
        and lineage['discovery_snapshot_sha256']
        == _acceptance_digest(receipt.get('snapshot_sha256'))
        and lineage['predecessor_scope_sha256']
        == _acceptance_digest(receipt.get('scope_sha256'))
        and lineage['discovery_receipt_sha256'] == receipt_sha256
    )
    lineage_consistent = bool(
        receipt_valid
        and continuation_valid
        and chronology_valid
        and discovery_counters_valid
        and identity_consistent
        and registry_consistent
        and freshness_consistent
    )
    return {
        'lineageConsistent': lineage_consistent,
        'discoveryReceiptValid': receipt_valid,
        'continuationValid': continuation_valid,
        'chronologyValid': chronology_valid,
        'discoveryCountersValid': discovery_counters_valid,
        'formalLineageSha256': lineage['lineage_sha256'],
        'predecessorScopeSha256': lineage['predecessor_scope_sha256'],
        'discoveryReceiptSha256': discovery_receipt_sha256,
        '_proofHashes': proof_hashes if receipt_valid else [],
        '_commandId': receipt.get('command_id'),
        '_leaseId': receipt.get('authorization_lease_id'),
        'chronology': chronology,
        'discovery': {
            'taskId': receipt.get('task_id'),
            'snapshotId': receipt.get('snapshot_id'),
            'snapshotSha256': _acceptance_digest(
                receipt.get('snapshot_sha256')
            ),
            'scopeSha256': _acceptance_digest(receipt.get('scope_sha256')),
            'productId': receipt.get('product_id'),
            'receiptSha256': receipt_sha256,
            'proofSetSha256': (
                _acceptance_sha256(proof_hashes) if receipt_valid else None
            ),
            'leafProofSha256s': (
                proof_hashes if receipt_valid else []
            ),
            'commandRefSha256': _acceptance_opaque_ref(
                'command', receipt.get('command_id')
            ),
            'leaseRefSha256': _acceptance_opaque_ref(
                'lease', receipt.get('authorization_lease_id')
            ),
            'counters': discovery_counters,
        },
    }


@app.get('/api/tasks/{task_id}/acceptance-export')
def get_real_path_b_acceptance_export(task_id: int):
    """Return a redacted, public-API-only Path B acceptance projection."""

    task = repo.get_task_private(task_id)
    if not isinstance(task, Mapping):
        raise HTTPException(status_code=404, detail='Task not found')
    payload = task.get('payload') if isinstance(task.get('payload'), Mapping) else {}
    real_authorization = (
        payload.get('real_dxm_write_authorization')
        if isinstance(payload.get('real_dxm_write_authorization'), Mapping)
        else {}
    )
    scope_sha256 = str(real_authorization.get('scope_sha256') or '')
    scope_record = repo.get_real_dxm_write_scope(scope_sha256) if scope_sha256 else None
    scope = (
        scope_record.get('scope')
        if isinstance(scope_record, Mapping)
        and isinstance(scope_record.get('scope'), Mapping)
        else {}
    )
    campaign_evidence = _acceptance_discovery_formal_campaign(
        task_id=task_id,
        formal_task=task,
        task_payload=payload,
        formal_scope_sha256=scope_sha256,
        formal_scope_record=(
            scope_record if isinstance(scope_record, Mapping) else None
        ),
        formal_scope=scope,
    )
    jobs = [item for item in task.get('jobs') or [] if isinstance(item, Mapping)]
    jobs_by_product = {
        item.get('product_id'): item
        for item in jobs
        if isinstance(item.get('product_id'), int)
        and not isinstance(item.get('product_id'), bool)
    }
    scoped_products = [
        item
        for item in scope.get('orderedProducts', [])
        if isinstance(item, Mapping)
    ]
    ordered_products = []
    for item in scoped_products:
        job = jobs_by_product.get(item.get('productId'))
        ordered_products.append(
            {
                'ordinal': item.get('ordinal'),
                'productId': item.get('productId'),
                'jobId': job.get('id') if isinstance(job, Mapping) else None,
                'status': job.get('status') if isinstance(job, Mapping) else 'missing',
            }
        )

    receipt_rows = repo.list_receipts(task_id)
    save_stage_authority = repo.revalidate_task_save_stage_authority(task_id)
    receipts_by_job: dict[int, Mapping[str, Any]] = {}
    persisted_save_receipts: dict[tuple[int, str], Mapping[str, Any]] = {}
    receipt_row_issues: list[str] = []
    expected_product_by_job = {
        int(item['id']): item.get('product_id')
        for item in jobs
        if isinstance(item.get('id'), int) and not isinstance(item.get('id'), bool)
    }
    for row in receipt_rows:
        canonical = row.get('receipt') if isinstance(row.get('receipt'), Mapping) else None
        job_id = row.get('job_id')
        if (
            not isinstance(job_id, int)
            or isinstance(job_id, bool)
            or not isinstance(canonical, Mapping)
            or job_id not in expected_product_by_job
        ):
            receipt_row_issues.append('CANONICAL_RECEIPT_ROW_INVALID')
            continue
        receipt_kind = str(row.get('receipt_kind') or 'product_aggregate')
        if receipt_kind == 'save_stage':
            save_stage = str(row.get('save_stage') or '')
            pair = (job_id, save_stage)
            stored_digest = _acceptance_digest(
                canonical.get('canonical_receipt_sha256')
            )
            parent_digest = _acceptance_digest(
                row.get('parent_canonical_receipt_sha256')
            )
            nested = (
                canonical.get('save_receipt')
                if isinstance(canonical.get('save_receipt'), Mapping)
                else None
            )
            nested_digest = (
                _acceptance_digest(
                    nested.get('canonical_save_receipt_sha256')
                )
                if isinstance(nested, Mapping)
                else None
            )
            unsigned_stage = {
                key: value
                for key, value in canonical.items()
                if key not in {'schema_version', 'canonical_receipt_sha256'}
            }
            unsigned_nested = {
                key: value
                for key, value in nested.items()
                if key not in {
                    'schema_version',
                    'canonical_save_receipt_sha256',
                }
            } if isinstance(nested, Mapping) else {}
            expected_phase = {
                'SAVE1': 'phase_1_first_save',
                'SAVE2': 'phase_2_second_save',
            }.get(save_stage)
            if (
                pair in persisted_save_receipts
                or expected_phase is None
                or canonical.get('schema_version')
                != 'dxm.path-b.canonical-save-stage-receipt.v1'
                or canonical.get('receipt_kind') != 'save_stage'
                or canonical.get('task_id') != task_id
                or canonical.get('job_id') != job_id
                or canonical.get('product_id') != expected_product_by_job[job_id]
                or canonical.get('save_stage') != save_stage
                or canonical.get('mode') != 'batch_draft_save'
                or canonical.get('job_status') != 'succeeded'
                or canonical.get('error_code') is not None
                or canonical.get('error_detail') is not None
                or canonical.get('needs_manual_review') is not False
                or _acceptance_digest(canonical.get('scope_sha256')) is None
                or _acceptance_digest(canonical.get('claim_mark'))
                != _acceptance_digest(canonical.get('scope_sha256'))
                or parent_digest is None
                or stored_digest is None
                or stored_digest != _acceptance_sha256(unsigned_stage)
                or _acceptance_digest(row.get('canonical_receipt_sha256'))
                != stored_digest
                or row.get('save_stage') != save_stage
                or _acceptance_digest(row.get('scope_sha256'))
                != _acceptance_digest(canonical.get('scope_sha256'))
                or nested_digest is None
                or nested_digest != _acceptance_sha256(unsigned_nested)
                or nested.get('save_phase') != expected_phase
            ):
                receipt_row_issues.append(
                    'CANONICAL_SAVE_STAGE_RECEIPT_BINDING_INVALID'
                )
                continue
            persisted_save_receipts[pair] = {
                **dict(canonical),
                '_row_parent_canonical_receipt_sha256': parent_digest,
            }
            continue
        if receipt_kind != 'product_aggregate':
            receipt_row_issues.append('CANONICAL_RECEIPT_KIND_INVALID')
            continue
        if job_id in receipts_by_job:
            receipt_row_issues.append('CANONICAL_RECEIPT_DUPLICATE_JOB')
            continue
        stored_digest = _acceptance_digest(canonical.get('canonical_receipt_sha256'))
        unsigned_canonical = {
            key: value
            for key, value in canonical.items()
            if key not in {'schema_version', 'canonical_receipt_sha256'}
        }
        if (
            canonical.get('schema_version') != 'dxm.path-b.canonical-receipt.v1'
            or canonical.get('task_id') != task_id
            or canonical.get('job_id') != job_id
            or canonical.get('product_id') != expected_product_by_job[job_id]
            or canonical.get('mode') != 'batch_draft_save'
            or canonical.get('job_status') != 'succeeded'
            or canonical.get('error_code') is not None
            or canonical.get('needs_manual_review') is not False
            or stored_digest is None
            or stored_digest != _acceptance_sha256(unsigned_canonical)
            or _acceptance_digest(row.get('canonical_receipt_sha256')) != stored_digest
        ):
            receipt_row_issues.append('CANONICAL_RECEIPT_BINDING_INVALID')
            continue
        receipts_by_job[job_id] = canonical

    capability_phase_names = {
        'content_finalize_wholesale': 'wholesale',
        'content_finalize_video': 'video',
        'content_finalize_translation': 'translation',
        'semi_managed_entry': 'semi_managed',
        'rollback_preparation': 'rollback_preparation',
    }
    capability_hashes: dict[str, dict[int, str]] = {
        value: {} for value in capability_phase_names.values()
    }
    capability_issues: list[str] = []
    save_receipts: list[dict[str, Any]] = []
    private_save_receipt_by_lease: dict[str, Mapping[str, Any]] = {}
    for canonical in receipts_by_job.values():
        product_id = canonical.get('product_id')
        job_id = canonical.get('job_id')
        for capability in canonical.get('content_finalize_receipts', []):
            if not isinstance(capability, Mapping):
                continue
            name = capability_phase_names.get(str(capability.get('phase') or ''))
            digest = _acceptance_digest(capability.get('canonical_sha256'))
            if (
                name
                and isinstance(product_id, int)
                and capability.get('result_ok') is True
                and capability.get('unresolved') is False
                and digest is not None
            ):
                if product_id in capability_hashes[name]:
                    capability_issues.append('CAPABILITY_RECEIPT_DUPLICATE_PRODUCT')
                else:
                    capability_hashes[name][product_id] = digest
        aggregate_saves: dict[str, Mapping[str, Any]] = {}
        for aggregate_save in canonical.get('save_receipts', []):
            if not isinstance(aggregate_save, Mapping):
                receipt_row_issues.append('CANONICAL_SAVE_RECEIPT_INVALID')
                continue
            aggregate_stage = {
                'phase_1_first_save': 'SAVE1',
                'phase_2_second_save': 'SAVE2',
            }.get(str(aggregate_save.get('save_phase') or ''))
            if aggregate_stage is None or aggregate_stage in aggregate_saves:
                receipt_row_issues.append('CANONICAL_SAVE_RECEIPT_PHASE_INVALID')
                continue
            aggregate_saves[aggregate_stage] = aggregate_save
        for stage in ('SAVE1', 'SAVE2'):
            persisted = persisted_save_receipts.get((job_id, stage))
            aggregate_save = aggregate_saves.get(stage)
            raw_save = (
                persisted.get('save_receipt')
                if isinstance(persisted, Mapping)
                and isinstance(persisted.get('save_receipt'), Mapping)
                else None
            )
            if (
                not isinstance(persisted, Mapping)
                or not isinstance(raw_save, Mapping)
                or not isinstance(aggregate_save, Mapping)
                or dict(raw_save) != dict(aggregate_save)
                or _acceptance_digest(
                    persisted.get('_row_parent_canonical_receipt_sha256')
                )
                != _acceptance_digest(canonical.get('canonical_receipt_sha256'))
                or _acceptance_digest(persisted.get('scope_sha256'))
                != _acceptance_digest(scope_sha256)
                or _acceptance_digest(
                    persisted.get('canonical_save_receipt_sha256')
                )
                != _acceptance_digest(
                    raw_save.get('canonical_save_receipt_sha256')
                )
            ):
                receipt_row_issues.append(
                    'CANONICAL_SAVE_STAGE_PARENT_BINDING_INVALID'
                )
                continue
            proofs = raw_save.get('proofs') if isinstance(raw_save.get('proofs'), Mapping) else {}
            request = proofs.get('network_request') if isinstance(proofs.get('network_request'), Mapping) else {}
            response = proofs.get('network_response') if isinstance(proofs.get('network_response'), Mapping) else {}
            screenshot = (
                proofs.get('page_success_screenshot')
                if isinstance(proofs.get('page_success_screenshot'), Mapping)
                else proofs.get('screenshot')
                if isinstance(proofs.get('screenshot'), Mapping)
                else {}
            )
            unpublished = proofs.get('unpublished_status') if isinstance(proofs.get('unpublished_status'), Mapping) else {}
            product_scope = next(
                (
                    item
                    for item in scoped_products
                    if item.get('productId') == product_id
                ),
                {},
            )
            governed = {
                item.get('field'): item
                for item in product_scope.get('allowedFields', [])
                if isinstance(item, Mapping) and item.get('saveStage') == stage
            }
            readbacks = [
                item
                for item in raw_save.get('field_readbacks', [])
                if isinstance(item, Mapping)
            ]
            readback_equal = bool(governed) and set(governed) == {
                item.get('field_key') for item in readbacks
            }
            if readback_equal:
                for readback in readbacks:
                    binding = governed.get(readback.get('field_key'), {})
                    if (
                        _acceptance_sha256(readback.get('before_value'))
                        != binding.get('preimageSha256')
                        or _acceptance_sha256(readback.get('after_value'))
                        != binding.get('expectedSha256')
                        or readback.get('readback_proven') is not True
                    ):
                        readback_equal = False
                        break
            save_receipts.append(
                {
                    'productId': product_id,
                    'stage': stage,
                    'canonicalReceiptSha256': _acceptance_digest(
                        persisted.get('canonical_receipt_sha256')
                    ),
                    'canonicalSaveReceiptSha256': _acceptance_digest(
                        persisted.get('canonical_save_receipt_sha256')
                    ),
                    'parentCanonicalReceiptSha256': _acceptance_digest(
                        persisted.get(
                            '_row_parent_canonical_receipt_sha256'
                        )
                    ),
                    'persisted': True,
                    'commandId': raw_save.get('action_grant_id'),
                    'leaseId': raw_save.get('save_lease_id'),
                    'mutationCount': raw_save.get('physical_mutation_count'),
                    'publishCount': raw_save.get('publish_request_count'),
                    'networkRequestSha256': _acceptance_digest(request.get('body_sha256')),
                    'networkResponseSha256': _acceptance_digest(response.get('body_sha256')),
                    'businessSuccess': response.get('business_success') is True
                    and str(response.get('business_code')) == '0',
                    'screenshotSha256': _acceptance_digest(screenshot.get('body_sha256')),
                    'readbackSha256': _acceptance_sha256(readbacks),
                    'unpublishedReadbackSha256': _acceptance_digest(unpublished.get('body_sha256')),
                    'readbackEqual': readback_equal,
                    'unpublished': unpublished.get('unpublished') is True
                    and unpublished.get('independent') is True,
                    'published': (
                        raw_save.get('published')
                        if isinstance(raw_save.get('published'), bool)
                        else None
                    ),
                }
            )
            raw_lease_id = raw_save.get('save_lease_id')
            if isinstance(raw_lease_id, str) and raw_lease_id.strip():
                private_save_receipt_by_lease[raw_lease_id] = raw_save

    ledger_rows = repo.list_task_mutation_ledger(task_id)
    product_by_job = {
        str(item.get('id')): item.get('product_id') for item in jobs
    }
    receipt_by_lease = {
        str(item.get('leaseId') or ''): item for item in save_receipts
    }
    mutation_ledger = []
    for row in ledger_rows:
        lease_id = str(row.get('authorization_lease_id') or '')
        save_receipt = receipt_by_lease.get(lease_id, {})
        private_save_receipt = private_save_receipt_by_lease.get(lease_id, {})
        try:
            command_json = json.loads(str(row.get('command_json') or ''))
            save_result_json = json.loads(
                str(row.get('save_action_result_json') or '')
            )
            save_authority_json = json.loads(
                str(row.get('save_authority_json') or '')
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            command_json = None
            save_result_json = None
            save_authority_json = None
        expected_state = {
            'SAVE1': 'SAVE_ONLY',
            'SAVE2': 'SAVE2_ONLY',
        }.get(save_receipt.get('stage'))
        save_observations = (
            save_result_json.get('evidence', {}).get('observations', {})
            if isinstance(save_result_json, Mapping)
            and isinstance(save_result_json.get('evidence'), Mapping)
            else {}
        )
        save_network = (
            save_observations.get('network_save_result')
            if isinstance(save_observations.get('network_save_result'), Mapping)
            else {}
        )
        save_refs = (
            save_result_json.get('evidence', {}).get('refs', [])
            if isinstance(save_result_json, Mapping)
            and isinstance(save_result_json.get('evidence'), Mapping)
            else []
        )
        private_proofs = (
            private_save_receipt.get('proofs')
            if isinstance(private_save_receipt.get('proofs'), Mapping)
            else {}
        )
        request_proof = (
            private_proofs.get('network_request')
            if isinstance(private_proofs.get('network_request'), Mapping)
            else {}
        )
        response_proof = (
            private_proofs.get('network_response')
            if isinstance(private_proofs.get('network_response'), Mapping)
            else {}
        )
        screenshot_proof = (
            private_proofs.get('page_success_screenshot')
            if isinstance(
                private_proofs.get('page_success_screenshot'), Mapping
            )
            else private_proofs.get('screenshot')
            if isinstance(private_proofs.get('screenshot'), Mapping)
            else {}
        )
        authority_task = (
            save_authority_json.get('task_authority')
            if isinstance(save_authority_json, Mapping)
            and isinstance(save_authority_json.get('task_authority'), Mapping)
            else {}
        )
        authority_authorization = (
            save_authority_json.get('authorization')
            if isinstance(save_authority_json, Mapping)
            and isinstance(save_authority_json.get('authorization'), Mapping)
            else {}
        )
        authority_target = (
            save_authority_json.get('target')
            if isinstance(save_authority_json, Mapping)
            and isinstance(save_authority_json.get('target'), Mapping)
            else {}
        )
        authority_command = (
            save_authority_json.get('command')
            if isinstance(save_authority_json, Mapping)
            and isinstance(save_authority_json.get('command'), Mapping)
            else {}
        )
        ledger_evidence_bound = bool(
            isinstance(command_json, Mapping)
            and isinstance(save_result_json, Mapping)
            and isinstance(save_authority_json, Mapping)
            and _acceptance_digest(row.get('command_sha256'))
            == _acceptance_sha256(command_json)
            and _acceptance_digest(row.get('save_action_result_sha256'))
            == _acceptance_sha256(save_result_json)
            and _acceptance_digest(row.get('save_authority_sha256'))
            == _acceptance_sha256(save_authority_json)
            and str(command_json.get('task_id')) == str(task_id)
            and str(command_json.get('job_id')) == str(row.get('job_id'))
            and command_json.get('state') == expected_state
            and command_json.get('action') == 'save_only'
            and command_json.get('command_id') == row.get('command_id')
            and command_json.get('authorization_lease_id') == lease_id
            and _acceptance_digest(command_json.get('target_hash'))
            == _acceptance_digest(private_save_receipt.get('target_hash'))
            and private_save_receipt.get('mutation_id')
            == row.get('mutation_id')
            and private_save_receipt.get('ledger_entry_id') == row.get('id')
            and save_authority_json.get('schema')
            == 'dxm.batch_draft_save.dispatch_authority.v1'
            and authority_task.get('task_id') == task_id
            and authority_authorization.get('lease_id') == lease_id
            and _acceptance_digest(authority_target.get('target_hash'))
            == _acceptance_digest(private_save_receipt.get('target_hash'))
            and authority_command.get('payload') == command_json
            and _acceptance_digest(authority_command.get('sha256'))
            == _acceptance_digest(row.get('command_sha256'))
            and _acceptance_digest(save_network.get('request_body_sha256'))
            == _acceptance_digest(request_proof.get('body_sha256'))
            and _acceptance_digest(save_network.get('response_body_sha256'))
            == _acceptance_digest(response_proof.get('body_sha256'))
            and len(save_refs) == 1
            and isinstance(save_refs[0], Mapping)
            and _acceptance_digest(save_refs[0].get('sha256'))
            == _acceptance_digest(screenshot_proof.get('body_sha256'))
            and save_observations.get('save_field_readbacks')
            == private_save_receipt.get('field_readbacks')
        )
        success_evidence_complete = bool(
            row.get('status') == 'DISPATCHED'
            and ledger_evidence_bound
            and isinstance(row.get('dispatched_at'), str)
            and str(row.get('dispatched_at')).strip()
            and isinstance(row.get('save_success_recorded_at'), str)
            and str(row.get('save_success_recorded_at')).strip()
            and save_receipt.get('mutationCount') == 1
            and save_receipt.get('publishCount') == 0
            and save_receipt.get('businessSuccess') is True
            and save_receipt.get('readbackEqual') is True
            and save_receipt.get('unpublished') is True
            and save_receipt.get('published') is False
        )
        mutation_ledger.append(
            {
                'productId': product_by_job.get(str(row.get('job_id'))),
                'stage': {
                    'SAVE_ONLY': 'SAVE1',
                    'SAVE2_ONLY': 'SAVE2',
                }.get(str(row.get('command_state') or ''), 'UNKNOWN'),
                'commandId': row.get('command_id'),
                'leaseId': lease_id,
                'physicalMutationCount': (
                    1 if row.get('status') == 'DISPATCHED' else 0
                ),
                'publishCount': save_receipt.get('publishCount'),
                'status': 'succeeded' if success_evidence_complete else 'blocked',
            }
        )

    fence_rows = repo.list_task_writer_fences(task_id)
    fence_conflicts = sum(1 for item in fence_rows if item.get('status') == 'conflict')
    fence_released = len(fence_rows) == 1 and fence_rows[0].get('status') == 'released'
    unknown_count = int(
        task.get('status') in {'unknown', 'needs_manual_review'}
        or str(task.get('error_code') or '').upper() == 'UNKNOWN'
        or task.get('needs_manual_review') is True
    ) + sum(
        1
        for item in jobs
        if item.get('status') in {'unknown', 'needs_manual_review'}
        or str(item.get('error_code') or '').upper() == 'UNKNOWN'
        or item.get('needs_manual_review') is True
    )
    ledger_groups: dict[tuple[Any, Any], int] = {}
    for item in mutation_ledger:
        key = (item.get('productId'), item.get('stage'))
        ledger_groups[key] = ledger_groups.get(key, 0) + 1
    auto_retry_count = sum(max(0, count - 1) for count in ledger_groups.values())
    authorized_save_leases = [
        item
        for item in real_authorization.get('save_leases', [])
        if isinstance(item, Mapping)
    ]
    authorized_lease_ids = {
        item.get('lease_id') for item in authorized_save_leases
    }
    authorized_lease_pairs = {
        (item.get('product_id'), item.get('save_stage'))
        for item in authorized_save_leases
    }
    authorized_lease_targets = {
        (
            item.get('product_id'),
            item.get('product_ordinal'),
            item.get('save_stage'),
        )
        for item in authorized_save_leases
    }
    lineage_consistent = bool(
        scope
        and save_stage_authority.get('ok') is True
        and isinstance(scope_record, Mapping)
        and scope_record.get('status') == 'consumed'
        and scope.get('scopeSha256') == scope_sha256
        and real_authorization.get('ordered_product_ids')
        == [item.get('productId') for item in scoped_products]
        and len(authorized_save_leases) == 6
        and len(authorized_lease_ids) == 6
        and all(
            _acceptance_digest(item.get('lease_id')) is not None
            and _acceptance_digest(item.get('scope_sha256'))
            == _acceptance_digest(scope_sha256)
            and item.get('single_use') is True
            for item in authorized_save_leases
        )
        and {item.get('leaseId') for item in save_receipts}
        == {item.get('leaseId') for item in mutation_ledger}
        == authorized_lease_ids
    )
    scoped_product_ids = [item.get('productId') for item in scoped_products]
    capabilities: dict[str, dict[str, Any]] = {}
    for name, hashes_by_product in capability_hashes.items():
        ordered_hashes = [
            hashes_by_product.get(product_id) for product_id in scoped_product_ids
        ]
        passed = bool(
            len(scoped_product_ids) == 3
            and set(hashes_by_product) == set(scoped_product_ids)
            and all(_acceptance_digest(value) is not None for value in ordered_hashes)
            and len(set(ordered_hashes)) == 3
        )
        capabilities[name] = {
            'status': 'passed' if passed else 'missing',
            'evidenceSha256': (
                _acceptance_sha256(ordered_hashes) if passed else None
            ),
        }

    expected_save_pairs = {
        (product_id, stage)
        for product_id in scoped_product_ids
        for stage in {'SAVE1', 'SAVE2'}
    }
    lineage_consistent = lineage_consistent and (
        authorized_lease_pairs == expected_save_pairs
        and authorized_lease_targets
        == {
            (product_id, ordinal, stage)
            for ordinal, product_id in enumerate(scoped_product_ids, start=1)
            for stage in {'SAVE1', 'SAVE2'}
        }
    )
    save_pairs = [
        (item.get('productId'), item.get('stage')) for item in save_receipts
    ]
    ledger_pairs = [
        (item.get('productId'), item.get('stage')) for item in mutation_ledger
    ]
    save_command_ids = [item.get('commandId') for item in save_receipts]
    save_lease_ids = [item.get('leaseId') for item in save_receipts]
    save_stage_receipt_hashes = [
        item.get('canonicalReceiptSha256') for item in save_receipts
    ]
    nested_save_receipt_hashes = [
        item.get('canonicalSaveReceiptSha256') for item in save_receipts
    ]
    save_proof_hashes = [
        item.get(key)
        for item in save_receipts
        for key in (
            'networkRequestSha256',
            'networkResponseSha256',
            'screenshotSha256',
            'readbackSha256',
            'unpublishedReadbackSha256',
        )
    ]
    ledger_by_pair = {
        (item.get('productId'), item.get('stage')): item
        for item in mutation_ledger
    }
    receipt_ledger_bound = all(
        ledger_by_pair.get((item.get('productId'), item.get('stage')), {}).get('commandId')
        == item.get('commandId')
        and ledger_by_pair.get((item.get('productId'), item.get('stage')), {}).get('leaseId')
        == item.get('leaseId')
        for item in save_receipts
    )
    publish_request_count = sum(
        int(item.get('publishCount') or 0) for item in save_receipts
    )
    published_state = (
        True
        if any(item.get('published') is True for item in save_receipts)
        else False
        if len(save_receipts) == 6
        and publish_request_count == 0
        and all(
            item.get('published') is False
            and item.get('unpublished') is True
            for item in save_receipts
        )
        else None
    )
    formal_counters = {
        'physicalMutation': sum(
            int(item.get('mutationCount') or 0) for item in save_receipts
        ),
        'save1': sum(1 for item in save_receipts if item.get('stage') == 'SAVE1'),
        'save2': sum(1 for item in save_receipts if item.get('stage') == 'SAVE2'),
        'publishRequest': publish_request_count,
        'unknown': unknown_count,
        'autoRetry': auto_retry_count,
    }
    formal_counters_valid = bool(
        len(save_receipts) == 6
        and formal_counters
        == {
            'physicalMutation': 6,
            'save1': 3,
            'save2': 3,
            'publishRequest': 0,
            'unknown': 0,
            'autoRetry': 0,
        }
        and all(item.get('mutationCount') == 1 for item in save_receipts)
    )
    discovery_proof_hashes = {
        value
        for value in campaign_evidence.get('_proofHashes', [])
        if _acceptance_digest(value) is not None
    }
    formal_proof_hashes = {
        value
        for value in save_proof_hashes
        if _acceptance_digest(value) is not None
    }
    cross_phase_evidence_distinct = bool(
        len(discovery_proof_hashes) == 5
        and len(formal_proof_hashes) == 30
        and discovery_proof_hashes.isdisjoint(formal_proof_hashes)
    )
    discovery_command_id = campaign_evidence.get('_commandId')
    discovery_lease_id = campaign_evidence.get('_leaseId')
    cross_phase_authority_distinct = bool(
        isinstance(discovery_command_id, str)
        and discovery_command_id.strip()
        and isinstance(discovery_lease_id, str)
        and discovery_lease_id.strip()
        and discovery_command_id not in save_command_ids
        and discovery_lease_id not in save_lease_ids
    )
    campaign_lineage_consistent = bool(
        campaign_evidence.get('lineageConsistent') is True
        and formal_counters_valid
        and cross_phase_evidence_distinct
        and cross_phase_authority_distinct
    )
    lineage_consistent = bool(lineage_consistent and campaign_lineage_consistent)
    discovery_counters = campaign_evidence.get('discovery', {}).get(
        'counters', {}
    )
    campaign = {
        key: value
        for key, value in campaign_evidence.items()
        if not key.startswith('_')
    }
    campaign['lineageConsistent'] = campaign_lineage_consistent
    campaign['formalCountersValid'] = formal_counters_valid
    campaign['crossPhaseEvidenceDistinct'] = cross_phase_evidence_distinct
    campaign['crossPhaseAuthorityDistinct'] = cross_phase_authority_distinct
    campaign['formal'] = {
        'taskId': task_id,
        'snapshotId': int(payload.get('plan_snapshot_id') or 0),
        'snapshotSha256': _acceptance_digest(
            payload.get('plan_snapshot_hash')
        ),
        'scopeSha256': _acceptance_digest(scope_sha256),
        'counters': formal_counters,
    }
    campaign['totals'] = {
        'physicalMutation': (
            int(discovery_counters.get('physicalMutation') or 0)
            + formal_counters['physicalMutation']
        ),
        'save1': (
            int(discovery_counters.get('save1') or 0)
            + formal_counters['save1']
        ),
        'save2': (
            int(discovery_counters.get('save2') or 0)
            + formal_counters['save2']
        ),
        'publishRequest': (
            int(discovery_counters.get('publishRequest') or 0)
            + formal_counters['publishRequest']
        ),
        'unknown': (
            int(discovery_counters.get('unknown') or 0)
            + formal_counters['unknown']
        ),
        'autoRetry': formal_counters['autoRetry'],
    }
    blockers: list[str] = []

    def block(code: str, condition: bool) -> None:
        if condition and code not in blockers:
            blockers.append(code)

    block('TASK_NOT_COMPLETED', task.get('status') not in {'completed', 'succeeded'})
    block('TASK_MODE_OR_PATH_INVALID', task.get('mode') != 'batch_draft_save' or _task_plan_path(task) != 'B')
    block('ORDERED_PRODUCT_COUNT_INVALID', len(ordered_products) != 3)
    block('ORDERED_PRODUCT_IDENTITY_INVALID', [item.get('ordinal') for item in ordered_products] != [1, 2, 3] or len(set(scoped_product_ids)) != 3)
    block('ORDERED_JOB_NOT_SUCCEEDED', any(item.get('status') not in {'completed', 'succeeded'} for item in ordered_products))
    block('CANONICAL_PRODUCT_RECEIPTS_INCOMPLETE', len(receipts_by_job) != 3)
    block('CANONICAL_RECEIPT_ROWS_INVALID', bool(receipt_row_issues))
    block(
        'CANONICAL_SAVE_STAGE_AUTHORITY_DRIFT',
        save_stage_authority.get('ok') is not True,
    )
    block(
        'CANONICAL_SAVE_STAGE_RECEIPTS_INCOMPLETE',
        len(persisted_save_receipts) != 6
        or len(save_stage_receipt_hashes) != 6
        or any(
            _acceptance_digest(value) is None
            for value in save_stage_receipt_hashes + nested_save_receipt_hashes
        )
        or len(set(save_stage_receipt_hashes)) != 6
        or len(set(nested_save_receipt_hashes)) != 6,
    )
    block('SAVE_RECEIPTS_INCOMPLETE', len(save_receipts) != 6)
    block('SAVE_RECEIPT_PAIRS_INVALID', len(save_pairs) != 6 or set(save_pairs) != expected_save_pairs or len(set(save_pairs)) != 6)
    block('SAVE_RECEIPT_AUTHORITY_REUSED', len(set(save_command_ids)) != 6 or len(set(save_lease_ids)) != 6 or any(not isinstance(value, str) or not value.strip() for value in save_command_ids + save_lease_ids))
    block('SAVE_PROOF_HASH_INVALID_OR_REUSED', len(save_proof_hashes) != 30 or any(_acceptance_digest(value) is None for value in save_proof_hashes) or len(set(save_proof_hashes)) != 30)
    block('MUTATION_LEDGER_INCOMPLETE', len(mutation_ledger) != 6)
    block('MUTATION_LEDGER_PAIRS_INVALID', len(ledger_pairs) != 6 or set(ledger_pairs) != expected_save_pairs or len(set(ledger_pairs)) != 6)
    block('RECEIPT_LEDGER_BINDING_MISMATCH', not receipt_ledger_bound)
    block('MUTATION_LEDGER_SUCCESS_UNPROVEN', any(item.get('status') != 'succeeded' for item in mutation_ledger))
    block('MANDATORY_CAPABILITIES_INCOMPLETE', bool(capability_issues) or any(item['status'] != 'passed' for item in capabilities.values()))
    block('UNKNOWN_PRESENT', unknown_count != 0)
    block('AUTO_RETRY_PRESENT', auto_retry_count != 0)
    block('SAVE_MUTATION_COUNT_INVALID', any(item.get('mutationCount') != 1 for item in save_receipts))
    block('SAVE_BUSINESS_SUCCESS_MISSING', any(item.get('businessSuccess') is not True for item in save_receipts))
    block('SAVE_READBACK_MISMATCH', any(item.get('readbackEqual') is not True for item in save_receipts))
    block('SAVE_UNPUBLISHED_PROOF_MISSING', any(item.get('unpublished') is not True for item in save_receipts))
    block('PUBLISH_REQUEST_PRESENT', any(item.get('publishCount') != 0 for item in save_receipts))
    block('PUBLISH_SCOPE_NOT_FALSE', scope.get('publishAllowed') is not False)
    block('PUBLISHED_STATE_NOT_PROVEN_FALSE', published_state is not False)
    block('WRITER_FENCE_NOT_ENFORCED', len(fence_rows) != 1 or fence_conflicts != 0)
    block('WRITER_FENCE_NOT_RELEASED', not fence_released)
    block(
        'DISCOVERY_RECEIPT_INVALID',
        campaign_evidence.get('discoveryReceiptValid') is not True,
    )
    block(
        'DISCOVERY_COUNTERS_INVALID',
        campaign_evidence.get('discoveryCountersValid') is not True,
    )
    block(
        'DISCOVERY_FORMAL_CONTINUATION_INVALID',
        campaign_evidence.get('continuationValid') is not True,
    )
    block(
        'DISCOVERY_FORMAL_CHRONOLOGY_INVALID',
        campaign_evidence.get('chronologyValid') is not True,
    )
    block(
        'DISCOVERY_FORMAL_AUTHORITY_REUSED',
        not cross_phase_authority_distinct,
    )
    block(
        'DISCOVERY_FORMAL_EVIDENCE_REUSED',
        not cross_phase_evidence_distinct,
    )
    block('FORMAL_COUNTERS_INVALID', not formal_counters_valid)
    block('DISCOVERY_FORMAL_LINEAGE_MISMATCH', not campaign_lineage_consistent)
    block('PROVENANCE_LINEAGE_MISMATCH', not lineage_consistent)

    return {
        'schemaVersion': 'real_dxm_path_b_acceptance_export.v1',
        'acceptanceStatus': 'REAL_PATH_B_3_ACCEPTED' if not blockers else 'NON_READY',
        'task': {
            'id': task_id,
            'status': task.get('status'),
            'mode': task.get('mode'),
            'path': _task_plan_path(task),
            'orderedProductIds': [item.get('productId') for item in ordered_products],
            'unknownCount': unknown_count,
            'autoRetryCount': auto_retry_count,
        },
        'provenance': {
            'gitHead': scope.get('git', {}).get('head') if isinstance(scope.get('git'), Mapping) else None,
            'worktreeClean': scope.get('worktree', {}).get('git_dirty') is False if isinstance(scope.get('worktree'), Mapping) else False,
            'runtimeInstanceId': scope.get('runtime', {}).get('runtimeInstanceId') if isinstance(scope.get('runtime'), Mapping) else None,
            'browserRuntimeId': scope.get('runtime', {}).get('browserRuntimeId') if isinstance(scope.get('runtime'), Mapping) else None,
            'browserSessionId': scope.get('runtime', {}).get('browserSessionId') if isinstance(scope.get('runtime'), Mapping) else None,
            'scopeSha256': scope_sha256 or None,
            'l2EvidenceFingerprint': scope.get('l2', {}).get('evidenceFingerprint') if isinstance(scope.get('l2'), Mapping) else None,
            'lineageConsistent': lineage_consistent,
        },
        'campaign': campaign,
        'orderedProducts': ordered_products,
        'capabilities': capabilities,
        'saveReceipts': save_receipts,
        'mutationLedger': mutation_ledger,
        'publish': {
            'allowed': scope.get('publishAllowed'),
            'requestCount': publish_request_count,
            'published': published_state,
            'finalReadbackPublished': (
                False
                if published_state is False
                else None
            ),
        },
        'writerFence': {
            'shopId': scope.get('shop', {}).get('shopId') if isinstance(scope.get('shop'), Mapping) else None,
            'enforced': bool(fence_rows) and fence_conflicts == 0,
            'conflictCount': fence_conflicts,
            'released': fence_released,
        },
        'blockers': blockers,
    }


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
    required_confirmation = _assert_task_can_receive_manual_approval(
        task_id,
        payload,
        allow_exact_formal_path_b=True,
    )
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
    task_path = _task_plan_path(task)
    real_authorization: dict[str, Any] | None = None
    if task_path == 'B':
        if (
            not isinstance(payload.real_dxm_write_scope, Mapping)
            or not isinstance(payload.real_dxm_write_approval, Mapping)
        ):
            _scope_rejected(
                'SCOPE_AND_APPROVAL_REQUIRED',
                'Path B 原子启动缺少 scope 或 ApprovalFile。',
            )
        real_authorization = _validate_real_scope_task_binding(
            task,
            payload.real_dxm_write_scope,
            raw_approval=payload.real_dxm_write_approval,
            approved_by=payload.approved_by,
        )
        result = repo.approve_and_start_real_dxm_path_b(
            task_id,
            scope=real_authorization['scope'],
            approval=real_authorization['approval'],
            predecessor_scope_sha256=payload.predecessor_scope_sha256,
            discovery_receipt_sha256=payload.discovery_receipt_sha256,
            token=secrets.token_urlsafe(24),
            confirmation=required_confirmation,
            approved_by=payload.approved_by.strip(),
            lease_id=uuid.uuid4().hex,
        )
    else:
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
        if task_path == 'B':
            _scope_rejected(
                result.reason_code,
                'ApprovalFile 消费、授权绑定与任务启动未能原子完成。',
            )
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
                real_authorization=(
                    payload.get('real_dxm_write_authorization')
                    if isinstance(payload.get('real_dxm_write_authorization'), Mapping)
                    else None
                ),
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
    allowed_states = {
        'single_save': {'SAVE_ONLY'},
        'batch_draft_save': {
            'SAVE_ONLY',
            PATH_B_SAVE1_DISCOVERY_STATE,
            'SAVE2_ONLY',
        },
    }.get(mode)
    if allowed_states is None or state not in allowed_states:
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


def _scope_rejected(detail_code: str, message: str) -> NoReturn:
    raise HTTPException(
        status_code=409,
        detail={
            'reason_code': 'SCOPE_REJECTED',
            'detail_code': detail_code,
            'message': message,
            'mutation_count': 0,
        },
    )


def _task_plan_path(task: Mapping[str, Any]) -> str:
    payload = task.get('payload') if isinstance(task.get('payload'), Mapping) else {}
    plan = payload.get('plan_snapshot') if isinstance(payload.get('plan_snapshot'), Mapping) else {}
    payload_path = str(payload.get('path') or '').strip().upper()
    plan_path = str(plan.get('path') or '').strip().upper()
    return payload_path if payload_path == plan_path else ''


def _assert_real_scope_data_dir_external() -> None:
    try:
        Path(DATA_DIR).resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return
    _scope_rejected(
        'DATA_DIR_INSIDE_WORKTREE',
        '真实 scope Prepare 要求 DXM_DATA_DIR 位于 Git worktree 外。',
    )


def _validate_scope_field_hashes_against_frozen_task(
    task: Mapping[str, Any],
    scope: Mapping[str, Any],
) -> None:
    """Prove an exact, stage-authoritative field grant against the snapshot."""

    payload = task.get('payload') if isinstance(task.get('payload'), Mapping) else {}
    plan = payload.get('plan_snapshot') if isinstance(payload.get('plan_snapshot'), Mapping) else {}
    item_snapshots = plan.get('item_snapshots') if isinstance(plan.get('item_snapshots'), list) else []
    item_by_product: dict[int, Mapping[str, Any]] = {}
    for item in item_snapshots:
        if not isinstance(item, Mapping):
            continue
        try:
            product_id = int(item.get('product_id'))
        except (TypeError, ValueError):
            continue
        if product_id in item_by_product:
            _scope_rejected('FROZEN_PRODUCT_DUPLICATE', '冻结 snapshot 商品身份重复。')
        item_by_product[product_id] = item

    for product_scope in scope.get('orderedProducts') or []:
        if not isinstance(product_scope, Mapping):
            _scope_rejected('FIELD_HASH_BINDING_INVALID', '字段哈希授权结构无效。')
        product_id = int(product_scope.get('productId') or 0)
        frozen_item = item_by_product.get(product_id)
        if not isinstance(frozen_item, Mapping):
            _scope_rejected('FROZEN_PRODUCT_NOT_FOUND', '字段哈希授权找不到冻结商品。')
        current_values = frozen_item.get('current_value_snapshot')
        current_values = current_values if isinstance(current_values, Mapping) else {}
        resolution = frozen_item.get('resolution_result')
        resolution = resolution if isinstance(resolution, Mapping) else {}
        resolved_fields = resolution.get('resolved_fields')
        resolved_fields = resolved_fields if isinstance(resolved_fields, list) else []
        resolved_by_field: dict[str, Mapping[str, Any]] = {}
        for resolved in resolved_fields:
            if (
                not isinstance(resolved, Mapping)
                or not isinstance(resolved.get('field_key'), str)
                or 'resolved_value' not in resolved
            ):
                continue
            field_key = str(resolved['field_key'])
            if field_key in resolved_by_field:
                _scope_rejected(
                    'FROZEN_RESOLVED_FIELD_DUPLICATE',
                    '冻结 snapshot 的 resolved field 身份重复。',
                )
            resolved_by_field[field_key] = resolved
        trusted_stages = _trusted_real_write_stage_by_field(frozen_item)
        if trusted_stages is None:
            _scope_rejected(
                'FIELD_SAVE_STAGE_AUTHORITY_NOT_FROZEN',
                '冻结 snapshot 尚未提供可信的 SAVE1/SAVE2 字段阶段分区。',
            )
        if set(trusted_stages) != set(resolved_by_field):
            _scope_rejected(
                'FROZEN_FIELD_STAGE_COVERAGE_DRIFT',
                '冻结字段阶段分区必须精确覆盖全部 resolved fields。',
            )
        seen_fields: set[str] = set()
        requested_by_stage: dict[str, set[str]] = {'SAVE1': set(), 'SAVE2': set()}
        for binding in product_scope.get('allowedFields') or []:
            if not isinstance(binding, Mapping):
                _scope_rejected('FIELD_HASH_BINDING_INVALID', '字段哈希授权结构无效。')
            field_name = str(binding.get('field') or '')
            save_stage = str(binding.get('saveStage') or '')
            if field_name in seen_fields:
                _scope_rejected(
                    'FIELD_REUSED_ACROSS_SAVE_STAGES',
                    '同一字段不得跨 SAVE1/SAVE2 重复授权。',
                )
            seen_fields.add(field_name)
            if save_stage not in requested_by_stage:
                _scope_rejected('FIELD_SAVE_STAGE_INVALID', '字段未绑定到 SAVE1 或 SAVE2。')
            requested_by_stage[save_stage].add(field_name)
            frozen_resolved = resolved_by_field.get(field_name)
            if frozen_resolved is None:
                _scope_rejected(
                    'EXPECTED_FIELD_NOT_FROZEN',
                    '字段 expected 值未进入不可变 plan snapshot。',
                )
            if trusted_stages.get(field_name) != save_stage:
                _scope_rejected(
                    'FIELD_SAVE_STAGE_DRIFT',
                    '调用方字段阶段与冻结的 SAVE1/SAVE2 权威分区不一致。',
                )
            if field_name not in current_values:
                _scope_rejected(
                    'PREIMAGE_FIELD_NOT_FROZEN',
                    '字段 preimage 缺少明确的冻结值；不能把缺失猜成 null。',
                )
            expected_preimage = real_scope_sha256(current_values[field_name])
            expected_after = real_scope_sha256(frozen_resolved['resolved_value'])
            if (
                not hmac.compare_digest(
                    str(binding.get('preimageSha256') or '').encode('utf-8'),
                    expected_preimage.encode('utf-8'),
                )
                or not hmac.compare_digest(
                    str(binding.get('expectedSha256') or '').encode('utf-8'),
                    expected_after.encode('utf-8'),
                )
            ):
                _scope_rejected(
                    'FIELD_HASH_BINDING_DRIFT',
                    '字段哈希授权与冻结 preimage/expected 值不一致。',
                )
        trusted_by_stage = {
            stage: {
                field_name
                for field_name, trusted_stage in trusted_stages.items()
                if trusted_stage == stage
            }
            for stage in ('SAVE1', 'SAVE2')
        }
        if (
            any(not fields for fields in trusted_by_stage.values())
            or requested_by_stage != trusted_by_stage
        ):
            _scope_rejected(
                'FIELD_SCOPE_NOT_EXACT',
                'scope 必须逐阶段精确覆盖冻结的全部 SAVE1/SAVE2 字段。',
            )


def _validate_fresh_scope_reader_binding(
    scope: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    """Cross-check shop and product identity through the current read-only Reader."""

    session = plan.get('session_context') if isinstance(plan.get('session_context'), Mapping) else {}
    if (
        str(session.get('account_ref_hash') or '') != scope['account']['accountContextHash']
        or int(session.get('shop_id') or 0) != scope['shop']['shopId']
        or str(session.get('shop_name') or '') != scope['shop']['shopName']
    ):
        _scope_rejected('FROZEN_SESSION_DRIFT', '冻结账号或店铺身份与 scope 不一致。')
    expected_session_ref = str(session.get('session_ref') or '')
    try:
        shops = _run_login_flow(
            DxmDraftReader(workflow_adapter).list_shops,
            fail_if_busy=True,
        )
    except Exception as exc:
        _scope_rejected(
            'FRESH_READER_UNAVAILABLE',
            f'无法取得 fresh Reader 店铺事实：{type(exc).__name__}。',
        )
    if (
        not isinstance(shops, Mapping)
        or shops.get('source') != 'api'
        or shops.get('session_bound') is not True
        or str(shops.get('session_ref') or '') != expected_session_ref
    ):
        _scope_rejected('FRESH_READER_SESSION_DRIFT', 'fresh Reader 会话与冻结会话不一致。')
    matching_shops = [
        item
        for item in shops.get('shops') or []
        if isinstance(item, Mapping)
        and str(item.get('id') or '') == str(scope['shop']['shopId'])
    ]
    if (
        len(matching_shops) != 1
        or str(matching_shops[0].get('name') or '') != scope['shop']['shopName']
    ):
        _scope_rejected('FRESH_SHOP_IDENTITY_DRIFT', 'fresh Reader 店铺身份与 scope 不一致。')

    required_ids = {str(item['productId']) for item in scope['orderedProducts']}
    visible_ids: set[str] = set()
    page_no = 1
    while required_ids - visible_ids:
        try:
            page = _run_login_flow(
                DxmDraftReader(workflow_adapter).list_products,
                shop_id=str(scope['shop']['shopId']),
                page_no=page_no,
                page_size=200,
                fail_if_busy=True,
            )
        except Exception as exc:
            _scope_rejected(
                'FRESH_READER_UNAVAILABLE',
                f'无法取得 fresh Reader 商品事实：{type(exc).__name__}。',
            )
        if (
            not isinstance(page, Mapping)
            or page.get('source') != 'api'
            or page.get('session_bound') is not True
            or not str(page.get('session_ref') or '')
            or str(page.get('session_ref') or '') != expected_session_ref
        ):
            _scope_rejected('FRESH_READER_SESSION_DRIFT', 'fresh Reader 商品页会话已漂移。')
        visible_ids.update(
            str(item.get('id'))
            for item in page.get('items') or []
            if isinstance(item, Mapping) and item.get('id') is not None
        )
        pagination = page.get('pagination') if isinstance(page.get('pagination'), Mapping) else {}
        if pagination.get('has_next') is not True:
            break
        page_no += 1
        if page_no > 100_000:
            _scope_rejected('FRESH_READER_PAGINATION_INVALID', 'fresh Reader 分页未能收敛。')
    if required_ids - visible_ids:
        _scope_rejected('FRESH_PRODUCT_IDENTITY_DRIFT', 'scope 商品不再属于 fresh Reader 草稿集合。')


def _validate_real_scope_task_binding(
    task: Mapping[str, Any],
    raw_scope: Mapping[str, Any],
    *,
    raw_approval: Mapping[str, Any] | None = None,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Bind an external scope to current repository and live runtime truth."""

    try:
        if raw_approval is None:
            scope = validate_real_dxm_write_scope(raw_scope)
            approval = None
        else:
            authorization = validate_real_dxm_write_authorization(
                scope=raw_scope,
                approval=raw_approval,
            )
            scope = authorization['scope']
            approval = authorization['approval']
    except RealDxmWriteScopeError as exc:
        _scope_rejected(exc.detail_code, '真实写 scope 或 ApprovalFile 合同无效。')

    if _task_plan_path(task) != 'B':
        _scope_rejected('TASK_PATH_MISMATCH', '真实 Path B scope 不能授权其它路径。')
    payload = task.get('payload') if isinstance(task.get('payload'), Mapping) else {}
    plan = payload.get('plan_snapshot') if isinstance(payload.get('plan_snapshot'), Mapping) else {}
    snapshot = scope['snapshot']
    if (
        int(task.get('id') or 0) != snapshot['taskId']
        or int(payload.get('plan_snapshot_id') or 0) != snapshot['snapshotId']
        or str(payload.get('plan_snapshot_hash') or '').upper()
        != snapshot['snapshotSha256']
        or str(plan.get('snapshot_hash') or '').upper()
        != snapshot['snapshotSha256']
    ):
        _scope_rejected('SNAPSHOT_BINDING_DRIFT', 'scope 与冻结任务或 snapshot 不一致。')
    ordered_ids = [item['productId'] for item in scope['orderedProducts']]
    task_ids = payload.get('product_ids') if isinstance(payload.get('product_ids'), list) else []
    job_ids = [job.get('product_id') for job in task.get('jobs') or [] if isinstance(job, Mapping)]
    if len(ordered_ids) < 3 or ordered_ids != task_ids or ordered_ids != job_ids:
        _scope_rejected('ORDERED_PRODUCTS_DRIFT', 'scope、snapshot 与队列商品顺序不一致。')
    _validate_scope_field_hashes_against_frozen_task(task, scope)
    if (
        int(task.get('store_id') or 0) != scope['shop']['shopId']
        or str(plan.get('shop_scope') or '') != str(scope['shop']['shopId'])
    ):
        _scope_rejected('SHOP_BINDING_DRIFT', 'scope 与冻结店铺不一致。')
    if payload.get('publish_allowed') is not False or plan.get('publish_allowed') is not False:
        _scope_rejected('PUBLISH_INTENT_FORBIDDEN', '冻结任务必须永久禁止发布。')

    git_summary = _current_git_summary()
    current_worktree = _current_execution_worktree_identity(git_summary)
    if str(git_summary.get('head') or '').lower() != scope['git']['head']:
        _scope_rejected('GIT_HEAD_DRIFT', '当前 Git HEAD 与 scope 不一致。')
    if current_worktree != scope['worktree']:
        _scope_rejected('WORKTREE_IDENTITY_DRIFT', '当前工作树身份与 scope 不一致。')
    _assert_real_scope_data_dir_external()
    _validate_fresh_scope_reader_binding(scope, plan)
    adapter_browser_session_id = str(workflow_adapter.browser_session_id() or '')
    try:
        runtime_browser_session_id = _current_browser_session_id()
    except HTTPException:
        _scope_rejected('BROWSER_SESSION_UNAVAILABLE', 'BrowserAgent 当前会话不可用。')
    try:
        account_ref_hash = workflow_adapter.refresh_account_context_hash()
    except Exception:
        _scope_rejected('ACCOUNT_CONTEXT_UNAVAILABLE', '无法从当前会话重读账号身份。')
    if (
        str(runtime_identity.instance_id) != scope['runtime']['runtimeInstanceId']
        or str(browser_agent_runtime.runtime_id) != scope['runtime']['browserRuntimeId']
        or not adapter_browser_session_id
        or adapter_browser_session_id != runtime_browser_session_id
        or runtime_browser_session_id != scope['runtime']['browserSessionId']
        or account_ref_hash != scope['account']['accountContextHash']
    ):
        _scope_rejected('RUNTIME_IDENTITY_DRIFT', '运行时、浏览器会话或账号身份已变化。')
    l2_gate = l2_real_probe_gate()
    if (
        l2_gate.get('status') != 'passed'
        or _l2_authorization_fingerprint(l2_gate)
        != scope['l2']['evidenceFingerprint']
    ):
        _scope_rejected('L2_EVIDENCE_DRIFT', '当前 fresh L2 与 scope 不一致。')
    if approval is not None and approved_by is not None:
        if not hmac.compare_digest(
            str(approval.get('approvedBy') or '').encode('utf-8'),
            str(approved_by or '').strip().encode('utf-8'),
        ):
            _scope_rejected('APPROVER_MISMATCH', 'ApprovalFile 批准人与请求批准人不一致。')
    return {'scope': scope, 'approval': approval}


def _assert_task_can_receive_manual_approval(
    task_id: int,
    request: TaskManualApprovalRequest,
    *,
    allow_exact_formal_path_b: bool = False,
) -> str:
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
        if _task_plan_path(task) == 'B':
            formal_lineage_requested = bool(
                allow_exact_formal_path_b
                and request.predecessor_scope_sha256
                and request.discovery_receipt_sha256
            )
            if not is_plan_execution_path_released('B') and not formal_lineage_requested:
                raise HTTPException(
                    status_code=403,
                    detail={
                        'reason_code': PLAN_PATH_EXECUTION_NOT_RELEASED,
                        'message': 'Path B 生产能力与真实验收闭环前保持锁定。',
                    },
                )
            if allow_exact_formal_path_b and not formal_lineage_requested:
                _scope_rejected(
                    'FORMAL_LINEAGE_REQUIRED',
                    'Path B 原子正式启动必须绑定 sealed Discovery 与前序 scope。',
                )
            if (
                not isinstance(request.real_dxm_write_scope, Mapping)
                or not isinstance(request.real_dxm_write_approval, Mapping)
            ):
                _scope_rejected(
                    'SCOPE_AND_APPROVAL_REQUIRED',
                    'Path B 仅接受匹配的一次性 scope 与 ApprovalFile。',
                )
            authorization = _validate_real_scope_task_binding(
                task,
                request.real_dxm_write_scope,
                raw_approval=request.real_dxm_write_approval,
                approved_by=request.approved_by,
            )
            prepared = repo.get_real_dxm_write_scope(
                authorization['scope']['scopeSha256']
            )
            if not isinstance(prepared, Mapping) or prepared.get('status') != 'prepared':
                _scope_rejected(
                    'SCOPE_NOT_PREPARED_OR_CONSUMED',
                    'scope 未 Prepare 或 ApprovalFile 已被消费。',
                )
            if formal_lineage_requested and (
                prepared.get('purpose') != 'formal'
                or str(
                    prepared.get('lineage_discovery_receipt_sha256') or ''
                ).upper()
                != str(request.discovery_receipt_sha256 or '').upper()
                or str(
                    prepared.get('lineage_predecessor_scope_sha256') or ''
                ).upper()
                != str(request.predecessor_scope_sha256 or '').upper()
            ):
                _scope_rejected(
                    'FORMAL_LINEAGE_SCOPE_MISMATCH',
                    'prepared scope 未绑定请求中的 Discovery 谱系。',
                )
        else:
            if request.predecessor_scope_sha256 or request.discovery_receipt_sha256:
                _scope_rejected(
                    'FORMAL_LINEAGE_PATH_MISMATCH',
                    'Discovery 谱系只允许用于 exact Path B 原子启动。',
                )
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
