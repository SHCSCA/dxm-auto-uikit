"""仅隔离调度顺序的显式 spy；不声明真实控件、来源事务或浏览器能力。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src import db
from src.batch_edit.editor_inventory_contract import STATE
from tests.support.content_authority_case import content_dispatch_case


class InventoryRuntimeSpy:
    def __init__(self, runtime_id):
        self.runtime_id, self.calls, self.cancelled = runtime_id, [], []
        self.on_run = None
        self.healthy = True
        self.reservations = {}

    def reserve_command(self, command):
        self.reservations[command.command_id] = False
        return {'ok': True, 'status': 'reserved', 'commandId': command.command_id, 'runtimeId': self.runtime_id}

    def status(self):
        return {'runtimeId': self.runtime_id, 'healthy': self.healthy, 'active': False,
            'status': 'idle', 'mutationLedgerEnabled': True}

    def run(self, command, *, timeout_seconds):
        if self.reservations.pop(command.command_id, False):
            raise RuntimeError('BROWSER_AGENT_COMMAND_CANCELLED_BEFORE_START')
        self.calls.append(command)
        if self.on_run is not None:
            return self.on_run(command)
        return {'synthetic_orchestration_result': True}

    def cancel_command(self, command_id, runtime_id):
        self.cancelled.append((command_id, runtime_id))
        if command_id in self.reservations:
            self.reservations[command_id] = True
            return {'ok': True, 'status': 'cancelled_before_start', 'commandId': command_id, 'runtimeId': runtime_id}
        return {'ok': True}


@pytest.fixture
def inventory_runner_case(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'inventory-runner.db')
    db.init_db()
    case = content_dispatch_case(monkeypatch)
    repo, runner = case['repository'], case['runner']
    job_id = case['task']['jobs'][0]['id']
    repo.update_job(job_id, status='running', current_step_code=STATE)
    task = repo.get_task_private(case['task']['id']); job = task['jobs'][0]
    runtime = InventoryRuntimeSpy(case['live'].browser_runtime_id)
    runner.browser_agent_runtime = runtime
    runner.workflow_adapter = SimpleNamespace()
    runner.workflow_action_timeout_seconds = 2
    events, commands = [], []

    def reserve(task_id, current_job_id, command):
        events.append('reserve'); commands.append(deepcopy(command))
        assert (task_id, current_job_id) == (task['id'], job['id'])

    def persist(task_id, current_job_id, command, result):
        events.append('persist')
        assert command == commands[0] and result == {'synthetic_orchestration_result': True}
        return {'source_sha256': 'E' * 64}

    monkeypatch.setattr(repo, 'reserve_editor_control_inventory', reserve, raising=False)
    monkeypatch.setattr(repo, 'persist_editor_control_inventory', persist, raising=False)
    yield {**case, 'task': task, 'job': job, 'runtime': runtime, 'events': events, 'commands': commands}
    if runner._workflow_executor is not None:
        runner._workflow_executor.shutdown(wait=True)
