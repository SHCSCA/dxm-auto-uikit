from __future__ import annotations

import os
import hashlib
import json
import struct
import threading
import time
import uuid
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from src.execution.action_result_contract import ACTION_RESULT_CONTRACTS
from src.execution.browser_agent_protocol import BrowserAgentCommand, browser_agent_command_from_worker_request
import src.execution.browser_agent_worker as browser_agent_worker
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.services.browser_agent_status import build_browser_hud


def _runtime_command(runtime, **kwargs):
    action = str(kwargs.get("action") or "")
    if action == "check_login_state":
        expected_page = "authenticated_dxm"
    elif action in {"open_data_acquisition", "claim_from_data_acquisition"}:
        expected_page = "data_acquisition"
    elif action in {"open_draft_box", "verify_draft_box_claim", "claim_product"}:
        expected_page = "draft_box"
    elif action in {
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "save_only",
        "verify_not_published",
    }:
        expected_page = "semi_managed"
    else:
        expected_page = "editor"
    kwargs.setdefault("command_id", f"test-{uuid.uuid4().hex}")
    kwargs.setdefault("idempotency_key", f"test-{uuid.uuid4().hex}")
    kwargs.setdefault("deadline", (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat())
    kwargs.setdefault("expected_page", expected_page)
    kwargs.setdefault("runtime_id", runtime.runtime_id)
    return BrowserAgentCommand(**kwargs)


def _complete_open_editor_raw(**overrides):
    result = {
        "ok": True,
        "action": "open_editor",
        "page_url": "https://www.dianxiaomi.com/web/smt/edit",
        "page_title": "编辑商品",
        "contract_facts": {
            "before_values": {"target": "product-1"},
            "after_values": {"editor": "product-1"},
            "postconditions": {
                "expected_editor_page": True,
                "editor_ready": True,
                "product_identity_match": True,
                "store_match": True,
                "source_identity_match": True,
            },
            "evidence_observations": {"editor_marker": "编辑商品"},
            "failure_code": None,
            "recoverability": {
                "kind": "none",
                "retryable": False,
                "requires_page_reverify": False,
                "reason": None,
            },
        },
    }
    result.update(overrides)
    return result


def _png_chunk(chunk_type, data):
    checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)


def _valid_png_bytes():
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    scanline = b"\x00\x00\x00\x00\x00"
    return (
        signature
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(scanline))
        + _png_chunk(b"IEND", b"")
    )


def _evidence_descriptor(path):
    content = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(content).hexdigest().upper(),
        "size": len(content),
    }


def _complete_draft_box_proof_raw(evidence_ref=None):
    result = {
        "ok": True,
        "action": "verify_draft_box_claim",
        "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        "contract_facts": {
            "before_values": {"target": "product-1"},
            "after_values": {"draft_box_target": "product-1"},
            "postconditions": {
                "draft_box_verified": True,
                "target_unique": True,
                "product_identity_match": True,
                "store_match": True,
                "source_identity_match": True,
                "claim_mark_match": True,
            },
            "evidence_observations": {"matched_product": "product-1"},
            "failure_code": None,
            "recoverability": {
                "kind": "none",
                "retryable": False,
                "requires_page_reverify": False,
                "reason": None,
            },
        },
    }
    if evidence_ref is not None:
        result["evidence_ref"] = evidence_ref
    return result


@pytest.fixture(autouse=True)
def _legacy_runtime_adapter_contract_bridge(monkeypatch, tmp_path):
    """Keep legacy runtime fakes focused on lifecycle behavior, not producer facts.

    The explicit producer-consumer boundary tests opt out or already return real
    ``contract_facts``. Production remains fail closed; this bridge only upgrades
    the many older in-module adapter fakes that predate the common envelope.
    """

    screenshot_root = tmp_path / "legacy-runtime-screenshots"
    screenshot_root.mkdir()
    proof_path = screenshot_root / "legacy-proof.png"
    proof_path.write_bytes(_valid_png_bytes())
    proof_ref = _evidence_descriptor(proof_path)
    monkeypatch.setattr(browser_agent_worker, "SCREENSHOT_DIR", screenshot_root)

    original_execute = browser_agent_worker.execute_browser_agent_action
    original_session_id = BrowserAgentRuntime._adapter_browser_session_id

    def _execute_with_legacy_contract(adapter, action, params=None):
        raw = original_execute(adapter, action, params)
        if (
            getattr(adapter, "preserve_raw_contract", False)
            or not isinstance(raw, dict)
            or "contract_facts" in raw
            or "ok" not in raw
            or type(raw["ok"]) is not bool
        ):
            return raw

        state_contracts = ACTION_RESULT_CONTRACTS.get(action)
        if not state_contracts:
            return raw
        expected_pages = {
            contract.expected_page for contract in state_contracts.values()
        }
        default_page_urls = {
            "authenticated_dxm": "https://www.dianxiaomi.com/web/home",
            "data_acquisition": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            "draft_box": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "editor": "https://www.dianxiaomi.com/web/smt/edit",
            "semi_managed": "https://www.dianxiaomi.com/web/smt/editFromSmt",
        }
        if len(expected_pages) == 1 and not raw.get("page_url"):
            raw["page_url"] = default_page_urls[next(iter(expected_pages))]
        required_postconditions = sorted(
            {
                postcondition
                for contract in state_contracts.values()
                for postcondition in contract.required_postconditions
            }
        )
        if raw["ok"] is True:
            raw["contract_facts"] = {
                "before_values": {"legacy_test_fixture": True},
                "after_values": {"legacy_test_fixture": True},
                "postconditions": {
                    postcondition: True
                    for postcondition in required_postconditions
                },
                "evidence_observations": {"legacy_test_fixture": True},
                "failure_code": None,
                "recoverability": {
                    "kind": "none",
                    "retryable": False,
                    "requires_page_reverify": False,
                    "reason": None,
                },
            }
            if action in {
                "verify_draft_box_claim",
                "save_only",
                "verify_not_published",
            }:
                raw.setdefault("evidence_ref", proof_ref)
        else:
            raw["contract_facts"] = {
                "before_values": {"legacy_test_fixture": True},
                "after_values": {},
                "postconditions": {
                    postcondition: False
                    for postcondition in required_postconditions
                },
                "evidence_observations": {},
                "failure_code": "TEST_ACTION_FAILED",
                "recoverability": {
                    "kind": "manual_takeover",
                    "retryable": False,
                    "requires_page_reverify": True,
                    "reason": str(
                        raw.get("error")
                        or raw.get("message")
                        or raw.get("reason")
                        or "legacy runtime fixture failure"
                    ),
                },
            }
        return raw

    def _session_id_with_legacy_fallback(self, adapter):
        if adapter is None:
            return original_session_id(self, adapter)
        getter = getattr(adapter, "browser_session_id", None)
        login_flow = getattr(adapter, "login_flow", None)
        login_getter = getattr(login_flow, "browser_session_id", None)
        if callable(getter) or callable(login_getter):
            return original_session_id(self, adapter)
        return "legacy-test-browser-session"

    monkeypatch.setattr(
        browser_agent_worker,
        "execute_browser_agent_action",
        _execute_with_legacy_contract,
    )
    monkeypatch.setattr(
        BrowserAgentRuntime,
        "_adapter_browser_session_id",
        _session_id_with_legacy_fallback,
    )


def test_browser_agent_command_protocol_roundtrips_caller_owned_execution_identity():
    payload = {
        "command_id": "cmd-protocol-1",
        "idempotency_key": "idem-protocol-1",
        "deadline": "2099-01-01T00:00:00+00:00",
        "expected_page": "draft_box",
        "runtime_id": "runtime-protocol-1",
        "task_id": 1,
        "job_id": 2,
        "state": "OPEN_DRAFT_LIST",
        "action": "open_draft_box",
        "params": {"store_name": "Dang Kang"},
        "step_label": "打开商品箱",
    }

    command = browser_agent_command_from_worker_request(payload)

    assert command.to_payload() == payload


def test_browser_agent_runtime_uses_caller_identity_without_polluting_exact_envelope():
    class Adapter:
        def open_draft_box(self):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
            }

    runtime = BrowserAgentRuntime(Adapter())
    command = BrowserAgentCommand(
        command_id="cmd-runtime-1",
        idempotency_key="idem-runtime-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=10,
        job_id=20,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    result = runtime.run(command)

    assert "command_id" not in result
    assert "idempotency_key" not in result
    assert "runtime_id" not in result
    assert result["page_identity"]["runtime_id"] == runtime.runtime_id
    assert result["action"] == "open_draft_box"
    assert result["attempted_state"] == "OPEN_DRAFT_LIST"
    runtime.shutdown()


@pytest.mark.parametrize(
    ("state", "action", "expected_page"),
    [
        ("OPEN_DRAFT_LIST", "save_only", "draft_box"),
        ("OPEN_DRAFT_LIST", "open_draft_box", "editor"),
    ],
    ids=["wrong-action", "wrong-page"],
)
def test_browser_agent_rejects_illegal_command_contract_before_adapter_or_authorizer(
    state,
    action,
    expected_page,
):
    adapter_calls = []
    authorizer_calls = []

    class Adapter:
        def open_draft_box(self):
            adapter_calls.append("open_draft_box")
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

        def save_only(self, **_kwargs):
            adapter_calls.append("save_only")
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/editFromSmt",
            }

    runtime = BrowserAgentRuntime(Adapter())
    runtime.set_mutation_authorizer(
        lambda *_args: authorizer_calls.append(True) or {"ok": True}
    )
    command = BrowserAgentCommand(
        command_id=f"cmd-invalid-{uuid.uuid4().hex}",
        idempotency_key=f"idem-invalid-{uuid.uuid4().hex}",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        expected_page=expected_page,
        runtime_id=runtime.runtime_id,
        task_id=12,
        job_id=13,
        state=state,
        action=action,
        params={},
    )

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_CONTRACT_MISMATCH"):
        runtime.run(command)

    assert adapter_calls == []
    assert authorizer_calls == []
    runtime.shutdown()


def test_browser_agent_rejects_mutation_action_outside_state_allowlist_before_upstream_auth():
    operation_calls = []
    upstream_calls = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "save_only_click"},
                lambda: operation_calls.append("executed"),
            )
            return {
                "ok": False,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "message": "mutation rejected",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(
        lambda *_args: upstream_calls.append(True) or {"ok": True}
    )
    result = runtime.run(
        _runtime_command(
            runtime,
            task_id=14,
            job_id=15,
            state="CLAIM_TO_DRAFT_BOX",
            action="claim_from_data_acquisition",
            params={"claim_mark": "AI-OPS"},
        )
    )

    assert result["ok"] is False
    assert adapter.authorization_result["reason"] == "browser_agent_mutation_action_not_allowed"
    assert adapter.authorization_result["executed"] is False
    assert operation_calls == []
    assert upstream_calls == []
    runtime.shutdown()


def test_browser_agent_open_edit_page_rejects_ok_without_contract_facts():
    class Adapter:
        preserve_raw_contract = True

        def browser_session_id(self):
            return "browser-session-contract-1"

        def open_editor(self, **_kwargs):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/edit",
            }

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(
        runtime,
        task_id=101,
        job_id=102,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={},
    )

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_ACTION_RESULT_CONTRACT_FAILURE"):
        runtime.run(command)

    runtime.shutdown()


def test_browser_agent_builds_and_validates_exact_canonical_action_result_envelope():
    class Adapter:
        def browser_session_id(self):
            return "browser-session-contract-2"

        def open_editor(self, **_kwargs):
            return _complete_open_editor_raw()

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(
        runtime,
        task_id=103,
        job_id=104,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={},
    )

    result = runtime.run(command)

    assert set(result) == {
        "schema_version",
        "ok",
        "action",
        "attempted_state",
        "before_values",
        "after_values",
        "postconditions",
        "evidence",
        "page_identity",
        "failure_code",
        "recoverability",
    }
    assert result == {
        "schema_version": "dxm.action-result.v1",
        "ok": True,
        "action": "open_editor",
        "attempted_state": "OPEN_EDIT_PAGE",
        "before_values": {"target": "product-1"},
        "after_values": {"editor": "product-1"},
        "postconditions": {
            "expected_editor_page": True,
            "editor_ready": True,
            "product_identity_match": True,
            "store_match": True,
            "source_identity_match": True,
        },
        "evidence": {
            "observations": {"editor_marker": "编辑商品"},
            "refs": [],
        },
        "page_identity": {
            "kind": "editor",
            "url": "https://www.dianxiaomi.com/web/smt/edit",
            "runtime_id": runtime.runtime_id,
            "browser_session_id": "browser-session-contract-2",
        },
        "failure_code": None,
        "recoverability": {
            "kind": "none",
            "retryable": False,
            "requires_page_reverify": False,
            "reason": None,
        },
    }
    assert runtime.status()["currentUrl"] == result["page_identity"]["url"]
    runtime.shutdown()


@pytest.mark.parametrize(
    "raw_overrides",
    [
        {"runtime_id": "runtime-other"},
        {"browser_session_id": "browser-session-other"},
        {"page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft"},
    ],
    ids=["wrong-runtime", "wrong-session", "wrong-page-url"],
)
def test_browser_agent_rejects_conflicting_producer_identity(raw_overrides):
    class Adapter:
        def browser_session_id(self):
            return "browser-session-contract-3"

        def open_editor(self, **_kwargs):
            return _complete_open_editor_raw(**raw_overrides)

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(
        runtime,
        task_id=105,
        job_id=106,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={},
    )

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_ACTION_RESULT_CONTRACT_FAILURE"):
        runtime.run(command)

    runtime.shutdown()


def test_browser_agent_rejects_raw_ok_true_with_false_contract_postcondition():
    class Adapter:
        def browser_session_id(self):
            return "browser-session-contract-false"

        def open_editor(self, **_kwargs):
            result = _complete_open_editor_raw()
            result["contract_facts"]["postconditions"]["editor_ready"] = False
            return result

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(
        runtime,
        task_id=111,
        job_id=112,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={},
    )

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_ACTION_RESULT_CONTRACT_FAILURE"):
        runtime.run(command)

    runtime.shutdown()


def test_browser_agent_rejects_non_boolean_raw_ok():
    class Adapter:
        def browser_session_id(self):
            return "browser-session-contract-non-boolean"

        def open_editor(self, **_kwargs):
            return _complete_open_editor_raw(ok=1)

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(
        runtime,
        task_id=113,
        job_id=114,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={},
    )

    with pytest.raises(RuntimeError, match="raw ok must be an exact boolean"):
        runtime.run(command)

    runtime.shutdown()


def test_browser_agent_returns_a_valid_explicit_failure_envelope():
    class Adapter:
        def browser_session_id(self):
            return "browser-session-contract-failure"

        def open_editor(self, **_kwargs):
            result = _complete_open_editor_raw(ok=False)
            result["contract_facts"] = {
                "before_values": {"target": "product-1"},
                "after_values": {},
                "postconditions": {"editor_ready": False},
                "evidence_observations": {},
                "failure_code": "EDITOR_NOT_READY",
                "recoverability": {
                    "kind": "manual_takeover",
                    "retryable": False,
                    "requires_page_reverify": True,
                    "reason": "editor marker was not observed",
                },
            }
            return result

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(
        runtime,
        task_id=115,
        job_id=116,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={},
    )

    result = runtime.run(command)

    assert result["ok"] is False
    assert result["failure_code"] == "EDITOR_NOT_READY"
    assert result["recoverability"]["kind"] == "manual_takeover"
    assert result["page_identity"]["runtime_id"] == runtime.runtime_id
    assert runtime.status()["status"] == "failed"
    assert runtime.status()["currentUrl"] == result["page_identity"]["url"]
    runtime.shutdown()


@pytest.mark.parametrize("reference_mode", ["missing", "bad-live-file"])
def test_browser_agent_proof_state_rejects_missing_or_bad_live_evidence(
    tmp_path,
    monkeypatch,
    reference_mode,
):
    screenshot_root = tmp_path / "screenshots"
    screenshot_root.mkdir()
    monkeypatch.setattr(browser_agent_worker, "SCREENSHOT_DIR", screenshot_root)
    evidence_ref = None
    if reference_mode == "bad-live-file":
        proof_path = screenshot_root / "bad-proof.png"
        proof_path.write_bytes(b"not-a-valid-png")
        evidence_ref = _evidence_descriptor(proof_path)

    class Adapter:
        def browser_session_id(self):
            return "browser-session-proof-bad"

        def verify_draft_box_claim(self, *_args, **_kwargs):
            return _complete_draft_box_proof_raw(evidence_ref)

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(
        runtime,
        task_id=107,
        job_id=108,
        state="VERIFY_DRAFT_BOX_CLAIM",
        action="verify_draft_box_claim",
        params={},
    )

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_ACTION_RESULT_CONTRACT_FAILURE"):
        runtime.run(command)

    runtime.shutdown()


def test_browser_agent_live_proof_builds_canonical_envelope_and_replays_exactly(
    tmp_path,
    monkeypatch,
):
    screenshot_root = tmp_path / "screenshots"
    screenshot_root.mkdir()
    monkeypatch.setattr(browser_agent_worker, "SCREENSHOT_DIR", screenshot_root)
    proof_path = screenshot_root / "draft-box-proof.png"
    proof_path.write_bytes(_valid_png_bytes())
    evidence_ref = _evidence_descriptor(proof_path)

    class Adapter:
        def __init__(self):
            self.calls = 0

        def browser_session_id(self):
            return "browser-session-proof-good"

        def verify_draft_box_claim(self, *_args, **_kwargs):
            self.calls += 1
            return _complete_draft_box_proof_raw(evidence_ref)

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(
        runtime,
        task_id=109,
        job_id=110,
        state="VERIFY_DRAFT_BOX_CLAIM",
        action="verify_draft_box_claim",
        params={},
    )

    first = runtime.run(command)
    replay = runtime.run(command)

    assert replay == first
    assert replay is not first
    assert adapter.calls == 1
    assert first["schema_version"] == "dxm.action-result.v1"
    assert first["page_identity"] == {
        "kind": "draft_box",
        "url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        "runtime_id": runtime.runtime_id,
        "browser_session_id": "browser-session-proof-good",
    }
    assert len(first["evidence"]["refs"]) == 1
    immutable_ref = first["evidence"]["refs"][0]
    assert immutable_ref["path"] == str(proof_path.resolve())
    assert immutable_ref["sha256"] == evidence_ref["sha256"]
    assert immutable_ref["size"] == evidence_ref["size"]
    assert immutable_ref["kind"] == "draft_box_screenshot"
    assert datetime.fromisoformat(immutable_ref["captured_at"]).tzinfo is not None
    runtime.shutdown()


def test_browser_agent_runtime_reuses_completed_idempotent_result_without_dispatching_twice():
    class Adapter:
        def __init__(self):
            self.calls = 0

        def open_draft_box(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        command_id="cmd-idem-1",
        idempotency_key="idem-once-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=11,
        job_id=21,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    first = runtime.run(command)
    second = runtime.run(command)

    assert first == second
    assert adapter.calls == 1
    runtime.shutdown()


def test_browser_agent_runtime_retry_may_refresh_transport_identity_and_deadline():
    class Adapter:
        def __init__(self):
            self.calls = 0

        def open_draft_box(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    semantics = {
        "idempotency_key": "idem-refresh-1",
        "expected_page": "draft_box",
        "runtime_id": runtime.runtime_id,
        "task_id": 111,
        "job_id": 211,
        "state": "OPEN_DRAFT_LIST",
        "action": "open_draft_box",
        "params": {},
    }
    first = runtime.run(
        BrowserAgentCommand(
            command_id="cmd-refresh-1",
            deadline=(datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat(),
            **semantics,
        )
    )
    replay = runtime.run(
        BrowserAgentCommand(
            command_id="cmd-refresh-2",
            deadline=(datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat(),
            **semantics,
        )
    )

    assert replay == first
    assert "command_id" not in replay
    assert replay["page_identity"]["runtime_id"] == runtime.runtime_id
    assert adapter.calls == 1
    runtime.shutdown()


def test_browser_agent_runtime_rejects_idempotency_key_reuse_with_different_payload():
    class Adapter:
        def open_draft_box(self):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    runtime = BrowserAgentRuntime(Adapter())
    base = {
        "idempotency_key": "idem-conflict-1",
        "deadline": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        "expected_page": "draft_box",
        "runtime_id": runtime.runtime_id,
        "task_id": 12,
        "job_id": 22,
        "state": "OPEN_DRAFT_LIST",
        "action": "open_draft_box",
        "params": {},
    }
    runtime.run(BrowserAgentCommand(command_id="cmd-conflict-1", **base))

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_IDEMPOTENCY_CONFLICT"):
        runtime.run(
            BrowserAgentCommand(
                command_id="cmd-conflict-2",
                **{**base, "params": {"store_name": "Different Store"}},
            )
        )

    runtime.shutdown()


def test_browser_agent_runtime_explicit_cancel_revokes_only_matching_command_and_releases_lease():
    started = threading.Event()
    release = threading.Event()
    errors = []

    class Adapter:
        def open_draft_box(self):
            started.set()
            assert release.wait(timeout=2)
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    runtime = BrowserAgentRuntime(Adapter())
    command = BrowserAgentCommand(
        command_id="cmd-cancel-1",
        idempotency_key="idem-cancel-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=13,
        job_id=23,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    def run_command():
        try:
            runtime.run(command)
        except BaseException as exc:
            errors.append(exc)

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert started.wait(timeout=1)

    assert runtime.cancel_command("cmd-other", runtime.runtime_id)["ok"] is False
    assert runtime.cancel_command(command.command_id, "runtime-other")["ok"] is False
    assert runtime.cancel_command(command.command_id, runtime.runtime_id)["ok"] is True
    release.set()
    run_thread.join(timeout=2)

    assert not run_thread.is_alive()
    assert errors and "BROWSER_AGENT_COMMAND_REVOKED" in str(errors[0])
    assert runtime.status()["active"] is False
    assert runtime.status()["status"] != "idle"
    runtime.shutdown()


def test_browser_agent_runtime_setup_failure_does_not_poison_idempotency_key():
    class Adapter:
        def open_draft_box(self):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    runtime = BrowserAgentRuntime()
    command = BrowserAgentCommand(
        command_id="cmd-setup-retry-1",
        idempotency_key="idem-setup-retry-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=14,
        job_id=24,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    with pytest.raises(RuntimeError, match="adapter is not configured"):
        runtime.run(command)
    runtime.set_adapter(Adapter())

    assert runtime.run(command)["ok"] is True
    runtime.shutdown()


def test_browser_agent_runtime_does_not_accept_semi_managed_page_as_plain_editor():
    class Adapter:
        def open_editor(self, **_kwargs):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/editFromSmt?id=1",
            }

    runtime = BrowserAgentRuntime(Adapter())
    command = BrowserAgentCommand(
        command_id="cmd-editor-boundary-1",
        idempotency_key="idem-editor-boundary-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        expected_page="editor",
        runtime_id=runtime.runtime_id,
        task_id=15,
        job_id=25,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={},
    )

    with pytest.raises(
        RuntimeError,
        match="BROWSER_AGENT_ACTION_RESULT_CONTRACT_FAILURE: expected exact editor DXM page URL",
    ):
        runtime.run(command)

    runtime.shutdown()


def test_browser_agent_runtime_absolute_deadline_bounds_wait_without_relative_timeout():
    class Adapter:
        def open_draft_box(self):
            time.sleep(0.2)
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    runtime = BrowserAgentRuntime(Adapter())
    command = BrowserAgentCommand(
        command_id="cmd-deadline-1",
        idempotency_key="idem-deadline-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=0.02)).isoformat(),
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=16,
        job_id=26,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        runtime.run(command)

    assert time.monotonic() - started < 0.15
    runtime.shutdown(timeout_seconds=1)


def test_browser_agent_reserved_command_cancelled_before_run_never_calls_adapter():
    class Adapter:
        def __init__(self):
            self.calls = 0

        def open_draft_box(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        command_id="cmd-reserved-cancel-1",
        idempotency_key="idem-reserved-cancel-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=17,
        job_id=27,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    assert runtime.reserve_command(command)["ok"] is True
    assert runtime.cancel_command(command.command_id, command.runtime_id)["ok"] is True
    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_CANCELLED_BEFORE_START"):
        runtime.run(command)

    assert adapter.calls == 0
    assert runtime.status()["active"] is False
    runtime.shutdown()


def test_cancelled_reservation_is_released_even_after_its_deadline_expires():
    class Adapter:
        def __init__(self):
            self.calls = 0

        def open_draft_box(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        command_id="cmd-reserved-expired-cancel-1",
        idempotency_key="idem-reserved-expired-cancel-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=0.02)).isoformat(),
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=18,
        job_id=28,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    assert runtime.reserve_command(command)["ok"] is True
    assert runtime.cancel_command(command.command_id, command.runtime_id)["ok"] is True
    time.sleep(0.03)

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_CANCELLED_BEFORE_START"):
        runtime.run(command)

    assert runtime.status()["reservedCommandCount"] == 0
    assert adapter.calls == 0
    runtime.shutdown()


def test_browser_agent_reserve_cancel_race_linearizes_before_adapter_dispatch():
    class Adapter:
        def __init__(self):
            self.calls = 0

        def open_draft_box(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    command = BrowserAgentCommand(
        command_id="cmd-reserve-race-1",
        idempotency_key="idem-reserve-race-1",
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
        expected_page="draft_box",
        runtime_id=runtime.runtime_id,
        task_id=18,
        job_id=28,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )
    barrier = threading.Barrier(2)
    reservation_done = threading.Event()
    cancel_results = []

    def reserve():
        barrier.wait()
        runtime.reserve_command(command)
        reservation_done.set()

    def cancel():
        barrier.wait()
        for _ in range(100):
            result = runtime.cancel_command(command.command_id, command.runtime_id)
            cancel_results.append(result)
            if result["ok"] is True:
                return
            if reservation_done.is_set():
                time.sleep(0.001)
            else:
                time.sleep(0.001)

    reserve_thread = threading.Thread(target=reserve)
    cancel_thread = threading.Thread(target=cancel)
    reserve_thread.start()
    cancel_thread.start()
    reserve_thread.join(timeout=2)
    cancel_thread.join(timeout=2)

    assert cancel_results[-1]["ok"] is True
    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_CANCELLED_BEFORE_START"):
        runtime.run(command)
    assert adapter.calls == 0
    runtime.shutdown()


def test_browser_agent_status_maps_acquisition_steps_to_chinese_hud():
    open_page = build_browser_hud({
        "task_name": "已有商品认领",
        "step": "OPEN_DATA_ACQUISITION",
        "status": "running",
        "store_name": "Dang Kang",
    })
    assert open_page["title"] == "正在打开待认领商品列表"
    assert open_page["line1"] == "进入店小秘已有待认领列表"
    assert open_page["line2"] == "店铺：Dang Kang"
    assert open_page["phase"] == "第一段：待认领商品"
    assert open_page["severity"] == "running"
    assert open_page["requires_user_action"] is False

    claim = build_browser_hud({
        "task_name": "已有商品认领",
        "step": "CLAIM_TO_DRAFT_BOX",
        "status": "running",
    })
    assert claim["title"] == "正在认领已有商品"
    assert claim["line1"] == "把已有待认领商品认领到商品箱"
    assert claim["human_next"] == "检查商品是否已进入商品箱"

    verify = build_browser_hud({
        "task_name": "已有商品认领",
        "step": "VERIFY_DRAFT_BOX_CLAIM",
        "status": "running",
    })
    assert verify["title"] == "正在确认商品箱"
    assert verify["line1"] == "检查商品是否已进入商品箱"
    assert verify["human_next"] == "选择该商品箱商品继续编辑保存"


def test_browser_agent_status_normalizes_legacy_collection_words_in_overrides():
    hud = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "OPEN_DRAFT_LIST",
        "status": "running",
        "title": "正在打开采集箱",
        "line1": "进入店小秘采集箱",
        "line2": "数据采集页已打开",
        "next_step": "认领到采集箱后继续",
        "maintenance_detail": "继续切换到采集箱",
    })

    assert hud["task_name"] == "商品箱编辑保存"
    assert hud["title"] == "正在打开商品箱"
    assert hud["line1"] == "进入店小秘商品箱"
    assert hud["line2"] == "已有待认领列表已打开"
    assert hud["human_next"] == "认领到商品箱后继续"
    assert hud["maintenance_detail"] == "继续切换到商品箱"


def test_browser_agent_status_maps_save_steps_to_chinese_hud():
    editor = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "OPEN_EDIT_PAGE",
        "status": "running",
    })
    assert editor["title"] == "正在打开编辑页"
    assert editor["line1"] == "进入商品编辑页"
    assert editor["phase"] == "第二段：商品箱编辑保存"

    fill = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "FILL_BASE_INFO",
        "status": "running",
    })
    assert fill["title"] == "正在编辑商品"
    assert fill["line1"] == "正在填写标题"
    assert fill["human_next"] == "继续填写价格、图片和物流信息"

    media = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "FILL_MEDIA",
        "status": "running",
    })
    assert media["title"] == "正在编辑商品"
    assert media["line1"] == "正在处理图片"

    save = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "SAVE_ONLY",
        "status": "running",
    })
    assert save["title"] == "正在只保存"
    assert save["line1"] == "只点击保存，不发布"
    assert save["guard"] == "只保存不发布"
    assert save["human_next"] == "确认商品没有发布"

    verify = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "VERIFY_NOT_PUBLISHED",
        "status": "running",
    })
    assert verify["title"] == "正在检查结果"
    assert verify["line1"] == "确认商品没有发布"
    assert verify["human_next"] == "查看保存结果和未发布证明"


def test_browser_agent_status_tells_user_browser_stays_open_after_terminal_states():
    done = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "RELEASE_LOCK",
        "status": "success",
    })
    assert done["title"] == "任务完成"
    assert "真实浏览器保持打开" in done["human_next"]
    assert done["requires_user_action"] is False

    failed = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "TASK_FAILED",
        "status": "failed",
    })
    assert failed["title"] == "当前步骤失败"
    assert "真实浏览器保持打开" in failed["human_next"]
    assert failed["requires_user_action"] is True


def test_browser_agent_status_failed_session_points_to_login_recheck():
    hud = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "PRECHECK_SESSION",
        "status": "failed",
        "error": "执行浏览器还没有登录店小秘；请在打开的真实浏览器完成登录后再检测。",
    })

    assert hud["title"] == "需要登录店小秘"
    assert hud["line1"] == "执行浏览器还没有登录店小秘；请在打开的真实浏览器完成登录后再检测。"
    assert hud["human_next"] == "在真实浏览器完成登录后重新检测"
    assert hud["phase"] == "等待登录"
    assert hud["requires_user_action"] is True


def test_browser_agent_status_does_not_put_step_code_in_maintenance_detail_for_normal_steps():
    hud = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "SAVE_ONLY",
        "status": "running",
    })

    assert hud["maintenance_detail"] is None


def test_browser_agent_status_hides_unknown_technical_step_from_default_copy():
    hud = build_browser_hud({
        "task_name": "商品箱编辑保存",
        "step": "SOME_INTERNAL_STEP",
        "status": "failed",
        "error": "Cannot switch to a different thread",
    })

    assert hud["title"] == "当前步骤需要处理"
    assert hud["line1"] == "请按控制台提示处理后重试"
    assert hud["severity"] == "error"
    assert hud["requires_user_action"] is True
    assert "SOME_INTERNAL_STEP" not in hud["title"]
    assert "Cannot switch" not in hud["line1"]
    assert "Cannot switch" in hud["maintenance_detail"]


def test_browser_agent_runtime_reports_last_internal_claim_step_on_timeout():
    class SlowClaimAdapter:
        def __init__(self):
            self.listener = None

        def set_workflow_event_listener(self, listener):
            self.listener = listener

        def recent_workflow_events(self):
            return [{
                "event": "data_acquisition_claim:target_find_start",
                "human_step": "定位待认领商品",
            }]

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            if self.listener:
                self.listener({
                    "event": "data_acquisition_claim:target_find_start",
                    "human_step": "定位待认领商品",
                })
            time.sleep(0.2)
            return {"ok": True}

    runtime = BrowserAgentRuntime(SlowClaimAdapter())
    command = _runtime_command(runtime,
        task_id=40,
        job_id=40,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
        step_label="认领到商品箱",
    )

    with pytest.raises(TimeoutError):
        runtime.run(command, timeout_seconds=0.02)

    status = runtime.status()
    assert status["healthy"] is False
    assert status["currentStep"] == "定位待认领商品"
    assert "定位待认领商品" in status["lastError"]
    assert any(event["action"] == "workflow_trace" and event["step"] == "定位待认领商品" for event in status["events"])
    runtime.shutdown()


def test_browser_agent_cancel_during_upstream_authorization_prevents_the_mutation():
    authorization_started = threading.Event()
    release_authorization = threading.Event()
    operation_calls = []
    run_errors = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: operation_calls.append("claim_confirm_click") or "clicked",
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    def authorize(_command, _context):
        authorization_started.set()
        assert release_authorization.wait(timeout=2)
        return {"ok": True, "policy": "operator-approved"}

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(authorize)
    command = _runtime_command(
        runtime,
        task_id=895,
        job_id=896,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except BaseException as exc:
            run_errors.append(exc)

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert authorization_started.wait(timeout=1)

    cancelled = runtime.cancel_command(command.command_id, command.runtime_id)
    release_authorization.set()
    run_thread.join(timeout=2)

    assert cancelled["ok"] is True
    assert operation_calls == []
    assert adapter.authorization_result["ok"] is False
    assert adapter.authorization_result["reason"] == "browser_agent_command_revoked"
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    runtime.shutdown()


def test_browser_agent_cancel_returns_pending_without_waiting_for_inflight_mutation_dispatch():
    operation_started = threading.Event()
    release_operation = threading.Event()
    operation_finished = threading.Event()
    cancel_returned = threading.Event()
    operation_calls = []
    cancel_result = {}
    run_errors = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            def mutate():
                operation_calls.append("entered")
                operation_started.set()
                assert release_operation.wait(timeout=2)
                operation_calls.append("finished")
                operation_finished.set()
                return "clicked"

            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                mutate,
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(
        lambda _command, _context: {"ok": True, "policy": "operator-approved"}
    )
    command = _runtime_command(
        runtime,
        task_id=897,
        job_id=898,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except BaseException as exc:
            run_errors.append(exc)

    def cancel_command():
        cancel_result.update(runtime.cancel_command(command.command_id, command.runtime_id))
        cancel_returned.set()

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert operation_started.wait(timeout=1)
    cancel_thread = threading.Thread(target=cancel_command)
    cancel_thread.start()

    assert cancel_returned.wait(timeout=0.2) is True
    assert cancel_result["ok"] is False
    assert cancel_result["status"] == "cancel_pending_dispatch_inflight"
    assert cancel_result["reasonCode"] == "BROWSER_AGENT_MUTATION_DISPATCH_INFLIGHT"
    assert operation_finished.is_set() is False
    release_operation.set()
    cancel_thread.join(timeout=1)
    run_thread.join(timeout=2)

    assert operation_finished.is_set()
    assert cancel_returned.is_set()
    assert operation_calls == ["entered", "finished"]
    assert adapter.authorization_result == {
        "ok": True,
        "policy": "operator-approved",
        "executed": True,
        "operation_result": "clicked",
        "command_id": command.command_id,
    }
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    runtime.shutdown()


def test_browser_agent_takeover_returns_pending_without_waiting_for_inflight_mutation_dispatch():
    operation_started = threading.Event()
    release_operation = threading.Event()
    operation_finished = threading.Event()
    takeover_returned = threading.Event()
    takeover_result = {}
    run_errors = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            def mutate():
                operation_started.set()
                assert release_operation.wait(timeout=2)
                operation_finished.set()
                return "clicked"

            self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                mutate,
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(lambda _command, _context: {"ok": True})
    command = _runtime_command(
        runtime,
        task_id=899,
        job_id=900,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except BaseException as exc:
            run_errors.append(exc)

    def takeover():
        takeover_result.update(runtime.request_manual_takeover(timeout_seconds=0.01))
        takeover_returned.set()

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert operation_started.wait(timeout=1)
    takeover_thread = threading.Thread(target=takeover)
    takeover_thread.start()

    assert takeover_returned.wait(timeout=0.2) is True
    assert takeover_result["ok"] is False
    assert takeover_result["status"] == "takeover_pending_dispatch_inflight"
    assert takeover_result["reasonCode"] == "BROWSER_AGENT_MUTATION_DISPATCH_INFLIGHT"
    assert operation_finished.is_set() is False
    release_operation.set()
    takeover_thread.join(timeout=1)
    run_thread.join(timeout=2)

    assert operation_finished.is_set()
    assert takeover_returned.is_set()
    assert runtime.status()["status"] in {"takeover_pending", "manual_takeover"}
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    runtime.shutdown()


def test_browser_agent_shutdown_returns_pending_without_waiting_for_inflight_mutation_dispatch():
    operation_started = threading.Event()
    release_operation = threading.Event()
    operation_finished = threading.Event()
    shutdown_returned = threading.Event()
    shutdown_result = {}
    run_errors = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            def mutate():
                operation_started.set()
                assert release_operation.wait(timeout=2)
                operation_finished.set()
                return "clicked"

            self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                mutate,
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

        def close_browser_session(self):
            return None

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(lambda _command, _context: {"ok": True})
    command = _runtime_command(
        runtime,
        task_id=901,
        job_id=902,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except BaseException as exc:
            run_errors.append(exc)

    def shutdown():
        shutdown_result.update(runtime.shutdown(timeout_seconds=0.01))
        shutdown_returned.set()

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert operation_started.wait(timeout=1)
    shutdown_thread = threading.Thread(target=shutdown)
    shutdown_thread.start()

    assert shutdown_returned.wait(timeout=0.2) is True
    assert shutdown_result["ok"] is False
    assert shutdown_result["status"] == "shutdown_pending_dispatch_inflight"
    assert shutdown_result["reasonCode"] == "BROWSER_AGENT_MUTATION_DISPATCH_INFLIGHT"
    assert operation_finished.is_set() is False
    release_operation.set()
    shutdown_thread.join(timeout=2)
    run_thread.join(timeout=2)

    assert operation_finished.is_set()
    assert shutdown_returned.is_set()
    assert runtime.status()["status"] in {"stopping", "stopped"}
    assert len(run_errors) <= 1
    assert all("BROWSER_AGENT_COMMAND_REVOKED" in str(error) for error in run_errors)
    runtime.shutdown()


def test_browser_agent_timeout_returns_without_waiting_for_mutation_dispatch():
    operation_started = threading.Event()
    release_operation = threading.Event()
    operation_finished = threading.Event()
    run_finished = threading.Event()
    run_errors = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            def mutate():
                operation_started.set()
                assert release_operation.wait(timeout=2)
                operation_finished.set()
                return "clicked"

            self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                mutate,
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(lambda _command, _context: {"ok": True})
    command = _runtime_command(
        runtime,
        task_id=913,
        job_id=914,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=0.05)
        except BaseException as exc:
            run_errors.append(exc)
        finally:
            run_finished.set()

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert operation_started.wait(timeout=1)

    assert run_finished.wait(timeout=0.2) is True
    assert operation_finished.is_set() is False
    assert len(run_errors) == 1
    assert isinstance(run_errors[0], TimeoutError)
    release_operation.set()
    run_thread.join(timeout=2)

    assert operation_finished.wait(timeout=2)
    assert run_finished.is_set()
    runtime.shutdown()


def test_browser_agent_mutation_operation_can_cancel_same_command_without_deadlock():
    cancel_result = {}
    run_errors = []

    class Adapter:
        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            def mutate():
                cancel_result.update(
                    runtime.cancel_command(
                        self.command_context["command_id"],
                        self.command_context["runtime_id"],
                    )
                )
                return "clicked"

            self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                mutate,
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    runtime = BrowserAgentRuntime(Adapter())
    runtime.set_mutation_authorizer(lambda _command, _context: {"ok": True})
    command = _runtime_command(
        runtime,
        task_id=915,
        job_id=916,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=1)
        except BaseException as exc:
            run_errors.append(exc)

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    run_thread.join(timeout=1)

    assert run_thread.is_alive() is False
    assert cancel_result["ok"] is False
    assert cancel_result["status"] == "cancel_pending_dispatch_inflight"
    assert cancel_result["reasonCode"] == "BROWSER_AGENT_MUTATION_DISPATCH_INFLIGHT"
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    runtime.shutdown()


@pytest.mark.parametrize(
    ("drift_field", "drift_value", "expected_reason"),
    [
        ("browser_session_id", "session-2", "browser_agent_mutation_session_drift"),
        (
            "page_url",
            "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition?store=other",
            "browser_agent_mutation_page_url_drift",
        ),
        ("page_kind", "draft_box", "browser_agent_mutation_page_kind_drift"),
        ("target_hash", "b" * 64, "browser_agent_mutation_target_drift"),
    ],
)
def test_browser_agent_rejects_auth_time_live_mutation_identity_drift(
    drift_field,
    drift_value,
    expected_reason,
):
    operation_calls = []

    class Adapter:
        requires_persistent_browser_agent = True

        def __init__(self):
            self.identity = {
                "browser_session_id": "session-1",
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "page_kind": "data_acquisition",
                "target_hash": "a" * 64,
            }
            self.authorization_result = None

        def browser_session_id(self):
            return self.identity["browser_session_id"]

        def current_mutation_identity(self):
            return dict(self.identity)

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: operation_calls.append("clicked"),
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)

    def authorize(_command, _context):
        adapter.identity[drift_field] = drift_value
        return {"ok": True, "policy": "operator-approved"}

    runtime.set_mutation_authorizer(authorize)
    command = _runtime_command(
        runtime,
        task_id=917,
        job_id=918,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
        target_hash="a" * 64,
    )

    try:
        runtime.run(command, timeout_seconds=1)
    except RuntimeError:
        pass

    assert operation_calls == []
    assert adapter.authorization_result["ok"] is False
    assert adapter.authorization_result["reason"] == expected_reason
    runtime.shutdown()


def test_browser_agent_mutation_dispatch_rejects_wrong_command_context_without_execution():
    operation_calls = []
    upstream_calls = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            wrong_context = {
                **self.command_context,
                "command_id": "wrong-command",
                "mutation_action": "claim_confirm_click",
            }
            self.authorization_result = self.authorizer(
                wrong_context,
                lambda: operation_calls.append("clicked"),
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(
        lambda command, context: upstream_calls.append((command, context)) or {"ok": True}
    )
    command = _runtime_command(
        runtime,
        task_id=903,
        job_id=904,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    result = runtime.run(command, timeout_seconds=2)

    assert result["ok"] is True
    assert upstream_calls == []
    assert operation_calls == []
    assert adapter.authorization_result == {
        "ok": False,
        "executed": False,
        "reason": "browser_agent_command_context_mismatch",
        "command_id": command.command_id,
    }
    runtime.shutdown()


def test_browser_agent_successful_mutation_dispatch_executes_once_and_returns_auth_diagnostics():
    operation_calls = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: operation_calls.append("clicked") or {"clicked": True},
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(
        lambda _command, _context: {
            "ok": True,
            "policy": "operator-approved",
            "authorization_id": "auth-1",
        }
    )
    command = _runtime_command(
        runtime,
        task_id=911,
        job_id=912,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    result = runtime.run(command, timeout_seconds=2)

    assert result["ok"] is True
    assert operation_calls == ["clicked"]
    assert adapter.authorization_result == {
        "ok": True,
        "policy": "operator-approved",
        "authorization_id": "auth-1",
        "executed": True,
        "operation_result": {"clicked": True},
        "command_id": command.command_id,
    }
    runtime.shutdown()


def test_browser_agent_cancel_between_mutations_prevents_the_next_dispatch():
    first_mutation_finished = threading.Event()
    release_second_mutation = threading.Event()
    operation_calls = []
    authorization_results = []
    upstream_calls = []
    run_errors = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            authorization_results.append(
                self.authorizer(
                    {**self.command_context, "mutation_action": "claim_open_dialog_click"},
                    lambda: operation_calls.append("first") or "first-clicked",
                )
            )
            first_mutation_finished.set()
            assert release_second_mutation.wait(timeout=2)
            authorization_results.append(
                self.authorizer(
                    {**self.command_context, "mutation_action": "claim_confirm_click"},
                    lambda: operation_calls.append("second") or "second-clicked",
                )
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(
        lambda command, context: upstream_calls.append((command, context)) or {"ok": True}
    )
    command = _runtime_command(
        runtime,
        task_id=905,
        job_id=906,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except BaseException as exc:
            run_errors.append(exc)

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert first_mutation_finished.wait(timeout=1)

    cancelled = runtime.cancel_command(command.command_id, command.runtime_id)
    release_second_mutation.set()
    run_thread.join(timeout=2)

    assert cancelled["ok"] is True
    assert operation_calls == ["first"]
    assert len(upstream_calls) == 1
    assert authorization_results[0]["executed"] is True
    assert authorization_results[0]["operation_result"] == "first-clicked"
    assert authorization_results[1]["executed"] is False
    assert authorization_results[1]["reason"] == "browser_agent_command_revoked"
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    runtime.shutdown()


@pytest.mark.parametrize("control_action", ["takeover", "shutdown"])
def test_browser_agent_lifecycle_revoke_during_upstream_authorization_prevents_mutation(
    control_action,
):
    authorization_started = threading.Event()
    release_authorization = threading.Event()
    operation_calls = []
    run_errors = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: operation_calls.append("clicked") or "clicked",
            )
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

        def close_browser_session(self):
            return None

    def authorize(_command, _context):
        authorization_started.set()
        assert release_authorization.wait(timeout=2)
        return {"ok": True, "policy": "operator-approved"}

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(authorize)
    command = _runtime_command(
        runtime,
        task_id=907,
        job_id=908,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except BaseException as exc:
            run_errors.append(exc)

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert authorization_started.wait(timeout=1)

    if control_action == "takeover":
        control_result = runtime.request_manual_takeover(timeout_seconds=0.01)
    else:
        control_result = runtime.shutdown(timeout_seconds=0.01)
    release_authorization.set()
    run_thread.join(timeout=2)

    assert control_result["ok"] is False
    assert operation_calls == []
    assert adapter.authorization_result["ok"] is False
    assert adapter.authorization_result["executed"] is False
    assert adapter.authorization_result["reason"] == "browser_agent_command_revoked"
    assert adapter.authorization_result["policy"] == "operator-approved"
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    runtime.shutdown()


def test_browser_agent_absolute_deadline_during_upstream_authorization_prevents_mutation():
    authorization_started = threading.Event()
    release_authorization = threading.Event()
    action_finished = threading.Event()
    operation_calls = []

    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: operation_calls.append("clicked") or "clicked",
            )
            action_finished.set()
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    def authorize(_command, _context):
        authorization_started.set()
        assert release_authorization.wait(timeout=2)
        return {"ok": True, "policy": "operator-approved"}

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(authorize)
    command = _runtime_command(
        runtime,
        task_id=909,
        job_id=910,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
        deadline=(datetime.now(timezone.utc) + timedelta(seconds=0.1)).isoformat(),
    )

    with pytest.raises(TimeoutError):
        runtime.run(command, timeout_seconds=2)

    assert authorization_started.is_set()
    release_authorization.set()
    assert action_finished.wait(timeout=2)

    assert operation_calls == []
    assert adapter.authorization_result["ok"] is False
    assert adapter.authorization_result["executed"] is False
    assert adapter.authorization_result["reason"] == "browser_agent_command_revoked"
    assert adapter.authorization_result["policy"] == "operator-approved"
    runtime.shutdown()


def test_browser_agent_runtime_revokes_timed_out_command_before_late_mutation():
    release_action = threading.Event()
    action_finished = threading.Event()
    upstream_authorizer_calls = []

    class LateMutationAdapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None
            self.mutation_count = 0

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            assert release_action.wait(timeout=2)
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: setattr(self, "mutation_count", self.mutation_count + 1),
            )
            action_finished.set()
            return {"ok": True}

    adapter = LateMutationAdapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(
        lambda command, context: upstream_authorizer_calls.append((command, context)) or {"ok": True}
    )
    command = _runtime_command(runtime,
        task_id=901,
        job_id=902,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    with pytest.raises(TimeoutError):
        runtime.run(command, timeout_seconds=0.02)

    release_action.set()
    assert action_finished.wait(timeout=2)
    assert adapter.mutation_count == 0
    assert upstream_authorizer_calls == []
    assert adapter.authorization_result == {
        "ok": False,
        "executed": False,
        "reason": "browser_agent_command_revoked",
        "command_id": adapter.command_context["command_id"],
    }
    runtime.shutdown()


def test_browser_agent_runtime_takeover_timeout_revokes_mutation_and_late_completion_cannot_restore_idle():
    action_started = threading.Event()
    release_action = threading.Event()
    run_finished = threading.Event()
    upstream_authorizer_calls = []
    run_errors = []

    class BlockingMutationAdapter:
        def __init__(self):
            self.authorizer = None
            self.saved_authorizer = None
            self.command_context = None
            self.authorization_result = None
            self.mutation_count = 0

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.saved_authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            action_started.set()
            assert release_action.wait(timeout=2)
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: setattr(self, "mutation_count", self.mutation_count + 1),
            )
            return {"ok": True}

    adapter = BlockingMutationAdapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(
        lambda command, context: upstream_authorizer_calls.append((command, context)) or {"ok": True}
    )
    command = _runtime_command(runtime,
        task_id=921,
        job_id=922,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except Exception as exc:
            run_errors.append(exc)
        finally:
            run_finished.set()

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert action_started.wait(timeout=1)

    takeover = runtime.request_manual_takeover(timeout_seconds=0.02)

    assert takeover["ok"] is False
    assert takeover["status"] == "takeover_pending"
    assert takeover["manualTakeover"] is False
    assert takeover["needsRestart"] is True
    release_action.set()
    assert run_finished.wait(timeout=2)
    run_thread.join(timeout=1)
    assert adapter.mutation_count == 0
    assert upstream_authorizer_calls == []
    assert adapter.authorization_result["reason"] == "browser_agent_command_revoked"
    assert adapter.saved_authorizer(
        {**adapter.command_context, "mutation_action": "claim_confirm_click"},
        lambda: setattr(adapter, "mutation_count", adapter.mutation_count + 1),
    )["reason"] == "browser_agent_command_revoked"
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    assert runtime.status()["status"] == "manual_takeover"
    assert runtime.status()["manualTakeover"] is True
    runtime.shutdown()


def test_browser_agent_runtime_running_takeover_waits_for_full_run_finalization_before_success():
    action_started = threading.Event()
    release_action = threading.Event()
    run_finished = threading.Event()
    run_errors = []

    class BlockingAdapter:
        def claim_from_data_acquisition(self, *_args, **_kwargs):
            action_started.set()
            assert release_action.wait(timeout=2)
            return {"ok": True}

    runtime = BrowserAgentRuntime(BlockingAdapter())
    command = _runtime_command(runtime,
        task_id=923,
        job_id=924,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except Exception as exc:
            run_errors.append(exc)
        finally:
            run_finished.set()

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert action_started.wait(timeout=1)

    takeover_result = {}
    takeover_thread = threading.Thread(
        target=lambda: takeover_result.update(runtime.request_manual_takeover(timeout_seconds=1))
    )
    takeover_thread.start()
    for _ in range(100):
        if runtime.status()["status"] == "takeover_pending":
            break
        time.sleep(0.005)
    assert runtime.status()["status"] == "takeover_pending"
    release_action.set()
    takeover_thread.join(timeout=1)
    takeover = takeover_result
    run_thread.join(timeout=1)

    assert takeover["ok"] is True
    assert run_finished.is_set()
    assert takeover["status"] == "manual_takeover"
    assert takeover["manualTakeover"] is True
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    runtime.shutdown()


def test_browser_agent_runtime_takeover_retry_stays_pending_until_old_run_settles():
    action_started = threading.Event()
    release_action = threading.Event()
    run_errors = []

    class BlockingAdapter:
        def claim_from_data_acquisition(self, *_args, **_kwargs):
            action_started.set()
            assert release_action.wait(timeout=2)
            return {"ok": True}

    runtime = BrowserAgentRuntime(BlockingAdapter())
    command = _runtime_command(runtime,
        task_id=925,
        job_id=926,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )
    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except Exception as exc:
            run_errors.append(exc)

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert action_started.wait(timeout=1)

    first = runtime.request_manual_takeover(timeout_seconds=0.01)
    second = runtime.request_manual_takeover(timeout_seconds=0.01)

    assert first["ok"] is False
    assert second["ok"] is False
    assert first["reasonCode"] == "BROWSER_AGENT_TAKEOVER_PENDING"
    assert second["status"] == "takeover_pending"
    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_STILL_RUNNING"):
        runtime.reset()
    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_IN_PROGRESS"):
        runtime.run(command, timeout_seconds=0.01)

    release_action.set()
    run_thread.join(timeout=2)
    for _ in range(100):
        if runtime.status()["status"] == "manual_takeover":
            break
        time.sleep(0.005)
    third = runtime.request_manual_takeover(timeout_seconds=0.01)
    assert third["ok"] is True
    assert third["status"] == "manual_takeover"
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    runtime.shutdown()


def test_browser_agent_runtime_shutdown_timeout_revokes_mutation_and_closes_only_after_old_run_settles():
    action_started = threading.Event()
    release_action = threading.Event()
    run_finished = threading.Event()
    close_finished = threading.Event()
    upstream_authorizer_calls = []
    run_errors = []

    class BlockingMutationAdapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None
            self.authorization_result = None
            self.mutation_count = 0
            self.action_thread = None
            self.close_thread = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.action_thread = threading.get_ident()
            action_started.set()
            assert release_action.wait(timeout=2)
            self.authorization_result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: setattr(self, "mutation_count", self.mutation_count + 1),
            )
            return {"ok": True}

        def close_browser_session(self):
            self.close_thread = threading.get_ident()
            close_finished.set()

    adapter = BlockingMutationAdapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.set_mutation_authorizer(
        lambda command, context: upstream_authorizer_calls.append((command, context)) or {"ok": True}
    )
    command = _runtime_command(runtime,
        task_id=927,
        job_id=928,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except Exception as exc:
            run_errors.append(exc)
        finally:
            run_finished.set()

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert action_started.wait(timeout=1)

    stopped = runtime.shutdown(timeout_seconds=0.02)

    assert stopped["ok"] is False
    assert stopped["status"] == "stopping"
    assert stopped["needsRestart"] is True
    assert close_finished.is_set() is False
    release_action.set()
    assert run_finished.wait(timeout=2)
    assert close_finished.wait(timeout=2)
    run_thread.join(timeout=1)
    assert adapter.mutation_count == 0
    assert upstream_authorizer_calls == []
    assert adapter.authorization_result["reason"] == "browser_agent_command_revoked"
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    assert adapter.close_thread == adapter.action_thread
    assert runtime.status()["status"] == "stopped"
    runtime.shutdown()


def test_browser_agent_runtime_running_shutdown_reports_success_only_after_run_and_session_close_finish():
    action_started = threading.Event()
    release_action = threading.Event()
    run_finished = threading.Event()
    close_finished = threading.Event()
    run_errors = []

    class BlockingAdapter:
        def claim_from_data_acquisition(self, *_args, **_kwargs):
            action_started.set()
            assert release_action.wait(timeout=2)
            return {"ok": True}

        def close_browser_session(self):
            close_finished.set()

    runtime = BrowserAgentRuntime(BlockingAdapter())
    command = _runtime_command(runtime,
        task_id=929,
        job_id=930,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except Exception as exc:
            run_errors.append(exc)
        finally:
            run_finished.set()

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert action_started.wait(timeout=1)
    shutdown_result = {}
    shutdown_thread = threading.Thread(
        target=lambda: shutdown_result.update(runtime.shutdown(timeout_seconds=1))
    )
    shutdown_thread.start()
    for _ in range(100):
        if runtime.status()["status"] == "stopping":
            break
        time.sleep(0.005)
    assert runtime.status()["status"] == "stopping"

    release_action.set()
    shutdown_thread.join(timeout=2)
    run_thread.join(timeout=2)

    assert shutdown_result["ok"] is True
    assert shutdown_result["status"] == "stopped"
    assert run_finished.is_set()
    assert close_finished.is_set()
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])
    assert runtime.status()["status"] == "stopped"
    assert runtime.status()["browserVisible"] is False
    runtime.shutdown()


def test_browser_agent_runtime_shutdown_retry_remains_fail_closed_until_stop_finishes():
    action_started = threading.Event()
    release_action = threading.Event()
    run_errors = []

    class BlockingAdapter:
        def claim_from_data_acquisition(self, *_args, **_kwargs):
            action_started.set()
            assert release_action.wait(timeout=2)
            return {"ok": True}

        def close_browser_session(self):
            return None

    runtime = BrowserAgentRuntime(BlockingAdapter())
    command = _runtime_command(runtime,
        task_id=931,
        job_id=932,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )
    def run_command():
        try:
            runtime.run(command, timeout_seconds=2)
        except Exception as exc:
            run_errors.append(exc)

    run_thread = threading.Thread(target=run_command)
    run_thread.start()
    assert action_started.wait(timeout=1)

    first = runtime.shutdown(timeout_seconds=0.01)
    second = runtime.shutdown(timeout_seconds=0.01)

    assert first["ok"] is False
    assert second["ok"] is False
    assert first["reasonCode"] == "BROWSER_AGENT_STOPPING"
    assert second["status"] == "stopping"
    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_STILL_RUNNING"):
        runtime.reset()
    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_IN_PROGRESS"):
        runtime.run(command, timeout_seconds=0.01)

    release_action.set()
    run_thread.join(timeout=2)
    for _ in range(100):
        if runtime.status()["status"] == "stopped":
            break
        time.sleep(0.005)
    third = runtime.shutdown(timeout_seconds=0.01)
    assert third["ok"] is True
    assert third["status"] == "stopped"
    assert len(run_errors) == 1
    assert "BROWSER_AGENT_COMMAND_REVOKED" in str(run_errors[0])


def test_browser_agent_runtime_idle_shutdown_is_singleflight_and_replays_terminal_result():
    close_started = threading.Event()
    release_close = threading.Event()
    second_started = threading.Event()
    second_finished = threading.Event()
    results = {}

    class Adapter:
        def __init__(self):
            self.close_calls = 0

        def close_browser_session(self):
            self.close_calls += 1
            close_started.set()
            assert release_close.wait(timeout=2)

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)

    first_thread = threading.Thread(
        target=lambda: results.update(first=runtime.shutdown(timeout_seconds=1))
    )

    def second_shutdown():
        second_started.set()
        try:
            results["second"] = runtime.shutdown(timeout_seconds=1)
        finally:
            second_finished.set()

    second_thread = threading.Thread(target=second_shutdown)
    first_thread.start()
    assert close_started.wait(timeout=1)
    second_thread.start()
    assert second_started.wait(timeout=1)
    assert second_finished.wait(timeout=0.05) is False
    assert adapter.close_calls == 1

    release_close.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert first_thread.is_alive() is False
    assert second_thread.is_alive() is False
    assert adapter.close_calls == 1
    assert results["first"] == results["second"]
    assert results["first"]["ok"] is True
    assert results["first"]["status"] == "stopped"
    assert runtime.shutdown(timeout_seconds=0.01) == results["first"]
    assert adapter.close_calls == 1


def test_browser_agent_runtime_reset_after_stopped_creates_one_new_execution_owner():
    class Adapter:
        def __init__(self):
            self.calls = 0

        def open_draft_box(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

        def close_browser_session(self):
            return None

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    assert runtime.shutdown(timeout_seconds=1)["status"] == "stopped"

    reset = runtime.reset(adapter)
    command = _runtime_command(runtime,
        task_id=933,
        job_id=934,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    assert reset["ok"] is True
    assert reset["browserAgent"]["status"] == "idle"
    assert runtime.run(command, timeout_seconds=1)["ok"] is True
    assert adapter.calls == 1
    runtime.shutdown()


def test_browser_agent_runtime_stopped_requires_reset_before_takeover():
    runtime = BrowserAgentRuntime()
    assert runtime.shutdown(timeout_seconds=1)["status"] == "stopped"

    takeover = runtime.request_manual_takeover(timeout_seconds=0.01)

    assert takeover["ok"] is False
    assert takeover["status"] == "stopped"
    assert takeover["reasonCode"] == "BROWSER_AGENT_STOPPED_REQUIRES_RESET"
    assert runtime.status()["status"] == "stopped"


def test_browser_agent_runtime_stopped_requires_reset_before_resume():
    runtime = BrowserAgentRuntime()
    assert runtime.shutdown(timeout_seconds=1)["status"] == "stopped"

    resumed = runtime.resume()

    assert resumed["ok"] is False
    assert resumed["status"] == "stopped"
    assert resumed["reasonCode"] == "BROWSER_AGENT_STOPPED_REQUIRES_RESET"
    assert runtime.status()["status"] == "stopped"


def test_browser_agent_runtime_stopped_requires_reset_before_new_run():
    class Adapter:
        def open_draft_box(self):
            raise AssertionError("stopped runtime must not dispatch a command")

    runtime = BrowserAgentRuntime(Adapter())
    assert runtime.shutdown(timeout_seconds=1)["status"] == "stopped"
    command = _runtime_command(runtime,
        task_id=937,
        job_id=938,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_STOPPED_REQUIRES_RESET"):
        runtime.run(command, timeout_seconds=0.01)


def test_browser_agent_runtime_resume_cannot_erase_failed_runtime_state():
    class Adapter:
        def open_draft_box(self):
            return {"ok": False, "message": "navigation failed"}

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(runtime,
        task_id=939,
        job_id=940,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )
    assert runtime.run(command, timeout_seconds=1)["ok"] is False
    assert runtime.status()["status"] == "failed"

    resumed = runtime.resume()

    assert resumed["ok"] is False
    assert resumed["status"] == "failed"
    assert resumed["reasonCode"] == "BROWSER_AGENT_RESUME_NOT_ALLOWED"
    runtime.shutdown()


def test_browser_agent_runtime_rejects_takeover_while_reset_owns_lifecycle_transition():
    close_started = threading.Event()
    release_close = threading.Event()
    reset_result = {}

    class Adapter:
        def close_browser_session(self):
            close_started.set()
            assert release_close.wait(timeout=2)

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    reset_thread = threading.Thread(target=lambda: reset_result.update(runtime.reset(adapter)))
    reset_thread.start()
    assert close_started.wait(timeout=1)

    try:
        takeover = runtime.request_manual_takeover(timeout_seconds=0.01)

        assert takeover["ok"] is False
        assert takeover["status"] == "resetting"
        assert takeover["reasonCode"] == "BROWSER_AGENT_RESET_IN_PROGRESS"
    finally:
        release_close.set()
        reset_thread.join(timeout=2)
    assert reset_result["ok"] is True
    assert runtime.status()["status"] == "idle"
    runtime.shutdown()


def test_browser_agent_runtime_rejects_resume_while_reset_owns_lifecycle_transition():
    close_started = threading.Event()
    release_close = threading.Event()
    reset_result = {}

    class Adapter:
        def close_browser_session(self):
            close_started.set()
            assert release_close.wait(timeout=2)

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    reset_thread = threading.Thread(target=lambda: reset_result.update(runtime.reset(adapter)))
    reset_thread.start()
    assert close_started.wait(timeout=1)

    try:
        resumed = runtime.resume()

        assert resumed["ok"] is False
        assert resumed["status"] == "resetting"
        assert resumed["reasonCode"] == "BROWSER_AGENT_RESET_IN_PROGRESS"
    finally:
        release_close.set()
        reset_thread.join(timeout=2)
    assert reset_result["ok"] is True
    assert runtime.status()["status"] == "idle"
    runtime.shutdown()


def test_browser_agent_runtime_rejects_shutdown_while_reset_owns_lifecycle_transition():
    close_started = threading.Event()
    release_close = threading.Event()
    shutdown_finished = threading.Event()
    reset_result = {}
    shutdown_result = {}

    class Adapter:
        def __init__(self):
            self.close_calls = 0

        def close_browser_session(self):
            self.close_calls += 1
            close_started.set()
            assert release_close.wait(timeout=2)

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    reset_thread = threading.Thread(target=lambda: reset_result.update(runtime.reset(adapter)))
    reset_thread.start()
    assert close_started.wait(timeout=1)

    def request_shutdown():
        try:
            shutdown_result.update(runtime.shutdown(timeout_seconds=0.01))
        finally:
            shutdown_finished.set()

    shutdown_thread = threading.Thread(target=request_shutdown)
    shutdown_thread.start()
    try:
        assert shutdown_finished.wait(timeout=0.2)
        assert shutdown_result["ok"] is False
        assert shutdown_result["status"] == "resetting"
        assert shutdown_result["reasonCode"] == "BROWSER_AGENT_RESET_IN_PROGRESS"
        assert adapter.close_calls == 1
    finally:
        release_close.set()
        reset_thread.join(timeout=2)
        shutdown_thread.join(timeout=2)
    assert reset_result["ok"] is True
    assert runtime.status()["status"] == "idle"
    runtime.shutdown()


def test_browser_agent_runtime_keeps_execution_owned_after_worker_returns_until_outer_finalize_finishes(
    monkeypatch,
):
    outer_processing = threading.Event()
    release_outer = threading.Event()

    class BlockingResult(dict):
        def __init__(self, value):
            super().__init__(value)
            self.ok_reads = 0

        def get(self, key, default=None):
            if key == "ok":
                self.ok_reads += 1
                if self.ok_reads == 2:
                    outer_processing.set()
                    assert release_outer.wait(timeout=2)
            return super().get(key, default)

    original_validate = browser_agent_worker.validate_action_result_envelope

    def _validate_with_blocking_outer_result(*args, **kwargs):
        return BlockingResult(original_validate(*args, **kwargs))

    monkeypatch.setattr(
        browser_agent_worker,
        "validate_action_result_envelope",
        _validate_with_blocking_outer_result,
    )

    class Adapter:
        def open_draft_box(self):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            }

        def close_browser_session(self):
            return None

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(runtime,
        task_id=935,
        job_id=936,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
    )
    run_thread = threading.Thread(target=lambda: runtime.run(command, timeout_seconds=2))
    run_thread.start()
    assert outer_processing.wait(timeout=1)

    try:
        with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_STILL_RUNNING"):
            runtime.reset()
        with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_IN_PROGRESS"):
            runtime.run(command, timeout_seconds=0.01)
    finally:
        release_outer.set()
        run_thread.join(timeout=2)
        runtime.shutdown()


def test_browser_agent_runtime_refuses_reset_and_new_command_until_timed_out_future_stops():
    release_old_action = threading.Event()
    old_action_finished = threading.Event()

    class BlockingAdapter:
        def __init__(self):
            self.call_count = 0

        def set_mutation_authorizer(self, _authorizer, _command_context=None):
            return None

        def clear_mutation_authorizer(self):
            return None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.call_count += 1
            if self.call_count == 1:
                assert release_old_action.wait(timeout=2)
                old_action_finished.set()
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            }

    adapter = BlockingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(runtime,
        task_id=911,
        job_id=912,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
    )

    with pytest.raises(TimeoutError):
        runtime.run(command, timeout_seconds=0.02)

    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_STILL_RUNNING"):
        runtime.reset(adapter)
    with pytest.raises(RuntimeError, match="BROWSER_AGENT_COMMAND_IN_PROGRESS"):
        runtime.run(command, timeout_seconds=0.02)
    assert adapter.call_count == 1

    release_old_action.set()
    assert old_action_finished.wait(timeout=2)
    reset_result = None
    for _ in range(100):
        try:
            reset_result = runtime.reset(adapter)
            break
        except RuntimeError as exc:
            assert "BROWSER_AGENT_COMMAND_STILL_RUNNING" in str(exc)
            time.sleep(0.01)
    assert reset_result is not None
    assert reset_result["ok"] is True

    assert runtime.run(
        _runtime_command(
            runtime,
            task_id=911,
            job_id=912,
            state="CLAIM_TO_DRAFT_BOX",
            action="claim_from_data_acquisition",
            params={"claim_mark": "AI-OPS"},
        ),
        timeout_seconds=1,
    )["ok"] is True
    assert adapter.call_count == 2
    runtime.shutdown()


def test_browser_agent_runtime_normalizes_workflow_trace_step_copy():
    class LegacyTraceAdapter:
        def __init__(self):
            self.listener = None

        def set_workflow_event_listener(self, listener):
            self.listener = listener

        def recent_workflow_events(self):
            return [{"human_step": "进入店小秘采集箱"}]

        def open_draft_box(self):
            if self.listener:
                self.listener({"human_step": "进入店小秘采集箱"})
            time.sleep(0.2)
            return {"ok": True}

    runtime = BrowserAgentRuntime(LegacyTraceAdapter())
    command = _runtime_command(runtime,
        task_id=42,
        job_id=42,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
        step_label="打开采集箱",
    )

    with pytest.raises(TimeoutError):
        runtime.run(command, timeout_seconds=0.02)

    status = runtime.status()
    assert status["currentStep"] == "进入店小秘商品箱"
    assert "进入店小秘商品箱" in status["lastError"]
    assert any(event["step"] == "进入店小秘商品箱" for event in status["events"])
    runtime.shutdown()


def test_browser_agent_runtime_applies_hud_inside_agent_thread_before_action():
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["human_action"]))
            return {"ok": True, "updated": True, "hud": hud}

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            self.calls.append(("claim",))
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "page_title": "店小秘--待认领列表",
            }

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(runtime,
        task_id=41,
        job_id=41,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS", "store_name": "Dang Kang"},
        step_label="认领到商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert adapter.calls[0] == ("hud", "CLAIM_TO_DRAFT_BOX", "把已有待认领商品认领到商品箱")
    assert adapter.calls[1] == ("claim",)
    assert adapter.calls[-1][0] == "hud"
    status = runtime.status()
    assert status["hud"]["state"] == "CLAIM_TO_DRAFT_BOX"
    assert status["message"] == "把已有待认领商品认领到商品箱"
    assert status["nextAction"] == "检查商品是否已进入商品箱"
    runtime.shutdown()


def test_browser_agent_runtime_does_not_write_page_hud_for_navigation_actions():
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["status"]))
            return {"ok": True, "updated": True, "hud": hud}

        def open_draft_box(self):
            self.calls.append(("open_draft_box",))
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "page_title": "店小秘--速卖通产品",
            }

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(runtime,
        task_id=41,
        job_id=41,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={"store_name": "Dang Kang"},
        step_label="打开商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert adapter.calls == [("open_draft_box",)]
    status = runtime.status()
    assert status["status"] == "idle"
    assert status["hud"]["status"] == "success"
    runtime.shutdown()


def test_browser_agent_runtime_does_not_write_page_hud_for_open_editor():
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["status"]))
            return {"ok": True, "updated": True, "hud": hud}

        def open_editor(self, **kwargs):
            self.calls.append(("open_editor", kwargs.get("product_query")))
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=1",
                "page_title": "店小秘--编辑产品",
            }

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(runtime,
        task_id=42,
        job_id=42,
        state="OPEN_EDIT_PAGE",
        action="open_editor",
        params={"store_name": "Dang Kang", "product_query": "目标商品"},
        step_label="打开编辑页",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert adapter.calls == [("open_editor", "目标商品")]
    assert runtime.status()["hud"]["status"] == "success"
    runtime.shutdown()


@pytest.mark.parametrize(
    ("action", "state"),
    [
        ("verify_edit_ownership", "VERIFY_EDIT_OWNERSHIP"),
        ("fill_editor_required_defaults", "FILL_BASE_INFO"),
        ("save_only", "SAVE_ONLY"),
        ("verify_not_published", "VERIFY_NOT_PUBLISHED"),
    ],
)
def test_browser_agent_runtime_defers_page_hud_for_editor_and_save_actions(action, state):
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["status"]))
            return {"ok": True, "updated": True, "hud": hud}

        def verify_edit_ownership(self, **kwargs):
            self.calls.append(("verify_edit_ownership", kwargs.get("product_query")))
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=1", "page_title": "店小秘--编辑产品"}

        def fill_editor_required_defaults(self, **kwargs):
            self.calls.append(("fill_editor_required_defaults", kwargs.get("product_query")))
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=1", "page_title": "店小秘--编辑产品"}

        def save_only(self, **kwargs):
            self.calls.append(("save_only", kwargs.get("product_query")))
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/smt/editFromSmt?id=1", "page_title": "店小秘--半托管编辑"}

        def verify_not_published(self, **kwargs):
            self.calls.append(("verify_not_published", kwargs.get("product_query")))
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/smt/editFromSmt?id=1", "page_title": "店小秘--半托管编辑"}

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(runtime,
        task_id=43,
        job_id=43,
        state=state,
        action=action,
        params={"store_name": "Dang Kang", "product_query": "目标商品"},
        step_label="编辑页动作",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert all(call[0] != "hud" for call in adapter.calls)
    assert adapter.calls == [(action, "目标商品")]
    runtime.shutdown()


def test_browser_agent_runtime_does_not_write_page_hud_for_login_check():
    class HudRecordingAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["status"]))
            return {"ok": True, "updated": True, "hud": hud}

        def check_login_state(self):
            self.calls.append(("check_login_state",))
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/home",
                "page_title": "店小秘--首页",
            }

    adapter = HudRecordingAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(runtime,
        task_id=41,
        job_id=41,
        state="PRECHECK_SESSION",
        action="check_login_state",
        params={"store_name": "Dang Kang"},
        step_label="检查店小秘登录状态",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert adapter.calls == [("check_login_state",)]
    status = runtime.status()
    assert status["status"] == "idle"
    assert status["hud"]["status"] == "success"
    runtime.shutdown()


def test_browser_agent_runtime_writes_request_result_and_trace_files(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_agent_worker, "DATA_DIR", tmp_path)

    class TraceWritingAdapter:
        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, _hud):
            return {"ok": True, "updated": True}

        def open_draft_box(self):
            trace_file = os.environ.get("DXM_WORKFLOW_TRACE_FILE")
            assert trace_file
            with open(trace_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"event": "navigate:return", "human_step": "商品箱页面已打开"}, ensure_ascii=False) + "\n")
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "page_title": "店小秘--速卖通产品",
            }

    runtime = BrowserAgentRuntime(TraceWritingAdapter())
    command = _runtime_command(runtime,
        task_id=88,
        job_id=99,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={},
        step_label="打开商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert "browser_agent_request_file" not in result
    assert "browser_agent_result_file" not in result
    assert "workflow_trace_file" not in result
    worker_dir = tmp_path / "workflow_worker"
    request_file = next(worker_dir.glob("*.request.json"))
    result_file = next(worker_dir.glob("*.result.json"))
    trace_file = next(worker_dir.glob("*.trace.jsonl"))
    assert os.path.exists(request_file)
    assert os.path.exists(result_file)
    assert os.path.exists(trace_file)
    assert json.loads(open(request_file, encoding="utf-8").read())["action"] == "open_draft_box"
    persisted = json.loads(open(result_file, encoding="utf-8").read())
    assert persisted["ok"] is True
    assert persisted["result"] == result
    assert persisted["transport"] == {
        "command_id": command.command_id,
        "idempotency_key": command.idempotency_key,
        "runtime_id": runtime.runtime_id,
        "workflow_trace_file": str(trace_file),
        "browser_agent_request_file": str(request_file),
        "browser_agent_result_file": str(result_file),
    }
    assert "商品箱页面已打开" in open(trace_file, encoding="utf-8").read()
    runtime.shutdown()


def test_browser_agent_runtime_does_not_apply_success_hud_after_failed_action():
    class FailedNavigationAdapter:
        def __init__(self):
            self.calls = []

        def set_workflow_event_listener(self, _listener):
            return None

        def update_live_hud(self, hud):
            self.calls.append(("hud", hud["state"], hud["human_action"]))
            if len([call for call in self.calls if call[0] == "hud"]) > 1:
                raise AssertionError("failed browser action must not write a success HUD")
            return {"ok": True, "updated": True, "hud": hud}

        def open_draft_box(self):
            self.calls.append(("open_draft_box",))
            return {
                "ok": False,
                "stage": "workflow_navigation_failed",
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "message": "商品箱静置后仍未加载完成",
            }

    adapter = FailedNavigationAdapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(runtime,
        task_id=42,
        job_id=42,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={"store_name": "Dang Kang"},
        step_label="打开商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is False
    assert adapter.calls == [
        ("open_draft_box",),
    ]
    status = runtime.status()
    assert status["status"] == "failed"
    assert status["healthy"] is False
    assert "商品箱静置后仍未加载完成" in status["lastError"]
    runtime.shutdown()


def test_browser_agent_runtime_enables_stable_visible_workflow_profile(monkeypatch, tmp_path):
    captured = {}

    class Adapter:
        def set_workflow_event_listener(self, _listener):
            return None

        def open_draft_box(self):
            captured["persistent"] = os.environ.get("DXM_WORKFLOW_PERSISTENT_PROFILE")
            captured["profile_dir"] = os.environ.get("DXM_WORKFLOW_PROFILE_DIR")
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "page_title": "店小秘--速卖通产品",
            }

    data_dir = tmp_path / "data"
    monkeypatch.delenv("DXM_WORKFLOW_PERSISTENT_PROFILE", raising=False)
    monkeypatch.delenv("DXM_WORKFLOW_PROFILE_DIR", raising=False)
    monkeypatch.setenv("DXM_DATA_DIR", str(data_dir))

    runtime = BrowserAgentRuntime(Adapter())
    command = _runtime_command(runtime,
        task_id=43,
        job_id=43,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={"store_name": "Dang Kang"},
        step_label="打开商品箱",
    )

    result = runtime.run(command, timeout_seconds=1)

    assert result["ok"] is True
    assert captured["persistent"] == "1"
    assert captured["profile_dir"] == str(data_dir / "browser_profiles" / "dxm_workflow")
    assert runtime.status()["profile_dir"] == captured["profile_dir"]
    runtime.shutdown()


def test_browser_agent_runtime_shutdown_closes_browser_on_agent_thread():
    class Adapter:
        def __init__(self):
            self.action_thread = None
            self.close_thread = None

        def set_workflow_event_listener(self, _listener):
            return None

        def open_draft_box(self):
            self.action_thread = threading.get_ident()
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
                "page_title": "店小秘--速卖通产品",
            }

        def close_browser_session(self):
            self.close_thread = threading.get_ident()

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    command = _runtime_command(runtime,
        task_id=44,
        job_id=44,
        state="OPEN_DRAFT_LIST",
        action="open_draft_box",
        params={"store_name": "Dang Kang"},
        step_label="打开商品箱",
    )

    runtime.run(command, timeout_seconds=1)
    runtime.shutdown()

    assert adapter.close_thread == adapter.action_thread


def test_browser_agent_runtime_resume_reverifies_same_session_and_page_on_agent_executor():
    class Adapter:
        def __init__(self):
            self.session_id = "session-resume-1"
            self.action_thread = None
            self.reverify_thread = None
            self.reverify_calls = 0

        def browser_session_id(self):
            return self.session_id

        def open_draft_box(self):
            self.action_thread = threading.get_ident()
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
            }

        def check_login_state(self):
            self.reverify_calls += 1
            self.reverify_thread = threading.get_ident()
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.run(
        BrowserAgentCommand(
            command_id="cmd-resume-1",
            idempotency_key="idem-resume-1",
            deadline=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(),
            expected_page="draft_box",
            runtime_id=runtime.runtime_id,
            task_id=44,
            job_id=45,
            state="OPEN_DRAFT_LIST",
            action="open_draft_box",
            params={},
        )
    )
    takeover = runtime.request_manual_takeover()
    assert takeover["manualTakeover"] is True
    assert takeover["status"] == "manual_takeover"

    resumed = runtime.resume(timeout_seconds=1)

    assert resumed["manualTakeover"] is False
    assert resumed["status"] == "idle"
    assert resumed["currentStep"] == "等待继续执行"
    assert adapter.reverify_calls == 1
    assert adapter.reverify_thread == adapter.action_thread
    assert any(event["action"] == "resume" for event in resumed["events"])
    runtime.shutdown()


def test_browser_agent_runtime_resume_probe_cannot_override_new_takeover_owner():
    probe_started = threading.Event()
    release_probe = threading.Event()

    class Adapter:
        def __init__(self):
            self.session_id = "session-resume-race-1"

        def browser_session_id(self):
            return self.session_id

        def open_draft_box(self):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
            }

        def check_login_state(self):
            probe_started.set()
            assert release_probe.wait(timeout=2)
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.run(
        _runtime_command(
            runtime,
            task_id=48,
            job_id=49,
            state="OPEN_DRAFT_LIST",
            action="open_draft_box",
            params={},
        )
    )
    runtime.request_manual_takeover()
    resume_result = {}
    resume_thread = threading.Thread(
        target=lambda: resume_result.update(runtime.resume(timeout_seconds=1))
    )
    resume_thread.start()
    assert probe_started.wait(timeout=1)

    superseding_takeover = runtime.request_manual_takeover(timeout_seconds=0.1)

    assert superseding_takeover["ok"] is True
    assert superseding_takeover["status"] == "manual_takeover"
    release_probe.set()
    resume_thread.join(timeout=2)
    assert resume_thread.is_alive() is False
    assert resume_result["ok"] is False
    assert resume_result["reasonCode"] == "BROWSER_AGENT_LIFECYCLE_OWNER_CHANGED"
    assert resume_result["status"] == "manual_takeover"
    assert resume_result["manualTakeover"] is True
    assert runtime.status()["status"] == "manual_takeover"
    runtime.shutdown()


def test_browser_agent_runtime_resume_without_takeover_snapshot_stays_fail_closed():
    runtime = BrowserAgentRuntime()
    runtime.request_manual_takeover()

    resumed = runtime.resume(timeout_seconds=0.1)

    assert resumed["ok"] is False
    assert resumed["reasonCode"] == "BROWSER_AGENT_TAKEOVER_SNAPSHOT_INVALID"
    assert resumed["manualTakeover"] is True
    assert resumed["status"] == "manual_takeover"
    assert resumed["healthy"] is False
    runtime.shutdown()


def test_browser_agent_runtime_resume_keeps_manual_takeover_when_session_changes():
    class Adapter:
        def __init__(self):
            self.session_id = "session-before-takeover"

        def browser_session_id(self):
            return self.session_id

        def open_draft_box(self):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
            }

        def check_login_state(self):
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
            }

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runtime.run(
        _runtime_command(
            runtime,
            task_id=46,
            job_id=47,
            state="OPEN_DRAFT_LIST",
            action="open_draft_box",
            params={},
        )
    )
    runtime.request_manual_takeover()
    adapter.session_id = "session-after-takeover"

    resumed = runtime.resume(timeout_seconds=1)

    assert resumed["ok"] is False
    assert resumed["reasonCode"] == "BROWSER_AGENT_RESUME_SESSION_MISMATCH"
    assert resumed["status"] == "manual_takeover"
    assert resumed["manualTakeover"] is True
    assert resumed["healthy"] is False
    runtime.shutdown()


def test_browser_agent_runtime_blocks_commands_during_manual_takeover():
    class Adapter:
        def claim_from_data_acquisition(self, *_args, **_kwargs):
            raise AssertionError("agent command must not run during manual takeover")

    runtime = BrowserAgentRuntime(Adapter())
    runtime.request_manual_takeover()
    command = _runtime_command(runtime,
        task_id=42,
        job_id=42,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS"},
        step_label="认领到商品箱",
    )

    with pytest.raises(RuntimeError, match="人工接管"):
        runtime.run(command, timeout_seconds=1)

    status = runtime.status()
    assert status["manualTakeover"] is True
    assert status["status"] == "manual_takeover"
    runtime.shutdown()


def test_browser_agent_runtime_session_id_only_mirrors_real_adapter_context_generation():
    class Adapter:
        def __init__(self):
            self.session_id = None

        def browser_session_id(self):
            return self.session_id

        def close_browser_session(self):
            self.session_id = None

    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)

    assert runtime.status()["sessionId"] is None
    adapter.session_id = "context-generation-1"
    assert runtime.status()["sessionId"] == "context-generation-1"

    reset_result = runtime.reset(adapter)

    assert reset_result["previousStatus"]["sessionId"] == "context-generation-1"
    assert reset_result["browserAgent"]["sessionId"] is None
    assert runtime.status()["sessionId"] is None
    runtime.shutdown()


def test_browser_agent_runtime_injects_command_bound_mutation_authorizer_after_reset():
    class Adapter:
        def __init__(self):
            self.authorizer = None
            self.command_context = None

        def set_mutation_authorizer(self, authorizer, command_context=None):
            self.authorizer = authorizer
            self.command_context = dict(command_context or {})

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *_args, **_kwargs):
            result = self.authorizer(
                {**self.command_context, "mutation_action": "claim_confirm_click"},
                lambda: "clicked",
            )
            assert result["ok"] is True
            assert result["executed"] is True
            return {"ok": True, "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition"}

        def close_browser_session(self):
            return None

    seen = []
    first_adapter = Adapter()
    runtime = BrowserAgentRuntime(first_adapter)
    runtime.set_mutation_authorizer(
        lambda command, context: seen.append((command.to_payload(), dict(context))) or {"ok": True}
    )
    command = _runtime_command(runtime,
        task_id=77,
        job_id=88,
        state="CLAIM_TO_DRAFT_BOX",
        action="claim_from_data_acquisition",
        params={"claim_mark": "AI-OPS", "store_name": "Dang Kang"},
    )

    runtime.run(command, timeout_seconds=2)
    second_adapter = Adapter()
    runtime.reset(second_adapter)
    runtime.run(
        _runtime_command(
            runtime,
            task_id=77,
            job_id=88,
            state="CLAIM_TO_DRAFT_BOX",
            action="claim_from_data_acquisition",
            params={"claim_mark": "AI-OPS", "store_name": "Dang Kang"},
        ),
        timeout_seconds=2,
    )

    assert len(seen) == 2
    assert all(item[1]["task_id"] == 77 for item in seen)
    assert all(item[1]["job_id"] == 88 for item in seen)
    assert all(item[1]["state"] == "CLAIM_TO_DRAFT_BOX" for item in seen)
    assert all(item[1]["mode"] == "claim_only" for item in seen)
    assert all(item[1]["mutation_action"] == "claim_confirm_click" for item in seen)
    assert seen[0][1]["command_id"] != seen[1][1]["command_id"]
    runtime.shutdown()
