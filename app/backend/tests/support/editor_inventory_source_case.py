"""合成只读页面与真实 Repo/Adapter/Worker 往返，不证明生产控件覆盖。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import current_thread

import pytest

from src import db, repository as repository_module
from src.batch_edit.editor_inventory_contract import ACTION, SCHEMA, STATE, command_binding
from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults
from src.batch_edit.plan_snapshot_compiler import plan_snapshot_sha256
from src.batch_edit.scope_contract import canonical_sha256
from src.execution import browser_agent_worker as worker
from src.execution.browser_agent_protocol import BrowserAgentCommand
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.editor_control_inventory import collect_editor_control_inventory
from tests.support import content_authority_case
from tests.support.content_observation_case import Flow, Page, NOW


class InventoryPage(Page):
    def __init__(self, payload, category):
        super().__init__(payload)
        self.payload, self.category, self.main_frame = payload, category, object()
        self.missing_key = self.checkbox_key = None

    def is_closed(self):
        return False

    def evaluate(self, script, args):
        fields = []
        for field in args['fields']:
            key = field['field_key']; definition = self.category['normalized_schema']['properties'][key]
            kind = definition.get('type')
            checkbox = kind == 'boolean' or key == self.checkbox_key
            value = True if checkbox else '1' if kind in {'integer', 'number'} else 'Synthetic original English value'
            missing = ['CONTROL_NATIVE_IDENTITY_MISSING'] if key == self.missing_key else []
            observed = not missing and kind in {'string', 'number', 'integer', 'boolean'}
            if not observed and not missing:
                missing.append('CONTROL_TYPE_UNREVIEWED')
            control = None if key == self.missing_key else {'tag': 'input', 'id': key, 'name': key,
                'type': 'checkbox' if checkbox else 'text', 'visible': True,
                'disabled': False, 'read_only': False, 'content_editable': False}
            fields.append({'field_key': key, 'ui_binding': field['ui_binding'], 'match_count': int(control is not None),
                'control': control, 'raw_value': value if observed else None, 'value_observed': observed,
                'value_kind': ('checkbox_boolean' if checkbox else 'native_input_value') if observed else None,
                'options': None, 'section_bound': control is not None, 'missing': missing})
        return {'schema': 'dxm.editor_control_dom.v1', 'collected': True, 'url': self.url,
            'document_time_origin': 1000, 'root_count': 1, 'fields': fields, 'missing': [],
            'sections': [{**section, 'match_count': int(section['anchor'] is not None),
                'visible_count': int(section['anchor'] is not None)} for section in args['sections']]}


class InventoryFlow(Flow):
    def __init__(self, payload, category, *, session):
        super().__init__(payload, session=session)
        self._page = InventoryPage(payload, category)

    def observe_editor_control_inventory(self, **params):
        self.observer_thread = current_thread().name
        payload, category = params['defaults']['_frozen_execution_payload'], params['category_schema']
        before = collect_editor_control_inventory(self._page, payload, category)
        path = self.screenshot_root / 'synthetic-editor-inventory.png'
        self._page.screenshot(path=str(path), full_page=True)
        after = collect_editor_control_inventory(self._page, payload, category)
        ref = self._evidence_descriptor(path)
        observation = {'product_id': payload['product_id'], 'shop_id': params['shop_id'], 'browser_session_id': self.session,
            'page_url': self._page.url, 'target_identity_sha256': canonical_sha256(params['target_identity']),
            'observed_at': NOW, 'inventory_sha256': after['inventory_sha256'], 'evidence_ref': ref, 'write_attempted': False}
        wrapper = {'schema': SCHEMA, 'command': command_binding(self._execution_evidence_context),
            'execution_payload_hash': payload['payload_hash'], 'category_schema_hash': category['schema_hash'],
            'started_at': NOW, 'completed_at': NOW, 'before': before, 'after': after,
            'effect_facts': {'request_facts': [], 'unexpected_effects': []}, 'observation': observation}
        return {'ok': True, 'stage': 'editor_control_inventory_observed', 'page_url': self._page.url,
            'target_identity': params['target_identity'], 'store_name': params['store_name'],
            'write_attempted': False, 'editor_inventory_observation': wrapper, 'evidence_ref': ref}


@pytest.fixture
def inventory_source_case(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'editor-inventory.db'); db.init_db()
    original_freeze = content_authority_case.PlanSnapshotStore.freeze_with_task

    def freeze(store, snapshot, **kwargs):
        # 只规范冻结前的合成 Schema；不在来源复验中修改既有快照或补默认值。
        for item in snapshot['item_snapshots']:
            category = item['category_schema']; schema = category['normalized_schema']
            schema['required'] = sorted(schema['properties'])
            schema['dependentRequired'] = {}
            schema['allOf'] = []
            category['schema_hash'] = canonical_sha256(schema)
        snapshot['snapshot_hash'] = plan_snapshot_sha256(snapshot)
        return original_freeze(store, snapshot, **kwargs)

    monkeypatch.setattr(content_authority_case.PlanSnapshotStore, 'freeze_with_task', freeze)
    case = content_authority_case.content_dispatch_case(monkeypatch)
    repo = case['repository']; task = repo.get_task_private(case['task']['id']); job = task['jobs'][0]
    repo.update_job(job['id'], status='running', current_step_code=STATE)
    task = repo.get_task_private(task['id']); job = task['jobs'][0]
    payload = compile_frozen_execution_payload(task, job)
    category = deepcopy(task['payload']['plan_snapshot']['item_snapshots'][0]['category_schema'])
    screenshots = tmp_path / 'screenshots'; screenshots.mkdir()
    monkeypatch.setattr(repository_module, 'SCREENSHOT_DIR', screenshots)
    monkeypatch.setattr(worker, 'SCREENSHOT_DIR', screenshots); monkeypatch.setattr(worker, 'DATA_DIR', tmp_path)
    flow = InventoryFlow(payload, category, session=case['live'].browser_session_id); flow.screenshot_root = screenshots
    runtime = worker.BrowserAgentRuntime(DxmWorkflowAdapter(flow), mutation_ledger=case['ledger'])
    runtime._runtime_id = case['live'].browser_runtime_id
    command = BrowserAgentCommand(command_id='c'*32, idempotency_key='synthetic-editor-inventory',
        deadline=(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat(), expected_page='editor',
        runtime_id=runtime.runtime_id, task_id=task['id'], job_id=job['id'], state=STATE, action=ACTION,
        execution_mode='batch_draft_save', params={'defaults': frozen_execution_defaults(payload), 'category_schema': category,
            'product_query': str(job['product_id']), 'store_name': case['store']['name'], 'shop_id': str(case['store']['id']),
            'target_identity': deepcopy(task['payload']['plan_snapshot']['item_snapshots'][0]['target_identity'])})
    yield {**case, 'task': task, 'job': job, 'command': command, 'payload': payload,
        'category': category, 'flow': flow, 'runtime': runtime, 'screenshots': screenshots}
    runtime._executor.shutdown(wait=True)


def persist(case):
    repo, task, job = case['repository'], case['task']['id'], case['job']['id']
    command = case['command'].to_payload()
    reservation = repo.reserve_editor_control_inventory(task, job, command)
    result = case['runtime'].run(case['command'], timeout_seconds=10)
    record = repo.persist_editor_control_inventory(task, job, command, result)
    return reservation, result, record


def require_source(case, record):
    return case['repository'].require_editor_control_inventory(case['task']['id'], case['job']['id'], source_sha256=record['source_sha256'])


def records(kind):
    with db.connection() as conn:
        return conn.execute('SELECT * FROM job_evidences WHERE evidence_type=? ORDER BY id', (kind,)).fetchall()
