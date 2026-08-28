from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterable, Mapping
from typing import Any


BATCH_DRAFT_TASK_FACTS_SCHEMA = "dxm.batch_draft_save.task_facts.v1"
BATCH_DRAFT_AUTHORIZATION_CONTEXT_SCHEMA = "dxm.authorization.context.v2"
WORKTREE_IDENTITY_SCHEMA = "dxm.git-worktree.identity.v1"
BATCH_DRAFT_SAVE_CONFIRMATION = "CONFIRM_DXM_SAVE_ONLY"
BATCH_DRAFT_SAVE_PUBLISH_SCENE = "SMT_SEMI_MANAGED_SAVE_ONLY"

_BATCH_DRAFT_FACT_KEYS = frozenset(
    {
        "schema",
        "stage",
        "mode",
        "confirmation",
        "publish_scene",
        "action",
        "task_id",
        "store_id",
        "product_ids",
        "plan_snapshot_id",
        "plan_snapshot_hash",
        "path",
        "fingerprint",
    }
)
_BATCH_DRAFT_STATIC_FACTS = {
    "stage": "batch_draft_save",
    "mode": "batch_draft_save",
    "confirmation": BATCH_DRAFT_SAVE_CONFIRMATION,
    "publish_scene": BATCH_DRAFT_SAVE_PUBLISH_SCENE,
    "action": "batch_draft_save_only",
}
_AUTHORIZATION_CONTEXT_KEYS = frozenset(
    {
        "schema",
        "stage_task_facts",
        "runtime_instance_id",
        "browser_session_id",
        "git_head",
        "worktree_identity",
        "l2_evidence_fingerprint",
        "approved_by",
        "fingerprint",
    }
)
_WORKTREE_IDENTITY_KEYS = frozenset(
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


class BatchDraftAuthorizationError(ValueError):
    """Invalid input to the immutable batch-draft-save authorization contract."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise BatchDraftAuthorizationError(
            "VALUE_NOT_JSON_SERIALIZABLE",
            "contract value must be JSON serializable",
        ) from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest().upper()


def _json_clone(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _check(ok: bool, reason_code: str = "OK") -> dict[str, bool | str]:
    return {"ok": ok, "reason_code": reason_code}


def _positive_id(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BatchDraftAuthorizationError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be a positive integer",
        )
    return value


def _canonical_sha256(value: Any, *, field_name: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or digest != digest.upper():
        raise BatchDraftAuthorizationError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be an uppercase SHA-256 hex digest",
        )
    try:
        int(digest, 16)
    except ValueError as exc:
        raise BatchDraftAuthorizationError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be an uppercase SHA-256 hex digest",
        ) from exc
    return digest


def _nonempty_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BatchDraftAuthorizationError(
            f"{field_name.upper()}_REQUIRED",
            f"{field_name} is required",
        )
    return value.strip()


def _canonical_git_head(value: Any) -> str:
    git_head = _nonempty_text(value, field_name="git_head").lower()
    if len(git_head) not in {40, 64}:
        raise BatchDraftAuthorizationError(
            "GIT_HEAD_INVALID",
            "git_head must be a full 40- or 64-character hex object ID",
        )
    try:
        int(git_head, 16)
    except ValueError as exc:
        raise BatchDraftAuthorizationError(
            "GIT_HEAD_INVALID",
            "git_head must be a full hex object ID",
        ) from exc
    return git_head


def _canonical_worktree_identity(
    value: Any,
    *,
    git_head: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _WORKTREE_IDENTITY_KEYS:
        raise BatchDraftAuthorizationError(
            "WORKTREE_IDENTITY_SHAPE_MISMATCH",
            "worktree identity must contain the exact v1 fields",
        )
    if value.get("schema") != WORKTREE_IDENTITY_SCHEMA:
        raise BatchDraftAuthorizationError(
            "WORKTREE_IDENTITY_SCHEMA_MISMATCH",
            "worktree identity schema mismatch",
        )
    canonical_head = _canonical_git_head(value.get("git_head"))
    if canonical_head != git_head:
        raise BatchDraftAuthorizationError(
            "WORKTREE_IDENTITY_HEAD_MISMATCH",
            "worktree identity HEAD differs from authorization HEAD",
        )
    if type(value.get("git_dirty")) is not bool:
        raise BatchDraftAuthorizationError(
            "WORKTREE_IDENTITY_DIRTY_INVALID",
            "worktree identity git_dirty must be a boolean",
        )
    status_count = value.get("status_count")
    execution_file_count = value.get("execution_file_count")
    if (
        type(status_count) is not int
        or status_count < 0
        or type(execution_file_count) is not int
        or execution_file_count < 0
    ):
        raise BatchDraftAuthorizationError(
            "WORKTREE_IDENTITY_COUNT_INVALID",
            "worktree identity counts must be non-negative integers",
        )
    return {
        "schema": WORKTREE_IDENTITY_SCHEMA,
        "git_head": canonical_head,
        "git_dirty": value["git_dirty"],
        "status_count": status_count,
        "status_sha256": _canonical_sha256(
            value.get("status_sha256"),
            field_name="worktree_status_sha256",
        ),
        "execution_file_count": execution_file_count,
        "execution_tree_sha256": _canonical_sha256(
            value.get("execution_tree_sha256"),
            field_name="execution_tree_sha256",
        ),
    }


def build_batch_draft_save_task_facts(
    *,
    task_id: int,
    store_id: int,
    product_ids: Iterable[Any],
    plan_snapshot_id: int,
    plan_snapshot_hash: str,
    path: str = "A",
) -> dict[str, Any]:
    """Build the exact immutable facts authorized for Path A batch draft save."""

    if str(path or "").strip().upper() != "A":
        raise BatchDraftAuthorizationError(
            "BATCH_PATH_FORBIDDEN",
            "batch_draft_save authorization only allows Path A",
        )
    normalized_product_ids: list[int] = []
    seen: set[int] = set()
    for raw_product_id in product_ids:
        product_id = _positive_id(raw_product_id, field_name="product_id")
        if product_id in seen:
            raise BatchDraftAuthorizationError(
                "BATCH_PRODUCT_DUPLICATE",
                "batch_draft_save product_ids must be unique",
            )
        seen.add(product_id)
        normalized_product_ids.append(product_id)
    if not normalized_product_ids:
        raise BatchDraftAuthorizationError(
            "BATCH_PRODUCT_IDS_REQUIRED",
            "batch_draft_save requires at least one product id",
        )
    unsigned = {
        "schema": BATCH_DRAFT_TASK_FACTS_SCHEMA,
        **_BATCH_DRAFT_STATIC_FACTS,
        "task_id": _positive_id(task_id, field_name="task_id"),
        "store_id": _positive_id(store_id, field_name="store_id"),
        "product_ids": normalized_product_ids,
        "plan_snapshot_id": _positive_id(
            plan_snapshot_id,
            field_name="plan_snapshot_id",
        ),
        "plan_snapshot_hash": _canonical_sha256(
            plan_snapshot_hash,
            field_name="plan_snapshot_hash",
        ),
        "path": "A",
    }
    if set(unsigned) | {"fingerprint"} != _BATCH_DRAFT_FACT_KEYS:
        raise BatchDraftAuthorizationError(
            "BATCH_TASK_FACTS_SHAPE_MISMATCH",
            "batch_draft_save task facts shape is invalid",
        )
    return {**unsigned, "fingerprint": _sha256(unsigned)}


def verify_exact_batch_draft_save_task_facts(
    facts: Mapping[str, Any],
) -> dict[str, bool | str]:
    """Validate exact keys, fixed semantics, identities and digest of batch facts."""

    if not isinstance(facts, Mapping):
        return _check(False, "STAGE_TASK_FACTS_SHAPE_MISMATCH")
    if facts.get("stage") != "batch_draft_save":
        return _check(False, "STAGE_TASK_FACTS_STAGE_MISMATCH")
    if set(facts) != _BATCH_DRAFT_FACT_KEYS:
        return _check(False, "STAGE_TASK_FACTS_SHAPE_MISMATCH")
    if facts.get("schema") != BATCH_DRAFT_TASK_FACTS_SCHEMA:
        return _check(False, "STAGE_TASK_FACTS_SCHEMA_MISMATCH")
    for field_name, expected in _BATCH_DRAFT_STATIC_FACTS.items():
        if facts.get(field_name) != expected:
            return _check(
                False,
                f"STAGE_TASK_FACTS_{field_name.upper()}_MISMATCH",
            )
    try:
        _positive_id(facts.get("task_id"), field_name="task_id")
        _positive_id(facts.get("store_id"), field_name="store_id")
        if facts.get("path") != "A":
            return _check(False, "BATCH_PATH_FORBIDDEN")
        product_ids = facts.get("product_ids")
        if not isinstance(product_ids, list) or not product_ids:
            return _check(False, "BATCH_PRODUCT_IDS_REQUIRED")
        seen: set[int] = set()
        for raw_product_id in product_ids:
            product_id = _positive_id(raw_product_id, field_name="product_id")
            if product_id in seen:
                return _check(False, "BATCH_PRODUCT_DUPLICATE")
            seen.add(product_id)
        _positive_id(facts.get("plan_snapshot_id"), field_name="plan_snapshot_id")
        _canonical_sha256(
            facts.get("plan_snapshot_hash"),
            field_name="plan_snapshot_hash",
        )
        stored_fingerprint = _canonical_sha256(
            facts.get("fingerprint"),
            field_name="stage_task_facts_fingerprint",
        )
        unsigned = {
            key: facts[key]
            for key in _BATCH_DRAFT_FACT_KEYS
            if key != "fingerprint"
        }
        if not hmac.compare_digest(stored_fingerprint, _sha256(unsigned)):
            return _check(False, "STAGE_TASK_FACTS_FINGERPRINT_MISMATCH")
    except BatchDraftAuthorizationError as exc:
        return _check(False, exc.reason_code)
    except (TypeError, ValueError, OverflowError):
        return _check(False, "STAGE_TASK_FACTS_INVALID_VALUE")
    return _check(True)


def verify_exact_stage_task_facts(
    facts: Mapping[str, Any],
    *,
    expected_stage: str,
) -> dict[str, bool | str]:
    """Compatibility name restricted to the sole supported batch stage."""

    if expected_stage != "batch_draft_save":
        return _check(False, "EXPECTED_STAGE_INVALID")
    return verify_exact_batch_draft_save_task_facts(facts)


def _authorization_context_unsigned(context: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(context, Mapping) or frozenset(context) not in {
        _AUTHORIZATION_CONTEXT_KEYS,
        _AUTHORIZATION_CONTEXT_KEYS - {"fingerprint"},
    }:
        raise BatchDraftAuthorizationError(
            "AUTH_CONTEXT_SHAPE_MISMATCH",
            "authorization context must contain the exact batch v2 fields",
        )
    if context.get("schema") != BATCH_DRAFT_AUTHORIZATION_CONTEXT_SCHEMA:
        raise BatchDraftAuthorizationError(
            "AUTH_CONTEXT_SCHEMA_MISMATCH",
            "authorization context schema mismatch",
        )
    facts = context.get("stage_task_facts")
    facts_check = verify_exact_batch_draft_save_task_facts(facts)
    if facts_check["ok"] is not True:
        raise BatchDraftAuthorizationError(
            str(facts_check["reason_code"]),
            "authorization context contains invalid batch task facts",
        )
    runtime_instance_id = _nonempty_text(
        context.get("runtime_instance_id"),
        field_name="runtime_instance_id",
    )
    browser_session_id = _nonempty_text(
        context.get("browser_session_id"),
        field_name="browser_session_id",
    )
    approved_by = _nonempty_text(
        context.get("approved_by"),
        field_name="approved_by",
    )
    git_head = _canonical_git_head(context.get("git_head"))
    l2_evidence_fingerprint = _canonical_sha256(
        context.get("l2_evidence_fingerprint"),
        field_name="l2_evidence_fingerprint",
    )
    if (
        runtime_instance_id != context.get("runtime_instance_id")
        or browser_session_id != context.get("browser_session_id")
        or approved_by != context.get("approved_by")
        or git_head != context.get("git_head")
    ):
        raise BatchDraftAuthorizationError(
            "AUTH_CONTEXT_NOT_CANONICAL",
            "authorization context text fields are not canonical",
        )
    return {
        "schema": BATCH_DRAFT_AUTHORIZATION_CONTEXT_SCHEMA,
        "stage_task_facts": _json_clone(dict(facts)),
        "runtime_instance_id": runtime_instance_id,
        "browser_session_id": browser_session_id,
        "git_head": git_head,
        "worktree_identity": _canonical_worktree_identity(
            context.get("worktree_identity"),
            git_head=git_head,
        ),
        "l2_evidence_fingerprint": l2_evidence_fingerprint,
        "approved_by": approved_by,
    }


def authorization_context_fingerprint(context: Mapping[str, Any]) -> str:
    """Recompute the batch v2 authorization digest from canonical facts."""

    return _sha256(_authorization_context_unsigned(context))


def build_authorization_context(
    *,
    stage_task_facts: Mapping[str, Any],
    runtime_instance_id: str,
    browser_session_id: str,
    git_head: str,
    worktree_identity: Mapping[str, Any],
    l2_evidence_fingerprint: str,
    approved_by: str,
) -> dict[str, Any]:
    """Bind one batch approval to exact task, runtime, browser and code facts."""

    unsigned = _authorization_context_unsigned(
        {
            "schema": BATCH_DRAFT_AUTHORIZATION_CONTEXT_SCHEMA,
            "stage_task_facts": _json_clone(dict(stage_task_facts)),
            "runtime_instance_id": runtime_instance_id,
            "browser_session_id": browser_session_id,
            "git_head": git_head,
            "worktree_identity": _json_clone(dict(worktree_identity)),
            "l2_evidence_fingerprint": l2_evidence_fingerprint,
            "approved_by": approved_by,
        }
    )
    return {**unsigned, "fingerprint": _sha256(unsigned)}


def verify_authorization_context(
    context: Mapping[str, Any],
) -> dict[str, bool | str]:
    if not isinstance(context, Mapping) or frozenset(context) != _AUTHORIZATION_CONTEXT_KEYS:
        return _check(False, "AUTH_CONTEXT_SHAPE_MISMATCH")
    try:
        stored_fingerprint = _canonical_sha256(
            context.get("fingerprint"),
            field_name="authorization_context_fingerprint",
        )
        recomputed_fingerprint = authorization_context_fingerprint(context)
    except BatchDraftAuthorizationError as exc:
        return _check(False, exc.reason_code)
    except (TypeError, ValueError, OverflowError):
        return _check(False, "AUTH_CONTEXT_INVALID_VALUE")
    if not hmac.compare_digest(stored_fingerprint, recomputed_fingerprint):
        return _check(False, "AUTH_CONTEXT_FINGERPRINT_MISMATCH")
    return _check(True)


def compare_authorization_context(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> dict[str, bool | str]:
    """Timing-safely compare two internally valid batch v2 contexts."""

    expected_check = verify_authorization_context(expected)
    if expected_check["ok"] is not True:
        return _check(False, "EXPECTED_AUTH_CONTEXT_INVALID")
    actual_check = verify_authorization_context(actual)
    if actual_check["ok"] is not True:
        return actual_check
    try:
        expected_digest = authorization_context_fingerprint(expected)
        actual_digest = authorization_context_fingerprint(actual)
    except BatchDraftAuthorizationError:
        return _check(False, "AUTH_CONTEXT_INVALID_VALUE")
    if not hmac.compare_digest(expected_digest, actual_digest):
        return _check(False, "AUTH_CONTEXT_MISMATCH")
    return _check(True)


__all__ = [
    "BATCH_DRAFT_AUTHORIZATION_CONTEXT_SCHEMA",
    "BATCH_DRAFT_TASK_FACTS_SCHEMA",
    "BATCH_DRAFT_SAVE_CONFIRMATION",
    "BATCH_DRAFT_SAVE_PUBLISH_SCENE",
    "BatchDraftAuthorizationError",
    "authorization_context_fingerprint",
    "build_authorization_context",
    "build_batch_draft_save_task_facts",
    "compare_authorization_context",
    "verify_authorization_context",
    "verify_exact_batch_draft_save_task_facts",
    "verify_exact_stage_task_facts",
]
