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

from src.execution.batch_command_contract import (
    BatchCommandContractError,
    validate_frozen_execution_readback as validate_expected_frozen_execution_readback,
    validate_save_verification_context,
)
from src.execution.browser_agent_protocol import (
    MutationCommandContractError,
    mutation_target_hash,
)


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
_CATEGORY_SCHEMA_READBACK_KEYS = frozenset(
    {
        "schema",
        "ok",
        "phase",
        "expected_category_id",
        "observed_category_id",
        "expected_category_schema_hash",
        "observed_category_schema_hash",
        "category_source",
        "reason",
    }
)
_FAILURE_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_SHA256_PATTERN = re.compile(r"^[0-9A-Fa-f]{64}$")
_RECOVERABILITY_KINDS = frozenset(
    {"none", "retry_same_page", "manual_takeover", "restart_runtime", "terminal"}
)
_IMMUTABLE_PROOF_STATES = frozenset(
    {
        "SAVE_ONLY",
        "SAVE2_ONLY",
        "FIRST_SAVE_INTENT",
        "VERIFY_NOT_PUBLISHED",
        "VERIFY_SAVE1_NOT_PUBLISHED",
        "VERIFY_SAVE2_NOT_PUBLISHED",
        "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED",
    }
)
_PROOF_REF_KIND_BY_STATE = MappingProxyType(
    {
        "SAVE_ONLY": "save_screenshot",
        "SAVE2_ONLY": "save_screenshot",
        "FIRST_SAVE_INTENT": "save_screenshot",
        "VERIFY_NOT_PUBLISHED": "unpublished_screenshot",
        "VERIFY_SAVE1_NOT_PUBLISHED": "unpublished_screenshot",
        "VERIFY_SAVE2_NOT_PUBLISHED": "unpublished_screenshot",
        "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED": "unpublished_screenshot",
    }
)
_NON_RETRYABLE_MUTATION_STATES = frozenset(
    {"SAVE_ONLY", "SAVE2_ONLY", "FIRST_SAVE_INTENT"}
)
_CONTROLLED_PAGE_PATHS = MappingProxyType(
    {
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
    allowed_pages: frozenset[str]
    page_by_execution_mode: Mapping[str, str]

    def page_for_execution_mode(self, execution_mode: str) -> str | None:
        if not self.page_by_execution_mode:
            return self.expected_page
        return self.page_by_execution_mode.get(str(execution_mode or "").strip())


def _contract(
    expected_page: str,
    *required_postconditions: str,
    additional_pages: frozenset[str] = frozenset(),
    page_by_execution_mode: Mapping[str, str] | None = None,
) -> ActionResultContract:
    mode_pages = dict(page_by_execution_mode or {})
    return ActionResultContract(
        expected_page=expected_page,
        required_postconditions=frozenset(required_postconditions),
        allowed_pages=frozenset(
            {expected_page, *additional_pages, *mode_pages.values()}
        ),
        page_by_execution_mode=MappingProxyType(mode_pages),
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
                "SAVE_INTENT_MODAL": _contract(
                    "semi_managed",
                    "expected_semi_managed_page",
                    "business_marker_present",
                    "loading_absent",
                    "source_editor_identity_preserved",
                    "save1_intent_observed",
                    "same_handshake",
                    "publish_not_attempted",
                ),
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
                    page_by_execution_mode={
                        "single_save": "semi_managed",
                        "batch_draft_save": "editor",
                    },
                ),
                "SAVE2_ONLY": _contract(
                    "semi_managed",
                    "mutation_authorized",
                    "exact_save_target",
                    "save_click_dispatched",
                    "network_save_success",
                    "page_save_success",
                    "published_false",
                    "publish_action_not_clicked",
                    page_by_execution_mode={
                        "batch_draft_save": "semi_managed",
                    },
                ),
            }
        ),
        "first_save_intent": MappingProxyType(
            {
                "FIRST_SAVE_INTENT": _contract(
                    "semi_managed",
                    "mutation_authorized",
                    "first_save_intent_observed",
                    "exactly_one_save_request",
                    "network_save_success",
                    "open_semi_managed_editor_observed",
                    "same_handshake",
                    "source_editor_identity_preserved",
                    "published_false",
                    "publish_action_not_clicked",
                    page_by_execution_mode={"batch_draft_save": "semi_managed"},
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
                    page_by_execution_mode={
                        "single_save": "semi_managed",
                        "batch_draft_save": "editor",
                    },
                ),
                "VERIFY_SAVE1_NOT_PUBLISHED": _contract(
                    "editor",
                    "independent_probe",
                    "product_identity_match",
                    "unpublished_verified",
                    "publish_status_absent_or_false",
                    "save_evidence_not_reused",
                    page_by_execution_mode={"batch_draft_save": "editor"},
                ),
                "VERIFY_SAVE2_NOT_PUBLISHED": _contract(
                    "semi_managed",
                    "independent_probe",
                    "product_identity_match",
                    "unpublished_verified",
                    "publish_status_absent_or_false",
                    "save_evidence_not_reused",
                    page_by_execution_mode={"batch_draft_save": "semi_managed"},
                ),
                "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED": _contract(
                    "semi_managed",
                    "independent_probe",
                    "product_identity_match",
                    "unpublished_verified",
                    "publish_status_absent_or_false",
                    "save_evidence_not_reused",
                    page_by_execution_mode={"batch_draft_save": "semi_managed"},
                ),
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
    expected_page: str,
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
        if page_identity["kind"] != expected_page or not _page_url_matches_identity(
            page_identity["url"], expected_page
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
    if controlled_dxm_page_identity(url) is None:
        _reject(
            "page_identity.url must be an absolute HTTP URL for the controlled DXM page "
            "using HTTPS on www.dianxiaomi.com with the default port"
        )
    return url


def controlled_dxm_page_identity(value: Any) -> str | None:
    """Return the exact controlled page kind for the production DXM origin."""

    try:
        parsed = urlsplit(str(value or "").strip())
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.casefold() != "https"
        or str(parsed.hostname or "").casefold() != "www.dianxiaomi.com"
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    path = str(parsed.path or "").rstrip("/").casefold()
    if path.startswith("/web/") and "/login" not in path:
        for page_kind, controlled_path in _CONTROLLED_PAGE_PATHS.items():
            if path == controlled_path:
                return page_kind
        return "authenticated_dxm"
    return None


def _page_url_matches_identity(value: Any, expected_page: str) -> bool:
    observed = controlled_dxm_page_identity(value)
    if expected_page == "authenticated_dxm":
        return observed is not None
    return observed == expected_page


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


def _validate_batch_category_schema_readback(
    value: Any,
    *,
    expected_execution_payload: Mapping[str, Any],
) -> dict[str, Any]:
    field = "save_result.pre_dispatch_readback.category_schema_readback"
    readback = _exact_mapping(value, _CATEGORY_SCHEMA_READBACK_KEYS, field)
    if (
        readback.get("schema") != "dxm.editor.category_schema_readback.v1"
        or readback.get("ok") is not True
        or readback.get("phase") != "before_ledger_begin_dispatch"
        or readback.get("reason") is not None
    ):
        _reject("SAVE success requires an exact current category_schema_readback")
    expected_category_id = _non_empty_string(
        expected_execution_payload.get("category_id"),
        "expected_execution_payload.category_id",
    )
    if any(
        readback.get(key) != expected_category_id
        for key in ("expected_category_id", "observed_category_id")
    ):
        _reject(
            "SAVE category_schema_readback must match the frozen execution payload"
        )
    expected_schema_hash = _required_sha256(
        expected_execution_payload.get("category_schema_hash"),
        "expected_execution_payload.category_schema_hash",
    )
    if any(
        _required_sha256(readback.get(key), f"{field}.{key}")
        != expected_schema_hash
        for key in (
            "expected_category_schema_hash",
            "observed_category_schema_hash",
        )
    ):
        _reject(
            "SAVE category_schema_readback must match the frozen execution payload"
        )
    _non_empty_string(readback.get("category_source"), f"{field}.category_source")
    return readback


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
    request_body_sha256 = _required_sha256(
        receipt.get("request_body_sha256"), f"{field}.request_body_sha256"
    )
    response_body_sha256 = _required_sha256(
        receipt.get("response_body_sha256"), f"{field}.response_body_sha256"
    )
    request_at = _parse_captured_at(
        receipt.get("request_observed_at"), f"{field}.request_observed_at"
    )
    response_at = _parse_captured_at(
        receipt.get("response_observed_at"), f"{field}.response_observed_at"
    )
    if response_at < request_at:
        _reject(f"{field} response observation must not precede its request")
    request_evidence_id = _non_empty_string(
        receipt.get("request_evidence_id"), f"{field}.request_evidence_id"
    )
    response_evidence_id = _non_empty_string(
        receipt.get("response_evidence_id"), f"{field}.response_evidence_id"
    )
    if request_evidence_id == response_evidence_id:
        _reject(f"{field} request and response evidence identities must differ")
    expected_request_evidence_id = (
        "dxm-network-request:"
        + _canonical_mapping_sha256(
            {
                "kind": "request",
                "url": receipt.get("url"),
                "method": receipt.get("method"),
                "body_sha256": request_body_sha256,
                "observed_at": receipt.get("request_observed_at"),
            },
            f"{field}.request_evidence_identity",
        )
    )
    expected_response_evidence_id = (
        "dxm-network-response:"
        + _canonical_mapping_sha256(
            {
                "kind": "response",
                "url": receipt.get("url"),
                "method": receipt.get("method"),
                "status": receipt.get("status"),
                "body_sha256": response_body_sha256,
                "observed_at": receipt.get("response_observed_at"),
            },
            f"{field}.response_evidence_identity",
        )
    )
    if (
        request_evidence_id != expected_request_evidence_id
        or response_evidence_id != expected_response_evidence_id
    ):
        _reject(f"{field} evidence identities do not bind the captured bodies")
    return receipt


def _validate_canonical_save_field_readbacks(value: Any, field: str) -> list[dict[str, Any]]:
    expected_keys = {
        "field_key",
        "field_label",
        "source",
        "before_value",
        "after_value",
        "readback_proven",
        "timestamp",
    }
    if not isinstance(value, list) or not value:
        _reject(f"{field} must contain at least one post-SAVE field readback")
    seen: set[str] = set()
    readbacks: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping) or set(raw) != expected_keys:
            _reject(f"{field}[{index}] has an unsupported shape")
        item = dict(raw)
        field_key = _non_empty_string(item.get("field_key"), f"{field}[{index}].field_key")
        _non_empty_string(item.get("field_label"), f"{field}[{index}].field_label")
        _non_empty_string(item.get("source"), f"{field}[{index}].source")
        _parse_captured_at(item.get("timestamp"), f"{field}[{index}].timestamp")
        if item.get("readback_proven") is not True or field_key in seen:
            _reject(f"{field}[{index}] is unproven or duplicated")
        try:
            json.dumps(
                {
                    "before_value": item.get("before_value"),
                    "after_value": item.get("after_value"),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError):
            _reject(f"{field}[{index}] values are not canonical JSON")
        seen.add(field_key)
        readbacks.append(item)
    return readbacks


def _validate_save_success_semantics(
    envelope: Mapping[str, Any],
    *,
    execution_mode: str | None = None,
    expected_execution_payload: Mapping[str, Any] | None = None,
) -> None:
    before = dict(envelope["before_values"])
    after = dict(envelope["after_values"])
    observations = dict(envelope["evidence"]["observations"])
    attempted_state = str(envelope.get("attempted_state") or "")
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
    if save.get("click_method") != "playwright_exact_role":
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
    pre_dispatch_target = _required_mapping(
        pre_dispatch.get("exact_save_target"),
        "save_result.pre_dispatch_readback.exact_save_target",
    )
    if (
        pre_dispatch_target.get("ok") is not True
        or pre_dispatch_target.get("text") != "保存"
        or pre_dispatch_target.get("exact_save_count") != 1
    ):
        _reject("SAVE success requires the unique exact SAVE target to be rebound before ledger dispatch")
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
    if execution_mode == "batch_draft_save" and attempted_state == "SAVE2_ONLY":
        if not isinstance(expected_execution_payload, Mapping):
            _reject("batch SAVE2 requires the exact frozen execution payload authority")
        if (
            pre_dispatch.get("page_kind") != "semi_managed"
            or pre_dispatch.get("category_schema_readback") is not None
            or pre_dispatch.get("frozen_execution_readback") is not None
        ):
            _reject("SAVE2 must use a semi-managed pre-dispatch readback")
    elif execution_mode == "batch_draft_save":
        if not isinstance(expected_execution_payload, Mapping):
            _reject("batch SAVE requires the exact frozen execution payload")
        _validate_batch_category_schema_readback(
            pre_dispatch.get("category_schema_readback"),
            expected_execution_payload=expected_execution_payload,
        )
        try:
            validate_expected_frozen_execution_readback(
                pre_dispatch.get("frozen_execution_readback"),
                expected_payload=expected_execution_payload,
            )
        except BatchCommandContractError as exc:
            _reject(f"{exc.reason_code}: {exc}")

    network = _validate_save_network_receipt(
        save.get("network_save_result"), "save_result.network_save_result"
    )
    audit = _required_mapping(save.get("network_audit"), "save_result.network_audit")
    if (
        audit.get("scope") != "same_origin_write_window"
        or audit.get("complete") is not True
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
        or type(audit.get("read_only_schema_request_count")) is not int
        or audit.get("read_only_schema_request_count") < 0
        or type(audit.get("publish_request_count")) is not int
        or audit.get("publish_request_count") != 0
    ):
        _reject("SAVE success requires one exact SAVE request and a closed zero-publish audit")
    if (
        execution_mode == "batch_draft_save"
        and attempted_state != "SAVE2_ONLY"
        and audit.get("read_only_schema_request_count") < 1
    ):
        _reject("batch SAVE success requires at least one live read-only Schema request")
    publish_signal = _required_mapping(
        save.get("publish_signal"), "save_result.publish_signal"
    )
    if (
        publish_signal.get("detected") is not False
        or publish_signal.get("kind") != "network_route_classification"
        or type(publish_signal.get("request_count")) is not int
        or publish_signal.get("request_count") != 0
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
    readbacks = _validate_canonical_save_field_readbacks(
        observations.get("save_field_readbacks"),
        "evidence.observations.save_field_readbacks",
    )
    if after.get("save_field_readbacks") not in (None, readbacks):
        _reject("SAVE field readbacks disagree across evidence and after_values")


def _validate_first_save_intent_success_semantics(
    envelope: Mapping[str, Any],
    *,
    execution_mode: str | None,
    expected_execution_payload: Mapping[str, Any] | None,
) -> None:
    """Validate one native SAVE1 intent -> semi-managed transition handshake.

    The producer must capture the entire causal chain in one canonical object.
    A ready modal, an unbound navigation, or a second write-capable command is
    never accepted as a substitute for the post-dispatch page identity.
    """

    if execution_mode != "batch_draft_save":
        _reject("FIRST_SAVE_INTENT is only valid for batch_draft_save")
    if not isinstance(expected_execution_payload, Mapping):
        _reject("FIRST_SAVE_INTENT requires the exact frozen execution payload")
    before = dict(envelope["before_values"])
    after = dict(envelope["after_values"])
    observations = dict(envelope["evidence"]["observations"])
    handshake = _required_mapping(
        observations.get("first_save_intent_handshake"),
        "evidence.observations.first_save_intent_handshake",
    )
    required_keys = frozenset(
        {
            "schema_version",
            "save_stage",
            "handshake_id",
            "handshake_sha256",
            "pre_dispatch_page",
            "post_dispatch_page",
            "first_save_intent",
            "open_semi_managed_editor",
            "mutation_authorization",
            "pre_dispatch_readback",
            "network_save_result",
            "network_audit",
            "publish_signal",
            "page_transition",
            "physical_mutation_count",
            "publish_request_count",
            "same_handshake",
        }
    )
    if frozenset(handshake) != required_keys:
        _reject("FIRST_SAVE_INTENT handshake has an unsupported shape")
    if (
        handshake.get("schema_version") != "dxm.first-save-intent-handshake.v1"
        or handshake.get("save_stage") != "SAVE1"
        or type(handshake.get("physical_mutation_count")) is not int
        or handshake.get("physical_mutation_count") != 1
        or type(handshake.get("publish_request_count")) is not int
        or handshake.get("publish_request_count") != 0
        or handshake.get("same_handshake") is not True
    ):
        _reject("FIRST_SAVE_INTENT handshake counters or stage are invalid")
    handshake_id = _non_empty_string(
        handshake.get("handshake_id"), "first_save_intent.handshake_id"
    )
    frozen_hash = _required_sha256(
        handshake.get("handshake_sha256"), "first_save_intent.handshake_sha256"
    )
    recomputed_hash = _canonical_mapping_sha256(
        {key: value for key, value in handshake.items() if key != "handshake_sha256"},
        "first_save_intent_handshake",
    )
    if frozen_hash != recomputed_hash:
        _reject("FIRST_SAVE_INTENT handshake hash cannot be reproduced")

    frozen_target = _required_mapping(before.get("target_identity"), "before_values.target_identity")
    expected_target_sha = _canonical_mapping_sha256(
        frozen_target, "before_values.target_identity"
    )
    pre_page = _required_mapping(
        handshake.get("pre_dispatch_page"), "first_save_intent.pre_dispatch_page"
    )
    post_page = _required_mapping(
        handshake.get("post_dispatch_page"), "first_save_intent.post_dispatch_page"
    )
    for page, kind, field in (
        (pre_page, "editor", "pre_dispatch_page"),
        (post_page, "semi_managed", "post_dispatch_page"),
    ):
        if page.get("kind") != kind or not _page_url_matches_identity(page.get("url"), kind):
            _reject(f"FIRST_SAVE_INTENT {field} must identify {kind}")
        if _required_sha256(
            page.get("target_identity_sha256"),
            f"first_save_intent.{field}.target_identity_sha256",
        ) != expected_target_sha:
            _reject(f"FIRST_SAVE_INTENT {field} target identity drifted")

    intent = _required_mapping(
        handshake.get("first_save_intent"), "first_save_intent.first_save_intent"
    )
    opened = _required_mapping(
        handshake.get("open_semi_managed_editor"),
        "first_save_intent.open_semi_managed_editor",
    )
    if set(intent) != {"observed", "handshake_id", "event_id", "observed_at"}:
        _reject("FIRST_SAVE_INTENT intent observation has an unsupported shape")
    if set(opened) != {
        "observed",
        "handshake_id",
        "event_id",
        "observed_at",
        "field_readbacks",
    }:
        _reject("FIRST_SAVE_INTENT open observation has an unsupported shape")
    save_field_readbacks = _validate_canonical_save_field_readbacks(
        opened.get("field_readbacks"),
        "first_save_intent.open_semi_managed_editor.field_readbacks",
    )
    if intent.get("observed") is not True or opened.get("observed") is not True:
        _reject("FIRST_SAVE_INTENT requires both native intent and opened editor observations")
    if (
        intent.get("handshake_id") != handshake_id
        or opened.get("handshake_id") != handshake_id
    ):
        _reject("FIRST_SAVE_INTENT observations must bind the same handshake_id")
    intent_event = _non_empty_string(intent.get("event_id"), "first_save_intent.event_id")
    opened_event = _non_empty_string(
        opened.get("event_id"), "open_semi_managed_editor.event_id"
    )
    if intent_event == opened_event:
        _reject("FIRST_SAVE_INTENT requires distinct ordered intent/open observations")
    intent_at = _parse_captured_at(intent.get("observed_at"), "first_save_intent.observed_at")
    opened_at = _parse_captured_at(
        opened.get("observed_at"), "open_semi_managed_editor.observed_at"
    )
    if opened_at <= intent_at:
        _reject("OPEN_SEMI_MANAGED_EDITOR must follow FIRST_SAVE_INTENT")

    authorization = _required_mapping(
        handshake.get("mutation_authorization"),
        "first_save_intent.mutation_authorization",
    )
    if (
        authorization.get("ok") is not True
        or authorization.get("executed") is not True
        or authorization.get("mutation_action") != "first_save_intent"
        or authorization.get("mutation_status") != "DISPATCHED"
    ):
        _reject("FIRST_SAVE_INTENT requires its exact consumed mutation authorization")
    _non_empty_string(
        authorization.get("mutation_id"), "first_save_intent.mutation_authorization.mutation_id"
    )

    pre_dispatch = _required_mapping(
        handshake.get("pre_dispatch_readback"),
        "first_save_intent.pre_dispatch_readback",
    )
    if (
        pre_dispatch.get("ok") is not True
        or pre_dispatch.get("required_readback_complete") is not True
        or pre_dispatch.get("write_attempted") is not False
        or pre_dispatch.get("phase") != "before_ledger_begin_dispatch"
        or pre_dispatch.get("page_kind") != "editor"
    ):
        _reject("FIRST_SAVE_INTENT requires a complete editor pre-dispatch readback")
    try:
        validate_expected_frozen_execution_readback(
            pre_dispatch.get("frozen_execution_readback"),
            expected_payload=expected_execution_payload,
        )
    except BatchCommandContractError as exc:
        _reject(f"{exc.reason_code}: {exc}")

    network = _validate_save_network_receipt(
        handshake.get("network_save_result"),
        "first_save_intent.network_save_result",
    )
    network_response_at = _parse_captured_at(
        network.get("response_observed_at"),
        "first_save_intent.network_save_result.response_observed_at",
    )
    if network_response_at > opened_at:
        _reject("FIRST_SAVE_INTENT semi-managed page opened before the SAVE response")
    for index, readback in enumerate(save_field_readbacks):
        readback_at = _parse_captured_at(
            readback.get("timestamp"),
            f"first_save_intent.field_readbacks[{index}].timestamp",
        )
        if not network_response_at <= readback_at < opened_at:
            _reject("FIRST_SAVE_INTENT field readback is outside the SAVE/open window")
    audit = _required_mapping(
        handshake.get("network_audit"), "first_save_intent.network_audit"
    )
    if (
        audit.get("scope") != "same_origin_write_window"
        or audit.get("complete") is not True
        or audit.get("window_closed") is not True
        or type(audit.get("mutation_request_count")) is not int
        or audit.get("mutation_request_count") != 1
        or type(audit.get("save_request_count")) is not int
        or audit.get("save_request_count") != 1
        or type(audit.get("other_mutation_request_count")) is not int
        or audit.get("other_mutation_request_count") != 0
        or type(audit.get("publish_request_count")) is not int
        or audit.get("publish_request_count") != 0
    ):
        _reject("FIRST_SAVE_INTENT requires exactly one SAVE and zero other writes")
    publish_signal = _required_mapping(
        handshake.get("publish_signal"), "first_save_intent.publish_signal"
    )
    if (
        publish_signal.get("detected") is not False
        or publish_signal.get("kind") != "network_route_classification"
        or type(publish_signal.get("request_count")) is not int
        or publish_signal.get("request_count") != 0
    ):
        _reject("FIRST_SAVE_INTENT publish isolation is not proven")
    transition = _required_mapping(
        handshake.get("page_transition"), "first_save_intent.page_transition"
    )
    if transition != {
        "from": "editor",
        "to": "semi_managed",
        "same_browser_session": True,
        "source_editor_identity_preserved": True,
    }:
        _reject("FIRST_SAVE_INTENT post-dispatch page transition is not exact")

    compatibility_handshake = {
        "gate_outcome": "admitted",
        "semi_entry_triggered": True,
        "same_handshake": True,
        "handshake_id": handshake["handshake_id"],
        "save1_verified": True,
        "exactly_one_save_request": True,
    }
    if observations.get("save_result") != handshake:
        _reject("FIRST_SAVE_INTENT save_result must preserve the canonical handshake")
    if observations.get("save_intent_handshake") != compatibility_handshake:
        _reject("FIRST_SAVE_INTENT runner handshake facts disagree")
    if observations.get("save_field_readbacks") != save_field_readbacks:
        _reject("FIRST_SAVE_INTENT field readbacks must preserve the hashed handshake")

    for key, expected in (
        ("first_save_intent_handshake", handshake),
        ("mutation_authorization", authorization),
        ("network_save_result", network),
        ("network_audit", audit),
        ("publish_signal", publish_signal),
    ):
        if observations.get(key) != expected or after.get(key) != expected:
            _reject(f"FIRST_SAVE_INTENT {key} facts disagree")
    if after.get("published") is not False:
        _reject("FIRST_SAVE_INTENT after_values.published must be false")
    if after.get("save_field_readbacks") != save_field_readbacks:
        _reject("FIRST_SAVE_INTENT after_values field readbacks disagree")
    refs = envelope["evidence"]["refs"]
    if len(refs) != 1:
        _reject("FIRST_SAVE_INTENT requires one post-transition screenshot")
    screenshot_at = _parse_captured_at(
        refs[0].get("captured_at"), "first_save_intent.screenshot.captured_at"
    )
    if screenshot_at <= opened_at:
        _reject("FIRST_SAVE_INTENT screenshot must follow the semi-managed observation")


def _validate_expected_save_target_binding(
    envelope: Mapping[str, Any],
    *,
    expected_target_identity: Mapping[str, Any],
    expected_store_name: str,
    expected_target_hash: str,
    command_action: str = "save_only",
) -> None:
    """Bind canonical SAVE evidence to the exact frozen command target."""

    target = _required_mapping(
        expected_target_identity,
        "expected_target_identity",
    )
    store_name = _non_empty_string(expected_store_name, "expected_store_name")
    target_hash = _required_sha256(expected_target_hash, "expected_target_hash")
    before = dict(envelope["before_values"])
    if (
        before.get("target_identity") != target
        or before.get("store_name") != store_name
    ):
        _reject("SAVE result target identity/store differs from the frozen command")
    try:
        reproduced_target_hash = mutation_target_hash(
            command_action,
            {
                "store_name": store_name,
                "target_identity": target,
                "target_source_urls": target.get("source_urls"),
            },
        )
    except MutationCommandContractError:
        _reject("SAVE frozen command target is invalid")
    if reproduced_target_hash.casefold() != target_hash:
        _reject("SAVE result target hash differs from the frozen command")


def _validate_unpublished_success_semantics(
    envelope: Mapping[str, Any],
    *,
    state: str,
    expected_page: str,
) -> None:
    before = dict(envelope["before_values"])
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
    if not _page_url_matches_identity(proof.get("page_url"), expected_page):
        _reject("VERIFY_NOT_PUBLISHED proof must come from the commanded controlled page")
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
    predecessor_locations = (
        before.get("save_predecessor"),
        observations.get("save_predecessor"),
        proof.get("save_predecessor"),
        after.get("save_predecessor"),
        after.get("fresh_probe", {}).get("save_predecessor")
        if isinstance(after.get("fresh_probe"), Mapping)
        else None,
    )
    if state == "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED":
        expected_predecessor = {
            "state": "FIRST_SAVE_INTENT",
            "action": "first_save_intent",
        }
        if any(value != expected_predecessor for value in predecessor_locations):
            _reject("Discovery VERIFY is not bound to its FIRST_SAVE_INTENT predecessor")
    elif any(value is not None for value in predecessor_locations):
        _reject("save_predecessor is reserved for Discovery VERIFY")


def _validate_success_evidence_semantics(
    envelope: Mapping[str, Any],
    *,
    state: str,
    expected_page: str,
    execution_mode: str | None = None,
    expected_execution_payload: Mapping[str, Any] | None = None,
) -> None:
    if state in {"SAVE_ONLY", "SAVE2_ONLY"}:
        _validate_save_success_semantics(
            envelope,
            execution_mode=execution_mode,
            expected_execution_payload=expected_execution_payload,
        )
    elif state == "FIRST_SAVE_INTENT":
        _validate_first_save_intent_success_semantics(
            envelope,
            execution_mode=execution_mode,
            expected_execution_payload=expected_execution_payload,
        )
    elif state in {
        "VERIFY_NOT_PUBLISHED",
        "VERIFY_SAVE1_NOT_PUBLISHED",
        "VERIFY_SAVE2_NOT_PUBLISHED",
        "VERIFY_DISCOVERY_SAVE1_NOT_PUBLISHED",
    }:
        _validate_unpublished_success_semantics(
            envelope,
            state=state,
            expected_page=expected_page,
        )


def validate_action_result_envelope(
    value: Mapping[str, Any],
    *,
    expected_state: str | None = None,
    expected_action: str | None = None,
    expected_page: str | None = None,
    execution_mode: str | None = None,
    expected_runtime_id: str | None = None,
    expected_browser_session_id: str | None = None,
    expected_execution_payload: Mapping[str, Any] | None = None,
    expected_target_identity: Mapping[str, Any] | None = None,
    expected_store_name: str | None = None,
    expected_target_hash: str | None = None,
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
    mode_page = (
        contract.page_for_execution_mode(execution_mode)
        if execution_mode is not None
        else None
    )
    if execution_mode is not None and mode_page is None:
        _reject("execution_mode is not allowed for the state/action contract")
    if expected_page is not None and mode_page is not None and expected_page != mode_page:
        _reject("expected_page conflicts with the execution_mode page contract")
    commanded_page = mode_page or expected_page or contract.expected_page
    if commanded_page not in contract.allowed_pages:
        _reject("expected_page is not allowed for the state/action contract")

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
            expected_page=commanded_page,
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

    if _non_empty_string(page_identity["kind"], "page_identity.kind") != commanded_page:
        _reject("page_identity.kind does not match the action contract")
    _validate_page_url(page_identity["url"])
    if not _page_url_matches_identity(page_identity["url"], commanded_page):
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

    _validate_success_evidence_semantics(
        envelope,
        state=state,
        expected_page=commanded_page,
        execution_mode=execution_mode,
        expected_execution_payload=expected_execution_payload,
    )

    expected_target_values = (
        expected_target_identity,
        expected_store_name,
        expected_target_hash,
    )
    if any(value is not None for value in expected_target_values):
        if not (
            isinstance(expected_target_identity, Mapping)
            and isinstance(expected_store_name, str)
            and isinstance(expected_target_hash, str)
        ):
            _reject("SAVE expected target binding must be complete")
        if (state, action) not in {
            ("SAVE_ONLY", "save_only"),
            ("SAVE2_ONLY", "save_only"),
            ("FIRST_SAVE_INTENT", "first_save_intent"),
        }:
            _reject("expected SAVE target binding is invalid for this action")
        _validate_expected_save_target_binding(
            envelope,
            expected_target_identity=expected_target_identity,
            expected_store_name=expected_store_name,
            expected_target_hash=expected_target_hash,
            command_action=action,
        )

    return _json_clone(envelope)


def validate_independent_save_verification_pair(
    save_value: Mapping[str, Any],
    verification_value: Mapping[str, Any],
    *,
    expected_page: str | None = None,
    execution_mode: str | None = None,
    expected_execution_payload: Mapping[str, Any] | None = None,
    expected_verification_context: Mapping[str, Any] | None = None,
    expected_save_command: Mapping[str, Any] | None = None,
    expected_save_state: str = "SAVE_ONLY",
    expected_verification_state: str = "VERIFY_NOT_PUBLISHED",
) -> dict[str, dict[str, Any]]:
    """Validate that unpublished proof is target-bound and captured after SAVE."""

    save = validate_action_result_envelope(
        save_value,
        expected_state=expected_save_state,
        expected_action="save_only",
        expected_page=expected_page,
        execution_mode=execution_mode,
        expected_execution_payload=expected_execution_payload,
    )
    verification = validate_action_result_envelope(
        verification_value,
        expected_state=expected_verification_state,
        expected_action="verify_not_published",
        expected_page=expected_page,
        execution_mode=execution_mode,
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

    if execution_mode == "batch_draft_save":
        if not isinstance(expected_verification_context, Mapping):
            _reject(
                "batch VERIFY_NOT_PUBLISHED requires the exact preceding SAVE context"
            )
        try:
            verified_context = validate_save_verification_context(
                expected_verification_context,
                save_command=expected_save_command,
                save_action_result=save,
                structural_only=True,
            )
        except BatchCommandContractError as exc:
            _reject(f"{exc.reason_code}: {exc}")
        reported_before_context = verification["before_values"].get(
            "save_verification_context"
        )
        reported_probe_context = verification_probe.get(
            "save_verification_context"
        )
        if (
            reported_before_context != verified_context
            or reported_probe_context != verified_context
            or verified_context["browser_session_id"]
            != save["page_identity"]["browser_session_id"]
            or verified_context["browser_session_id"]
            != verification["page_identity"]["browser_session_id"]
        ):
            _reject(
                "VERIFY_NOT_PUBLISHED is not bound to the exact preceding SAVE context"
            )

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
