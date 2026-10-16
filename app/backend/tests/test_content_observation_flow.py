from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.batch_edit.content_observation_contract import ACTION, STATE, validate_observation
from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults
from src.execution.browser_agent_protocol import BrowserAgentCommand, validate_browser_agent_command
from src.execution.content_observation_guard import ContentObservationGuard
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution import browser_agent_worker as worker
from tests.support.content_observation_case import Flow
from tests.support.content_authority_case import content_dispatch_case
from src import db


@pytest.fixture
def observation_case(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'observation.db')
    db.init_db()
    case = content_dispatch_case(monkeypatch)
    task = case['repository'].get_task_private(case['task']['id'])
    job = task['jobs'][0]
    case['repository'].update_job(job['id'], status='running', current_step_code=STATE)
    task = case['repository'].get_task_private(task['id']); job = task['jobs'][0]
    payload = compile_frozen_execution_payload(task, job)
    flow = Flow(payload, session=case['live'].browser_session_id)
    screenshots = tmp_path / 'screenshots'; screenshots.mkdir()
    for module in (worker, __import__('src.repository', fromlist=['SCREENSHOT_DIR']),
                   __import__('src.execution.content_observation_flow', fromlist=['SCREENSHOT_DIR'])):
        monkeypatch.setattr(module, 'SCREENSHOT_DIR', screenshots)
    monkeypatch.setattr(worker, 'DATA_DIR', tmp_path)
    adapter = DxmWorkflowAdapter(flow)
    runtime = worker.BrowserAgentRuntime(adapter, mutation_ledger=case['ledger'])
    runtime._runtime_id = case['live'].browser_runtime_id
    command = BrowserAgentCommand(command_id='e'*32, idempotency_key='isolated-content-observation',
        deadline=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat(), expected_page='editor',
        runtime_id=runtime.runtime_id, task_id=task['id'], job_id=job['id'], state=STATE, action=ACTION,
        execution_mode='batch_draft_save', params={'defaults': frozen_execution_defaults(payload),
            'product_query': str(job['product_id']), 'store_name': case['store']['name'],
            'shop_id': str(case['store']['id']), 'target_identity': task['payload']['plan_snapshot']['item_snapshots'][0]['target_identity'],
            'translation_source_sha256': 'D'*64})
    yield {**case, 'task': task, 'job': job, 'command': command, 'payload': payload, 'flow': flow, 'runtime': runtime, 'screenshots': screenshots}
    runtime._executor.shutdown(wait=True)


def test_real_worker_adapter_pipeline_observes_independent_values_without_mutation_or_capability(observation_case):
    case = observation_case
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    assert result['ok'] is True
    assert result['action'] == ACTION and result['attempted_state'] == STATE
    observed = result['evidence']['observations']['content_finalize_observation']['observation']
    assert observed['values'] == case['flow']._page.values
    assert observed['values']['title'] != case['command'].params['defaults']['title']
    assert case['flow']._page.operations == ['readback', 'readback']
    assert all(name.startswith('dxm-browser-agent') for name in case['flow']._page.capture_threads)
    assert 'mandatory_capability_receipts' not in result['evidence']['observations']
    assert worker.load_browser_agent_action_source(case['command'].to_payload(), result,
        browser_session_id=case['flow'].session)['result']['size'] > 0
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0


@pytest.mark.parametrize('failure', ['drift', 'modal', 'missing'])
def test_flow_rejects_field_drift_blocking_modal_and_missing_bindings(observation_case, failure):
    case = observation_case
    setattr(case['flow']._page, failure, True)
    with pytest.raises(Exception):
        case['runtime'].run(case['command'], timeout_seconds=10)
    assert case['flow']._page.operations in ([], ['readback'], ['readback', 'readback'])
    assert not case['flow']._page.handlers and not case['flow']._page.listeners
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0


@pytest.mark.parametrize('change', [lambda cmd: replace(cmd, state='BATCH_WHOLESALE_FILL'),
    lambda cmd: replace(cmd, action='save_only'), lambda cmd: replace(cmd, authorization_lease_id='fake'),
    lambda cmd: replace(cmd, execution_payload_hash='A'*64),
    lambda cmd: replace(cmd, pre_dispatch_page='semi_managed'),
    lambda cmd: replace(cmd, params={**cmd.params, 'mutation_scope_id': 'fake'}),
    lambda cmd: replace(cmd, params={**cmd.params, 'defaults': {**cmd.params['defaults'], 'mutation_authorization': 'fake'}})])
def test_exact_readonly_pair_cannot_accept_mutation_scope_or_migrate_action(observation_case, change):
    with pytest.raises(ValueError):
        validate_browser_agent_command(change(observation_case['command']))
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0


def test_worker_rejects_readonly_mutation_callback_before_authorizer_or_operation(observation_case):
    called = []
    runtime, command = observation_case['runtime'], observation_case['command']
    decision = runtime._authorize_mutation(SimpleNamespace(), command, {'mutation_action': 'translate_language_click'},
        lambda: called.append('operation'))
    assert decision['executed'] is False and decision['reason'] == 'CONTENT_OBSERVATION_MUTATION_FORBIDDEN'
    assert called == []
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0


@pytest.mark.parametrize('url,body', [('https://www.dianxiaomi.com/api/smtProduct/add.json', 'categoryId=17'),
    ('https://www.dianxiaomi.com/api/smtCategory/attributeList.json', 'categoryId=18'),
    ('https://www.dianxiaomi.com/api/smtCategory/attributeList.json', 'categoryId=17&mutation=1')])
def test_guard_blocks_any_unexpected_request_or_schema_shape(observation_case, url, body):
    called = []
    with pytest.raises(RuntimeError, match='UNEXPECTED_EFFECT'):
        with ContentObservationGuard(observation_case['flow']._page, '17') as guard:
            guard._route(SimpleNamespace(request=SimpleNamespace(method='POST', url=url, post_data=body),
                abort=lambda: called.append('blocked'), continue_=lambda: called.append('allowed')))
    assert called == ['blocked']


def test_path_b_missing_binding_never_calls_the_modal_dismissing_fallback(observation_case, monkeypatch):
    from src.execution.dxm_login_flow import DxmLoginFlow
    calls = []
    monkeypatch.setattr(DxmLoginFlow, '_visible_frozen_fallback_result', lambda *args, **kwargs: calls.append('unsafe-fallback'))
    observation_case['flow']._page.missing = True
    with pytest.raises(RuntimeError, match='BINDINGS_OR_SCHEMA_UNPROVEN'):
        observation_case['runtime'].run(observation_case['command'], timeout_seconds=10)
    assert calls == []


def test_guard_rejects_popup_observed_during_teardown(observation_case, monkeypatch):
    page = observation_case['flow']._page
    original = page.unroute
    def unroute(pattern, callback):
        page.listeners['popup'](object())
        original(pattern, callback)
    monkeypatch.setattr(page, 'unroute', unroute)
    with pytest.raises(RuntimeError, match='UNEXPECTED_EFFECT'):
        with ContentObservationGuard(page, '17'):
            pass
    assert not page.handlers and not page.listeners


@pytest.mark.parametrize('phase', ['register', 'cleanup'])
def test_guard_partial_registration_and_cleanup_attempt_every_resource(observation_case, monkeypatch, caplog, phase):
    page = observation_case['flow']._page
    cleaned = []
    old_remove, old_unroute, old_on = page.remove_listener, page.unroute, page.on
    def remove(event, callback):
        cleaned.append(event)
        old_remove(event, callback)
        if phase == 'cleanup' and event == 'popup':
            raise RuntimeError('isolated listener cleanup failure')
    def unroute(pattern, callback):
        cleaned.append('route'); old_unroute(pattern, callback)
        if phase == 'cleanup':
            raise RuntimeError('isolated route cleanup failure')
    def register(event, callback):
        old_on(event, callback)
        if phase == 'register' and event == 'dialog':
            raise RuntimeError('isolated registration failure')
    monkeypatch.setattr(page, 'remove_listener', remove); monkeypatch.setattr(page, 'unroute', unroute); monkeypatch.setattr(page, 'on', register)
    with pytest.raises(RuntimeError):
        with ContentObservationGuard(page, '17'):
            pass
    assert 'route' in cleaned and 'popup' in cleaned and 'dialog' in cleaned
    if phase == 'cleanup':
        assert 'websocket' in cleaned
    assert not page.handlers and not page.listeners
    assert any('guard_' in record.message for record in caplog.records)
