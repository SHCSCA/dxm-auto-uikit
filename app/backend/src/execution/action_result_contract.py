from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit


ACTION_RESULT_SCHEMA_VERSION = "dxm.action-result.v1"

_TOP_LEVEL_KEYS = frozenset(
    {
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
)
_EVIDENCE_KEYS = frozenset({"observations", "refs"})
_EVIDENCE_REF_KEYS = frozenset({"path", "sha256", "size", "kind", "captured_at"})
_PAGE_IDENTITY_KEYS = frozenset({"kind", "url", "runtime_id", "browser_session_id"})
_RECOVERABILITY_KEYS = frozenset({"kind", "retryable", "requires_page_reverify", "reason"})
_FAILURE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_SHA256_PATTERN = re.compile(r"^[0-9A-Fa-f]{64}$")
_RECOVERABILITY_KINDS = frozenset(
    {"none", "retry_same_page", "manual_takeover", "restart_runtime", "terminal"}
)
_IMMUTABLE_PROOF_STATES = frozenset(
    {"VERIFY_DRAFT_BOX_CLAIM", "SAVE_ONLY", "VERIFY_NOT_PUBLISHED"}
)
_PROOF_REF_KIND_BY_STATE = MappingProxyType(
    {
        "VERIFY_DRAFT_BOX_CLAIM": "draft_box_screenshot",
        "SAVE_ONLY": "save_screenshot",
        "VERIFY_NOT_PUBLISHED": "unpublished_screenshot",
    }
)
_NON_RETRYABLE_MUTATION_STATES = frozenset(
    {"CLAIM_TO_DRAFT_BOX", "CLAIM_PRODUCT", "SAVE_ONLY"}
)
_CONTROLLED_PAGE_PATHS = MappingProxyType(
    {
        "data_acquisition": "/web/productcrawl/dataacquisition",
        "draft_box": "/web/smt/smtproductlist/draft",
        "editor": "/web/smt/edit",
        "semi_managed": "/web/smt/editfromsmt",
    }
)


class ActionResultContractError(ValueError):
    """Raised when an action-result envelope cannot be trusted."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ActionResultContract:
    expected_page: str
    required_postconditions: frozenset[str]


def _contract(expected_page: str, *required_postconditions: str) -> ActionResultContract:
    return ActionResultContract(
        expected_page=expected_page,
        required_postconditions=frozenset(required_postconditions),
    )


ACTION_RESULT_CONTRACTS = MappingProxyType(
    {
        "check_login_state": MappingProxyType(
            {
                "PRECHECK_SESSION": _contract(
                    "authenticated_dxm",
                    "session_authenticated",
                    "business_page_ready",
                    "loading_absent",
                )
            }
        ),
        "open_data_acquisition": MappingProxyType(
            {
                "OPEN_DATA_ACQUISITION": _contract(
                    "data_acquisition",
                    "expected_page",
                    "business_marker_present",
                    "loading_absent",
                    "blocking_modal_absent",
                )
            }
        ),
        "claim_from_data_acquisition": MappingProxyType(
            {
                "CLAIM_TO_DRAFT_BOX": _contract(
                    "data_acquisition",
                    "target_unique",
                    "source_identity_match",
                    "store_selected_exact",
                    "category_selected_exact",
                    "claim_dispatched",
                    "publish_not_attempted",
                )
            }
        ),
        "verify_draft_box_claim": MappingProxyType(
            {
                "VERIFY_DRAFT_BOX_CLAIM": _contract(
                    "draft_box",
                    "draft_box_verified",
                    "target_unique",
                    "product_identity_match",
                    "store_match",
                    "source_identity_match",
                    "claim_mark_match",
                )
            }
        ),
        "open_draft_box": MappingProxyType(
            {
                "OPEN_DRAFT_LIST": _contract(
                    "draft_box",
                    "expected_page",
                    "business_marker_present",
                    "loading_absent",
                    "blocking_modal_absent",
                )
            }
        ),
        "claim_product": MappingProxyType(
            {
                "CLAIM_PRODUCT": _contract(
                    "draft_box",
                    "target_unique",
                    "note_write_attempted",
                    "note_readback_exact",
                    "ownership_binding_match",
                )
            }
        ),
        "open_editor": MappingProxyType(
            {
                "OPEN_EDIT_PAGE": _contract(
                    "editor",
                    "expected_editor_page",
                    "editor_ready",
                    "product_identity_match",
                    "store_match",
                    "source_identity_match",
                )
            }
        ),
        "verify_edit_ownership": MappingProxyType(
            {
                "VERIFY_EDIT_OWNERSHIP": _contract(
                    "editor",
                    "editor_identity_match",
                    "product_identity_match",
                    "store_match",
                    "source_identity_match",
                )
            }
        ),
        "fill_editor_required_defaults": MappingProxyType(
            {
                "FILL_BASE_INFO": _contract(
                    "editor",
                    "title_readback_nonempty",
                    "title_readback_exact",
                    "category_selected_exact",
                    "required_templates_resolved",
                    "required_fields_complete",
                )
            }
        ),
        "fill_editor_variants": MappingProxyType(
            {
                "FILL_VARIANTS": _contract(
                    "editor",
                    "variant_rows_present",
                    "sku_readback_exact",
                    "price_readback_exact",
                    "stock_readback_exact",
                    "all_required_cells_complete",
                )
            }
        ),
        "fill_media_assets": MappingProxyType(
            {
                "FILL_MEDIA": _contract(
                    "editor",
                    "main_images_present",
                    "required_assets_match",
                    "invalid_images_absent",
                    "marketing_assets_complete",
                )
            }
        ),
        "fill_compliance_defaults": MappingProxyType(
            {
                "FILL_COMPLIANCE": _contract(
                    "editor",
                    "required_compliance_complete",
                    "eu_responsible_readback_exact",
                    "manufacturer_readback_exact",
                    "customs_readback_exact",
                    "required_templates_applied",
                )
            }
        ),
        "enable_semi_managed": MappingProxyType(
            {
                "ENABLE_SEMI_MANAGED": _contract(
                    "editor",
                    "semi_managed_visible",
                    "semi_managed_enabled",
                    "toggle_readback_exact",
                    "publish_not_attempted",
                )
            }
        ),
        "open_semi_managed_page": MappingProxyType(
            {
                "OPEN_SEMI_MANAGED_PAGE": _contract(
                    "semi_managed",
                    "expected_semi_managed_page",
                    "business_marker_present",
                    "loading_absent",
                    "source_editor_identity_preserved",
                )
            }
        ),
        "fill_semi_managed_defaults": MappingProxyType(
            {
                "FILL_SEMI_GOODS": _contract(
                    "semi_managed",
                    "weight_readback_exact",
                    "dimensions_readback_exact",
                    "logistics_attribute_readback_exact",
                    "freight_template_readback_exact",
                    "service_template_readback_exact",
                    "required_goods_fields_complete",
                ),
                "FILL_SEMI_VARIANTS": _contract(
                    "semi_managed",
                    "variant_rows_present",
                    "product_price_readback_exact",
                    "supply_price_readback_exact",
                    "jit_stock_readback_exact",
                    "goods_code_readback_exact",
                    "required_variant_fields_complete",
                ),
            }
        ),
        "save_only": MappingProxyType(
            {
                "SAVE_ONLY": _contract(
                    "semi_managed",
                    "mutation_authorized",
                    "exact_save_target",
                    "save_click_dispatched",
                    "network_save_success",
                    "page_save_success",
                    "published_false",
                    "publish_action_not_clicked",
                )
            }
        ),
        "verify_not_published": MappingProxyType(
            {
                "VERIFY_NOT_PUBLISHED": _contract(
                    "semi_managed",
                    "independent_probe",
                    "product_identity_match",
                    "unpublished_verified",
                    "publish_status_absent_or_false",
                    "save_evidence_not_reused",
                )
            }
        ),
    }
)


def _reject(message: str) -> None:
    raise ActionResultContractError("ACTION_RESULT_CONTRACT_VIOLATION", message)


def _exact_mapping(value: Any, keys: frozenset[str], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _reject(f"{field} must be a mapping")
    result = dict(value)
    if frozenset(result) != keys:
        _reject(f"{field} must contain exactly {sorted(keys)}")
    return result


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _reject(f"{field} must be a non-empty string")
    return value.strip()


def _json_clone(value: Any) -> dict[str, Any]:
    try:
        return json.loads(
            json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ActionResultContractError(
            "ACTION_RESULT_CONTRACT_VIOLATION",
            "action result must be JSON serializable",
        ) from exc


def _validate_recoverability_types(recoverability: dict[str, Any]) -> None:
    kind = _non_empty_string(recoverability["kind"], "recoverability.kind")
    if kind not in _RECOVERABILITY_KINDS:
        _reject("recoverability.kind is unsupported")
    if type(recoverability["retryable"]) is not bool:
        _reject("recoverability.retryable must be a boolean")
    if type(recoverability["requires_page_reverify"]) is not bool:
        _reject("recoverability.requires_page_reverify must be a boolean")


def _validate_failure_recoverability(
    recoverability: dict[str, Any],
    *,
    state: str,
    contract: ActionResultContract,
    page_identity: dict[str, Any],
) -> None:
    kind = recoverability["kind"]
    if kind == "none":
        _reject("failed actions require a non-none recoverability kind")
    should_be_retryable = kind in {"retry_same_page", "restart_runtime"}
    if recoverability["retryable"] is not should_be_retryable:
        _reject("recoverability.retryable conflicts with recoverability.kind")
    _non_empty_string(recoverability["reason"], "recoverability.reason")
    if state in _NON_RETRYABLE_MUTATION_STATES and recoverability["retryable"]:
        _reject(f"{state} mutation failures must not be retried automatically")
    if should_be_retryable and recoverability["requires_page_reverify"] is not True:
        _reject("retryable failures require page re-verification")
    if kind == "retry_same_page":
        for field in _PAGE_IDENTITY_KEYS:
            _non_empty_string(page_identity[field], f"page_identity.{field}")
        if page_identity["kind"] != contract.expected_page or not _page_url_matches_identity(
            page_identity["url"], contract.expected_page
        ):
            _reject("retry_same_page requires the controlled DXM page identity")


def _validate_optional_page_identity(page_identity: dict[str, Any]) -> None:
    for field, value in page_identity.items():
        if value is not None:
            _non_empty_string(value, f"page_identity.{field}")
    if page_identity["url"] is not None:
        _validate_page_url(page_identity["url"])
    if page_identity["kind"] is not None and page_identity["url"] is not None:
        if not _page_url_matches_identity(page_identity["url"], page_identity["kind"]):
            _reject("page_identity must identify the controlled DXM page")


def _validate_page_url(value: Any) -> str:
    url = _non_empty_string(value, "page_identity.url")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        _reject("page_identity.url must be an absolute HTTP URL")
    return url


def _page_url_matches_identity(value: Any, expected_page: str) -> bool:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return False
    hostname = str(parsed.hostname or "").casefold()
    if hostname != "dianxiaomi.com" and not hostname.endswith(".dianxiaomi.com"):
        return False
    path = str(parsed.path or "").rstrip("/").casefold()
    if expected_page == "authenticated_dxm":
        return path.startswith("/web/") and "/login" not in path
    return path == _CONTROLLED_PAGE_PATHS.get(expected_page)


def _parse_captured_at(value: Any, field: str) -> datetime:
    captured_at = _non_empty_string(value, field)
    try:
        parsed_at = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError:
        _reject(f"{field} must be ISO-8601")
    if parsed_at.tzinfo is None:
        _reject(f"{field} must include a timezone")
    return parsed_at.astimezone(timezone.utc)


def _validate_evidence_refs(
    refs: list[Any],
    *,
    required: bool,
    required_kind: str | None = None,
) -> None:
    if required and not refs:
        _reject("successful proof actions require immutable evidence refs")
    for index, raw_ref in enumerate(refs):
        evidence_ref = _exact_mapping(
            raw_ref,
            _EVIDENCE_REF_KEYS,
            f"evidence.refs[{index}]",
        )
        _non_empty_string(evidence_ref["path"], f"evidence.refs[{index}].path")
        sha256 = _non_empty_string(
            evidence_ref["sha256"], f"evidence.refs[{index}].sha256"
        )
        if not _SHA256_PATTERN.fullmatch(sha256):
            _reject(f"evidence.refs[{index}].sha256 must be 64 hexadecimal characters")
        if type(evidence_ref["size"]) is not int or evidence_ref["size"] <= 0:
            _reject(f"evidence.refs[{index}].size must be a positive integer")
        kind = _non_empty_string(evidence_ref["kind"], f"evidence.refs[{index}].kind")
        if required_kind is not None and kind != required_kind:
            _reject(f"evidence.refs[{index}].kind must be {required_kind}")
        _parse_captured_at(
            evidence_ref["captured_at"], f"evidence.refs[{index}].captured_at"
        )


def _required_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        _reject(f"{field} must be a non-empty mapping")
    return dict(value)


def _required_positive_count(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        _reject(f"{field} must be a positive integer")
    return value


def _required_sha256(value: Any, field: str) -> str:
    digest = _non_empty_string(value, field)
    if not _SHA256_PATTERN.fullmatch(digest):
        _reject(f"{field} must be 64 hexadecimal characters")
    return digest.casefold()


def _canonical_mapping_sha256(value: Mapping[str, Any], field: str) -> str:
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _reject(f"{field} must be canonical JSON")
    return hashlib.sha256(encoded).hexdigest()


def _validate_integrity_snapshot(value: Any, field: str) -> dict[str, Any]:
    snapshot = _required_mapping(value, field)
    if snapshot.get("ok") is not True:
        _reject(f"{field}.ok must be true")
    if snapshot.get("kind") != "structured_nonempty_form_state":
        _reject(f"{field}.kind must identify structured non-empty form state")
    field_count = _required_positive_count(snapshot.get("field_count"), f"{field}.field_count")
    nonempty_count = _required_positive_count(
        snapshot.get("nonempty_field_count"), f"{field}.nonempty_field_count"
    )
    if field_count != nonempty_count:
        _reject(f"{field} must contain only non-empty captured fields")
    _required_sha256(snapshot.get("sha256"), f"{field}.sha256")
    return snapshot


def _validate_save_network_receipt(value: Any, field: str) -> dict[str, Any]:
    receipt = _required_mapping(value, field)
    if receipt.get("ok") is not True or receipt.get("receipt_complete") is not True:
        _reject(f"{field} must be a complete successful receipt")
    if type(receipt.get("receipt_count")) is not int or receipt.get("receipt_count") != 1:
        _reject(f"{field}.receipt_count must be exactly one")
    try:
        parsed = urlsplit(_non_empty_string(receipt.get("url"), f"{field}.url"))
    except ValueError:
        _reject(f"{field}.url must be a valid URL")
    hostname = str(parsed.hostname or "").casefold()
    if hostname != "dianxiaomi.com" and not hostname.endswith(".dianxiaomi.com"):
        _reject(f"{field}.url must use the controlled DXM origin")
    if str(parsed.path or "").casefold() not in {
        "/api/popchoiceproduct/add.json",
        "/api/smtproduct/add.json",
    }:
        _reject(f"{field}.url must be an exact supported SAVE endpoint")
    if str(receipt.get("method") or "").upper() != "POST":
        _reject(f"{field}.method must be POST")
    status = receipt.get("status")
    if type(status) is not int or not 200 <= status < 300:
        _reject(f"{field}.status must be a 2xx integer")
    if receipt.get("code") not in (0, "0"):
        _reject(f"{field}.code must be zero")
    message = _non_empty_string(
        receipt.get("message") or receipt.get("msg"), f"{field}.message"
    )
    if not any(term in message for term in ("保存成功", "编辑保存成功", "编辑成功")):
        _reject(f"{field}.message must contain a structured SAVE success term")
    return receipt


def _validate_save_success_semantics(envelope: Mapping[str, Any]) -> None:
    before = dict(envelope["before_values"])
    after = dict(envelope["after_values"])
    observations = dict(envelope["evidence"]["observations"])
    save = _required_mapping(observations.get("save_result"), "evidence.observations.save_result")

    if save.get("ok") is not True or save.get("published") is not False:
        _reject("SAVE success requires save_result ok=true and published=false")
    if save.get("exact_save_target") is not True:
        _reject("SAVE success requires an exact SAVE target")
    if save.get("save_click_dispatched") is not True or save.get("clicked") is not True:
        _reject("SAVE success requires one dispatched SAVE click")
    if save.get("publish_action_clicked") is not False:
        _reject("SAVE success requires publish_action_clicked=false")
    if str(save.get("text") or "") != "保存" or save.get("exact_save_count") != 1:
        _reject("SAVE success requires exactly one visible button labelled 保存")
    if save.get("click_method") not in {"native_exact_save", "dom_exact_save"}:
        _reject("SAVE success requires an approved exact-save click method")

    authorization = _required_mapping(
        save.get("mutation_authorization"), "save_result.mutation_authorization"
    )
    if (
        authorization.get("ok") is not True
        or authorization.get("executed") is not True
        or authorization.get("mutation_action") != "save_only_click"
        or authorization.get("mutation_status") != "DISPATCHED"
    ):
        _reject("SAVE success requires the exact consumed mutation authorization")
    _non_empty_string(
        authorization.get("mutation_id"), "save_result.mutation_authorization.mutation_id"
    )

    pre_dispatch = _required_mapping(
        save.get("pre_dispatch_readback"), "save_result.pre_dispatch_readback"
    )
    if (
        pre_dispatch.get("ok") is not True
        or pre_dispatch.get("required_readback_complete") is not True
        or pre_dispatch.get("write_attempted") is not False
        or pre_dispatch.get("phase") != "before_ledger_begin_dispatch"
    ):
        _reject("SAVE success requires a complete zero-write pre-dispatch readback")
    identity = _required_mapping(
        pre_dispatch.get("identity"), "save_result.pre_dispatch_readback.identity"
    )
    if any(
        identity.get(key) is not True
        for key in (
            "ok",
            "product_identity_match",
            "store_identity_match",
            "source_identity_match",
        )
    ):
        _reject("SAVE success requires exact product, store, and source identity")
    frozen_target = _required_mapping(
        before.get("target_identity"), "before_values.target_identity"
    )
    if identity.get("target_identity") != frozen_target:
        _reject("SAVE pre-dispatch identity must equal the frozen command target")
    expected_store = " ".join(str(before.get("store_name") or "").split())
    if not expected_store or " ".join(str(identity.get("expected_store_name") or "").split()) != expected_store:
        _reject("SAVE pre-dispatch store must equal the frozen command store")
    identity_digest = _required_sha256(
        identity.get("target_identity_sha256"),
        "save_result.pre_dispatch_readback.identity.target_identity_sha256",
    )
    if identity_digest != _canonical_mapping_sha256(
        frozen_target, "before_values.target_identity"
    ):
        _reject("SAVE pre-dispatch target digest must match the frozen command target")
    baseline = _validate_integrity_snapshot(
        pre_dispatch.get("baseline_field_integrity"),
        "save_result.pre_dispatch_readback.baseline_field_integrity",
    )
    current = _validate_integrity_snapshot(
        pre_dispatch.get("current_field_integrity"),
        "save_result.pre_dispatch_readback.current_field_integrity",
    )
    for key in ("kind", "field_count", "nonempty_field_count", "sha256"):
        if baseline.get(key) != current.get(key):
            _reject("SAVE form state changed after required-field readback")

    network = _validate_save_network_receipt(
        save.get("network_save_result"), "save_result.network_save_result"
    )
    audit = _required_mapping(save.get("network_audit"), "save_result.network_audit")
    if (
        audit.get("complete") is not True
        or audit.get("window_closed") is not True
        or type(audit.get("registered_listener_count")) is not int
        or audit.get("registered_listener_count") != 2
        or type(audit.get("removed_listener_count")) is not int
        or audit.get("removed_listener_count") != 2
        or type(audit.get("mutation_request_count")) is not int
        or audit.get("mutation_request_count") != 1
        or type(audit.get("save_request_count")) is not int
        or audit.get("save_request_count") != 1
        or type(audit.get("other_mutation_request_count")) is not int
        or audit.get("other_mutation_request_count") != 0
        or type(audit.get("publish_request_count")) is not int
        or audit.get("publish_request_count") != 0
    ):
        _reject("SAVE success requires one exact SAVE request and a closed zero-publish audit")
    publish_signal = _required_mapping(
        save.get("publish_signal"), "save_result.publish_signal"
    )
    if (
        publish_signal.get("detected") is not False
        or publish_signal.get("kind") != "network_route_classification"
    ):
        _reject("SAVE success requires an explicit zero-publish network classification")

    page = _required_mapping(save.get("page_save_result"), "save_result.page_save_result")
    transition = _required_mapping(
        page.get("status_transition"), "save_result.page_save_result.status_transition"
    )
    if (
        page.get("ok") is not True
        or transition.get("kind") != "new_or_changed_structured_save_status"
        or not isinstance(transition.get("entry"), Mapping)
        or not transition.get("entry")
    ):
        _reject("SAVE success requires a new or changed structured page status")
    _non_empty_string(page.get("success_text"), "save_result.page_save_result.success_text")
    decision = _required_mapping(save.get("save_decision"), "save_result.save_decision")
    if decision != {
        "ok": True,
        "rule": "page_success_and_network_success",
        "page_ok": True,
        "network_ok": True,
        "network_receipt_ok": True,
        "network_audit_ok": True,
    }:
        _reject("SAVE decision must bind page, receipt, and network audit success")
    if save.get("network_save_success") is not True or save.get("page_save_success") is not True:
        _reject("SAVE result must preserve both independent success signals")

    exact_target = _required_mapping(
        observations.get("exact_save_target"), "evidence.observations.exact_save_target"
    )
    if exact_target != {
        "text": "保存",
        "exact_save_count": 1,
        "click_method": save.get("click_method"),
    }:
        _reject("SAVE observations must preserve the exact click target")
    if observations.get("save_click_dispatched") is not True:
        _reject("SAVE observations must preserve click dispatch")
    for key, expected in (
        ("mutation_authorization", authorization),
        ("pre_dispatch_readback", pre_dispatch),
        ("network_save_result", network),
        ("network_audit", audit),
        ("publish_signal", publish_signal),
        ("page_save_result", page),
    ):
        if observations.get(key) != expected or after.get(key) != expected:
            _reject(f"SAVE {key} facts must agree across result, evidence, and readback")
    if after.get("exact_save_target") is not True or after.get("save_click_dispatched") is not True:
        _reject("SAVE after_values must preserve the exact dispatched target")
    if after.get("published") is not False:
        _reject("SAVE after_values.published must be false")


def _validate_unpublished_success_semantics(envelope: Mapping[str, Any]) -> None:
    after = dict(envelope["after_values"])
    observations = dict(envelope["evidence"]["observations"])
    proof = _required_mapping(
        observations.get("fresh_probe"), "evidence.observations.fresh_probe"
    )
    status = "".join(str(proof.get("status_text") or proof.get("publish_status") or "").split())
    if (
        proof.get("ok") is not True
        or proof.get("published") is not False
        or proof.get("proof_kind") != "structured_unpublished_status"
        or status not in {"待发布", "草稿", "未发布", "待完善"}
        or proof.get("verified_on_current_page") is not True
        or proof.get("status_scope_unique") is not True
        or type(proof.get("bound_candidate_count")) is not int
        or proof.get("bound_candidate_count") != 1
        or type(proof.get("structured_candidate_count")) is not int
        or proof.get("structured_candidate_count") != 1
        or proof.get("target_bound") is not True
        or proof.get("product_matched") is not True
        or proof.get("store_matched") is not True
        or proof.get("source_identity_match") is not True
        or proof.get("identity_binding_kind")
        != "frozen_target_structured_page_readback"
        or proof.get("publish_risk_term") not in (None, "")
    ):
        _reject("VERIFY_NOT_PUBLISHED requires one target-bound structured unpublished row")
    _required_sha256(
        proof.get("target_identity_sha256"), "fresh_probe.target_identity_sha256"
    )
    if not _page_url_matches_identity(proof.get("page_url"), "semi_managed"):
        _reject("VERIFY_NOT_PUBLISHED proof must come from the controlled semi-managed page")
    identity = _required_mapping(proof.get("identity_readback"), "fresh_probe.identity_readback")
    if any(
        identity.get(key) is not True
        for key in (
            "product_identity_match",
            "store_identity_match",
            "source_identity_match",
        )
    ):
        _reject("VERIFY_NOT_PUBLISHED requires exact product, store, and source readback")
    observed_target = _required_mapping(
        observations.get("target_identity"), "evidence.observations.target_identity"
    )
    if any(
        observed_target.get(key) is not True
        for key in (
            "product_matched",
            "store_matched",
            "source_identity_match",
            "target_bound",
        )
    ):
        _reject("VERIFY_NOT_PUBLISHED target observation must be exact")
    observed_target_digest = _required_sha256(
        observed_target.get("target_identity_sha256"),
        "evidence.observations.target_identity.target_identity_sha256",
    )
    if observed_target_digest != _required_sha256(
        proof.get("target_identity_sha256"), "fresh_probe.target_identity_sha256"
    ):
        _reject("VERIFY_NOT_PUBLISHED target observation digest must match the fresh probe")
    if observations.get("identity_readback") != identity:
        _reject("VERIFY_NOT_PUBLISHED identity observations disagree")
    if after.get("fresh_probe") != proof:
        _reject("VERIFY_NOT_PUBLISHED readback must preserve the fresh probe")
    if after.get("target_identity") != observed_target or after.get("identity_readback") != identity:
        _reject("VERIFY_NOT_PUBLISHED after_values must preserve target identity")
    if after.get("published") is not False:
        _reject("VERIFY_NOT_PUBLISHED after_values.published must be false")


def _validate_success_evidence_semantics(
    envelope: Mapping[str, Any], *, state: str
) -> None:
    if state == "SAVE_ONLY":
        _validate_save_success_semantics(envelope)
    elif state == "VERIFY_NOT_PUBLISHED":
        _validate_unpublished_success_semantics(envelope)


def validate_action_result_envelope(
    value: Mapping[str, Any],
    *,
    expected_state: str | None = None,
    expected_action: str | None = None,
    expected_runtime_id: str | None = None,
    expected_browser_session_id: str | None = None,
) -> dict[str, Any]:
    """Validate and clone a producer action result without inferring missing facts."""

    envelope = _exact_mapping(value, _TOP_LEVEL_KEYS, "action result")
    if envelope["schema_version"] != ACTION_RESULT_SCHEMA_VERSION:
        _reject(f"schema_version must be {ACTION_RESULT_SCHEMA_VERSION}")
    if type(envelope["ok"]) is not bool:
        _reject("ok must be a boolean")

    action = _non_empty_string(envelope["action"], "action")
    state = _non_empty_string(envelope["attempted_state"], "attempted_state")
    if expected_action is not None and action != expected_action:
        _reject("action does not match the command")
    if expected_state is not None and state != expected_state:
        _reject("attempted_state does not match the command")

    state_contracts = ACTION_RESULT_CONTRACTS.get(action)
    contract = state_contracts.get(state) if state_contracts is not None else None
    if contract is None:
        _reject(f"unsupported state/action pair: {state}/{action}")

    for field in ("before_values", "after_values", "postconditions"):
        if not isinstance(envelope[field], Mapping):
            _reject(f"{field} must be a mapping")

    evidence = _exact_mapping(envelope["evidence"], _EVIDENCE_KEYS, "evidence")
    if not isinstance(evidence["observations"], Mapping):
        _reject("evidence.observations must be a mapping")
    if not isinstance(evidence["refs"], list):
        _reject("evidence.refs must be a list")

    page_identity = _exact_mapping(
        envelope["page_identity"], _PAGE_IDENTITY_KEYS, "page_identity"
    )
    recoverability = _exact_mapping(
        envelope["recoverability"], _RECOVERABILITY_KEYS, "recoverability"
    )
    _validate_recoverability_types(recoverability)

    postconditions = dict(envelope["postconditions"])
    if any(type(condition_value) is not bool for condition_value in postconditions.values()):
        _reject("postcondition values must be booleans")
    _validate_evidence_refs(
        evidence["refs"],
        required=envelope["ok"] is True and state in _IMMUTABLE_PROOF_STATES,
        required_kind=(
            _PROOF_REF_KIND_BY_STATE.get(state)
            if envelope["ok"] is True
            else None
        ),
    )

    if expected_runtime_id is not None and page_identity["runtime_id"] != expected_runtime_id:
        _reject("page_identity.runtime_id does not match the authoritative runtime")
    if (
        expected_browser_session_id is not None
        and page_identity["browser_session_id"] != expected_browser_session_id
    ):
        _reject("page_identity.browser_session_id does not match the authoritative session")

    if envelope["ok"] is False:
        failure_code = envelope["failure_code"]
        if not isinstance(failure_code, str) or not _FAILURE_CODE_PATTERN.fullmatch(failure_code):
            _reject("failed actions require a stable failure_code")
        _validate_failure_recoverability(
            recoverability,
            state=state,
            contract=contract,
            page_identity=page_identity,
        )
        _validate_optional_page_identity(page_identity)
        return _json_clone(envelope)

    if not envelope["before_values"] or not envelope["after_values"]:
        _reject("successful actions require non-empty before_values and after_values")
    if not evidence["observations"]:
        _reject("successful actions require non-empty evidence observations")

    missing = contract.required_postconditions - postconditions.keys()
    if missing:
        _reject(f"missing required postconditions: {sorted(missing)}")
    if any(condition_value is not True for condition_value in postconditions.values()):
        _reject("successful action postconditions must all be true")

    if _non_empty_string(page_identity["kind"], "page_identity.kind") != contract.expected_page:
        _reject("page_identity.kind does not match the action contract")
    _validate_page_url(page_identity["url"])
    if not _page_url_matches_identity(page_identity["url"], contract.expected_page):
        _reject("page_identity must identify the controlled DXM page")
    _non_empty_string(page_identity["runtime_id"], "page_identity.runtime_id")
    _non_empty_string(
        page_identity["browser_session_id"], "page_identity.browser_session_id"
    )
    if envelope["failure_code"] is not None:
        _reject("successful actions require failure_code to be null")
    if recoverability != {
        "kind": "none",
        "retryable": False,
        "requires_page_reverify": False,
        "reason": None,
    }:
        _reject("successful actions require recoverability kind=none")

    _validate_success_evidence_semantics(envelope, state=state)

    return _json_clone(envelope)


def validate_independent_save_verification_pair(
    save_value: Mapping[str, Any],
    verification_value: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Validate that unpublished proof is target-bound and captured after SAVE."""

    save = validate_action_result_envelope(
        save_value,
        expected_state="SAVE_ONLY",
        expected_action="save_only",
    )
    verification = validate_action_result_envelope(
        verification_value,
        expected_state="VERIFY_NOT_PUBLISHED",
        expected_action="verify_not_published",
    )

    save_target = save["before_values"].get("target_identity")
    verification_target = verification["before_values"].get("target_identity")
    if save_target is None or verification_target is None or save_target != verification_target:
        _reject("SAVE and VERIFY_NOT_PUBLISHED target identity must match")
    for identity_field in ("runtime_id", "browser_session_id"):
        if save["page_identity"][identity_field] != verification["page_identity"][identity_field]:
            _reject(
                f"SAVE and VERIFY_NOT_PUBLISHED page_identity.{identity_field} must match"
            )

    save_observations = save["evidence"]["observations"]
    verification_observations = verification["evidence"]["observations"]
    save_pre_dispatch = _required_mapping(
        save_observations.get("pre_dispatch_readback"),
        "SAVE evidence.observations.pre_dispatch_readback",
    )
    save_identity = _required_mapping(
        save_pre_dispatch.get("identity"),
        "SAVE evidence.observations.pre_dispatch_readback.identity",
    )
    verification_probe = _required_mapping(
        verification_observations.get("fresh_probe"),
        "VERIFY_NOT_PUBLISHED evidence.observations.fresh_probe",
    )
    save_target_digest = _required_sha256(
        save_identity.get("target_identity_sha256"),
        "SAVE target_identity_sha256",
    )
    verification_target_digest = _required_sha256(
        verification_probe.get("target_identity_sha256"),
        "VERIFY_NOT_PUBLISHED target_identity_sha256",
    )
    if save_target_digest != verification_target_digest:
        _reject("SAVE and VERIFY_NOT_PUBLISHED target identity digests must match")

    save_refs = save["evidence"]["refs"]
    verification_refs = verification["evidence"]["refs"]
    save_paths = {
        str(item["path"]).replace("\\", "/").casefold()
        for item in save_refs
    }
    verification_paths = {
        str(item["path"]).replace("\\", "/").casefold()
        for item in verification_refs
    }
    if save_paths & verification_paths:
        _reject("VERIFY_NOT_PUBLISHED must not reuse SAVE evidence paths")

    latest_save_capture = max(
        _parse_captured_at(item["captured_at"], "SAVE evidence captured_at")
        for item in save_refs
    )
    earliest_verification_capture = min(
        _parse_captured_at(
            item["captured_at"], "VERIFY_NOT_PUBLISHED evidence captured_at"
        )
        for item in verification_refs
    )
    if earliest_verification_capture <= latest_save_capture:
        _reject("VERIFY_NOT_PUBLISHED evidence must be captured after SAVE evidence")

    return {"save": save, "verification": verification}
