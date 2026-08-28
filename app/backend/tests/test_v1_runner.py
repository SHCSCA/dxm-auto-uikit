import asyncio
from copy import deepcopy
import hashlib
import json
import sqlite3
import struct
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from src import db, repository as repository_module
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution import v1_runner as v1_runner_module
from src.execution.v1_runner import V1ExecutionError, V1TaskRunner
from src.repository import Repository
from src.state_machine.contracts import StateName
from tests.test_action_result_contract import _valid_save_result, _valid_unpublished_result


def _test_runner(*args, **kwargs):
    kwargs.setdefault("authorization_verifier", lambda *_args: {"ok": True, "reason_code": "OK"})
    return V1TaskRunner(*args, **kwargs)


def _evidence_ref(name: str) -> dict:
    path = (Path(v1_runner_module.SCREENSHOT_DIR) / name).resolve()
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)

    content = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(content)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest().upper(),
        "size": len(content),
    }


_TEST_PAGE_URLS = {
    "authenticated_dxm": "https://www.dianxiaomi.com/web/index.htm",
    "draft_box": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
    "editor": "https://www.dianxiaomi.com/web/smt/edit",
    "semi_managed": "https://www.dianxiaomi.com/web/smt/editFromSmt",
}

_TEST_ACTION_CONTRACTS = {
    "check_login_state": ("PRECHECK_SESSION", "authenticated_dxm", ("session_authenticated", "business_page_ready", "loading_absent")),
    "open_draft_box": ("OPEN_DRAFT_LIST", "draft_box", ("expected_page", "business_marker_present", "loading_absent", "blocking_modal_absent")),
    "open_editor": ("OPEN_EDIT_PAGE", "editor", ("expected_editor_page", "editor_ready", "product_identity_match", "store_match", "source_identity_match")),
    "verify_edit_ownership": ("VERIFY_EDIT_OWNERSHIP", "editor", ("editor_identity_match", "product_identity_match", "store_match", "source_identity_match")),
    "fill_editor_required_defaults": ("FILL_BASE_INFO", "editor", ("title_readback_nonempty", "title_readback_exact", "category_selected_exact", "required_templates_resolved", "required_fields_complete")),
    "fill_editor_variants": ("FILL_VARIANTS", "editor", ("variant_rows_present", "sku_readback_exact", "price_readback_exact", "stock_readback_exact", "all_required_cells_complete")),
    "fill_media_assets": ("FILL_MEDIA", "editor", ("main_images_present", "required_assets_match", "invalid_images_absent", "marketing_assets_complete")),
    "fill_compliance_defaults": ("FILL_COMPLIANCE", "editor", ("required_compliance_complete", "eu_responsible_readback_exact", "manufacturer_readback_exact", "customs_readback_exact", "required_templates_applied")),
    "enable_semi_managed": ("ENABLE_SEMI_MANAGED", "editor", ("semi_managed_visible", "semi_managed_enabled", "toggle_readback_exact", "publish_not_attempted")),
    "open_semi_managed_page": ("OPEN_SEMI_MANAGED_PAGE", "semi_managed", ("expected_semi_managed_page", "business_marker_present", "loading_absent", "source_editor_identity_preserved")),
    "fill_semi_managed_defaults": ("FILL_SEMI_GOODS", "semi_managed", ("weight_readback_exact", "dimensions_readback_exact", "logistics_attribute_readback_exact", "freight_template_readback_exact", "service_template_readback_exact", "required_goods_fields_complete")),
    "save_only": ("SAVE_ONLY", "semi_managed", ("mutation_authorized", "exact_save_target", "save_click_dispatched", "network_save_success", "page_save_success", "published_false", "publish_action_not_clicked")),
    "verify_not_published": ("VERIFY_NOT_PUBLISHED", "semi_managed", ("independent_probe", "product_identity_match", "unpublished_verified", "publish_status_absent_or_false", "save_evidence_not_reused")),
}

_TEST_SEMI_VARIANT_CONTRACT = (
    "FILL_SEMI_VARIANTS",
    "semi_managed",
    (
        "variant_rows_present",
        "product_price_readback_exact",
        "supply_price_readback_exact",
        "jit_stock_readback_exact",
        "goods_code_readback_exact",
        "required_variant_fields_complete",
    ),
)


def _mapping_sha256(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest().upper()


def _merge_mapping(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_mapping(merged[key], value)
        else:
            merged[key] = value
    return merged


def _strict_test_save_result(*, target_identity: dict, store_name: str) -> dict:
    target_digest = _mapping_sha256(target_identity)
    integrity = {
        "ok": True,
        "kind": "structured_nonempty_form_state",
        "field_count": 12,
        "nonempty_field_count": 12,
        "sha256": "C" * 64,
    }
    authorization = {
        "ok": True,
        "executed": True,
        "mutation_action": "save_only_click",
        "mutation_status": "DISPATCHED",
        "mutation_id": "mutation-test-1",
    }
    pre_dispatch = {
        "ok": True,
        "required_readback_complete": True,
        "write_attempted": False,
        "phase": "before_ledger_begin_dispatch",
        "exact_save_target": {"ok": True, "text": "保存", "exact_save_count": 1},
        "identity": {
            "ok": True,
            "product_identity_match": True,
            "store_identity_match": True,
            "source_identity_match": True,
            "target_identity": target_identity,
            "target_identity_sha256": target_digest,
            "expected_store_name": store_name,
        },
        "baseline_field_integrity": integrity,
        "current_field_integrity": dict(integrity),
    }
    network = {
        "ok": True,
        "receipt_complete": True,
        "receipt_count": 1,
        "method": "POST",
        "url": "https://www.dianxiaomi.com/api/popChoiceProduct/add.json",
        "status": 200,
        "code": 0,
        "msg": "您的产品编辑保存成功！",
    }
    network_audit = {
        "scope": "same_origin_write_window",
        "complete": True,
        "window_closed": True,
        "registered_listener_count": 2,
        "removed_listener_count": 2,
        "mutation_request_count": 1,
        "save_request_count": 1,
        "other_mutation_request_count": 0,
        "read_only_schema_request_count": 0,
        "publish_request_count": 0,
    }
    publish_signal = {
        "detected": False,
        "kind": "network_route_classification",
        "request_count": 0,
    }
    page_save_result = {
        "ok": True,
        "success_text": "保存成功",
        "status_transition": {
            "kind": "new_or_changed_structured_save_status",
            "entry": {"text": "保存成功", "kind": "toast"},
        },
    }
    return {
        "ok": True,
        "code": 0,
        "msg": "真实保存成功",
        "published": False,
        "exact_save_target": True,
        "save_click_dispatched": True,
        "clicked": True,
        "publish_action_clicked": False,
        "text": "保存",
        "exact_save_count": 1,
        "click_method": "native_exact_save",
        "network_save_success": True,
        "page_save_success": True,
        "mutation_authorization": authorization,
        "pre_dispatch_readback": pre_dispatch,
        "network_save_result": network,
        "network_audit": network_audit,
        "publish_signal": publish_signal,
        "page_save_result": page_save_result,
        "save_decision": {
            "ok": True,
            "rule": "page_success_and_network_success",
            "page_ok": True,
            "network_ok": True,
            "network_receipt_ok": True,
            "network_audit_ok": True,
        },
    }


def _strict_test_unpublished_proof(*, target_identity: dict) -> dict:
    return {
        "ok": True,
        "published": False,
        "proof_kind": "structured_unpublished_status",
        "status_text": "待发布",
        "verified_on_current_page": True,
        "status_scope_unique": True,
        "bound_candidate_count": 1,
        "structured_candidate_count": 1,
        "target_bound": True,
        "product_matched": True,
        "store_matched": True,
        "source_identity_match": True,
        "identity_binding_kind": "frozen_target_structured_page_readback",
        "publish_risk_term": None,
        "target_identity_sha256": _mapping_sha256(target_identity),
        "page_url": _TEST_PAGE_URLS["semi_managed"],
        "identity_readback": {
            "product_identity_match": True,
            "store_identity_match": True,
            "source_identity_match": True,
        },
    }


def _canonical_test_action_result(
    action: str,
    legacy_result: dict,
    *,
    state_override: str | None = None,
    runtime_id: str = "test-runtime",
    browser_session_id: str = "test-browser-session",
) -> dict:
    state, page_kind, condition_names = _TEST_ACTION_CONTRACTS[action]
    if state_override == "FILL_SEMI_VARIANTS":
        state, page_kind, condition_names = _TEST_SEMI_VARIANT_CONTRACT
    ok = legacy_result.get("ok") is True
    evidence = legacy_result.get("evidence") if isinstance(legacy_result.get("evidence"), dict) else {}
    save_result = legacy_result.get("save_result")
    if action == "save_only" and (not isinstance(save_result, dict) or save_result.get("ok") is not True):
        ok = False

    product_query = legacy_result.get("product_query") or "test-product"
    store_name = legacy_result.get("store_name") or "test-store"
    before_values = {
        "requested_action": action,
        "product_query": product_query,
        "store_name": store_name,
    }
    target_identity = legacy_result.get("target_identity")
    if not isinstance(target_identity, dict):
        target_identity = {
            "product_query": "test-product",
            "store_name": "test-store",
        }
    if action in {"save_only", "verify_not_published"}:
        before_values["target_identity"] = target_identity

    after_values = {
        "observed_action": action,
        "page_url": _TEST_PAGE_URLS[page_kind],
    }
    if action == "save_only":
        after_values.update({"published": False, "save_result": dict(save_result or {})})
    if action == "verify_not_published":
        proof = legacy_result.get("unpublished_proof")
        if not isinstance(proof, dict):
            proof = _strict_test_unpublished_proof(target_identity=target_identity)
        observed_target = {
            "product_matched": True,
            "store_matched": True,
            "source_identity_match": True,
            "target_bound": True,
            "target_identity_sha256": proof["target_identity_sha256"],
        }
        after_values.update(
            {
                "published": False,
                "fresh_probe": proof,
                "target_identity": observed_target,
                "identity_readback": proof["identity_readback"],
            }
        )

    observations = {
        **evidence,
        "page_title": legacy_result.get("page_title"),
        "page_url": _TEST_PAGE_URLS[page_kind],
        "product_query": product_query,
        "store_name": store_name,
    }
    for key in (
        "save_result",
        "fill_result",
        "unpublished_proof",
        "dxm_reference_template_results",
    ):
        if legacy_result.get(key) is not None:
            observations[key] = legacy_result[key]
    if action == "save_only" and isinstance(save_result, dict) and save_result.get("ok") is True:
        observations.update(
            {
                "exact_save_target": {
                    "text": "保存",
                    "exact_save_count": 1,
                    "click_method": save_result.get("click_method"),
                },
                "save_click_dispatched": True,
            }
        )
        for key in (
            "mutation_authorization",
            "pre_dispatch_readback",
            "network_save_result",
            "network_audit",
            "publish_signal",
            "page_save_result",
        ):
            observations[key] = save_result.get(key)
            after_values[key] = save_result.get(key)
        after_values["exact_save_target"] = True
        after_values["save_click_dispatched"] = True
    if action == "verify_not_published":
        observations.update(
            {
                "fresh_probe": proof,
                "target_identity": observed_target,
                "identity_readback": proof["identity_readback"],
            }
        )

    refs = []
    basic_ref = legacy_result.get("evidence_ref") or evidence.get("evidence_ref")
    if isinstance(basic_ref, dict):
        kind = {
            "SAVE_ONLY": "save_screenshot",
            "VERIFY_NOT_PUBLISHED": "unpublished_screenshot",
        }.get(state, "screenshot")
        captured_at = (
            "2026-05-22T00:00:02+00:00"
            if state == "VERIFY_NOT_PUBLISHED"
            else "2026-05-22T00:00:01+00:00"
        )
        refs.append({**basic_ref, "kind": kind, "captured_at": captured_at})

    return {
        "schema_version": "dxm.action-result.v1",
        "ok": ok,
        "action": action,
        "attempted_state": state,
        "before_values": before_values,
        "after_values": after_values,
        "postconditions": {name: ok for name in condition_names},
        "evidence": {"observations": observations, "refs": refs},
        "page_identity": {
            "kind": page_kind,
            "url": _TEST_PAGE_URLS[page_kind],
            "runtime_id": runtime_id,
            "browser_session_id": browser_session_id,
        },
        "failure_code": None if ok else "TEST_ACTION_FAILED",
        "recoverability": (
            {
                "kind": "none",
                "retryable": False,
                "requires_page_reverify": False,
                "reason": None,
            }
            if ok
            else {
                "kind": "manual_takeover",
                "retryable": False,
                "requires_page_reverify": True,
                "reason": "test action failed",
            }
        ),
    }


def _test_action_observations(result: dict) -> dict:
    return result["evidence"]["observations"]


def _test_action_first_ref(result: dict) -> dict:
    return result["evidence"]["refs"][0]


def _bind_single_save_action_result(
    result: dict,
    *,
    target_identity: dict,
    product_query: str,
    store_name: str,
    evidence_name: str,
    execution_defaults: dict | None = None,
) -> dict:
    bound = deepcopy(result)
    bound["before_values"]["product_query"] = product_query
    bound["before_values"]["store_name"] = store_name
    frozen_payload = (
        execution_defaults.get("_frozen_execution_payload")
        if isinstance(execution_defaults, dict)
        else None
    )
    path_a = isinstance(frozen_payload, dict) and isinstance(
        frozen_payload.get("fields"),
        list,
    )
    if path_a:
        bound["page_identity"]["kind"] = "editor"
        bound["page_identity"]["url"] = "https://www.dianxiaomi.com/web/smt/edit"
    digest = hashlib.sha256(
        json.dumps(
            target_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    bound["before_values"]["target_identity"] = deepcopy(target_identity)
    if bound["attempted_state"] == "SAVE_ONLY":
        bound["before_values"]["store_name"] = store_name
        category_schema_readback = None
        frozen_execution_readback = None
        if path_a:
            category_schema_readback = {
                "schema": "dxm.editor.category_schema_readback.v1",
                "ok": True,
                "phase": "before_ledger_begin_dispatch",
                "expected_category_id": frozen_payload["category_id"],
                "observed_category_id": frozen_payload["category_id"],
                "expected_category_schema_hash": frozen_payload[
                    "category_schema_hash"
                ],
                "observed_category_schema_hash": frozen_payload[
                    "category_schema_hash"
                ],
                "category_source": "test:live_schema_readback",
                "reason": None,
            }
            readback_fields = []
            for field in frozen_payload["fields"]:
                resolved_value = field["resolved_value"]
                value_hash = hashlib.sha256(
                    json.dumps(
                        resolved_value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest().upper()
                readback_fields.append(
                    {
                        "field_key": field["field_key"],
                        "ui_binding": field["ui_binding"],
                        "expected_value_hash": value_hash,
                        "observed_value_hash": value_hash,
                        "match_count": (
                            len(resolved_value)
                            if isinstance(resolved_value, list)
                            else 1
                        ),
                        "aggregate_kind": (
                            "sku_rows"
                            if field["field_key"] == "aeopAeProductSKUs"
                            else (
                                "choice_group"
                                if isinstance(resolved_value, list)
                                else "single"
                            )
                        ),
                        "exact": True,
                    }
                )
            frozen_execution_readback = {
                "schema": "dxm.frozen_execution.readback.v1",
                "ok": True,
                "phase": "before_ledger_begin_dispatch",
                "execution_payload_hash": frozen_payload["payload_hash"],
                "field_count": len(readback_fields),
                "fields": readback_fields,
                "reason": None,
            }
        for container in (
            bound["after_values"],
            bound["evidence"]["observations"],
            bound["evidence"]["observations"]["save_result"],
        ):
            identity = container["pre_dispatch_readback"]["identity"]
            identity["target_identity"] = deepcopy(target_identity)
            identity["target_identity_sha256"] = digest
            identity["expected_store_name"] = store_name
            if category_schema_readback is not None:
                container["pre_dispatch_readback"][
                    "category_schema_readback"
                ] = deepcopy(category_schema_readback)
                container["pre_dispatch_readback"][
                    "frozen_execution_readback"
                ] = deepcopy(frozen_execution_readback)
        if category_schema_readback is not None:
            bound["evidence"]["observations"]["save_result"]["network_audit"][
                "read_only_schema_request_count"
            ] = 1
    else:
        for container in (
            bound["after_values"],
            bound["evidence"]["observations"],
        ):
            fresh_probe = container["fresh_probe"]
            fresh_probe["target_identity_sha256"] = digest
            if path_a:
                fresh_probe["page_url"] = "https://www.dianxiaomi.com/web/smt/edit"
            target = container["target_identity"]
            target["target_identity_sha256"] = digest
    evidence_ref = _evidence_ref(evidence_name)
    evidence_ref.update(
        {
            "kind": (
                "save_screenshot"
                if bound["attempted_state"] == "SAVE_ONLY"
                else "unpublished_screenshot"
            ),
            "captured_at": (
                "2026-07-15T08:00:00+08:00"
                if bound["attempted_state"] == "SAVE_ONLY"
                else "2026-07-15T08:00:01+08:00"
            ),
        }
    )
    bound["evidence"]["refs"] = [evidence_ref]
    return bound


class DummyManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, task_id, payload):
        self.events.append((task_id, payload))


class FakeWorkflowAdapter:
    def __init__(
        self,
        fail_action: str | None = None,
        save_result: dict | None = None,
        include_save_result: bool = True,
    ):
        self.calls = []
        self.fail_action = fail_action
        self.save_result = save_result or {"ok": True, "code": 0, "msg": "真实保存成功", "published": False}
        self.include_save_result = include_save_result
        self.live_hud_calls = []
        self._last_frozen_execution_defaults = None

    def check_login_state(self):
        return self._record("check_login_state")

    def open_draft_box(self):
        return self._record("open_draft_box")

    def open_editor(self, product_query=None, store_name=None, target_source_urls=None, target_identity=None):
        return self._record("open_editor", product_query, store_name, target_source_urls, target_identity)

    def verify_edit_ownership(self, product_query=None, store_name=None, target_source_urls=None, target_identity=None):
        return self._record("verify_edit_ownership", product_query, store_name, target_source_urls, target_identity)

    def fill_editor_required_defaults(self, defaults=None, product_query=None, store_name=None, target_identity=None):
        return self._record("fill_editor_required_defaults", defaults, product_query, store_name)

    def fill_editor_variants(self, defaults=None, product_query=None, store_name=None, target_identity=None):
        return self._record("fill_editor_variants", defaults, product_query, store_name)

    def fill_media_assets(self, defaults=None, product_query=None, store_name=None, target_identity=None):
        return self._record("fill_media_assets", defaults, product_query, store_name)

    def fill_compliance_defaults(self, defaults=None, product_query=None, store_name=None, target_identity=None):
        return self._record("fill_compliance_defaults", defaults, product_query, store_name)

    def enable_semi_managed(self, product_query=None, store_name=None, target_identity=None):
        return self._record("enable_semi_managed", product_query, store_name)

    def open_semi_managed_page(self, defaults=None, product_query=None, store_name=None, target_identity=None):
        return self._record("open_semi_managed_page", defaults, product_query, store_name)

    def fill_semi_managed_defaults(self, defaults=None, product_query=None, store_name=None, target_identity=None):
        return self._record("fill_semi_managed_defaults", defaults, product_query, store_name)

    def save_only(self, defaults=None, product_query=None, store_name=None, target_identity=None):
        return self._record("save_only", defaults, product_query, store_name, target_identity)

    def verify_not_published(self, product_query=None, store_name=None, target_identity=None):
        return self._record("verify_not_published", product_query, store_name, target_identity)

    def update_live_hud(self, hud):
        self.live_hud_calls.append(hud)
        return {
            "ok": True,
            "updated": True,
            "reason": "live_browser_hud_updated",
            "current_url": "https://www.dianxiaomi.com/web/smt/edit",
            "page_title": "店小秘--编辑速卖通产品",
            "hud": hud,
            "updated_at": "2026-05-22T00:00:02+00:00",
        }

    def _record(self, action, *args, target_identity=None):
        self.calls.append((action, *args))
        target_identity = args[-1] if args and isinstance(args[-1], dict) else None
        business_args = args[:-1] if target_identity is not None else args
        product_query = business_args[-2] if len(business_args) >= 2 else None
        store_name = business_args[-1] if business_args else None
        effective_save_result = self.save_result
        if (
            action == "save_only"
            and self.include_save_result
            and isinstance(self.save_result, dict)
            and self.save_result.get("ok") is True
        ):
            effective_save_result = _merge_mapping(
                _strict_test_save_result(
                    target_identity=target_identity or {"product_query": "test-product", "store_name": "test-store"},
                    store_name=str(store_name or "test-store"),
                ),
                self.save_result,
            )
        evidence = {"action": action}
        if action == "fill_editor_required_defaults" and args:
            defaults = args[0] if isinstance(args[0], dict) else {}
            resolved = defaults.get("dxm_reference_templates_resolved") or {}
            applied = {
                section: {"ok": True, "section": section, **config}
                for section, config in resolved.items()
            }
            evidence["dxm_reference_template_results"] = applied
        if action == "save_only" and self.include_save_result:
            evidence["save_result"] = effective_save_result
        if action in {"save_only", "verify_not_published"}:
            evidence["evidence_ref"] = _evidence_ref(
                f"workflow-{action}-{len(self.calls)}.png"
            )
        result = {
            "ok": action != self.fail_action,
            "action": action,
            "stage": f"{action}_stage",
            "page_title": "速卖通商品箱",
            "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "screenshot_url": f"/artifacts/{action}.png",
            "product_query": product_query,
            "store_name": store_name,
            "target_identity": target_identity,
            "evidence": evidence,
        }
        if action == "save_only" and self.include_save_result:
            result["save_result"] = effective_save_result
        if action == "verify_not_published":
            result["unpublished_proof"] = _strict_test_unpublished_proof(
                target_identity=target_identity or {"product_query": "test-product", "store_name": "test-store"}
            )
        if action in {"save_only", "verify_not_published"}:
            result["evidence_ref"] = evidence["evidence_ref"]
        if "dxm_reference_template_results" in evidence:
            result["dxm_reference_template_results"] = evidence["dxm_reference_template_results"]
        semi_call_count = sum(
            1 for recorded in self.calls if recorded and recorded[0] == "fill_semi_managed_defaults"
        )
        state_override = (
            "FILL_SEMI_VARIANTS"
            if action == "fill_semi_managed_defaults" and semi_call_count % 2 == 0
            else None
        )
        return _canonical_test_action_result(
            action,
            result,
            state_override=state_override,
        )


class ThreadRecordingWorkflowAdapter(FakeWorkflowAdapter):
    def __init__(self):
        super().__init__()
        self.thread_names = []
        self.hud_thread_names = []

    def _record(self, action, *args, target_identity=None):
        self.thread_names.append(threading.current_thread().name)
        return super()._record(
            action,
            *args,
            target_identity=target_identity,
        )

    def update_live_hud(self, hud):
        self.hud_thread_names.append(threading.current_thread().name)
        return super().update_live_hud(hud)


class FakeBrowserAgentRuntime:
    def __init__(self):
        self.commands = []

    def run(self, command, *, timeout_seconds=None):
        self.commands.append((command, timeout_seconds))
        if command.action == "update_live_hud":
            hud = command.params.get("hud") or {}
            return {
                "ok": True,
                "updated": True,
                "reason": "live_browser_hud_updated",
                "current_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
                "page_title": "店小秘商品箱",
                "hud": hud,
                "updated_at": "2026-05-22T00:00:03+00:00",
            }
        page_kind = _TEST_ACTION_CONTRACTS[command.action][1]
        result = {
            "ok": True,
            "action": command.action,
            "stage": f"{command.action}_stage",
            "page_title": "店小秘商品箱",
            "page_url": _TEST_PAGE_URLS[page_kind],
            "screenshot_url": f"/artifacts/{command.action}.png",
            "evidence": {"action": command.action},
            "product_query": command.params.get("product_query"),
            "store_name": command.params.get("store_name"),
            "target_identity": command.params.get("target_identity"),
        }
        if command.action == "save_only":
            target_identity = command.params.get("target_identity") or {
                "product_query": "test-product",
                "store_name": "test-store",
            }
            result["save_result"] = _strict_test_save_result(
                target_identity=target_identity,
                store_name=str(command.params.get("store_name") or "test-store"),
            )
            result["evidence"]["save_result"] = result["save_result"]
        if command.action == "verify_not_published":
            target_identity = command.params.get("target_identity") or {
                "product_query": "test-product",
                "store_name": "test-store",
            }
            result["unpublished_proof"] = _strict_test_unpublished_proof(
                target_identity=target_identity,
            )
        if command.action in {"save_only", "verify_not_published"}:
            evidence_ref = _evidence_ref(
                f"browser-task-{command.task_id}-job-{command.job_id}-{command.action}.png"
            )
            result["evidence_ref"] = evidence_ref
            result["evidence"]["evidence_ref"] = evidence_ref
        return _canonical_test_action_result(
            command.action,
            result,
            state_override=command.state,
            runtime_id=command.runtime_id,
            browser_session_id="fake-browser-agent-session",
        )


class FakeAgentConsole:
    def __init__(self, fail: bool = False):
        self.calls = []
        self.action_calls = []
        self.fail = fail
        self.start_calls = []

    def update_task_step(self, **payload):
        if self.fail:
            raise RuntimeError("console unavailable")
        self.calls.append(payload)
        return {
            "ok": True,
            "updated": True,
            "reason": "updated",
            "active": True,
            "session_id": "agent-test",
            "task_id": payload.get("task_id"),
            "job_id": payload.get("job_id"),
            "product_id": payload.get("product_id"),
            "browser_visible": False,
            "current_url": "about:blank",
            "last_step_code": payload.get("step_code"),
            "last_step_name": payload.get("step_name"),
            "hud": {
                "title": payload.get("step_name"),
                "state": payload.get("step_code"),
                "action": payload.get("field_domain"),
                "next_step": payload.get("next_step"),
                "store_name": payload.get("store_name"),
                "guard": "只保存不发布",
            },
            "screenshot": None,
            "updated_at": "2026-05-22T00:00:00+00:00",
            "last_error": None,
        }

    def record_action_event(self, **payload):
        if self.fail:
            raise RuntimeError("console unavailable")
        self.action_calls.append(payload)
        return {
            "ok": True,
            "updated": True,
            "reason": "action_recorded",
            "active": True,
            "session_id": "agent-test",
            "task_id": payload.get("task_id"),
            "job_id": payload.get("job_id"),
            "product_id": payload.get("product_id"),
            "browser_visible": False,
            "current_url": payload.get("page_url") or "about:blank",
            "last_step_code": payload.get("step_code") or payload.get("state"),
            "last_step_name": payload.get("label") or payload.get("action"),
            "hud": {
                "title": payload.get("label") or payload.get("action"),
                "state": payload.get("step_code") or payload.get("state"),
                "action": payload.get("action"),
                "next_step": None,
                "store_name": payload.get("store_name"),
                "guard": "只保存不发布",
            },
            "action_events": [payload],
            "screenshot": payload.get("screenshot_url"),
            "updated_at": "2026-05-22T00:00:01+00:00",
            "last_error": None,
        }


@pytest.fixture()
def v1_db(tmp_path, monkeypatch):
    db_path = tmp_path / "v1-runner.db"
    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir()
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(repository_module, "EVIDENCE_DIR", screenshot_dir)
    monkeypatch.setattr(v1_runner_module, "SCREENSHOT_DIR", screenshot_dir)
    db.init_db()
    return db_path


def _create_task(
    repo: Repository,
    mode: str = "single_save",
    product_count: int = 1,
    manual_approval: bool = True,
):
    store = repo.create_store("Dang Kang", "AliExpress")
    dxm_reference_templates = {
        "attribute_info": {"names": ["立牌类谷子"]},
        "description": {"names": [], "required": False},
        "freight": {"names": ["40g普货包裹"]},
        "service": {"names": ["Service Template for New Sellers"]},
        "eu_responsible": {"names": ["Jacqueiline Marti"]},
        "manufacturer": {"names": ["jiyang county thunder"]},
        "compliance": {"names": [], "required": False},
        "semi_managed": {"names": [], "required": False},
    }
    template_payloads = {
        "category": {
            "category_name": "模板类目",
            "dxm_reference_templates": dxm_reference_templates,
            "category": {
                "template_category_id": "tmpl-cat",
            },
        },
        "sku": {"stock": "100", "sku": {"template_sku_rule": "tmpl-sku"}},
        "pricing": {"price": "9.99", "pricing": {"currency": "USD"}},
        "logistics": {
            "weight": "0.03",
            "logistics": {
                "length": "10",
                "width": "10",
                "height": "2",
            },
        },
        "image": {
            "image": {
                "eu_outer_package_filename": "template-eu.jpg",
                "marketing_images_strategy": "generate",
            },
        },
        "compliance": {"compliance": {"material": "PVC"}},
        "semi_managed": {
            "semi_managed": {
                "supply_price": "4.20",
                "jit_stock": "100",
                "is_original_box": "否",
                "length": "10",
                "width": "10",
                "height": "2",
                "goods_code_strategy": "allow_blank",
                "barcode_strategy": "allow_blank",
            },
        },
    }
    for template_type, template_payload in template_payloads.items():
        repo.create_template(
            {
                "template_type": template_type,
                "template_name": f"{template_type} template",
                "binding_scope": "V1",
                "payload": template_payload,
                "is_enabled": True,
            }
        )
    product_ids = []
    for idx in range(product_count):
        source_url = f"https://detail.1688.com/offer/{1013604102950 + idx}.html"
        product_data = {
            "title": f"ACG Stand Product {idx + 1}",
            "source": "dxm_draft_box" if mode == "single_save" else "test",
            "status": "ready_for_edit" if mode == "single_save" else "draft",
            "category_name": "立牌类谷子",
            "price": 7.01,
            "currency": "USD",
            "sku_count": 8,
            "image_count": 8,
            "payload": {
                "source": "dxm_draft_box" if mode == "single_save" else "test",
                "source_title": f"ACG Stand Product {idx + 1}",
                "source_url": source_url,
                "source_urls": [source_url],
                "draft_box_verified": mode == "single_save",
                "store_id": store["id"],
                "store_name": "Dang Kang",
                "product_box_evidence_ref": _evidence_ref(f"v1-product-{idx + 1}.png"),
                "category": {"template_category_id": f"product-cat-{idx + 1}"},
                "image": {"eu_outer_package_filename": f"product-eu-{idx + 1}.jpg"},
                "compliance": {"battery": "none"},
            },
        }
        product = repo.create_product(product_data)
        product_ids.append(product["id"])
    task = repo.create_task(
        {
            "name": "V1 半托管保存任务",
            "store_id": store["id"],
            "mode": mode,
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": product_ids,
            "payload": {
                "store_name": "Dang Kang",
                "category_name": "任务类目",
                "template_overrides": {"logistics": {"weight": "0.05"}},
                "image": {"alt_text": "任务图片说明"},
                "compliance": {"material": "ABS"},
                "semi_managed": {"supply_price": "5.60"},
            },
        }
    )
    if mode in {"single_save", "batch_save"} and manual_approval:
        approval = repo.set_task_manual_approval(
            task["id"],
            approved=True,
            token="runner-approval-token",
            approved_by="ops-owner",
        )
        assert approval.ok is True
        assert approval.task is not None
        approved_task = repo.get_task_private(task["id"])
        assert approved_task is not None
        return approved_task
    return task


def test_single_save_generates_success_report_and_never_publishes(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()

    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "completed"
    assert len(reports) == 1
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["msg"] == "真实保存成功"
    assert "claim_mark" not in reports[0]["summary"]
    assert reports[0]["summary"]["product_box_snapshot_fingerprint"]
    assert "semi_goods" in reports[0]["summary"]["filled_fields"]


def test_single_save_late_success_cannot_override_manual_review_after_save_authorization(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()

    class ManualReviewDuringSaveAdapter(FakeWorkflowAdapter):
        def save_only(
            self,
            defaults=None,
            product_query=None,
            store_name=None,
            target_identity=None,
            **kwargs,
        ):
            repo.update_task_status(task["id"], "needs_manual_review")
            return super().save_only(
                defaults,
                product_query,
                store_name,
                target_identity=target_identity,
                **kwargs,
            )

    asyncio.run(
        _test_runner(
            repo,
            manager,
            workflow_adapter=ManualReviewDuringSaveAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "needs_manual_review"
    assert refreshed["jobs"][0]["status"] == "running"
    assert repo.list_reports(task["id"]) == []
    assert not any(payload.get("type") == "job_completed" for _, payload in manager.events)
    assert not any(
        payload.get("type") == "task_status" and payload.get("status") in {"completed", "partial_success"}
        for _, payload in manager.events
    )


def test_create_task_preserves_payload_overrides(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    assert task["payload"]["store_name"] == "Dang Kang"
    assert task["payload"]["category_name"] == "任务类目"
    assert task["payload"]["template_overrides"]["logistics"]["weight"] == "0.05"
    assert task["payload"]["image"]["alt_text"] == "任务图片说明"
    assert task["payload"]["compliance"]["material"] == "ABS"
    assert task["payload"]["semi_managed"]["supply_price"] == "5.60"


def test_single_save_calls_workflow_adapter_in_complete_save_order(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert [call[0] for call in adapter.calls] == [
        "check_login_state",
        "open_draft_box",
        "open_editor",
        "verify_edit_ownership",
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "enable_semi_managed",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "fill_semi_managed_defaults",
        "save_only",
        "verify_not_published",
    ]
    source_urls = ["https://detail.1688.com/offer/1013604102950.html"]
    assert adapter.calls[2][1:4] == ("ACG Stand Product 1", "Dang Kang", source_urls)
    assert adapter.calls[3][1:4] == ("ACG Stand Product 1", "Dang Kang", source_urls)
    assert adapter.calls[2][4] == adapter.calls[3][4]
    defaults = adapter.calls[4][1]
    assert defaults["category_name"] == "任务类目"
    assert defaults["category"]["template_category_id"] == "tmpl-cat"
    assert defaults["logistics"]["weight"] == "0.05"
    assert defaults["image"]["eu_outer_package_filename"] == "template-eu.jpg"
    assert defaults["image"]["alt_text"] == "任务图片说明"
    assert defaults["compliance"]["material"] == "PVC"
    assert defaults["compliance"]["battery"] == "none"
    assert defaults["semi_managed"]["supply_price"] == "4.20"
    assert adapter.calls[9][1] == defaults
    reports = repo.list_reports(task["id"])
    assert reports[0]["published"] is False
    assert reports[0]["summary"]["workflow_actions"] == [
        "check_login_state",
        "open_draft_box",
        "open_editor",
        "verify_edit_ownership",
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "enable_semi_managed",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "fill_semi_managed_defaults",
        "save_only",
        "verify_not_published",
    ]
    assert reports[0]["summary"]["workflow_results"][-1]["product_query"] == "ACG Stand Product 1"
    assert reports[0]["summary"]["workflow_results"][-1]["store_name"] == "Dang Kang"
    assert reports[0]["summary"]["category"] == "立牌类谷子"
    assert reports[0]["summary"]["template_trace"]
    assert "_template_trace" not in reports[0]["summary"]["resolved_defaults"]


def test_single_save_fill_actions_use_manually_selected_template_over_store_default(v1_db):
    repo = Repository()
    store_template = repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "Dang Kang 店铺包装模板",
            "binding_scope": "Dang Kang",
            "payload": {
                "binding": {"store_name": "Dang Kang", "category_name": "立牌类谷子", "platform": "AliExpress"},
                "logistics": {"weight": "0.03", "length": "10", "width": "10", "height": "2"},
            },
            "is_enabled": True,
        }
    )
    selected_template = repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "本次选择包装模板",
            "binding_scope": "手动选择",
            "payload": {
                "binding": {"store_name": "Other Store", "category_name": "Other Category", "platform": "AliExpress"},
                "logistics": {"weight": "0.09", "length": "18", "width": "12", "height": "4"},
            },
            "is_enabled": True,
        }
    )
    task = _create_task(repo, mode="single_save", product_count=1)
    payload = dict(task["payload"])
    payload["template_id"] = selected_template["id"]
    payload.pop("template_overrides", None)
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), task["id"]),
        )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    fill_defaults = next(call[1] for call in adapter.calls if call[0] == "fill_editor_required_defaults")
    assert fill_defaults["logistics"]["weight"] == "0.09"
    assert fill_defaults["logistics"]["length"] == "18"
    assert fill_defaults["logistics"]["width"] == "12"
    assert fill_defaults["logistics"]["height"] == "4"
    fill_action_defaults = [
        call[1]
        for call in adapter.calls
        if call[0]
        in {
            "fill_editor_required_defaults",
            "fill_editor_variants",
            "fill_media_assets",
            "fill_compliance_defaults",
            "open_semi_managed_page",
            "fill_semi_managed_defaults",
            "save_only",
        }
    ]
    assert fill_action_defaults
    assert all(defaults["logistics"]["weight"] == "0.09" for defaults in fill_action_defaults)
    reports = repo.list_reports(task["id"])
    trace_names = [item["template_name"] for item in reports[0]["summary"]["template_trace"]]
    assert trace_names.index(store_template["template_name"]) < trace_names.index(selected_template["template_name"])


def test_single_save_syncs_agent_console_hud_without_changing_workflow_order(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()
    console = FakeAgentConsole()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    states = [call["step_code"] for call in console.calls]
    assert "PRECHECK_CONFIG" in states
    assert "PRECHECK_PUBLISH_GUARD" in states
    assert "SELECT_CATEGORY" in states
    assert "SAVE_ONLY" in states
    assert "VERIFY_NOT_PUBLISHED" in states
    assert "WRITE_REPORT" in states
    assert "RELEASE_LOCK" in states
    precheck_config = next(call for call in console.calls if call["step_code"] == "PRECHECK_CONFIG")
    open_draft = next(call for call in console.calls if call["step_code"] == "OPEN_DRAFT_LIST")
    find_product = next(call for call in console.calls if call["step_code"] == "FIND_PRODUCT")
    open_editor = next(call for call in console.calls if call["step_code"] == "OPEN_EDIT_PAGE")
    base_info = next(call for call in console.calls if call["step_code"] == "FILL_BASE_INFO")
    variants = next(call for call in console.calls if call["step_code"] == "FILL_VARIANTS")
    media = next(call for call in console.calls if call["step_code"] == "FILL_MEDIA")
    semi_goods = next(call for call in console.calls if call["step_code"] == "FILL_SEMI_GOODS")
    select_category = next(call for call in console.calls if call["step_code"] == "SELECT_CATEGORY")
    save_only = next(call for call in console.calls if call["step_code"] == "SAVE_ONLY")
    verify_not_published = next(call for call in console.calls if call["step_code"] == "VERIFY_NOT_PUBLISHED")
    release_lock = next(call for call in console.calls if call["step_code"] == "RELEASE_LOCK")
    assert precheck_config["human_title"] == "开始任务"
    assert precheck_config["phase"] == "准备执行"
    assert open_draft["human_title"] == "正在打开商品箱"
    assert open_draft["human_action"] == "进入店小秘商品箱"
    assert find_product["human_title"] == "正在定位商品"
    assert open_editor["human_title"] == "正在打开编辑页"
    assert base_info["human_title"] == "正在编辑商品"
    assert base_info["human_action"] == "正在填写标题"
    assert base_info["human_next"] == "继续填写价格、图片和物流信息"
    assert select_category["human_title"] == "正在选择分类"
    assert select_category["human_action"] == "确认商品分类和属性"
    assert select_category["progress_index"] == 6
    assert select_category["progress_total"] == 12
    assert variants["human_action"] == "正在填写价格、库存和 SKU"
    assert media["human_action"] == "正在处理图片"
    assert semi_goods["human_title"] == "正在设置包装物流"
    assert save_only["human_title"] == "正在只保存"
    assert save_only["human_action"] == "只点击保存，不发布"
    assert verify_not_published["human_title"] == "正在检查结果"
    assert verify_not_published["human_action"] == "确认商品没有发布"
    assert release_lock["human_title"] == "任务完成"
    assert release_lock["progress_index"] == 12
    assert release_lock["progress_total"] == 12
    operator_phrases = [
        "开始任务",
        "进入店小秘商品箱",
        "查找本次要编辑保存的商品",
        "进入商品编辑页",
        "正在填写标题",
        "确认商品分类和属性",
        "正在填写价格、库存和 SKU",
        "正在处理图片",
        "填写重量、尺寸和物流信息",
        "只点击保存，不发布",
        "确认商品没有发布",
        "任务完成",
    ]
    hud_text = "\n".join(
        str(call.get(key) or "")
        for call in console.calls
        for key in ("phase", "human_title", "human_action", "human_next")
    )
    for phrase in operator_phrases:
        assert phrase in hud_text
    assert all(call["progress_total"] == 12 for call in console.calls if call.get("progress_total"))
    compact_progress = []
    for call in console.calls:
        progress = call.get("progress_index")
        if not progress or progress == (compact_progress[-1] if compact_progress else None):
            continue
        compact_progress.append(progress)
    assert compact_progress == list(range(1, 13))
    assert all(call["severity"] == "running" for call in console.calls)
    assert all(call["requires_user_action"] is False for call in console.calls)
    assert all(call["store_name"] == "Dang Kang" for call in console.calls)
    assert console.start_calls == []
    assert [call["action"] for call in console.action_calls] == [call[0] for call in adapter.calls]
    assert next(call for call in console.action_calls if call["action"] == "fill_editor_required_defaults")["type"] == "fill"
    assert next(call for call in console.action_calls if call["action"] == "fill_media_assets")["type"] == "upload"
    save_action = next(call for call in console.action_calls if call["action"] == "save_only")
    assert save_action["type"] == "save"
    assert save_action["save_result"]["published"] is False
    assert [call[0] for call in adapter.calls].count("save_only") == 1
    assert [call[0] for call in adapter.calls].index("save_only") < [call[0] for call in adapter.calls].index("verify_not_published")

    report = repo.list_reports(task["id"])[0]
    assert report["published"] is False
    assert report["save_result"]["published"] is False
    assert report["summary"]["agent_console"]["session_id"] == "agent-test"
    assert report["summary"]["agent_console"]["hud"]["guard"] == "只保存不发布"
    assert report["summary"]["agent_console"]["last_step_code"] == "RELEASE_LOCK"
    assert report["summary"]["agent_action_events"][-1]["action"] == "verify_not_published"
    assert any(event["action"] == "save_only" and event["type"] == "save" for event in report["summary"]["agent_action_events"])
    assert any(
        evidence["meta"].get("agent_console", {}).get("hud", {}).get("guard") == "只保存不发布"
        for evidence in repo.list_evidences(task["id"])
    )
    assert any(
        evidence["evidence_type"] == "workflow_action"
        and evidence["meta"].get("agent_action", {}).get("action") == "save_only"
        for evidence in repo.list_evidences(task["id"])
    )


def test_single_save_updates_live_browser_hud_without_agent_console(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    states = [call["step_code"] for call in adapter.live_hud_calls]
    assert "PRECHECK_CONFIG" in states
    assert "FILL_BASE_INFO" in states
    assert "SELECT_CATEGORY" in states
    assert "SAVE_ONLY" in states
    assert "VERIFY_NOT_PUBLISHED" in states
    select_category = next(call for call in adapter.live_hud_calls if call["step_code"] == "SELECT_CATEGORY")
    assert select_category["human_title"] == "正在选择分类"
    assert select_category["human_action"] == "确认商品分类和属性"
    assert select_category["progress_index"] == 6
    assert select_category["progress_total"] == 12
    save_only = next(call for call in adapter.live_hud_calls if call["step_code"] == "SAVE_ONLY")
    assert save_only["human_title"] == "正在只保存"
    assert save_only["human_action"] == "只点击保存，不发布"
    assert save_only["progress_total"] == 12
    assert save_only["store_name"] == "Dang Kang"
    assert save_only["requires_user_action"] is False

    report = repo.list_reports(task["id"])[0]
    assert report["summary"]["agent_console_events"] == []
    assert report["summary"]["agent_console"] is None
    assert report["summary"]["live_browser_hud_events"]
    assert report["summary"]["live_browser_hud"]["last_step_code"] == "RELEASE_LOCK"
    assert report["summary"]["live_browser_hud"]["hud"]["guard"] == "只保存不发布"
    assert any(
        evidence["meta"].get("live_browser_hud", {}).get("hud", {}).get("human_title") == "正在只保存"
        for evidence in repo.list_evidences(task["id"])
    )


def test_single_save_persists_save_and_unpublished_evidence_refs_in_workflow_meta(v1_db):
    class EvidenceWorkflowAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args, target_identity=None):
            result = super()._record(
                action,
                *args,
                target_identity=target_identity,
            )
            if action in {"save_only", "verify_not_published"}:
                evidence_ref = _evidence_ref(f"{action}-proof.png")
                result["evidence"]["refs"] = [
                    {
                        **evidence_ref,
                        "kind": (
                            "save_screenshot"
                            if action == "save_only"
                            else "unpublished_screenshot"
                        ),
                        "captured_at": (
                            "2026-05-22T00:00:01+00:00"
                            if action == "save_only"
                            else "2026-05-22T00:00:02+00:00"
                        ),
                    }
                ]
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(_test_runner(repo, DummyManager(), workflow_adapter=EvidenceWorkflowAdapter()).run_task(task["id"]))

    workflow_evidence = {
        evidence["meta"].get("state"): evidence
        for evidence in repo.list_evidences(task["id"])
        if evidence["evidence_type"] == "workflow_action"
    }
    for state in {"SAVE_ONLY", "VERIFY_NOT_PUBLISHED"}:
        evidence = workflow_evidence[state]
        evidence_ref = evidence["meta"]["evidence_ref"]
        assert set(evidence_ref) == {"path", "sha256", "size"}
        assert evidence["file_path"] == evidence_ref["path"]


def test_agent_console_sync_failure_does_not_fail_save_flow(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()
    console = FakeAgentConsole(fail=True)

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    report = repo.list_reports(task["id"])[0]
    assert refreshed["status"] == "completed"
    assert report["status"] == "success"
    assert report["published"] is False
    assert report["summary"]["agent_console"]["reason"] == "agent_console_exception"
    assert "console unavailable" in report["summary"]["agent_console"]["last_error"]


def test_execution_defaults_task_payload_overrides_stale_product_media_slots(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product = repo.list_products()[0]
    product["payload"]["image"]["slots"] = [
        {"slot_key": "marketing_scene_3_4", "strategy": "generate", "label": "(3:4场景图)"},
        {"slot_key": "eu_outer_package", "filename": "product-eu-1.jpg", "label": "外包装/标签实拍图-欧盟"},
    ]
    task["payload"]["image"]["slots"] = [
        {"slot_key": "marketing_scene_3_4", "strategy": "generate", "label": "(3:4场景图)", "filename": "scene-750x1000.jpg"},
        {"slot_key": "eu_outer_package", "filename": "task-eu.jpg", "label": "外包装/标签实拍图-欧盟"},
    ]

    defaults = _test_runner(repo, DummyManager())._execution_defaults(task, product)

    assert defaults["image"]["slots"][0]["filename"] == "scene-750x1000.jpg"
    assert defaults["image"]["slots"][1]["filename"] == "task-eu.jpg"


def test_execution_defaults_only_applies_matching_template_bindings():
    class TemplateRepo:
        def list_templates(self):
            return [
                {
                    "id": 1,
                    "template_type": "category",
                    "template_name": "Other category",
                    "binding_scope": "store/category",
                    "payload": {
                        "binding": {"store_name": "Other Store", "category_name": "运动鞋"},
                        "category": {"category_match": "Shoes"},
                    },
                    "is_enabled": True,
                },
                {
                    "id": 2,
                    "template_type": "category",
                    "template_name": "ACG Stand",
                    "binding_scope": "store/category",
                    "payload": {
                        "binding": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
                        "category": {
                            "category_keyword": "立牌",
                            "category_match": "ACG Stand",
                            "attribute_template_priorities": ["立牌类谷子"],
                        },
                    },
                    "is_enabled": True,
                },
            ]

    runner = _test_runner(TemplateRepo(), DummyManager())
    defaults = runner._execution_defaults(
        {"payload": {"store_name": "Dang Kang"}},
        {"category_name": "立牌类谷子", "payload": {}},
    )

    assert defaults["category"]["category_match"] == "ACG Stand"
    assert defaults["category"]["attribute_template_priorities"] == ["立牌类谷子"]
    assert defaults["dxm_reference_templates_resolved"]["attribute_info"] == {
        "names": ["立牌类谷子"],
        "required": True,
    }
    assert defaults["_template_trace"] == [
        {
            "template_id": 2,
            "template_type": "category",
            "template_name": "ACG Stand",
            "binding_scope": "store/category",
        }
    ]


def test_execution_defaults_resolves_new_dxm_reference_templates():
    class TemplateRepo:
        def list_templates(self):
            return [
                {
                    "id": 1,
                    "template_type": "dxm_reference",
                    "template_name": "Dxm Reference",
                    "binding_scope": "V1",
                    "payload": {
                        "dxm_reference_templates": {
                            "freight": {"names": ["40g普货包裹"]},
                            "service": {"names": [], "required": False},
                        },
                        "logistics": {
                            "freight_template_priorities": ["旧运费模板"],
                            "service_template_priorities": ["旧服务模板"],
                        },
                    },
                    "is_enabled": True,
                },
            ]

    runner = _test_runner(TemplateRepo(), DummyManager())
    defaults = runner._execution_defaults({"payload": {}}, {"payload": {}})

    assert defaults["dxm_reference_templates_resolved"]["freight"] == {"names": ["40g普货包裹"], "required": True}
    assert defaults["dxm_reference_templates_resolved"]["service"] == {"names": [], "required": False}
    assert defaults["dxm_reference_templates_resolved"]["attribute_info"] == {"names": [], "required": True}


def test_single_save_missing_required_dxm_reference_template_fails_before_save(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    with db.connection() as conn:
        conn.execute(
            "UPDATE templates SET payload_json=? WHERE template_type='category'",
            (
                db.dumps(
                    {
                        "category_name": "模板类目",
                        "dxm_reference_templates": {
                            "attribute_info": {"names": ["立牌类谷子"]},
                            "freight": {"names": [], "required": True},
                            "service": {"names": ["Service Template for New Sellers"]},
                            "eu_responsible": {"names": ["Jacqueiline Marti"]},
                            "manufacturer": {"names": ["jiyang county thunder"]},
                        },
                        "category": {
                            "template_category_id": "tmpl-cat",
                        },
                    }
                ),
            ),
        )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "dxm_reference_templates.freight" in reports[0]["summary"]["blocked_reason"]
    assert "save_only" not in [call[0] for call in adapter.calls]


def test_single_save_report_includes_resolved_dxm_reference_templates(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (
                db.dumps(
                    {
                        **task["payload"],
                        "dxm_reference_templates": {
                            "freight": {"names": ["40g普货包裹"], "required": True},
                            "description": {"names": [], "required": False},
                        },
                    }
                ),
                task["id"],
            ),
        )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    resolved = reports[0]["summary"]["dxm_reference_templates_resolved"]
    assert resolved["description"] == {"names": [], "required": False}
    assert resolved["freight"] == {"names": ["40g普货包裹"], "required": True}
    reference_results = reports[0]["summary"]["dxm_reference_template_results"]
    assert set(reference_results) == {
        "attribute_info",
        "description",
        "freight",
        "service",
        "eu_responsible",
        "manufacturer",
        "compliance",
        "semi_managed",
    }
    assert reference_results["description"] == {"ok": True, "section": "description", "names": [], "required": False}
    assert reference_results["freight"] == {"ok": True, "section": "freight", "names": ["40g普货包裹"], "required": True}


@pytest.mark.parametrize("invalid_result", [None, True, "unexpected"])
def test_real_mutation_authorizer_malformed_result_fails_closed(v1_db, invalid_result):
    runner = V1TaskRunner(
        Repository(),
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        authorization_verifier=lambda *_args: invalid_result,
    )

    with pytest.raises(V1ExecutionError) as exc_info:
        runner._assert_real_mutation_authorized(1, "single_save", StateName.SAVE_ONLY)

    assert exc_info.value.error_code == "AUTH_REVALIDATION_FAILED"


def test_single_save_revalidates_consumed_lease_immediately_before_save_mutation(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    adapter = FakeWorkflowAdapter()
    verifier_calls = []

    def reject_drift(task_id, mode, state):
        verifier_calls.append((task_id, mode, state))
        return {"ok": False, "reason_code": "AUTH_LEASE_EXPIRED"}

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=adapter,
            authorization_verifier=reject_drift,
        ).run_task(task["id"])
    )

    assert verifier_calls == [(task["id"], "single_save", "SAVE_ONLY")]
    assert "save_only" not in [call[0] for call in adapter.calls]
    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert report["save_result"]["error_code"] == "AUTH_LEASE_EXPIRED"


def test_single_save_fails_when_adapter_lacks_media_or_compliance_methods(v1_db):
    class LegacyWorkflowAdapter(FakeWorkflowAdapter):
        fill_media_assets = None
        fill_compliance_defaults = None

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = LegacyWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["save_result"]["ok"] is False
    assert "fill_media_assets adapter method unavailable" in reports[0]["save_result"]["message"]
    assert "fill_media_assets adapter method unavailable" in reports[0]["summary"]["blocked_reason"]
    assert "fill_compliance_defaults" not in reports[0]["summary"]["workflow_actions"]


def test_single_save_missing_eu_outer_package_image_config_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = repo.get_task(task["id"])["jobs"][0]["product_id"]
    with db.connection() as conn:
        conn.execute(
            "UPDATE products SET payload_json=? WHERE id=?",
            (db.dumps({"source_title": "ACG Stand Product 1", "compliance": {"battery": "none"}}), product_id),
        )
        conn.execute(
            "UPDATE templates SET payload_json=? WHERE template_type='image'",
            (db.dumps({"image": {"alt_text": "no eu image"}}),),
        )
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (
                db.dumps({
                    **task["payload"],
                    "image": {"alt_text": "task no eu image"},
                }),
                task["id"],
            ),
        )

    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "eu_outer_package" in reports[0]["summary"]["blocked_reason"]


def test_workflow_adapter_failure_fails_job_and_writes_exception_and_report(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(fail_action="open_editor")

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    reports = repo.list_reports(task["id"])
    exceptions = repo.list_exceptions()
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is None
    assert "open_editor" in reports[0]["summary"]["blocked_reason"]
    assert exceptions[0]["error_code"] == "E901"
    assert any(
        payload.get("type") == "task_status" and payload.get("status") == "failed"
        for _, payload in manager.events
    )
    assert not any(payload.get("type") == "job_completed" for _, payload in manager.events)
    assert exceptions[0]["field_domain"] == "v1_executor"


@pytest.mark.parametrize("impostor_ok", ["true", 1])
def test_workflow_action_rejects_non_boolean_success_values(v1_db, impostor_ok):
    class ImpostorOkAdapter(FakeWorkflowAdapter):
        def open_draft_box(self):
            result = super().open_draft_box()
            result["ok"] = impostor_ok
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=ImpostorOkAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E201"
    assert [report for report in reports if report["status"] == "success"] == []


def test_single_save_runner_requires_server_manual_approval_immediately_before_save(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1, manual_approval=False)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert "save_only" not in [call[0] for call in adapter.calls]
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is None
    assert "人工确认" in reports[0]["summary"]["blocked_reason"]


def test_single_save_browser_agent_still_requires_manual_approval_before_save(v1_db, monkeypatch):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1, manual_approval=False)
    manager = DummyManager()
    runtime = FakeBrowserAgentRuntime()
    runner = _test_runner(
        repo,
        manager,
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    asyncio.run(runner.run_task(task["id"]))

    actions = [command.action for command, _timeout in runtime.commands]
    assert "open_editor" in actions
    assert "save_only" not in actions
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is None
    assert "人工确认" in reports[0]["summary"]["blocked_reason"]


def test_single_save_browser_agent_records_save_only_result(v1_db, monkeypatch):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    runtime = FakeBrowserAgentRuntime()
    runner = _test_runner(
        repo,
        manager,
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    asyncio.run(runner.run_task(task["id"]))

    actions = [command.action for command, _timeout in runtime.commands]
    assert "save_only" in actions
    assert actions.index("save_only") < actions.index("verify_not_published")
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["ok"] is True


def test_save_only_false_save_result_fails_job(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(save_result={"ok": False, "message": "保存失败", "published": False})

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is None
    assert "保存失败" in reports[0]["summary"]["blocked_reason"]


def test_single_save_fails_when_action_result_has_no_evidence_descriptor(v1_db):
    class MissingEvidenceAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args, target_identity=None):
            result = super()._record(
                action,
                *args,
                target_identity=target_identity,
            )
            if action in {"save_only", "verify_not_published"}:
                result["evidence"]["refs"] = []
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=MissingEvidenceAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E999"
    assert [report for report in reports if report["status"] == "success"] == []


def test_single_save_rejects_nested_only_evidence_descriptor(v1_db):
    class NestedOnlyEvidenceAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args, target_identity=None):
            result = super()._record(
                action,
                *args,
                target_identity=target_identity,
            )
            if action == "save_only":
                result["evidence"]["refs"] = []
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=NestedOnlyEvidenceAdapter(),
        ).run_task(task["id"])
    )

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "immutable evidence refs" in report["summary"]["blocked_reason"]


@pytest.mark.parametrize(
    ("corruption", "reason_code"),
    [
        ("outside", "EVIDENCE_REF_OUTSIDE_SCREENSHOT_DIR"),
        ("extension", "EVIDENCE_REF_EXTENSION_INVALID"),
        ("signature", "EVIDENCE_REF_PNG_SIGNATURE_INVALID"),
        ("hash", "EVIDENCE_REF_SHA256_MISMATCH"),
        ("size", "EVIDENCE_REF_SIZE_MISMATCH"),
    ],
)
def test_single_save_rejects_invalid_live_evidence(
    v1_db,
    tmp_path,
    corruption,
    reason_code,
):
    class InvalidEvidenceAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args, target_identity=None):
            result = super()._record(
                action,
                *args,
                target_identity=target_identity,
            )
            if action != "save_only":
                return result

            extended_ref = dict(_test_action_first_ref(result))
            evidence_ref = {
                "path": extended_ref["path"],
                "sha256": extended_ref["sha256"],
                "size": extended_ref["size"],
            }
            evidence_path = Path(evidence_ref["path"])
            if corruption == "outside":
                evidence_path = tmp_path / "outside.png"
                content = b"\x89PNG\r\n\x1a\noutside"
                evidence_path.write_bytes(content)
                evidence_ref = {
                    "path": str(evidence_path.resolve()),
                    "sha256": hashlib.sha256(content).hexdigest().upper(),
                    "size": len(content),
                }
            elif corruption == "extension":
                evidence_path = Path(v1_runner_module.SCREENSHOT_DIR) / "save-proof.txt"
                content = b"\x89PNG\r\n\x1a\nwrong-extension"
                evidence_path.write_bytes(content)
                evidence_ref = {
                    "path": str(evidence_path.resolve()),
                    "sha256": hashlib.sha256(content).hexdigest().upper(),
                    "size": len(content),
                }
            elif corruption == "signature":
                content = b"not-a-real-png"
                evidence_path.write_bytes(content)
                evidence_ref["sha256"] = hashlib.sha256(content).hexdigest().upper()
                evidence_ref["size"] = len(content)
            elif corruption == "hash":
                content = bytearray(evidence_path.read_bytes())
                content[-1] = (content[-1] + 1) % 256
                evidence_path.write_bytes(bytes(content))
            elif corruption == "size":
                evidence_ref["size"] += 1

            result["evidence"]["refs"] = [
                {
                    **evidence_ref,
                    "kind": extended_ref["kind"],
                    "captured_at": extended_ref["captured_at"],
                }
            ]
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=InvalidEvidenceAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E999"
    assert reason_code in reports[0]["summary"]["blocked_reason"]
    assert [report for report in reports if report["status"] == "success"] == []


def test_single_save_revalidates_save_evidence_before_finalize(v1_db):
    class LateTamperAdapter(FakeWorkflowAdapter):
        def __init__(self):
            super().__init__()
            self.save_evidence_path = None

        def _record(self, action, *args, target_identity=None):
            result = super()._record(
                action,
                *args,
                target_identity=target_identity,
            )
            if action == "save_only":
                self.save_evidence_path = Path(_test_action_first_ref(result)["path"])
            elif action == "verify_not_published" and self.save_evidence_path:
                content = bytearray(self.save_evidence_path.read_bytes())
                content[-1] = (content[-1] + 1) % 256
                self.save_evidence_path.write_bytes(bytes(content))
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=LateTamperAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E999"
    assert "EVIDENCE_REF_SHA256_MISMATCH" in reports[0]["summary"]["blocked_reason"]
    assert [report for report in reports if report["status"] == "success"] == []


def test_save_only_smt_add_json_network_success_does_not_leave_failure_summary(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(
        save_result={
            "ok": True,
            "message": "您的产品编辑成功！",
            "success_text": "您的产品编辑成功！",
            "published": False,
            "network_save_result": {
                "ok": True,
                "url": "https://www.dianxiaomi.com/api/smtProduct/add.json",
                "method": "POST",
                "status": 200,
                "code": 0,
                "msg": "您的产品编辑成功！",
                "raw": {
                    "code": 0,
                    "msg": "Successful",
                    "data": {
                        "msg": "您的产品编辑成功！",
                        "code": 0,
                        "productId": "130658341344670934",
                    },
                },
            },
            "network_events": [
                {
                    "url": "https://www.dianxiaomi.com/api/smtProduct/add.json",
                    "method": "POST",
                    "resource_type": "xhr",
                    "status": 200,
                    "json": {
                        "code": 0,
                        "msg": "Successful",
                        "data": {
                            "msg": "您的产品编辑成功！",
                            "code": 0,
                            "productId": "130658341344670934",
                        },
                    },
                }
            ],
        },
    )

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["network_save_result"]["url"].endswith("/api/smtProduct/add.json")
    assert reports[0]["summary"].get("blocked_reason") is None
    action_evidence = {
        item["meta"].get("action"): item
        for item in repo.list_evidences(task["id"])
        if item["evidence_type"] == "workflow_action"
        and item["meta"].get("action") in {"save_only", "verify_not_published"}
    }
    assert set(action_evidence) == {"save_only", "verify_not_published"}
    for item in action_evidence.values():
        evidence_ref = item["meta"]["evidence_ref"]
        content = Path(evidence_ref["path"]).read_bytes()
        assert set(evidence_ref) == {"path", "sha256", "size"}
        assert item["file_path"] == evidence_ref["path"]
        assert evidence_ref["size"] == len(content)
        assert evidence_ref["sha256"] == hashlib.sha256(content).hexdigest().upper()


def test_single_save_runner_rejects_product_that_lost_ready_for_edit_status_before_browser(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = task["payload"]["product_ids"][0]
    with sqlite3.connect(v1_db) as conn:
        conn.execute("UPDATE products SET status='draft' WHERE id=?", (product_id,))
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == []
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "商品箱" in reports[0]["summary"]["blocked_reason"]


def test_single_save_runner_rejects_product_without_draft_box_verification_before_browser(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = task["payload"]["product_ids"][0]
    with sqlite3.connect(v1_db) as conn:
        row = conn.execute("SELECT payload_json FROM products WHERE id=?", (product_id,)).fetchone()
        payload = json.loads(row[0])
        payload["draft_box_verified"] = False
        conn.execute("UPDATE products SET payload_json=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), product_id))
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == []
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "商品箱验证" in reports[0]["summary"]["blocked_reason"]


def test_save_only_missing_save_result_fails_job(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(include_save_result=False)

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is None
    assert "save_result" in reports[0]["summary"]["blocked_reason"]


def test_save_only_failure_report_includes_save_result_reason(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(
        fail_action="save_only",
        save_result={
            "ok": False,
            "message": "保存按钮已点击但未成功",
            "reason": "未检测到保存成功提示",
            "published": False,
            "network_save_result": {"ok": False, "reason": "未捕获保存相关接口响应"},
            "network_events": [],
        },
    )
    console = FakeAgentConsole()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "未检测到保存成功提示" in report["summary"]["blocked_reason"]
    assert "未捕获保存相关接口响应" in report["summary"]["blocked_reason"]
    assert "保存接口捕获 0 条" in report["summary"]["blocked_reason"]
    assert "未检测到保存成功提示" in report["save_result"]["message"]
    failure_console_call = console.calls[-1]
    assert failure_console_call["step_code"] == "TASK_FAILED"
    assert failure_console_call["severity"] == "error"
    assert failure_console_call["requires_user_action"] is True
    assert "查看结果与问题" in failure_console_call["human_next"]
    failure_live_hud = adapter.live_hud_calls[-1]
    assert failure_live_hud["step_code"] == "TASK_FAILED"
    assert failure_live_hud["severity"] == "error"
    assert failure_live_hud["requires_user_action"] is True
    assert "真实保存不会继续" in failure_live_hud["human_action"]


def test_runner_uses_injected_workflow_executor_for_thread_bound_login_flow(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = ThreadRecordingWorkflowAdapter()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dxm-login-flow") as executor:
        asyncio.run(
            _test_runner(
                repo,
                manager,
                workflow_adapter=adapter,
                workflow_executor=executor,
            ).run_task(task["id"])
        )

    assert adapter.thread_names
    assert all(name.startswith("dxm-login-flow") for name in adapter.thread_names)
    assert adapter.hud_thread_names
    assert all(name.startswith("dxm-login-flow") for name in adapter.hud_thread_names)
    assert repo.get_task(task["id"])["status"] == "completed"


def test_real_dxm_adapter_always_requires_persistent_browser_agent_runtime(v1_db, monkeypatch):
    class MinimalFlow:
        pass

    repo = Repository()
    manager = DummyManager()
    real_adapter = DxmWorkflowAdapter(MinimalFlow())
    fake_adapter = FakeWorkflowAdapter()

    persistent_runtime = object()

    assert _test_runner(
        repo,
        manager,
        workflow_adapter=real_adapter,
        browser_agent_runtime=persistent_runtime,
    )._use_browser_agent_runtime() is True
    assert _test_runner(repo, manager, workflow_adapter=real_adapter)._use_process_workflow_runtime() is False
    assert _test_runner(repo, manager, workflow_adapter=fake_adapter)._use_process_workflow_runtime() is False

    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "thread")
    forced_thread = _test_runner(
        repo,
        manager,
        workflow_adapter=real_adapter,
        browser_agent_runtime=persistent_runtime,
    )
    assert forced_thread._use_browser_agent_runtime() is True
    assert forced_thread._use_process_workflow_runtime() is False

    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "process")
    forced_process = _test_runner(
        repo,
        manager,
        workflow_adapter=real_adapter,
        browser_agent_runtime=persistent_runtime,
    )
    assert forced_process._use_browser_agent_runtime() is True
    assert forced_process._use_process_workflow_runtime() is False
    assert _test_runner(repo, manager, workflow_adapter=fake_adapter)._use_process_workflow_runtime() is True


def test_single_save_process_worker_keeps_source_urls_for_editor_identity(v1_db, monkeypatch):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    runner = _test_runner(repo, DummyManager(), workflow_adapter=FakeWorkflowAdapter())
    requests = []

    def fake_invoke_worker(**kwargs):
        requests.append(kwargs["request"])
        legacy_result = {
            "ok": True,
            "action": kwargs["action_name"],
            "stage": f"{kwargs['action_name']}_stage",
            "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=123",
            "evidence": {"stage": f"{kwargs['action_name']}_stage"},
        }
        return _canonical_test_action_result(
            kwargs["action_name"],
            legacy_result,
            state_override=kwargs["state_name"].value,
        )

    monkeypatch.setattr(runner, "_invoke_workflow_worker", fake_invoke_worker)

    for state_name in (StateName.OPEN_EDIT_PAGE, StateName.VERIFY_EDIT_OWNERSHIP):
        runner._run_workflow_action_process(
            task,
            job,
            state_name,
            {},
        )

    assert [request["action"] for request in requests] == ["open_editor", "verify_edit_ownership"]
    assert requests[0]["params"]["target_source_urls"] == ["https://detail.1688.com/offer/1013604102950.html"]
    assert requests[1]["params"]["target_source_urls"] == ["https://detail.1688.com/offer/1013604102950.html"]


def test_v1_rebuilds_command_with_stable_idempotency_key_and_runtime_reuses_result(v1_db):
    class Adapter:
        def __init__(self):
            self.calls = 0

        def browser_session_id(self):
            return "stable-browser-session"

        def check_login_state(self):
            self.calls += 1
            return {
                "ok": True,
                "action": "check_login_state",
                "stage": "login_success",
                "page_url": "https://www.dianxiaomi.com/web/home",
                "evidence": {},
                "contract_facts": {
                    "before_values": {"probe": "visible_browser"},
                    "after_values": {"authenticated": True, "loading": False},
                    "postconditions": {
                        "session_authenticated": True,
                        "business_page_ready": True,
                        "loading_absent": True,
                    },
                    "evidence_observations": {
                        "login_check": {"authenticated": True, "loading": False}
                    },
                    "failure_code": None,
                    "recoverability": {
                        "kind": "none",
                        "retryable": False,
                        "requires_page_reverify": False,
                        "reason": None,
                    },
                },
            }

    class RecordingRuntime(BrowserAgentRuntime):
        def __init__(self, adapter):
            super().__init__(adapter)
            self.submissions = []

        def run(self, command, *, timeout_seconds=None):
            self.submissions.append(command)
            return super().run(command, timeout_seconds=timeout_seconds)

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    adapter = Adapter()
    runtime = RecordingRuntime(adapter)
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )

    first = runner._run_workflow_action_browser_agent(
        task,
        job,
        StateName.PRECHECK_SESSION,
        "DXM-LOCK",
        {},
    )
    second = runner._run_workflow_action_browser_agent(
        task,
        job,
        StateName.PRECHECK_SESSION,
        "DXM-LOCK",
        {},
    )

    assert first["ok"] is True and second["ok"] is True
    assert runtime.submissions[0].command_id != runtime.submissions[1].command_id
    assert runtime.submissions[0].idempotency_key == runtime.submissions[1].idempotency_key
    assert adapter.calls == 1
    runtime.shutdown()


def test_v1_command_uses_one_runtime_id_snapshot_for_binding_and_idempotency(v1_db):
    class ResetBetweenReadsRuntime(FakeBrowserAgentRuntime):
        def __init__(self):
            super().__init__()
            self.runtime_reads = 0

        @property
        def runtime_id(self):
            self.runtime_reads += 1
            return "runtime-before-reset" if self.runtime_reads == 1 else "runtime-after-reset"

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = ResetBetweenReadsRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )

    runner._run_workflow_action_browser_agent(
        task,
        job,
        StateName.PRECHECK_SESSION,
        "DXM-LOCK",
        {},
    )

    command = runtime.commands[0][0]
    assert command.idempotency_key.startswith(f"v1:{command.runtime_id}:")
    assert runtime.runtime_reads == 1


def test_v1_runtime_reset_between_snapshot_and_reservation_fails_closed_without_execution(v1_db, monkeypatch):
    class Adapter:
        def __init__(self):
            self.calls = 0

        def check_login_state(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/home",
            }

        def close_browser_session(self):
            return None

    class ResetOnReserveRuntime(BrowserAgentRuntime):
        def __init__(self, adapter):
            super().__init__(adapter)
            self.did_reset = False

        def reserve_command(self, command):
            if not self.did_reset:
                self.did_reset = True
                self.reset(self.adapter)
            return super().reserve_command(command)

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    adapter = Adapter()
    runtime = ResetOnReserveRuntime(adapter)
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    with pytest.raises(V1ExecutionError, match="预留失败"):
        asyncio.run(
            runner._run_workflow_action_async(
                task,
                job,
                StateName.PRECHECK_SESSION,
                {},
            )
        )

    assert adapter.calls == 0
    assert runtime.status()["reservedCommandCount"] == 0
    runtime.shutdown()


def test_browser_agent_runtime_does_not_queue_live_hud_updates(v1_db, monkeypatch):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    adapter = FakeWorkflowAdapter()
    runtime = FakeBrowserAgentRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=33,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    event = runner._sync_live_browser_hud(
        task,
        job,
        "single_save",
        StateName.SAVE_ONLY,
        "保存商品",
        "semi_managed",
        "/artifacts/save.txt",
    )

    assert runtime.commands == []
    assert adapter.live_hud_calls == []
    assert event["updated"] is False
    assert event["reason"] == "live_browser_hud_deferred_to_browser_agent"
    assert event["last_step_code"] == "SAVE_ONLY"
    assert event["hud"]["state"] == "SAVE_ONLY"
    assert "保存" in event["hud"]["human_action"]
    assert "不发布" in event["hud"]["human_action"]


def test_live_hud_update_skips_unhealthy_browser_agent_runtime(v1_db, monkeypatch):
    class UnhealthyRuntime:
        def __init__(self):
            self.commands = []

        def status(self):
            return {
                "status": "needs_restart",
                "healthy": False,
                "lastError": "save_only timed out",
            }

        def run(self, command, *, timeout_seconds=None):
            self.commands.append((command, timeout_seconds))
            raise AssertionError("unhealthy Browser Agent must not receive HUD work")

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = UnhealthyRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=33,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    event = runner._sync_live_browser_hud(
        task,
        job,
        "single_save",
        StateName.SAVE_ONLY,
        "当前步骤失败",
        "semi_managed",
        "/artifacts/save.txt",
        hud_override={"step_code": "TASK_FAILED", "step_name": "当前步骤失败"},
    )

    assert runtime.commands == []
    assert event["updated"] is False
    assert event["reason"] == "live_browser_hud_runtime_unhealthy"
    assert event["last_error"] == "save_only timed out"
    assert event["last_step_code"] == "TASK_FAILED"


def test_browser_agent_timeout_detail_includes_last_internal_save_step(v1_db, monkeypatch):
    class TimeoutAtSaveRuntime(FakeBrowserAgentRuntime):
        def __init__(self):
            super().__init__()
            self.last_step = None

        def status(self):
            return {
                "status": "running",
                "healthy": True,
                "currentStep": self.last_step or "待启动",
                "lastWorkflowEvent": {
                    "event": "save_only:dispatch_start",
                    "human_step": self.last_step,
                } if self.last_step else None,
            }

        def run(self, command, *, timeout_seconds=None):
            if command.action == "save_only":
                self.commands.append((command, timeout_seconds))
                self.last_step = "点击保存"
                raise TimeoutError("Browser Agent command timed out: save_only")
            return super().run(command, timeout_seconds=timeout_seconds)

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    runtime = TimeoutAtSaveRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=33,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    asyncio.run(runner.run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    report = repo.list_reports(task["id"])[0]
    assert refreshed["status"] == "failed"
    assert "点击保存" in refreshed["jobs"][0]["error_message"]
    assert "点击保存" in report["summary"]["blocked_reason"]


def test_browser_agent_timeout_explicitly_cancels_the_same_command_identity(v1_db):
    class TimeoutRuntime:
        runtime_id = "runtime-timeout-cancel"

        def __init__(self):
            self.command = None
            self.cancelled = []

        def run(self, command, *, timeout_seconds=None):
            self.command = command
            raise TimeoutError("deadline")

        def cancel_command(self, command_id, runtime_id):
            self.cancelled.append((command_id, runtime_id))
            return {"ok": True}

        def status(self):
            return {
                "runtimeId": self.runtime_id,
                "status": "idle",
                "healthy": True,
                "active": False,
            }

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = TimeoutRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=0.01,
    )

    with pytest.raises(V1ExecutionError, match="超时"):
        runner._run_workflow_action_browser_agent(
            task,
            job,
            StateName.PRECHECK_SESSION,
            "DXM-LOCK",
            {},
        )

    assert runtime.cancelled == [
        (runtime.command.command_id, runtime.command.runtime_id),
    ]


def test_async_caller_cancellation_explicitly_cancels_browser_agent_command(v1_db, monkeypatch):
    class CancellableRuntime:
        runtime_id = "runtime-async-cancel"

        def __init__(self):
            self.started = threading.Event()
            self.release = threading.Event()
            self.command = None
            self.cancelled = []

        def run(self, command, *, timeout_seconds=None):
            self.command = command
            self.started.set()
            assert self.release.wait(timeout=2)
            return {
                "ok": True,
                "action": command.action,
                "stage": "session_check_complete",
                "page_url": "https://www.dianxiaomi.com/web/home",
                "evidence": {},
            }

        def cancel_command(self, command_id, runtime_id):
            self.cancelled.append((command_id, runtime_id))
            self.release.set()
            return {"ok": True}

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = CancellableRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    async def scenario():
        pending = asyncio.create_task(
            runner._run_workflow_action_async(
                task,
                job,
                StateName.PRECHECK_SESSION,
                {},
            )
        )
        assert await asyncio.to_thread(runtime.started.wait, 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(scenario())
    runtime.release.set()

    assert runtime.cancelled == [
        (runtime.command.command_id, runtime.command.runtime_id),
    ]


def test_async_cancel_before_executor_start_consumes_reservation_without_adapter_call(v1_db, monkeypatch):
    class Adapter:
        def __init__(self):
            self.calls = 0

        def check_login_state(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/home",
            }

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")
    blocker_started = threading.Event()
    release_blocker = threading.Event()

    async def scenario():
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)

        def occupy_executor():
            blocker_started.set()
            assert release_blocker.wait(timeout=2)

        blocker = loop.run_in_executor(None, occupy_executor)
        for _ in range(100):
            if blocker_started.is_set():
                break
            await asyncio.sleep(0.01)
        assert blocker_started.is_set()
        pending = asyncio.create_task(
            runner._run_workflow_action_async(
                task,
                job,
                StateName.PRECHECK_SESSION,
                {},
            )
        )
        for _ in range(100):
            if runtime.status()["reservedCommandCount"] == 1:
                break
            await asyncio.sleep(0.01)
        assert runtime.status()["reservedCommandCount"] == 1
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        release_blocker.set()
        await blocker
        for _ in range(100):
            if runtime.status()["reservedCommandCount"] == 0:
                break
            await asyncio.sleep(0.01)
        assert runtime.status()["reservedCommandCount"] == 0

    asyncio.run(scenario())

    assert adapter.calls == 0
    runtime.shutdown()


def test_browser_agent_runtime_setting_fails_closed_when_runtime_missing(v1_db, monkeypatch):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    adapter = FakeWorkflowAdapter()
    runner = _test_runner(repo, DummyManager(), workflow_adapter=adapter)
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    asyncio.run(runner.run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "自动浏览器" in reports[0]["summary"]["blocked_reason"]
    assert "不会保存或发布" in reports[0]["summary"]["blocked_reason"]
    assert adapter.calls == []


def test_real_dxm_adapter_fails_closed_when_persistent_runtime_is_missing_even_if_thread_requested(v1_db, monkeypatch):
    class FlowThatMustNotRun:
        def get_state(self):
            raise AssertionError("real DxmWorkflowAdapter must not run outside BrowserAgent")

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=DxmWorkflowAdapter(FlowThatMustNotRun()),
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "thread")

    asyncio.run(runner.run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "持久在线真实浏览器" in report["summary"]["blocked_reason"]


@pytest.mark.parametrize(
    "runtime_status",
    [
        {"runtimeId": "runtime-real-1", "status": "needs_restart", "healthy": False, "active": False},
        {"runtimeId": "runtime-wrong", "status": "idle", "healthy": True, "active": False},
    ],
)
def test_real_dxm_adapter_fails_closed_on_unhealthy_or_wrong_runtime_binding(
    v1_db,
    monkeypatch,
    runtime_status,
):
    class FlowThatMustNotRun:
        def get_state(self):
            raise AssertionError("real DxmWorkflowAdapter must not run with invalid BrowserAgent binding")

    class Runtime:
        runtime_id = "runtime-real-1"

        def status(self):
            return dict(runtime_status)

        def run(self, *_args, **_kwargs):
            raise AssertionError("invalid BrowserAgent runtime must not dispatch")

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=DxmWorkflowAdapter(FlowThatMustNotRun()),
        browser_agent_runtime=Runtime(),
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "process")

    asyncio.run(runner.run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "不会保存或发布" in report["summary"]["blocked_reason"]


def test_single_save_without_workflow_adapter_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()

    asyncio.run(_test_runner(repo, manager).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "workflow_adapter" in reports[0]["summary"]["blocked_reason"]


def test_batch_save_without_workflow_adapter_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="batch_save", product_count=1)
    manager = DummyManager()

    asyncio.run(_test_runner(repo, manager).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "workflow_adapter" in reports[0]["summary"]["blocked_reason"]


def test_legacy_batch_save_cannot_enter_the_single_save_browser_chain(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="batch_save", product_count=3)
    manager = DummyManager()

    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["completed_jobs"] == 0
    assert refreshed["failed_jobs"] == 1
    assert len(reports) == 1
    assert all(report["status"] == "failed" for report in reports)
    assert all(report["published"] is None for report in reports)
    assert all("单商品只保存" in report["summary"]["blocked_reason"] for report in reports)
    assert "save_only" not in [call[0] for call in adapter.calls]


def test_forbidden_publish_mode_fails_before_actions(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="publish", product_count=1)
    manager = DummyManager()

    asyncio.run(_test_runner(repo, manager).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    exceptions = repo.list_exceptions()
    assert refreshed["status"] == "failed"
    assert exceptions[0]["error_code"] == "E999"


def test_reports_table_exists_after_init(v1_db):
    with sqlite3.connect(v1_db) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reports'"
        ).fetchone()

    assert table == ("reports",)
