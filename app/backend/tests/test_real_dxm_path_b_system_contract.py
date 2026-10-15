"""Focused deterministic contract tests for the real DXM Path B flow.

These tests deliberately stop at pure contracts, temporary SQLite state, and
source invariants.  They never construct or mock the production DXM adapter,
never open a browser, and never treat fixture values as real acceptance proof.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from tests.support.content_authority_case import (
    _scope_facts, _prepared_scope, _approval_facts, _prepared_approval, _shared_required_editor_actions_plan,
)

from src import db
from src.batch_edit.full_product_edit_orchestrator import (
    EditPhase,
    FullProductEditOrchestrator,
    PhaseStatus,
)
from src.batch_edit.plan_snapshot_compiler import RELEASED_PLAN_EXECUTION_PATHS
from src.execution.browser_agent_protocol import (
    BrowserAgentCommand,
    build_mutation_scope_id,
)
from src.execution.canonical_receipt import (
    CanonicalReceipt,
    ContentFinalizeReceipt,
    FieldReadback,
    ReceiptPhase,
    ReceiptValidationError,
    SaveProof,
    SaveProofKind,
    SaveReceipt,
)
from src.execution.controlled_mutation_dispatch import ControlledMutationDispatch
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.v1_runner import SAVE1_TAIL, SAVE2_TAIL
from src.real_dxm_write_scope import (
    REAL_DXM_WRITE_APPROVAL_SCHEMA,
    REAL_DXM_WRITE_SCOPE_SCHEMA,
    RealDxmWriteScopeError,
    canonical_sha256,
    prepare_real_dxm_write_approval,
    prepare_real_dxm_write_scope,
    validate_real_dxm_write_approval,
    validate_real_dxm_write_scope,
)
from src.repository import Repository
from src.services.ownership_lock import ConcurrentEditorGuard
from src.state_machine.contracts import StateName


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = "2026-08-31T00:01:00Z"
ISSUED_AT = "2026-08-31T00:00:00Z"
APPROVED_AT = "2026-08-31T00:00:30Z"
EXPIRES_AT = "2026-08-31T00:10:00Z"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest().upper()
HASH_A = "A" * 64
HASH_B = "B" * 64
HASH_C = "C" * 64
HASH_D = "D" * 64
GIT_HEAD = "1" * 40






def test_save2_freeze_is_deferred_without_inventing_preimages():
    from src.batch_edit.plan_contract import PlanContractError
    from src.batch_edit.plan_snapshot_compiler import PlanSnapshotCompiler

    compiler = PlanSnapshotCompiler(PlanContractError, local_plan_store=None)
    plan = {
        "id": 20, "version": "1.3.0", "path": "B", "status": "ready",
        "shop_id": "91", "category_ids": ["101"],
        "configuration_contract": "local_plan_template.v3",
        "semi_managed": {"enabled": True, "freeze_timing": "after_native_gate"},
        "fixed_values": {"publish_allowed": False, "field_values": {"101": {"semiManagedJitStock": 100}}},
        "fill_rules": {"101": {}}, "source_policies": {"101": {}},
        "dxm_template_refs": [], "editor_actions": {},
    }
    properties = {
        "title": {"type": "string", "ui_section": "basic_info", "ui_binding": "dxm_editor:title"},
        "semiManagedJitStock": {"type": "integer", "ui_section": "semi_managed", "ui_binding": "dxm_editor:semiManagedJitStock"},
    }
    mapping = {"entries": [{"field_key": key, "ui_binding": value["ui_binding"]} for key, value in properties.items()]}
    kwargs = dict(plan=plan, mapping=mapping, properties=properties,
                  current_values={"title": "Before"},
                  resolved_fields=[{"field_key": "title", "resolved_value": "After"}],
                  unresolved_fields=[])
    result = compiler._freeze_real_write_stage_authority(**kwargs)
    assert result["real_write_stage_facts"]["SAVE2"] == []
    policy = result["deferred_save2"]
    assert policy["freeze_timing"] == "after_native_gate"
    assert policy["fields"][0]["rule"] == {"value": 100}
    assert "preimage_sha256" not in policy["fields"][0]
    assert result["real_write_stage_fields"]["SAVE2"] == ["semiManagedJitStock"]
    # A missing SAVE1 preimage still blocks before any write.
    with pytest.raises(PlanContractError, match="preimage"):
        compiler._freeze_real_write_stage_authority(**{**kwargs, "current_values": {}})
    old_plan = deepcopy(plan)
    old_plan["semi_managed"].pop("freeze_timing")
    with pytest.raises(PlanContractError):
        compiler._freeze_real_write_stage_authority(**{**kwargs, "plan": old_plan})


def test_deferred_scope_binds_one_rule_set_and_rejects_early_or_mixed_values():
    facts = _scope_facts()
    facts["schema"] = "real_dxm_write_scope.v2"
    for product in facts["orderedProducts"]:
        product["allowedFields"][1] = {
            "field": "semi_goods", "saveStage": "SAVE2",
            "freezeAt": "after_native_gate", "ruleSha256": HASH_C,
        }
    scope = prepare_real_dxm_write_scope(facts, now=NOW)
    assert validate_real_dxm_write_scope(scope, now=NOW) == scope
    assert "preimageSha256" not in scope["orderedProducts"][0]["allowedFields"][1]
    for mutate in (
        lambda x: x.update(schema="real_dxm_write_scope.v1"),
        lambda x: x["orderedProducts"][0]["allowedFields"][1].update(preimageSha256=HASH_D),
        lambda x: x["orderedProducts"][1]["allowedFields"][1].update(ruleSha256=HASH_D),
        lambda x: x["orderedProducts"][0]["allowedFields"][1].update(saveStage="SAVE1"),
    ):
        bad = deepcopy(facts)
        mutate(bad)
        with pytest.raises(RealDxmWriteScopeError):
            prepare_real_dxm_write_scope(bad, now=NOW)


def test_late_save2_payload_uses_persisted_observation_and_the_same_shared_rules(contract_db):
    from src.batch_edit.plan_contract import PlanContractError
    from src.batch_edit.plan_snapshot_compiler import PlanSnapshotCompiler
    from src.batch_edit.frozen_execution_contract import (
        FrozenExecutionContractError, build_save2_stage_freeze, compile_frozen_execution_payload,
        frozen_scope_field_bindings, load_save2_stage_freezes, validated_save2_stage_freeze,
    )
    plan = {
        "id": 20, "version": "1.3.0", "path": "B", "status": "ready", "shop_id": "91",
        "category_ids": ["101"], "configuration_contract": "local_plan_template.v3",
        "semi_managed": {"enabled": True, "freeze_timing": "after_native_gate"},
        "fixed_values": {"publish_allowed": False, "field_values": {"101": {"semiManagedJitStock": 100}}},
        "fill_rules": {"101": {}}, "source_policies": {"101": {"semiManagedCode": "current"}},
        "dxm_template_refs": [], "editor_actions": {},
    }
    properties = {key: {"type": kind, "ui_binding": f"dxm_editor:{key}",
                        "ui_section": "basic_info" if key == "title" else "semi_managed"}
                  for key, kind in (("title", "string"), ("semiManagedJitStock", "integer"), ("semiManagedCode", "string"))}
    schema = {"type": "object", "properties": properties, "required": []}
    mapping = {"mapping_version": "contract.v1", "entries": [
        {"field_key": key, "ui_binding": value["ui_binding"], "ui_label_zh": key,
         "category_schema_path": f"$.properties.{key}"} for key, value in properties.items()]}
    mapping["mapping_hash"] = canonical_sha256(mapping)
    resolved = [{"field_key": "title", "resolved_value": "Shared title"}]
    authority = PlanSnapshotCompiler(PlanContractError, local_plan_store=None)._freeze_real_write_stage_authority(
        plan=plan, mapping=mapping, properties=properties, current_values={"title": "Before"},
        resolved_fields=resolved, unresolved_fields=[],
    )
    resolution = {"resolved_fields": resolved, "unresolved_fields": [], "price_validation": {}}
    item = {"product_id": "8101", "shop_id": "91", "categoryId": "101", "target_identity_sha256": HASH_A,
            "category_schema": {"normalized_schema": schema, "schema_hash": canonical_sha256(schema)},
            "field_mapping": mapping, "current_value_snapshot": {"title": "Before"},
            "resolution_result": {**resolution, "resolution_hash": canonical_sha256(resolution)}, **authority}
    task = {"id": 701, "payload": {"plan_snapshot": {"snapshot_hash": HASH_B, "item_snapshots": [item]},
                                  "real_dxm_write_authorization": {"scope_sha256": HASH_C}}}
    job = {"id": 801, "product_id": 8101}
    assert [field["field_key"] for field in compile_frozen_execution_payload(task, job)["fields"]] == ["title"]
    with pytest.raises(FrozenExecutionContractError, match="persisted stage freeze"):
        compile_frozen_execution_payload(task, job, save_stage="SAVE2")
    gate = {"gate_outcome": "admitted", "same_handshake": True, "semi_entry_triggered": True,
            "handshake_id": "contract-entry", "blocked": False}
    observation = {
        "product_id": "8101", "shop_id": "91", "target_identity_sha256": HASH_A,
        "page_url": "https://www.dianxiaomi.com/web/smt/editFromSmt?id=8101",
        "browser_session_id": "contract-session", "observed_at": NOW, "write_attempted": False,
        "values": {"semiManagedJitStock": 17, "semiManagedCode": "native-code"},
        "bindings": {key: properties[key]["ui_binding"] for key in ("semiManagedJitStock", "semiManagedCode")},
        "evidence_ref": {"path": "C:/contract/observation.png", "sha256": HASH_D, "size": 100},
    }
    seal = build_save2_stage_freeze(task, job, observation=observation, gate=gate, save1_receipt_sha256=HASH_D)
    parent_before = deepcopy(task["payload"]["plan_snapshot"])
    # Only a private persisted record reaches compilation, never a command body.
    with db.connection() as conn:
        conn.execute("INSERT INTO job_evidences(task_id,job_id,evidence_type,meta_json,created_at) VALUES(?,?,'path_b_save2_freeze',?,?)",
                     (701, 801, db.dumps(seal), NOW))
        task["_save2_freezes"] = load_save2_stage_freezes(conn, 701)
    late = compile_frozen_execution_payload(task, job, save_stage="SAVE2")
    assert {field["field_key"]: field["resolved_value"] for field in late["fields"]} == {
        "semiManagedJitStock": 100, "semiManagedCode": "native-code"}
    assert task["payload"]["plan_snapshot"] == parent_before
    bindings = frozen_scope_field_bindings(item, stage_freeze=validated_save2_stage_freeze(task, job))
    assert bindings[1]["preimageSha256"] == canonical_sha256(17)
    assert bindings[1]["expectedSha256"] == canonical_sha256(100)
    for mutate in (
        lambda x: x["_save2_freezes"]["801"]["fields"][0].update(resolved_value=999),
        lambda x: x["_save2_freezes"]["801"]["gate"].update(gate_outcome="blocked"),
        lambda x: x["_save2_freezes"]["801"]["observation"]["values"].pop("semiManagedJitStock"),
        lambda x: x["_save2_freezes"]["801"]["observation"].update(product_id="8102"),
    ):
        bad = deepcopy(task)
        mutate(bad)
        with pytest.raises(FrozenExecutionContractError):
            compile_frozen_execution_payload(bad, job, save_stage="SAVE2")
    with db.connection() as conn:
        conn.execute("INSERT INTO job_evidences(task_id,job_id,evidence_type,meta_json,created_at) VALUES(?,?,'path_b_save2_freeze',?,?)",
                     (701, 801, db.dumps(seal), NOW))
        with pytest.raises(FrozenExecutionContractError, match="multiple stage freezes"):
            load_save2_stage_freezes(conn, 701)


def test_deferred_prepare_model_and_schema_keep_exact_stage_shapes():
    from pydantic import ValidationError
    from src.models import RealDxmPathBFieldHashBinding

    deferred = {'field': 'stock', 'saveStage': 'SAVE2', 'freezeAt': 'after_native_gate', 'ruleSha256': HASH_A}
    assert RealDxmPathBFieldHashBinding(**deferred).model_dump(exclude_none=True) == deferred
    early = {'field': 'title', 'saveStage': 'SAVE1', 'preimageSha256': HASH_B, 'expectedSha256': HASH_C}
    assert RealDxmPathBFieldHashBinding(**early).model_dump(exclude_none=True) == early
    for invalid in ({**deferred, 'saveStage': 'SAVE1'}, {**deferred, 'preimageSha256': None},
                    {**deferred, 'expectedSha256': HASH_D}, {**early, 'preimageSha256': None},
                    {**deferred, 'freezeAt': 'before_native_gate'}):
        with pytest.raises(ValidationError):
            RealDxmPathBFieldHashBinding(**invalid)
    schema = json.loads((REPO_ROOT / 'config/real_dxm_write_scope.schema.json').read_text(encoding='utf-8'))
    late = schema['$defs']['deferredSave2Field']
    assert set(late['required']) == set(deferred) == set(late['properties'])
    assert late['additionalProperties'] is False
    conditional = schema['$defs']['writeScope']['allOf'][0]
    assert conditional['if']['properties']['schema']['const'] == 'real_dxm_write_scope.v1'
    assert conditional['then']['properties']['orderedProducts']['items']['properties']['allowedFields']['items']['$ref'] == '#/$defs/allowedField'
    assert conditional['else']['properties']['orderedProducts']['items']['properties']['allowedFields']['items']['then']['$ref'] == '#/$defs/deferredSave2Field'


def test_save2_runtime_origin_rejects_drift_and_preserves_observed_empty_values():
    from src.batch_edit.frozen_execution_contract import FrozenExecutionContractError, validate_save2_runtime_origin

    url = 'https://www.dianxiaomi.com/web/smt/editFromSmt?id=8101'
    body = {'save_stage': 'SAVE2', 'product_id': '8101', 'stage_freeze_sha256': HASH_B,
            'fields': [{'field_key': 'code', 'ui_binding': 'dxm_editor:code', 'resolved_value': ''}],
            'stage_preimage': {'product_id': '8101', 'page_url': url, 'browser_session_id': 'same-session',
                               'values': {'code': ''}, 'bindings': {'code': 'dxm_editor:code'}, 'write_attempted': False}}
    payload = {**body, 'payload_hash': canonical_sha256(body)}
    validate_save2_runtime_origin(payload, page_url=url, browser_session_id='same-session')
    assert payload['stage_preimage']['values'] == {'code': ''}
    for other_url, other_session in ((url.replace('8101', '8102'), 'same-session'),
                                      (url.replace('editFromSmt', 'edit'), 'same-session'), (url, 'new-session')):
        with pytest.raises(FrozenExecutionContractError):
            validate_save2_runtime_origin(payload, page_url=other_url, browser_session_id=other_session)
    for mutate in (lambda x: x['stage_preimage']['values'].clear(),
                   lambda x: x['stage_preimage'].update(write_attempted=True),
                   lambda x: x['fields'][0].update(resolved_value='caller override')):
        bad = deepcopy(payload)
        mutate(bad)
        with pytest.raises(FrozenExecutionContractError):
            validate_save2_runtime_origin(bad, page_url=url, browser_session_id='same-session')


def test_save2_persisted_lineage_requires_unchanged_save1_and_session(contract_db):
    from src.batch_edit.frozen_execution_contract import (
        FrozenExecutionContractError, build_save2_stage_freeze, validate_save2_persistence,
    )
    field = {'field_key': 'stock', 'ui_binding': 'dxm_editor:stock', 'ui_label_zh': '库存',
             'property_schema': {'type': 'integer', 'ui_section': 'semi_managed', 'ui_binding': 'dxm_editor:stock'},
             'rule': {'value': 100}}
    policy = {'schema': 'dxm.deferred_save2_policy.v1', 'freeze_timing': 'after_native_gate',
              'source_sha256': HASH_A, 'fields': [field]}
    item = {'product_id': '8101', 'shop_id': '91', 'target_identity_sha256': HASH_B,
            'real_write_stage_fields': {'SAVE2': ['stock']},
            'deferred_save2': {**policy, 'policy_sha256': canonical_sha256(policy)}}
    task = {'id': 701, 'payload': {'plan_snapshot': {'snapshot_hash': HASH_A, 'item_snapshots': [item]},
                                 'real_dxm_write_authorization': {'scope_sha256': HASH_C}}}
    job = {'id': 801, 'product_id': 8101}
    gate = {'gate_outcome': 'admitted', 'same_handshake': True, 'semi_entry_triggered': True,
            'handshake_id': 'unit-native-gate', 'blocked': False}
    observation = {'product_id': '8101', 'shop_id': '91', 'browser_session_id': 'unit-session',
                   'page_url': 'https://www.dianxiaomi.com/web/smt/editFromSmt?id=8101',
                   'target_identity_sha256': HASH_B, 'observed_at': NOW,
                   'values': {'stock': 17}, 'bindings': {'stock': 'dxm_editor:stock'},
                   'write_attempted': False, 'evidence_ref': {'path': 'unit-only.png'}}
    # This synthetic row tests lineage comparison only, never receipt acceptance.
    source = {'receipt_kind': 'save_stage', 'save_stage': 'SAVE1', 'task_id': 701, 'job_id': 801}
    digest = canonical_sha256(source)
    source['canonical_receipt_sha256'] = digest
    seal = build_save2_stage_freeze(task, job, observation=observation, gate=gate, save1_receipt_sha256=digest)
    task['_save2_freezes'] = {'801': seal}
    with db.connection() as conn:
        with pytest.raises(FrozenExecutionContractError):
            validate_save2_persistence(conn, task, job, browser_session_id='unit-session')
        conn.execute("INSERT INTO canonical_receipts(task_id,job_id,product_id,receipt_kind,save_stage,mode,claim_mark,started_at,scope_sha256,canonical_receipt_sha256,receipt_json,created_at,updated_at) VALUES(701,801,8101,'save_stage','SAVE1','batch_draft_save','unit-only','2026-09-07T00:00:00Z',?,?,?,?,?)",
                     (HASH_C, digest, db.dumps(source), NOW, NOW))
        assert validate_save2_persistence(conn, task, job, browser_session_id='unit-session') == seal
        with pytest.raises(FrozenExecutionContractError):
            validate_save2_persistence(conn, task, job, browser_session_id='other-session')
        source['job_id'] = 999
        conn.execute("UPDATE canonical_receipts SET receipt_json=? WHERE task_id=701", (db.dumps(source),))
        with pytest.raises(FrozenExecutionContractError):
            validate_save2_persistence(conn, task, job, browser_session_id='unit-session')


def test_late_save2_uses_shared_executor_and_checks_the_seal_before_dispatch():
    from textwrap import dedent
    from src.execution.dxm_login_flow import DxmLoginFlow
    from src.execution.action_result_contract import _validate_save_success_semantics
    from src.repository import Repository
    from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload
    from src.execution.batch_dispatch_authority import validate_current_task_against_frozen_authority

    semi_source = inspect.getsource(DxmLoginFlow._fill_semi_managed_defaults_on_page)
    assert semi_source.index('_prepare_frozen_execution_page_for_save') < semi_source.index('_missing_explicit_template_defaults')
    source = inspect.getsource(DxmLoginFlow._prepare_frozen_execution_page_for_save)
    assert source.index('SAVE2_PREIMAGE_DRIFT_BEFORE_FIRST_WRITE') < source.index('fill_result = self._fill_frozen_execution_payload_on_page')
    assert 'SAVE2_PREFILL_ALREADY_ATTEMPTED' in source and 'SAVE2_PREFILL_READBACK_DRIFT' in source
    assert 'stage_preimage=deepcopy(seal["observation"])' in inspect.getsource(compile_frozen_execution_payload)
    repository = inspect.getsource(Repository.freeze_save2_before_first_write)
    assert repository.index('_build_canonical_save_stage_receipt') < repository.index('INSERT INTO job_evidences')
    assert 'SAVE2_FREEZE_SHARED_SCOPE_RULE_DRIFT' in repository
    assert 'validate_save2_persistence' in inspect.getsource(validate_current_task_against_frozen_authority)
    semantics = inspect.getsource(_validate_save_success_semantics)
    assert 'SAVE2 readback must bind the persisted late freeze' in semantics
    observer = inspect.getsource(DxmLoginFlow.observe_save2_before_first_write)
    tree = ast.parse(dedent(observer))
    assert not any(_call_name(node) in {'goto', 'click', '_goto_with_live_hud'} for node in ast.walk(tree) if isinstance(node, ast.Call))






@pytest.fixture()
def contract_db(tmp_path, monkeypatch):
    db_path = tmp_path / "real-path-b-contract.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return db_path


def _insert_draft_batch_task(task_id: int) -> None:
    with db.connection() as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                id, name, store_id, status, mode, publish_scene,
                total_jobs, completed_jobs, failed_jobs, payload_json,
                created_at, updated_at
            ) VALUES (?, 'Path B contract task', 91, 'draft',
                      'batch_draft_save', 'draft_only', 3, 0, 0,
                      '{}', ?, ?)
            """,
            (task_id, ISSUED_AT, ISSUED_AT),
        )


def _verified_section_receipt(seed: str = "a") -> dict:
    return {
        "success": True,
        "readback_proven": True,
        "receipt_sha256": seed * 64,
    }


def _sha(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _field_readback(phase: str, timestamp: str) -> FieldReadback:
    return FieldReadback(
        field_key=f"{phase}_field",
        field_label=f"{phase} field",
        source="visible_production_runtime",
        before_value=f"{phase}-before",
        after_value=f"{phase}-expected",
        readback_proven=True,
        timestamp=timestamp,
    )


def _save_proofs(
    *,
    label: str,
    page_kind: str,
    request_at: str,
    response_at: str,
    screenshot_at: str,
    unpublished_at: str,
    target_hash: str,
) -> dict[SaveProofKind, SaveProof]:
    url = f"https://contract.invalid/{label}/save"
    common = {
        "file_path": None,
        "network_url": None,
        "network_method": None,
        "network_status": None,
        "body_sha256": None,
        "timestamp": None,
        "proven": True,
        "source": "visible_production_runtime",
        "target_hash": target_hash,
    }
    return {
        SaveProofKind.NETWORK_REQUEST: SaveProof(
            proof_kind=SaveProofKind.NETWORK_REQUEST,
            **(
                common
                | {
                    "network_url": url,
                    "network_method": "POST",
                    "body_sha256": _sha(f"{label}-request"),
                    "timestamp": request_at,
                    "evidence_id": f"{label}-network-request",
                }
            ),
        ),
        SaveProofKind.NETWORK_RESPONSE: SaveProof(
            proof_kind=SaveProofKind.NETWORK_RESPONSE,
            **(
                common
                | {
                    "network_url": url,
                    "network_method": "POST",
                    "network_status": 200,
                    "body_sha256": _sha(f"{label}-response"),
                    "timestamp": response_at,
                    "evidence_id": f"{label}-network-response",
                    "business_success": True,
                    "business_code": 0,
                    "business_message": "success",
                }
            ),
        ),
        SaveProofKind.PAGE_SUCCESS_SCREENSHOT: SaveProof(
            proof_kind=SaveProofKind.PAGE_SUCCESS_SCREENSHOT,
            **(
                common
                | {
                    "file_path": f"/contract-evidence/{label}.png",
                    "body_sha256": _sha(f"{label}-screenshot"),
                    "timestamp": screenshot_at,
                    "evidence_id": f"{label}-page-success",
                    "page_kind": page_kind,
                    "page_success": True,
                }
            ),
        ),
        SaveProofKind.UNPUBLISHED_STATUS: SaveProof(
            proof_kind=SaveProofKind.UNPUBLISHED_STATUS,
            **(
                common
                | {
                    "body_sha256": _sha(f"{label}-unpublished"),
                    "timestamp": unpublished_at,
                    "evidence_id": f"{label}-unpublished",
                    "unpublished": True,
                    "independent": True,
                }
            ),
        ),
    }


def _save_receipt(
    phase: ReceiptPhase,
    *,
    label: str,
    page_kind: str,
    ledger_entry_id: int,
    dispatched_at: str,
    completed_at: str,
    readback_at: str,
) -> SaveReceipt:
    target_hash = _sha("one-frozen-product-target")
    second = label == "save2"
    proofs = _save_proofs(
        label=label,
        page_kind=page_kind,
        request_at="2026-08-31T00:00:31Z" if second else "2026-08-31T00:00:11Z",
        response_at="2026-08-31T00:00:32Z" if second else "2026-08-31T00:00:12Z",
        screenshot_at="2026-08-31T00:00:33Z" if second else "2026-08-31T00:00:13Z",
        unpublished_at="2026-08-31T00:00:34Z" if second else "2026-08-31T00:00:14Z",
        target_hash=target_hash,
    )
    return SaveReceipt(
        save_phase=phase,
        save_lease_id=f"{label}-lease",
        action_grant_id=f"{label}-action-grant",
        mutation_id=f"{label}-mutation",
        ledger_entry_id=ledger_entry_id,
        target_hash=target_hash,
        dispatched_at=dispatched_at,
        completed_at=completed_at,
        physical_mutation_count=1,
        publish_request_count=0,
        published=False,
        proofs=proofs,
        field_readbacks=[_field_readback(label, readback_at)],
        save_result_ok=True,
        unresolved=False,
    )


def _canonical_receipt() -> CanonicalReceipt:
    receipt = CanonicalReceipt(
        task_id=701,
        job_id=801,
        product_id=8101,
        mode="batch_draft_save",
        claim_mark="path-b-contract-product-8101",
        started_at="2026-08-31T00:00:00Z",
        completed_at="2026-08-31T00:01:00Z",
    )
    for phase in (
        ReceiptPhase.CONTENT_FINALIZE_WHOLESALE,
        ReceiptPhase.CONTENT_FINALIZE_VIDEO,
        ReceiptPhase.CONTENT_FINALIZE_TRANSLATION,
        ReceiptPhase.SEMI_MANAGED_ENTRY,
        ReceiptPhase.ROLLBACK_PREPARATION,
    ):
        receipt.add_content_finalize_receipt(
            ContentFinalizeReceipt(
                phase=phase,
                action_grant_id=f"grant-{phase.value}",
                result_ok=True,
                unresolved=False,
                media_identity=(
                    "video-media-contract"
                    if phase == ReceiptPhase.CONTENT_FINALIZE_VIDEO
                    else None
                ),
            )
        )
    receipt.mark_rollback_prepared(_sha("rollback-preimage"))
    receipt.add_save_receipt(
        _save_receipt(
            ReceiptPhase.PHASE_1_FIRST_SAVE,
            label="save1",
            page_kind="editor",
            ledger_entry_id=1,
            dispatched_at="2026-08-31T00:00:10Z",
            completed_at="2026-08-31T00:00:20Z",
            readback_at="2026-08-31T00:00:15Z",
        )
    )
    receipt.add_save_receipt(
        _save_receipt(
            ReceiptPhase.PHASE_2_SECOND_SAVE,
            label="save2",
            page_kind="semi_managed",
            ledger_entry_id=2,
            dispatched_at="2026-08-31T00:00:30Z",
            completed_at="2026-08-31T00:00:40Z",
            readback_at="2026-08-31T00:00:35Z",
        )
    )
    receipt.mark_succeeded()
    return receipt


def _mutation_command() -> BrowserAgentCommand:
    values = {
        "command_id": "contract-command-1",
        "idempotency_key": "contract-idempotency-1",
        "deadline": "2099-01-01T00:00:00+00:00",
        "expected_page": "semi_managed",
        "runtime_id": "contract-runtime-1",
        "task_id": 11,
        "job_id": 22,
        "state": "SAVE_ONLY",
        "action": "save_only",
        "execution_mode": "single_save",
        "params": {},
        "authorization_lease_id": "contract-save-lease-1",
        "stage_task_facts_fingerprint": HASH_A,
        "target_hash": HASH_B,
        "authorization_fingerprint": HASH_C,
    }
    return BrowserAgentCommand(
        **values,
        mutation_scope_id=build_mutation_scope_id(
            authorization_lease_id=values["authorization_lease_id"],
            task_id=values["task_id"],
            job_id=values["job_id"],
            state=values["state"],
            action=values["action"],
        ),
    )


def test_scope_exact_keys_schema_digest_and_order_are_frozen() -> None:
    scope = _prepared_scope()
    unsigned = {key: value for key, value in scope.items() if key != "scopeSha256"}
    schema = json.loads(
        (REPO_ROOT / "config" / "real_dxm_write_scope.schema.json").read_text(
            encoding="utf-8"
        )
    )
    scope_schema = schema["$defs"]["writeScope"]

    assert set(scope) == set(scope_schema["required"])
    assert scope_schema["additionalProperties"] is False
    assert scope["scopeSha256"] == canonical_sha256(unsigned)
    assert validate_real_dxm_write_scope(scope, now=NOW) == scope
    assert [item["productId"] for item in scope["orderedProducts"]] == [8101, 8102, 8103]
    assert all(
        [save["stage"] for save in item["saves"]] == ["SAVE1", "SAVE2"]
        for item in scope["orderedProducts"]
    )


@pytest.mark.parametrize(
    ("mutate", "detail_code"),
    [
        (
            lambda value: value.__setitem__("unexpected", True),
            "EXACT_KEYS_MISMATCH",
        ),
        (
            lambda value: value["orderedProducts"][0].__setitem__("productId", 9999),
            "SCOPE_HASH_MISMATCH",
        ),
        (
            lambda value: value["orderedProducts"][0].__setitem__("ordinal", 2),
            "PRODUCT_ORDER_INVALID",
        ),
        (
            lambda value: value["worktree"].__setitem__("git_head", "2" * 40),
            "WORKTREE_HEAD_MISMATCH",
        ),
    ],
)
def test_scope_rejects_tamper_order_or_identity_drift(mutate, detail_code: str) -> None:
    scope = _prepared_scope()
    mutate(scope)

    with pytest.raises(RealDxmWriteScopeError) as raised:
        validate_real_dxm_write_scope(scope, now=NOW)

    assert raised.value.reason_code == "SCOPE_REJECTED"
    assert raised.value.detail_code == detail_code


def test_scope_rejects_expiry_wildcard_and_publish_intent() -> None:
    with pytest.raises(RealDxmWriteScopeError) as expired:
        validate_real_dxm_write_scope(
            _prepared_scope(),
            now="2026-08-31T00:10:00Z",
        )
    assert expired.value.detail_code == "SCOPE_EXPIRED"

    wildcard = _scope_facts()
    wildcard["orderedProducts"][0]["allowedFields"][0]["field"] = "*"
    with pytest.raises(RealDxmWriteScopeError) as wildcard_rejected:
        prepare_real_dxm_write_scope(wildcard, now=NOW)
    assert wildcard_rejected.value.detail_code == "WILDCARD_FORBIDDEN"

    publishing = _scope_facts()
    publishing["publishAllowed"] = True
    with pytest.raises(RealDxmWriteScopeError) as publish_rejected:
        prepare_real_dxm_write_scope(publishing, now=NOW)
    assert publish_rejected.value.detail_code == "PUBLISH_INTENT_FORBIDDEN"

    publish_field = _scope_facts()
    publish_field["orderedProducts"][0]["allowedFields"][0]["field"] = "publishNow"
    with pytest.raises(RealDxmWriteScopeError) as field_rejected:
        prepare_real_dxm_write_scope(publish_field, now=NOW)
    assert field_rejected.value.detail_code == "PUBLISH_FIELD_FORBIDDEN"


def test_scope_rejection_has_zero_mutation_side_effect(contract_db) -> None:
    tampered = _prepared_scope()
    tampered["orderedProducts"][0]["productId"] = 9999
    wildcard = _scope_facts()
    wildcard["orderedProducts"][0]["allowedFields"][0]["field"] = "*"
    rejected_calls = (
        lambda: validate_real_dxm_write_scope(tampered, now=NOW),
        lambda: validate_real_dxm_write_scope(
            _prepared_scope(), now="2026-08-31T00:10:00Z"
        ),
        lambda: prepare_real_dxm_write_scope(wildcard, now=NOW),
    )
    for rejected_call in rejected_calls:
        with pytest.raises(RealDxmWriteScopeError) as rejected:
            rejected_call()
        assert rejected.value.reason_code == "SCOPE_REJECTED"

    with db.connection() as conn:
        mutation_count = conn.execute(
            "SELECT COUNT(*) AS count FROM mutation_dispatch_ledger"
        ).fetchone()["count"]
    assert mutation_count == 0


def test_approval_is_bound_to_exact_scope_nonce_and_hash() -> None:
    scope = _prepared_scope()
    approval = _prepared_approval(scope)
    schema = json.loads(
        (REPO_ROOT / "config" / "real_dxm_write_scope.schema.json").read_text(
            encoding="utf-8"
        )
    )["$defs"]["writeApproval"]

    assert set(approval) == set(schema["required"])
    assert schema["additionalProperties"] is False
    assert validate_real_dxm_write_approval(approval, scope=scope, now=NOW) == approval

    other_scope = deepcopy(approval)
    other_scope["scopeSha256"] = HASH_D
    with pytest.raises(RealDxmWriteScopeError) as wrong_scope:
        validate_real_dxm_write_approval(other_scope, scope=scope, now=NOW)
    assert wrong_scope.value.detail_code == "APPROVAL_SCOPE_HASH_MISMATCH"

    other_nonce = deepcopy(approval)
    other_nonce["nonce"] = "scope-nonce-00000002"
    with pytest.raises(RealDxmWriteScopeError) as wrong_nonce:
        validate_real_dxm_write_approval(other_nonce, scope=scope, now=NOW)
    assert wrong_nonce.value.detail_code == "APPROVAL_NONCE_MISMATCH"

    tampered_approver = deepcopy(approval)
    tampered_approver["approvedBy"] = "different-operator"
    with pytest.raises(RealDxmWriteScopeError) as wrong_approval_hash:
        validate_real_dxm_write_approval(tampered_approver, scope=scope, now=NOW)
    assert wrong_approval_hash.value.detail_code == "APPROVAL_HASH_MISMATCH"


def test_approval_consume_is_atomic_single_use_and_derives_six_leases(contract_db) -> None:
    task_id = 701
    _insert_draft_batch_task(task_id)
    scope = _prepared_scope(task_id=task_id)
    approval = _prepared_approval(scope)
    repository = Repository()
    assert repository.prepare_real_dxm_write_scope(scope)["ok"] is True

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _index: repository.consume_real_dxm_write_approval(
                    scope=scope,
                    approval=approval,
                ),
                range(2),
            )
        )

    accepted = [result for result in results if result["ok"] is True]
    rejected = [result for result in results if result["ok"] is False]
    assert len(accepted) == 1
    assert len(rejected) == 1
    assert rejected[0]["reason_code"] == "SCOPE_REJECTED"
    assert rejected[0]["detail_code"] in {
        "APPROVAL_REPLAY",
        "SCOPE_NOT_PREPARED_OR_CONSUMED",
    }
    leases = accepted[0]["save_leases"]
    assert len(leases) == 6
    assert len({item["lease_id"] for item in leases}) == 6
    assert [item["save_stage"] for item in leases] == ["SAVE1", "SAVE2"] * 3
    assert all(item["single_use"] is True for item in leases)

    persisted = repository.get_real_dxm_write_scope(scope["scopeSha256"])
    assert persisted is not None
    assert persisted["status"] == "consumed"
    with db.connection() as conn:
        task_payload = db.loads(
            conn.execute("SELECT payload_json FROM tasks WHERE id=?", (task_id,)).fetchone()[
                "payload_json"
            ],
            {},
        )
    bound = task_payload["real_dxm_write_authorization"]
    assert bound["publish_allowed"] is False
    assert bound["ordered_product_ids"] == [8101, 8102, 8103]
    assert bound["save_leases"] == leases


def test_writer_fence_is_shop_scoped_and_release_invalidates_owner(contract_db) -> None:
    guard = ConcurrentEditorGuard()
    first = guard.acquire_writer_fence("91", "task-701", generation=0)
    conflict = guard.acquire_writer_fence("91", "task-702", generation=0)

    assert first["acquired"] is True
    assert conflict == {
        "acquired": False,
        "conflict": True,
        "writer_fence_id": first["writer_fence_id"],
        "shop_id": "91",
        "task_id": "task-702",
        "generation": 0,
        "status": "conflict",
        "reason": "shop_writer_fence_held_by_other_task",
    }
    released = guard.release_writer_fence(first["writer_fence_id"], generation=0)
    assert released["status"] == "released"
    assert guard.validate_writer_fence("91", "task-701")["acquired"] is False
    assert guard.acquire_writer_fence("91", "task-702", generation=0)["acquired"] is True


def test_orchestrator_blocks_missing_failed_readback_or_receipt() -> None:
    from tests.support.path_b_receipts import section_receipt, capability_receipt
    orchestrator = FullProductEditOrchestrator()
    required = (
        *orchestrator.MAIN_SECTIONS,
        *orchestrator.CONTENT_FINALIZE_CAPABILITIES,
    )

    missing_ctx = orchestrator.create_context("8101", "91")
    missing = orchestrator.execute_phase(missing_ctx, EditPhase.PHASE_MAIN_EDIT, {})
    assert missing.status == PhaseStatus.BLOCKED
    assert missing.execute_receipt["missing_sections"] == list(required)

    for field_name, bad_value in (
        ("success", False),
        ("readback_proven", False),
        ("receipt_sha256", "not-a-receipt-hash"),
    ):
        results = {name: section_receipt(name) for name in orchestrator.MAIN_SECTIONS}
        results.update({name: capability_receipt(name) for name in orchestrator.CONTENT_FINALIZE_CAPABILITIES})
        complete = orchestrator.execute_phase(orchestrator.create_context("8101", "91"),
                                               EditPhase.PHASE_MAIN_EDIT, deepcopy(results))
        assert complete.status == PhaseStatus.COMPLETED
        results[required[0]][field_name] = bad_value
        ctx = orchestrator.create_context("8101", "91")
        blocked = orchestrator.execute_phase(ctx, EditPhase.PHASE_MAIN_EDIT, results)
        assert blocked.status == PhaseStatus.BLOCKED
        assert blocked.execute_receipt["failed_sections"] == [required[0]]


def test_orchestrator_requires_verified_native_gate_and_all_semi_sections() -> None:
    orchestrator = FullProductEditOrchestrator()
    modal_ctx = orchestrator.create_context("8101", "91")
    blocked = orchestrator.execute_phase(
        modal_ctx,
        EditPhase.PHASE_SAVE_MODAL,
        {
            "save_modal": {
                "save1_verified": True,
                "gate_outcome": "admitted",
                "semi_entry_triggered": True,
                "handshake_id": "handshake-1",
                "same_handshake": False,
            }
        },
    )
    assert blocked.status == PhaseStatus.BLOCKED

    semi_ctx = orchestrator.create_context("8101", "91")
    semi_results = {
        name: _verified_section_receipt("b") for name in orchestrator.SEMI_SECTIONS
    }
    semi_results.pop(orchestrator.SEMI_SECTIONS[-1])
    semi = orchestrator.execute_phase(semi_ctx, EditPhase.PHASE_SEMI_EDIT, semi_results)
    assert semi.status == PhaseStatus.BLOCKED
    assert semi.execute_receipt["missing_sections"] == [orchestrator.SEMI_SECTIONS[-1]]


def test_controlled_dispatch_delegates_to_one_ledger_and_cas_rejects_second_dispatch(
    contract_db,
) -> None:
    authority = MutationDispatchLedger(recover_inflight=False)
    dispatcher = ControlledMutationDispatch(ledger=authority, recover_inflight=False)
    command = _mutation_command()

    assert dispatcher.ledger is authority
    assert dispatcher.reserve_command(command).ok is True
    first = dispatcher.begin_dispatch(command, "save_only_click")
    duplicate = dispatcher.begin_dispatch(command, "save_only_click")

    assert first.ok is True
    assert duplicate.ok is False
    assert duplicate.reason_code == "MUTATION_ALREADY_DISPATCHING"
    source = inspect.getsource(ControlledMutationDispatch).casefold()
    assert "insert into" not in source
    assert "update mutation_dispatch_ledger" not in source
    assert "delete from" not in source
    main_source = (BACKEND_ROOT / "src" / "main.py").read_text(encoding="utf-8")
    assert "ControlledMutationDispatch(" in main_source


def test_canonical_receipt_requires_two_independent_single_mutation_save_phases() -> None:
    receipt = _canonical_receipt()
    digest = receipt.finalize()

    assert len(digest) == 64
    assert len(receipt.content_finalize_receipts) == 5
    assert [item.save_phase for item in receipt.save_receipts] == [
        ReceiptPhase.PHASE_1_FIRST_SAVE,
        ReceiptPhase.PHASE_2_SECOND_SAVE,
    ]
    assert [item.physical_mutation_count for item in receipt.save_receipts] == [1, 1]
    assert [item.publish_request_count for item in receipt.save_receipts] == [0, 0]
    assert [item.published for item in receipt.save_receipts] == [False, False]
    assert [
        item.proofs[SaveProofKind.PAGE_SUCCESS_SCREENSHOT].page_kind
        for item in receipt.save_receipts
    ] == ["editor", "semi_managed"]
    assert receipt.save_receipts[0].evidence_identities().isdisjoint(
        receipt.save_receipts[1].evidence_identities()
    )
    persisted_saves = receipt.save_receipt_dicts()
    assert len(persisted_saves) == 2
    assert len({item["canonical_save_receipt_sha256"] for item in persisted_saves}) == 2


@pytest.mark.parametrize(
    ("mutate", "reason_code"),
    [
        (
            lambda receipt: setattr(
                receipt.save_receipts[0].proofs[SaveProofKind.NETWORK_RESPONSE],
                "business_success",
                False,
            ),
            "SAVE_BUSINESS_SUCCESS_NOT_PROVEN",
        ),
        (
            lambda receipt: setattr(
                receipt.save_receipts[0], "physical_mutation_count", 2
            ),
            "SAVE_PHYSICAL_MUTATION_COUNT_INVALID",
        ),
        (
            lambda receipt: setattr(receipt.save_receipts[0], "publish_request_count", 1),
            "SAVE_PUBLISH_NOT_PROVEN_ABSENT",
        ),
        (
            lambda receipt: setattr(
                receipt.save_receipts[1].proofs[SaveProofKind.PAGE_SUCCESS_SCREENSHOT],
                "page_kind",
                "editor",
            ),
            "SAVE_PAGE_KIND_MISMATCH",
        ),
    ],
)
def test_canonical_receipt_rejects_missing_business_proof_duplicate_write_or_publish(
    mutate,
    reason_code: str,
) -> None:
    receipt = _canonical_receipt()
    mutate(receipt)

    with pytest.raises(ReceiptValidationError) as raised:
        receipt.finalize()

    assert raised.value.reason_code == reason_code


def test_canonical_receipt_rejects_missing_or_reused_save_evidence() -> None:
    missing = _canonical_receipt()
    missing.save_receipts[0].proofs.pop(SaveProofKind.NETWORK_RESPONSE)
    with pytest.raises(ReceiptValidationError) as missing_proof:
        missing.finalize()
    assert missing_proof.value.reason_code == "SAVE_PROOF_REQUIRED"

    reused = _canonical_receipt()
    first_proofs = reused.save_receipts[0].proofs
    second_proofs = reused.save_receipts[1].proofs
    for kind in second_proofs:
        second_proofs[kind].evidence_id = first_proofs[kind].evidence_id
    with pytest.raises(ReceiptValidationError) as reused_proof:
        reused.finalize()
    assert reused_proof.value.reason_code == "SAVE_PHASE_EVIDENCE_REUSED"


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_runner_has_one_authority_context_lifetime_and_distinct_save_phases() -> None:
    source_files = list((BACKEND_ROOT / "src").rglob("*.py"))
    runner_calls = 0
    for path in source_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        runner_calls += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _call_name(node) == "V1TaskRunner"
        )
    assert runner_calls == 1

    runner_path = BACKEND_ROOT / "src" / "execution" / "v1_runner.py"
    runner_tree = ast.parse(runner_path.read_text(encoding="utf-8"), filename=str(runner_path))
    run_job = next(
        node
        for node in ast.walk(runner_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_job"
    )
    create_context_calls = [
        node
        for node in ast.walk(run_job)
        if isinstance(node, ast.Call) and _call_name(node) == "create_context"
    ]
    state_loop = next(
        node
        for node in ast.walk(run_job)
        if isinstance(node, ast.For)
        and isinstance(node.target, ast.Tuple)
        and [item.id for item in node.target.elts if isinstance(item, ast.Name)]
        == ["state_name", "step_name", "field_domain"]
    )
    assert len(create_context_calls) == 1
    assert create_context_calls[0].lineno < state_loop.lineno

    save1_states = [state for state, _label, _domain in SAVE1_TAIL]
    save2_states = [state for state, _label, _domain in SAVE2_TAIL]
    assert StateName.SAVE_ONLY in save1_states
    assert StateName.SAVE2_ONLY not in save1_states
    assert StateName.VERIFY_SAVE1_NOT_PUBLISHED in save1_states
    assert StateName.VERIFY_SAVE2_NOT_PUBLISHED not in save1_states
    assert StateName.SAVE2_ONLY in save2_states
    assert StateName.SAVE_ONLY not in save2_states
    assert StateName.VERIFY_SAVE2_NOT_PUBLISHED in save2_states
    assert StateName.VERIFY_SAVE1_NOT_PUBLISHED not in save2_states


def test_path_b_stays_release_locked_without_genuine_visible_runtime_provider() -> None:
    assert RELEASED_PLAN_EXECUTION_PATHS == frozenset({"A"})
    adapter_source = (
        BACKEND_ROOT / "src" / "execution" / "dxm_adapter.py"
    ).read_text(encoding="utf-8")
    assert 'proof.get("source") != "visible_production_runtime"' in adapter_source
    assert "PRODUCTION_CAPABILITY_NOT_CLOSED_" in adapter_source
    assert "evidence_sha256" in adapter_source


def test_flow_and_acceptance_scripts_use_public_api_without_db_or_private_adapter() -> None:
    flow_path = REPO_ROOT / "scripts" / "run-real-dxm-path-b-system-test.ps1"
    report_path = REPO_ROOT / "scripts" / "report" / "generate_v1_acceptance_record.py"
    assert flow_path.is_file()
    assert report_path.is_file()

    flow_source = flow_path.read_text(encoding="utf-8")
    report_source = report_path.read_text(encoding="utf-8")
    report_tree = ast.parse(report_source, filename=str(report_path))
    imported_modules = {
        alias.name.split(".")[0]
        for node in ast.walk(report_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module or "").split(".")[0]
        for node in ast.walk(report_tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert "sqlite3" not in imported_modules
    assert "src" not in imported_modules
    assert "/api/" in report_source
    assert "Invoke-RestMethod" in flow_source
    assert "/api/" in flow_source
    assert "db_path" not in report_source.casefold()
    flow_executable = "\n".join(
        line for line in flow_source.splitlines() if not line.lstrip().startswith("#")
    ).casefold()
    for forbidden in (
        "db_path",
        "sqlite3",
        "playwright",
        ".locator(",
        "dxm_adapter",
        "workflow_adapter.",
        "save_only(",
    ):
        assert forbidden not in flow_executable


@pytest.mark.parametrize("drift", [None, "product", "session", "http", "preflight", "preflight_success", "preflight_drift"])
def test_inspect_phase_binds_three_current_products_without_save_or_scope(tmp_path, drift):
    """Exercise the driver against a local HTTP double, never a DXM adapter."""
    import shutil
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import parse_qs, urlsplit

    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    assert shell, "The system-flow driver requires PowerShell"
    ids = [str(910000000000000001 + index) for index in range(3)]
    session = "1234567890abcdef"
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            calls.append(("GET", path))
            if path == "/health":
                self.reply({"status": "ok"})
            elif path == "/api/dxm/draft-reader/shops":
                self.reply({"source": "api", "session_bound": True, "session_ref": session,
                            "shops": [{"id": "91", "name": "Unit Shop"}]})
            elif path == "/api/dxm/draft-reader/products":
                self.reply({"source": "api", "session_bound": True, "session_ref": session,
                            "items": [{"id": pid, "shop_id": "91", "category_id": "17",
                                       "dxm_state": "draft"} for pid in ids],
                            "pagination": {"has_next": False}})
            elif path == "/api/local-plan-templates/7":
                self.reply({"id": 7, "shop_id": "91", "path": "B", "category_ids": ["17"]})
            else:
                self.send_error(404)

        def do_POST(self):
            url = urlsplit(self.path)
            calls.append(("POST", url.path))
            if url.path == "/api/plan-snapshots/preview":
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert request == {"local_plan_template_id": 7, "shop_id": "91", "session_ref": session,
                                   "product_ids": ids, "target_category_id": "17"}
                if drift == "preflight":
                    self.reply({"detail": {"reason_code": "MANDATORY_CAPABILITY_UNAVAILABLE"}}, status=409)
                else:
                    self.reply({"schema": "dxm_batch_draft_save_plan.v1", "path": "B", "publish_allowed": False,
                                "shop_scope": "92" if drift == "preflight_drift" else "91", "local_plan_template": {"id": 7},
                                "product_ids": ids, "snapshot_hash": "A" * 64})
                return
            if url.path != "/api/dxm-template-refs/sync":
                self.send_error(404)
                return
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert parse_qs(url.query) == {"include_current_values": ["true"]}
            if drift == "http":
                self.reply({"detail": {"reason_code": "CURRENT_VALUES_UNAVAILABLE"}}, status=409)
                return
            pid = request["representative_product_ids"]["17"]
            self.reply({
                "source": "api", "session_bound": True,
                "session_ref": "fedcba0987654321" if drift == "session" else session,
                "representative_products": {"17": {
                    "__product_id": "1" if drift == "product" else pid,
                    "title": "Unit Product", "weight": "", "enabled": False,
                }},
                "category_schemas": {"17": {"properties": {
                    "title": {"type": "string", "ui_label_zh": "产品标题"}, "weight": {"type": "number"},
                    "enabled": {"type": "boolean"},
                }, "required": ["title", "weight", "enabled"]}},
                "refs": [],
            })

    request_path = tmp_path / "inspection-request.json"
    request_path.write_text(json.dumps({
        "schemaVersion": "real_dxm_path_b_inspection_request.v1",
        "shopId": "91", "orderedProductIds": ids,
    }), encoding="utf-8")
    evidence = tmp_path / "evidence"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run([
            shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(REPO_ROOT / "scripts" / "run-real-dxm-path-b-system-test.ps1"),
            "-Phase", "Inspect", "-InspectionRequestFile", str(request_path),
            "-EvidenceDirectory", str(evidence),
            "-BaseUrl", f"http://127.0.0.1:{server.server_port}",
            *(["-LocalPlanTemplateId", "7"] if str(drift).startswith("preflight") else []),
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    allowed = {
        ("GET", "/health"), ("GET", "/api/dxm/draft-reader/shops"),
        ("GET", "/api/dxm/draft-reader/products"),
        ("POST", "/api/dxm-template-refs/sync"),
    }
    if str(drift).startswith("preflight"):
        allowed |= {("GET", "/api/local-plan-templates/7"), ("POST", "/api/plan-snapshots/preview")}
        assert calls[-1] == ("POST", "/api/plan-snapshots/preview")
    assert set(calls) <= allowed
    traces = list(evidence.glob("*-trace.json"))
    assert len(traces) == 1
    trace = json.loads(traces[0].read_text(encoding="utf-8"))
    assert trace["executionAllowed"] is False and trace["scopeIssued"] is False
    reports = [path for path in evidence.glob("*.json") if path not in traces]
    assert not list(evidence.glob("*attempt-journal*"))
    if drift and drift not in {"preflight", "preflight_success"}:
        assert result.returncode != 0
        assert not reports and trace["completed"] is False
        if drift == "http":
            assert "CURRENT_VALUES_UNAVAILABLE" in result.stdout + result.stderr
        return
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(reports) == 1 and trace["completed"] is True
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["orderedProductIds"] == ids
    assert [item["productId"] for item in report["items"]] == ids
    assert all(item["categorySchema"]["properties"]["title"]["ui_label_zh"] == "产品标题" for item in report["items"])
    assert [item["missingCurrentRequiredFields"] for item in report["items"]] == [["weight"]] * 3
    assert report["executionAllowed"] is False and report["scopeIssued"] is False
    if drift == "preflight":
        assert report["planPreflight"] == {"localPlanTemplateId": 7, "ok": False,
                                           "reasonCode": "MANDATORY_CAPABILITY_UNAVAILABLE", "snapshotHash": None}
    elif drift == "preflight_success":
        assert report["planPreflight"]["ok"] is True


def test_reader_preserves_missing_sku_logistics_without_certifying_it():
    from src.batch_edit.plan_schema_contract import (
        PlanSchemaError,
        assert_value_matches_schema,
    )
    from src.services.dxm_plan_reader import DxmPlanReader, DxmPlanReaderError

    sku_schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "skuCode": {"type": "string"},
                "logisticAttrList": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                },
            },
            "required": [],
        },
    }
    field = "aeopAeProductSKUs"
    schema = {"properties": {field: sku_schema}}
    for missing in (None, [None]):
        raw_skus = [{"skuCode": "example-sku", "logisticAttrList": missing}]
        current = DxmPlanReader._current_values_from_detail(
            {field: json.dumps(raw_skus)}, schema=schema,
        )
        assert current[field] == raw_skus
        with pytest.raises(PlanSchemaError) as exc:
            assert_value_matches_schema(current[field], sku_schema, field_key=field)
        assert exc.value.reason_code == "PLAN_FIELD_SCHEMA_INVALID"

    valid = [{"skuCode": "example-sku", "logisticAttrList": [{"value": "101"}]}]
    current = DxmPlanReader._current_values_from_detail(
        {field: json.dumps(valid)}, schema=schema,
    )
    assert current[field] == valid
    assert_value_matches_schema(current[field], sku_schema, field_key=field)

    with pytest.raises(DxmPlanReaderError, match=r"logisticAttrList\[0\].*received str"):
        DxmPlanReader._current_values_from_detail(
            {field: [{"logisticAttrList": ["not-an-object"]}]}, schema=schema,
        )


def test_reviewed_user_identity_probe_allowlist_is_exact() -> None:
    import runpy

    probe = runpy.run_path(str(REPO_ROOT / "tools" / "probes" / "l2_readonly_probe.py"))
    entries, errors, _ = probe["load_allowlist"](REPO_ROOT / "config" / "l2_readonly_allowlist.json")
    assert errors == []
    guard = probe["ReadOnlyProbeGuard"](strict_active_requests=True, allowlist_entries=entries)
    record = {"method": "GET", "url": "https://www.dianxiaomi.com/api/userIn.json", "resource_type": "xhr"}
    reasons = ["active_or_unknown_resource_type:xhr"]
    approved = guard._matching_allowlist_entry(record, reasons, [])
    assert approved is not None
    assert approved["id"] == "dxm-bootstrap-user-in"
    for drift in (
        {"method": "POST"},
        {"url": "https://www.dianxiaomi.com/api/userIn.json/extra"},
        {"url": "https://other.example/api/userIn.json"},
        {"resource_type": "fetch"},
    ):
        assert guard._matching_allowlist_entry({**record, **drift}, reasons, []) is None
    assert guard._matching_allowlist_entry(record, reasons, ["save"]) is None


def test_editor_inspection_reuses_read_guards_without_allowing_mutations() -> None:
    from src.execution.dxm_login_flow import DXM_E2_PLAN_READ_ALLOWLIST
    from src.execution.editor_readonly_inspection import make_editor_readonly_guard

    guard = make_editor_readonly_guard(
        REPO_ROOT / "tools" / "probes" / "l2_readonly_probe.py",
        REPO_ROOT / "config" / "l2_readonly_allowlist.json",
        DXM_E2_PLAN_READ_ALLOWLIST,
    )
    assert guard.strict_active_requests is True
    assert guard.allowlist_errors == []
    read = {"method": "GET", "url": "https://www.dianxiaomi.com/api/smtProduct/edit.json?id=8101", "resource_type": "xhr"}
    reasons = ["active_or_unknown_resource_type:xhr"]
    assert guard._matching_allowlist_entry(read, reasons, []) is not None
    for drift in (
        {"method": "POST"},
        {"url": "https://other.example/api/smtProduct/edit.json"},
        {"url": "https://www.dianxiaomi.com/api/smtProduct/edit.json/extra"},
        {"url": "https://www.dianxiaomi.com/api/smtProduct/save.json"},
        {"resource_type": "websocket"},
    ):
        assert guard._matching_allowlist_entry({**read, **drift}, reasons, []) is None
    assert guard._matching_allowlist_entry(read, reasons, ["publish"]) is None
    with pytest.raises(ValueError, match="read allowlist"):
        make_editor_readonly_guard(
            REPO_ROOT / "tools" / "probes" / "l2_readonly_probe.py",
            REPO_ROOT / "config" / "l2_readonly_allowlist.json",
            {("POST", "https://www.dianxiaomi.com/api/smtProduct/save.json")},
        )


def test_editor_inspection_requires_the_loaded_product_title() -> None:
    import subprocess
    from src.execution.editor_readonly_inspection import EDITOR_READONLY_READY_SCRIPT

    check = r"""
const assert = require('node:assert/strict');
const ready = eval('(' + JSON.parse(process.argv[1]) + ')');
let controls = [];
global.document = {querySelectorAll: () => controls};
global.getComputedStyle = el => ({display: 'block', visibility: el.hidden ? 'hidden' : 'visible'});
const field = (value, hidden = false) => ({value, hidden, getBoundingClientRect: () => ({width: 600, height: 32})});
assert.equal(ready('Exact draft title'), false);
controls = [field(''), field('100000015')];
assert.equal(ready('Exact draft title'), false);
controls = [field('Other product')];
assert.equal(ready('Exact draft title'), false);
controls = [field('Exact draft title', true)];
assert.equal(ready('Exact draft title'), false);
controls = [field(' Exact draft title ')];
assert.equal(ready('Exact draft title'), true);
assert.equal(ready(''), false);
"""
    result = subprocess.run(
        ["node", "-e", check, json.dumps(EDITOR_READONLY_READY_SCRIPT)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_shared_sku_rule_preserves_identity_and_has_one_resolution_authority() -> None:
    from src.batch_edit.plan_contract import PlanContractError as E2PlanError
    from src.batch_edit.plan_snapshot_compiler import PlanSnapshotCompiler
    from src.batch_edit.plan_template_contract import (
        PlanTemplateContractError, normalize_local_plan_payload,
    )

    field = "aeopAeProductSKUs"
    rule = {"source": "current", "set_each": {
        "logisticAttrList": [{"value": "101", "text": "普货"}],
        "ipmSkuStock": 200,
    }}
    plan = {
        "name": "普货模板", "version": "1.0.0", "shop_id": "91",
        "category_ids": ["17"], "path": "B",
        "fixed_values": {"publish_allowed": False, "field_values": {"17": {}}},
        "fill_rules": {"17": {field: rule}}, "dxm_template_refs": [],
        "field_mappings": {"17": {"mapping_version": "1.0.0", "entries": [{
            "ui_label_zh": "SKU 行", "field_key": field,
            "category_schema_path": f"$.properties.{field}",
            "ui_binding": f"dxm_editor:{field}",
        }]}},
        "source_policies": {"17": {field: "template"}},
        "configuration_contract": "local_plan_template.v3", "status": "draft",
        "source_snapshots": {},
        "validation_policy": {"required_fields": "fail_closed", "natural_language": "english_before_save"},
        "exception_policy": {"unknown": "stop_batch"}, "provenance": "unit contract only",
    }
    normalized = normalize_local_plan_payload(plan)
    assert normalized["fill_rules"] == plan["fill_rules"]
    compiler = PlanSnapshotCompiler(E2PlanError, local_plan_store=None)
    for count in (2, 3, 1):
        current = {field: [{"id": str(index + 1), "skuCode": f"sku-{count}-{index}",
                           "skuPrice": "12.50", "logisticAttrList": None}
                          for index in range(count)]}
        before = deepcopy(current)
        value, source, ref = compiler._resolve_field_value(
            field, plan={"id": 7, **normalized}, category_id="17",
            current_values=current, template_values={}, product_id=str(count),
        )
        assert current == before and len(value) == count
        assert source == "local_plan_template" and ref == "7@1.0.0#set_each"
        for original, resolved in zip(before[field], value):
            assert resolved == {**original, **rule["set_each"]}
        value[0]["logisticAttrList"][0]["value"] = "changed"
        assert rule["set_each"]["logisticAttrList"][0]["value"] == "101"
        if count > 1:
            assert value[1]["logisticAttrList"][0]["value"] == "101"

    for invalid in ([], None, [None]):
        with pytest.raises(E2PlanError, match="SKU"):
            compiler._resolve_field_value(
                field, plan={"id": 7, **normalized}, category_id="17",
                current_values={field: invalid}, template_values={}, product_id="1",
            )
    for override in ({"id": "other"}, {"skuCode": "same-for-all"}, {}):
        invalid = deepcopy(plan)
        invalid["fill_rules"]["17"][field]["set_each"] = override
        with pytest.raises(PlanTemplateContractError):
            normalize_local_plan_payload(invalid)
    # Explicit template/current policies must not silently use the other source.
    plain = {"id": 7, **normalized, "fill_rules": {"17": {}}}
    assert compiler._resolve_field_value(
        field, plan=plain, category_id="17", current_values={field: [1]},
        template_values={}, product_id="1",
    ) is None
    plain["source_policies"]["17"][field] = "current"
    assert compiler._resolve_field_value(
        field, plan=plain, category_id="17", current_values={},
        template_values={field: ([1], "remote")}, product_id="1",
    ) is None
    preflight = inspect.getsource(PlanSnapshotCompiler._resolve_target_category_preflight)
    assert "self._resolve_field_value(" in preflight




def test_shared_required_editor_actions_are_explicit_and_never_product_overrides():
    from dataclasses import fields
    from src.batch_edit.path_a_section_templates import AutoTranslateConfig, VideoGenerationConfig, WholesaleConfig
    from src.batch_edit.plan_template_contract import PlanTemplateContractError, normalize_local_plan_payload
    from src.batch_edit.wholesale_filler import WholesaleFiller

    plan = _shared_required_editor_actions_plan()
    plan.pop("id")
    original = deepcopy(plan)
    assert normalize_local_plan_payload(plan)["editor_actions"] == plan["editor_actions"]
    assert normalize_local_plan_payload(plan)["status"] == "draft" and plan == original
    models = {"video": VideoGenerationConfig, "wholesale": WholesaleConfig, "translation": AutoTranslateConfig}
    invalid_actions = []
    for name, model in models.items():
        assert set(plan["editor_actions"]["17"][name]) == {field.name for field in fields(model)}
        for key in plan["editor_actions"]["17"][name]:
            actions = deepcopy(plan["editor_actions"])
            actions["17"][name].pop(key)
            invalid_actions.append(actions)
        for value in (False, 1, None):
            actions = deepcopy(plan["editor_actions"])
            actions["17"][name]["enabled"] = value
            invalid_actions.append(actions)
    for name, key, value in (
        ("video", "failure_strategy", "ignore"), ("video", "max_wait_seconds", 0),
        ("video", "max_wait_seconds", True), ("video", "max_wait_seconds", 300.0),
        ("video", "poll_interval_seconds", -1), ("video", "poll_interval_seconds", 301),
        ("wholesale", "min_quantity", True), ("wholesale", "min_quantity", 3.0),
        ("wholesale", "min_quantity", WholesaleFiller.TIER_MIN_QUANTITY_RANGE[0] - 1),
        ("wholesale", "min_quantity", WholesaleFiller.TIER_MIN_QUANTITY_RANGE[1] + 1),
        ("wholesale", "discount_percent", True), ("wholesale", "discount_percent", 10.0),
        ("wholesale", "discount_percent", WholesaleFiller.DISCOUNT_RANGE[0] - 1),
        ("wholesale", "discount_percent", WholesaleFiller.DISCOUNT_RANGE[1] + 1),
        ("wholesale", "deduction_method", "guess"), ("wholesale", "deduction_method", []),
        ("translation", "direction", "en_zh"), ("translation", "translate_type", "guess"),
        ("translation", "apply_to", ["title"]),
        ("translation", "apply_to", ["title", "attributes", "descriptions", "custom_names"]),
        ("translation", "apply_to", ["title", "attributes", "description_pc", "description_mobile", "custom_name", "title"]),
        ("translation", "apply_to", ["title", "attributes", "description_pc", "description_mobile", {}]),
        ("video", "per_product", {"8101": {"enabled": True}}),
    ):
        actions = deepcopy(plan["editor_actions"])
        actions["17"][name][key] = value
        invalid_actions.append(actions)
    invalid_actions.extend(({"8101": deepcopy(plan["editor_actions"]["17"])}, {"17": {"per_product": {}}}))
    for actions in invalid_actions:
        with pytest.raises(PlanTemplateContractError) as error:
            normalize_local_plan_payload({**plan, "editor_actions": actions})
        assert error.value.reason_code == "LOCAL_PLAN_EDITOR_ACTIONS_INVALID"
    for min_quantity, discount in zip(WholesaleFiller.TIER_MIN_QUANTITY_RANGE, WholesaleFiller.DISCOUNT_RANGE):
        allowed = deepcopy(plan)
        allowed["editor_actions"]["17"]["wholesale"].update(min_quantity=min_quantity, discount_percent=discount, deduction_method="order")
        allowed["editor_actions"]["17"]["translation"]["translate_type"] = "ai"
        assert normalize_local_plan_payload(allowed)["editor_actions"] == allowed["editor_actions"]
    for values in ({"bulkOrder": 3, "bulkDiscount": 10, "reduceStrategy": "payment_success_deduct"},
                   {"bulkOrder": 4}, {"bulkDiscount": 11}, {"reduceStrategy": "unobserved_wire_value"}):
        candidate = deepcopy(plan)
        candidate["field_mappings"]["17"]["entries"].extend({
            "field_key": key, "ui_label_zh": "批发字段", "ui_binding": f"dxm_editor:{key}",
            "category_schema_path": f"$.properties.{key}",
        } for key in values)
        candidate["fixed_values"]["field_values"]["17"] = values
        if len(values) == 3:
            assert normalize_local_plan_payload(candidate)["editor_actions"] == plan["editor_actions"]
            candidate["editor_actions"]["17"]["wholesale"]["deduction_method"] = "order"
        with pytest.raises(PlanTemplateContractError, match="wholesale"):
            normalize_local_plan_payload(candidate)
        if len(values) == 1:
            candidate["fixed_values"]["field_values"]["17"] = {}
            candidate["fill_rules"]["17"] = {key: {"value": value} for key, value in values.items()}
            with pytest.raises(PlanTemplateContractError, match="wholesale"):
                normalize_local_plan_payload(candidate)


def test_shared_editor_actions_and_each_control_survive_freeze_to_save1():
    from src.batch_edit.plan_contract import PlanContractError
    from src.batch_edit.plan_snapshot_compiler import PlanSnapshotCompiler
    from src.batch_edit.frozen_execution_contract import (
        FrozenExecutionContractError, compile_frozen_execution_payload, frozen_execution_defaults,
    )

    plan = _shared_required_editor_actions_plan()
    compiler = PlanSnapshotCompiler(PlanContractError, local_plan_store=None)
    props = {"title": {"type": "string", "ui_binding": "dxm_editor:title"},
             "aeopAeProductSKUs": {"type": "array", "ui_binding": "dxm_editor:aeopAeProductSKUs", "ui_control": "sku_matrix"},
             "bulkOrder": {"type": "integer", "ui_binding": "dxm_editor:bulkOrder"},
             "bulkDiscount": {"type": "number", "ui_binding": "dxm_editor:bulkDiscount"},
             "reduceStrategy": {"type": "string", "ui_binding": "dxm_editor:reduceStrategy"}}
    schema = {"type": "object", "properties": props, "required": []}
    resolution = {"resolved_fields": [{"field_key": "title", "resolved_value": "Shared title"},
                                      {"field_key": "aeopAeProductSKUs", "resolved_value": [{"id": "1", "skuPrice": "12"}]},
                                      {"field_key": "bulkOrder", "resolved_value": 3},
                                      {"field_key": "bulkDiscount", "resolved_value": 10},
                                      {"field_key": "reduceStrategy", "resolved_value": "payment_success_deduct"}],
                  "unresolved_fields": [], "price_validation": {}}
    item = {"product_id": "8101", "shop_id": "91", "categoryId": "17",
            "category_schema": {"normalized_schema": schema, "schema_hash": canonical_sha256(schema)},
            "resolution_result": {**resolution, "resolution_hash": canonical_sha256(resolution)}}
    task = {"payload": {"plan_snapshot": {"snapshot_hash": HASH_A, "editor_actions": deepcopy(plan["editor_actions"]), "item_snapshots": [item]}}}
    job = {"product_id": "8101"}
    for order in (list(props), list(reversed(props))):
        mapping = {"mapping_version": "1.0.0", "entries": [
            {"field_key": key, "ui_binding": props[key]["ui_binding"], "ui_label_zh": "合同字段",
             "category_schema_path": f"$.properties.{key}"} for key in order]}
        item["field_mapping"] = {**mapping, "mapping_hash": canonical_sha256(mapping)}
        payload = compile_frozen_execution_payload(task, job, save_stage="SAVE1")
        by_key = {field["field_key"]: field for field in payload["fields"]}
        assert "ui_control" not in by_key["title"]
        assert by_key["aeopAeProductSKUs"]["ui_control"] == "sku_matrix"
        assert payload["editor_actions"] == plan["editor_actions"]["17"]
        assert frozen_execution_defaults(payload)["_editor_actions"] == plan["editor_actions"]["17"]
    frozen = compiler._freeze_plan_content(plan, None, "contract")
    for name, key, value in (("video", "max_wait_seconds", 301), ("wholesale", "discount_percent", 11), ("translation", "translate_type", "ai")):
        changed = deepcopy(plan)
        changed["editor_actions"]["17"][name][key] = value
        assert compiler._freeze_plan_content(changed, None, "contract")["plan_content_sha256"] != frozen["plan_content_sha256"]
    bad_task = deepcopy(task)
    bad_task["payload"]["plan_snapshot"]["editor_actions"]["17"]["video"].pop("failure_strategy")
    with pytest.raises(FrozenExecutionContractError, match="explicit"):
        compile_frozen_execution_payload(bad_task, job)
    bad_task = deepcopy(task)
    bad_resolution = bad_task["payload"]["plan_snapshot"]["item_snapshots"][0]["resolution_result"]
    bad_resolution["resolved_fields"][3]["resolved_value"] = 11
    bad_resolution["resolution_hash"] = canonical_sha256({key: value for key, value in bad_resolution.items() if key != "resolution_hash"})
    with pytest.raises(FrozenExecutionContractError, match="wholesale conflicts"):
        compile_frozen_execution_payload(bad_task, job)
    payload["editor_actions"]["video"]["max_wait_seconds"] = 999
    assert task["payload"]["plan_snapshot"]["editor_actions"] == plan["editor_actions"]
    # Configuration acceptance does not enable a production capability or release Path B.
    capability = compiler._check_mandatory_capabilities()
    assert capability["ok"] is False and capability["reason_code"] == "MANDATORY_CAPABILITY_CHECKER_MISSING"
    assert "B" not in RELEASED_PLAN_EXECUTION_PATHS


def test_editor_inspection_waits_for_the_actual_source_field() -> None:
    import subprocess
    from src.execution.editor_readonly_inspection import EDITOR_READONLY_HYDRATED_SCRIPT

    check = r"""
const assert = require('node:assert/strict');
const loaded = eval('(' + JSON.parse(process.argv[1]) + ')');
const url = 'https://example.com/source?id=42';
let fields = [];
global.document = {querySelectorAll: selector => {
  assert.equal(selector, 'input[name="sourceUrl"]');
  return fields;
}};
global.getComputedStyle = el => ({display:'block', visibility:el.hidden ? 'hidden' : 'visible'});
const field = (value, hidden = false) => ({value, hidden, getBoundingClientRect: () => ({width:200, height:30})});
assert.equal(loaded(url), false);
fields = [field('')];
assert.equal(loaded(url), false);
fields = [field(url, true)];
assert.equal(loaded(url), false);
fields = [field('https://example.com/other')];
assert.equal(loaded(url), false);
fields = [field(url), field(url)];
assert.equal(loaded(url), false);
fields = [field(url)];
assert.equal(loaded(url), true);
assert.equal(loaded(''), false);
"""
    result = subprocess.run(["node", "-e", check, json.dumps(EDITOR_READONLY_HYDRATED_SCRIPT)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("drift", [False, True])
def test_configure_phase_versions_one_shared_plan_and_checks_readback(tmp_path, drift):
    import shutil
    import subprocess
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    shell = shutil.which("powershell") or shutil.which("pwsh")
    assert shell is not None
    calls = []
    saved = {}
    base = {"id": 7, "name": "普货模板", "version": "1.0.0", "shop_id": "91",
            "path": "B", "configuration_contract": "local_plan_template.v3",
            "scope_contract": "single_target_category.v2", "category_ids": ["17"],
            "fixed_values": {"publish_allowed": False}, "status": "draft"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def respond(self, body):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            calls.append(("GET", self.path))
            if self.path == "/health":
                self.respond({"status": "ok"})
            elif self.path == "/api/local-plan-templates/7":
                self.respond(base)
            elif self.path == "/api/local-plan-templates/8":
                result = dict(reversed(list(saved.items())))
                if drift:
                    result["fill_rules"]["17"]["aeopAeProductSKUs"]["set_each"]["ipmSkuStock"] = 999
                self.respond(result)
            else:
                self.send_error(404)

        def do_POST(self):
            calls.append(("POST", self.path))
            assert self.path == "/api/local-plan-templates/7/versions"
            saved.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            saved["id"] = 8
            self.respond(saved)

    request_path = tmp_path / "configuration.json"
    request_path.write_text(json.dumps({
        "schemaVersion": "real_dxm_path_b_configuration_request.v1",
        "baseLocalPlanTemplateId": 7,
        "planChanges": {"version": "1.1.0", "fill_rules": {"17": {"aeopAeProductSKUs": {
            "source": "current", "set_each": {"ipmSkuStock": 200, "logisticAttrList": [{"value": "101", "text": "普货"}]},
        }}}, "source_snapshots": {"empty": [], "nulls": [None], "nested": [["a"]]}},
    }), encoding="utf-8")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    evidence = tmp_path / "evidence"
    try:
        result = subprocess.run([
            shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(REPO_ROOT / "scripts" / "run-real-dxm-path-b-system-test.ps1"),
            "-Phase", "Configure", "-ConfigurationRequestFile", str(request_path),
            "-EvidenceDirectory", str(evidence), "-BaseUrl", f"http://127.0.0.1:{server.server_port}",
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert calls == [("GET", "/health"), ("GET", "/api/local-plan-templates/7"),
                     ("POST", "/api/local-plan-templates/7/versions"), ("GET", "/api/local-plan-templates/8")]
    traces = list(evidence.glob("*-trace.json"))
    assert len(traces) == 1
    trace = json.loads(traces[0].read_text(encoding="utf-8"))
    assert trace["executionAllowed"] is False and trace["scopeIssued"] is False
    reports = [path for path in evidence.glob("*.json") if path not in traces]
    if drift:
        assert result.returncode != 0 and not reports
        assert "CONFIGURATION_READBACK_MISMATCH" in result.stdout + result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(reports) == 1
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        assert report["configurationPersisted"] is True and report["localPlanTemplateId"] == 8
        assert report["plan"] == saved and saved["name"] == "普货模板"
        assert saved["source_snapshots"] == {"empty": [], "nulls": [None], "nested": [["a"]]}
    assert not list(evidence.glob("*attempt-journal*"))


def test_shared_sku_template_round_trip_keeps_rules_and_wire_types() -> None:
    import subprocess
    from src.services.dxm_editor_model import enrich_dxm_editor_schema
    from src.batch_edit.plan_schema_contract import assert_value_matches_schema

    schema = enrich_dxm_editor_schema({"type": "object", "required": [], "properties": {
        "aeopAeProductSKUs": {"type": "array", "ui_label_zh": "SKU 行", "ui_binding": "dxm_editor:aeopAeProductSKUs",
                             "items": {"type": "object", "properties": {"skuCode": {"type": "string"}}}},
    }})
    definition = schema["properties"]["aeopAeProductSKUs"]
    assert definition["items"]["properties"]["packageWeight"]["type"] == "string"
    assert definition["items"]["properties"]["originalBox"]["values"] == [
        {"id": "0", "name": "否"}, {"id": "1", "name": "是"},
    ]
    assert_value_matches_schema([{"skuCode": "original", "packageWeight": "0.03", "originalBox": "0"}], definition, field_key="aeopAeProductSKUs")
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const source = fs.readFileSync('src/components/workbench/LocalPlanWorkspace.tsx', 'utf8');
const ast = ts.createSourceFile('workspace.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const names = new Set(['buildFieldDrafts', 'buildStructuredPlanFields', 'schemaLabel', 'isConfiguredValue']);
const code = ast.statements.filter(n => ts.isFunctionDeclaration(n) && names.has(n.name?.text)).map(n => n.getText(ast)).join('\n');
const api = new Function(ts.transpileModule(code, {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText + ';return {buildFieldDrafts,buildStructuredPlanFields};')();
const field = 'aeopAeProductSKUs';
const schemas = {'17': {properties: {[field]:JSON.parse(process.argv[1])},required:[]}};
const rule = {source:'current',set_each:{packageWeight:'0.03',originalBox:'0'}};
const plan = {fill_rules:{'17':{[field]:rule}}, source_policies:{'17':{[field]:'template'}}, fixed_values:{field_values:{}}, field_mappings:{}};
const drafts = api.buildFieldDrafts(schemas, plan);
assert.deepEqual(drafts['17'][field].value, rule.set_each);
assert.equal(drafts['17'][field].strategy, 'shared_rows');
const saved = api.buildStructuredPlanFields(['17'], schemas, drafts, 'B');
assert.deepEqual(saved.fillRules, plan.fill_rules);
assert.deepEqual(saved.sourcePolicies, plan.source_policies);
"""
    result = subprocess.run(["node", "-e", script, json.dumps(definition)], cwd=REPO_ROOT / "app/frontend",
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_every_explicit_template_reference_requires_its_own_success() -> None:
    from src.execution.dxm_login_flow import DxmLoginFlow

    check = DxmLoginFlow._missing_required_reference_template_results
    expected = ("product", "attribute_info", "freight", "regional_pricing")
    results = {key: {"ok": True} for key in expected}
    assert check(results, expected_sections=expected) == []
    for key in expected:
        incomplete = {name: result for name, result in results.items() if name != key}
        assert check(incomplete, expected_sections=expected) == [f"dxm_reference_templates.{key}"]
        incomplete[key] = {"ok": False, "required": False}
        assert check(incomplete, expected_sections=expected) == [f"dxm_reference_templates.{key}"]
    source = inspect.getsource(DxmLoginFlow._apply_frozen_templates_before_field_writes)
    assert "expected_sections=" in source and "_missing_required_reference_template_results(" in source


def test_editor_dialog_observation_is_enum_scoped_and_readonly() -> None:
    import subprocess
    from pydantic import ValidationError
    from src.models import DxmEditorReadonlyInspectionRequest

    request = {"shop_id": "101", "product_id": "202", "session_ref": "a" * 16}
    assert DxmEditorReadonlyInspectionRequest(**request).observe_dialog is None
    for dialog in ("translation", "video"):
        assert DxmEditorReadonlyInspectionRequest(**request, observe_dialog=dialog).observe_dialog == dialog
    for extra in ({"observe_dialog": "save"}, {"observe_dialog": "button:first-child"},
                  {"selector": "button"}, {"url": "https://example.invalid"}):
        with pytest.raises(ValidationError):
            DxmEditorReadonlyInspectionRequest(**request, **extra)

    from src.execution.editor_readonly_inspection import EDITOR_DIALOG_REVEAL_BINDINGS, EDITOR_READONLY_FORM_SCRIPT
    assert set(EDITOR_DIALOG_REVEAL_BINDINGS) == {"translation", "video"}
    assert EDITOR_DIALOG_REVEAL_BINDINGS["translation"] == (
        ".product-add-wrapper .header .btn-box button.translation-btn", "一键翻译",
    )
    assert EDITOR_DIALOG_REVEAL_BINDINGS["video"] == (
        ".product-add-wrapper .video-operate", "图片生成视频",
    )
    source = (BACKEND_ROOT / "src/execution/dxm_login_flow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "inspect_editor_readonly")
    calls = [_call_name(node) for node in ast.walk(method) if isinstance(node, ast.Call)]
    assert calls.count("click") == 1
    assert not set(calls) & {"fill", "select_option", "check", "set_input_files", "perform_editor_action", "_save_only_on_page"}
    method_source = ast.get_source_segment(source, method)
    assert method_source.index("guard.install(page)") < method_source.index("button.click(")
    assert "title_loaded and form_loaded" in method_source
    assert "existing_dialogs.count() != 0" in method_source
    assert "main_form_after == main_form_before" in method_source
    assert method_source.index("page.close()") < method_source.index("after = self.read_e2_product_details")
    assert "if after != before:" in method_source
    assert "'capabilityCertified': False" in method_source
    check = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
const field = {tagName:'INPUT', id:'bulk', type:'checkbox', name:'bulk', value:'1', checked:true,
  getAttribute:name => name === 'type' ? 'checkbox' : null, closest:() => null};
const dialogField = {...field, value:'dialog-only', closest:() => ({})};
const root = {querySelectorAll: selector => {
  assert.ok(selector.includes('input:not([type=password])'));
  return [field, dialogField];
}};
const read = vm.runInNewContext('(' + JSON.parse(process.argv[1]) + ')');
const before = JSON.parse(JSON.stringify(read(root)));
assert.equal(before.length, 1);
assert.equal(before[0].checked, true);
assert.doesNotMatch(JSON.stringify(before), /dialog-only/);
field.checked = false;
assert.notDeepEqual(JSON.parse(JSON.stringify(read(root))), before);
console.log('EDITOR_DIALOG_READONLY_CONTRACT_OK');
"""
    result = subprocess.run(["node", "-e", check, json.dumps(EDITOR_READONLY_FORM_SCRIPT)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "EDITOR_DIALOG_READONLY_CONTRACT_OK"


def test_editor_readonly_dom_records_bounded_semantic_context() -> None:
    import subprocess
    from src.execution.editor_readonly_inspection import EDITOR_READONLY_DOM_SCRIPT

    check = r"""
const assert = require('node:assert/strict');
const vm = require('node:vm');
let writes = 0;
const forbiddenWrite = () => { writes++; throw Error('DOM write forbidden'); };
const node = (tag, attributes = {}, parent = null, text = '') => {
  const element = {
    tagName: tag.toUpperCase(), id: attributes.id || '', className: attributes.class || '',
    parentElement: parent, innerText: text, textContent: text, labels: [],
    disabled: false, readOnly: false,
    getBoundingClientRect: () => ({width: 10, height: 10}),
    getAttribute: name => {
      assert.doesNotMatch(name, /token|password|__react/i);
      return attributes[name] ?? null;
    },
    closest: () => null, click: forbiddenWrite, setAttribute: forbiddenWrite,
    dispatchEvent: forbiddenWrite, appendChild: forbiddenWrite,
  };
  if (tag === 'input') { element.value = 'choice-a'; element.checked = true; }
  return new Proxy(Object.freeze(element), {
    get(target, key, receiver) {
      assert.doesNotMatch(String(key), /__react/i);
      return Reflect.get(target, key, receiver);
    },
    set: forbiddenWrite, defineProperty: forbiddenWrite, deleteProperty: forbiddenWrite,
  });
};
const top = node('div', {id: 'top-tools', 'data-token': 'private-top-token'});
const bottom = node('div', {id: 'bottom-tools'});
const buttons = [node('button', {class: 'translation-btn'}, top, 'Translate'),
  node('button', {class: 'translation-btn'}, bottom, 'Translate')];
let parent = null;
for (let depth = 7; depth >= 1; depth--) parent = node('div', {id: `ancestor-${depth}`}, parent);
const checkbox = node('input', {id: 'bulk-enabled', type: 'checkbox',
  'data-field': 'bulkEnabled', 'data-password': 'private-password'}, parent);
checkbox.labels.push(node('label', {for: 'bulk-enabled', 'data-token': 'private-label-token'}, null, 'Bulk'));
const controls = [...buttons, checkbox];
const context = {
  document: {title: 'Fixture', readyState: 'complete', body: {innerText: 'Fixture'},
    querySelectorAll: selector => {
      assert.ok(selector.includes('input:not([type=password])'));
      return controls;
    }},
  location: {href: 'https://example.invalid/editor'},
  getComputedStyle: () => ({display: 'block', visibility: 'visible'}),
  fetch: forbiddenWrite,
};
const result = JSON.parse(JSON.stringify(vm.runInNewContext('(' + JSON.parse(process.argv[1]) + ')()', context)));
assert.equal(result.controls.length, 3);
assert.equal(result.controls[0].text, result.controls[1].text);
assert.equal(result.controls[0].ancestors[0].attributes.id, 'top-tools');
assert.equal(result.controls[1].ancestors[0].attributes.id, 'bottom-tools');
assert.deepEqual(result.controls[0].labels, []);
assert.equal(result.controls[0].checked, null);
const observed = result.controls[2];
assert.equal(observed.ancestors.length, 6);
assert.equal(observed.ancestors[5].attributes.id, 'ancestor-6');
assert.equal(observed.bindingAttributes['data-field'], 'bulkEnabled');
assert.equal(observed.checked, true);
assert.deepEqual(observed.labels, [{text: 'Bulk', attributes: {for: 'bulk-enabled'}}]);
assert.doesNotMatch(JSON.stringify(result), /private-|data-token|data-password|__react/);
assert.deepEqual(Object.keys(result).sort(), ['bodyText', 'controls', 'readyState', 'title', 'url']);
assert.equal(writes, 0);
console.log('EDITOR_READONLY_DOM_CONTRACT_OK');
"""
    result = subprocess.run(
        ["node", "-e", check, json.dumps(EDITOR_READONLY_DOM_SCRIPT)],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "EDITOR_READONLY_DOM_CONTRACT_OK"


def test_shared_field_executor_never_calls_an_interrupted_apply_zero_write() -> None:
    from src.execution.dxm_adapter import DxmWorkflowAdapter
    from src.execution.dxm_login_flow import DxmLoginFlow

    class InterruptedPage:
        calls = 0

        def evaluate(self, *_args):
            self.calls += 1
            raise RuntimeError("transport closed after dispatch")

    payload = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "fields": [{"field_key": "title", "ui_label_zh": "标题",
                    "ui_binding": "dxm_editor:title", "resolved_value": "Example"}],
        "unresolved_fields": [],
    }
    payload["payload_hash"] = canonical_sha256(payload)
    page = InterruptedPage()
    apply = DxmLoginFlow._fill_frozen_execution_payload_on_page(page, payload)
    assert apply["ok"] is False and apply["write_attempted"] is True
    assert apply["failure_code"] == "UNKNOWN"
    assert apply["reason_code"] == "FROZEN_EXECUTION_BROWSER_WRITE_UNCERTAIN"
    assert DxmWorkflowAdapter._failure_code("fill_semi_managed_defaults", {}, {
        "editor_action_result": apply,
    }) == "UNKNOWN"
    assert DxmWorkflowAdapter._recoverability("UNKNOWN")["retryable"] is False
    read = DxmLoginFlow._fill_frozen_execution_payload_on_page(page, payload, operation="readback")
    assert read["ok"] is False and read["write_attempted"] is False
    assert read["failure_code"] == "FROZEN_EXECUTION_BROWSER_READ_FAILED"
    invalid = DxmLoginFlow._fill_frozen_execution_payload_on_page(page, payload, operation="preview")
    assert invalid["failure_code"] == "FROZEN_EXECUTION_OPERATION_INVALID"
    assert invalid["write_attempted"] is False and page.calls == 2


def test_rollback_preparation_binds_actual_preimage_and_precedes_every_main_write():
    from src.batch_edit.rollback_manager import (
        build_rollback_preparation_record, rollback_preparation_receipt,
        validate_rollback_preparation_observation,
    )
    from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults
    from src.execution.browser_agent_protocol import build_frozen_product_target_identity
    from src.execution.v1_runner import BATCH_PATH_B_STEPS, PATH_B_SAVE1_DISCOVERY_STEPS, V1TaskRunner
    from src.repository import Repository

    target = build_frozen_product_target_identity(product_id='81010001', store_name='Contract Shop',
                                                   source_urls=['https://detail.1688.com/offer/81010001.html'])
    properties = {key: {'type': 'string', 'ui_binding': f'dxm_editor:{key}'} for key in ('title', 'code')}
    schema = {'type': 'object', 'properties': properties, 'required': []}
    mapping = {'mapping_version': '1', 'entries': [
        {'field_key': key, 'ui_binding': prop['ui_binding'], 'ui_label_zh': key,
         'category_schema_path': f'$.properties.{key}'} for key, prop in properties.items()]}
    resolution = {'resolved_fields': [{'field_key': 'title', 'resolved_value': 'After'},
                                     {'field_key': 'code', 'resolved_value': ''}],
                  'unresolved_fields': [], 'price_validation': {}}
    item = {'product_id': '81010001', 'shop_id': '91', 'categoryId': '17', 'target_identity': target,
            'target_identity_sha256': canonical_sha256(target),
            'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
            'field_mapping': {**mapping, 'mapping_hash': canonical_sha256(mapping)},
            'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)},
            'real_write_stage_fields': {'SAVE1': ['title', 'code'], 'SAVE2': []},
            'real_write_stage_facts': {'SAVE1': [
                {'field_key': key, 'ui_binding': properties[key]['ui_binding'],
                 'preimage_sha256': canonical_sha256(value), 'expected_sha256': canonical_sha256(expected)}
                for key, value, expected in [('title', 'Before', 'After'), ('code', '', '')]], 'SAVE2': []}}
    task = {'id': 701, 'mode': 'batch_draft_save', 'payload': {
        'plan_snapshot': {'snapshot_hash': HASH_B, 'path': 'B', 'item_snapshots': [item]},
        'real_dxm_write_authorization': {'scope_sha256': HASH_C}}}
    job = {'id': 801, 'product_id': 81010001}
    payload = compile_frozen_execution_payload(task, job)
    command = BrowserAgentCommand(command_id='prepare-command', idempotency_key='prepare-once', deadline=EXPIRES_AT,
        expected_page='editor', runtime_id='runtime-contract', task_id=701, job_id=801,
        state='PREPARE_ROLLBACK', action='prepare_rollback', execution_mode='batch_draft_save',
        params={'defaults': frozen_execution_defaults(payload), 'target_identity': target, 'store_name': 'Contract Shop', 'shop_id': '91'})
    observation = {'schema': 'dxm.rollback-preimage-observation.v1', 'product_id': '81010001', 'shop_id': '91',
        'browser_session_id': 'same-session', 'target_identity_sha256': canonical_sha256(target),
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=81010001', 'category_id': '17',
        'category_schema_hash': payload['category_schema_hash'], 'execution_payload_hash': payload['payload_hash'],
        'observed_at': NOW, 'write_attempted': False,
        'values': [{'field_key': key, 'value': value, 'ui_binding': properties[key]['ui_binding'],
                    'unique': True, 'visible': True, 'writable': True} for key, value in [('title', 'Before'), ('code', '')]],
        'evidence_ref': {'path': 'C:/contract/preimage.png', 'sha256': HASH_D, 'size': 100}}
    validate = lambda candidate: validate_rollback_preparation_observation(candidate, execution_payload=payload,
        target_identity=target, browser_session_id='same-session')
    assert validate(observation) == observation
    for mutate in (lambda x: x['values'].pop(), lambda x: x['values'].append(deepcopy(x['values'][0])),
                   lambda x: x['values'][0].update(writable=False), lambda x: x.update(write_attempted=True),
                   lambda x: x.update(browser_session_id='other'), lambda x: x.update(category_schema_hash=HASH_A),
                   lambda x: x.update(page_url='https://www.dianxiaomi.com/web/smt/edit?id=9999')):
        bad = deepcopy(observation)
        mutate(bad)
        with pytest.raises(ValueError):
            validate(bad)
    record = build_rollback_preparation_record(task, job, command.to_payload(), observation)
    assert [entry['field_key'] for entry in record['restore_plan']] == ['code', 'title']
    assert record['restore_plan'][0]['value'] == ''
    assert record['command']['command_id'] == 'prepare-command'
    assert record['record_sha256'] == canonical_sha256({k: v for k, v in record.items() if k != 'record_sha256'})
    assert record['capability_receipt'] == rollback_preparation_receipt(observation, 'prepare-command')
    changed = deepcopy(observation)
    changed['values'][0]['value'] = 'Another before'
    with pytest.raises(ValueError, match='PREIMAGE_DRIFT'):
        build_rollback_preparation_record(task, job, command.to_payload(), changed)
    for steps in (BATCH_PATH_B_STEPS, PATH_B_SAVE1_DISCOVERY_STEPS):
        names = [state.value for state, *_ in steps]
        assert names.index('VERIFY_EDIT_OWNERSHIP') < names.index('PREPARE_ROLLBACK') < names.index('FILL_BASE_INFO')
    runner = inspect.getsource(V1TaskRunner)
    assert 'persist_rollback_preparation' in runner and 'require_rollback_preparation_before_write' in runner
    persistence = inspect.getsource(Repository.persist_rollback_preparation)
    assert persistence.index('BEGIN IMMEDIATE') < persistence.index('INSERT INTO job_evidences')
    assert 'build_rollback_preparation_record' in persistence


def test_shared_preimage_preflight_preserves_raw_values_without_any_write() -> None:
    import subprocess
    from textwrap import dedent
    from src.execution.dxm_login_flow import DxmLoginFlow

    function = ast.parse(dedent(inspect.getsource(DxmLoginFlow._fill_frozen_execution_payload_on_page)))
    script = next(node.value for node in ast.walk(function) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and node.value.startswith("({fields, operation, preimage})"))
    check = r"""
const assert = require('node:assert/strict');
const run = new Function('return (' + JSON.parse(require('node:fs').readFileSync(0, 'utf8')) + ')')();
const noWrite = () => { throw Error('preflight attempted a write'); };
const control = {tagName:'INPUT', value:'  Before\nvalue  ', disabled:false, readOnly:false,
  getAttribute: key => key === 'type' ? 'text' : null, hasAttribute:() => false,
  getBoundingClientRect:() => ({width:10,height:10}), matches:() => true,
  querySelectorAll:() => [], dispatchEvent:noWrite, focus:noWrite, scrollIntoView:noWrite};
let controls = [control];
global.window = {CSS:{escape:value => value}, getComputedStyle:() => ({display:'block',visibility:'visible'})};
global.document = {querySelectorAll:selector => selector === '[data-ui-binding="dxm_editor:title"]' ? controls : []};
const field = {field_key:'title',ui_binding:'dxm_editor:title',resolved_value:'After'};
const preflight = () => run({fields:[field],operation:'preflight',preimage:null});
assert.equal(preflight().ok, true, JSON.stringify(preflight()));
assert.equal(preflight().observations[0].value, '  Before\nvalue  ');
assert.equal(preflight().write_attempted, false);
assert.equal(control.value, '  Before\nvalue  ');
control.disabled = true;
assert.equal(preflight().ok, false);
control.disabled = false; control.readOnly = true;
assert.equal(preflight().ok, false);
control.readOnly = false; controls = [control, {...control}];
assert.equal(preflight().ok, false);
controls = [];
assert.equal(preflight().ok, false);
controls = [control]; control.tagName = 'SELECT'; control.value = 'old';
control.options = [{value:'new',textContent:'New'}];
field.resolved_value = 'new';
assert.equal(preflight().ok, true);
field.resolved_value = 'old';
assert.equal(preflight().ok, false); // A value readable now may not be restorable.
assert.equal(control.value, 'old');
"""
    result = subprocess.run(["node", "-e", check], input=json.dumps(script), capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr


def test_rollback_preparation_does_not_read_batch_plan_for_unrelated_commands():
    from types import SimpleNamespace
    from src.execution.v1_runner import V1TaskRunner
    from src.state_machine.contracts import StateName

    # Pure command factory inputs; no Adapter, runtime, browser or database.
    names = SimpleNamespace(_source_title=lambda _product: 'Contract title',
                            _target_source_urls=lambda _task, _job: [],
                            _store_name=lambda _task: 'Contract Shop')
    result = V1TaskRunner._workflow_action_worker_request(names,
        {'mode': 'single_save'}, {'product_id': 81010001}, StateName.PRECHECK_SESSION, {})
    assert result[0] == 'check_login_state' and result[3] == {}


def test_rollback_command_is_persisted_once_before_the_browser_runs(contract_db):
    from src.repository import Repository

    _insert_draft_batch_task(701)
    command = BrowserAgentCommand(command_id='readonly-preparation', idempotency_key='prepare-once', deadline=EXPIRES_AT,
        expected_page='editor', runtime_id='contract-runtime', task_id=701, job_id=801,
        state='PREPARE_ROLLBACK', action='prepare_rollback', execution_mode='batch_draft_save', params={}).to_payload()
    with db.connection() as conn:
        conn.execute("UPDATE tasks SET status='running' WHERE id=701")
        conn.execute("INSERT INTO jobs(id,task_id,product_id,status,current_step_code,created_at,updated_at) VALUES(801,701,81010001,'running','VERIFY_EDIT_OWNERSHIP',?,?)", (NOW, NOW))
    repo = Repository()
    with pytest.raises(ValueError, match='OUTSIDE_PREPARATION'):
        repo.reserve_rollback_preparation(701, 801, command)
    with db.connection() as conn:
        conn.execute("UPDATE jobs SET current_step_code='PREPARE_ROLLBACK' WHERE id=801")
    repo.reserve_rollback_preparation(701, 801, command)
    with pytest.raises(ValueError, match='ALREADY_RESERVED'):
        repo.reserve_rollback_preparation(701, 801, command)
    with db.connection() as conn:
        rows = conn.execute("SELECT meta_json FROM job_evidences WHERE task_id=701 AND job_id=801 AND evidence_type='path_b_rollback_command'").fetchall()
        assert len(rows) == 1 and json.loads(rows[0]['meta_json']) == command
        assert conn.execute('SELECT count(*) AS total FROM mutation_dispatch_ledger').fetchone()['total'] == 0


def test_preimage_restore_writer_keeps_whitespace_and_rejects_lossy_controls() -> None:
    import subprocess
    from textwrap import dedent
    from src.execution.dxm_login_flow import DxmLoginFlow

    function = ast.parse(dedent(inspect.getsource(DxmLoginFlow._fill_frozen_execution_payload_on_page)))
    script = next(node.value for node in ast.walk(function) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and node.value.startswith("({fields, operation, preimage})"))
    check = r"""
const assert = require('node:assert/strict');
const run = new Function('return (' + JSON.parse(require('node:fs').readFileSync(0, 'utf8')) + ')')();
let writes = 0;
const control = {tagName:'TEXTAREA', value:'old', children:[], disabled:false, readOnly:false,
  getAttribute:() => null, hasAttribute:() => false, matches:() => true,
  getBoundingClientRect:() => ({width:10,height:10}), querySelectorAll:() => [],
  dispatchEvent:() => writes++, focus:() => {}, scrollIntoView:() => {}};
global.InputEvent = Event;
global.window = {CSS:{escape:value => value}, HTMLTextAreaElement:{prototype:{}},
  getComputedStyle:() => ({display:'block',visibility:'visible'})};
global.document = {querySelectorAll:s => s === '[data-ui-binding="dxm_editor:title"]' ? [control] : []};
const fields = [{field_key:'title',ui_binding:'dxm_editor:title',resolved_value:' a\nb  c '}];
assert.equal(run({fields,operation:'apply',preimage:null}).ok, true);
assert.equal(control.value, fields[0].resolved_value);
assert.equal(writes, 3);
control.tagName = 'INPUT';
assert.equal(run({fields,operation:'preflight',preimage:null}).ok, false);
control.tagName = 'DIV'; control.children = [{}];
control.getAttribute = key => key === 'contenteditable' ? 'true' : null;
assert.equal(run({fields,operation:'preflight',preimage:null}).ok, false);
assert.equal(writes, 3);
"""
    result = subprocess.run(["node", "-e", check], input=json.dumps(script), capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr


def test_rollback_path_authority_is_frozen_not_an_unchecked_runtime_default():
    from src.batch_edit.frozen_execution_contract import (
        FrozenExecutionContractError, compile_frozen_execution_payload,
        frozen_execution_defaults, validate_frozen_execution_defaults,
    )

    schema = {'type': 'object', 'properties': {'title': {'type': 'string', 'ui_binding': 'dxm_editor:title'}}}
    mapping = {'mapping_version': '1', 'entries': [{'field_key': 'title', 'ui_label_zh': '标题',
               'ui_binding': 'dxm_editor:title', 'category_schema_path': '$.properties.title'}]}
    resolution = {'resolved_fields': [{'field_key': 'title', 'resolved_value': 'After'}],
                  'unresolved_fields': [], 'price_validation': {}}
    item = {'product_id': '81010001', 'categoryId': '17',
            'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
            'field_mapping': {**mapping, 'mapping_hash': canonical_sha256(mapping)},
            'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)}}
    task = {'payload': {'plan_snapshot': {'item_snapshots': [item], 'path': 'B'}}}
    job = {'product_id': 81010001}
    payload = compile_frozen_execution_payload(task, job)
    assert payload.get('execution_path') == 'B'
    defaults = frozen_execution_defaults(payload)
    defaults['_frozen_execution_payload']['execution_path'] = 'A'
    with pytest.raises(FrozenExecutionContractError):
        validate_frozen_execution_defaults(defaults, expected_payload=payload)
    task['payload']['plan_snapshot']['path'] = 'A'
    assert 'execution_path' not in compile_frozen_execution_payload(task, job)


def test_save1_first_write_compares_raw_preimage_and_checks_choice_restoreability() -> None:
    import subprocess
    from textwrap import dedent
    from src.execution.dxm_login_flow import DxmLoginFlow

    function = ast.parse(dedent(inspect.getsource(DxmLoginFlow._fill_frozen_execution_payload_on_page)))
    script = next(node.value for node in ast.walk(function) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and node.value.startswith("({fields, operation, preimage})"))
    check = r"""
const assert = require('node:assert/strict');
const run = new Function('return (' + JSON.parse(require('node:fs').readFileSync(0, 'utf8')) + ')')();
let writes = 0;
const control = {tagName:'TEXTAREA', value:' before ', children:[], disabled:false, readOnly:false,
  getAttribute:() => null, hasAttribute:() => false, matches:() => true,
  getBoundingClientRect:() => ({width:10,height:10}), querySelectorAll:() => [],
  dispatchEvent:() => writes++, focus:() => {}, scrollIntoView:() => {}};
let controls = [control];
global.InputEvent = Event;
global.window = {CSS:{escape:value => value}, HTMLTextAreaElement:{prototype:{}},
  getComputedStyle:() => ({display:'block',visibility:'visible'})};
global.document = {querySelectorAll:s => s === '[data-ui-binding="dxm_editor:title"]' ? [
  {matches:() => false, querySelectorAll:() => controls, getBoundingClientRect:() => ({width:10,height:10})}
] : []};
const fields = [{field_key:'title',ui_binding:'dxm_editor:title',resolved_value:'after'}];
const preimage = {schema:'dxm.rollback-preimage-values.v1',values:{title:'before'}};
assert.equal(run({fields,operation:'apply',preimage}).failure_code, 'SAVE1_PREIMAGE_DRIFT_BEFORE_FIRST_WRITE');
assert.equal(writes, 0);
preimage.values.title = ' before ';
assert.equal(run({fields,operation:'apply',preimage}).ok, true);
assert.equal(control.value, 'after'); assert.equal(writes, 3);
control.tagName = 'SELECT'; control.options = [{value:'after',textContent:'after',parentElement:{disabled:true}}];
assert.equal(run({fields,operation:'preflight',preimage:null}).ok, false);
controls = ['a','b'].map(value => ({...control, tagName:'INPUT', value, checked:value==='a',
  getAttribute:key => key === 'type' ? 'radio' : null}));
fields[0].resolved_value = ['a','b'];
assert.equal(run({fields,operation:'preflight',preimage:null}).ok, false);
assert.equal(writes, 3);
"""
    result = subprocess.run(["node", "-e", check], input=json.dumps(script), capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    method = inspect.getsource(DxmLoginFlow._prepare_frozen_execution_page_for_save)
    assert method.index("prepared['attempted'] = True") < method.index("fill_result = self._fill_frozen_execution_payload_on_page")
    assert "SAVE1_PREFILL_ALREADY_ATTEMPTED" in method and "SAVE1_PREFILL_READBACK_DRIFT" in method
    assert "prepared_preimage=prepared['observation']" in method


def test_save1_shared_fill_prepares_once_preserves_raw_baseline_and_never_falls_back(monkeypatch) -> None:
    from types import MethodType, SimpleNamespace
    from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
    from src.execution.dxm_login_flow import DxmLoginFlow

    payload = {'schema': 'dxm.batch_draft_save.execution_payload.v1', 'execution_path': 'B',
               'fields': [{'field_key': 'title', 'ui_label_zh': '标题',
                           'ui_binding': 'dxm_editor:title', 'resolved_value': 'after'}],
               'unresolved_fields': []}
    payload['payload_hash'] = canonical_sha256(payload)
    defaults = frozen_execution_defaults(payload)
    calls = []
    page = SimpleNamespace(url='https://www.dianxiaomi.com/web/smt/edit?id=81010001')
    raw_before = ' before\nsecond line '
    observation = {'schema': 'dxm.rollback-preimage-observation.v1',
                   'execution_payload_hash': payload['payload_hash'], 'browser_session_id': 'unit-session',
                   'page_url': page.url, 'values': [{'field_key': 'title', 'value': raw_before}]}
    schema = {'ok': True}
    readback = {'ok': True, 'values': [{'field_key': 'title', 'value': 'after'}]}

    def evaluate(_script, arguments):
        assert arguments['preimage']['values'] == {'title': raw_before}
        calls.append('apply')
        return {'ok': True, 'field_count': 1, 'write_attempted': True,
                'fields': [{'field_key': 'title', 'ui_binding': 'dxm_editor:title',
                            'ok': True, 'write_attempted': True}]}

    def capture_schema(*_args, **_kwargs):
        calls.append('schema')
        return dict(schema)

    page.evaluate = evaluate
    flow = SimpleNamespace(
        _execution_evidence_context={'task_id': 1, 'job_id': 2, 'command_id': 'first-fill',
            'runtime_id': 'unit-runtime', 'browser_session_id': 'unit-session',
            'state': 'FILL_BASE_INFO', 'command_action': 'fill_editor_required_defaults'},
        _save1_prefill_state={'observation': observation, 'page': page,
                             'task_id': 1, 'job_id': 2, 'attempted': False, 'result': None},
        browser_session_id=lambda: 'unit-session',
        _capture_current_editor_category_schema=capture_schema,
        _capture_frozen_execution_values=lambda *_a, **_k: {
            'ok': True, 'values': [{'field_key': 'title', 'value': 'before second line'}]},
        _capture_frozen_execution_readback=lambda *_a, **_k: deepcopy(readback),
        _capture_save_field_integrity_snapshot=lambda *_a: {'ok': True},
        _is_visible_dxm_editor_page=lambda *_a: True,
        _fill_frozen_execution_payload_on_page=DxmLoginFlow._fill_frozen_execution_payload_on_page,
    )
    for name in ('_prepare_editor_page_for_save', '_prepare_frozen_execution_page_for_save'):
        setattr(flow, name, MethodType(getattr(DxmLoginFlow, name), flow))
    first = DxmLoginFlow._try_fill_frozen_execution_defaults(flow, page, defaults)
    assert first['ok'] is True and calls == ['schema', 'apply']
    assert first['fields'] == first['fill_result']['fields'] and first['field_count'] == 1
    assert first['write_attempted'] is True
    assert first['save_field_baseline'][0]['value_before'] == raw_before
    reused = DxmLoginFlow._try_fill_frozen_execution_defaults(flow, page, defaults)
    assert calls == ['schema', 'apply', 'schema'] and reused['ok'] is True
    assert reused['prefill_reused'] is True and reused['write_attempted'] is False
    assert reused['field_count'] == 1 and reused['fields'][0]['write_attempted'] is False
    assert reused['fill_result']['write_attempted'] is False
    assert reused['preflight_results']['frozen_execution']['fields'][0]['write_attempted'] is False
    assert first['fields'][0]['write_attempted'] is True  # Reuse must not rewrite historical evidence.
    schema['ok'] = False
    blocked = DxmLoginFlow._try_fill_frozen_execution_defaults(flow, page, defaults)
    assert blocked['failure_code'] == 'FROZEN_CATEGORY_SCHEMA_DRIFT' and blocked['write_attempted'] is False
    schema['ok'] = True
    readback['ok'] = False
    with pytest.raises(RuntimeError, match='SAVE1_PREFILL_READBACK_DRIFT'):
        DxmLoginFlow._try_fill_frozen_execution_defaults(flow, page, defaults)
    assert calls.count('apply') == 1

    def forbidden_fallback(*_args, **_kwargs):
        pytest.fail('Path B main-page operations must not use visible-label fallback')

    monkeypatch.setattr(DxmLoginFlow, '_visible_frozen_fallback_result', forbidden_fallback)
    page.evaluate = lambda *_a: {'ok': False, 'field_count': 0, 'fields': [],
                                'observations': [], 'write_attempted': False}
    for operation in ('apply', 'readback', 'preflight'):
        result = DxmLoginFlow._fill_frozen_execution_payload_on_page(
            page, payload, operation=operation, prepared_preimage=observation)
        assert result['ok'] is False and result['write_attempted'] is False


def test_editor_form_stability_wait_resets_on_change_and_times_out_readonly(monkeypatch) -> None:
    from types import SimpleNamespace
    from src.execution import editor_readonly_inspection as inspection

    clock = [0.0]
    monkeypatch.setattr(inspection.time, 'monotonic', lambda: clock[0])
    page = SimpleNamespace(wait_for_timeout=lambda ms: clock.__setitem__(0, clock[0] + ms / 1000))
    form = SimpleNamespace(evaluate=lambda script: [{'value': 'early' if clock[0] < 1 else 'loaded'}])
    result = inspection.wait_editor_form_stable(page, form)
    assert result['ok'] is True and result['snapshot'] == [{'value': 'loaded'}]
    assert result['changes'] == 1 and 3 <= clock[0] <= 3.25
    clock[0] = 0
    form.evaluate = lambda script: [{'value': clock[0]}]
    result = inspection.wait_editor_form_stable(page, form)
    assert result['ok'] is False and result['snapshot'] is None and clock[0] == 15
    from src.execution.dxm_login_flow import DxmLoginFlow
    source = inspect.getsource(DxmLoginFlow.inspect_editor_readonly)
    assert source.index('wait_editor_form_stable(page, main_form)') < source.index('button.click(')
    assert 'entryProbe' in source and 'overlayDom' in source


def test_frozen_main_fill_facts_require_bound_business_readbacks() -> None:
    from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
    from src.execution.action_result_contract import (
        ActionResultContractError, derive_frozen_main_fill_facts, validate_action_result_envelope,
    )
    from src.execution.dxm_adapter import DxmWorkflowAdapter

    rows = [
        {'skuCode': f'UNIT-{index}', 'skuPrice': '10.50', 'cargoPrice': '4.00', 'ipmSkuStock': 0,
         'packageWeight': '0.2', 'packageLength': '10', 'packageWidth': '8', 'packageHeight': '5',
         'originalBox': '0', 'logisticAttrList': [{'value': '1', 'text': 'unit logistics'}],
         'aeopSKUProperty': [{'skuPropertyId': '1', 'propertyValueId': str(index)}]}
        for index in (1, 2)
    ]
    values = {'title': 'Unit title', 'aeopAeProductSKUs': rows, 'msrEuId': '101', 'manufactureId': '102'}

    def evidence_for(field_values):
        payload = {'schema': 'dxm.batch_draft_save.execution_payload.v1', 'execution_path': 'B',
                   'product_id': '81010001', 'category_id': '17', 'category_schema_hash': 'A' * 64,
                   'target_category': {'category_id': '17', 'plan_owned': True}, 'unresolved_fields': [],
                   'fields': [{'field_key': key, 'ui_binding': f'dxm_editor:{key}',
                               'ui_label_zh': key, 'resolved_value': value} for key, value in field_values.items()]}
        payload['payload_hash'] = canonical_sha256(payload)
        fill = {'ok': True, 'execution_payload_hash': payload['payload_hash'],
                'field_count': len(field_values), 'write_attempted': False,
                'fields': [{'field_key': field['field_key'], 'ui_binding': field['ui_binding'],
                            'ok': True, 'write_attempted': False} for field in payload['fields']]}
        readback = {'schema': 'dxm.frozen_execution.readback.v1', 'ok': True, 'phase': 'after_prefill',
                    'execution_payload_hash': payload['payload_hash'], 'field_count': len(field_values),
                    'fields': [{'field_key': field['field_key'], 'ui_binding': field['ui_binding'],
                                'expected_value_hash': canonical_sha256(field['resolved_value']),
                                'observed_value_hash': canonical_sha256(field['resolved_value']),
                                'aggregate_kind': 'sku_rows' if field['field_key'] == 'aeopAeProductSKUs' else 'single',
                                'match_count': len(field['resolved_value']) if field['field_key'] == 'aeopAeProductSKUs' else 1,
                                'exact': True} for field in payload['fields']], 'reason': None}
        editor = {**fill, 'execution_payload': payload, 'fill_result': deepcopy(fill),
                  'preflight_results': {'frozen_execution': deepcopy(fill)}, 'required_readback_complete': True,
                  'frozen_execution_readback': readback,
                  'category_schema_readback': {'schema': 'dxm.editor.category_schema_readback.v1', 'ok': True,
                      'phase': 'before_any_field_write', 'expected_category_id': '17', 'observed_category_id': '17',
                      'expected_category_schema_hash': 'A' * 64, 'observed_category_schema_hash': 'A' * 64,
                      'category_source': 'dom:value', 'reason': None}}
        return {'defaults': frozen_execution_defaults(payload)}, editor, payload

    before, editor, payload = evidence_for(values)
    derive = lambda action, b=before, e=editor: derive_frozen_main_fill_facts(
        action, before_values=b, editor_result=e)
    base = derive('fill_editor_required_defaults')
    assert base['postconditions'] == {'title_readback_nonempty': True, 'title_readback_exact': True,
        'category_selected_exact': True, 'required_templates_resolved': False, 'required_fields_complete': False}
    variants = derive('fill_editor_variants')
    assert all(variants['postconditions'].values())
    assert variants['after_values']['variant_readback'] == editor['frozen_execution_readback']
    compliance = derive('fill_compliance_defaults')['postconditions']
    assert compliance['eu_responsible_readback_exact'] and compliance['manufacturer_readback_exact']
    assert not compliance['customs_readback_exact'] and not compliance['required_templates_applied']
    assert not compliance['required_compliance_complete']
    assert derive_frozen_main_fill_facts('fill_media_assets', before_values=before, editor_result=editor) is None

    missing_stock = deepcopy(values)
    missing_stock['aeopAeProductSKUs'][1].pop('ipmSkuStock')
    b, e, _ = evidence_for(missing_stock)
    partial = derive('fill_editor_variants', b, e)['postconditions']
    assert partial['price_readback_exact'] and not partial['stock_readback_exact']
    assert not partial['all_required_cells_complete']
    duplicate_identity = deepcopy(values)
    duplicate_identity['aeopAeProductSKUs'][1]['aeopSKUProperty'] = rows[0]['aeopSKUProperty']
    b, e, _ = evidence_for(duplicate_identity)
    assert not derive('fill_editor_variants', b, e)['postconditions']['variant_rows_present']
    drift = deepcopy(editor)
    drift['frozen_execution_readback']['fields'][0]['observed_value_hash'] = 'B' * 64
    assert not any(derive('fill_editor_variants', before, drift)['postconditions'].values())
    drift = deepcopy(editor)
    drift['fill_result']['fields'][0]['ui_binding'] = 'dxm_editor:other'
    assert not any(derive('fill_editor_required_defaults', before, drift)['postconditions'].values())
    b = deepcopy(before)
    b['defaults']['title'] = 'not the frozen value'
    assert not any(derive('fill_editor_required_defaults', b, editor)['postconditions'].values())
    drift = deepcopy(editor)
    drift['category_schema_readback']['observed_category_id'] = '18'
    assert not any(derive('fill_editor_required_defaults', before, drift)['postconditions'].values())

    envelope = {'schema_version': 'dxm.action-result.v1', 'ok': True, 'action': 'fill_editor_variants',
                'attempted_state': 'FILL_VARIANTS', 'before_values': before, **variants,
                'evidence': {'observations': {'editor_action_result': editor}, 'refs': []},
                'page_identity': {'kind': 'editor', 'url': 'https://www.dianxiaomi.com/web/smt/edit?id=81010001',
                                  'runtime_id': 'unit-runtime', 'browser_session_id': 'unit-session'},
                'failure_code': None,
                'recoverability': {'kind': 'none', 'retryable': False, 'requires_page_reverify': False, 'reason': None}}
    assert validate_action_result_envelope(envelope, expected_execution_payload=payload)['ok'] is True
    forged = deepcopy(envelope)
    forged['evidence']['observations']['editor_action_result']['frozen_execution_readback']['fields'][1]['match_count'] = 1
    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(forged, expected_execution_payload=payload)
    forged = deepcopy(envelope)
    forged['after_values']['variant_readback']['execution_payload_hash'] = 'B' * 64
    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(forged, expected_execution_payload=payload)
    source = inspect.getsource(DxmWorkflowAdapter._build_contract_facts)
    assert 'derive_frozen_main_fill_facts(' in source and 'frozen_facts[\'after_values\']' in source
    for action in ('fill_editor_required_defaults', 'fill_editor_variants', 'fill_compliance_defaults'):
        assert 'perform_editor_action(' in inspect.getsource(getattr(DxmWorkflowAdapter, action))


def test_translation_overlay_observation_reads_unique_outer_surface_without_actions() -> None:
    import subprocess
    from src.execution.editor_readonly_inspection import EDITOR_READONLY_OVERLAYS_SCRIPT, EDITOR_TRANSLATION_SURFACE_BINDING
    from src.execution.dxm_login_flow import DxmLoginFlow

    assert EDITOR_TRANSLATION_SURFACE_BINDING == '.ant-popover:visible .translate-panel:visible'
    check = r"""
const assert = require('node:assert/strict');
const run = new Function('return (' + JSON.parse(process.argv[1]) + ')')();
const fail = () => { throw Error('observation wrote to DOM'); };
const node = (role, text, width=10) => ({tagName:'DIV', id:'', innerText:text,
  getAttribute:key => key === 'role' ? role : null,
  getBoundingClientRect:() => ({width,height:10}), contains:() => false,
  querySelectorAll:() => [], click:fail, focus:fail, setAttribute:fail, dispatchEvent:fail});
const child = node('tooltip', 'Translation');
const outer = node(null, 'Translation');
const hidden = node('dialog','Not visible',0);
outer.contains = el => el === child;
outer.querySelectorAll = query => {
  assert.ok(query.includes('input:not([type=password])'));
  return [child];
};
global.document = {querySelectorAll:() => [outer,child,hidden]};
global.getComputedStyle = () => ({display:'block',visibility:'visible'});
const result = run();
assert.equal(result.length,1);
assert.equal(result[0].nodes.length,1);
assert.equal(result[0].nodes[0].role,'tooltip');
"""
    result = subprocess.run(["node", "-e", check, json.dumps(EDITOR_READONLY_OVERLAYS_SCRIPT)], capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    source = inspect.getsource(DxmLoginFlow.inspect_editor_readonly)
    assert "page.locator(EDITOR_TRANSLATION_SURFACE_BINDING) if observe_dialog == 'translation'" in source
    assert source.count('button.click(') == 1 and "'capabilityCertified': False" in source


def test_frozen_fill_consumes_identity_enriched_production_result() -> None:
    from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
    from src.execution.action_result_contract import derive_frozen_main_fill_facts
    from src.execution.dxm_login_flow import DxmLoginFlow

    field = {'field_key': 'title', 'ui_binding': 'dxm_editor:title', 'ui_label_zh': 'Title', 'resolved_value': 'Unit'}
    payload = {'schema': 'dxm.batch_draft_save.execution_payload.v1', 'execution_path': 'B',
               'category_id': '17', 'category_schema_hash': 'A' * 64, 'fields': [field], 'unresolved_fields': []}
    payload['payload_hash'] = canonical_sha256(payload)
    fill = {'ok': True, 'execution_payload_hash': payload['payload_hash'], 'field_count': 1, 'write_attempted': False,
            'fields': [{'field_key': 'title', 'ui_binding': 'dxm_editor:title', 'ok': True, 'write_attempted': False}]}
    readback = {'schema': 'dxm.frozen_execution.readback.v1', 'ok': True, 'phase': 'after_prefill',
                'execution_payload_hash': payload['payload_hash'], 'field_count': 1, 'reason': None,
                'fields': [{'field_key': 'title', 'ui_binding': 'dxm_editor:title', 'aggregate_kind': 'single',
                    'match_count': 1, 'exact': True, 'expected_value_hash': canonical_sha256('Unit'),
                    'observed_value_hash': canonical_sha256('Unit')}]}
    schema = {'schema': 'dxm.editor.category_schema_readback.v1', 'ok': True, 'phase': 'before_any_field_write',
              'expected_category_id': '17', 'observed_category_id': '17', 'expected_category_schema_hash': 'A' * 64,
              'observed_category_schema_hash': 'A' * 64, 'category_source': 'dom:value', 'reason': None}
    editor = {**fill, 'execution_payload': payload, 'fill_result': fill,
              'preflight_results': {'frozen_execution': fill}, 'frozen_execution_readback': readback,
              'category_schema_readback': schema, 'required_readback_complete': True}
    attached = DxmLoginFlow._attach_frozen_target_evidence(editor, target_identity={'product_id': '81010001'},
        target_identity_sha256='B' * 64, before={'product_identity_match': True, 'store_identity_match': True,
                                               'source_identity_match': True})
    assert attached['fill_result'] != attached['preflight_results']['frozen_execution']
    before = {'defaults': frozen_execution_defaults(payload)}
    facts = derive_frozen_main_fill_facts('fill_editor_required_defaults', before_values=before, editor_result=attached)
    assert facts['postconditions']['title_readback_exact'] is True
    assert facts['after_values']['base_info_readback'] == readback
    attached = deepcopy(attached)
    attached['fill_result']['execution_payload_hash'] = 'C' * 64
    assert not any(derive_frozen_main_fill_facts('fill_editor_required_defaults', before_values=before,
        editor_result=attached)['postconditions'].values())


def test_stock_deduction_binding_uses_observed_wire_values_and_one_group() -> None:
    import subprocess
    from textwrap import dedent
    from src.execution.dxm_login_flow import DxmLoginFlow

    function = ast.parse(dedent(inspect.getsource(DxmLoginFlow._fill_frozen_execution_payload_on_page)))
    script = next(node.value for node in ast.walk(function) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and node.value.startswith("({fields, operation, preimage})"))
    check = r"""
const assert = require('node:assert/strict');
const run = new Function('return (' + JSON.parse(require('node:fs').readFileSync(0, 'utf8')) + ')')();
let writes = 0;
const group = {};
const radios = ['payment_success_deduct', 'place_order_withhold'].map((value, index) => ({
  value, checked: index === 0, tagName:'INPUT', disabled:false, readOnly:false,
  parentElement:{innerText:''},
  getAttribute:k => k === 'type' ? 'radio' : null,
  getBoundingClientRect:() => ({width:10,height:10}),
  closest: selector => selector === '.ant-radio-group' ? group : null,
  dispatchEvent:() => {writes += 1;},
}));
group.querySelectorAll = () => radios;
global.getComputedStyle = () => ({display:'block',visibility:'visible'});
global.window = {getComputedStyle, HTMLInputElement:{prototype:{}}};
global.document = {querySelectorAll:selector => selector.includes('payment_success_deduct') ? radios : []};
const fields = [{field_key:'reduceStrategy',ui_binding:'dxm_editor:reduceStrategy',resolved_value:'payment_success_deduct'}];
const read = () => run({fields,operation:'readback',preimage:null});
assert.equal(read().ok, true);
assert.equal(read().observations[0].value, 'payment_success_deduct');
assert.equal(writes, 0);
fields[0].resolved_value = 'place_order_withhold';
assert.equal(run({fields,operation:'apply',preimage:null}).ok, true);
assert.deepEqual(radios.map(node => node.checked), [false,true]);
assert.equal(read().observations[0].value, 'place_order_withhold');
radios[1].closest = () => ({});
assert.equal(read().ok, false);
assert.equal(run({fields,operation:'apply',preimage:null}).ok, false);
radios[1].closest = selector => selector === '.ant-radio-group' ? group : null;
radios.push({...radios[0]});
assert.equal(read().ok, false);
assert.equal(run({fields,operation:'apply',preimage:null}).ok, false);
assert.equal(writes, 4);
"""
    result = subprocess.run(["node", "-e", check], input=json.dumps(script), capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr


def test_path_b_freeze_preserves_all_reference_identities_and_final_provenance() -> None:
    from src.batch_edit.frozen_execution_contract import (
        FrozenExecutionContractError, compile_frozen_execution_payload,
        frozen_execution_defaults, validate_frozen_execution_defaults,
    )
    from src.batch_edit.plan_reference_store import ResolvedTemplateReferences
    from src.batch_edit.plan_snapshot_compiler import PlanSnapshotCompiler
    from src.batch_edit.plan_value_contract import PlanValueContract

    refs = ResolvedTemplateReferences([
        {'id': index, 'ref_type': 'attribute', 'dxm_template_id': str(100 + index),
         'shop_id': '7', 'category_id': '17', 'observed_display_name': f'Unit {index}',
         'source_digest': str(index) * 64, 'resolved_values_hash': 'A' * 64, 'availability': 'available',
         'audit_items_hash': canonical_sha256([] if index == 1 else ['unmapped']), 'audit_item_count': index - 1}
        for index in (1, 2)
    ], values=PlanValueContract(ValueError))
    legacy_refs = refs.frozen_summary()
    assert all(set(ref) == {'type', 'id', 'shop_id', 'category_id', 'observed_display_name',
                           'source_digest', 'resolved_values_hash', 'availability'} for ref in legacy_refs)
    full_refs = refs.frozen_summary(include_audit=True)
    assert [ref['ref_id'] for ref in full_refs] == [1, 2]
    assert full_refs[1]['audit_item_count'] == 1
    assert full_refs[1]['audit_items_hash'] == canonical_sha256(['unmapped'])
    sources = [('title', 'fixed_value', '9@v1#fixed', 'Unit title'),
               ('productUnit', 'dxm_template_ref', '101@' + '1' * 64, '1'),
               ('aeopAeProductSKUs', 'local_plan_template', '9@v1#set_each', [{'skuCode': 'UNIT-1'}])]
    schema = {'type': 'object', 'properties': {key: {'type': 'array' if isinstance(value, list) else 'string',
               'ui_binding': f'dxm_editor:{key}'} for key, _source, _ref, value in sources}}
    mapping = {'mapping_version': '1', 'entries': [{'field_key': key, 'ui_label_zh': key,
               'ui_binding': f'dxm_editor:{key}', 'category_schema_path': f'$.properties.{key}'}
               for key, _source, _ref, _value in sources]}
    resolution = {'resolved_fields': [{'field_key': key, 'source': source, 'source_ref': ref,
                  'resolved_value': value} for key, source, ref, value in sources],
                  'unresolved_fields': [], 'price_validation': {}}
    item = {'product_id': '81010001', 'categoryId': '17',
            'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
            'field_mapping': {**mapping, 'mapping_hash': canonical_sha256(mapping)},
            'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)}}
    task = {'payload': {'plan_snapshot': {'item_snapshots': [item], 'path': 'B', 'dxm_template_refs': full_refs}}}
    job = {'product_id': 81010001}
    payload = compile_frozen_execution_payload(task, job)
    assert payload['dxm_template_refs'] == full_refs and len(payload['dxm_template_refs']) == 2
    assert [(field['source'], field['source_ref']) for field in payload['fields']] == [(s, r) for _k, s, r, _v in sources]
    assert 'template_apply' not in payload and 'required_templates_applied' not in payload
    defaults = frozen_execution_defaults(payload)
    defaults['_path_a_fill_context'] = {'dxm_template_refs': [{'id': 'untrusted'}]}
    assert validate_frozen_execution_defaults(defaults, expected_payload=payload) == payload
    for target, key, value in [('ref', 'source_digest', 'B' * 64), ('ref', 'audit_item_count', 0),
                               ('field', 'source_ref', 'untrusted'), ('field', 'source', 'current')]:
        altered = deepcopy(defaults)
        frozen = altered['_frozen_execution_payload']
        entry = frozen['dxm_template_refs'][1] if target == 'ref' else frozen['fields'][0]
        entry[key] = value
        with pytest.raises(FrozenExecutionContractError):
            validate_frozen_execution_defaults(altered, expected_payload=payload)
    altered = deepcopy(defaults)
    altered['_frozen_execution_payload']['dxm_template_refs'].pop()
    body = {key: value for key, value in altered['_frozen_execution_payload'].items() if key != 'payload_hash'}
    altered['_frozen_execution_payload']['payload_hash'] = canonical_sha256(body)
    altered['_frozen_execution_payload_hash'] = canonical_sha256(body)
    with pytest.raises(FrozenExecutionContractError):
        validate_frozen_execution_defaults(altered, expected_payload=payload)
    tampered = deepcopy(task)
    tampered['payload']['plan_snapshot']['item_snapshots'][0]['resolution_result']['resolved_fields'][0]['source_ref'] = 'drift'
    with pytest.raises(FrozenExecutionContractError):
        compile_frozen_execution_payload(tampered, job)
    task['payload']['plan_snapshot']['path'] = 'A'
    legacy = compile_frozen_execution_payload(task, job)
    assert 'dxm_template_refs' not in legacy and 'execution_path' not in legacy
    assert all(set(field) == {'field_key', 'ui_label_zh', 'ui_binding', 'category_schema_path', 'resolved_value'}
               for field in legacy['fields'])
    assert 'frozen_summary(include_audit=True)' in inspect.getsource(PlanSnapshotCompiler.compile)


def test_path_b_audit_details_and_deferred_sources_survive_both_save_stages() -> None:
    from src.batch_edit.plan_contract import PlanContractError
    from src.batch_edit.plan_reference_store import ResolvedTemplateReferences
    from src.batch_edit.plan_snapshot_compiler import PlanSnapshotCompiler
    from src.batch_edit.plan_value_contract import PlanValueContract
    from src.batch_edit.frozen_execution_contract import (
        FrozenExecutionContractError, build_save2_stage_freeze, compile_frozen_execution_payload,
        frozen_execution_defaults, validate_frozen_execution_defaults,
    )

    audit = [{'kind': 'unmapped_custom_attribute', 'executable': False, 'source_index': 0,
              'attr_name': 'Unit unmapped', 'attr_value': 'Unit value',
              'reason_code': 'DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED'}]
    record = {'id': 41, 'ref_type': 'attribute', 'dxm_template_id': '101', 'shop_id': '91',
              'category_id': '101', 'source_digest': HASH_A, 'resolved_values_hash': HASH_B,
              'availability': 'available', 'audit_items_hash': canonical_sha256(audit),
              'audit_item_count': 1, '_audit_items': audit,
              '_resolved_values': {'semiManagedCode': 'Shared code', 'semiManagedJitStock': 8}}
    refs = ResolvedTemplateReferences([record], values=PlanValueContract(PlanContractError))
    summary = refs.frozen_summary(include_audit=True)
    assert summary[0]['audit_items'] == audit
    summary[0]['audit_items'][0]['attr_name'] = 'Changed copy'
    summary = refs.frozen_summary(include_audit=True)
    assert summary[0]['audit_items'] == audit and 'audit_items' not in refs.frozen_summary()[0]
    historical = deepcopy(record)
    historical.pop('_audit_items')
    assert 'audit_items' not in ResolvedTemplateReferences(
        [historical], values=PlanValueContract(PlanContractError)).frozen_summary(include_audit=True)[0]
    plan = {'id': 20, 'version': '1.3.0', 'path': 'B', 'status': 'ready', 'shop_id': '91',
            'category_ids': ['101'], 'configuration_contract': 'local_plan_template.v3',
            'semi_managed': {'enabled': True, 'freeze_timing': 'after_native_gate'},
            'fixed_values': {'publish_allowed': False, 'field_values': {'101': {'semiManagedJitStock': 100}}},
            'fill_rules': {'101': {}}, 'source_policies': {'101': {'semiManagedCost': 'current'}},
            'dxm_template_refs': [{'ref_id': 41, 'source_digest': HASH_A}], 'editor_actions': {}}
    properties = {key: {'type': kind, 'ui_binding': f'dxm_editor:{key}',
                       'ui_section': 'basic_info' if key == 'title' else 'semi_managed'}
                  for key, kind in [('title', 'string'), ('semiManagedJitStock', 'integer'),
                                    ('semiManagedCode', 'string'), ('semiManagedCost', 'number')]}
    schema = {'type': 'object', 'properties': properties, 'required': []}
    mapping = {'mapping_version': '1', 'entries': [
        {'field_key': key, 'ui_binding': value['ui_binding'], 'ui_label_zh': key,
         'category_schema_path': f'$.properties.{key}'} for key, value in properties.items()]}
    mapping['mapping_hash'] = canonical_sha256(mapping)
    resolved = [{'field_key': 'title', 'resolved_value': 'Shared title'}]
    authority = PlanSnapshotCompiler(PlanContractError, local_plan_store=None)._freeze_real_write_stage_authority(
        plan=plan, mapping=mapping, properties=properties, current_values={'title': 'Before'},
        resolved_fields=resolved, unresolved_fields=[],
        template_values=refs.values_for_category('101', allowed_fields=properties))
    policy_fields = authority['deferred_save2']['fields']
    assert [(field.get('source'), field.get('source_ref')) for field in policy_fields] == [
        ('fixed_value', '20@1.3.0#fixed'), ('dxm_template_ref', '101@' + HASH_A), (None, None)]
    assert policy_fields[2]['rule'] == {'source': 'current'}
    resolution = {'resolved_fields': resolved, 'unresolved_fields': [], 'price_validation': {}}
    item = {'product_id': '8101', 'shop_id': '91', 'categoryId': '101', 'target_identity_sha256': HASH_A,
            'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
            'field_mapping': mapping, 'current_value_snapshot': {'title': 'Before'},
            'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)}, **authority}
    task = {'id': 701, 'payload': {'plan_snapshot': {'path': 'B', 'snapshot_hash': HASH_B,
             'item_snapshots': [item], 'dxm_template_refs': summary},
             'real_dxm_write_authorization': {'scope_sha256': HASH_C}}}
    job = {'id': 801, 'product_id': 8101}
    gate = {'gate_outcome': 'admitted', 'same_handshake': True, 'semi_entry_triggered': True,
            'handshake_id': 'unit-entry', 'blocked': False}
    observation = {'product_id': '8101', 'shop_id': '91', 'target_identity_sha256': HASH_A,
        'page_url': 'https://www.dianxiaomi.com/web/smt/editFromSmt?id=8101',
        'browser_session_id': 'unit-session', 'observed_at': NOW, 'write_attempted': False,
        'values': {'semiManagedJitStock': 17, 'semiManagedCode': 'Before code', 'semiManagedCost': 3},
        'bindings': {field['field_key']: field['ui_binding'] for field in policy_fields},
        'evidence_ref': {'path': 'C:/unit/observation.png', 'sha256': HASH_D, 'size': 100}}
    seal = build_save2_stage_freeze(task, job, observation=observation, gate=gate, save1_receipt_sha256=HASH_D)
    task['_save2_freezes'] = {'801': seal}  # Pure projection only; no persistence or live acceptance claim.
    for stage in ('SAVE1', 'SAVE2'):
        payload = compile_frozen_execution_payload(task, job, save_stage=stage)
        assert payload['dxm_template_refs'] == summary
        assert payload['dxm_template_refs'][0]['audit_items'][0]['executable'] is False
        assert 'template_apply' not in payload and 'required_templates_applied' not in payload
        defaults = frozen_execution_defaults(payload)
        defaults['_frozen_execution_payload']['dxm_template_refs'][0]['audit_items'][0]['executable'] = True
        with pytest.raises(FrozenExecutionContractError):
            validate_frozen_execution_defaults(defaults, expected_payload=payload)
    late = compile_frozen_execution_payload(task, job, save_stage='SAVE2')
    assert [(field.get('source'), field.get('source_ref')) for field in late['fields']] == [
        ('fixed_value', '20@1.3.0#fixed'), ('dxm_template_ref', '101@' + HASH_A), (None, None)]
    for target in ('policy', 'seal'):
        altered = deepcopy(task)
        fields = (altered['payload']['plan_snapshot']['item_snapshots'][0]['deferred_save2']['fields']
                  if target == 'policy' else altered['_save2_freezes']['801']['fields'])
        fields[1]['source_ref'] = 'changed'
        with pytest.raises(FrozenExecutionContractError):
            compile_frozen_execution_payload(altered, job, save_stage='SAVE2')
    legacy = deepcopy(task)
    legacy['payload']['plan_snapshot'].pop('dxm_template_refs')
    policy = legacy['payload']['plan_snapshot']['item_snapshots'][0]['deferred_save2']
    for field in policy['fields']:
        field.pop('source', None)
        field.pop('source_ref', None)
    policy['policy_sha256'] = canonical_sha256({key: value for key, value in policy.items() if key != 'policy_sha256'})
    legacy['_save2_freezes']['801'] = build_save2_stage_freeze(
        legacy, job, observation=observation, gate=gate, save1_receipt_sha256=HASH_D)
    incomplete = compile_frozen_execution_payload(legacy, job, save_stage='SAVE2')
    assert 'dxm_template_refs' not in incomplete and all('source' not in field for field in incomplete['fields'])


def test_wholesale_observed_pair_readback_is_readonly_and_ambiguous_groups_fail() -> None:
    import subprocess
    from textwrap import dedent
    from src.execution.dxm_login_flow import DxmLoginFlow

    def js(method, prefix):
        tree = ast.parse(dedent(inspect.getsource(method)))
        return next(node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                    and isinstance(node.value, str) and node.value.startswith(prefix))

    scripts = [js(DxmLoginFlow._fill_frozen_execution_payload_on_page, '({fields, operation, preimage})'),
               js(DxmLoginFlow._observe_wholesale_enabled_control, '() =>')]
    check = r"""
const assert = require('node:assert/strict');
const [read, enabled] = JSON.parse(require('node:fs').readFileSync(0,'utf8')).map(script => new Function('return ('+script+')')());
let writes = 0;
const label = {textContent:'批发'};
const wrapper = {parentElement:{textContent:'%'}};
const input = (value, type='text') => ({value,type,checked:true,disabled:false,readOnly:false,tagName:'INPUT',
  getAttribute:key => key === 'type' ? type : null, hasAttribute:() => false,
  getBoundingClientRect:() => ({width:10,height:10}),
  closest:selector => selector === '.input-number-wrapper' ? wrapper : null,
  dispatchEvent:() => {writes++;}, focus:() => {writes++;}, scrollIntoView:() => {writes++;}});
const qty = input('3'), discount = input('10'), checkbox = input('on','checkbox');
const group = {getBoundingClientRect:() => ({width:100,height:20}),
  querySelectorAll:selector => selector.includes('w-100!') ? [qty] : selector.includes('w-140!') ? [discount]
    : selector.includes('checkbox') ? [checkbox] : [],
  querySelector:selector => selector === '.ant-form-item-label' ? label : group.querySelectorAll(selector)[0]};
let groups = [group];
global.getComputedStyle = () => ({display:'block',visibility:'visible'});
global.window = {getComputedStyle,HTMLInputElement:{prototype:{}}};
global.document = {querySelectorAll:selector => selector === '.ant-form-item' ? groups : []};
const fields = ['bulkOrder','bulkDiscount'].map((key,i) => ({field_key:key,ui_binding:'dxm_editor:'+key,resolved_value:i?10:3}));
const snapshot = () => read({fields,operation:'readback',preimage:null});
assert.equal(snapshot().ok,true);
assert.deepEqual(snapshot().observations.map(value => value.value),['3','10']);
assert.deepEqual(enabled(),{ui_binding:'dxm_editor:wholesale.enabled',found:true,match_count:1,
 visible:true,checked:true,discount_unit:'%',quantity_enabled:true,discount_enabled:true});
qty.disabled = true; discount.disabled = true; checkbox.checked = false;
assert.equal(enabled().checked,false);
assert.equal(enabled().quantity_enabled,false);
assert.equal(snapshot().ok,true); // Reads retain actual disabled/empty controls; never enable them.
assert.equal(read({fields,operation:'preflight',preimage:null}).ok,false);
groups = [group,group];
assert.equal(snapshot().ok,false);
assert.equal(enabled().found,false);
groups = [group]; label.textContent = 'Something else';
assert.equal(snapshot().ok,false);
assert.equal(enabled().found,false);
assert.equal(writes,0);
"""
    result = subprocess.run(['node', '-e', check], input=json.dumps(scripts), capture_output=True,
                            text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stderr
    source = inspect.getsource(DxmLoginFlow.validate_editor_wholesale)
    assert "operation='readback'" in source and "operation='apply'" not in source
    assert '_prepare_frozen_execution_page_for_save' not in source
    assert "deepcopy(prepared['writer'])" in source
    fill_source = inspect.getsource(DxmLoginFlow._prepare_frozen_execution_page_for_save)
    assert fill_source.index('SAVE1_PREFILL_WRITER_CONTEXT_MISSING') < fill_source.index("prepared['attempted'] = True")
    assert fill_source.index("prepared['writer'] =") > fill_source.index("prepared['result'] = result")


def test_wholesale_fresh_contract_rejects_missing_changed_and_reused_evidence() -> None:
    from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
    from src.batch_edit.wholesale_filler import (
        WHOLESALE_POSTCONDITIONS, build_editor_wholesale_receipt, validate_editor_wholesale_observation,
    )
    from src.execution.action_result_contract import ActionResultContractError, validate_action_result_envelope
    from src.execution.browser_agent_protocol import build_frozen_product_target_identity

    target = build_frozen_product_target_identity(product_id='81010001', store_name='Contract Shop',
        source_urls=['https://detail.1688.com/offer/81010001.html'])
    rows = [{'skuCode': f'UNIT-{i}', 'skuPrice': '10.00', 'cargoPrice': '4.00', 'ipmSkuStock': 10,
             'aeopSKUProperty': [{'skuPropertyId': '1', 'propertyValueId': str(i)}]} for i in (1, 2)]
    values = {'bulkOrder': 3, 'bulkDiscount': 10, 'reduceStrategy': 'payment_success_deduct',
              'aeopAeProductSKUs': rows, 'title': 'Original shared input'}
    payload = {'schema': 'dxm.batch_draft_save.execution_payload.v1', 'execution_path': 'B',
        'product_id': '81010001', 'category_id': '16', 'target_category': {'category_id': '17'},
        'category_schema_hash': HASH_A, 'unresolved_fields': [],
        'editor_actions': _shared_required_editor_actions_plan()['editor_actions']['17'],
        'fields': [{'field_key': key, 'ui_binding': 'dxm_editor:'+key, 'ui_label_zh': key,
                    'resolved_value': value} for key, value in values.items()]}
    payload['payload_hash'] = canonical_sha256(payload)
    defaults = frozen_execution_defaults(payload)
    command = {'command_id': 'wholesale-command', 'action': 'validate_editor_wholesale',
        'state': 'BATCH_WHOLESALE_FILL', 'task_id': 701, 'job_id': 801,
        'runtime_id': 'unit-runtime', 'browser_session_id': 'unit-session'}
    context = {**command, 'command_action': command['action'], 'mode': 'batch_draft_save'}
    fill = {'ok': True, 'execution_payload_hash': payload['payload_hash'], 'field_count': len(values),
        'write_attempted': False, 'fields': [{'field_key': field['field_key'], 'ui_binding': field['ui_binding'],
            'ok': True, 'write_attempted': False} for field in payload['fields']]}
    snapshot = {'category_schema': {'schema': 'dxm.editor.category_schema_readback.v1', 'ok': True,
        'phase': 'wholesale_finalize', 'expected_category_id': '17', 'observed_category_id': '17',
        'expected_category_schema_hash': HASH_A, 'observed_category_schema_hash': HASH_A,
        'category_source': 'dom:value', 'reason': None},
        'enabled_control': {'ui_binding': 'dxm_editor:wholesale.enabled', 'found': True, 'match_count': 1,
            'visible': True, 'checked': True, 'discount_unit': '%', 'quantity_enabled': True, 'discount_enabled': True},
        'fields': [{'field_key': key, 'ui_binding': 'dxm_editor:'+key, 'found': True,
            'value': str(value) if key in ('bulkOrder', 'bulkDiscount') else deepcopy(value),
            'match_count': 2 if key in ('reduceStrategy', 'aeopAeProductSKUs') else 1,
            'aggregate_kind': 'sku_rows' if key == 'aeopAeProductSKUs' else 'choice_group' if key == 'reduceStrategy' else 'single'}
            for key, value in values.items() if key != 'title']}
    observed = {'schema': 'dxm.editor_wholesale_observation.v1', 'command': command, 'target_identity': target,
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=81010001', 'execution_payload_hash': payload['payload_hash'],
        'started_at': NOW, 'completed_at': EXPIRES_AT, 'write_attempted': False,
        'before': deepcopy(snapshot), 'after': deepcopy(snapshot),
        'writer': {'command': {**command, 'command_id': 'original-fill', 'action': 'fill_editor_required_defaults',
            'state': 'FILL_BASE_INFO'}, 'execution_payload_hash': payload['payload_hash'],
            'fill_result_hash': canonical_sha256(fill), 'fill_result': fill},
        'evidence_ref': {'path': 'C:/unit/wholesale.png', 'sha256': HASH_D, 'size': 100}}
    validate = lambda item: validate_editor_wholesale_observation(item, defaults=defaults,
        expected_payload=payload, target_identity=target, command_context=context)
    assert validate(observed) == observed
    receipt = build_editor_wholesale_receipt(validate(observed))
    assert receipt['canonical_receipt']['action_grant_id'] == 'wholesale-command'
    assert len(receipt['canonical_receipt']['field_readbacks']) == 4
    assert receipt['canonical_receipt']['field_readbacks'][0]['before_value'] == '3'

    for change in (
        lambda x: x.update(write_attempted=True),
        lambda x: x['after']['fields'].pop(),
        lambda x: x['after']['fields'][0].update(value='4'),
        lambda x: x['command'].update(command_id='original-fill'),
        lambda x: x['writer']['command'].update(command_id='wholesale-command'),
        lambda x: x['writer']['command'].update(browser_session_id='other'),
        lambda x: x['writer']['fill_result'].update(write_attempted=True),
        lambda x: x.update(execution_payload_hash=HASH_C),
        lambda x: x.update(page_url='https://www.dianxiaomi.com/web/smt/edit?id=81010002'),
        lambda x: x.update(completed_at=ISSUED_AT),
        lambda x: x['evidence_ref'].update(size=0),
    ):
        bad = deepcopy(observed)
        change(bad)
        with pytest.raises(ValueError):
            validate(bad)
    for change in (
        lambda x: x['enabled_control'].update(checked=False),
        lambda x: x['enabled_control'].update(discount_unit='USD'),
        lambda x: x['enabled_control'].update(quantity_enabled=False),
        lambda x: x['category_schema'].update(observed_category_id='16'),
        lambda x: x['fields'][0].update(value=' 3 '),
        lambda x: x['fields'][0].update(value=True),
        lambda x: x['fields'][2].update(aggregate_kind='single'),
        lambda x: x['fields'][3].update(match_count=1),
        lambda x: x['fields'][3]['value'][0].update(cargoPrice='40.00'),
    ):
        bad = deepcopy(observed)
        change(bad['before']); change(bad['after'])
        with pytest.raises(ValueError):
            validate(bad)
    envelope = {'schema_version': 'dxm.action-result.v1', 'ok': True, 'action': command['action'],
        'attempted_state': command['state'], 'before_values': {'defaults': defaults, 'target_identity': target},
        'after_values': {'wholesale_readback': observed['after']},
        'postconditions': {key: True for key in WHOLESALE_POSTCONDITIONS},
        'evidence': {'observations': {'wholesale_observation': observed,
            'mandatory_capability_receipts': {'wholesale': receipt}}, 'refs': []},
        'page_identity': {'kind': 'editor', 'url': observed['page_url'], 'runtime_id': 'unit-runtime',
            'browser_session_id': 'unit-session'}, 'failure_code': None,
        'recoverability': {'kind': 'none', 'retryable': False, 'requires_page_reverify': False, 'reason': None}}
    assert validate_action_result_envelope(envelope, execution_mode='batch_draft_save', expected_execution_payload=payload)['ok']
    bad = deepcopy(envelope)
    bad['evidence']['observations']['mandatory_capability_receipts']['wholesale']['canonical_receipt']['field_readbacks'] = []
    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(bad, execution_mode='batch_draft_save', expected_execution_payload=payload)


def test_wholesale_runner_requires_actual_first_fill_and_unique_command_receipt() -> None:
    from src.batch_edit.full_product_edit_orchestrator import ProductEditContext
    from src.execution.v1_runner import BATCH_PATH_B_STEPS, PATH_B_SAVE1_DISCOVERY_STEPS, V1TaskRunner, V1ExecutionError
    from src.execution.browser_agent_worker import execute_browser_agent_action
    from src.execution.dxm_adapter import DxmWorkflowAdapter

    runner = object.__new__(V1TaskRunner)  # Pure collector only: no Adapter, repository or worker instance.
    command = {'command_id': 'wholesale-only', 'action': 'validate_editor_wholesale',
        'state': 'BATCH_WHOLESALE_FILL', 'execution_mode': 'batch_draft_save',
        'task_id': 701, 'job_id': 801, 'runtime_id': 'unit-runtime'}
    fill_command = {**command, 'command_id': 'original-fill', 'action': 'fill_editor_required_defaults', 'state': 'FILL_BASE_INFO'}
    fill = {'ok': True, 'field_count': 1, 'fields': [{'field_key': 'unit', 'ok': True}]}
    prior = [{'browser_agent_command': fill_command, 'action_result': {
        'ok': True, 'action': 'fill_editor_required_defaults', 'attempted_state': 'FILL_BASE_INFO',
        'page_identity': {'browser_session_id': 'unit-session'},
        'evidence': {'observations': {'editor_action_result': {'execution_payload_hash': HASH_A,
            'preflight_results': {'frozen_execution': fill}}}}}}]
    writer = {'command': {key: value for key, value in fill_command.items() if key != 'execution_mode'},
        'fill_result': fill, 'fill_result_hash': canonical_sha256(fill), 'execution_payload_hash': HASH_A}
    writer['command']['browser_session_id'] = 'unit-session'
    wrapper = {'canonical_receipt': {'action_grant_id': 'wholesale-only'}, 'receipt_sha256': HASH_C}
    current = {'browser_agent_command': command, 'action_result': {'ok': True,
        'attempted_state': 'BATCH_WHOLESALE_FILL', 'action': 'validate_editor_wholesale',
        'page_identity': {'browser_session_id': 'unit-session'}, 'evidence': {'observations': {
            'wholesale_observation': {'writer': writer}, 'mandatory_capability_receipts': {'wholesale': wrapper}}}}}
    ctx = ProductEditContext(product_id='81010001', shop_id='91')
    record = lambda context, state, result, history: runner._record_path_b_phase_result(
        FullProductEditOrchestrator, context, state, result, history)
    record(ctx, StateName.BATCH_WHOLESALE_FILL, current, prior)
    assert ctx.metadata['path_b_receipts']['capabilities']['wholesale'] == wrapper
    with pytest.raises(V1ExecutionError, match='WHOLESALE_RECEIPT_ALREADY_RECORDED'):
        record(ctx, StateName.BATCH_WHOLESALE_FILL, current, prior)
    for history in ([], prior + prior):
        with pytest.raises(V1ExecutionError, match='WHOLESALE_ORIGINAL_FILL_REQUIRED'):
            record(ProductEditContext(product_id='81010001', shop_id='91'), StateName.BATCH_WHOLESALE_FILL, current, history)
    bad = deepcopy(current)
    bad['action_result']['evidence']['observations']['wholesale_observation']['writer']['command']['command_id'] = 'other-fill'
    with pytest.raises(V1ExecutionError, match='WHOLESALE_ORIGINAL_FILL_DRIFT'):
        record(ProductEditContext(product_id='81010001', shop_id='91'), StateName.BATCH_WHOLESALE_FILL, bad, prior)
    with pytest.raises(V1ExecutionError, match='WHOLESALE_COMMAND_RECEIPT_MISMATCH'):
        record(ProductEditContext(product_id='81010001', shop_id='91'), StateName.FILL_BASE_INFO, current, prior)
    assert 'adapter.validate_editor_wholesale(' in inspect.getsource(execute_browser_agent_action)
    assert 'self.login_flow.validate_editor_wholesale(' in inspect.getsource(DxmWorkflowAdapter.validate_editor_wholesale)
    assert 'compile_frozen_execution_payload(task, job' in inspect.getsource(V1TaskRunner._build_browser_agent_command)
    # Wiring alone must not activate a truncated mandatory sequence.
    for steps in (BATCH_PATH_B_STEPS, PATH_B_SAVE1_DISCOVERY_STEPS):
        assert StateName.BATCH_WHOLESALE_FILL not in [step[0] for step in steps]


def test_shared_field_delegation_is_explicit_and_hash_bound() -> None:
    from src.batch_edit.plan_template_contract import normalize_field_mapping, PlanTemplateContractError

    entry = {'field_key': 'videoUrl', 'ui_binding': 'dxm_editor:videoUrl',
        'ui_label_zh': '产品视频', 'category_schema_path': '$.properties.videoUrl',
        'delegated_to': 'content_finalize.video'}
    mapping = {'mapping_version': '1.0.0', 'entries': [entry]}
    schema = {'properties': {'videoUrl': {'type': 'string', 'ui_binding': 'dxm_editor:videoUrl',
        'ui_control': 'media', 'ui_section': 'product_info'}}}
    normalized = normalize_field_mapping(mapping, category_id='17', schema=schema)
    assert normalized['entries'][0]['delegated_to'] == 'content_finalize.video'
    plain = deepcopy(mapping); plain['entries'][0].pop('delegated_to')
    assert normalized['mapping_hash'] != normalize_field_mapping(plain, category_id='17', schema=schema)['mapping_hash']
    for value in ('content_finalize.wholesale', 'content_finalize.publish', '', True, ['content_finalize.video']):
        bad = deepcopy(mapping); bad['entries'][0]['delegated_to'] = value
        with pytest.raises(PlanTemplateContractError):
            normalize_field_mapping(bad, category_id='17', schema=schema)


def test_common_output_policy_survives_compile_without_overwriting_input_values() -> None:
    from src.batch_edit.frozen_execution_contract import (
        build_content_finalize_policy, compile_frozen_execution_payload, frozen_execution_defaults,
        FrozenExecutionContractError,
    )
    from src.batch_edit.plan_template_contract import normalize_field_mapping, normalize_local_plan_payload, PlanTemplateContractError
    from src.batch_edit.plan_snapshot_compiler import PlanSnapshotCompiler

    definitions = {
        'videoUrl': {'type': 'string', 'ui_binding': 'dxm_editor:videoUrl', 'ui_control': 'media', 'ui_section': 'product_info'},
        'title': {'type': 'string', 'ui_binding': 'dxm_editor:title', 'natural_language': True, 'ui_section': 'basic_info'},
        'code': {'type': 'string', 'ui_binding': 'dxm_editor:code', 'ui_section': 'product_info'},
    }
    schema = {'type': 'object', 'properties': definitions, 'required': []}
    entries = [{'field_key': key, 'ui_binding': definition['ui_binding'], 'ui_label_zh': '字段',
        'category_schema_path': '$.properties.'+key,
        **({'delegated_to': 'content_finalize.'+('video' if key == 'videoUrl' else 'translation')} if key != 'code' else {})}
        for key, definition in definitions.items()]
    raw_mapping = {'mapping_version': '2.0.0', 'entries': entries}
    mapping = normalize_field_mapping(raw_mapping, category_id='17', schema=schema)
    values = {'videoUrl': 'https://unit.invalid/old.mp4', 'title': 'Initial title', 'code': 'UNIT-1'}
    resolution = {'resolved_fields': [{'field_key': key, 'resolved_value': value} for key, value in values.items()],
        'unresolved_fields': [], 'price_validation': {}}
    item = {'product_id': '81010001', 'shop_id': '91', 'categoryId': '17',
        'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
        'field_mapping': mapping, 'current_value_snapshot': deepcopy(values),
        'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)},
        'real_write_stage_fields': {'SAVE1': list(values), 'SAVE2': []}}
    actions = _shared_required_editor_actions_plan()['editor_actions']['17']
    original = deepcopy(item)
    policy = build_content_finalize_policy(item, editor_actions=actions, source_sha256=HASH_B)
    assert item == original
    assert policy['order'] == ['video', 'wholesale', 'translation']
    assert [field['field_key'] for field in policy['fields']] == ['videoUrl', 'title']
    item['content_finalize_policy'] = policy
    task = {'id': 701, 'payload': {'plan_snapshot': {'path': 'B', 'snapshot_hash': HASH_A,
        'plan_content_sha256': HASH_B, 'editor_actions': {'17': actions}, 'item_snapshots': [item]}}}
    job = {'id': 801, 'product_id': 81010001}
    payload = compile_frozen_execution_payload(task, job)
    assert payload['content_finalize_policy'] == policy
    assert [field.get('delegated_to') for field in payload['fields']] == ['content_finalize.video', 'content_finalize.translation', None]
    defaults = frozen_execution_defaults(payload)
    assert {key: defaults[key] for key in values} == values
    assert item['current_value_snapshot'] == values
    changed = deepcopy(task)
    changed['payload']['plan_snapshot']['item_snapshots'][0]['content_finalize_policy']['fields'][0]['delegated_to'] = 'content_finalize.translation'
    with pytest.raises(FrozenExecutionContractError, match='output ownership differs'):
        compile_frozen_execution_payload(changed, job)
    for change in (
        lambda x: x['category_schema']['normalized_schema']['properties']['title'].update(natural_language=False),
        lambda x: x['category_schema']['normalized_schema']['properties']['title'].update(readOnly=True),
        lambda x: x['real_write_stage_fields']['SAVE1'].remove('title'),
        lambda x: x['field_mapping']['entries'][1].update(delegated_to='content_finalize.video'),
    ):
        bad = deepcopy(item); change(bad)
        with pytest.raises(FrozenExecutionContractError):
            build_content_finalize_policy(bad, editor_actions=actions, source_sha256=HASH_B)
    shared = _shared_required_editor_actions_plan()
    shared.pop('id')
    shared['field_mappings']['17'] = raw_mapping
    normalized = normalize_local_plan_payload(shared)
    assert normalized['field_mappings']['17']['entries'][0]['delegated_to'] == 'content_finalize.video'
    shared['editor_actions']['17']['video']['enabled'] = False
    with pytest.raises(PlanTemplateContractError):
        normalize_local_plan_payload(shared)
    assert 'content_finalize_mappings' in inspect.getsource(PlanSnapshotCompiler._freeze_plan_content)


def test_content_finalize_candidate_preserves_preimages_and_rejects_unowned_or_identity_changes() -> None:
    from src.batch_edit.frozen_execution_contract import build_content_finalize_policy, build_content_finalize_stage_freeze, FrozenExecutionContractError

    values = {'videoUrl': 'https://unit.invalid/old.mp4', 'title': 'Initial title',
        'bulkOrder': 3, 'bulkDiscount': 10, 'reduceStrategy': 'payment_success_deduct',
        'aeopAeProductSKUs': [{'skuId': 'UNIT-1', 'name': 'Initial name', 'price': 10}]}
    row_schema = {'type': 'object', 'properties': {'skuId': {'type': 'string', 'readOnly': True},
        'name': {'type': 'string', 'natural_language': True}, 'price': {'type': 'integer'}}}
    definitions = {key: {'type': 'array' if key == 'aeopAeProductSKUs' else 'integer' if type(value) is int else 'string',
        'ui_binding': 'dxm_editor:'+key, 'ui_section': 'product_info',
        **({'ui_control': 'media'} if key == 'videoUrl' else {}),
        **({'natural_language': True} if key == 'title' else {}),
        **({'items': row_schema} if key == 'aeopAeProductSKUs' else {})} for key, value in values.items()}
    schema = {'type': 'object', 'properties': definitions}
    entries = [{'field_key': key, 'ui_binding': 'dxm_editor:'+key, 'ui_label_zh': '字段',
        'category_schema_path': '$.properties.'+key,
        **({'delegated_to': 'content_finalize.video'} if key == 'videoUrl' else
           {'delegated_to': 'content_finalize.translation'} if key in {'title', 'aeopAeProductSKUs'} else {})} for key in values]
    mapping = {'mapping_version': '2', 'entries': entries}
    resolution = {'resolved_fields': [{'field_key': key, 'resolved_value': value} for key, value in values.items()],
        'unresolved_fields': [], 'price_validation': {}}
    item = {'product_id': '81010001', 'shop_id': '91', 'categoryId': '17', 'target_identity_sha256': HASH_C,
        'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
        'field_mapping': {**mapping, 'mapping_hash': canonical_sha256(mapping)},
        'current_value_snapshot': {**deepcopy(values), 'title': 'Original preimage'},
        'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)},
        'real_write_stage_fields': {'SAVE1': list(values), 'SAVE2': []}}
    actions = _shared_required_editor_actions_plan()['editor_actions']['17']
    item['content_finalize_policy'] = build_content_finalize_policy(item, editor_actions=actions, source_sha256=HASH_B)
    task = {'id': 701, 'payload': {'real_dxm_write_authorization': {'scope_sha256': HASH_D},
        'plan_snapshot': {'path': 'B', 'snapshot_hash': HASH_A, 'plan_content_sha256': HASH_B,
                          'editor_actions': {'17': actions}, 'item_snapshots': [item]}}}
    job = {'id': 801, 'product_id': 81010001}
    after = deepcopy(values); after.update(videoUrl='https://unit.invalid/generated.mp4', title='Translated title')
    after['aeopAeProductSKUs'][0]['name'] = 'Translated name'
    observation = {'product_id': '81010001', 'shop_id': '91', 'browser_session_id': 'unit-session',
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=81010001', 'target_identity_sha256': HASH_C,
        'observed_at': EXPIRES_AT, 'values': after, 'bindings': {key: 'dxm_editor:'+key for key in values},
        'write_attempted': False, 'evidence_ref': {'path': 'C:/unit/after-actions.png', 'sha256': HASH_D, 'size': 100}}

    def receipts_for(result):
        receipts = {}
        groups = {'video': ['videoUrl'], 'wholesale': ['bulkOrder', 'bulkDiscount', 'reduceStrategy', 'aeopAeProductSKUs'],
                  'translation': ['title', 'aeopAeProductSKUs']}
        for index, (action, keys) in enumerate(groups.items()):
            start, end = f'2026-08-31T00:0{index+1}:00Z', f'2026-08-31T00:0{index+1}:30Z'
            receipt = ContentFinalizeReceipt(phase=ReceiptPhase('content_finalize_'+action), action_grant_id='unit-'+action,
                result_ok=True, started_at=start, completed_at=end,
                media_identity=result['videoUrl'] if action == 'video' else None,
                field_readbacks=[FieldReadback(field_key=key, field_label='字段', source='pure_contract_only',
                    before_value=deepcopy(values[key]), after_value=deepcopy(values[key] if action == 'wholesale' else result[key]),
                    readback_proven=True, timestamp=end) for key in keys])
            digest = receipt.finalize()
            receipts[action] = {'canonical_receipt': receipt.to_dict(), 'receipt_sha256': digest}
        return receipts

    original = deepcopy(task)
    seal = build_content_finalize_stage_freeze(task, job, observation=observation, receipts=receipts_for(after))
    assert task == original and item['current_value_snapshot']['title'] == 'Original preimage'
    assert seal['fields'][1]['resolved_value'] == 'Translated title'
    assert seal['initial_execution_payload_hash'] != seal['freeze_sha256']
    for change in (
        lambda x: x['values'].update(bulkOrder=4),
        lambda x: x['values']['aeopAeProductSKUs'][0].update(skuId='OTHER'),
        lambda x: x['values']['aeopAeProductSKUs'][0].update(price=99),
        lambda x: x['values']['aeopAeProductSKUs'].append(deepcopy(x['values']['aeopAeProductSKUs'][0])),
        lambda x: x['values'].update(title='仍是中文'),
        lambda x: x.update(page_url='https://www.dianxiaomi.com/web/smt/edit?id=81010002'),
        lambda x: x.update(write_attempted=True),
        lambda x: x.update(observed_at=NOW),
        lambda x: x['bindings'].update(title='dxm_editor:other'),
    ):
        bad = deepcopy(observation); change(bad)
        with pytest.raises(ValueError):
            build_content_finalize_stage_freeze(task, job, observation=bad, receipts=receipts_for(bad['values']))
    missing = receipts_for(after); missing.pop('wholesale')
    with pytest.raises(FrozenExecutionContractError, match='all three ordered'):
        build_content_finalize_stage_freeze(task, job, observation=observation, receipts=missing)
    wrong_owner = receipts_for(after)
    wrong_owner['translation']['canonical_receipt']['field_readbacks'].pop()
    with pytest.raises(ValueError):
        build_content_finalize_stage_freeze(task, job, observation=observation, receipts=wrong_owner)


def test_shared_generated_scope_preserves_inputs_and_rejects_per_product_rules() -> None:
    import subprocess
    from pydantic import ValidationError
    from src.models import RealDxmPathBFieldHashBinding

    facts = _scope_facts(); facts['schema'] = 'real_dxm_write_scope.v3'
    generated = {'field': 'videoUrl', 'saveStage': 'SAVE1', 'freezeAt': 'after_content_finalize',
        'delegatedTo': 'content_finalize.video', 'ruleSha256': HASH_D,
        'preimageSha256': HASH_A, 'inputSha256': HASH_B}
    for index, product in enumerate(facts['orderedProducts']):
        product['allowedFields'] = [deepcopy(generated),
            {**generated, 'field': 'title', 'delegatedTo': 'content_finalize.translation', 'preimageSha256': canonical_sha256(index)},
            {'field': 'bulkOrder', 'saveStage': 'SAVE1', 'preimageSha256': HASH_A, 'expectedSha256': HASH_B},
            {'field': 'semi_goods', 'saveStage': 'SAVE2', 'freezeAt': 'after_native_gate', 'ruleSha256': HASH_C}]
    scope = prepare_real_dxm_write_scope(facts, now=NOW)
    assert validate_real_dxm_write_scope(scope, now=NOW) == scope
    assert scope['orderedProducts'] == facts['orderedProducts']
    for product in scope['orderedProducts']:
        for binding in product['allowedFields']:
            assert RealDxmPathBFieldHashBinding(**binding).model_dump(exclude_none=True) == binding
    for change in (
        lambda x: x.update(schema='real_dxm_write_scope.v1'),
        lambda x: x.update(schema='real_dxm_write_scope.v2'),
        lambda x: x['orderedProducts'][0]['allowedFields'][0].update(expectedSha256=HASH_C),
        lambda x: x['orderedProducts'][0]['allowedFields'][0].pop('inputSha256'),
        lambda x: x['orderedProducts'][0]['allowedFields'][0].update(freezeAt='after_native_gate'),
        lambda x: x['orderedProducts'][0]['allowedFields'][0].update(delegatedTo='content_finalize.translation'),
        lambda x: x['orderedProducts'][0]['allowedFields'][1].update(delegatedTo='content_finalize.publish'),
        lambda x: x['orderedProducts'][1]['allowedFields'][1].update(ruleSha256=HASH_A),
        lambda x: x['orderedProducts'][1]['allowedFields'].pop(1),
        lambda x: x['orderedProducts'][1]['allowedFields'][1].update(field='other_text'),
    ):
        bad = deepcopy(facts); change(bad)
        with pytest.raises(RealDxmWriteScopeError):
            prepare_real_dxm_write_scope(bad, now=NOW)
    altered = deepcopy(scope); altered['orderedProducts'][0]['allowedFields'][0]['inputSha256'] = HASH_C
    with pytest.raises(RealDxmWriteScopeError, match='SCOPE_HASH_MISMATCH'):
        validate_real_dxm_write_scope(altered, now=NOW)
    for bad in ({**generated, 'expectedSha256': None}, {**generated, 'inputSha256': None},
                {**generated, 'saveStage': 'SAVE2'}, {**generated, 'delegatedTo': 'content_finalize.translation'}):
        with pytest.raises(ValidationError):
            RealDxmPathBFieldHashBinding(**bad)
    schema = json.loads((REPO_ROOT / 'config/real_dxm_write_scope.schema.json').read_text(encoding='utf-8'))
    definition = schema['$defs']['contentFinalizeField']
    assert set(definition['required']) == set(definition['properties']) == set(generated)
    assert definition['additionalProperties'] is False
    assert definition['if']['properties']['delegatedTo']['const'] == 'content_finalize.video'
    assert definition['then']['properties']['field']['const'] == 'videoUrl'
    # Existing v1/v2 branches remain restrictive; no legacy green test is rerun.
    legacy = schema['$defs']['writeScope']['allOf'][0]
    assert legacy['else']['properties']['orderedProducts']['items']['properties']['allowedFields']['items']['then']['$ref'] == '#/$defs/deferredSave2Field'
    request = {'schemaVersion': 'real_dxm_path_b_prepare_request.v1', 'localPlanTemplateId': 20, 'shopId': '91',
        'sessionRef': 'a'*16, 'idempotencyKey': 'content-unit-once', 'prepareKey': 'content-unit-prepare', 'validForSeconds': 300,
        'orderedProducts': [{'productId': p['productId'], 'fieldHashBindings': p['allowedFields']} for p in facts['orderedProducts']]}
    source_path = str(REPO_ROOT / 'scripts/run-real-dxm-path-b-system-test.ps1').replace("'", "''")
    check = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$tokens=$null; $errors=$null
$tree=[System.Management.Automation.Language.Parser]::ParseFile('SOURCE_PATH',[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw $errors[0].Message }
$names=@('Assert-AllowedProperties','Assert-NoWildcards','Assert-PrepareRequest')
$nodes=$tree.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -in $names},$true)
if ($nodes.Count -ne 3) { throw 'pure functions missing' }
foreach($node in $nodes) { Invoke-Expression $node.Extent.Text }
$request=[Console]::In.ReadToEnd() | ConvertFrom-Json
Assert-PrepareRequest -Request $request
$request.orderedProducts[0].fieldHashBindings[0].inputSha256=''
$rejected=$false
try { Assert-PrepareRequest -Request $request } catch { $rejected=$true }
if (-not $rejected) { throw 'missing input was accepted' }
'CONTENT_PREPARE_PURE_OK'
""".replace('SOURCE_PATH', source_path)
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', check],
        input=json.dumps(request), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and 'CONTENT_PREPARE_PURE_OK' in result.stdout, result.stderr


def test_content_scope_projection_keeps_preimages_and_closes_unpersisted_save() -> None:
    from src.batch_edit.frozen_execution_contract import (
        build_content_finalize_policy, frozen_scope_field_bindings, compile_frozen_execution_payload,
        FrozenExecutionContractError,
    )
    from src.batch_edit.plan_template_contract import normalize_local_plan_payload, PlanTemplateContractError
    from src.execution import batch_dispatch_authority
    from src.execution.v1_runner import V1TaskRunner

    values = {'videoUrl': 'https://unit.invalid/input.mp4', 'title': 'Shared input', 'bulkOrder': 3, 'semi_goods': 4}
    definitions = {key: {'type': 'integer' if type(value) is int else 'string', 'ui_binding': 'dxm_editor:'+key,
        'ui_section': 'semi_managed' if key == 'semi_goods' else 'product_info',
        **({'ui_control': 'media'} if key == 'videoUrl' else {}), **({'natural_language': True} if key == 'title' else {})}
        for key, value in values.items()}
    schema = {'type': 'object', 'properties': definitions}
    entries = [{'field_key': key, 'ui_binding': definition['ui_binding'], 'ui_label_zh': '字段',
        'category_schema_path': '$.properties.'+key,
        **({'delegated_to': 'content_finalize.'+('video' if key == 'videoUrl' else 'translation')} if key in {'videoUrl', 'title'} else {})}
        for key, definition in definitions.items()]
    mapping = {'mapping_version': 'unit.v3', 'entries': entries}
    resolution = {'resolved_fields': [{'field_key': key, 'resolved_value': value} for key, value in values.items()],
                  'unresolved_fields': [], 'price_validation': {}}
    item = {'product_id': '81010001', 'shop_id': '91', 'categoryId': '17',
        'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
        'field_mapping': {**mapping, 'mapping_hash': canonical_sha256(mapping)},
        'current_value_snapshot': {**values, 'title': 'Original text'},
        'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)},
        'real_write_stage_fields': {'SAVE1': ['videoUrl', 'title', 'bulkOrder'], 'SAVE2': ['semi_goods']}}
    actions = _shared_required_editor_actions_plan()['editor_actions']['17']
    item['content_finalize_policy'] = build_content_finalize_policy(item, editor_actions=actions, source_sha256=HASH_B)
    before = deepcopy(item)
    fields = frozen_scope_field_bindings(item)
    assert fields[1]['preimageSha256'] == canonical_sha256('Original text')
    assert fields[1]['inputSha256'] == canonical_sha256('Shared input')
    assert 'expectedSha256' not in fields[1] and fields[1]['freezeAt'] == 'after_content_finalize'
    assert fields[2]['expectedSha256'] == canonical_sha256(3) and 'freezeAt' not in fields[2]
    assert item == before
    for change in (lambda x: x.pop('content_finalize_policy'),
                   lambda x: x['content_finalize_policy'].update(policy_sha256=HASH_C),
                   lambda x: x['field_mapping']['entries'][0].pop('delegated_to'),
                   lambda x: x['current_value_snapshot'].pop('title')):
        bad = deepcopy(item); change(bad)
        with pytest.raises(FrozenExecutionContractError):
            frozen_scope_field_bindings(bad)
    task = {'payload': {'plan_snapshot': {'path': 'B', 'plan_content_sha256': HASH_B,
        'editor_actions': {'17': actions}, 'item_snapshots': [item]}}}
    job = {'id': 801, 'product_id': 81010001}
    assert compile_frozen_execution_payload(task, job)['fields'][1]['resolved_value'] == 'Shared input'
    for candidate in (None, {'freeze_sha256': HASH_C, 'fields': []}):
        task['_content_finalize_freezes'] = {'801': candidate}
        with pytest.raises(FrozenExecutionContractError, match='persisted, independently verified'):
            compile_frozen_execution_payload(task, job, for_save=True)
    assert 'for_save=True' in inspect.getsource(V1TaskRunner._build_browser_agent_command)
    assert 'for_save=True' in inspect.getsource(batch_dispatch_authority._validate_execution)
    tree = ast.parse((REPO_ROOT / 'app/backend/src/main.py').read_text(encoding='utf-8-sig'))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == 'compile_frozen_execution_payload']
    assert len(calls) == 1 and any(k.arg == 'for_save' and isinstance(k.value, ast.Constant) and k.value.value is True for k in calls[0].keywords)
    shared = _shared_required_editor_actions_plan(); shared.pop('id')
    shared['field_mappings']['17'] = {'mapping_version': 'unit.v3', 'entries': entries}
    for invalid in (None, [], True, 'not-config'):
        shared['editor_actions']['17']['video'] = invalid
        with pytest.raises(PlanTemplateContractError):
            normalize_local_plan_payload(shared)


def test_browser_action_source_reads_actual_worker_files_without_resigning_them(tmp_path, monkeypatch) -> None:
    from src.execution import browser_agent_worker as worker

    monkeypatch.setattr(worker, 'DATA_DIR', tmp_path)
    command = BrowserAgentCommand(command_id='a'*32, idempotency_key='unit-editor-once', deadline=EXPIRES_AT,
        expected_page='editor', runtime_id='unit-runtime', task_id=701, job_id=801, state='FILL_BASE_INFO',
        action='fill_editor_required_defaults', execution_mode='batch_draft_save', params={})
    # A failed synthetic ActionResult checks file lineage, not business success.
    envelope = {'schema_version': 'dxm.action-result.v1', 'ok': False, 'action': command.action,
        'attempted_state': command.state, 'before_values': {}, 'after_values': {}, 'postconditions': {},
        'evidence': {'observations': {}, 'refs': []}, 'page_identity': {'kind': 'editor',
            'url': 'https://www.dianxiaomi.com/web/smt/edit?id=81010001', 'runtime_id': 'unit-runtime', 'browser_session_id': 'unit-session'},
        'failure_code': 'UNIT_EDITOR_REJECTED', 'recoverability': {'kind': 'terminal', 'retryable': False,
            'requires_page_reverify': False, 'reason': 'Synthetic rejected attempt'}}
    artifacts = worker._prepare_action_artifacts(command, command_id=command.command_id)
    result = {'ok': True, 'result': envelope, 'transport': {'command_id': command.command_id,
        'idempotency_key': command.idempotency_key, 'runtime_id': command.runtime_id,
        'workflow_trace_file': str(artifacts['trace_file']), 'browser_agent_request_file': str(artifacts['request_file']),
        'browser_agent_result_file': str(artifacts['result_file'])}}
    worker._write_action_result(artifacts['result_file'], result)
    initial = {key: artifacts[key].read_bytes() for key in ('request_file', 'result_file')}
    source = worker.load_browser_agent_action_source(command.to_payload(), envelope, browser_session_id='unit-session')
    assert source['request']['sha256'] == hashlib.sha256(initial['request_file']).hexdigest().upper()
    assert source['result']['sha256'] == hashlib.sha256(initial['result_file']).hexdigest().upper()
    assert source['result']['size'] == len(initial['result_file'])
    assert {key: artifacts[key].read_bytes() for key in initial} == initial
    bad = deepcopy(envelope); bad['failure_code'] = 'OTHER_FAILURE'
    with pytest.raises(ValueError, match='SOURCE_RESULT_DRIFT'):
        worker.load_browser_agent_action_source(command.to_payload(), bad, browser_session_id='unit-session')
    bad_command = command.to_payload(); bad_command['params'] = {'caller_value': 'not-original'}
    with pytest.raises(ValueError, match='SOURCE_REQUEST_DRIFT'):
        worker.load_browser_agent_action_source(bad_command, envelope, browser_session_id='unit-session')
    with pytest.raises(ValueError, match='session'):
        worker.load_browser_agent_action_source(command.to_payload(), envelope, browser_session_id='other-session')
    for change in (lambda x: x.update(ok=False), lambda x: x['transport'].update(command_id='b'*32),
                   lambda x: x['transport'].update(browser_agent_result_file=str(tmp_path / 'elsewhere.json'))):
        bad_result = deepcopy(result); change(bad_result)
        worker._write_action_result(artifacts['result_file'], bad_result)
        with pytest.raises(ValueError):
            worker.load_browser_agent_action_source(command.to_payload(), envelope, browser_session_id='unit-session')
    artifacts['result_file'].unlink()
    with pytest.raises(ValueError, match='SOURCE_FILE_UNAVAILABLE'):
        worker.load_browser_agent_action_source(command.to_payload(), envelope, browser_session_id='unit-session')


def test_editor_attempt_is_persisted_once_with_worker_and_snapshot_sources(contract_db, tmp_path, monkeypatch) -> None:
    from src import repository as repository_module
    from src.execution import browser_agent_worker as worker
    from src.execution.v1_runner import V1TaskRunner
    from src.batch_edit.frozen_execution_contract import compile_frozen_execution_payload, frozen_execution_defaults, frozen_scope_field_bindings

    monkeypatch.setattr(worker, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(repository_module, 'now_iso', lambda: NOW)
    _insert_draft_batch_task(701)
    values = {'title': 'Shared input', 'semi_goods': 2}
    properties = {key: {'type': 'string' if key == 'title' else 'integer', 'ui_binding': 'dxm_editor:'+key,
        'ui_section': 'basic_info' if key == 'title' else 'semi_managed'} for key in values}
    schema = {'type': 'object', 'properties': properties}
    mapping = {'mapping_version': 'unit.v1', 'entries': [{'field_key': key, 'ui_binding': definition['ui_binding'],
        'ui_label_zh': '字段', 'category_schema_path': '$.properties.'+key} for key, definition in properties.items()]}
    resolution = {'resolved_fields': [{'field_key': key, 'resolved_value': value} for key, value in values.items()],
                  'unresolved_fields': [], 'price_validation': {}}
    products = [81010001, 81010002, 81010003]
    items = []
    for product in products:
        target = {'schema_version': 'dxm_draft_box_target.v1',
            'store_fingerprint': canonical_sha256({'source': 'structured_store_cell', 'store_name': 'Contract Shop'}),
            'stable_identity': {'kind': 'product_id', 'value': str(product),
                                'fingerprint': hashlib.sha256(f'product_id:{product}'.encode()).hexdigest().upper()},
            'source_urls': ['https://detail.1688.com/offer/810100010001.html']}
        items.append({'product_id': str(product), 'shop_id': '91', 'categoryId': '17', 'target_identity': target,
            'target_identity_sha256': canonical_sha256(target), 'current_value_snapshot': deepcopy(values),
            'category_schema': {'normalized_schema': schema, 'schema_hash': canonical_sha256(schema)},
            'field_mapping': {**mapping, 'mapping_hash': canonical_sha256(mapping)},
            'resolution_result': {**resolution, 'resolution_hash': canonical_sha256(resolution)},
            'real_write_stage_fields': {'SAVE1': ['title'], 'SAVE2': ['semi_goods']}})
    plan = {'path': 'B', 'publish_allowed': False, 'local_plan_template': {'id': 20},
            'product_ids': [str(p) for p in products], 'item_snapshots': items}
    plan['snapshot_hash'] = canonical_sha256(plan)
    facts = _scope_facts(); facts['snapshot']['snapshotSha256'] = plan['snapshot_hash']
    for product, item in zip(facts['orderedProducts'], items):
        product.update(productId=int(item['product_id']), allowedFields=frozen_scope_field_bindings(item))
    scope = prepare_real_dxm_write_scope(facts, now=NOW)
    repo = Repository()
    assert repo.prepare_real_dxm_write_scope(scope)['ok'] is True
    payload = {'path': 'B', 'execution_mode': 'batch_draft_save', 'publish_allowed': False, 'product_ids': products,
        'plan_snapshot_id': 601, 'plan_snapshot_hash': plan['snapshot_hash'], 'plan_snapshot': plan,
        'real_dxm_write_authorization': {'scope_sha256': scope['scopeSha256']}}
    with db.connection() as conn:
        conn.execute("UPDATE tasks SET status='running', payload_json=? WHERE id=701", (db.dumps(payload),))
        for index, product in enumerate(products):
            conn.execute('INSERT INTO jobs(id,task_id,product_id,status,current_step_code,created_at,updated_at) VALUES(?,701,?,?,?,?,?)',
                (801+index, product, 'running' if index == 0 else 'pending', 'FILL_BASE_INFO' if index == 0 else None, NOW, NOW))
        conn.execute('INSERT INTO plan_snapshots(id,local_plan_template_id,snapshot_hash,snapshot_json,created_at,task_id,idempotency_key) VALUES(601,20,?,?,?,701,?)',
            (plan['snapshot_hash'], db.dumps(plan), ISSUED_AT, 'unit-editor-freeze'))
        conn.execute('INSERT INTO plan_snapshot_idempotency_keys(idempotency_key,snapshot_id,snapshot_hash,created_at) VALUES(?,601,?,?)',
            ('unit-editor-freeze', plan['snapshot_hash'], ISSUED_AT))
        conn.execute("UPDATE real_dxm_write_scopes SET status='consumed' WHERE scope_sha256=?", (scope['scopeSha256'],))
    task = repo.get_task_private(701); job = task['jobs'][0]
    defaults = frozen_execution_defaults(compile_frozen_execution_payload(task, job))
    runtime, session = scope['runtime']['browserRuntimeId'], scope['runtime']['browserSessionId']
    command = BrowserAgentCommand(command_id='c'*32, idempotency_key='unit-editor-source', deadline=EXPIRES_AT,
        expected_page='editor', runtime_id=runtime, task_id=701, job_id=801, state='FILL_BASE_INFO',
        action='fill_editor_required_defaults', execution_mode='batch_draft_save',
        params={'defaults': defaults, 'target_identity': items[0]['target_identity'], 'store_name': 'Contract Shop', 'product_query': str(products[0])})
    # A persisted rejected attempt must remain rejected, with no business receipt.
    envelope = {'schema_version': 'dxm.action-result.v1', 'ok': False, 'action': command.action,
        'attempted_state': command.state, 'before_values': {}, 'after_values': {}, 'postconditions': {},
        'evidence': {'observations': {}, 'refs': []}, 'page_identity': {'kind': 'editor',
            'url': 'https://www.dianxiaomi.com/web/smt/edit?id=81010001', 'runtime_id': runtime, 'browser_session_id': session},
        'failure_code': 'UNIT_EDITOR_REJECTED', 'recoverability': {'kind': 'terminal', 'retryable': False,
            'requires_page_reverify': False, 'reason': 'Synthetic rejected attempt'}}
    artifacts = worker._prepare_action_artifacts(command, command_id=command.command_id)
    worker._write_action_result(artifacts['result_file'], {'ok': True, 'result': envelope, 'transport': {
        'command_id': command.command_id, 'idempotency_key': command.idempotency_key, 'runtime_id': runtime,
        'workflow_trace_file': str(artifacts['trace_file']), 'browser_agent_request_file': str(artifacts['request_file']),
        'browser_agent_result_file': str(artifacts['result_file'])}})
    with db.connection() as conn:
        conn.execute("UPDATE jobs SET current_step_code='FILL_VARIANTS' WHERE id=801")
    with pytest.raises(ValueError, match='EDITOR_SOURCE_STATE_INVALID'):
        repo.persist_path_b_editor_source(701, 801, command.to_payload(), envelope)
    with db.connection() as conn:
        conn.execute("UPDATE jobs SET current_step_code='FILL_BASE_INFO' WHERE id=801")
    record = repo.persist_path_b_editor_source(701, 801, command.to_payload(), envelope)
    assert record['action_result']['ok'] is False and record['command'] == command.to_payload()
    assert record['source_sha256'] == canonical_sha256({key: value for key, value in record.items() if key != 'source_sha256'})
    with pytest.raises(ValueError, match='EDITOR_SOURCE_ALREADY_RECORDED'):
        repo.persist_path_b_editor_source(701, 801, command.to_payload(), envelope)
    with db.connection() as conn:
        rows = conn.execute("SELECT meta_json FROM job_evidences WHERE evidence_type='path_b_editor_source'").fetchall()
        assert len(rows) == 1 and db.loads(rows[0]['meta_json'], {}) == record
        assert conn.execute('SELECT count(*) AS n FROM canonical_receipts').fetchone()['n'] == 0
        assert conn.execute('SELECT count(*) AS n FROM mutation_dispatch_ledger').fetchone()['n'] == 0
    source = inspect.getsource(V1TaskRunner._run_workflow_action_browser_agent)
    assert source.index('persist_path_b_editor_source(') < source.index('validated_result = self._validate_workflow_action_result(')


def test_wholesale_memory_and_persistence_use_the_same_first_writer_binding() -> None:
    from src.batch_edit.wholesale_filler import validate_wholesale_first_fill_source
    from src.execution.v1_runner import V1TaskRunner

    command = {'command_id': 'd'*32, 'action': 'validate_editor_wholesale', 'state': 'BATCH_WHOLESALE_FILL',
               'execution_mode': 'batch_draft_save', 'task_id': 701, 'job_id': 801, 'runtime_id': 'unit-runtime'}
    first_command = {**command, 'command_id': 'c'*32, 'action': 'fill_editor_required_defaults', 'state': 'FILL_BASE_INFO'}
    fill = {'ok': True, 'fields': [{'field_key': 'unit-field', 'before_value': 'one', 'after_value': 'two'}]}
    # Only provenance is exercised. No Adapter, screenshot, or production success is created.
    first = {'browser_agent_command': first_command, 'action_result': {'ok': True,
        'action': first_command['action'], 'attempted_state': first_command['state'],
        'page_identity': {'browser_session_id': 'unit-session'}, 'evidence': {'observations': {
            'editor_action_result': {'execution_payload_hash': HASH_A, 'preflight_results': {'frozen_execution': fill}}}}}}
    writer = {'command': {key: first_command[key] for key in ('command_id', 'action', 'state', 'task_id', 'job_id', 'runtime_id')},
              'fill_result': fill, 'fill_result_hash': canonical_sha256(fill), 'execution_payload_hash': HASH_A}
    writer['command']['browser_session_id'] = 'unit-session'
    before = deepcopy(first)
    validate_wholesale_first_fill_source(writer, first, command=command, browser_session_id='unit-session')
    assert first == before
    for change in (lambda x: x['action_result'].update(ok=False),
                   lambda x: x['browser_agent_command'].update(command_id=command['command_id']),
                   lambda x: x['browser_agent_command'].update(job_id=802),
                   lambda x: x['action_result']['page_identity'].update(browser_session_id='other-session'),
                   lambda x: x['action_result']['evidence']['observations']['editor_action_result'].update(execution_payload_hash=HASH_B),
                   lambda x: x['action_result']['evidence']['observations']['editor_action_result']['preflight_results']['frozen_execution'].update(ok=False)):
        bad = deepcopy(first); change(bad)
        with pytest.raises(ValueError, match='WHOLESALE_ORIGINAL_FILL'):
            validate_wholesale_first_fill_source(writer, bad, command=command, browser_session_id='unit-session')
    assert 'validate_wholesale_first_fill_source(' in inspect.getsource(V1TaskRunner._record_path_b_phase_result)
    persisted = inspect.getsource(Repository.persist_path_b_editor_source)
    assert 'validate_wholesale_first_fill_source(' in persisted
    assert "parent.get('artifacts') != load_browser_agent_action_source(" in persisted
    assert "parent.get('action_result', {}).get('ok') is not True" in persisted


def test_content_surface_reads_real_control_shapes_without_clicks_or_certification() -> None:
    import subprocess
    from src.execution.editor_readonly_inspection import EDITOR_CONTENT_ACTION_SURFACE_SCRIPT
    from src.execution.dxm_login_flow import DxmLoginFlow

    check = r"""
const assert = require('node:assert/strict');
const read = new Function('return ('+JSON.parse(require('node:fs').readFileSync(0,'utf8'))+')')();
const fail = () => { throw Error('readonly surface attempted a write'); };
const node = (tag,text='',classes=[]) => ({tagName:tag.toUpperCase(),innerText:text,disabled:false,width:10,
  getBoundingClientRect(){return {width:this.width,height:10};},
  getAttribute:key => null,classList:{contains:value => classes.includes(value)},
  querySelectorAll(){return [];},querySelector(selector){return this.querySelectorAll(selector)[0]||null;},
  click:fail,focus:fail,setAttribute:fail,dispatchEvent:fail});
global.getComputedStyle = () => ({display:'block',visibility:'visible'});
let roots = [], queries = {};
const root = node('div'); root.querySelectorAll = selector => queries[selector]||[];
global.document = {querySelectorAll:() => roots};
roots = [root];
const type = node('label','普通翻译',['ant-radio-button-wrapper-checked']);
const radio = Object.assign(node('input'),{value:'1',checked:true});
type.querySelectorAll = () => [radio];
const language = node('li','中文 → 英文');
language.querySelectorAll = selector => selector === '.panel-language-title' ? [node('div','中文 → 英文')] : [];
queries = {
  '.panel-translate-type .ant-radio-button-wrapper':[type],
  '.panel-language-list > .panel-language-item':[language],
  '.panel-content-main > span:not(.panel-content-edit)':[node('span','标题、自定义属性、自定义名称、PC端描述、无线端描述')]
};
let result = read('translation');
assert.equal(result.types.matches[0].value,'1');
assert.equal(result.types.matches[0].checked,true);
assert.deepEqual(result.languages.matches[0].titles,['中文 → 英文']);
assert.equal(result.content.matches.length,1);
radio.disabled = true; assert.equal(read('translation').types.matches[0].disabled,true);
type.querySelectorAll = () => [radio,radio];
assert.equal(read('translation').types.matches[0].value,null);
const generate = node('button','生成视频');
const image = Object.assign(node('img'),{getAttribute:key => key === 'src' ? 'https://unit.invalid/image.jpg' : null,
  currentSrc:'https://unit.invalid/image.jpg',complete:true,naturalWidth:800,naturalHeight:800});
const picture = node('li'); picture.querySelectorAll = () => [image];
const transition = node('li','自然',['activeName']); transition.querySelectorAll = () => [node('div','自然')];
queries = {
  '.img-translate-video':[node('div')],
  '.ant-modal-header .title-right button.btn-orange':[generate],
  '.ant-modal-header .title-right > .gray-c':[node('span','今日免费次数：2')],
  '.img-translate-video .content-imgs > li':[picture],
  '.img-translate-video .page-content_right-top .content-list > li':[transition]
};
result = read('video');
assert.equal(result.images.matches[0].images[0].natural_width,800);
assert.equal(result.transitions.matches[0].selected,true);
assert.equal(result.music.matches.length,0);
assert.equal(result.generate.matches[0].text,'生成视频');
assert.equal(result.execution_allowed,false); assert.equal(result.write_attempted,false);
image.complete=false; image.currentSrc='';
assert.equal(read('video').images.matches[0].images[0].current_src,null);
assert.equal(read('video').images.matches[0].images[0].complete,false);
roots=[root,root]; result=read('video');
assert.equal(result.surface_match_count,2); assert.equal('generate' in result,false);
root.width=0; assert.equal(read('video').surface_match_count,0);
assert.equal(read('publish').execution_allowed,false);
"""
    result = subprocess.run(['node', '-e', check], input=json.dumps(EDITOR_CONTENT_ACTION_SURFACE_SCRIPT),
                            capture_output=True, text=True, encoding='utf-8', timeout=15)
    assert result.returncode == 0, result.stderr
    source = inspect.getsource(DxmLoginFlow.inspect_editor_readonly)
    assert 'page.evaluate(EDITOR_CONTENT_ACTION_SURFACE_SCRIPT, observe_dialog)' in source
    assert source.count('button.click(') == 1
    assert "'executionAllowed': False, 'capabilityCertified': False" in source
    assert "'contentSurface': content_surface" in source
def test_content_commands_share_scope_authority_and_keep_save_leases_separate(contract_db, monkeypatch):
    from src.execution.batch_command_contract import BatchCommandContractError, validate_path_b_save1_discovery_dispatch
    from dataclasses import replace
    from src import repository as repository_module
    from src.batch_edit.plan_snapshot_store import PlanSnapshotStore
    from src.batch_edit.plan_snapshot_compiler import plan_snapshot_sha256
    from src.batch_edit.frozen_execution_contract import build_content_finalize_policy, frozen_scope_field_bindings, frozen_execution_defaults, compile_frozen_execution_payload
    from src.execution import batch_dispatch_authority as authority, mutation_dispatch_ledger as ledger_module
    from src.execution import browser_agent_worker as worker
    from src.execution.browser_agent_protocol import CONTENT_MUTATION_COMMANDS, build_frozen_product_target_identity, validate_browser_agent_command
    from src.execution.v1_runner import V1TaskRunner
    from src.state_machine.batch_draft_authorization import build_batch_draft_save_task_facts, build_authorization_context

    from tests.support.content_authority_case import content_dispatch_case

    case = content_dispatch_case(monkeypatch)
    repo, store, products = case['repository'], case['store'], case['products']
    task, live, current_live = case['task'], case['live'], case['current_live']
    ledger, dispatch, runner = case['ledger'], case['dispatch'], case['runner']
    original_leases = case['original_leases']
    commands = []
    for state, (action, mutation) in CONTENT_MUTATION_COMMANDS.items():
        task = repo.get_task_private(task['id'])
        job = task['jobs'][0]
        assert repo.update_job(job['id'], status='running', current_step_code=state, current_step_name='unit content')
        task = repo.get_task_private(task['id']); job = task['jobs'][0]
        with pytest.raises(BatchCommandContractError):
            validate_path_b_save1_discovery_dispatch(task, job_id=job['id'], command_state='SAVE2_ONLY', command_action='save_only')
        with pytest.raises(BatchCommandContractError):
            validate_path_b_save1_discovery_dispatch(task, job_id=task['jobs'][1]['id'], command_state=state, command_action=action)
        defaults = frozen_execution_defaults(compile_frozen_execution_payload(task, job))
        spec = runner._workflow_action_worker_request(task, job, StateName(state), defaults)
        assert spec[0] == action and spec[3]['shop_id'] == str(store['id'])
        command = runner._build_browser_agent_command(task, job, StateName(state), action, spec[3])
        assert validate_browser_agent_command(command) == {mutation: 1}
        assert command.authorization_lease_id not in {lease['lease_id'] for lease in original_leases}
        assert dict(worker._MUTATION_ACTION_SEQUENCE_BY_STATE[state]) == {mutation: 1}
        assert worker._is_phase_specific_path_b_command(command)
        identity = {'browser_session_id': live.browser_session_id, 'page_kind': 'editor',
            'page_url': f'https://www.dianxiaomi.com/web/smt/edit?id={products[0]}', 'target_hash': command.target_hash}
        assert dispatch.reserve_command(command).ok
        current_live[0] = replace(live, account_ref_hash=HASH_C)
        denied = dispatch.begin_dispatch(command, mutation, identity)
        assert not denied.ok and denied.reason_code == 'AUTH_REAL_WRITE_SCOPE_BINDING_MISMATCH'
        assert ledger.get_entry(command.mutation_scope_id, mutation)['status'] == 'RESERVED'
        current_live[0] = live
        begun = dispatch.begin_dispatch(command, mutation, identity)
        assert begun.ok, begun.reason_code
        stored = ledger.get_entry(command.mutation_scope_id, mutation)
        frozen = json.loads(stored['save_authority_json'])
        assert authority._validated_authority(frozen) == frozen
        assert frozen['authorization']['lease_authority']['action_state'] == state
        assert frozen['authorization']['lease_authority']['parent_lease_id'] == original_leases[0]['lease_id']
        assert not dispatch.begin_dispatch(command, mutation, identity).ok
        assert dispatch.mark_dispatched(command, mutation, {'unit_callback_returned': True}).ok
        assert not dispatch.mark_dispatched(command, mutation, {'unit_callback_returned': True}).ok
        commands.append(command)
    assert len({command.authorization_lease_id for command in commands}) == 3
    assert repo.get_task_private(task['id'])['payload']['real_dxm_write_authorization']['save_leases'] == original_leases
    assert worker._mark_batch_save_unknown(ledger, commands[-1], phase='unit-failure', failure={'failure_code': 'CONTENT_RESULT_MISSING'})
    assert ledger.recover_inflight() == 2
    for command in commands:
        mutation = CONTENT_MUTATION_COMMANDS[command.state][1]
        assert ledger.get_entry(command.mutation_scope_id, mutation)['status'] == 'UNKNOWN'
        assert not dispatch.begin_dispatch(command, mutation, identity).ok
    with db.connection() as conn:
        assert conn.execute('SELECT count(*) AS n FROM canonical_receipts').fetchone()['n'] == 0
        assert conn.execute("SELECT count(*) AS n FROM mutation_dispatch_ledger WHERE command_state IN ('SAVE_ONLY','SAVE2_ONLY','FIRST_SAVE_INTENT')").fetchone()['n'] == 0
    assert RELEASED_PLAN_EXECUTION_PATHS == frozenset({'A'})

def test_native_translation_preparation_uses_shared_scope_and_never_dispatches():
    from copy import deepcopy
    from types import SimpleNamespace
    from src.batch_edit.translator import prepare_native_translation, validate_native_translation_surface

    config = {'enabled': True, 'translate_type': 'normal', 'direction': 'zh_en',
              'apply_to': ['title', 'attributes', 'description_pc', 'description_mobile', 'custom_name']}
    labels = '标题、自定义属性、自定义名称、PC端描述、无线端描述'
    surface = {'schema': 'dxm.editor_content_surface.v1', 'action': 'translation',
        'surface_match_count': 1, 'write_attempted': False, 'execution_allowed': False,
        'types': {'matches': [{'text': '普通翻译', 'value': '1', 'input_match_count': 1,
                              'visible': True, 'disabled': False, 'selected': True, 'checked': True}]},
        'languages': {'matches': [{'visible': True, 'disabled': False, 'titles': ['中文 → 英文'],
                                  'descriptions': ['点击该行即执行；将翻译：' + labels]}]},
        'content': {'matches': [{'visible': True, 'text': labels}]}}
    original = deepcopy(surface)
    assert validate_native_translation_surface(surface, config) == surface
    assert surface == original
    for mutate in (
        lambda s: s.update(surface_match_count=2),
        lambda s: s['types']['matches'][0].update(checked=False),
        lambda s: s['types']['matches'][0].update(disabled=True),
        lambda s: s['content']['matches'][0].update(text=labels + '、SKU编码'),
        lambda s: s['content']['matches'][0].update(text=labels + '、标题'),
        lambda s: s['languages']['matches'].append(deepcopy(s['languages']['matches'][0])),
        lambda s: s['languages']['matches'][0].update(descriptions=['点击该行即执行；将翻译：标题']),
    ):
        bad = deepcopy(surface); mutate(bad)
        with pytest.raises(ValueError, match='TRANSLATION_'):
            validate_native_translation_surface(bad, config)

    events = []
    class Control:
        def __init__(self, kind): self.kind = kind
        def count(self): return 1
        def is_visible(self): return True
        def is_enabled(self): return True
        def filter(self, **kwargs): return self
        def inner_text(self): return '普通翻译'
        def wait_for(self, **kwargs): events.append('wait_visible')
        def click(self, **kwargs):
            assert self.kind in {'entry', 'normal'}, 'preparation dispatched translation'
            events.append(self.kind)
            if self.kind == 'normal':
                surface['types']['matches'][0].update(selected=True, checked=True)
        def locator(self, selector):
            return Control('normal' if 'input[type="radio"][value="1"]' in selector else 'language')
    def locator(selector):
        return Control('entry' if 'button.translation-btn' in selector else 'surface')
    page = SimpleNamespace(locator=locator, evaluate=lambda script, action: deepcopy(surface))
    surface['types']['matches'][0].update(selected=False, checked=False)
    result = prepare_native_translation(page, config)
    assert result == original and events == ['entry', 'wait_visible', 'normal']
    events.clear()
    for bad_config in ({}, {**config, 'direction': 'en_zh'}, {**config, 'translate_type': 'ai'}):
        with pytest.raises(ValueError):
            prepare_native_translation(page, bad_config)
    assert events == []

def test_native_translation_network_binds_responses_and_blocks_late_fallbacks():
    from types import SimpleNamespace
    from src.batch_edit.translator import NativeTranslationNetwork
    from src.batch_edit.scope_contract import canonical_sha256

    calls, handlers = [], {}
    page = SimpleNamespace(url='https://www.dianxiaomi.com/web/smt/edit?id=101',
        on=lambda event, fn: handlers.update({event: fn}),
        remove_listener=lambda event, fn: handlers.pop(event))
    page.context = SimpleNamespace(route=lambda pattern, fn: handlers.update(route=fn),
        unroute=lambda pattern, fn: handlers.pop('route'))
    body = {'module': '速卖通产品', 'textList': ['测试商品'], 'sourceLanguage': 'zh', 'targetLanguage': 'en'}
    def request(url=NativeTranslationNetwork.URL, payload=None):
        return SimpleNamespace(url=url, method='POST', resource_type='xhr',
            frame=SimpleNamespace(page=page), post_data_buffer=json.dumps(body if payload is None else payload).encode())
    def route(req):
        return SimpleNamespace(request=req, abort=lambda: calls.append('abort'), fallback=lambda: calls.append('continue'))
    def response(req, value, status=200):
        raw = json.dumps(value).encode()
        return SimpleNamespace(request=req, url=req.url, status=status, body=lambda: raw)

    window = NativeTranslationNetwork(page, allowed_texts=['测试商品'], readonly_requests=set())
    window.install()
    first = request()
    handlers['route'](route(first))
    assert calls == ['abort'] and window.failure_code == 'TRANSLATION_REQUEST_BEFORE_AUTHORIZATION'
    window.close()
    window = NativeTranslationNetwork(page, allowed_texts=['测试商品'], readonly_requests=set())
    window.install(); window.arm()
    first = request(); handlers['route'](route(first))
    assert calls[-1] == 'continue' and window.pending_count == 1
    with pytest.raises(ValueError, match='TRANSLATION_NETWORK_PENDING'):
        window.evidence()
    handlers['response'](response(first, {'code': 0, 'data': ['Test product']}))
    evidence = window.evidence()
    assert evidence['request_count'] == 1 and evidence['events'][0]['response']['data'] == ['Test product']
    assert evidence['events'][0]['request_sha256'] == canonical_sha256(body)
    # Two native field handlers may submit identical text; each physical request is retained.
    second = request(); handlers['route'](route(second))
    handlers['response'](response(second, {'code': 0, 'data': ['Test product']}))
    assert window.evidence()['request_count'] == 2
    window.seal()
    handlers['route'](route(request()))
    assert calls[-1] == 'abort' and window.failure_code == 'TRANSLATION_REQUEST_AFTER_SEAL'
    window.close()

    for invalid in ({'code': False, 'data': ['Test product']}, {'code': 9, 'data': []},
                    {'code': 0, 'data': []}, {'code': 0, 'data': ['仍是中文']}):
        window = NativeTranslationNetwork(page, allowed_texts=['测试商品'], readonly_requests=set())
        window.install(); window.arm()
        req = request(); handlers['route'](route(req)); handlers['response'](response(req, invalid))
        with pytest.raises(ValueError, match='TRANSLATION_'):
            window.evidence()
        handlers['route'](route(request('https://translate.volcengine.com/crx/translate/v2/')))
        assert calls[-1] == 'abort'
        handlers['route'](route(request()))
        assert calls[-1] == 'abort'  # Native delayed retry cannot escape the failed window.
        window.close()
    window = NativeTranslationNetwork(page, allowed_texts=['测试商品'], readonly_requests=set())
    window.install(); window.arm()
    handlers['route'](route(request(payload={**body, 'textList': ['其它商品']})))
    assert window.failure_code == 'TRANSLATION_REQUEST_SCOPE_MISMATCH'
    assert window.pending_count == 0 and calls[-1] == 'abort'
    window.close()
    assert handlers == {}

def test_native_translation_readback_requires_provider_values_and_preserves_structure():
    from copy import deepcopy
    from src.batch_edit.scope_contract import canonical_sha256
    from src.batch_edit.translator import (
        NativeTranslationNetwork, native_translation_texts, validate_native_translation_values,
    )
    text = {'type': 'string', 'natural_language': True}
    sku = {'type': 'array', 'items': {'type': 'object', 'properties': {
        'id': {'type': 'string'}, 'label': text, 'price': {'type': 'integer'}}}}
    before = {'title': '测试商品', 'detail': '<p>红色</p>', 'skus': [{'id': 'one', 'label': '红色', 'price': 10}], 'stock': 3}
    after = {'title': 'Test product', 'detail': '<p>Red</p>', 'skus': [{'id': 'one', 'label': 'Red', 'price': 10}], 'stock': 3}
    definitions = {'title': text, 'detail': text, 'skus': sku}
    policy = {'schema': 'dxm.content_finalize_policy.v1', 'fields': [
        {'field_key': key, 'delegated_to': 'content_finalize.translation', 'property_schema': definition}
        for key, definition in definitions.items()]}
    policy['policy_sha256'] = canonical_sha256(policy)
    payload = {'execution_path': 'B', 'content_finalize_policy': policy, 'fields': [
        {'field_key': key, 'resolved_value': value,
         **({'delegated_to': 'content_finalize.translation'} if key in definitions else {})}
        for key, value in before.items()]}
    request = {'module': '速卖通产品', 'textList': ['测试商品', '红色'], 'sourceLanguage': 'zh', 'targetLanguage': 'en'}
    response = {'code': 0, 'data': ['Test product', 'Red']}
    network = {'request_count': 1, 'events': [{'sequence': 1, 'completed': True,
        'url': NativeTranslationNetwork.URL, 'method': 'POST', 'status': 200, 'request': request, 'response': response,
        'request_sha256': canonical_sha256(request), 'response_sha256': canonical_sha256(response),
        'request_body_sha256': HASH_A, 'response_body_sha256': HASH_B}]}
    assert validate_native_translation_values(payload, before, after, network) == after
    assert native_translation_texts(before['skus'], sku) == ['红色']
    assert native_translation_texts('测试商品', {**text, 'readOnly': True}) == []
    assert native_translation_texts('测试商品', {**text, 'enum': ['测试商品']}) == []
    for mutate in (
        lambda value: value.update(title='Unrelated English text'),
        lambda value: value.update(detail='<p>Green</p>'),
        lambda value: value.update(stock=4),
        lambda value: value['skus'][0].update(price=11),
        lambda value: value['skus'][0].update(id='other'),
        lambda value: value['skus'].append(deepcopy(value['skus'][0])),
        lambda value: value.update(extra='unapproved'),
    ):
        bad = deepcopy(after); mutate(bad)
        with pytest.raises(ValueError, match='TRANSLATION_'):
            validate_native_translation_values(payload, before, bad, network)
    for mutate in (
        lambda value: value.update(request_count=0),
        lambda value: value['events'][0].update(completed=False),
        lambda value: value['events'][0]['request'].update(targetLanguage='zh'),
        lambda value: value['events'][0]['response'].update(code=False),
    ):
        bad = deepcopy(network); mutate(bad)
        with pytest.raises(ValueError, match='TRANSLATION_'):
            validate_native_translation_values(payload, before, after, bad)
    assert before['title'] == '测试商品' and payload['fields'][0]['resolved_value'] == '测试商品'


def test_native_translation_observation_and_action_contract_bind_the_actual_dispatch():
    from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
    from src.batch_edit.translator import (
        NativeTranslationNetwork, NATIVE_TRANSLATION_POSTCONDITIONS,
        validate_editor_translation_observation, build_editor_translation_receipt,
    )
    from src.execution.action_result_contract import ActionResultContractError, validate_action_result_envelope
    from src.execution.browser_agent_protocol import build_frozen_product_target_identity
    from src.execution.dxm_login_flow import DxmLoginFlow
    from src.execution.dxm_adapter import DxmWorkflowAdapter
    from src.execution.browser_agent_worker import execute_browser_agent_action

    target = build_frozen_product_target_identity(product_id='81010001', store_name='Contract Shop',
        source_urls=['https://detail.1688.com/offer/81010001.html'])
    policy = {'schema': 'dxm.content_finalize_policy.v1', 'fields': [
        {'field_key': 'title', 'delegated_to': 'content_finalize.translation',
         'property_schema': {'type': 'string', 'natural_language': True}}]}
    policy['policy_sha256'] = canonical_sha256(policy)
    payload = {'schema': 'dxm.batch_draft_save.execution_payload.v1', 'execution_path': 'B',
        'product_id': '81010001', 'content_finalize_policy': policy,
        'editor_actions': _shared_required_editor_actions_plan()['editor_actions']['17'],
        'fields': [{'field_key': 'title', 'ui_binding': 'dxm_editor:title', 'ui_label_zh': '标题',
                    'resolved_value': '测试商品', 'delegated_to': 'content_finalize.translation'}]}
    payload['payload_hash'] = canonical_sha256(payload)
    defaults = frozen_execution_defaults(payload)
    labels = '标题、自定义属性、自定义名称、PC端描述、无线端描述'
    surface = {'schema': 'dxm.editor_content_surface.v1', 'action': 'translation',
        'surface_match_count': 1, 'write_attempted': False, 'execution_allowed': False,
        'types': {'matches': [{'value': '1', 'text': '普通翻译', 'selected': True, 'checked': True,
            'visible': True, 'disabled': False, 'input_match_count': 1}]},
        'content': {'matches': [{'visible': True, 'text': labels}]},
        'languages': {'matches': [{'titles': ['中文 → 英文'], 'visible': True, 'disabled': False,
                                  'descriptions': ['点击该行即执行；将翻译：' + labels]}]}}
    request = {'module': '速卖通产品', 'textList': ['测试商品'], 'sourceLanguage': 'zh', 'targetLanguage': 'en'}
    response = {'code': 0, 'data': ['Test product']}
    network = {'request_count': 1, 'events': [{'sequence': 1, 'completed': True,
        'url': NativeTranslationNetwork.URL, 'method': 'POST', 'status': 200, 'request': request, 'response': response,
        'request_sha256': canonical_sha256(request), 'response_sha256': canonical_sha256(response),
        'request_body_sha256': HASH_A, 'response_body_sha256': HASH_B}]}
    command = {'command_id': 'translation-command', 'state': 'BATCH_TRANSLATE_EXECUTE',
        'command_action': 'translate_editor_content', 'task_id': 701, 'job_id': 801,
        'runtime_id': 'unit-runtime', 'browser_session_id': 'unit-session'}
    context = {**command, 'mode': 'batch_draft_save'}
    observed = {'schema': 'dxm.editor_translation_observation.v1', 'command': command,
        'execution_payload_hash': payload['payload_hash'], 'target_identity': target,
        'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=81010001', 'shop_id': '901',
        'started_at': NOW, 'completed_at': EXPIRES_AT, 'surface': surface,
        'before': {'title': '测试商品'}, 'after': {'title': 'Test product'}, 'network': network,
        'mutation_authorization': {'ok': True, 'executed': True, 'mutation_action': 'translate_language_click',
            'mutation_status': 'DISPATCHED', 'command_id': 'translation-command', 'mutation_id': 'native-click-grant'},
        'wholesale_command_id': 'wholesale-command',
        'evidence_ref': {'path': 'C:/unit/translation.png', 'sha256': HASH_D, 'size': 100}}
    def validate(value):
        return validate_editor_translation_observation(value, defaults=defaults, target_identity=target,
            command_context=context, expected_payload=payload)
    assert validate(observed) == observed
    receipt = build_editor_translation_receipt(observed, payload)
    assert receipt['canonical_receipt']['action_grant_id'] == 'native-click-grant'
    assert len(receipt['canonical_receipt']['field_readbacks']) == 1
    assert receipt['canonical_receipt']['field_readbacks'][0]['after_value'] == 'Test product'
    for mutate in (
        lambda x: x['command'].update(command_id='other'),
        lambda x: x.update(execution_payload_hash=HASH_C),
        lambda x: x.update(page_url='https://www.dianxiaomi.com/web/smt/edit?id=81010002'),
        lambda x: x.update(wholesale_command_id='translation-command'),
        lambda x: x.update(completed_at=ISSUED_AT),
        lambda x: x['after'].update(title='Unrelated English'),
        lambda x: x['mutation_authorization'].update(executed=False),
        lambda x: x['mutation_authorization'].update(mutation_action='save_click'),
        lambda x: x['mutation_authorization'].update(command_id='other'),
        lambda x: x['evidence_ref'].update(size=0),
    ):
        bad = deepcopy(observed); mutate(bad)
        with pytest.raises(ValueError):
            validate(bad)
    envelope = {'schema_version': 'dxm.action-result.v1', 'ok': True, 'action': command['command_action'],
        'attempted_state': command['state'],
        'before_values': {'defaults': defaults, 'target_identity': target, 'shop_id': '901'},
        'after_values': {'translation_readback': observed['after']},
        'postconditions': {key: True for key in NATIVE_TRANSLATION_POSTCONDITIONS},
        'evidence': {'observations': {'translation_observation': observed,
            'mandatory_capability_receipts': {'translation': receipt}}, 'refs': []},
        'page_identity': {'kind': 'editor', 'url': observed['page_url'], 'runtime_id': 'unit-runtime',
            'browser_session_id': 'unit-session'}, 'failure_code': None,
        'recoverability': {'kind': 'none', 'retryable': False, 'requires_page_reverify': False, 'reason': None}}
    assert validate_action_result_envelope(envelope, execution_mode='batch_draft_save', expected_execution_payload=payload)['ok']
    for mutate in (
        lambda x: x['before_values'].update(shop_id='902'),
        lambda x: x['page_identity'].update(browser_session_id='other'),
        lambda x: x['evidence']['observations']['mandatory_capability_receipts']['translation']['canonical_receipt'].update(action_grant_id='save-lease'),
    ):
        bad = deepcopy(envelope); mutate(bad)
        with pytest.raises(ActionResultContractError):
            validate_action_result_envelope(bad, execution_mode='batch_draft_save', expected_execution_payload=payload)
    # Source wiring only: never instantiate/mock a production Adapter or browser.
    flow = inspect.getsource(DxmLoginFlow.translate_editor_content)
    assert flow.count("_dispatch_authorized_mutation('translate_language_click'") == 1
    assert flow.index('def click_language') < flow.index('window.arm()') < flow.index('language.click(')
    assert 'validate_native_translation_values(payload, before, verified, network)' in flow
    assert 'login_flow.translate_editor_content(' in inspect.getsource(DxmWorkflowAdapter.translate_editor_content)
    dispatch = inspect.getsource(execute_browser_agent_action)
    for action in ('validate_editor_wholesale', 'translate_editor_content'):
        assert f"if action == '{action}':" in dispatch
        assert f"return adapter.{action}(" in dispatch


def test_translation_native_click_returns_worker_dispatch_confirmation_only_after_click():
    import textwrap
    from types import SimpleNamespace
    from src.execution.dxm_login_flow import DxmLoginFlow

    tree = ast.parse(textwrap.dedent(inspect.getsource(DxmLoginFlow.translate_editor_content)))
    callback = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'click_language')
    events = []
    class NativeControl:
        def locator(self, *args): return self
        def filter(self, **kwargs): return self
        def count(self): return 1
        def is_visible(self): return True
        def is_enabled(self): return True
        def click(self, **kwargs):
            events.append('click')
            if fail[0]: raise RuntimeError('native click failed')
            return None  # Actual Playwright click return shape, not a success receipt.
    control, fail = NativeControl(), [False]
    scope = {'page': control, 'EDITOR_TRANSLATION_SURFACE_BINDING': 'observed-surface',
        're': __import__('re'), 'time': SimpleNamespace(monotonic=lambda: 1), 'deadline': 20,
        'window': SimpleNamespace(arm=lambda: events.append('arm'))}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[callback], type_ignores=[])), '<native-click>', 'exec'), scope)
    assert scope['click_language']() == {'dispatched': True}
    assert events == ['arm', 'click']
    fail[0] = True
    with pytest.raises(RuntimeError, match='native click failed'):
        scope['click_language']()
    assert events == ['arm', 'click', 'arm', 'click']


def test_translation_persistence_sources_and_runner_reject_reuse_and_drift():
    from src.batch_edit.full_product_edit_orchestrator import ProductEditContext
    from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
    from src.batch_edit.translator import validate_translation_wholesale_source, build_editor_translation_receipt
    from src.execution.browser_agent_protocol import browser_agent_command_sha256
    from src.execution.mutation_dispatch_ledger import _canonical_json
    from src.execution.v1_runner import V1TaskRunner, V1ExecutionError

    # Synthetic provenance only; no adapter, browser, DB success row or real receipt is created.
    policy = {'schema': 'dxm.content_finalize_policy.v1', 'fields': [
        {'field_key': 'title', 'delegated_to': 'content_finalize.translation',
         'property_schema': {'type': 'string', 'natural_language': True}}]}
    policy['policy_sha256'] = canonical_sha256(policy)
    payload = {'execution_path': 'B', 'content_finalize_policy': policy, 'fields': [
        {'field_key': 'title', 'ui_label_zh': '标题', 'resolved_value': '测试', 'delegated_to': 'content_finalize.translation'}]}
    payload['payload_hash'] = canonical_sha256(payload)
    defaults = frozen_execution_defaults(payload)
    params = {'defaults': defaults, 'shop_id': '91', 'batch_queue_guard': {
        'schema': 'dxm.batch_draft_save.queue_guard.v1', 'queue_epoch': HASH_A, 'queue_version': HASH_B,
        'current_job_id': 22, 'current_ordinal': 1, 'queue_total': 3}}
    values = {**_mutation_command().to_payload(), 'expected_page': 'editor', 'state': 'BATCH_TRANSLATE_EXECUTE',
        'action': 'translate_editor_content', 'execution_mode': 'batch_draft_save', 'params': params,
        'execution_payload_hash': payload['payload_hash'], 'authorization_lease_fingerprint': HASH_D}
    values['mutation_scope_id'] = build_mutation_scope_id(authorization_lease_id=values['authorization_lease_id'],
        task_id=values['task_id'], job_id=values['job_id'], state=values['state'], action=values['action'])
    command = BrowserAgentCommand(**values)
    prior_command = {**command.to_payload(), 'command_id': 'wholesale-predecessor', 'state': 'BATCH_WHOLESALE_FILL',
                     'action': 'validate_editor_wholesale'}
    shared = {'page_url': 'https://www.dianxiaomi.com/web/smt/edit?id=81010001', 'target_identity': {'unit': 'target'},
              'execution_payload_hash': payload['payload_hash']}
    wholesale = {**shared, 'completed_at': NOW, 'command': {key: prior_command[key]
        for key in ('command_id', 'action', 'state', 'task_id', 'job_id', 'runtime_id')}}
    wholesale['command']['browser_session_id'] = 'unit-session'
    predecessor = {'browser_agent_command': prior_command, 'action_result': {'ok': True,
        'action': 'validate_editor_wholesale', 'attempted_state': 'BATCH_WHOLESALE_FILL',
        'page_identity': {'browser_session_id': 'unit-session'},
        'evidence': {'observations': {'wholesale_observation': wholesale}}}}
    observed = {**shared, 'started_at': NOW, 'completed_at': EXPIRES_AT, 'shop_id': '91',
        'wholesale_command_id': prior_command['command_id'], 'before': {'title': '测试'}, 'after': {'title': 'Test'},
        'command': {key: values[key] for key in ('command_id', 'state', 'task_id', 'job_id', 'runtime_id')}}
    observed['command'].update(command_action=command.action, browser_session_id='unit-session')
    binding = MutationDispatchLedger._binding(command, 'translate_language_click', 1)
    observed['mutation_authorization'] = {'mutation_id': binding['mutation_id']}
    authority = {'command': {'payload': command.to_payload()}, 'execution': {'payload': payload}}
    row = {**binding, 'status': 'DISPATCHED', 'command_json': _canonical_json(command.to_payload()),
        'command_sha256': browser_agent_command_sha256(command), 'snapshot_row_authority_sha256': HASH_D,
        'page_kind': 'editor', 'page_url': shared['page_url'], 'browser_session_id': 'unit-session',
        'save_authority_json': _canonical_json(authority), 'save_authority_sha256': canonical_sha256(authority),
        'dispatch_started_at': NOW, 'dispatched_at': NOW}
    def validate_parent(value):
        validate_translation_wholesale_source(observed, value, command=command.to_payload(), browser_session_id='unit-session')
    def validate_row(value):
        return MutationDispatchLedger.validate_translation_source(value, command, observed, snapshot_row_authority_sha256=HASH_D)
    validate_parent(predecessor)
    assert validate_row(row) == authority
    for mutate in (
        lambda x: x['browser_agent_command'].update(command_id=command.command_id),
        lambda x: x['browser_agent_command'].update(job_id=23),
        lambda x: x['action_result'].update(ok=False),
        lambda x: x['action_result']['page_identity'].update(browser_session_id='other'),
        lambda x: x['action_result']['evidence']['observations']['wholesale_observation'].update(execution_payload_hash=HASH_A),
        lambda x: x['action_result']['evidence']['observations']['wholesale_observation'].update(completed_at=EXPIRES_AT),
    ):
        bad = deepcopy(predecessor); mutate(bad)
        with pytest.raises(ValueError, match='TRANSLATION_'): validate_parent(bad)
    for mutate in (
        lambda x: x.update(status='UNKNOWN'), lambda x: x.update(unknown_at=NOW),
        lambda x: x.update(command_id='other'), lambda x: x.update(runtime_id='other'),
        lambda x: x.update(command_sha256=HASH_C), lambda x: x.update(authorization_lease_id='save-lease'),
        lambda x: x.update(browser_session_id='other'), lambda x: x.update(mutation_id='other'),
        lambda x: x.update(snapshot_row_authority_sha256=HASH_A), lambda x: x.update(save_authority_sha256=HASH_A),
        lambda x: x.update(dispatched_at=ISSUED_AT), lambda x: x.update(save_success_recorded_at=NOW),
    ):
        bad = deepcopy(row); mutate(bad)
        with pytest.raises(ValueError, match='TRANSLATION_'): validate_row(bad)
    runner = object.__new__(V1TaskRunner)
    wrapper = build_editor_translation_receipt(observed, payload)
    result = {'browser_agent_command': command.to_payload(), 'workflow_runtime': 'browser_agent',
        'path_b_editor_source_sha256': HASH_D, 'action_result': {'ok': True, 'attempted_state': command.state,
            'action': command.action, 'page_identity': {'browser_session_id': 'unit-session'},
            'evidence': {'observations': {'translation_observation': observed,
                        'mandatory_capability_receipts': {'translation': wrapper}}}}}
    orchestrator = FullProductEditOrchestrator()
    def collect(ctx, value, state=StateName.BATCH_TRANSLATE_EXECUTE):
        runner._record_path_b_phase_result(orchestrator, ctx, state, value, [predecessor])
    ctx = ProductEditContext(product_id='81010001', shop_id='91')
    collect(ctx, result)
    assert runner._path_b_receipt_store(ctx)['capabilities']['translation'] == wrapper
    with pytest.raises(V1ExecutionError, match='TRANSLATION_RECEIPT_REUSED_OR_CHANGED'): collect(ctx, result)
    for mutate in (
        lambda x: x.pop('path_b_editor_source_sha256'),
        lambda x: x.update(workflow_runtime='fake'),
        lambda x: x['action_result']['evidence']['observations']['mandatory_capability_receipts']['translation']['canonical_receipt'].update(action_grant_id='save-lease'),
    ):
        bad = deepcopy(result); mutate(bad)
        with pytest.raises(V1ExecutionError): collect(ProductEditContext(product_id='81010001', shop_id='91'), bad)
    with pytest.raises(V1ExecutionError):
        collect(ProductEditContext(product_id='81010001', shop_id='91'), result, StateName.FILL_BASE_INFO)
    persist = inspect.getsource(Repository.persist_path_b_editor_source)
    assert "'BATCH_TRANSLATE_EXECUTE': 'translate_editor_content'" in persist
    assert 'validate_translation_wholesale_source(' in persist and 'validate_translation_source(' in persist
    assert 'validate_current_translation_authority(conn, authority, command=parsed, observation=observed)' in persist
    assert "parent.get('artifacts') != load_browser_agent_action_source(" in persist
    assert persist.index('validate_translation_source(') < persist.index('INSERT INTO job_evidences')
    run = inspect.getsource(V1TaskRunner._run_workflow_action_browser_agent)
    assert 'StateName.BATCH_TRANSLATE_EXECUTE}' in run and "'phase': 'translation_source_persistence'" in run


def test_shared_video_rule_is_explicit_and_resolves_current_native_inputs_without_defaults():
    from src.batch_edit.plan_template_contract import validate_editor_actions, PlanTemplateContractError
    from src.batch_edit.video_generator import resolve_native_video_inputs

    legacy = {'enabled': True, 'failure_strategy': 'pause', 'max_wait_seconds': 300, 'poll_interval_seconds': 5}
    validate_editor_actions({'video': legacy})  # Stored old drafts remain readable, but cannot execute.
    with pytest.raises(ValueError, match='VIDEO_SHARED_GENERATION_RULE_INVALID'):
        resolve_native_video_inputs(legacy, [], [])
    rule = {'image_selection': 'first_product_images', 'image_count': 5, 'transition': 1, 'music': {'mode': 'none'}}
    config = {**legacy, 'generation_rule': rule}
    images = [f'https://example.invalid/product-{i}.jpg' for i in range(1, 8)]
    before = deepcopy(config)
    result = resolve_native_video_inputs(config, images, [])
    assert result == {'images': images[:5], 'transition': 1, 'transition_label': '自然', 'music': {'mode': 'none'}}
    assert config == before
    assert resolve_native_video_inputs(config, images[:3], [])['images'] == images[:3]
    for bad_images in ([], images[:1], [images[0], images[0]], ['file:///private.jpg', images[0]],
                       ['https://user:secret@example.invalid/a.jpg', images[0]], ['https://example.invalid/a,b.jpg', images[0]]):
        with pytest.raises(ValueError, match='VIDEO_'):
            resolve_native_video_inputs(config, bad_images, [])
    library = {**config, 'generation_rule': {**rule, 'music': {'mode': 'library', 'id': '31'}}}
    catalog = [{'id': 31, 'fileId': 'source-31', 'fileUrl': 'https://example.invalid/music.mp3'}]
    selected = resolve_native_video_inputs(library, images, catalog)
    assert selected['music'] == {'mode': 'library', 'record': catalog[0]}
    selected['music']['record']['id'] = 'changed'
    assert catalog[0]['id'] == 31
    for bad_catalog in ([], catalog * 2, [{'id': 31}], None):
        with pytest.raises(ValueError, match='VIDEO_MUSIC_'):
            resolve_native_video_inputs(library, images, bad_catalog)
    for mutate in (
        lambda x: x.pop('image_selection'), lambda x: x.update(image_selection='native_default'),
        lambda x: x.update(image_count=True), lambda x: x.update(image_count=1), lambda x: x.update(image_count=9),
        lambda x: x.update(transition=True), lambda x: x.update(transition=7),
        lambda x: x.update(music={}), lambda x: x.update(music={'mode': 'library', 'id': ''}),
        lambda x: x.update(product_id='unapproved-per-product'),
    ):
        bad = deepcopy(config); mutate(bad['generation_rule'])
        with pytest.raises(PlanTemplateContractError): validate_editor_actions({'video': bad})
    assert canonical_sha256({'video': config}) != canonical_sha256({'video': legacy})
    for key, value in (('image_count', 6), ('transition', 2), ('music', {'mode': 'library', 'id': '31'})):
        changed = deepcopy(config); changed['generation_rule'][key] = value
        validate_editor_actions({'video': changed})
        assert canonical_sha256(changed) != canonical_sha256(config)
