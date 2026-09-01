from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


REAL_DXM_WRITE_SCOPE_SCHEMA = "real_dxm_write_scope.v1"
REAL_DXM_WRITE_APPROVAL_SCHEMA = "real_dxm_write_approval.v1"
REAL_DXM_WRITE_STAGE = "execute"
REAL_DXM_WRITE_PATH = "B"
REAL_DXM_WRITE_SAVE_STAGES = ("SAVE1", "SAVE2")
SCOPE_REJECTED = "SCOPE_REJECTED"
WORKTREE_IDENTITY_SCHEMA = "dxm.git-worktree.identity.v1"

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest().upper()
_SCOPE_UNSIGNED_KEYS = frozenset(
    {
        "schema",
        "stage",
        "path",
        "issuedAt",
        "expiresAt",
        "nonce",
        "account",
        "shop",
        "snapshot",
        "git",
        "worktree",
        "runtime",
        "l2",
        "orderedProducts",
        "publishAllowed",
        "maxPhysicalRequestsPerSave",
    }
)
_SCOPE_KEYS = _SCOPE_UNSIGNED_KEYS | {"scopeSha256"}
_APPROVAL_UNSIGNED_KEYS = frozenset(
    {
        "schema",
        "stage",
        "scopeSha256",
        "nonce",
        "approvedAt",
        "expiresAt",
        "approvedBy",
        "decision",
    }
)
_APPROVAL_KEYS = _APPROVAL_UNSIGNED_KEYS | {"approvalSha256"}
_WORKTREE_KEYS = frozenset(
    {
        "schema",
        "git_head",
        "git_dirty",
        "status_count",
        "status_sha256",
        "execution_file_count",
        "execution_tree_sha256",
    }
)
_WILDCARD_SENTINELS = frozenset(
    {
        "all",
        "any",
        "all_fields",
        "any_field",
        "all_products",
        "any_product",
    }
)
_PUBLISH_FIELD_TOKENS = ("publish", "发布")


class RealDxmWriteScopeError(ValueError):
    """Fail-closed rejection from the real DXM write-scope contract.

    ``reason_code`` is intentionally stable for the public API. ``detail_code``
    provides a non-sensitive diagnostic without allowing callers to branch into
    weaker write paths.
    """

    reason_code = SCOPE_REJECTED

    def __init__(self, detail_code: str, detail: str) -> None:
        self.reason_code = SCOPE_REJECTED
        self.detail_code = detail_code
        self.detail = detail
        super().__init__(f"[{SCOPE_REJECTED}:{detail_code}] {detail}")


def canonical_json(value: Any) -> str:
    """Return the sole JSON representation used by both contract digests."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RealDxmWriteScopeError(
            "VALUE_NOT_CANONICAL_JSON",
            "contract value must be finite canonical JSON",
        ) from exc


def canonical_sha256(value: Any) -> str:
    """Return an uppercase SHA-256 of :func:`canonical_json`."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest().upper()


def prepare_real_dxm_write_scope(
    scope_facts: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Canonicalize exact unsigned v1 facts and attach ``scopeSha256``.

    This function performs no Reader, filesystem, database, browser, or network
    access. All identity facts must be supplied by a trusted caller. The result
    is a JSON-compatible document ready to be written outside the Git checkout.
    """

    resolved_now = _now(now)
    unsigned = _normalize_scope(
        scope_facts,
        has_digest=False,
        strict_canonical=False,
        now=resolved_now,
    )
    return _json_clone({**unsigned, "scopeSha256": canonical_sha256(unsigned)})


def validate_real_dxm_write_scope(
    scope: Mapping[str, Any],
    *,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Validate exact shape, semantics, canonical form, digest, and expiry."""

    normalized = _normalize_scope(
        scope,
        has_digest=True,
        strict_canonical=True,
        now=_now(now),
    )
    return _json_clone(normalized)


def prepare_real_dxm_write_approval(
    approval_facts: Mapping[str, Any],
    *,
    scope: Mapping[str, Any],
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Canonicalize one ApprovalFile bound to an already valid scope."""

    resolved_now = _now(now)
    canonical_scope = _normalize_scope(
        scope,
        has_digest=True,
        strict_canonical=True,
        now=resolved_now,
    )
    unsigned = _normalize_approval(
        approval_facts,
        scope=canonical_scope,
        has_digest=False,
        strict_canonical=False,
        now=resolved_now,
    )
    return _json_clone({**unsigned, "approvalSha256": canonical_sha256(unsigned)})


def validate_real_dxm_write_approval(
    approval: Mapping[str, Any],
    *,
    scope: Mapping[str, Any],
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Validate one ApprovalFile against the exact scope hash and bindings.

    Successful validation does not consume the nonce. The persistence layer must
    atomically mark that nonce consumed in the same transaction that starts the
    task; this pure contract deliberately cannot claim replay protection alone.
    """

    resolved_now = _now(now)
    canonical_scope = _normalize_scope(
        scope,
        has_digest=True,
        strict_canonical=True,
        now=resolved_now,
    )
    normalized = _normalize_approval(
        approval,
        scope=canonical_scope,
        has_digest=True,
        strict_canonical=True,
        now=resolved_now,
    )
    return _json_clone(normalized)


def validate_real_dxm_write_authorization(
    *,
    scope: Mapping[str, Any],
    approval: Mapping[str, Any],
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Return one canonical result containing a matched scope and ApprovalFile."""

    resolved_now = _now(now)
    canonical_scope = validate_real_dxm_write_scope(scope, now=resolved_now)
    canonical_approval = validate_real_dxm_write_approval(
        approval,
        scope=canonical_scope,
        now=resolved_now,
    )
    return {
        "scope": canonical_scope,
        "approval": canonical_approval,
        "scopeSha256": canonical_scope["scopeSha256"],
        "approvalSha256": canonical_approval["approvalSha256"],
    }


def _normalize_scope(
    value: Mapping[str, Any],
    *,
    has_digest: bool,
    strict_canonical: bool,
    now: datetime,
) -> dict[str, Any]:
    raw = _exact_object(
        value,
        _SCOPE_KEYS if has_digest else _SCOPE_UNSIGNED_KEYS,
        "scope",
    )
    if raw["schema"] != REAL_DXM_WRITE_SCOPE_SCHEMA:
        _reject("SCOPE_SCHEMA_MISMATCH", "unsupported real-write scope schema")
    if raw["stage"] != REAL_DXM_WRITE_STAGE:
        _reject("SCOPE_STAGE_MISMATCH", "real-write scope stage must be execute")
    if raw["path"] != REAL_DXM_WRITE_PATH:
        _reject("SCOPE_PATH_MISMATCH", "real-write scope must be bound to Path B")
    if raw["publishAllowed"] is not False:
        _reject("PUBLISH_INTENT_FORBIDDEN", "publishAllowed must be exactly false")
    if not _exact_int(raw["maxPhysicalRequestsPerSave"], 1):
        _reject(
            "SAVE_REQUEST_LIMIT_INVALID",
            "maxPhysicalRequestsPerSave must be exactly 1",
        )

    issued_at, issued_at_text = _timestamp(
        raw["issuedAt"],
        "scope.issuedAt",
        strict=strict_canonical,
    )
    expires_at, expires_at_text = _timestamp(
        raw["expiresAt"],
        "scope.expiresAt",
        strict=strict_canonical,
    )
    _valid_window(issued_at, expires_at, now=now, label="scope")
    nonce = _nonce(raw["nonce"], "scope.nonce", strict=strict_canonical)

    account_raw = _exact_object(
        raw["account"],
        {"accountContextHash"},
        "scope.account",
    )
    account = {
        "accountContextHash": _sha256_text(
            account_raw["accountContextHash"],
            "scope.account.accountContextHash",
            strict=strict_canonical,
        )
    }

    shop_raw = _exact_object(raw["shop"], {"shopId", "shopName"}, "scope.shop")
    shop = {
        "shopId": _positive_int(shop_raw["shopId"], "scope.shop.shopId"),
        "shopName": _text(
            shop_raw["shopName"],
            "scope.shop.shopName",
            strict=strict_canonical,
        ),
    }

    snapshot_raw = _exact_object(
        raw["snapshot"],
        {"snapshotId", "snapshotSha256", "taskId"},
        "scope.snapshot",
    )
    snapshot = {
        "snapshotId": _positive_int(
            snapshot_raw["snapshotId"],
            "scope.snapshot.snapshotId",
        ),
        "snapshotSha256": _sha256_text(
            snapshot_raw["snapshotSha256"],
            "scope.snapshot.snapshotSha256",
            strict=strict_canonical,
        ),
        "taskId": _positive_int(snapshot_raw["taskId"], "scope.snapshot.taskId"),
    }

    git_raw = _exact_object(raw["git"], {"head"}, "scope.git")
    git_head = _git_head(git_raw["head"], strict=strict_canonical)
    git = {"head": git_head}
    worktree = _worktree_identity(
        raw["worktree"],
        git_head=git_head,
        strict=strict_canonical,
    )

    runtime_raw = _exact_object(
        raw["runtime"],
        {"runtimeInstanceId", "browserRuntimeId", "browserSessionId"},
        "scope.runtime",
    )
    runtime = {
        "runtimeInstanceId": _text(
            runtime_raw["runtimeInstanceId"],
            "scope.runtime.runtimeInstanceId",
            strict=strict_canonical,
        ),
        "browserRuntimeId": _text(
            runtime_raw["browserRuntimeId"],
            "scope.runtime.browserRuntimeId",
            strict=strict_canonical,
        ),
        "browserSessionId": _text(
            runtime_raw["browserSessionId"],
            "scope.runtime.browserSessionId",
            strict=strict_canonical,
        ),
    }

    l2_raw = _exact_object(
        raw["l2"],
        {"status", "evidenceFingerprint"},
        "scope.l2",
    )
    if l2_raw["status"] != "passed":
        _reject("L2_NOT_PASSED", "scope must bind a fresh passed L2 gate")
    l2 = {
        "status": "passed",
        "evidenceFingerprint": _sha256_text(
            l2_raw["evidenceFingerprint"],
            "scope.l2.evidenceFingerprint",
            strict=strict_canonical,
        ),
    }

    ordered_products = _ordered_products(
        raw["orderedProducts"],
        strict=strict_canonical,
    )
    unsigned = {
        "schema": REAL_DXM_WRITE_SCOPE_SCHEMA,
        "stage": REAL_DXM_WRITE_STAGE,
        "path": REAL_DXM_WRITE_PATH,
        "issuedAt": issued_at_text,
        "expiresAt": expires_at_text,
        "nonce": nonce,
        "account": account,
        "shop": shop,
        "snapshot": snapshot,
        "git": git,
        "worktree": worktree,
        "runtime": runtime,
        "l2": l2,
        "orderedProducts": ordered_products,
        "publishAllowed": False,
        "maxPhysicalRequestsPerSave": 1,
    }
    _assert_no_wildcards(unsigned, "scope")
    if not has_digest:
        return unsigned

    stored_digest = _sha256_text(
        raw["scopeSha256"],
        "scope.scopeSha256",
        strict=strict_canonical,
    )
    expected_digest = canonical_sha256(unsigned)
    if not hmac.compare_digest(stored_digest, expected_digest):
        _reject("SCOPE_HASH_MISMATCH", "scopeSha256 does not match canonical scope facts")
    return {**unsigned, "scopeSha256": stored_digest}


def _normalize_approval(
    value: Mapping[str, Any],
    *,
    scope: Mapping[str, Any],
    has_digest: bool,
    strict_canonical: bool,
    now: datetime,
) -> dict[str, Any]:
    raw = _exact_object(
        value,
        _APPROVAL_KEYS if has_digest else _APPROVAL_UNSIGNED_KEYS,
        "approval",
    )
    if raw["schema"] != REAL_DXM_WRITE_APPROVAL_SCHEMA:
        _reject("APPROVAL_SCHEMA_MISMATCH", "unsupported real-write approval schema")
    if raw["stage"] != REAL_DXM_WRITE_STAGE or raw["stage"] != scope["stage"]:
        _reject("APPROVAL_STAGE_MISMATCH", "approval stage differs from the scope")
    if raw["decision"] != "APPROVE":
        _reject("APPROVAL_DECISION_INVALID", "ApprovalFile decision must be APPROVE")

    scope_digest = _sha256_text(
        raw["scopeSha256"],
        "approval.scopeSha256",
        strict=strict_canonical,
    )
    if not hmac.compare_digest(scope_digest, scope["scopeSha256"]):
        _reject("APPROVAL_SCOPE_HASH_MISMATCH", "approval is bound to another scope")

    nonce = _nonce(raw["nonce"], "approval.nonce", strict=strict_canonical)
    if not hmac.compare_digest(nonce, scope["nonce"]):
        _reject("APPROVAL_NONCE_MISMATCH", "approval nonce differs from the scope")

    approved_at, approved_at_text = _timestamp(
        raw["approvedAt"],
        "approval.approvedAt",
        strict=strict_canonical,
    )
    expires_at, expires_at_text = _timestamp(
        raw["expiresAt"],
        "approval.expiresAt",
        strict=strict_canonical,
    )
    if expires_at_text != scope["expiresAt"]:
        _reject("APPROVAL_EXPIRY_MISMATCH", "approval expiry differs from the scope")
    scope_issued_at, _ = _timestamp(
        scope["issuedAt"],
        "scope.issuedAt",
        strict=True,
    )
    if approved_at < scope_issued_at or approved_at >= expires_at:
        _reject(
            "APPROVAL_TIME_OUTSIDE_SCOPE",
            "approval time must fall inside the scope validity window",
        )
    if approved_at > now:
        _reject("APPROVAL_NOT_YET_VALID", "approval time is in the future")
    if now >= expires_at:
        _reject("APPROVAL_EXPIRED", "ApprovalFile has expired")

    unsigned = {
        "schema": REAL_DXM_WRITE_APPROVAL_SCHEMA,
        "stage": REAL_DXM_WRITE_STAGE,
        "scopeSha256": scope_digest,
        "nonce": nonce,
        "approvedAt": approved_at_text,
        "expiresAt": expires_at_text,
        "approvedBy": _text(
            raw["approvedBy"],
            "approval.approvedBy",
            strict=strict_canonical,
        ),
        "decision": "APPROVE",
    }
    _assert_no_wildcards(unsigned, "approval")
    if not has_digest:
        return unsigned

    stored_digest = _sha256_text(
        raw["approvalSha256"],
        "approval.approvalSha256",
        strict=strict_canonical,
    )
    expected_digest = canonical_sha256(unsigned)
    if not hmac.compare_digest(stored_digest, expected_digest):
        _reject(
            "APPROVAL_HASH_MISMATCH",
            "approvalSha256 does not match canonical approval facts",
        )
    return {**unsigned, "approvalSha256": stored_digest}


def _ordered_products(value: Any, *, strict: bool) -> list[dict[str, Any]]:
    products = _array(value, "scope.orderedProducts")
    if not 3 <= len(products) <= 100:
        _reject(
            "ORDERED_PRODUCTS_COUNT_INVALID",
            "Path B real-write scope requires 3..100 ordered products",
        )

    normalized: list[dict[str, Any]] = []
    seen_products: set[int] = set()
    for expected_ordinal, item_value in enumerate(products, start=1):
        label = f"scope.orderedProducts[{expected_ordinal - 1}]"
        item = _exact_object(
            item_value,
            {"ordinal", "productId", "allowedFields", "saves"},
            label,
        )
        ordinal = _positive_int(item["ordinal"], f"{label}.ordinal")
        if ordinal != expected_ordinal:
            _reject(
                "PRODUCT_ORDER_INVALID",
                "product ordinals must be contiguous, one-based, and list ordered",
            )
        product_id = _positive_int(item["productId"], f"{label}.productId")
        if product_id in seen_products:
            _reject("PRODUCT_DUPLICATE", "ordered product IDs must be unique")
        seen_products.add(product_id)

        saves_raw = _array(item["saves"], f"{label}.saves")
        if len(saves_raw) != 2:
            _reject("SAVE_STAGES_INVALID", "each product must have SAVE1 and SAVE2")
        saves: list[dict[str, Any]] = []
        for save_index, expected_stage in enumerate(REAL_DXM_WRITE_SAVE_STAGES):
            save = _exact_object(
                saves_raw[save_index],
                {"stage", "maxPhysicalRequests"},
                f"{label}.saves[{save_index}]",
            )
            if save["stage"] != expected_stage:
                _reject(
                    "SAVE_ORDER_INVALID",
                    "save stages must be ordered exactly as SAVE1 then SAVE2",
                )
            if not _exact_int(save["maxPhysicalRequests"], 1):
                _reject(
                    "SAVE_REQUEST_LIMIT_INVALID",
                    "every SAVE must allow exactly one physical request",
                )
            saves.append({"stage": expected_stage, "maxPhysicalRequests": 1})

        fields_raw = _array(item["allowedFields"], f"{label}.allowedFields")
        if not fields_raw:
            _reject("ALLOWED_FIELDS_REQUIRED", "each product needs explicit allowed fields")
        fields: list[dict[str, Any]] = []
        seen_fields: set[tuple[str, str]] = set()
        seen_field_names: set[str] = set()
        fields_per_stage = {stage: 0 for stage in REAL_DXM_WRITE_SAVE_STAGES}
        for field_index, field_value in enumerate(fields_raw):
            field_label = f"{label}.allowedFields[{field_index}]"
            field = _exact_object(
                field_value,
                {"field", "saveStage", "preimageSha256", "expectedSha256"},
                field_label,
            )
            field_name = _text(
                field["field"],
                f"{field_label}.field",
                strict=strict,
            )
            if any(token in field_name.casefold() for token in _PUBLISH_FIELD_TOKENS):
                _reject(
                    "PUBLISH_FIELD_FORBIDDEN",
                    "allowed fields cannot grant any publish-like field",
                )
            save_stage = field["saveStage"]
            if save_stage not in REAL_DXM_WRITE_SAVE_STAGES:
                _reject(
                    "FIELD_SAVE_STAGE_INVALID",
                    "allowed field must be bound to SAVE1 or SAVE2",
                )
            identity = (save_stage, field_name)
            if identity in seen_fields:
                _reject(
                    "ALLOWED_FIELD_DUPLICATE",
                    "allowed fields must be unique within each SAVE stage",
                )
            seen_fields.add(identity)
            if field_name in seen_field_names:
                _reject(
                    "FIELD_REUSED_ACROSS_SAVE_STAGES",
                    "one field cannot be authorized by both SAVE stages",
                )
            seen_field_names.add(field_name)
            fields_per_stage[save_stage] += 1
            fields.append(
                {
                    "field": field_name,
                    "saveStage": save_stage,
                    "preimageSha256": _sha256_text(
                        field["preimageSha256"],
                        f"{field_label}.preimageSha256",
                        strict=strict,
                    ),
                    "expectedSha256": _sha256_text(
                        field["expectedSha256"],
                        f"{field_label}.expectedSha256",
                        strict=strict,
                    ),
                }
            )
        if any(fields_per_stage[stage] == 0 for stage in REAL_DXM_WRITE_SAVE_STAGES):
            _reject(
                "SAVE_ALLOWED_FIELDS_REQUIRED",
                "SAVE1 and SAVE2 each require at least one explicit allowed field",
            )

        normalized.append(
            {
                "ordinal": ordinal,
                "productId": product_id,
                "allowedFields": fields,
                "saves": saves,
            }
        )
    return normalized


def _worktree_identity(
    value: Any,
    *,
    git_head: str,
    strict: bool,
) -> dict[str, Any]:
    raw = _exact_object(value, _WORKTREE_KEYS, "scope.worktree")
    if raw["schema"] != WORKTREE_IDENTITY_SCHEMA:
        _reject("WORKTREE_SCHEMA_MISMATCH", "unsupported worktree identity schema")
    worktree_head = _git_head(raw["git_head"], strict=strict)
    if worktree_head != git_head:
        _reject("WORKTREE_HEAD_MISMATCH", "worktree HEAD differs from scope Git HEAD")
    if raw["git_dirty"] is not False:
        _reject("WORKTREE_DIRTY", "real-write scope requires a clean worktree")
    status_count = _non_negative_int(raw["status_count"], "scope.worktree.status_count")
    if status_count != 0:
        _reject("WORKTREE_DIRTY", "clean worktree status_count must be zero")
    status_sha256 = _sha256_text(
        raw["status_sha256"],
        "scope.worktree.status_sha256",
        strict=strict,
    )
    if not hmac.compare_digest(status_sha256, _EMPTY_SHA256):
        _reject("WORKTREE_STATUS_HASH_INVALID", "clean worktree status hash is invalid")
    execution_file_count = _positive_int(
        raw["execution_file_count"],
        "scope.worktree.execution_file_count",
    )
    return {
        "schema": WORKTREE_IDENTITY_SCHEMA,
        "git_head": worktree_head,
        "git_dirty": False,
        "status_count": 0,
        "status_sha256": status_sha256,
        "execution_file_count": execution_file_count,
        "execution_tree_sha256": _sha256_text(
            raw["execution_tree_sha256"],
            "scope.worktree.execution_tree_sha256",
            strict=strict,
        ),
    }


def _exact_object(value: Any, keys: set[str] | frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        _reject("EXACT_KEYS_MISMATCH", f"{label} must contain the exact v1 keys")
    return dict(value)


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _reject("VALUE_TYPE_INVALID", f"{label} must be an array")
    return value.copy()


def _text(value: Any, label: str, *, strict: bool) -> str:
    if not isinstance(value, str) or not value.strip():
        _reject("TEXT_INVALID", f"{label} must be non-empty text")
    normalized = value.strip()
    if "\r" in normalized or "\n" in normalized:
        _reject("TEXT_INVALID", f"{label} cannot contain line breaks")
    if strict and normalized != value:
        _reject("VALUE_NOT_CANONICAL", f"{label} is not canonical text")
    return normalized


def _nonce(value: Any, label: str, *, strict: bool) -> str:
    nonce = _text(value, label, strict=strict)
    if not 16 <= len(nonce) <= 256:
        _reject("NONCE_INVALID", f"{label} must contain 16..256 characters")
    if any(
        not (
            character.isascii()
            and (character.isalnum() or character in "._~:-")
        )
        for character in nonce
    ):
        _reject("NONCE_INVALID", f"{label} contains a forbidden character")
    return nonce


def _sha256_text(value: Any, label: str, *, strict: bool) -> str:
    text = _text(value, label, strict=strict).upper()
    if len(text) != 64 or any(character not in "0123456789ABCDEF" for character in text):
        _reject("SHA256_INVALID", f"{label} must be a SHA-256 digest")
    if strict and text != value:
        _reject("VALUE_NOT_CANONICAL", f"{label} must use uppercase hexadecimal")
    return text


def _git_head(value: Any, *, strict: bool) -> str:
    text = _text(value, "git head", strict=strict).lower()
    if len(text) not in {40, 64} or any(character not in "0123456789abcdef" for character in text):
        _reject("GIT_HEAD_INVALID", "Git HEAD must be a full hexadecimal object ID")
    if strict and text != value:
        _reject("VALUE_NOT_CANONICAL", "Git HEAD must use lowercase hexadecimal")
    return text


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _reject("INTEGER_INVALID", f"{label} must be a positive integer")
    return value


def _non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _reject("INTEGER_INVALID", f"{label} must be a non-negative integer")
    return value


def _exact_int(value: Any, expected: int) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value == expected


def _timestamp(value: Any, label: str, *, strict: bool) -> tuple[datetime, str]:
    if isinstance(value, datetime) and not strict:
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RealDxmWriteScopeError(
                "TIMESTAMP_INVALID",
                f"{label} must be an ISO-8601 timestamp",
            ) from exc
    else:
        _reject("TIMESTAMP_INVALID", f"{label} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _reject("TIMESTAMP_INVALID", f"{label} must include a timezone")
    parsed = parsed.astimezone(timezone.utc)
    canonical = _format_timestamp(parsed)
    if strict and value != canonical:
        _reject("VALUE_NOT_CANONICAL", f"{label} must be canonical UTC with Z suffix")
    return parsed, canonical


def _format_timestamp(value: datetime) -> str:
    if value.microsecond:
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _now(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed, _ = _timestamp(value, "now", strict=False)
    return parsed


def _valid_window(issued_at: datetime, expires_at: datetime, *, now: datetime, label: str) -> None:
    if issued_at >= expires_at:
        _reject("EXPIRY_WINDOW_INVALID", f"{label} expiry must be after issuance")
    if now < issued_at:
        _reject("SCOPE_NOT_YET_VALID", f"{label} is not yet valid")
    if now >= expires_at:
        _reject("SCOPE_EXPIRED", f"{label} has expired")


def _assert_no_wildcards(value: Any, label: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_no_wildcards(child, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_wildcards(child, f"{label}[{index}]")
        return
    if not isinstance(value, str):
        return
    folded = value.strip().casefold()
    if (
        "*" in value
        or "?" in value
        or "%" in value
        or folded in _WILDCARD_SENTINELS
    ):
        _reject("WILDCARD_FORBIDDEN", f"{label} contains a wildcard")


def _json_clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def _reject(detail_code: str, detail: str) -> None:
    raise RealDxmWriteScopeError(detail_code, detail)


__all__ = [
    "REAL_DXM_WRITE_APPROVAL_SCHEMA",
    "REAL_DXM_WRITE_PATH",
    "REAL_DXM_WRITE_SAVE_STAGES",
    "REAL_DXM_WRITE_SCOPE_SCHEMA",
    "REAL_DXM_WRITE_STAGE",
    "SCOPE_REJECTED",
    "RealDxmWriteScopeError",
    "canonical_json",
    "canonical_sha256",
    "prepare_real_dxm_write_approval",
    "prepare_real_dxm_write_scope",
    "validate_real_dxm_write_approval",
    "validate_real_dxm_write_authorization",
    "validate_real_dxm_write_scope",
]
