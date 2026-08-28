from __future__ import annotations

"""Task2 trust-boundary phases for frozen readback and SAVE-only evidence.

The real BrowserAgentRuntime and SQLite MutationDispatchLedger own reserve/JIT/
begin. A local Playwright DOM is the external page seam; DxmLoginFlow's real
binding/value and exact-SAVE locators produce each preflight fact.

``save_request_count`` and ``publish_request_count`` are N/A before the external
operation: they can only be observed after the network window opens. Their
pre-operation safety invariant is therefore operation_count=0 and no fabricated
network observation. Restart validation covers their single-field tamper cases.
"""

from copy import deepcopy
import json

import pytest
from playwright.sync_api import sync_playwright

from src import db
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.mutation_dispatch_ledger import MutationDispatchLedger
from tests.test_login_flow import DummyLiveClient
from tests.test_e3_post_save_trust_matrix import (
    _canonical_json,
    _canonical_sha256,
    _mutate_binding,
    _mutate_exact_save_count,
    _mutate_observed_value,
    _mutate_publish_request_count,
    _mutate_save_request_count,
    _prepare_dispatched_save,
    _prepare_runtime_save,
)


_PRE_JIT_REASON_CODE = "MUTATION_TARGET_DRIFT"


class _LiveDomPreflightAdapter:
    requires_persistent_browser_agent = True

    def __init__(self, *, state_file, initial_case: str, after_jit_case: str | None = None):
        self.state_file = state_file
        self.initial_case = initial_case
        self.after_jit_case = after_jit_case
        self.authorizer = None
        self.command_context: dict = {}
        self.target_hash: str | None = None
        self.page = None
        self.preflight_calls = 0
        self.operation_calls = 0
        self.last_decision: dict | None = None
        self.last_readback: dict | None = None
        self.last_button_state: dict | None = None
        self.post_save_network_observation = None

    def browser_session_id(self) -> str:
        return "e3-test-browser-session"

    def refresh_account_context_hash(self) -> str:
        return "A" * 64

    def current_mutation_identity(self) -> dict:
        return {
            "browser_session_id": self.browser_session_id(),
            "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=70001",
            "page_kind": "editor",
            "target_hash": self.target_hash,
        }

    def set_mutation_authorizer(self, authorizer, command_context=None) -> None:
        self.authorizer = authorizer
        self.command_context = dict(command_context or {})

    def clear_mutation_authorizer(self) -> None:
        self.authorizer = None

    @staticmethod
    def _html(case: str) -> str:
        input_value = "99" if case == "value" else "10"
        input_count = 2 if case == "binding" else 1
        save_count = {"exact-zero": 0, "exact-two": 2}.get(case, 1)
        controls = "".join(
            (
                '<input id="weight-{index}" data-field="weight" '
                'data-ui-binding="dxm_editor:weight" value="{value}">'
            ).format(index=index, value=input_value)
            for index in range(input_count)
        )
        buttons = "".join(
            '<button class="exact-save" type="button">保存</button>'
            for _ in range(save_count)
        )
        return (
            "<style>input{display:block;width:160px;height:32px}"
            "button{display:block;width:96px;height:36px;margin-top:8px}</style>"
            f"{controls}{buttons}"
        )

    def _flow(self) -> DxmLoginFlow:
        flow = DxmLoginFlow(
            DummyLiveClient(logged_in=True),
            state_file=self.state_file,
        )
        flow._evaluate_visible_page_function_via_devtools = (
            lambda page, script, arg=None, **_kwargs: (
                page.evaluate(script, arg) if arg is not None else page.evaluate(script)
            )
        )
        return flow

    def _preflight(self, execution_payload: dict) -> dict:
        self.preflight_calls += 1
        flow = self._flow()
        self.last_readback = DxmLoginFlow._capture_frozen_execution_readback(
            self.page,
            execution_payload,
            phase="before_ledger_begin_dispatch",
        )
        self.last_button_state = flow._visible_exact_save_button_state(self.page)
        ok = bool(
            self.last_readback.get("ok") is True
            and self.last_button_state.get("ok") is True
            and self.last_button_state.get("exact_save_count") == 1
        )
        return {
            "ok": ok,
            "reason_code": _PRE_JIT_REASON_CODE,
            "reason": (
                self.last_readback.get("reason")
                if self.last_readback.get("ok") is not True
                else self.last_button_state.get("reason")
                if self.last_button_state.get("ok") is not True
                else None
            ),
        }

    def mutate_after_jit(self) -> None:
        case = self.after_jit_case
        if case == "binding":
            self.page.evaluate(
                """() => document.body.insertAdjacentHTML(
                  'afterbegin',
                  '<input data-field="weight" data-ui-binding="dxm_editor:weight" value="10">'
                )"""
            )
        elif case == "value":
            self.page.locator('[data-ui-binding="dxm_editor:weight"]').first.evaluate(
                "el => { el.value = '99'; el.dispatchEvent(new Event('change', {bubbles:true})); }"
            )
        elif case == "exact-zero":
            self.page.locator("button.exact-save").evaluate_all(
                "buttons => buttons.forEach(button => button.remove())"
            )
        elif case == "exact-two":
            self.page.evaluate(
                """() => document.body.insertAdjacentHTML(
                  'beforeend', '<button class="exact-save" type="button">保存</button>'
                )"""
            )
        elif case is not None:
            raise AssertionError(f"unsupported DOM drift case: {case}")

    def save_only(self, *, defaults, **_kwargs):
        execution_payload = defaults["_frozen_execution_payload"]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                self.page = browser.new_page()
                self.page.set_content(self._html(self.initial_case))
                self.last_decision = self.authorizer(
                    {
                        **self.command_context,
                        "mutation_action": "save_only_click",
                        "_pre_dispatch_guard": lambda: self._preflight(
                            execution_payload
                        ),
                    },
                    self._operation,
                )
            finally:
                browser.close()
                self.page = None
        if self.last_decision.get("ok") is not True:
            raise RuntimeError(
                self.last_decision.get("reason_code") or "MUTATION_TARGET_DRIFT"
            )
        raise RuntimeError("UNEXPECTED_SAVE_OPERATION_REACHED")

    def _operation(self) -> dict:
        self.operation_calls += 1
        return {"dispatched": True, "external_write": False}


@pytest.mark.parametrize(
    ("dom_case", "producer_reason"),
    [
        pytest.param("binding", "FROZEN_EXECUTION_BINDING_UNRESOLVED", id="stable-binding"),
        pytest.param("value", "frozen_execution_value_mismatch", id="frozen-value"),
        pytest.param("exact-zero", "精确“保存”按钮数量不是 1：0", id="exact-save-zero"),
        pytest.param("exact-two", "精确“保存”按钮数量不是 1：2", id="exact-save-two"),
    ],
)
def test_reserve_to_jit_live_dom_preflight_rejects_with_zero_operation(
    tmp_path,
    monkeypatch,
    dom_case,
    producer_reason,
):
    adapter = _LiveDomPreflightAdapter(
        state_file=tmp_path / "dom-runtime.json",
        initial_case=dom_case,
    )
    command, ledger, runtime = _prepare_runtime_save(tmp_path, monkeypatch, adapter)
    jit_calls: list[str] = []
    runtime.set_mutation_authorizer(
        lambda _command, _context: jit_calls.append("jit")
        or {"ok": True, "reason_code": "OK"}
    )
    try:
        with pytest.raises(RuntimeError, match=_PRE_JIT_REASON_CODE):
            runtime.run(command, timeout_seconds=10)

        entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
        assert adapter.preflight_calls == 1
        assert jit_calls == []
        assert adapter.operation_calls == 0
        assert producer_reason in str(adapter.last_decision.get("detail") or "")
        assert adapter.last_decision["reason_code"] == _PRE_JIT_REASON_CODE
        assert adapter.post_save_network_observation is None
        assert entry["status"] == "RESERVED"
        assert entry["dispatch_started_at"] is None
        assert entry["save_authority_json"] is None
        assert entry["outcome"] is None
    finally:
        runtime.shutdown()


@pytest.mark.parametrize(
    "dom_case",
    [
        pytest.param("binding", id="stable-binding"),
        pytest.param("value", id="frozen-value"),
        pytest.param("exact-zero", id="exact-save-zero"),
        pytest.param("exact-two", id="exact-save-two"),
    ],
)
def test_jit_to_begin_rechecks_live_dom_preflight_with_zero_operation(
    tmp_path,
    monkeypatch,
    dom_case,
):
    adapter = _LiveDomPreflightAdapter(
        state_file=tmp_path / "dom-runtime.json",
        initial_case="normal",
        after_jit_case=dom_case,
    )
    command, ledger, runtime = _prepare_runtime_save(tmp_path, monkeypatch, adapter)
    jit_calls: list[str] = []

    def jit_authorizer(_command, _context):
        jit_calls.append("jit")
        adapter.mutate_after_jit()
        return {"ok": True, "reason_code": "OK"}

    runtime.set_mutation_authorizer(jit_authorizer)
    try:
        with pytest.raises(RuntimeError, match=_PRE_JIT_REASON_CODE):
            runtime.run(command, timeout_seconds=10)

        entry = ledger.get_entry(command.mutation_scope_id, "save_only_click")
        assert jit_calls == ["jit"]
        assert adapter.preflight_calls == 2
        assert adapter.operation_calls == 0
        assert adapter.last_decision["reason_code"] == _PRE_JIT_REASON_CODE
        # SAVE/publish request counts do not exist before operation; this is the
        # explicit N/A boundary, not a synthetic zero-success claim.
        assert adapter.post_save_network_observation is None
        assert entry["status"] == "RESERVED"
        assert entry["dispatch_started_at"] is None
        assert entry["save_authority_json"] is None
        assert entry["outcome"] is None
    finally:
        runtime.shutdown()


@pytest.mark.parametrize(
    ("case_id", "mutator"),
    [
        pytest.param("stable-binding", _mutate_binding, id="stable-binding"),
        pytest.param("frozen-value", _mutate_observed_value, id="frozen-value"),
        pytest.param(
            "exact-save-zero",
            lambda result: _mutate_exact_save_count(result, 0),
            id="exact-save-zero",
        ),
        pytest.param(
            "exact-save-two",
            lambda result: _mutate_exact_save_count(result, 2),
            id="exact-save-two",
        ),
        pytest.param(
            "save-request-zero",
            lambda result: _mutate_save_request_count(result, 0),
            id="save-request-zero",
        ),
        pytest.param(
            "save-request-two",
            lambda result: _mutate_save_request_count(result, 2),
            id="save-request-two",
        ),
        pytest.param(
            "publish-request",
            _mutate_publish_request_count,
            id="publish-request",
        ),
    ],
)
def test_restart_rejects_rehashed_single_field_save_evidence_tamper(
    tmp_path,
    monkeypatch,
    case_id,
    mutator,
):
    harness = _prepare_dispatched_save(tmp_path, monkeypatch)
    restart_operations: list[str] = []
    try:
        assert harness.ledger.record_success(
            harness.command,
            harness.action_result,
        ).ok is True
        entry = harness.ledger.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )
        tampered = json.loads(entry["save_action_result_json"])
        mutator(tampered)
        tampered_json = _canonical_json(tampered)
        tampered_sha256 = _canonical_sha256(tampered)
        with db.connection() as conn:
            conn.execute(
                """
                UPDATE mutation_dispatch_ledger
                   SET save_action_result_json=?, save_action_result_sha256=?
                 WHERE mutation_scope_id=? AND mutation_action='save_only_click'
                """,
                (
                    tampered_json,
                    tampered_sha256,
                    harness.command.mutation_scope_id,
                ),
            )

        restarted = MutationDispatchLedger()
        recovered = restarted.get_entry(
            harness.command.mutation_scope_id,
            "save_only_click",
        )

        assert restart_operations == [], case_id
        assert recovered["status"] == "UNKNOWN"
        assert recovered["outcome"]["reason_code"] == (
            "SAVE_ACTION_RESULT_INVALID_AFTER_RESTART"
        )
        retry = restarted.begin_dispatch(harness.command, "save_only_click")
        assert retry.ok is False
        assert retry.reason_code == "MUTATION_OUTCOME_UNKNOWN"
    finally:
        harness.runtime.shutdown()
