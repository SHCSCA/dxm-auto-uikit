"""仅隔离首写成功提供器；真实 Worker 文件与来源事务不代表生产前序成立。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import current_thread

import pytest

from src import db, repository as repository_module
from src.batch_edit import native_video_input_source as source
from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults
from src.batch_edit.native_video_observation_contract import ACTION, STATE
from src.execution import browser_agent_worker as worker
from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.state_machine.contracts import StateName
from tests.support import content_authority_case
from tests.support.content_observation_case import Flow
from tests.support.native_video_observation_case import make_observation


NOW = content_authority_case.NOW


class NativeInputFlow(Flow):
    def observe_native_video_inputs(self, *, defaults, target_identity, store_name, shop_id, **kwargs):
        self.observer_thread = current_thread().name
        path = self.screenshot_root / 'synthetic-native-video-input.png'
        self._page.screenshot(path=str(path), full_page=True)
        observation = make_observation(payload=defaults['_frozen_execution_payload'], target_identity=target_identity,
            context=self._execution_evidence_context, shop_id=shop_id, evidence_ref=self._evidence_descriptor(path),
            started_at=NOW, completed_at=NOW)
        origin = datetime.fromisoformat(NOW.replace('Z', '+00:00')).timestamp() * 1000 - 1000
        for raw in (observation['before'], observation['after'], observation['lifecycle']):
            raw['document_time_origin'] = origin
        return {'ok': True, 'stage': 'native_video_inputs_observed', 'page_url': self._page.url,
            'target_identity': target_identity, 'store_name': store_name, 'write_attempted': False,
            'native_video_input_observation': observation, 'evidence_ref': observation['observation']['evidence_ref']}


@pytest.fixture
def video_source_case(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'native-input.db'); db.init_db()
    original = content_authority_case._shared_required_editor_actions_plan
    def configured_plan():
        value = deepcopy(original())
        value['editor_actions']['17']['video']['generation_rule'] = {
            'image_selection': 'native_default', 'transition': {'mode': 'native_default'}, 'music': {'mode': 'native_default'}}
        return value
    monkeypatch.setattr(content_authority_case, '_shared_required_editor_actions_plan', configured_plan)
    case = content_authority_case.content_dispatch_case(monkeypatch)
    repo = case['repository']; task = repo.get_task_private(case['task']['id']); job = task['jobs'][0]
    repo.update_job(job['id'], status='running', current_step_code=STATE)
    task = repo.get_task_private(task['id']); job = task['jobs'][0]
    payload = compile_frozen_execution_payload(task, job)
    screenshots = tmp_path / 'screenshots'; screenshots.mkdir()
    monkeypatch.setattr(repository_module, 'SCREENSHOT_DIR', screenshots)
    monkeypatch.setattr(worker, 'SCREENSHOT_DIR', screenshots); monkeypatch.setattr(worker, 'DATA_DIR', tmp_path)
    flow = NativeInputFlow(payload, session=case['live'].browser_session_id); flow.screenshot_root = screenshots
    runtime = worker.BrowserAgentRuntime(DxmWorkflowAdapter(flow), mutation_ledger=case['ledger'])
    runtime._runtime_id = case['live'].browser_runtime_id
    command = BrowserAgentCommand(command_id='b'*32, idempotency_key='isolated-native-input-read',
        deadline=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat(), expected_page='editor',
        runtime_id=runtime.runtime_id, task_id=task['id'], job_id=job['id'], state=STATE, action=ACTION,
        execution_mode='batch_draft_save', params={'defaults': frozen_execution_defaults(payload),
            'product_query': str(job['product_id']), 'store_name': case['store']['name'], 'shop_id': str(case['store']['id']),
            'target_identity': task['payload']['plan_snapshot']['item_snapshots'][0]['target_identity'],
            'first_fill_source_sha256': 'D'*64})
    yield {**case, 'task': task, 'job': job, 'command': command, 'payload': payload, 'flow': flow,
           'runtime': runtime, 'screenshots': screenshots}
    runtime._executor.shutdown(wait=True)


@pytest.fixture
def isolated_first_fill(video_source_case, monkeypatch):
    # 仅隔离未具生产证据的首写前序；其余合同、文件、截图、批准和数据库均真实复验。
    parent = {'source_sha256': 'D'*64, 'created_at': NOW}
    monkeypatch.setattr(source, 'first_fill_source', lambda *args, **kwargs: deepcopy(parent))
    return {**video_source_case, 'isolated_parent': parent}


def persist(case):
    repo, task, job = case['repository'], case['task'], case['job']; command = case['command'].to_payload()
    reservation = repo.reserve_native_video_inputs(task['id'], job['id'], command)
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    record = repo.persist_native_video_inputs(task['id'], job['id'], command, result)
    return reservation, result, record


def freeze(case):
    _, _, source_record = persist(case)
    record = case['repository'].persist_native_video_input_freeze(case['task']['id'], case['job']['id'],
        source_sha256=source_record['source_sha256'])
    return source_record, record


def generation(case, record):
    repo = case['repository']; repo.update_job(case['job']['id'], current_step_code='BATCH_VIDEO_SUBMIT')
    task = repo.get_task_private(case['task']['id']); job = task['jobs'][0]
    params = {key: deepcopy(value) for key, value in case['command'].params.items() if key != 'first_fill_source_sha256'}
    params['target_source_urls'] = params['target_identity']['source_urls']
    params['native_video_input_freeze_sha256'] = record['freeze_sha256']
    return case['runner']._build_browser_agent_command(task, job, StateName.BATCH_VIDEO_SUBMIT, 'submit_editor_video', params)


def count(kind):
    with db.connection() as conn:
        return conn.execute('SELECT COUNT(*) AS n FROM job_evidences WHERE evidence_type=?', (kind,)).fetchone()['n']


def rewrite(kind, update):
    with db.connection() as conn:
        row = conn.execute('SELECT id,meta_json FROM job_evidences WHERE evidence_type=?', (kind,)).fetchone()
        value = db.loads(row['meta_json'], {}); update(value)
        conn.execute('UPDATE job_evidences SET meta_json=? WHERE id=?', (db.dumps(value), row['id']))
