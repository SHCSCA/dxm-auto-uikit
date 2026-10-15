from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from tests.support.network_receipts import complete_save_receipt

_PAGE_URLS = {
    "authenticated_dxm": "https://www.dianxiaomi.com/web/index.htm",
    "draft_box": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
    "editor": "https://www.dianxiaomi.com/web/smt/edit",
    "semi_managed": "https://www.dianxiaomi.com/web/smt/editFromSmt",
}
def _valid_navigation_result() -> dict:
    return {
        "schema_version": "dxm.action-result.v1",
        "ok": True,
        "action": "open_draft_box",
        "attempted_state": "OPEN_DRAFT_LIST",
        "before_values": {"page_url": "https://www.dianxiaomi.com/web/product/index.htm"},
        "after_values": {"page_url": _PAGE_URLS["draft_box"]},
        "postconditions": {
            "expected_page": True,
            "business_marker_present": True,
            "loading_absent": True,
            "blocking_modal_absent": True,
        },
        "evidence": {
            "observations": {"business_marker": "速卖通商品箱"},
            "refs": [],
        },
        "page_identity": {
            "kind": "draft_box",
            "url": _PAGE_URLS["draft_box"],
            "runtime_id": "runtime-1",
            "browser_session_id": "browser-session-1",
        },
        "failure_code": None,
        "recoverability": {
            "kind": "none",
            "retryable": False,
            "requires_page_reverify": False,
            "reason": None,
        },
    }


def _immutable_ref(
    kind: str = "screenshot",
    *,
    path: str = "D:/evidence/proof.png",
    sha256: str = "A" * 64,
    captured_at: str = "2026-07-15T08:00:00+08:00",
) -> dict:
    return {
        "path": path,
        "sha256": sha256,
        "size": 128,
        "kind": kind,
        "captured_at": captured_at,
    }


def _valid_save_result() -> dict:
    target_identity = {
        "product_query": "product-1",
        "store_name": "DXM Shop A",
        "source_url": "https://detail.1688.com/offer/1013604102950.html",
    }
    target_identity_sha256 = hashlib.sha256(
        json.dumps(
            target_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    authorization = {
        "ok": True,
        "executed": True,
        "mutation_action": "save_only_click",
        "mutation_status": "DISPATCHED",
        "mutation_id": "mutation-save-1",
    }
    integrity = {
        "ok": True,
        "kind": "structured_nonempty_form_state",
        "field_count": 2,
        "nonempty_field_count": 2,
        "sha256": "C" * 64,
    }
    pre_dispatch = {
        "ok": True,
        "required_readback_complete": True,
        "write_attempted": False,
        "phase": "before_ledger_begin_dispatch",
        "exact_save_target": {
            "ok": True,
            "text": "保存",
            "exact_save_count": 1,
        },
        "identity": {
            "ok": True,
            "product_identity_match": True,
            "store_identity_match": True,
            "source_identity_match": True,
            "target_identity": target_identity,
            "expected_store_name": "DXM Shop A",
            "target_identity_sha256": target_identity_sha256,
        },
        "baseline_field_integrity": integrity,
        "current_field_integrity": deepcopy(integrity),
    }
    network = {
        "ok": True,
        "receipt_complete": True,
        "receipt_count": 1,
        "url": "https://www.dianxiaomi.com/api/smtProduct/add.json",
        "method": "POST",
        "status": 200,
        "code": 0,
        "message": "编辑保存成功",
    }
    network = complete_save_receipt(network)
    audit = {
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
    page = {
        "ok": True,
        "success_text": "保存成功",
        "status_transition": {
            "kind": "new_or_changed_structured_save_status",
            "entry": {"text": "保存成功", "status": "success"},
        },
    }
    field_readbacks = [{"field_key": "weight", "field_label": "包装重量",
        "source": "exact_control_readback", "before_value": "10", "after_value": "10",
        "readback_proven": True, "timestamp": "2026-07-15T08:00:00+08:00"}]
    save = {
        "ok": True,
        "published": False,
        "exact_save_target": True,
        "save_click_dispatched": True,
        "clicked": True,
        "publish_action_clicked": False,
        "text": "保存",
        "exact_save_count": 1,
        "click_method": "playwright_exact_role",
        "mutation_authorization": authorization,
        "pre_dispatch_readback": pre_dispatch,
        "network_save_result": network,
        "network_audit": audit,
        "publish_signal": publish_signal,
        "page_save_result": page,
        "save_decision": {
            "ok": True,
            "rule": "page_success_and_network_success",
            "page_ok": True,
            "network_ok": True,
            "network_receipt_ok": True,
            "network_audit_ok": True,
        },
        "network_save_success": True,
        "page_save_success": True,
        "save_field_readbacks": field_readbacks,
    }
    value = _valid_navigation_result()
    value.update(
        {
            "action": "save_only",
            "attempted_state": "SAVE_ONLY",
            "before_values": {
                "target_identity": target_identity,
                "store_name": "DXM Shop A",
                "authorization_fingerprint": "authorization-1",
            },
            "after_values": {
                "exact_save_target": True,
                "save_click_dispatched": True,
                "published": False,
                "mutation_authorization": authorization,
                "pre_dispatch_readback": pre_dispatch,
                "network_save_result": network,
                "network_audit": audit,
                "publish_signal": publish_signal,
                "page_save_result": page,
            },
            "postconditions": {
                "mutation_authorized": True,
                "exact_save_target": True,
                "save_click_dispatched": True,
                "network_save_success": True,
                "page_save_success": True,
                "published_false": True,
                "publish_action_not_clicked": True,
            },
            "evidence": {
                "observations": {
                    "save_result": save,
                    "save_field_readbacks": field_readbacks,
                    "exact_save_target": {
                        "text": "保存",
                        "exact_save_count": 1,
                        "click_method": "playwright_exact_role",
                    },
                    "save_click_dispatched": True,
                    "mutation_authorization": authorization,
                    "pre_dispatch_readback": pre_dispatch,
                    "network_save_result": network,
                    "network_audit": audit,
                    "publish_signal": publish_signal,
                    "page_save_result": page,
                },
                "refs": [_immutable_ref("save_screenshot")],
            },
            "page_identity": {
                "kind": "semi_managed",
                "url": _PAGE_URLS["semi_managed"],
                "runtime_id": "runtime-1",
                "browser_session_id": "browser-session-1",
            },
        }
    )
    return value



def _valid_unpublished_result() -> dict:
    value = _valid_save_result()
    target_identity = deepcopy(value["before_values"]["target_identity"])
    target_identity_sha256 = value["evidence"]["observations"]["pre_dispatch_readback"]["identity"]["target_identity_sha256"]
    identity_readback = {
        "product_identity_match": True,
        "store_identity_match": True,
        "source_identity_match": True,
    }
    fresh_probe = {
        "ok": True,
        "published": False,
        "proof_kind": "structured_unpublished_status",
        "status_text": "草稿",
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
        "target_identity_sha256": target_identity_sha256,
        "page_url": _PAGE_URLS["semi_managed"],
        "identity_readback": identity_readback,
    }
    target_observation = {
        "product_matched": True,
        "store_matched": True,
        "source_identity_match": True,
        "target_bound": True,
        "target_identity_sha256": target_identity_sha256,
    }
    value.update(
        {
            "action": "verify_not_published",
            "attempted_state": "VERIFY_NOT_PUBLISHED",
            "before_values": {
                "target_identity": target_identity,
                "save_evidence_fingerprint": "save-proof-1",
            },
            "after_values": {
                "published": False,
                "fresh_probe": fresh_probe,
                "target_identity": target_observation,
                "identity_readback": identity_readback,
            },
            "postconditions": {
                "independent_probe": True,
                "product_identity_match": True,
                "unpublished_verified": True,
                "publish_status_absent_or_false": True,
                "save_evidence_not_reused": True,
            },
            "evidence": {
                "observations": {
                    "fresh_probe": fresh_probe,
                    "target_identity": target_observation,
                    "identity_readback": identity_readback,
                },
                "refs": [
                    _immutable_ref(
                        "unpublished_screenshot",
                        path="D:/evidence/unpublished-proof.png",
                        sha256="B" * 64,
                        captured_at="2026-07-15T08:00:01+08:00",
                    )
                ],
            },
        }
    )
    return value



def _path_a_execution_payload() -> dict:
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
        "price_validation": {"ok": True},
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {**body, "payload_hash": hashlib.sha256(encoded).hexdigest().upper()}


def _as_path_a_editor(value: dict, execution_payload: dict | None = None) -> dict:
    result = deepcopy(value)
    result["page_identity"]["kind"] = "editor"
    result["page_identity"]["url"] = _PAGE_URLS["editor"]
    if result["attempted_state"] == "SAVE_ONLY":
        execution_payload = execution_payload or _path_a_execution_payload()
        value_hash = hashlib.sha256(b'"10"').hexdigest().upper()
        category_schema_readback = {
            "schema": "dxm.editor.category_schema_readback.v1",
            "ok": True,
            "phase": "before_ledger_begin_dispatch",
            "expected_category_id": execution_payload["category_id"],
            "observed_category_id": execution_payload["category_id"],
            "expected_category_schema_hash": execution_payload[
                "category_schema_hash"
            ],
            "observed_category_schema_hash": execution_payload[
                "category_schema_hash"
            ],
            "category_source": "same_origin_attribute_schema",
            "reason": None,
        }
        frozen_readback = {
            "schema": "dxm.frozen_execution.readback.v1",
            "ok": True,
            "phase": "before_ledger_begin_dispatch",
            "execution_payload_hash": execution_payload["payload_hash"],
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
        for container in (
            result["after_values"],
            result["evidence"]["observations"],
            result["evidence"]["observations"]["save_result"],
        ):
            container["pre_dispatch_readback"][
                "category_schema_readback"
            ] = deepcopy(category_schema_readback)
            container["pre_dispatch_readback"][
                "frozen_execution_readback"
            ] = deepcopy(frozen_readback)
        result["evidence"]["observations"]["save_result"]["network_audit"][
            "read_only_schema_request_count"
        ] = 1
    if result["attempted_state"] == "VERIFY_NOT_PUBLISHED":
        result["after_values"]["fresh_probe"]["page_url"] = _PAGE_URLS["editor"]
        result["evidence"]["observations"]["fresh_probe"]["page_url"] = _PAGE_URLS[
            "editor"
        ]
    return result


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _bind_batch_save_verification_context(
    save: dict,
    verification: dict,
    execution_payload: dict,
) -> dict:
    body = {
        "schema": "dxm.batch_draft_save.save_verification.v1",
        "task_id": 11,
        "job_id": 22,
        "execution_mode": "batch_draft_save",
        "plan_snapshot_id": 33,
        "plan_snapshot_hash": "1" * 64,
        "queue_epoch": "2" * 64,
        "queue_version": "3" * 64,
        "runtime_id": save["page_identity"]["runtime_id"],
        "browser_session_id": save["page_identity"]["browser_session_id"],
        "git_head": "4" * 40,
        "worktree_identity_sha256": "5" * 64,
        "authorization_fingerprint": "6" * 64,
        "authorization_lease_id": "contract-test-lease",
        "stage_task_facts_fingerprint": "7" * 64,
        "target_hash": "8" * 64,
        "execution_payload_hash": execution_payload["payload_hash"],
        "mutation_scope_id": "9" * 64,
        "save_command_id": "contract-test-save-command",
        "save_command_sha256": "A" * 64,
        "save_action_result_sha256": _canonical_sha256(save),
    }
    context = {**body, "context_sha256": _canonical_sha256(body)}
    verification["before_values"]["save_verification_context"] = deepcopy(context)
    for container in (
        verification["after_values"]["fresh_probe"],
        verification["evidence"]["observations"]["fresh_probe"],
    ):
        container["save_verification_context"] = deepcopy(context)
    return context


