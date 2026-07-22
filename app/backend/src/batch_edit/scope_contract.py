from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from src.execution.browser_agent_protocol import (
    MutationCommandContractError,
    canonical_frozen_target_identity,
)
from src.state_machine.two_stage import (
    TwoStageContractError,
    canonical_source_identity,
    is_supported_product_detail_url,
)


RAW_SCOPE_SCHEMA = "dxm_draft_box_scope_capture.v1"
SCOPE_SCHEMA = "dxm_draft_box_scope.v1"
TARGET_SCHEMA = "dxm_draft_box_target.v1"


class ScopeContractError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


def canonical_sha256(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ScopeContractError("SCOPE_NOT_CANONICAL", "scope facts are not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest().upper()


def normalize_scope_capture(
    capture: Any,
    *,
    requested_max_items: int,
    runtime_context: dict[str, Any],
    expected_browser_session_id: str,
) -> dict[str, Any]:
    if (
        isinstance(requested_max_items, bool)
        or not isinstance(requested_max_items, int)
        or not 1 <= requested_max_items <= 100
    ):
        _reject("SCOPE_ITEMS_INVALID", "requested_max_items must be an integer in 1..100")
    raw = _exact_object(
        capture,
        {
            "schema",
            "ok",
            "stage",
            "reason_code",
            "message",
            "captured_at",
            "browser_session_id",
            "page",
            "facts",
            "items",
            "evidence",
            "zero_write_proof",
        },
        "scope capture",
    )
    if raw["schema"] != RAW_SCOPE_SCHEMA:
        _reject("SCOPE_SCHEMA_INVALID", "unsupported scope capture schema")
    if raw["ok"] is not True:
        reason_code = _non_empty_text(raw.get("reason_code"), "reason_code")
        message = _non_empty_text(raw.get("message"), "message")
        _reject(reason_code, message)
    if raw["stage"] != "draft_box_scope_captured" or raw["reason_code"] != "OK":
        _reject("SCOPE_CAPTURE_STATUS_INVALID", "scope capture does not report a successful read")

    captured_at = _timestamp(raw["captured_at"])
    browser_session_id = _non_empty_text(raw["browser_session_id"], "browser_session_id")
    if browser_session_id != _non_empty_text(expected_browser_session_id, "current browser session"):
        _reject("SCOPE_SESSION_DRIFT", "browser session changed while the scope was captured")

    page = _exact_object(
        raw["page"],
        {"kind", "url", "title", "ready", "business_marker"},
        "page",
    )
    page_url = _draft_box_url(page["url"])
    if page["kind"] != "draft_box" or page["ready"] is not True:
        _reject("SCOPE_PAGE_INVALID", "capture must be bound to the ready draft-box page")
    _non_empty_text(page["title"], "page.title")
    _non_empty_text(page["business_marker"], "page.business_marker")

    facts = _exact_object(raw["facts"], {"filter", "sort", "pagination", "runtime"}, "facts")
    filter_state = _object(facts["filter"], "facts.filter")
    sort_state = _object(facts["sort"], "facts.sort")
    if sort_state.get("dom_order_authoritative") is not True:
        _reject("SCOPE_ORDER_NOT_AUTHORITATIVE", "DOM order is not authoritative")
    pagination = _exact_object(
        facts["pagination"],
        {
            "current_page",
            "page_size",
            "total_items",
            "visible_row_count",
            "captured_count",
            "max_items",
            "truncated",
        },
        "facts.pagination",
    )
    runtime = _exact_object(
        facts["runtime"],
        {
            "browser_session_id",
            "browser_visible",
            "page_kind",
            "page_url",
            "owner_thread_id",
            "capture_thread_id",
            "binding",
        },
        "facts.runtime",
    )
    if (
        runtime["browser_session_id"] != browser_session_id
        or runtime["browser_visible"] is not True
        or runtime["page_kind"] != "draft_box"
        or runtime["page_url"] != page_url
        or runtime["binding"] != "current_live_browser_page"
        or not _same_exact_int(runtime["owner_thread_id"], runtime["capture_thread_id"])
    ):
        _reject("SCOPE_RUNTIME_BINDING_INVALID", "scope is not bound to one visible browser owner")

    raw_items = raw["items"]
    if not isinstance(raw_items, list) or not raw_items:
        _reject("SCOPE_ITEMS_INVALID", "scope must contain at least one item")
    if len(raw_items) > requested_max_items:
        _reject("SCOPE_ITEMS_INVALID", "scope contains more items than requested")
    if (
        not _exact_int(pagination["captured_count"], len(raw_items))
        or not _exact_int(pagination["max_items"], requested_max_items)
        or not _non_negative_int_at_least(pagination["visible_row_count"], len(raw_items))
    ):
        _reject("SCOPE_PAGINATION_INVALID", "scope pagination does not match captured items")

    normalized_items, store_identity = _normalize_items(
        raw_items,
        browser_session_id=browser_session_id,
        page_url=page_url,
    )

    evidence = _exact_object(
        raw["evidence"],
        {"kind", "dom_sha256", "dom_digest", "summary", "refs"},
        "evidence",
    )
    if evidence["kind"] != "live_dom_snapshot":
        _reject("SCOPE_EVIDENCE_INVALID", "scope evidence must be a live DOM snapshot")
    reported_dom_sha256 = _sha256_text(evidence["dom_sha256"], "evidence.dom_sha256")
    expected_dom_sha256 = canonical_sha256({"page": page, "facts": facts, "items": raw_items})
    if not hmac.compare_digest(reported_dom_sha256, expected_dom_sha256):
        _reject("SCOPE_EVIDENCE_DIGEST_INVALID", "scope DOM evidence digest does not match")
    summary = _exact_object(
        evidence["summary"],
        {"captured_count", "visible_row_count", "ordered", "stable_identity_complete", "page_kind"},
        "evidence.summary",
    )
    if (
        not _exact_int(summary["captured_count"], len(raw_items))
        or not _exact_int(summary["visible_row_count"], pagination["visible_row_count"])
        or summary["ordered"] is not True
        or summary["stable_identity_complete"] is not True
        or summary["page_kind"] != "draft_box"
    ):
        _reject("SCOPE_EVIDENCE_SUMMARY_INVALID", "scope evidence summary conflicts with capture facts")
    expected_refs = [item["evidence_ref"] for item in raw_items]
    if evidence["refs"] != expected_refs:
        _reject("SCOPE_EVIDENCE_REFS_INVALID", "scope evidence refs do not match ordered items")
    reported_refs_digest = _sha256_text(evidence["dom_digest"], "evidence.dom_digest")
    if not hmac.compare_digest(reported_refs_digest, canonical_sha256(expected_refs)):
        _reject("SCOPE_EVIDENCE_DIGEST_INVALID", "scope DOM ref digest does not match")

    zero_write = _exact_object(
        raw["zero_write_proof"],
        {
            "ok",
            "strategy",
            "navigation_attempted",
            "interactive_action_attempted",
            "mutation_dispatch_attempted",
        },
        "zero_write_proof",
    )
    if zero_write != {
        "ok": True,
        "strategy": "current_visible_page_dom_read",
        "navigation_attempted": False,
        "interactive_action_attempted": False,
        "mutation_dispatch_attempted": False,
    }:
        _reject("SCOPE_ZERO_WRITE_PROOF_INVALID", "capture does not prove a zero-write DOM read")

    canonical_runtime = _exact_object(
        runtime_context,
        {"instance_id", "browser_runtime_id", "git_head"},
        "authoritative runtime",
    )
    snapshot = {
        "schema_version": SCOPE_SCHEMA,
        "observed_at": captured_at,
        "runtime_identity": {
            "instance_id": _non_empty_text(canonical_runtime["instance_id"], "runtime instance"),
            "browser_runtime_id": _non_empty_text(
                canonical_runtime["browser_runtime_id"],
                "browser runtime",
            ),
            "browser_session_id": browser_session_id,
            "git_head": _non_empty_text(canonical_runtime["git_head"], "git head"),
        },
        "page_identity": {
            "url": page_url,
            "kind": "draft_box",
            "title": page["title"],
            "business_marker": page["business_marker"],
        },
        "store_identity": store_identity,
        "filter_state": filter_state,
        "sort_state": sort_state,
        "page_state": pagination,
        "items": normalized_items,
        "evidence": {
            "kind": evidence["kind"],
            "dom_sha256": reported_dom_sha256,
            "refs_digest": reported_refs_digest,
            "summary": summary,
            "refs": evidence["refs"],
        },
        "zero_write_proof": {
            key: zero_write[key]
            for key in (
                "strategy",
                "navigation_attempted",
                "interactive_action_attempted",
                "mutation_dispatch_attempted",
            )
        },
    }
    digest = canonical_sha256(snapshot)
    return {**snapshot, "digest": digest, "snapshot_sha256": digest}


def _normalize_items(
    raw_items: list[Any],
    *,
    browser_session_id: str,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    normalized: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    dom_indices: set[int] = set()
    previous_dom_index = -1
    store_name: str | None = None
    for expected_ordinal, raw_value in enumerate(raw_items, start=1):
        item = _exact_object(
            raw_value,
            {
                "position",
                "title",
                "product_id",
                "source_url",
                "source_urls",
                "stable_identity",
                "store_evidence",
                "row_text_excerpt",
                "evidence_ref",
            },
            f"items[{expected_ordinal - 1}]",
        )
        if not _exact_int(item["position"], expected_ordinal):
            _reject("SCOPE_ORDER_INVALID", "scope ordinals must be contiguous and one-based")
        title = _non_empty_text(item["title"], "item.title")
        source_urls = item["source_urls"]
        if not isinstance(source_urls, list) or any(not isinstance(value, str) for value in source_urls):
            _reject("SCOPE_ITEM_SOURCE_INVALID", "item source_urls must be a list of URLs")
        if not source_urls:
            _reject(
                "SCOPE_ITEM_SOURCE_INVALID",
                "every executable item requires canonical product source URLs",
            )
        try:
            canonical_source = canonical_source_identity(source_urls[0], source_urls)
        except TwoStageContractError as exc:
            raise ScopeContractError("SCOPE_ITEM_SOURCE_INVALID", str(exc)) from exc
        if (
            list(canonical_source["urls"]) != source_urls
            or item["source_url"] != canonical_source["primary_url"]
        ):
            _reject("SCOPE_ITEM_SOURCE_INVALID", "item source URLs are not canonical")
        if any(
            not is_supported_product_detail_url(candidate)
            for candidate in canonical_source["urls"]
        ):
            _reject(
                "SCOPE_ITEM_SOURCE_INVALID",
                "item source URLs must be supported external product detail pages",
            )
        stable = _exact_object(
            item["stable_identity"],
            {"kind", "value", "fingerprint"},
            "item.stable_identity",
        )
        kind = stable["kind"]
        value = _non_empty_text(stable["value"], "stable identity value")
        reported_fingerprint = _sha256_text(stable["fingerprint"], "stable identity fingerprint")
        if kind == "product_id":
            expected_fingerprint = hashlib.sha256(f"product_id:{value}".encode("utf-8")).hexdigest().upper()
            if item["product_id"] != value:
                _reject("SCOPE_ITEM_IDENTITY_INVALID", "product ID conflicts with stable identity")
        elif kind == "source_url":
            expected_fingerprint = canonical_source["fingerprint"]
            if item["product_id"] is not None or value != canonical_source["primary_url"]:
                _reject("SCOPE_ITEM_IDENTITY_INVALID", "source URL conflicts with stable identity")
        else:
            _reject("SCOPE_ITEM_IDENTITY_INVALID", "unsupported stable identity kind")
        if not hmac.compare_digest(reported_fingerprint, expected_fingerprint):
            _reject("SCOPE_ITEM_IDENTITY_INVALID", "stable identity fingerprint does not match")
        if reported_fingerprint in fingerprints:
            _reject("SCOPE_ITEM_IDENTITY_AMBIGUOUS", "scope contains duplicate stable identities")
        fingerprints.add(reported_fingerprint)

        store = _exact_object(
            item["store_evidence"],
            {"store_name", "cell_text", "source", "column_index", "tag", "class_name", "dom_index"},
            "item.store_evidence",
        )
        current_store_name = _non_empty_text(store["store_name"], "store name")
        store_cell_text = _non_empty_text(store["cell_text"], "store cell text")
        if store["source"] != "structured_store_cell":
            _reject("SCOPE_STORE_EVIDENCE_INVALID", "store identity is not from the structured store cell")
        normalized_store = " ".join(current_store_name.split())
        normalized_cell = " ".join(store_cell_text.split())
        if re.search(
            rf"(?:^|[\s:：\u300c]){re.escape(normalized_store)}(?:$|[\s\u300d])",
            normalized_cell,
        ) is None:
            _reject("SCOPE_STORE_EVIDENCE_INVALID", "store cell text does not exactly identify the store")
        if (
            isinstance(store["column_index"], bool)
            or not isinstance(store["column_index"], int)
            or store["column_index"] < 0
            or not _non_empty_text(store["tag"], "store cell tag")
        ):
            _reject("SCOPE_STORE_EVIDENCE_INVALID", "store cell metadata is invalid")
        dom_index = store["dom_index"]
        if (
            isinstance(dom_index, bool)
            or not isinstance(dom_index, int)
            or dom_index < 0
            or dom_index in dom_indices
            or dom_index <= previous_dom_index
        ):
            _reject("SCOPE_ORDER_INVALID", "scope DOM row indices must be unique and increasing")
        dom_indices.add(dom_index)
        previous_dom_index = dom_index
        if store_name is None:
            store_name = current_store_name
        elif store_name != current_store_name:
            _reject("SCOPE_MULTI_STORE_FORBIDDEN", "one edit batch scope must contain exactly one store")

        row_text = _non_empty_text(item["row_text_excerpt"], "row text excerpt")
        if title not in row_text or current_store_name not in row_text:
            _reject("SCOPE_ITEM_EVIDENCE_INVALID", "row evidence does not contain the exact title and store")
        ref = _exact_object(
            item["evidence_ref"],
            {"kind", "browser_session_id", "page_kind", "page_url", "dom_index", "row_sha256"},
            "item.evidence_ref",
        )
        if (
            ref["kind"] != "live_dom_row"
            or ref["browser_session_id"] != browser_session_id
            or ref["page_kind"] != "draft_box"
            or ref["page_url"] != page_url
            or ref["dom_index"] != store["dom_index"]
            or not hmac.compare_digest(
                _sha256_text(ref["row_sha256"], "row digest"),
                hashlib.sha256(row_text.encode("utf-8")).hexdigest().upper(),
            )
        ):
            _reject("SCOPE_ITEM_EVIDENCE_INVALID", "item DOM evidence does not match its live row")

        unsigned_store = {"store_name": current_store_name, "source": "structured_store_cell"}
        store_fingerprint = canonical_sha256(unsigned_store)
        target_identity = {
            "schema_version": TARGET_SCHEMA,
            "store_fingerprint": store_fingerprint,
            "stable_identity": {
                "kind": kind,
                "value": value,
                "fingerprint": reported_fingerprint,
            },
            "source_urls": list(source_urls),
        }
        try:
            canonical_target = canonical_frozen_target_identity(
                target_identity,
                store_name=current_store_name,
            )
        except MutationCommandContractError as exc:
            raise ScopeContractError("SCOPE_ITEM_IDENTITY_INVALID", str(exc)) from exc
        if canonical_target != target_identity:
            _reject(
                "SCOPE_ITEM_IDENTITY_INVALID",
                "scope target identity is not in the exact executable form",
            )
        normalized.append(
            {
                "ordinal": expected_ordinal,
                "title": title,
                "dxm_product_id": item["product_id"],
                "stable_record_key": f"{kind}:{value}",
                "source_url": item["source_url"],
                "source_urls": list(source_urls),
                "store_evidence": store,
                "target_identity": target_identity,
                "target_identity_sha256": canonical_sha256(target_identity),
                "evidence_ref": ref,
            }
        )

    assert store_name is not None
    unsigned_store = {"store_name": store_name, "source": "structured_store_cell"}
    return normalized, {**unsigned_store, "fingerprint": canonical_sha256(unsigned_store)}


def _exact_object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        _reject("SCOPE_SCHEMA_INVALID", f"{label} has an unexpected shape")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _reject("SCOPE_SCHEMA_INVALID", f"{label} must be an object")
    return value


def _non_empty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _reject("SCOPE_SCHEMA_INVALID", f"{label} must be non-empty text")
    return value.strip()


def _sha256_text(value: Any, label: str) -> str:
    text = _non_empty_text(value, label).upper()
    if len(text) != 64 or any(character not in "0123456789ABCDEF" for character in text):
        _reject("SCOPE_SCHEMA_INVALID", f"{label} must be SHA-256")
    return text


def _timestamp(value: Any) -> str:
    text = _non_empty_text(value, "captured_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScopeContractError("SCOPE_TIMESTAMP_INVALID", "captured_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        _reject("SCOPE_TIMESTAMP_INVALID", "captured_at must include a timezone")
    return text


def _draft_box_url(value: Any) -> str:
    text = _non_empty_text(value, "page.url")
    parsed = urlparse(text)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not (host == "dianxiaomi.com" or host.endswith(".dianxiaomi.com")):
        _reject("SCOPE_PAGE_INVALID", "scope page is outside dianxiaomi.com")
    if parsed.path.rstrip("/").casefold() != "/web/smt/smtproductlist/draft":
        _reject("SCOPE_PAGE_INVALID", "scope page is not the SMT draft box")
    return text


def _same_exact_int(left: Any, right: Any) -> bool:
    return not isinstance(left, bool) and isinstance(left, int) and left == right


def _exact_int(value: Any, expected: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value == expected


def _non_negative_int_at_least(value: Any, minimum: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= minimum


def _reject(reason_code: str, detail: str) -> None:
    raise ScopeContractError(reason_code, detail)
