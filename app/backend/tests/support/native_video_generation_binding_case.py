"""实际输入来源与批准事务用于生成消费测试；首写仍保留显式隔离边界。"""

from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace

import pytest

from src import db
from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults
from src.state_machine.contracts import StateName
from tests.support.native_video_input_source_case import NOW, freeze, isolated_first_fill, video_source_case


@pytest.fixture
def generation_input_case(isolated_first_fill):
    source, record = freeze(isolated_first_fill)
    return {**isolated_first_fill, 'input_source': source, 'input_freeze': record}


def build_submit(case, *, params=None, step='BATCH_VIDEO_SUBMIT'):
    repo, runner = case['repository'], case['runner']
    repo.update_job(case['job']['id'], current_step_code=step)
    task = repo.get_task_private(case['task']['id']); job = task['jobs'][0]
    defaults = frozen_execution_defaults(compile_frozen_execution_payload(task, job))
    spec = runner._workflow_action_worker_request(task, job, StateName.BATCH_VIDEO_SUBMIT, defaults)
    return runner._build_browser_agent_command(task, job, StateName.BATCH_VIDEO_SUBMIT,
        'submit_editor_video', {**spec[3], **deepcopy(params or {})})


def configure_main(case, monkeypatch):
    from src import main
    live, scope = case['live'], case['scope']
    monkeypatch.setattr(main, 'repo', case['repository'])
    monkeypatch.setattr(main, 'runtime_identity', SimpleNamespace(instance_id=live.runtime_instance_id))
    monkeypatch.setattr(main, '_closed_loop_replay_active', lambda: False)
    monkeypatch.setattr(main, '_current_browser_session_id', lambda: live.browser_session_id)
    monkeypatch.setattr(main, '_current_git_summary', lambda: {'head': live.git_head})
    monkeypatch.setattr(main, '_current_execution_worktree_identity', lambda summary: deepcopy(scope['worktree']))
    monkeypatch.setattr(main, 'l2_real_probe_gate', lambda: {'status': 'passed'})
    monkeypatch.setattr(main, '_l2_authorization_fingerprint', lambda gate: live.l2_evidence_fingerprint)
    monkeypatch.setattr(main, '_authorization_now', lambda: datetime.fromisoformat(NOW.replace('Z', '+00:00')))
    return main


def ledger_count():
    with db.connection() as conn:
        return conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n']
