"""E3 gates: batch_draft_save Path A mode, Path B reject, start/approve wiring."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from src import db, repository as repository_module
from src.batch_edit.plan_snapshot_store import PlanSnapshotStore
from src.batch_edit.scope_contract import canonical_sha256
from src.batch_edit.frozen_execution_contract import frozen_execution_defaults
from src.execution import v1_runner as v1_runner_module
from src.execution.action_result_contract import (
    ActionResultContractError,
    validate_action_result_envelope,
    validate_independent_save_verification_pair,
)
from src.execution.browser_agent_protocol import (
    build_mutation_scope_id,
    canonical_mutation_target_payload,
    mutation_target_hash,
    validate_browser_agent_command,
)
from src.execution.batch_command_contract import validate_frozen_execution_readback
from src.execution.batch_dispatch_authority import LiveDispatchFacts
import src.execution.browser_agent_worker as browser_agent_worker
from src.execution.browser_agent_worker import (
    BrowserAgentExecutionContext,
    BrowserAgentRuntime,
)
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from src.execution.v1_runner import V1ExecutionError, V1TaskRunner
from src.main import app
from src.repository import Repository
from src.state_machine.contracts import ExecutionMode, StateName, normalize_execution_mode
from src.state_machine.two_stage import (
    TwoStageContractError,
    build_authorization_context,
    build_batch_draft_save_task_facts,
    verify_exact_stage_task_facts,
)
from tests.test_action_result_contract import _valid_save_result, _valid_unpublished_result
from tests.test_v1_runner import DummyManager, FakeWorkflowAdapter, _create_task, _evidence_ref


class E3WorkflowAdapter(FakeWorkflowAdapter):
    """Fake only the external DXM boundary while exercising the real V1 runner."""

    def __init__(self, *, fail_action: str | None = None, failure_code: str | None = None):
        super().__init__(fail_action=fail_action)
        self.failure_code = failure_code
        self.target_ids: list[int] = []

    def open_editor(self, **kwargs):
        return self._record_e3("open_editor", **kwargs)

    def verify_edit_ownership(self, **kwargs):
        return self._record_e3("verify_edit_ownership", **kwargs)

    def fill_editor_required_defaults(self, **kwargs):
        return self._record_e3("fill_editor_required_defaults", **kwargs)

    def fill_editor_variants(self, **kwargs):
        return self._record_e3("fill_editor_variants", **kwargs)

    def fill_media_assets(self, **kwargs):
        return self._record_e3("fill_media_assets", **kwargs)

    def fill_compliance_defaults(self, **kwargs):
        return self._record_e3("fill_compliance_defaults", **kwargs)

    def enable_semi_managed(self, **kwargs):
        return self._record_e3("enable_semi_managed", **kwargs)

    def open_semi_managed_page(self, **kwargs):
        return self._record_e3("open_semi_managed_page", **kwargs)

    def fill_semi_managed_defaults(self, **kwargs):
        return self._record_e3("fill_semi_managed_defaults", **kwargs)

    def save_only(self, **kwargs):
        return self._record_e3("save_only", **kwargs)

    def verify_not_published(self, **kwargs):
        return self._record_e3("verify_not_published", **kwargs)

    def _record_e3(self, action: str, **kwargs):
        target = deepcopy(kwargs.get("target_identity") or {})
        stable = target.get("stable_identity")
        if (
            isinstance(stable, dict)
            and stable.get("kind") == "product_id"
            and str(stable.get("value") or "").isdecimal()
        ):
            self.target_ids.append(int(stable["value"]))
        recorded_by_base = False
        if action == "save_only":
            result = _valid_save_result()
            self._bind_path_a_result(
                result,
                target,
                kwargs.get("store_name"),
                "save_screenshot",
                execution_defaults=kwargs.get("defaults"),
            )
        elif action == "verify_not_published":
            result = _valid_unpublished_result()
            self._bind_path_a_result(result, target, kwargs.get("store_name"), "unpublished_screenshot")
        else:
            positional = []
            if action in {"fill_editor_required_defaults", "fill_editor_variants", "fill_media_assets", "fill_compliance_defaults"}:
                positional.append(kwargs.get("defaults"))
            positional.extend((kwargs.get("product_query"), kwargs.get("store_name")))
            result = super()._record(action, *positional)
            recorded_by_base = True
        if action == self.fail_action:
            result["ok"] = False
            result["failure_code"] = self.failure_code or "TEST_ACTION_FAILED"
            result["recoverability"] = {
                "kind": "manual_takeover",
                "retryable": False,
                "requires_page_reverify": True,
                "reason": "E3 injected external failure",
            }
            result["postconditions"] = {
                key: False for key in result.get("postconditions", {})
            }
        if not recorded_by_base:
            self.calls.append((action, kwargs))
        return result

    @staticmethod
    def _bind_path_a_result(
        result: dict,
        target: dict,
        store_name: str | None,
        evidence_kind: str,
        *,
        execution_defaults: dict | None = None,
    ) -> None:
        digest = hashlib.sha256(
            json.dumps(target, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        result["page_identity"] = {
            "kind": "editor",
            "url": "https://www.dianxiaomi.com/web/smt/edit",
            "runtime_id": "e3-test-runtime",
            "browser_session_id": "e3-test-session",
        }
        stable = target.get("stable_identity") if isinstance(target, dict) else {}
        stable_value = stable.get("value") if isinstance(stable, dict) else "unknown"
        result["evidence"]["refs"] = [{
            **_evidence_ref(f"e3-{evidence_kind}-{stable_value}.png"),
            "kind": evidence_kind,
            "captured_at": (
                "2026-08-10T00:00:02+00:00"
                if evidence_kind == "unpublished_screenshot"
                else "2026-08-10T00:00:01+00:00"
            ),
        }]
        result["before_values"]["target_identity"] = deepcopy(target)
        if result["action"] == "save_only":
            result["before_values"]["store_name"] = str(store_name or "")
            frozen_readback = None
            category_schema_readback = None
            if isinstance(execution_defaults, dict):
                payload = execution_defaults.get("_frozen_execution_payload")
                if isinstance(payload, dict) and isinstance(payload.get("fields"), list):
                    category_schema_readback = {
                        "schema": "dxm.editor.category_schema_readback.v1",
                        "ok": True,
                        "phase": "before_ledger_begin_dispatch",
                        "expected_category_id": payload["category_id"],
                        "observed_category_id": payload["category_id"],
                        "expected_category_schema_hash": payload[
                            "category_schema_hash"
                        ],
                        "observed_category_schema_hash": payload[
                            "category_schema_hash"
                        ],
                        "category_source": "test:live_schema_readback",
                        "reason": None,
                    }
                    readback_fields = []
                    for field in payload["fields"]:
                        value_hash = hashlib.sha256(
                            json.dumps(
                                field["resolved_value"],
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                                allow_nan=False,
                            ).encode("utf-8")
                        ).hexdigest().upper()
                        readback_fields.append({
                            "field_key": field["field_key"],
                            "ui_binding": field["ui_binding"],
                            "expected_value_hash": value_hash,
                            "observed_value_hash": value_hash,
                            "match_count": (
                                len(field["resolved_value"])
                                if isinstance(field["resolved_value"], list)
                                else 1
                            ),
                            "aggregate_kind": (
                                "sku_rows"
                                if field["field_key"] == "aeopAeProductSKUs"
                                else (
                                    "choice_group"
                                    if isinstance(field["resolved_value"], list)
                                    else "single"
                                )
                            ),
                            "exact": True,
                        })
                    frozen_readback = {
                        "schema": "dxm.frozen_execution.readback.v1",
                        "ok": True,
                        "phase": "before_ledger_begin_dispatch",
                        "execution_payload_hash": payload["payload_hash"],
                        "field_count": len(readback_fields),
                        "fields": readback_fields,
                        "reason": None,
                    }
            for container in (
                result["after_values"],
                result["evidence"]["observations"],
                result["evidence"]["observations"]["save_result"],
            ):
                identity = container["pre_dispatch_readback"]["identity"]
                identity["target_identity"] = deepcopy(target)
                identity["expected_store_name"] = str(store_name or "")
                identity["target_identity_sha256"] = digest
                if frozen_readback is not None:
                    container["pre_dispatch_readback"][
                        "category_schema_readback"
                    ] = deepcopy(category_schema_readback)
                    container["pre_dispatch_readback"][
                        "frozen_execution_readback"
                    ] = deepcopy(frozen_readback)
            if category_schema_readback is not None:
                result["evidence"]["observations"]["save_result"][
                    "network_audit"
                ]["read_only_schema_request_count"] = 1
        else:
            for container in (result["after_values"], result["evidence"]["observations"]):
                container["fresh_probe"]["target_identity_sha256"] = digest
                container["fresh_probe"]["page_url"] = "https://www.dianxiaomi.com/web/smt/edit"
                container["target_identity"]["target_identity_sha256"] = digest


class _StrictFakeMutationLedger:
    """Test ledger that admits only protocol-valid commands at the reserve boundary."""

    def __init__(self) -> None:
        self.reserved_command_ids: set[str] = set()

    def reserve_command(self, command):
        validate_browser_agent_command(command)
        self.reserved_command_ids.add(command.command_id)
        return {"ok": True, "reasonCode": "OK"}


class _StrictFakeBrowserAgentRuntime:
    """Exercise V1 command/reserve/run without opening a browser or writing DXM."""

    def __init__(self, adapter: E3WorkflowAdapter) -> None:
        self.adapter = adapter
        self.runtime_id = f"e3-fake-runtime-{id(self):x}"
        self.ledger = _StrictFakeMutationLedger()

    def status(self):
        return {
            "runtimeId": self.runtime_id,
            "status": "idle",
            "healthy": True,
            "active": False,
            "mutationLedgerEnabled": True,
        }

    def reserve_command(self, command):
        return self.ledger.reserve_command(command)

    def run(self, command, *, timeout_seconds=None):
        del timeout_seconds
        if command.command_id not in self.ledger.reserved_command_ids:
            raise RuntimeError("BROWSER_AGENT_RESERVATION_REQUIRED")
        self.ledger.reserved_command_ids.remove(command.command_id)
        result = browser_agent_worker.execute_browser_agent_action(
            self.adapter,
            command.action,
            command.params,
        )
        if (
            command.execution_mode == "batch_draft_save"
            and command.action == "verify_not_published"
            and isinstance(result, dict)
        ):
            verification_context = deepcopy(
                command.params.get("save_verification_context")
            )
            result["before_values"]["save_verification_context"] = deepcopy(
                verification_context
            )
            result["after_values"]["save_verification_context"] = deepcopy(
                verification_context
            )
            result["evidence"]["observations"][
                "save_verification_context"
            ] = deepcopy(verification_context)
            result["evidence"]["observations"]["fresh_probe"][
                "save_verification_context"
            ] = deepcopy(verification_context)
        return result

    def cancel_command(self, command_id, runtime_id):
        if runtime_id != self.runtime_id:
            return {"ok": False, "reasonCode": "BROWSER_AGENT_RUNTIME_BINDING_MISMATCH"}
        self.ledger.reserved_command_ids.discard(command_id)
        return {"ok": True, "reasonCode": "CANCELLED_BEFORE_DISPATCH"}


def _runner_context(
    tmp_path,
    monkeypatch,
    *,
    adapter: E3WorkflowAdapter | None = None,
    product_count: int = 3,
    approve: bool = True,
):
    db_path = tmp_path / "e3-real-runner.db"
    screenshot_dir = tmp_path / "e3-screenshots"
    screenshot_dir.mkdir()
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(repository_module, "SCREENSHOT_DIR", screenshot_dir)
    monkeypatch.setattr(v1_runner_module, "SCREENSHOT_DIR", screenshot_dir)
    db.init_db()
    repo = Repository()
    task, _store, ids, _digest = _create_batch_draft_task(
        repo,
        product_ids=[70001 + index for index in range(product_count)],
    )
    workflow = adapter or E3WorkflowAdapter()
    browser_runtime = _StrictFakeBrowserAgentRuntime(workflow)
    if approve:
        issued = datetime.now(timezone.utc)
        git_head = "6" * 40
        facts = build_batch_draft_save_task_facts(
            task_id=task["id"],
            store_id=task["store_id"],
            product_ids=ids,
            plan_snapshot_id=task["payload"]["plan_snapshot_id"],
            plan_snapshot_hash=task["payload"]["plan_snapshot_hash"],
            path="A",
        )
        authorization_context = build_authorization_context(
            stage_task_facts=facts,
            runtime_instance_id="e3-test-backend-runtime",
            browser_session_id="e3-test-browser-session",
            git_head=git_head,
            worktree_identity=_worktree_identity(git_head, "runner-context"),
            l2_evidence_fingerprint="9" * 64,
            approved_by="ops-owner",
        )
        approved = repo.set_task_manual_approval(
            task["id"],
            approved=True,
            token="e3-runner-approval",
            approved_by="ops-owner",
            confirmation="CONFIRM_DXM_SAVE_ONLY",
            authorization_context=authorization_context,
            lease_id="e3-runner-lease",
            issued_at=issued.isoformat(),
            expires_at=(issued + timedelta(minutes=5)).isoformat(),
        )
        assert approved.ok is True
        started = repo.try_start_task_with_authorization(
            task["id"],
            token="e3-runner-approval",
            confirmation="CONFIRM_DXM_SAVE_ONLY",
            approved_by="ops-owner",
            authorization_context=authorization_context,
            consumed_at=(issued + timedelta(seconds=1)).isoformat(),
        )
        assert started.ok is True
    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=workflow,
        browser_agent_runtime=browser_runtime,
        authorization_verifier=lambda *_args: {"ok": True, "reason_code": "OK"},
    )
    return repo, task, ids, runner, workflow


def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "e3-batch-draft-save.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    repo = Repository()
    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=E3WorkflowAdapter(),
        authorization_verifier=lambda *_args: {"ok": True, "reason_code": "OK"},
    )
    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "runner", runner)
    monkeypatch.setattr(main, "_current_browser_session_id", lambda: "e3-browser-session")
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    return TestClient(app), repo, runner, main


def _snapshot_hash(seed: str = "e3-plan") -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest().upper()


def _worktree_identity(git_head: str, seed: str = "e3-worktree") -> dict:
    return {
        "schema": "dxm.git-worktree.identity.v1",
        "git_head": git_head,
        "git_dirty": True,
        "status_count": 737,
        "status_sha256": _snapshot_hash(f"{seed}-status"),
        "execution_file_count": 123,
        "execution_tree_sha256": _snapshot_hash(f"{seed}-tree"),
    }


def _frozen_target(product_id: int, store_name: str) -> dict:
    store_fingerprint = hashlib.sha256(
        json.dumps(
            {"source": "structured_store_cell", "store_name": store_name},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest().upper()
    stable_value = str(product_id)
    return {
        "schema_version": "dxm_draft_box_target.v1",
        "store_fingerprint": store_fingerprint,
        "stable_identity": {
            "kind": "product_id",
            "value": stable_value,
            "fingerprint": hashlib.sha256(
                f"product_id:{stable_value}".encode("utf-8")
            ).hexdigest().upper(),
        },
        "source_urls": [f"https://detail.1688.com/offer/{product_id}.html"],
    }


def _create_batch_draft_task(
    repo: Repository,
    *,
    path: str = "A",
    product_ids: list[int] | None = None,
    publish_allowed: bool = False,
):
    store = repo.create_store("E3 Draft Shop", "AliExpress")
    ids = product_ids or [70001, 70002, 70003]
    plan_body = {
        "schema": "dxm_batch_draft_save_plan.v1",
        "mode": "batch_draft_save",
        "path": path,
        "shop_scope": str(store["id"]),
        "session_context": {
            "session_ref": "e3-session-proof",
            "account_ref_hash": "A" * 64,
            "shop_id": str(store["id"]),
            "shop_name": store["name"],
        },
        "local_plan_template": {"id": 1, "version": "1.0.0"},
        "product_ids": [str(value) for value in ids],
        "item_snapshots": [],
        "publish_allowed": publish_allowed,
    }
    for value in ids:
        normalized_schema = {
            "type": "object",
            "properties": {
                "weight": {
                    "type": "string",
                    "ui_binding": "dxm_editor:weight",
                }
            },
        }
        mapping_body = {
            "mapping_version": "1.0.0",
            "entries": [
                {
                    "ui_label_zh": "包装重量",
                    "field_key": "weight",
                    "category_schema_path": "$.properties.weight",
                    "ui_binding": "dxm_editor:weight",
                }
            ],
        }
        resolution_body = {
            "resolved_fields": [
                {
                    "field_key": "weight",
                    "source": "local_plan_template",
                    "source_ref": "1@1.0.0",
                    "resolved_value": "10",
                    "natural_language": False,
                    "expected_language": None,
                    "detected_language": None,
                }
            ],
            "unresolved_fields": [],
            "price_validation": {
                "current_values": {},
                "resolved_values": {},
            },
        }
        plan_body["item_snapshots"].append(
            {
                "product_id": str(value),
                "categoryId": "100",
                "target_identity": _frozen_target(value, store["name"]),
                "category_schema": {
                    "normalized_schema": normalized_schema,
                    "schema_hash": canonical_sha256(normalized_schema),
                },
                "field_mapping": {
                    **mapping_body,
                    "mapping_hash": canonical_sha256(mapping_body),
                },
                "resolution_result": {
                    **resolution_body,
                    "resolution_hash": canonical_sha256(resolution_body),
                },
            }
        )
    digest = canonical_sha256(plan_body)
    row = PlanSnapshotStore().freeze_with_task(
        {**plan_body, "snapshot_hash": digest},
        idempotency_key=f"e3-{path.casefold()}-{digest[:20]}",
    )
    task = repo.get_task_private(int(row["task_id"]))
    assert task is not None
    return task, store, ids, digest


def test_real_runner_uses_frozen_resolution_after_runtime_template_drift(
    tmp_path,
    monkeypatch,
):
    adapter = E3WorkflowAdapter(fail_action="save_only")
    repo, task, _ids, runner, workflow = _runner_context(
        tmp_path,
        monkeypatch,
        adapter=adapter,
        product_count=1,
    )
    repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "drifted after snapshot",
            "binding_scope": "E3 Draft Shop",
            "payload": {"weight": "99", "logistics": {"weight": "99"}},
            "is_enabled": True,
        }
    )

    asyncio.run(runner.run_task(task["id"]))

    fill_call = next(
        call for call in workflow.calls if call[0] == "fill_editor_required_defaults"
    )
    assert fill_call[1]["weight"] == "10"
    assert [
        field["resolved_value"]
        for field in fill_call[1]["_frozen_execution_payload"]["fields"]
    ] == ["10"]


def test_batch_save_action_result_requires_frozen_execution_readback():
    result = _valid_save_result()
    E3WorkflowAdapter._bind_path_a_result(
        result,
        _frozen_target(70001, "E3 Draft Shop"),
        "E3 Draft Shop",
        "save_screenshot",
    )

    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            result,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
        )


def test_runner_rejects_frozen_readback_hash_not_bound_to_command(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    monkeypatch.setattr(
        browser_agent_worker,
        "SCREENSHOT_DIR",
        repository_module.SCREENSHOT_DIR,
    )
    private = repo.get_task_private(task["id"])
    defaults = runner._execution_defaults(
        private,
        None,
        job=private["jobs"][0],
    )
    result = _valid_save_result()
    E3WorkflowAdapter._bind_path_a_result(
        result,
        _frozen_target(70001, "E3 Draft Shop"),
        "E3 Draft Shop",
        "save_screenshot",
        execution_defaults=defaults,
    )
    result["evidence"]["observations"]["save_result"][
        "pre_dispatch_readback"
    ]["frozen_execution_readback"]["execution_payload_hash"] = "B" * 64

    with pytest.raises(V1ExecutionError) as exc_info:
        runner._validate_workflow_action_result(
            state_name=StateName.SAVE_ONLY,
            action_name="save_only",
            error_code="E207",
            error_title="保存失败",
            result=result,
            mode="batch_draft_save",
            expected_execution_payload=defaults["_frozen_execution_payload"],
            expected_execution_payload_hash=defaults[
                "_frozen_execution_payload_hash"
            ],
        )

    assert exc_info.value.error_code == "UNKNOWN"
    assert "FROZEN_EXECUTION_READBACK_HASH_MISMATCH" in exc_info.value.detail


def test_action_result_and_runner_reject_readback_field_outside_frozen_payload(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    private = repo.get_task_private(task["id"])
    defaults = runner._execution_defaults(
        private,
        None,
        job=private["jobs"][0],
    )
    execution_payload = defaults["_frozen_execution_payload"]
    result = _valid_save_result()
    E3WorkflowAdapter._bind_path_a_result(
        result,
        _frozen_target(70001, "E3 Draft Shop"),
        "E3 Draft Shop",
        "save_screenshot",
        execution_defaults=defaults,
    )
    readback = result["evidence"]["observations"]["save_result"][
        "pre_dispatch_readback"
    ]["frozen_execution_readback"]
    forged_value_hash = DxmLoginFlow._canonical_frozen_value_hash("forged")
    readback["fields"] = [
        {
            "field_key": "not_in_payload",
            "ui_binding": "reviewed:not_in_payload",
            "expected_value_hash": forged_value_hash,
            "observed_value_hash": forged_value_hash,
            "match_count": 1,
            "aggregate_kind": "single",
            "exact": True,
        }
    ]
    readback["field_count"] = 1

    with pytest.raises(ActionResultContractError):
        validate_action_result_envelope(
            result,
            expected_state="SAVE_ONLY",
            expected_action="save_only",
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=execution_payload,
        )

    with pytest.raises(V1ExecutionError) as exc_info:
        runner._validate_workflow_action_result(
            state_name=StateName.SAVE_ONLY,
            action_name="save_only",
            error_code="E207",
            error_title="保存失败",
            result=result,
            mode="batch_draft_save",
            expected_execution_payload=execution_payload,
            expected_execution_payload_hash=execution_payload["payload_hash"],
        )
    assert exc_info.value.error_code == "UNKNOWN"
    assert "FROZEN_EXECUTION_READBACK" in exc_info.value.detail


def test_browser_agent_rejects_frozen_readback_hash_not_bound_to_command(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    monkeypatch.setattr(
        browser_agent_worker,
        "SCREENSHOT_DIR",
        repository_module.SCREENSHOT_DIR,
    )
    private = repo.get_task_private(task["id"])
    job = private["jobs"][0]
    defaults = runner._execution_defaults(private, None, job=job)
    spec = runner._workflow_action_worker_request(
        private,
        job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        defaults,
    )
    assert spec is not None
    action, _error_code, _error_title, params = spec
    command = runner._build_browser_agent_command(
        private,
        job,
        StateName.SAVE_ONLY,
        action,
        params,
    )
    canonical = _valid_save_result()
    E3WorkflowAdapter._bind_path_a_result(
        canonical,
        command.params["target_identity"],
        command.params["store_name"],
        "save_screenshot",
        execution_defaults=defaults,
    )
    canonical["evidence"]["observations"]["save_result"][
        "pre_dispatch_readback"
    ]["frozen_execution_readback"]["execution_payload_hash"] = "B" * 64
    evidence_ref = canonical["evidence"]["refs"][0]
    raw_ref = {key: evidence_ref[key] for key in ("path", "sha256", "size")}
    raw = {
        "ok": True,
        "action": "save_only",
        "page_url": "https://www.dianxiaomi.com/web/smt/edit",
        "store_name": command.params["store_name"],
        "target_identity": deepcopy(command.params["target_identity"]),
        "save_evidence_ref": raw_ref,
        "evidence_ref": raw_ref,
        "contract_facts": {
            "before_values": canonical["before_values"],
            "after_values": canonical["after_values"],
            "postconditions": canonical["postconditions"],
            "evidence_observations": canonical["evidence"]["observations"],
            "failure_code": None,
            "recoverability": canonical["recoverability"],
        },
    }
    browser_session_id = "e3-readback-binding-session"

    class Adapter:
        def browser_session_id(self):
            return browser_session_id

    context = BrowserAgentExecutionContext(
        command_id=command.command_id,
        idempotency_key=command.idempotency_key,
        runtime_id=command.runtime_id,
        browser_session_id=browser_session_id,
        expected_page=command.expected_page,
        generation=1,
        deadline_monotonic=None,
        cancel_epoch=0,
        task_id=command.task_id,
        job_id=command.job_id,
        state=command.state,
        mode=command.execution_mode,
    )

    with pytest.raises(RuntimeError, match="FROZEN_EXECUTION_READBACK_HASH_MISMATCH"):
        BrowserAgentRuntime(Adapter())._build_action_result_envelope(
            Adapter(),
            command,
            context,
            raw,
        )


def test_frozen_execution_readback_hashes_each_field_and_rejects_drift(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    execution_payload = runner._execution_defaults(
        private,
        None,
        job=first_job,
    )["_frozen_execution_payload"]

    class ReadbackPage:
        def evaluate(self, _script, _fields):
            return [{"field_key": "weight", "found": True, "value": "99"}]

    flow = object.__new__(DxmLoginFlow)
    readback = flow._capture_frozen_execution_readback(
        ReadbackPage(),
        execution_payload,
        phase="before_ledger_begin_dispatch",
    )

    assert readback["ok"] is False
    assert readback["fields"][0]["exact"] is False
    assert readback["fields"][0]["expected_value_hash"] != readback["fields"][0][
        "observed_value_hash"
    ]


def test_frozen_execution_readback_rejects_ambiguous_exact_value_match(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    private = repo.get_task_private(task["id"])
    execution_payload = runner._execution_defaults(
        private,
        None,
        job=private["jobs"][0],
    )["_frozen_execution_payload"]

    class AmbiguousReadbackPage:
        def evaluate(self, _script, runtime_input):
            assert runtime_input["operation"] == "readback"
            return {
                "ok": True,
                "field_count": 1,
                "observations": [{
                    "field_key": "weight",
                    "found": True,
                    "value": "10",
                    "match_count": 2,
                    "aggregate_kind": "single",
                }],
                "fields": [],
                "write_attempted": False,
            }

    readback = DxmLoginFlow._capture_frozen_execution_readback(
        AmbiguousReadbackPage(),
        execution_payload,
        phase="before_ledger_begin_dispatch",
    )

    assert readback["ok"] is False
    assert readback["fields"][0]["exact"] is False
    assert readback["fields"][0]["match_count"] == 2
    assert readback["reason"] == "frozen_execution_binding_ambiguous"


def test_prepare_editor_uses_only_formal_frozen_ui_binding_writer(monkeypatch):
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "title",
                "ui_label_zh": "英文标题",
                "ui_binding": "dxm_editor:title",
                "category_schema_path": "$.properties.title",
                "resolved_value": "Wireless Bluetooth Earbuds",
            },
            {
                "field_key": "material",
                "ui_label_zh": "材质",
                "ui_binding": "dxm_attribute:1001",
                "category_schema_path": "$.properties.material",
                "resolved_value": "ABS",
            },
            {
                "field_key": "aeopAeProductSKUs",
                "ui_label_zh": "SKU 行",
                "ui_binding": "dxm_editor:aeopAeProductSKUs",
                "category_schema_path": "$.properties.aeopAeProductSKUs",
                "resolved_value": [{
                    "skuCode": "SKU-70001",
                    "skuPrice": "9.99",
                    "cargoPrice": "8.00",
                    "ipmSkuStock": 12,
                }],
            },
        ],
        "unresolved_fields": [],
        "price_validation": {"current_values": {}, "resolved_values": {}},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    defaults = frozen_execution_defaults(payload)
    flow = object.__new__(DxmLoginFlow)
    calls: list[tuple[str, list[str] | None]] = []
    ok_result = {
        "ok": True,
        "stage": "fill_frozen_execution_payload_ready",
        "field_count": 3,
        "fields": [field["field_key"] for field in payload["fields"]],
    }
    monkeypatch.setattr(
        flow,
        "_capture_current_editor_category_schema",
        lambda _page, _payload, **kwargs: {
            "schema": "dxm.editor.category_schema_readback.v1",
            "ok": True,
            "phase": kwargs["phase"],
            "expected_category_id": payload["category_id"],
            "observed_category_id": payload["category_id"],
            "expected_category_schema_hash": payload["category_schema_hash"],
            "observed_category_schema_hash": payload["category_schema_hash"],
            "category_source": "test",
            "reason": None,
        },
    )
    monkeypatch.setattr(
        flow,
        "_fill_frozen_execution_payload_on_page",
        lambda _page, actual: calls.append((
            "frozen",
            [field["field_key"] for field in actual["fields"]],
        )) or deepcopy(ok_result),
        raising=False,
    )
    for legacy_name in (
        "_fill_editor_required_defaults_on_page",
        "_fill_editor_variants_on_page",
        "_fill_media_assets_on_page",
        "_fill_compliance_defaults_on_page",
        "_repair_product_main_images_on_page",
    ):
        monkeypatch.setattr(
            flow,
            legacy_name,
            lambda *_args, _name=legacy_name, **_kwargs: calls.append((_name, None))
            or {"ok": False, "stage": f"{_name}_failed"},
        )
    monkeypatch.setattr(
        flow,
        "_capture_save_field_integrity_snapshot",
        lambda _page: {
            "ok": True,
            "kind": "structured_nonempty_form_state",
            "field_count": 3,
            "nonempty_field_count": 3,
            "sha256": "D" * 64,
        },
    )
    monkeypatch.setattr(
        flow,
        "_capture_frozen_execution_readback",
        lambda _page, _payload, **kwargs: {
            "schema": "dxm.frozen_execution.readback.v1",
            "ok": True,
            "phase": kwargs["phase"],
            "execution_payload_hash": payload["payload_hash"],
            "field_count": 3,
            "fields": [],
            "reason": None,
        },
    )
    monkeypatch.setattr(flow, "_is_visible_dxm_editor_page", lambda _page: True)

    class Page:
        url = "https://www.dianxiaomi.com/web/smt/edit"

        def title(self):
            return "店小秘编辑页"

    result = flow._prepare_editor_page_for_save(
        Page(),
        defaults,
        require_explicit_defaults=True,
    )

    assert result["ok"] is True
    assert result["preflight_results"] == {"frozen_execution": ok_result}
    assert calls == [("frozen", ["title", "material", "aeopAeProductSKUs"])]


def test_formal_dxm_login_flow_writes_frozen_title_attribute_and_sku_controls():
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "title",
                "ui_label_zh": "英文标题",
                "ui_binding": "dxm_editor:title",
                "category_schema_path": "$.properties.title",
                "resolved_value": "Wireless Bluetooth Earbuds",
            },
            {
                "field_key": "material",
                "ui_label_zh": "材质",
                "ui_binding": "dxm_attribute:1001",
                "category_schema_path": "$.properties.material",
                "resolved_value": "ABS",
            },
            {
                "field_key": "aeopAeProductSKUs",
                "ui_label_zh": "SKU 行",
                "ui_binding": "dxm_editor:aeopAeProductSKUs",
                "category_schema_path": "$.properties.aeopAeProductSKUs",
                "resolved_value": [{
                    "skuCode": "SKU-70001",
                    "skuPrice": "9.99",
                    "cargoPrice": "8.00",
                    "ipmSkuStock": 12,
                }],
            },
        ],
        "unresolved_fields": [],
        "price_validation": {"current_values": {}, "resolved_values": {}},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    html = """
      <style>input, select, table { display: block; width: 240px; height: 32px; }</style>
      <section data-ui-binding="dxm_editor:title">
        <input name="title" value="Old title" />
      </section>
      <section data-ui-binding="dxm_attribute:1001" data-attribute-id="1001">
        <select name="material">
          <option value="Metal">Metal</option>
          <option value="ABS">ABS</option>
        </select>
      </section>
      <table data-ui-binding="dxm_editor:aeopAeProductSKUs">
        <thead><tr><th>SKU 编码</th><th>零售价</th><th>货值</th><th>库存</th></tr></thead>
        <tbody><tr>
          <td><input data-sku-field="skuCode" value="OLD" /></td>
          <td><input data-sku-field="skuPrice" value="1.00" /></td>
          <td><input data-sku-field="cargoPrice" value="1.00" /></td>
          <td><input data-sku-field="ipmSkuStock" value="1" /></td>
        </tr></tbody>
      </table>
    """
    flow = object.__new__(DxmLoginFlow)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content(html)
        filled = flow._fill_frozen_execution_payload_on_page(page, payload)
        readback = flow._capture_frozen_execution_readback(
            page,
            payload,
            phase="after_prefill",
        )
        values = page.evaluate("""() => ({
          title: document.querySelector('[name="title"]').value,
          material: document.querySelector('[name="material"]').value,
          sku: Array.from(document.querySelectorAll('[data-sku-field]')).map(el => el.value),
        })""")
        page.set_content("""
          <style>input, select { display: block; width: 240px; height: 32px; }</style>
          <section data-ui-binding="dxm_editor:title"><input name="title" value="Old title" /></section>
          <section data-ui-binding="dxm_attribute:1001"><select><option>ABS</option></select></section>
          <section data-ui-binding="dxm_attribute:1001"><select><option>ABS</option></select></section>
          <table data-ui-binding="dxm_editor:aeopAeProductSKUs"><tbody><tr>
            <td><input data-sku-field="skuCode" value="OLD" /></td>
            <td><input data-sku-field="skuPrice" value="1.00" /></td>
            <td><input data-sku-field="cargoPrice" value="1.00" /></td>
            <td><input data-sku-field="ipmSkuStock" value="1" /></td>
          </tr></tbody></table>
        """)
        ambiguous = flow._fill_frozen_execution_payload_on_page(page, payload)
        title_after_ambiguous_preflight = page.locator('[name="title"]').input_value()
        browser.close()

    assert filled["ok"] is True, json.dumps(filled, ensure_ascii=False, indent=2)
    assert filled["write_attempted"] is True
    assert [item["field_key"] for item in filled["fields"]] == [
        "title",
        "material",
        "aeopAeProductSKUs",
    ]
    assert values == {
        "title": "Wireless Bluetooth Earbuds",
        "material": "ABS",
        "sku": ["SKU-70001", "9.99", "8.00", "12"],
    }
    assert readback["ok"] is True
    validated_readback = validate_frozen_execution_readback(
        readback,
        expected_payload=payload,
        expected_phase="after_prefill",
    )
    assert validated_readback == readback
    assert ambiguous["ok"] is False
    assert ambiguous["failure_code"] == "FROZEN_EXECUTION_BINDING_UNRESOLVED"
    assert ambiguous["write_attempted"] is False
    assert title_after_ambiguous_preflight == "Old title"


def test_save_network_audit_excludes_exact_read_only_schema_posts_from_mutations():
    class Request:
        resource_type = "xhr"

        def __init__(self, url: str):
            self.url = url
            self.method = "POST"

    class Response:
        status = 200

        def __init__(self, request: Request):
            self.request = request
            self.url = request.url

        def json(self):
            return {"code": 0, "msg": "success"}

    class Page:
        url = "https://www.dianxiaomi.com/web/smt/edit"

        def __init__(self):
            self.listeners: dict[str, list] = {"request": [], "response": []}

        def on(self, event_name, listener):
            self.listeners[event_name].append(listener)

        def remove_listener(self, event_name, listener):
            self.listeners[event_name].remove(listener)

        def emit(self, request: Request):
            for listener in list(self.listeners["request"]):
                listener(request)
            response = Response(request)
            for listener in list(self.listeners["response"]):
                listener(response)

    page = Page()
    flow = object.__new__(DxmLoginFlow)
    session = flow._capture_save_network_events(
        page,
        {"x": 1, "y": 1, "w": 10, "h": 10},
    )
    page.emit(Request("https://www.dianxiaomi.com/api/smtCategory/attributeList.json"))
    page.emit(Request("https://www.dianxiaomi.com/api/smtCategory/childAttributeList.json"))
    page.emit(Request("https://www.dianxiaomi.com/api/smtProduct/add.json"))

    result = flow._finalize_save_network_audit(page, session)
    audit = result["network_audit"]

    assert audit["read_only_schema_request_count"] == 2
    assert audit["mutation_request_count"] == 1
    assert audit["save_request_count"] == 1
    assert audit["other_mutation_request_count"] == 0
    assert flow._save_network_audit_complete(audit, result["publish_signal"]) is True

    unknown_page = Page()
    unknown_session = flow._capture_save_network_events(
        unknown_page,
        {"x": 1, "y": 1, "w": 10, "h": 10},
    )
    unknown_page.emit(
        Request("https://www.dianxiaomi.com/api/unknown/write-looking.json")
    )
    unknown_page.emit(Request("https://www.dianxiaomi.com/api/smtProduct/add.json"))
    unknown_result = flow._finalize_save_network_audit(
        unknown_page,
        unknown_session,
    )
    assert unknown_result["network_audit"]["other_mutation_request_count"] == 1
    assert (
        flow._save_network_audit_complete(
            unknown_result["network_audit"],
            unknown_result["publish_signal"],
        )
        is False
    )


def test_frozen_writer_never_uses_chinese_label_without_stable_binding():
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "weight",
                "ui_label_zh": "包装重量",
                "ui_binding": "dxm_editor:weight",
                "category_schema_path": "$.properties.weight",
                "resolved_value": "10",
            }
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    flow = object.__new__(DxmLoginFlow)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("""
          <style>input { display:block; width:200px; height:32px; }</style>
          <div class="ant-form-item">
            <label>包装重量</label>
            <input value="OLD" />
          </div>
        """)
        result = flow._fill_frozen_execution_payload_on_page(page, payload)
        observed = page.locator("input").input_value()
        browser.close()

    assert result["ok"] is False
    assert result["failure_code"] == "FROZEN_EXECUTION_BINDING_UNRESOLVED"
    assert result["write_attempted"] is False
    assert observed == "OLD"


def test_frozen_writer_rejects_hidden_control_before_any_write():
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "weight",
                "ui_label_zh": "包装重量",
                "ui_binding": "dxm_editor:weight",
                "category_schema_path": "$.properties.weight",
                "resolved_value": "10",
            }
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    flow = object.__new__(DxmLoginFlow)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("""
          <section data-ui-binding="dxm_editor:weight"
                   style="display:block;width:200px;height:32px">
            <input type="hidden" name="weight" value="OLD" />
          </section>
        """)
        result = flow._fill_frozen_execution_payload_on_page(page, payload)
        observed = page.locator("input").input_value()
        browser.close()

    assert result["ok"] is False
    assert result["failure_code"] == "FROZEN_EXECUTION_BINDING_UNRESOLVED"
    assert result["write_attempted"] is False
    assert observed == "OLD"


def test_frozen_writer_prevalidates_later_select_before_writing_earlier_field():
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "title",
                "ui_label_zh": "英文标题",
                "ui_binding": "dxm_editor:title",
                "category_schema_path": "$.properties.title",
                "resolved_value": "New title",
            },
            {
                "field_key": "material",
                "ui_label_zh": "材质",
                "ui_binding": "dxm_attribute:1001",
                "category_schema_path": "$.properties.material",
                "resolved_value": "ABS",
            },
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    flow = object.__new__(DxmLoginFlow)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("""
          <style>input,select,section { display:block; width:240px; height:32px; }</style>
          <section data-ui-binding="dxm_editor:title">
            <input name="title" value="Old title" />
          </section>
          <section data-ui-binding="dxm_attribute:1001" data-attribute-id="1001">
            <select name="material"><option value="Metal">Metal</option></select>
          </section>
        """)
        result = flow._fill_frozen_execution_payload_on_page(page, payload)
        title = page.locator('[name="title"]').input_value()
        material = page.locator('[name="material"]').input_value()
        browser.close()

    assert result["ok"] is False
    assert result["failure_code"] == "FROZEN_EXECUTION_BINDING_UNRESOLVED"
    assert result["write_attempted"] is False
    assert title == "Old title"
    assert material == "Metal"


def test_frozen_writer_and_readback_resolve_the_same_stable_attribute_control():
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "material",
                "ui_label_zh": "材质",
                "ui_binding": "dxm_attribute:1001",
                "category_schema_path": "$.properties.material",
                "resolved_value": "ABS",
            }
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    flow = object.__new__(DxmLoginFlow)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("""
          <style>input,select,section { display:block; width:240px; height:32px; }</style>
          <input name="material" value="WRONG" />
          <section data-attribute-id="1001">
            <select><option value="ABS" selected>ABS</option></select>
          </section>
        """)
        filled = flow._fill_frozen_execution_payload_on_page(page, payload)
        readback = flow._capture_frozen_execution_readback(
            page,
            payload,
            phase="after_prefill",
        )
        decoy = page.locator('[name="material"]').input_value()
        stable_value = page.locator('[data-attribute-id="1001"] select').input_value()
        browser.close()

    assert filled["ok"] is True
    assert readback["ok"] is True
    assert readback["fields"][0]["exact"] is True
    assert decoy == "WRONG"
    assert stable_value == "ABS"


def test_frozen_writer_prevalidates_later_choice_before_writing_earlier_field():
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "title",
                "ui_label_zh": "英文标题",
                "ui_binding": "dxm_editor:title",
                "category_schema_path": "$.properties.title",
                "resolved_value": "New title",
            },
            {
                "field_key": "color",
                "ui_label_zh": "颜色",
                "ui_binding": "dxm_attribute:1002",
                "category_schema_path": "$.properties.color",
                "resolved_value": "Blue",
            },
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    flow = object.__new__(DxmLoginFlow)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("""
          <style>input,section,label { display:block; width:240px; min-height:32px; }</style>
          <section data-ui-binding="dxm_editor:title">
            <input name="title" value="Old title" />
          </section>
          <section data-ui-binding="dxm_attribute:1002" data-attribute-id="1002">
            <label><input type="radio" value="Red" checked />Red</label>
          </section>
        """)
        result = flow._fill_frozen_execution_payload_on_page(page, payload)
        title = page.locator('[name="title"]').input_value()
        checked_value = page.locator('input[type="radio"]:checked').input_value()
        browser.close()

    assert result["ok"] is False
    assert result["failure_code"] == "FROZEN_EXECUTION_BINDING_UNRESOLVED"
    assert result["write_attempted"] is False
    assert title == "Old title"
    assert checked_value == "Red"


def test_shared_frozen_binding_runtime_round_trips_scalar_choice_to_contract():
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "color",
                "ui_label_zh": "颜色",
                "ui_binding": "dxm_attribute:1002",
                "category_schema_path": "$.properties.color",
                "resolved_value": "Blue",
            }
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    flow = object.__new__(DxmLoginFlow)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("""
          <style>section,label,input { display:block; width:240px; min-height:32px; }</style>
          <section data-ui-binding="dxm_attribute:1002" data-attribute-id="1002">
            <label><input type="radio" value="Red" checked />Red</label>
            <label><input type="radio" value="Blue" />Blue</label>
          </section>
        """)
        filled = flow._fill_frozen_execution_payload_on_page(page, payload)
        readback = flow._capture_frozen_execution_readback(
            page,
            payload,
            phase="after_prefill",
        )
        browser.close()

    assert filled["ok"] is True
    assert readback["ok"] is True
    assert readback["fields"][0]["aggregate_kind"] == "choice_group"
    assert readback["fields"][0]["match_count"] == 2
    assert validate_frozen_execution_readback(
        readback,
        expected_payload=payload,
        expected_phase="after_prefill",
    ) == readback


def test_frozen_sku_writer_requires_exact_stable_binding_marker():
    sku_rows = [
        {
            "skuCode": "SKU-1",
            "skuPrice": "12.50",
            "cargoPrice": "5.00",
            "ipmSkuStock": 7,
        }
    ]
    body = {
        "schema": "dxm.batch_draft_save.execution_payload.v1",
        "product_id": "70001",
        "category_id": "2621",
        "category_schema_hash": "A" * 64,
        "field_mapping_hash": "B" * 64,
        "resolution_hash": "C" * 64,
        "fields": [
            {
                "field_key": "aeopAeProductSKUs",
                "ui_label_zh": "SKU 列表",
                "ui_binding": "dxm_editor:aeopAeProductSKUs",
                "category_schema_path": "$.properties.aeopAeProductSKUs",
                "resolved_value": sku_rows,
            }
        ],
        "unresolved_fields": [],
        "price_validation": {},
    }
    payload = {**body, "payload_hash": canonical_sha256(body)}
    flow = object.__new__(DxmLoginFlow)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.set_content("""
          <style>table,input { display:table; width:240px; min-height:32px; }</style>
          <table>
            <thead><tr><th>SKU</th><th>零售价</th><th>货值</th><th>库存</th></tr></thead>
            <tbody><tr>
              <td><input data-sku-field="skuCode" value="OLD-SKU" /></td>
              <td><input data-sku-field="skuPrice" value="1.00" /></td>
              <td><input data-sku-field="cargoPrice" value="1.00" /></td>
              <td><input data-sku-field="ipmSkuStock" value="1" /></td>
            </tr></tbody>
          </table>
        """)
        result = flow._fill_frozen_execution_payload_on_page(page, payload)
        observed = page.locator('[data-sku-field="skuCode"]').input_value()
        browser.close()

    assert result["ok"] is False
    assert result["failure_code"] == "FROZEN_EXECUTION_BINDING_UNRESOLVED"
    assert result["write_attempted"] is False
    assert observed == "OLD-SKU"


def test_batch_save_prefill_stops_before_click_when_frozen_value_readback_drifts(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    private = repo.get_task_private(task["id"])
    defaults = runner._execution_defaults(
        private,
        None,
        job=private["jobs"][0],
    )
    flow = object.__new__(DxmLoginFlow)
    ok_result = {"ok": True, "stage": "ready"}
    monkeypatch.setattr(
        flow,
        "_capture_current_editor_category_schema",
        lambda _page, payload, **kwargs: {
            "schema": "dxm.editor.category_schema_readback.v1",
            "ok": True,
            "phase": kwargs["phase"],
            "expected_category_id": payload["category_id"],
            "observed_category_id": payload["category_id"],
            "expected_category_schema_hash": payload["category_schema_hash"],
            "observed_category_schema_hash": payload["category_schema_hash"],
            "category_source": "test",
            "reason": None,
        },
    )
    monkeypatch.setattr(
        flow,
        "_unsupported_dxm_reference_template_preflight",
        lambda _defaults: [],
    )
    monkeypatch.setattr(
        flow,
        "_fill_frozen_execution_payload_on_page",
        lambda *_args, **_kwargs: {
            "ok": True,
            "stage": "fill_frozen_execution_payload_ready",
            "write_attempted": True,
        },
    )
    monkeypatch.setattr(
        flow,
        "_fill_editor_required_defaults_on_page",
        lambda *_args, **_kwargs: deepcopy(ok_result),
    )
    monkeypatch.setattr(
        flow,
        "_fill_editor_variants_on_page",
        lambda *_args, **_kwargs: deepcopy(ok_result),
    )
    monkeypatch.setattr(
        flow,
        "_fill_media_assets_on_page",
        lambda *_args, **_kwargs: deepcopy(ok_result),
    )
    monkeypatch.setattr(
        flow,
        "_fill_compliance_defaults_on_page",
        lambda *_args, **_kwargs: deepcopy(ok_result),
    )
    monkeypatch.setattr(
        flow,
        "_repair_product_main_images_on_page",
        lambda *_args, **_kwargs: deepcopy(ok_result),
    )
    monkeypatch.setattr(
        flow,
        "_capture_save_field_integrity_snapshot",
        lambda *_args, **_kwargs: {
            "ok": True,
            "kind": "structured_nonempty_form_state",
            "field_count": 1,
            "nonempty_field_count": 1,
            "sha256": "A" * 64,
        },
    )
    monkeypatch.setattr(
        flow,
        "_capture_frozen_execution_readback",
        lambda *_args, **_kwargs: {
            "schema": "dxm.frozen_execution.readback.v1",
            "ok": False,
            "phase": "after_prefill",
            "execution_payload_hash": defaults["_frozen_execution_payload_hash"],
            "field_count": 1,
            "fields": [],
            "reason": "frozen_execution_value_mismatch",
        },
    )

    class Page:
        url = "https://www.dianxiaomi.com/web/smt/edit"

        def title(self):
            return "店小秘编辑页"

    result = flow._prepare_editor_page_for_save(
        Page(),
        defaults,
        require_explicit_defaults=True,
    )

    assert result["ok"] is False
    assert result["stage"] == "editor_save_prefill_failed"
    assert result["failure_code"] == "FROZEN_EXECUTION_READBACK_MISMATCH"


def test_batch_save_rejects_current_category_schema_drift_before_any_field_write(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    private = repo.get_task_private(task["id"])
    defaults = runner._execution_defaults(
        private,
        None,
        job=private["jobs"][0],
    )
    payload = defaults["_frozen_execution_payload"]
    flow = object.__new__(DxmLoginFlow)
    field_writes: list[str] = []
    monkeypatch.setattr(
        flow,
        "_capture_current_editor_category_schema",
        lambda _page, _payload, **_kwargs: {
            "schema": "dxm.editor.category_schema_readback.v1",
            "ok": False,
            "phase": "before_any_field_write",
            "expected_category_id": payload["category_id"],
            "observed_category_id": "999999",
            "expected_category_schema_hash": payload["category_schema_hash"],
            "observed_category_schema_hash": "F" * 64,
            "reason": "category_or_schema_drift",
        },
    )
    monkeypatch.setattr(
        flow,
        "_unsupported_dxm_reference_template_preflight",
        lambda _defaults: [],
    )
    monkeypatch.setattr(
        flow,
        "_fill_editor_required_defaults_on_page",
        lambda *_args, **_kwargs: field_writes.append("base") or {"ok": True},
    )

    class Page:
        url = "https://www.dianxiaomi.com/web/smt/edit"

    result = flow._prepare_editor_page_for_save(
        Page(),
        defaults,
        require_explicit_defaults=True,
    )

    assert result["ok"] is False
    assert result["failure_code"] == "FROZEN_CATEGORY_SCHEMA_DRIFT"
    assert result["write_attempted"] is False
    assert field_writes == []


def test_final_pre_dispatch_guard_rereads_every_frozen_value(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        product_count=1,
    )
    private = repo.get_task_private(task["id"])
    defaults = runner._execution_defaults(
        private,
        None,
        job=private["jobs"][0],
    )
    payload = defaults["_frozen_execution_payload"]
    value_hash = hashlib.sha256(b'"10"').hexdigest().upper()
    baseline_readback = {
        "schema": "dxm.frozen_execution.readback.v1",
        "ok": True,
        "phase": "after_prefill",
        "execution_payload_hash": payload["payload_hash"],
        "field_count": 1,
        "fields": [
            {
                "field_key": "weight",
                "ui_binding": "dxm_editor:weight",
                "expected_value_hash": value_hash,
                "observed_value_hash": value_hash,
                "match_count": 1,
                "aggregate_kind": "single",
                "exact": True,
            }
        ],
        "reason": None,
    }
    flow = object.__new__(DxmLoginFlow)
    flow._last_mutation_authorization_facts = None
    baseline_category_schema = {
        "schema": "dxm.editor.category_schema_readback.v1",
        "ok": True,
        "phase": "before_any_field_write",
        "expected_category_id": payload["category_id"],
        "observed_category_id": payload["category_id"],
        "expected_category_schema_hash": payload["category_schema_hash"],
        "observed_category_schema_hash": payload["category_schema_hash"],
        "category_source": "test",
        "reason": None,
    }
    target = _frozen_target(70001, "E3 Draft Shop")
    integrity = {
        "ok": True,
        "kind": "structured_nonempty_form_state",
        "field_count": 1,
        "nonempty_field_count": 1,
        "sha256": "A" * 64,
    }
    monkeypatch.setattr(flow, "_is_visible_dxm_editor_page", lambda _page: True)
    monkeypatch.setattr(
        flow,
        "_visible_exact_save_button_state",
        lambda _page: {
            "ok": True,
            "text": "保存",
            "exact_save_count": 1,
            "at_point_text": "保存",
            "rect": {"x": 1, "y": 1, "w": 10, "h": 10},
            "viewport": {},
        },
    )
    monkeypatch.setattr(
        flow,
        "_require_frozen_product_page_identity",
        lambda *_args, **_kwargs: {
            "ok": True,
            "product_identity_match": True,
            "store_identity_match": True,
            "source_identity_match": True,
            "target_identity": target,
            "expected_store_name": "E3 Draft Shop",
            "target_identity_sha256": canonical_sha256(target),
        },
    )
    monkeypatch.setattr(
        flow,
        "_capture_save_field_integrity_snapshot",
        lambda _page: deepcopy(integrity),
    )
    monkeypatch.setattr(
        flow,
        "_capture_frozen_execution_readback",
        lambda *_args, **_kwargs: {
            **deepcopy(baseline_readback),
            "ok": False,
            "phase": "before_ledger_begin_dispatch",
            "fields": [
                {
                    **deepcopy(baseline_readback["fields"][0]),
                    "observed_value_hash": "B" * 64,
                    "exact": False,
                }
            ],
            "reason": "frozen_execution_value_mismatch",
        },
    )
    monkeypatch.setattr(
        flow,
        "_capture_current_editor_category_schema",
        lambda *_args, **kwargs: {
            **deepcopy(baseline_category_schema),
            "phase": kwargs["phase"],
        },
    )
    monkeypatch.setattr(flow, "_structured_save_status_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(flow, "_capture_save_network_events", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        flow,
        "_finalize_save_network_audit",
        lambda *_args, **_kwargs: {
            "events": [],
            "network_audit": {},
            "publish_signal": {"detected": None},
        },
    )
    monkeypatch.setattr(flow, "_trace_workflow_event", lambda *_args, **_kwargs: None)

    def guarded_click(_page, _x, _y, **kwargs):
        return kwargs["pre_dispatch_guard"]().get("ok") is True

    monkeypatch.setattr(flow, "_click_point_with_native_window", guarded_click)

    class Page:
        url = "https://www.dianxiaomi.com/web/smt/edit"

    result = flow._save_only_on_page(
        Page(),
        target_identity=target,
        store_name="E3 Draft Shop",
        baseline_field_integrity=integrity,
        required_readback_complete=True,
        expected_execution_payload=payload,
        baseline_execution_readback=baseline_readback,
        baseline_category_schema_readback=baseline_category_schema,
    )

    assert result["save_result"]["save_click_dispatched"] is False
    assert result["save_result"]["pre_dispatch_readback"][
        "frozen_execution_readback"
    ]["ok"] is False


def test_batch_frozen_target_is_accepted_by_formal_browser_agent_protocol(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(tmp_path, monkeypatch)
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]

    target_identity = runner._frozen_batch_draft_target_identity(private, first_job)
    canonical = canonical_mutation_target_payload(
        "save_only",
        {
            "store_name": "E3 Draft Shop",
            "target_identity": target_identity,
        },
    )

    assert canonical["target_identity"] == target_identity
    assert canonical["target_source_urls"] == target_identity["source_urls"]


def test_batch_browser_request_uses_only_the_frozen_product_identity(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(tmp_path, monkeypatch)
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]

    spec = runner._workflow_action_worker_request(
        private,
        first_job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        {},
    )

    assert spec is not None
    _action, _code, _title, params = spec
    target = params["target_identity"]
    assert params["product_query"] == target["stable_identity"]["value"]
    assert params["target_source_urls"] == target["source_urls"]
    assert canonical_mutation_target_payload("save_only", params)[
        "target_identity"
    ] == target


def test_batch_save_builds_formal_consumed_lease_command_and_reserves_ledger(
    tmp_path,
    monkeypatch,
):
    repo, task, ids, _runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        approve=False,
    )
    facts = build_batch_draft_save_task_facts(
        task_id=task["id"],
        store_id=task["store_id"],
        product_ids=ids,
        plan_snapshot_id=task["payload"]["plan_snapshot_id"],
        plan_snapshot_hash=task["payload"]["plan_snapshot_hash"],
        path="A",
    )
    context = build_authorization_context(
        stage_task_facts=facts,
        runtime_instance_id="e3-runtime-instance",
        browser_session_id="e3-browser-session",
        git_head="1" * 40,
        worktree_identity=_worktree_identity("1" * 40, "formal-command"),
        l2_evidence_fingerprint="2" * 64,
        approved_by="ops-owner",
    )
    issued = datetime.now(timezone.utc)
    approval = repo.approve_and_start_task_with_authorization(
        task["id"],
        token="e3-formal-browser-agent-token",
        confirmation="CONFIRM_DXM_SAVE_ONLY",
        approved_by="ops-owner",
        authorization_context=context,
        lease_id="e3-batch-lease",
        issued_at=issued.isoformat(),
        expires_at=(issued + timedelta(minutes=5)).isoformat(),
        consumed_at=issued.isoformat(),
    )
    assert approval.ok is True

    class PersistentAdapterMarker:
        requires_persistent_browser_agent = True

    class RuntimeBinding:
        runtime_id = "e3-browser-runtime"

    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=PersistentAdapterMarker(),
        browser_agent_runtime=RuntimeBinding(),
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    assert repo.update_job(
        first_job["id"],
        status="running",
        current_step_code="SAVE_ONLY",
        current_step_name="只保存不发布",
    ) is True
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    frozen_defaults = runner._execution_defaults(
        private,
        None,
        job=first_job,
    )
    spec = runner._workflow_action_worker_request(
        private,
        first_job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        frozen_defaults,
    )
    assert spec is not None
    action, _code, _title, params = spec

    command = runner._build_browser_agent_command(
        private,
        first_job,
        StateName.SAVE_ONLY,
        action,
        params,
    )
    assert command.execution_payload_hash == frozen_defaults[
        "_frozen_execution_payload_hash"
    ]

    assert command.authorization_lease_id == "e3-batch-lease"
    assert command.stage_task_facts_fingerprint == facts["fingerprint"]
    assert command.job_id == first_job["id"]
    assert command.execution_mode == "batch_draft_save"
    assert "batch_draft_save_execution" not in command.params
    assert validate_browser_agent_command(command) == {"save_only_click": 1}
    assert MutationDispatchLedger(recover_inflight=False).reserve_command(command).ok is True


def test_batch_jit_authorization_rejects_command_target_outside_frozen_job(
    tmp_path,
    monkeypatch,
):
    repo, task, ids, _runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        approve=False,
    )
    import src.main as main

    browser_session_id = "e3-jit-session"
    backend_runtime_id = "e3-jit-runtime"
    git_head = "6" * 40
    l2_gate = {"status": "passed", "evidence": "e3-jit-command-binding"}
    facts = build_batch_draft_save_task_facts(
        task_id=task["id"],
        store_id=task["store_id"],
        product_ids=ids,
        plan_snapshot_id=task["payload"]["plan_snapshot_id"],
        plan_snapshot_hash=task["payload"]["plan_snapshot_hash"],
        path="A",
    )
    context = build_authorization_context(
        stage_task_facts=facts,
        runtime_instance_id=backend_runtime_id,
        browser_session_id=browser_session_id,
        git_head=git_head,
        worktree_identity=_worktree_identity(git_head, "jit-command"),
        l2_evidence_fingerprint=main._l2_authorization_fingerprint(l2_gate),
        approved_by="ops-owner",
    )
    issued = datetime.now(timezone.utc)
    approval = repo.approve_and_start_task_with_authorization(
        task["id"],
        token="e3-jit-token",
        confirmation="CONFIRM_DXM_SAVE_ONLY",
        approved_by="ops-owner",
        authorization_context=context,
        lease_id="e3-jit-lease",
        issued_at=issued.isoformat(),
        expires_at=(issued + timedelta(minutes=5)).isoformat(),
        consumed_at=issued.isoformat(),
    )
    assert approval.ok is True

    class PersistentAdapterMarker:
        requires_persistent_browser_agent = True

    class RuntimeBinding:
        runtime_id = "e3-jit-browser-runtime"

    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=PersistentAdapterMarker(),
        browser_agent_runtime=RuntimeBinding(),
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    assert repo.update_job(
        first_job["id"],
        status="running",
        current_step_code="SAVE_ONLY",
        current_step_name="只保存不发布",
    ) is True
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    frozen_defaults = runner._execution_defaults(
        private,
        None,
        job=first_job,
    )
    spec = runner._workflow_action_worker_request(
        private,
        first_job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        frozen_defaults,
    )
    assert spec is not None
    action, _code, _title, params = spec
    command = runner._build_browser_agent_command(
        private,
        first_job,
        StateName.SAVE_ONLY,
        action,
        params,
    )

    tampered_target = _frozen_target(79999, "E3 Draft Shop")
    tampered_params = {
        **command.params,
        "product_query": "79999",
        "target_source_urls": tampered_target["source_urls"],
        "target_identity": tampered_target,
    }
    tampered = replace(
        command,
        params=tampered_params,
        target_hash=mutation_target_hash("save_only", tampered_params),
    )
    assert validate_browser_agent_command(tampered) == {"save_only_click": 1}

    class RuntimeIdentity:
        instance_id = backend_runtime_id

    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "runtime_identity", RuntimeIdentity())
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: deepcopy(l2_gate))
    monkeypatch.setattr(main, "_current_browser_session_id", lambda: browser_session_id)
    jit_worktree = _worktree_identity(git_head, "jit-command")
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": git_head,
            "is_dirty": jit_worktree["git_dirty"],
            "status_count": jit_worktree["status_count"],
            "status_sha256": jit_worktree["status_sha256"],
            "execution_file_count": jit_worktree["execution_file_count"],
            "execution_tree_sha256": jit_worktree["execution_tree_sha256"],
        },
    )

    decision = main._authorize_browser_mutation(
        tampered,
        {"mutation_action": "save_only_click"},
    )

    assert decision == {
        "ok": False,
        "reason_code": "AUTH_COMMAND_TARGET_MISMATCH",
    }
    wrong_lease = "e3-jit-other-lease"
    lease_tampered = replace(
        command,
        authorization_lease_id=wrong_lease,
        mutation_scope_id=build_mutation_scope_id(
            authorization_lease_id=wrong_lease,
            task_id=command.task_id,
            job_id=command.job_id,
            state=command.state,
            action=command.action,
        ),
    )
    assert main._authorize_browser_mutation(
        lease_tampered,
        {"mutation_action": "save_only_click"},
    ) == {"ok": False, "reason_code": "AUTH_COMMAND_AUTHORIZATION_MISMATCH"}

    wrong_job_id = 999999
    job_tampered = replace(
        command,
        job_id=wrong_job_id,
        mutation_scope_id=build_mutation_scope_id(
            authorization_lease_id=command.authorization_lease_id,
            task_id=command.task_id,
            job_id=wrong_job_id,
            state=command.state,
            action=command.action,
        ),
    )
    assert main._authorize_browser_mutation(
        job_tampered,
        {"mutation_action": "save_only_click"},
    ) == {"ok": False, "reason_code": "AUTH_COMMAND_JOB_MISMATCH"}

    mode_tampered = replace(command, expected_page="semi_managed")
    assert main._authorize_browser_mutation(
        mode_tampered,
        {"mutation_action": "save_only_click"},
    ) == {"ok": False, "reason_code": "AUTH_COMMAND_MODE_MISMATCH"}

    downgraded_params = dict(tampered_params)
    downgraded_params.pop("batch_draft_save_execution", None)
    downgraded = replace(
        tampered,
        execution_mode="single_save",
        expected_page="semi_managed",
        params=downgraded_params,
        target_hash=mutation_target_hash("save_only", downgraded_params),
    )
    assert validate_browser_agent_command(downgraded) == {"save_only_click": 1}
    assert main._authorize_browser_mutation(
        downgraded,
        {"mutation_action": "save_only_click"},
    ) == {"ok": False, "reason_code": "AUTH_COMMAND_MODE_MISMATCH"}

    poisoned_execution_payload = deepcopy(
        command.params["defaults"]["_frozen_execution_payload"]
    )
    poisoned_execution_payload["fields"][0]["resolved_value"] = "999999"
    poisoned_body = {
        key: value
        for key, value in poisoned_execution_payload.items()
        if key != "payload_hash"
    }
    poisoned_execution_payload["payload_hash"] = canonical_sha256(poisoned_body)
    poisoned_defaults = deepcopy(command.params["defaults"])
    poisoned_defaults["weight"] = "999999"
    poisoned_defaults["_frozen_execution_payload"] = poisoned_execution_payload
    poisoned_defaults["_frozen_execution_payload_hash"] = poisoned_execution_payload[
        "payload_hash"
    ]
    poisoned_command = replace(
        command,
        params={**command.params, "defaults": poisoned_defaults},
        execution_payload_hash=poisoned_execution_payload["payload_hash"],
    )
    assert validate_browser_agent_command(poisoned_command) == {"save_only_click": 1}
    assert main._authorize_browser_mutation(
        poisoned_command,
        {"mutation_action": "save_only_click"},
    ) == {"ok": False, "reason_code": "AUTH_COMMAND_EXECUTION_MISMATCH"}

    pending_job = private["jobs"][1]
    pending_defaults = runner._execution_defaults(
        private,
        None,
        job=pending_job,
    )
    pending_spec = runner._workflow_action_worker_request(
        private,
        pending_job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        pending_defaults,
    )
    assert pending_spec is not None
    pending_action, _pending_code, _pending_title, pending_params = pending_spec
    pending_command = runner._build_browser_agent_command(
        private,
        pending_job,
        StateName.SAVE_ONLY,
        pending_action,
        pending_params,
    )
    assert validate_browser_agent_command(pending_command) == {"save_only_click": 1}
    assert main._authorize_browser_mutation(
        pending_command,
        {"mutation_action": "save_only_click"},
    ) == {"ok": False, "reason_code": "AUTH_COMMAND_QUEUE_STATE_MISMATCH"}

    import src.repository as repository_module

    monkeypatch.setattr(repository_module, "now_iso", lambda: "2099-01-01T00:00:00Z")
    assert repo.update_job(
        first_job["id"],
        status="running",
        current_step_code="SAVE_ONLY",
        current_step_name="只保存不发布（队列版本已变化）",
    ) is True
    assert main._authorize_browser_mutation(
        command,
        {"mutation_action": "save_only_click"},
    ) == {"ok": False, "reason_code": "AUTH_COMMAND_QUEUE_STATE_MISMATCH"}


def test_batch_save_crosses_persistent_browser_agent_with_real_authorization_and_ledger(
    tmp_path,
    monkeypatch,
):
    repo, task, ids, _runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        approve=False,
    )
    import src.main as main
    from src.core import config as config_module

    formal_evidence_root = tmp_path / "e3-formal-worker-evidence"
    formal_evidence_root.mkdir()
    monkeypatch.setattr(config_module, "SCREENSHOT_DIR", formal_evidence_root)
    monkeypatch.setattr(v1_runner_module, "SCREENSHOT_DIR", formal_evidence_root)
    monkeypatch.setattr(browser_agent_worker, "SCREENSHOT_DIR", formal_evidence_root)

    l2_gate = {"status": "passed", "evidence": "e3-formal-worker"}
    browser_session_id = "e3-formal-worker-session"
    backend_runtime_id = "e3-formal-backend-runtime"
    git_head = "5" * 40
    facts = build_batch_draft_save_task_facts(
        task_id=task["id"],
        store_id=task["store_id"],
        product_ids=ids,
        plan_snapshot_id=task["payload"]["plan_snapshot_id"],
        plan_snapshot_hash=task["payload"]["plan_snapshot_hash"],
        path="A",
    )
    context = build_authorization_context(
        stage_task_facts=facts,
        runtime_instance_id=backend_runtime_id,
        browser_session_id=browser_session_id,
        git_head=git_head,
        worktree_identity=_worktree_identity(git_head, "formal-worker"),
        l2_evidence_fingerprint=main._l2_authorization_fingerprint(l2_gate),
        approved_by="ops-owner",
    )
    issued = datetime.now(timezone.utc)
    approval = repo.approve_and_start_task_with_authorization(
        task["id"],
        token="e3-formal-worker-token",
        confirmation="CONFIRM_DXM_SAVE_ONLY",
        approved_by="ops-owner",
        authorization_context=context,
        lease_id="e3-formal-worker-lease",
        issued_at=issued.isoformat(),
        expires_at=(issued + timedelta(minutes=5)).isoformat(),
        consumed_at=issued.isoformat(),
    )
    assert approval.ok is True

    dispatches: list[str] = []

    class PersistentPathAAdapter:
        requires_persistent_browser_agent = True

        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.target_hash = None
            self.save_evidence_ref = None

        def browser_session_id(self):
            return browser_session_id

        def current_mutation_identity(self):
            return {
                "browser_session_id": browser_session_id,
                "page_url": "https://www.dianxiaomi.com/web/smt/edit",
                "page_kind": "editor",
                "target_hash": self.target_hash,
            }

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def save_only(self, *, store_name, target_identity, **_kwargs):
            decision = self.authorizer(
                {
                    **self.command_context,
                    "mutation_action": "save_only_click",
                },
                lambda: dispatches.append("save_only_click")
                or {"dispatched": True, "external_write": False},
            )
            assert decision["ok"] is True
            assert decision["executed"] is True
            canonical = _valid_save_result()
            E3WorkflowAdapter._bind_path_a_result(
                canonical,
                target_identity,
                store_name,
                "save_screenshot",
                execution_defaults=_kwargs.get("defaults"),
            )
            mutation_authorization = {
                "ok": True,
                "executed": True,
                "mutation_action": "save_only_click",
                "mutation_status": "DISPATCHED",
                "mutation_id": decision["mutation_id"],
            }
            canonical["after_values"]["mutation_authorization"] = mutation_authorization
            observations = canonical["evidence"]["observations"]
            observations["mutation_authorization"] = mutation_authorization
            observations["save_result"]["mutation_authorization"] = mutation_authorization
            evidence_ref = canonical["evidence"]["refs"][0]
            raw_ref = {
                key: evidence_ref[key]
                for key in ("path", "sha256", "size")
            }
            self.save_evidence_ref = deepcopy(raw_ref)
            return {
                "ok": True,
                "action": "save_only",
                "page_url": "https://www.dianxiaomi.com/web/smt/edit",
                "store_name": store_name,
                "target_identity": deepcopy(target_identity),
                "save_evidence_ref": raw_ref,
                "evidence_ref": raw_ref,
                "contract_facts": {
                    "before_values": canonical["before_values"],
                    "after_values": canonical["after_values"],
                    "postconditions": canonical["postconditions"],
                    "evidence_observations": observations,
                    "failure_code": None,
                    "recoverability": canonical["recoverability"],
                },
            }

        def verify_not_published(self, *, store_name, target_identity, **_kwargs):
            assert self.save_evidence_ref is not None
            time.sleep(0.01)
            canonical = _valid_unpublished_result()
            E3WorkflowAdapter._bind_path_a_result(
                canonical,
                target_identity,
                store_name,
                "unpublished_screenshot",
            )
            canonical["before_values"]["store_name"] = str(store_name or "")
            evidence_ref = canonical["evidence"]["refs"][0]
            raw_ref = {
                key: evidence_ref[key]
                for key in ("path", "sha256", "size")
            }
            return {
                "ok": True,
                "action": "verify_not_published",
                "page_url": "https://www.dianxiaomi.com/web/smt/edit",
                "store_name": store_name,
                "target_identity": deepcopy(target_identity),
                "unpublished_evidence_ref": raw_ref,
                "save_evidence_ref": deepcopy(self.save_evidence_ref),
                "evidence_ref": raw_ref,
                "contract_facts": {
                    "before_values": canonical["before_values"],
                    "after_values": canonical["after_values"],
                    "postconditions": canonical["postconditions"],
                    "evidence_observations": canonical["evidence"]["observations"],
                    "failure_code": None,
                    "recoverability": canonical["recoverability"],
                },
            }

    adapter = PersistentPathAAdapter()
    ledger = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: LiveDispatchFacts(
            runtime_instance_id=backend_runtime_id,
            browser_runtime_id=runtime.runtime_id,
            browser_session_id=browser_session_id,
            git_head=git_head,
            worktree_identity=_worktree_identity(git_head, "formal-worker"),
            l2_status="passed",
            l2_evidence_fingerprint=main._l2_authorization_fingerprint(l2_gate),
        ),
    )
    runtime = BrowserAgentRuntime(adapter, mutation_ledger=ledger)
    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    assert repo.update_job(
        first_job["id"],
        status="running",
        current_step_code="SAVE_ONLY",
        current_step_name="只保存不发布",
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    frozen_defaults = runner._execution_defaults(
        private,
        None,
        job=first_job,
    )
    spec = runner._workflow_action_worker_request(
        private,
        first_job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        frozen_defaults,
    )
    assert spec is not None
    action, _code, _title, params = spec
    command = runner._build_browser_agent_command(
        private,
        first_job,
        StateName.SAVE_ONLY,
        action,
        params,
    )
    adapter.target_hash = command.target_hash

    class RuntimeIdentity:
        instance_id = backend_runtime_id

    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "runtime_identity", RuntimeIdentity())
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: deepcopy(l2_gate))
    monkeypatch.setattr(main, "_current_browser_session_id", lambda: browser_session_id)
    formal_worktree = _worktree_identity(git_head, "formal-worker")
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": git_head,
            "is_dirty": formal_worktree["git_dirty"],
            "status_count": formal_worktree["status_count"],
            "status_sha256": formal_worktree["status_sha256"],
            "execution_file_count": formal_worktree["execution_file_count"],
            "execution_tree_sha256": formal_worktree["execution_tree_sha256"],
        },
    )
    runtime.set_mutation_authorizer(main._authorize_browser_mutation)

    assert main._authorize_browser_mutation(
        command,
        {"mutation_action": "save_only_click"},
    ) == {"ok": True, "reason_code": "OK"}
    drifted_worktree = {
        **formal_worktree,
        "execution_tree_sha256": _snapshot_hash("formal-worker-drift"),
    }
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": git_head,
            "is_dirty": drifted_worktree["git_dirty"],
            "status_count": drifted_worktree["status_count"],
            "status_sha256": drifted_worktree["status_sha256"],
            "execution_file_count": drifted_worktree["execution_file_count"],
            "execution_tree_sha256": drifted_worktree["execution_tree_sha256"],
        },
    )
    assert main._authorize_browser_mutation(
        command,
        {"mutation_action": "save_only_click"},
    ) == {"ok": False, "reason_code": "AUTH_CONTEXT_MISMATCH"}
    monkeypatch.setattr(
        main,
        "_current_git_summary",
        lambda: {
            "head": git_head,
            "is_dirty": formal_worktree["git_dirty"],
            "status_count": formal_worktree["status_count"],
            "status_sha256": formal_worktree["status_sha256"],
            "execution_file_count": formal_worktree["execution_file_count"],
            "execution_tree_sha256": formal_worktree["execution_tree_sha256"],
        },
    )

    assert runtime.reserve_command(command)["ok"] is True
    result = runtime.run(command, timeout_seconds=2)

    assert result["ok"] is True
    assert result["page_identity"]["kind"] == "editor"
    assert dispatches == ["save_only_click"]
    assert ledger.get_entry(
        command.mutation_scope_id,
        "save_only_click",
    )["status"] == "DISPATCHED"

    verify_spec = runner._workflow_action_worker_request(
        private,
        first_job,
        StateName.VERIFY_NOT_PUBLISHED,
        "E3_BATCH_DRAFT",
        {},
    )
    assert verify_spec is not None
    verify_action, _verify_code, _verify_title, verify_params = verify_spec
    verify_command = runner._build_browser_agent_command(
        private,
        first_job,
        StateName.VERIFY_NOT_PUBLISHED,
        verify_action,
        verify_params,
        preceding_save_result={
            "action_result": result,
            "browser_agent_command": command.to_payload(),
        },
    )
    verification_context = verify_command.params["save_verification_context"]
    assert verification_context["schema"] == "dxm.batch_draft_save.save_verification.v1"
    assert verification_context["task_id"] == task["id"]
    assert verification_context["job_id"] == first_job["id"]
    assert verification_context["plan_snapshot_hash"] == task["payload"]["plan_snapshot_hash"]
    assert verification_context["git_head"] == git_head
    assert verification_context["worktree_identity_sha256"] == canonical_sha256(
        formal_worktree
    )
    assert verification_context["save_command_id"] == command.command_id
    assert verification_context["save_action_result_sha256"] == canonical_sha256(
        result
    )
    assert validate_browser_agent_command(verify_command) == {}
    assert runtime.reserve_command(verify_command)["ok"] is True
    verification = runtime.run(verify_command, timeout_seconds=2)

    pair = validate_independent_save_verification_pair(
        result,
        verification,
        expected_page="editor",
        execution_mode="batch_draft_save",
        expected_execution_payload=command.params["defaults"]["_frozen_execution_payload"],
        expected_verification_context=verification_context,
        expected_save_command=command.to_payload(),
    )
    assert pair["save"]["page_identity"]["runtime_id"] == runtime.runtime_id
    assert pair["verification"]["page_identity"]["runtime_id"] == runtime.runtime_id
    assert pair["verification"]["after_values"]["published"] is False
    forged_verification = deepcopy(verification)
    forged_verification["before_values"]["save_verification_context"]["task_id"] = (
        task["id"] + 1
    )
    with pytest.raises(ActionResultContractError):
        validate_independent_save_verification_pair(
            result,
            forged_verification,
            expected_page="editor",
            execution_mode="batch_draft_save",
            expected_execution_payload=command.params["defaults"][
                "_frozen_execution_payload"
            ],
            expected_verification_context=verification_context,
        )
    assert dispatches == ["save_only_click"]
    runtime.shutdown()


@pytest.mark.parametrize("dispatch_state", ["DISPATCHING", "DISPATCHED"])
def test_startup_recovery_preserves_unknown_batch_save_and_leaves_tail_pending(
    tmp_path,
    monkeypatch,
    dispatch_state,
):
    repo, task, ids, _runner, _workflow = _runner_context(
        tmp_path,
        monkeypatch,
        approve=False,
    )
    facts = build_batch_draft_save_task_facts(
        task_id=task["id"],
        store_id=task["store_id"],
        product_ids=ids,
        plan_snapshot_id=task["payload"]["plan_snapshot_id"],
        plan_snapshot_hash=task["payload"]["plan_snapshot_hash"],
        path="A",
    )
    context = build_authorization_context(
        stage_task_facts=facts,
        runtime_instance_id="e3-restart-runtime-instance",
        browser_session_id="e3-restart-browser-session",
        git_head="3" * 40,
        worktree_identity=_worktree_identity("3" * 40, "restart"),
        l2_evidence_fingerprint="4" * 64,
        approved_by="ops-owner",
    )
    issued = datetime.now(timezone.utc)
    approval = repo.approve_and_start_task_with_authorization(
        task["id"],
        token="e3-restart-token",
        confirmation="CONFIRM_DXM_SAVE_ONLY",
        approved_by="ops-owner",
        authorization_context=context,
        lease_id="e3-restart-lease",
        issued_at=issued.isoformat(),
        expires_at=(issued + timedelta(minutes=5)).isoformat(),
        consumed_at=issued.isoformat(),
    )
    assert approval.ok is True

    class PersistentAdapterMarker:
        requires_persistent_browser_agent = True

    class RuntimeBinding:
        runtime_id = "e3-restart-browser-runtime"

    runner = V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=PersistentAdapterMarker(),
        browser_agent_runtime=RuntimeBinding(),
    )
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    assert repo.update_job(
        first_job["id"],
        status="running",
        current_step_code="SAVE_ONLY",
        current_step_name="只保存不发布（恢复窗口准备）",
    ) is True
    private = repo.get_task_private(task["id"])
    first_job = private["jobs"][0]
    frozen_defaults = runner._execution_defaults(
        private,
        None,
        job=first_job,
    )
    spec = runner._workflow_action_worker_request(
        private,
        first_job,
        StateName.SAVE_ONLY,
        "E3_BATCH_DRAFT",
        frozen_defaults,
    )
    assert spec is not None
    action, _code, _title, params = spec
    command = runner._build_browser_agent_command(
        private,
        first_job,
        StateName.SAVE_ONLY,
        action,
        params,
    )

    before_restart = MutationDispatchLedger(
        recover_inflight=False,
        live_facts_provider=lambda: LiveDispatchFacts(
            runtime_instance_id="e3-restart-runtime-instance",
            browser_runtime_id="e3-restart-browser-runtime",
            browser_session_id="e3-restart-browser-session",
            git_head="3" * 40,
            worktree_identity=_worktree_identity("3" * 40, "restart"),
            l2_status="passed",
            l2_evidence_fingerprint="4" * 64,
        ),
    )
    assert before_restart.reserve_command(command).ok is True
    assert before_restart.begin_dispatch(
        command,
        "save_only_click",
        {
                "browser_session_id": "e3-restart-browser-session",
                "page_url": "https://www.dianxiaomi.com/web/smt/edit",
                "page_kind": "editor",
                "target_hash": command.target_hash,
        },
    ).ok is True
    if dispatch_state == "DISPATCHED":
        assert before_restart.mark_dispatched(
            command,
            "save_only_click",
            {"dispatched": True, "external_write": False},
        ).ok is True
    repo.update_job(first_job["id"], status="running")

    restarted_ledger = MutationDispatchLedger()
    recovered_entry = restarted_ledger.get_entry(
        command.mutation_scope_id,
        "save_only_click",
    )
    assert recovered_entry["status"] == "UNKNOWN"
    assert recovered_entry["outcome"]["reason_code"] == {
        "DISPATCHING": "MUTATION_INTERRUPTED_INFLIGHT",
        "DISPATCHED": "SAVE_ACTION_RESULT_MISSING_AFTER_RESTART",
    }[dispatch_state]

    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "mutation_dispatch_ledger", restarted_ledger)
    recovery = main._recover_orphaned_runtime_tasks()

    refreshed = repo.get_task_private(task["id"])
    assert recovery == {"recovered": [task["id"]], "cancelled": []}
    assert refreshed["status"] == "needs_manual_review"
    assert refreshed["jobs"][0]["status"] == "unknown"
    assert refreshed["jobs"][0]["error_code"] == "UNKNOWN"
    assert refreshed["failed_jobs"] == 0
    assert [job["status"] for job in refreshed["jobs"][1:]] == ["pending", "pending"]
    retry = restarted_ledger.begin_dispatch(command, "save_only_click")
    assert retry.ok is False
    assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"


def test_execution_mode_accepts_batch_draft_save():
    assert normalize_execution_mode("batch_draft_save") is ExecutionMode.BATCH_DRAFT_SAVE
    assert ExecutionMode.BATCH_DRAFT_SAVE.value == "batch_draft_save"


def test_batch_draft_save_task_facts_path_a_only():
    facts = build_batch_draft_save_task_facts(
        task_id=1,
        store_id=2,
        product_ids=[10, 20, 30],
        plan_snapshot_id=99,
        plan_snapshot_hash=_snapshot_hash("facts"),
        path="A",
    )
    assert facts["stage"] == "batch_draft_save"
    assert facts["path"] == "A"
    assert facts["product_ids"] == [10, 20, 30]
    checked = verify_exact_stage_task_facts(facts, expected_stage="batch_draft_save")
    assert checked["ok"] is True

    with pytest.raises(TwoStageContractError) as exc:
        build_batch_draft_save_task_facts(
            task_id=1,
            store_id=2,
            product_ids=[10],
            plan_snapshot_id=99,
            plan_snapshot_hash=_snapshot_hash("facts-b"),
            path="B",
        )
    assert exc.value.reason_code == "BATCH_PATH_FORBIDDEN"


def test_create_task_api_rejects_direct_batch_draft_save(tmp_path, monkeypatch):
    client, repo, _runner, _main = _client(tmp_path, monkeypatch)
    store = repo.create_store("E3 Draft Shop", "AliExpress")
    response = client.post(
        "/api/tasks",
        json={
            "name": "direct batch_draft_save",
            "store_id": store["id"],
            "mode": "batch_draft_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [1, 2, 3],
        },
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    if isinstance(detail, dict):
        assert detail["reason_code"] == "BATCH_DRAFT_SAVE_CREATE_VIA_SNAPSHOT_ONLY"
    else:
        assert "batch_draft_save" in str(detail).lower()


def test_batch_save_still_unreleased(tmp_path, monkeypatch):
    client, repo, _runner, _main = _client(tmp_path, monkeypatch)
    store = repo.create_store("E3 Draft Shop", "AliExpress")
    response = client.post(
        "/api/tasks",
        json={
            "name": "legacy batch_save",
            "store_id": store["id"],
            "mode": "batch_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [1],
        },
    )
    assert response.status_code == 403
    assert "batch_save remains unreleased" in response.json()["detail"]


def test_path_b_rejected_on_atomic_approval(tmp_path, monkeypatch):
    client, repo, _runner, _main = _client(tmp_path, monkeypatch)
    task, _store, _ids, _digest = _create_batch_draft_task(repo, path="B")
    response = client.post(
        f"/api/tasks/{task['id']}/approve-and-start",
        json={"approved_by": "ops-owner", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["reason_code"] == "BATCH_PATH_B_FORBIDDEN"


def test_missing_plan_snapshot_rejected(tmp_path, monkeypatch):
    client, repo, _runner, _main = _client(tmp_path, monkeypatch)
    store = repo.create_store("E3 Draft Shop", "AliExpress")
    task = repo.create_task(
        {
            "name": "no snapshot",
            "store_id": store["id"],
            "mode": "batch_draft_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [70001, 70002],
            "payload": {
                "path": "A",
                "product_ids": [70001, 70002],
                "publish_allowed": False,
            },
        }
    )
    response = client.post(
        f"/api/tasks/{task['id']}/approve-and-start",
        json={"approved_by": "ops-owner", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reason_code"] == "BATCH_PLAN_SNAPSHOT_REQUIRED"


def test_batch_scope_reloads_persisted_snapshot_and_preserves_exact_order(
    tmp_path,
    monkeypatch,
):
    _api, repo, _runner, main = _client(tmp_path, monkeypatch)
    task, _store, _ids, _digest = _create_batch_draft_task(repo)
    private = repo.get_task_private(task["id"])

    main._assert_batch_draft_save_task_scope(private)

    reversed_jobs = deepcopy(private)
    reversed_jobs["jobs"] = list(reversed(reversed_jobs["jobs"]))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as reversed_error:
        main._assert_batch_draft_save_task_scope(reversed_jobs)
    assert reversed_error.value.detail["reason_code"] == "BATCH_JOB_ORDER_MISMATCH"

    drifted_snapshot = deepcopy(private)
    drifted_snapshot["payload"]["plan_snapshot"]["product_ids"][0] = "79999"
    with pytest.raises(HTTPException) as snapshot_error:
        main._assert_batch_draft_save_task_scope(drifted_snapshot)
    assert snapshot_error.value.detail["reason_code"] == (
        "BATCH_PLAN_SNAPSHOT_EMBEDDED_DRIFT"
    )


def test_publish_allowed_true_rejected(tmp_path, monkeypatch):
    _api, repo, _runner, main = _client(tmp_path, monkeypatch)
    task, _store, _ids, digest = _create_batch_draft_task(repo)
    private = repo.get_task_private(task["id"])
    poisoned = dict(private)
    poisoned_payload = dict(private.get("payload") or {})
    poisoned_payload["publish_allowed"] = True
    poisoned_payload["plan_snapshot"] = dict(poisoned_payload.get("plan_snapshot") or {})
    poisoned_payload["plan_snapshot"]["publish_allowed"] = True
    poisoned_payload["plan_snapshot"]["snapshot_hash"] = digest
    poisoned["payload"] = poisoned_payload
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        main._assert_batch_draft_save_task_scope(poisoned)
    assert exc.value.status_code == 403
    assert exc.value.detail["reason_code"] == "BATCH_PUBLISH_FORBIDDEN"


def test_batch_draft_save_manual_approval_requires_atomic_start(tmp_path, monkeypatch):
    client, repo, runner, _main = _client(tmp_path, monkeypatch)
    task, _store, _ids, _digest = _create_batch_draft_task(repo)
    private = repo.get_task_private(task["id"])
    assert private["mode"] == "batch_draft_save"
    assert len(private.get("jobs") or []) == 3

    approval = client.post(
        f"/api/tasks/{task['id']}/manual-approval",
        json={"approved_by": "ops-owner", "confirmation": "CONFIRM_DXM_SAVE_ONLY"},
    )
    assert approval.status_code == 409, approval.text
    assert approval.json()["detail"]["reason_code"] == "BATCH_APPROVAL_REQUIRES_ATOMIC_START"
    assert runner.workflow_adapter.calls == []
    reloaded = repo.get_task(task["id"])
    assert reloaded["status"] == "draft"
    assert reloaded["mode"] == "batch_draft_save"


def test_batch_draft_save_start_without_approval_fail_closed(tmp_path, monkeypatch):
    client, repo, runner, _main = _client(tmp_path, monkeypatch)
    task, _store, _ids, _digest = _create_batch_draft_task(repo)
    start = client.post(f"/api/tasks/{task['id']}/start", json={})
    assert start.status_code in {400, 403}
    assert runner.workflow_adapter.calls == []


def test_runner_steps_and_path_guard_for_batch_draft_save():
    from src.execution.v1_runner import MODE_LAST_STATE, V1TaskRunner
    from src.state_machine.contracts import StateName

    runner = V1TaskRunner(repo=None, manager=None)  # type: ignore[arg-type]
    steps = runner._steps_for_mode("batch_draft_save")
    assert steps
    assert any(state is StateName.SAVE_ONLY for state, _name, _domain in steps)
    assert MODE_LAST_STATE["batch_draft_save"] is StateName.RELEASE_LOCK

    task = {
        "mode": "batch_draft_save",
        "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
        "payload": {
            "path": "B",
            "plan_snapshot_id": 1,
            "plan_snapshot_hash": _snapshot_hash("runner-b"),
            "product_ids": [1],
            "plan_snapshot": {"path": "B", "snapshot_hash": _snapshot_hash("runner-b")},
        },
    }
    with pytest.raises(Exception) as exc:
        runner._guard_batch_draft_save_plan(task, {"product_id": 1})
    assert "Path B" in str(exc.value) or "path" in str(exc.value).lower()


def test_real_runner_batch_draft_save_uses_strict_path_a_order_and_stops_on_failure(
    tmp_path,
    monkeypatch,
):
    adapter = E3WorkflowAdapter(fail_action="save_only")
    repo, task, ids, runner, workflow = _runner_context(
        tmp_path,
        monkeypatch,
        adapter=adapter,
    )

    asyncio.run(runner.run_task(task["id"]))

    actions = [call[0] for call in workflow.calls]
    assert actions == [
        "check_login_state",
        "open_draft_box",
        "open_editor",
        "verify_edit_ownership",
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "save_only",
    ], repo.list_reports(task["id"])[0]["summary"].get("blocked_reason")
    assert "enable_semi_managed" not in actions
    assert "open_semi_managed_page" not in actions
    assert set(workflow.target_ids) == {ids[0]}
    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["status"] == "failed"
    assert all(job["status"] == "pending" for job in refreshed["jobs"][1:])


def test_real_runner_unknown_is_persisted_once_and_stops_batch_without_retry(
    tmp_path,
    monkeypatch,
):
    adapter = E3WorkflowAdapter(
        fail_action="open_editor",
        failure_code="UNKNOWN",
    )
    repo, task, _ids, runner, workflow = _runner_context(
        tmp_path,
        monkeypatch,
        adapter=adapter,
    )

    asyncio.run(runner.run_task(task["id"]))

    actions = [call[0] for call in workflow.calls]
    assert actions.count("open_editor") == 1
    assert "save_only" not in actions
    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "needs_manual_review"
    assert refreshed["jobs"][0]["status"] == "unknown"
    assert refreshed["jobs"][0]["error_code"] == "UNKNOWN"
    assert refreshed["failed_jobs"] == 0
    assert all(job["status"] == "pending" for job in refreshed["jobs"][1:])


def test_real_runner_path_a_three_evidence_chain_completes_serially(
    tmp_path,
    monkeypatch,
):
    repo, task, ids, runner, workflow = _runner_context(
        tmp_path,
        monkeypatch,
        approve=False,
    )
    git_head = "7" * 40
    facts = build_batch_draft_save_task_facts(
        task_id=task["id"],
        store_id=task["store_id"],
        product_ids=ids,
        plan_snapshot_id=task["payload"]["plan_snapshot_id"],
        plan_snapshot_hash=task["payload"]["plan_snapshot_hash"],
        path="A",
    )
    context = build_authorization_context(
        stage_task_facts=facts,
        runtime_instance_id="e3-report-runtime",
        browser_session_id="e3-report-session",
        git_head=git_head,
        worktree_identity=_worktree_identity(git_head, "terminal-report"),
        l2_evidence_fingerprint="8" * 64,
        approved_by="ops-owner",
    )
    issued = datetime.now(timezone.utc)
    approval = repo.approve_and_start_task_with_authorization(
        task["id"],
        token="e3-report-token",
        confirmation="CONFIRM_DXM_SAVE_ONLY",
        approved_by="ops-owner",
        authorization_context=context,
        lease_id="e3-report-lease",
        issued_at=issued.isoformat(),
        expires_at=(issued + timedelta(minutes=5)).isoformat(),
        consumed_at=issued.isoformat(),
    )
    assert approval.ok is True

    asyncio.run(runner.run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    actions = [call[0] for call in workflow.calls]
    assert refreshed["status"] == "completed", (
        reports[0]["summary"].get("blocked_reason") if reports else "missing report"
    )
    assert refreshed["completed_jobs"] == 3
    assert refreshed["failed_jobs"] == 0
    assert [report["product_id"] for report in reports] == ids
    assert all(report["status"] == "success" for report in reports)
    assert all(report["published"] is False for report in reports)
    assert [report["summary"]["queue_position"] for report in reports] == [1, 2, 3]
    assert all(report["summary"]["queue_total"] == 3 for report in reports)
    assert all(
        report["summary"]["plan_snapshot_hash"]
        == task["payload"]["plan_snapshot_hash"]
        for report in reports
    )
    assert all(
        report["summary"]["execution_identity"]
        == {
            "runtime_instance_id": "e3-report-runtime",
            "browser_session_id": "e3-report-session",
            "git_head": git_head,
            "worktree_identity": _worktree_identity(git_head, "terminal-report"),
            "authorization_fingerprint": context["fingerprint"],
            "authorization_lease_id": "e3-report-lease",
        }
        for report in reports
    )
    assert actions.count("save_only") == 3
    assert actions.count("verify_not_published") == 3
    assert "open_semi_managed_page" not in actions


def test_batch_pre_save_publish_guard_uses_validated_path_a_page_without_fake_network(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, _workflow = _runner_context(tmp_path, monkeypatch)

    class RecordingPublishGuard:
        def __init__(self):
            self.calls: list[dict] = []

        def check(self, **facts):
            self.calls.append(deepcopy(facts))
            return {
                "allowed": True,
                "risk_level": "low",
                "error_code": None,
                "reasons": [],
            }

    guard = RecordingPublishGuard()
    runner.publish_guard = guard

    asyncio.run(runner.run_task(task["id"]))

    pre_save_calls = [
        call for call in guard.calls if str(call.get("current_url") or "").strip()
    ]
    assert len(pre_save_calls) == 3
    assert {
        call["current_url"] for call in pre_save_calls
    } == {"https://www.dianxiaomi.com/web/smt/edit"}
    assert all("editFromSmt" not in call["current_url"] for call in pre_save_calls)
    assert all(call.get("network_urls") == [] for call in pre_save_calls)


def test_real_runner_missing_page_success_evidence_never_counts_as_success(
    tmp_path,
    monkeypatch,
):
    class MissingPageEvidenceAdapter(E3WorkflowAdapter):
        def save_only(self, **kwargs):
            result = super().save_only(**kwargs)
            result["evidence"]["observations"]["save_result"].pop(
                "page_save_result"
            )
            return result

    adapter = MissingPageEvidenceAdapter()
    repo, task, _ids, runner, workflow = _runner_context(
        tmp_path,
        monkeypatch,
        adapter=adapter,
    )

    asyncio.run(runner.run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    actions = [call[0] for call in workflow.calls]
    assert refreshed["status"] == "needs_manual_review"
    assert refreshed["completed_jobs"] == 0
    assert refreshed["failed_jobs"] == 0
    assert refreshed["jobs"][0]["status"] == "unknown"
    assert refreshed["jobs"][0]["error_code"] == "UNKNOWN"
    assert reports[0]["status"] == "unknown"
    assert "page_save_result" in reports[0]["summary"]["blocked_reason"]
    assert "verify_not_published" not in actions
    assert all(job["status"] == "pending" for job in refreshed["jobs"][1:])


def test_real_runner_save_dispatch_timeout_persists_unknown_without_retry(
    tmp_path,
    monkeypatch,
):
    class TimeoutAfterSaveDispatchAdapter(E3WorkflowAdapter):
        def save_only(self, **kwargs):
            self.calls.append(("save_only", kwargs))
            raise TimeoutError("simulated timeout after save dispatch")

    adapter = TimeoutAfterSaveDispatchAdapter()
    repo, task, _ids, runner, workflow = _runner_context(
        tmp_path,
        monkeypatch,
        adapter=adapter,
    )

    asyncio.run(runner.run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    actions = [call[0] for call in workflow.calls]
    assert refreshed["status"] == "needs_manual_review"
    assert refreshed["completed_jobs"] == 0
    assert refreshed["failed_jobs"] == 0
    assert refreshed["jobs"][0]["status"] == "unknown"
    assert refreshed["jobs"][0]["error_code"] == "UNKNOWN"
    assert actions.count("save_only") == 1
    assert "verify_not_published" not in actions
    assert all(job["status"] == "pending" for job in refreshed["jobs"][1:])


def test_batch_draft_save_atomic_approve_and_start_dispatches_real_runner_once(
    tmp_path,
    monkeypatch,
):
    repo, task, _ids, runner, workflow = _runner_context(
        tmp_path,
        monkeypatch,
        approve=False,
    )
    import src.main as main

    monkeypatch.setattr(main, "repo", repo)
    monkeypatch.setattr(main, "runner", runner)
    monkeypatch.setattr(main, "_current_browser_session_id", lambda: "e3-browser-session")
    monkeypatch.setattr(main, "l2_real_probe_gate", lambda: {"status": "passed"})
    scheduled_runner_coroutines = []

    def capture_runner_task(coroutine):
        scheduled_runner_coroutines.append(coroutine)
        return None

    with TestClient(app) as client:
        with monkeypatch.context() as task_scheduler_patch:
            task_scheduler_patch.setattr(main.asyncio, "create_task", capture_runner_task)
            response = client.post(
                f"/api/tasks/{task['id']}/approve-and-start",
                json={
                    "approved_by": "ops-owner",
                    "confirmation": "CONFIRM_DXM_SAVE_ONLY",
                },
            )
        assert response.status_code == 200, response.text
        assert response.json()["authorizationConsumed"] is True
        assert len(scheduled_runner_coroutines) == 1
        asyncio.run(scheduled_runner_coroutines[0])

    refreshed = repo.get_task_private(task["id"])
    approval = refreshed["payload"]["manual_approval"]
    assert approval["approved"] is True
    assert approval["consumed"] is True
    assert approval["consumed_at"]
    assert refreshed["status"] == "completed"
    assert [call[0] for call in workflow.calls].count("save_only") == 3


def test_real_runner_duplicate_start_does_not_redispatch_any_product(
    tmp_path,
    monkeypatch,
):
    repo, task, ids, runner, workflow = _runner_context(tmp_path, monkeypatch)

    async def duplicate_start():
        await asyncio.gather(
            runner.run_task(task["id"]),
            runner.run_task(task["id"]),
        )

    asyncio.run(duplicate_start())

    actions = [call[0] for call in workflow.calls]
    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "completed"
    assert refreshed["completed_jobs"] == len(ids)
    assert actions.count("save_only") == len(ids)
    assert actions.count("verify_not_published") == len(ids)
    assert len(repo.list_reports(task["id"])) == len(ids)
