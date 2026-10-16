"""真实 Worker 独立核对实际命令，不能只信观察字典自报的身份。"""

from copy import deepcopy

import pytest

from src import db
from tests.support.editor_inventory_source_case import inventory_source_case


@pytest.mark.parametrize('change', [
    lambda facts: facts['before_values']['category_schema'].update(caller_metadata=True),
    lambda facts: facts['before_values'].update(shop_id='999'),
    lambda facts: facts['before_values'].update(product_query='10002'),
    lambda facts: facts['evidence_observations']['editor_inventory_observation']['command'].update(command_id='other'),
    lambda facts: facts['evidence_observations']['editor_inventory_observation']['command'].update(task_id=999),
])
def test_worker_rejects_self_reported_command_or_full_schema_drift(inventory_source_case, monkeypatch, change):
    case = inventory_source_case
    adapter = case['runtime'].adapter; original = adapter._result

    def altered(*args, **kwargs):
        result = deepcopy(original(*args, **kwargs))
        change(result['contract_facts'])
        return result

    monkeypatch.setattr(adapter, '_result', altered)
    with pytest.raises(RuntimeError, match='actual read-only command'):
        case['runtime'].run(case['command'], timeout_seconds=10)
    with db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0
