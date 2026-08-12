from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from collections.abc import Iterable, Mapping
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, parse_qs, urlsplit, urlunsplit


SOURCE_IDENTITY_SCHEMA = "dxm.source.identity.v1"
CLAIM_TARGET_IDENTITY_SCHEMA = "dxm.claim_target.identity.v1"
DRAFT_BOX_PROOF_SCHEMA = "dxm.draft_box.proof.v1"
DRAFT_BOX_OBSERVATION_SCHEMA = "dxm.draft_box.observation.v1"
STAGE_TASK_FACTS_SCHEMA = "dxm.two_stage.task_facts.v1"
BATCH_DRAFT_TASK_FACTS_SCHEMA = "dxm.batch_draft_save.task_facts.v1"
STAGE_A_CONFIRMATION = "确认将该已有商品认领到商品箱"
STAGE_B_CONFIRMATION = "CONFIRM_DXM_SAVE_ONLY"
STAGE_A_PUBLISH_SCENE = "CONTROLLED_CLAIM_TO_DRAFT_ONLY"
STAGE_B_PUBLISH_SCENE = "SMT_SEMI_MANAGED_SAVE_ONLY"
AUTHORIZATION_CONTEXT_SCHEMA = "dxm.authorization.context.v1"
AUTHORIZATION_CONTEXT_SCHEMA_V2 = "dxm.authorization.context.v2"
WORKTREE_IDENTITY_SCHEMA = "dxm.git-worktree.identity.v1"
_SOURCE_IDENTITY_KEYS = frozenset({"schema", "primary_url", "urls", "fingerprint"})
_CLAIM_TARGET_IDENTITY_KEYS = frozenset(
    {"schema", "source_identity", "keyword", "category_name", "fingerprint"}
)
_DRAFT_BOX_PROOF_KEYS = frozenset(
    {
        "schema",
        "claim_task_id",
        "claim_job_id",
        "store_id",
        "product_id",
        "claim_target_identity",
        "claim_target_fingerprint",
        "stage_a_task_facts_fingerprint",
        "proof_content",
        "proof_content_sha256",
        "fingerprint",
    }
)
_DRAFT_BOX_OBSERVATION_KEYS = frozenset(
    {
        "schema",
        "verification_state",
        "action",
        "draft_box_verified",
        "page_url",
        "authorized_target_identity",
        "authorized_target_fingerprint",
        "observed_source_identity",
        "observed_store_identity",
        "matched_by",
        "match_evidence",
        "observed_product_identity",
        "observed_row_identity",
        "evidence_ref",
    }
)
_STAGE_A_FACT_KEYS = frozenset(
    {
        "schema",
        "stage",
        "mode",
        "confirmation",
        "publish_scene",
        "action",
        "task_id",
        "job_id",
        "store_id",
        "target_identity",
        "fingerprint",
    }
)
_STAGE_B_FACT_KEYS = frozenset(
    (_STAGE_A_FACT_KEYS - {"target_identity"})
    | {
        "source_identity",
        "target_identity",
        "claim_target_fingerprint",
        "stage_a_task_facts_fingerprint",
        "product_id",
        "claim_task_id",
        "claim_job_id",
        "draft_box_proof_fingerprint",
    }
)
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
_STAGE_STATIC_FACTS = {
    "stage_a": {
        "mode": "claim_only",
        "confirmation": STAGE_A_CONFIRMATION,
        "publish_scene": STAGE_A_PUBLISH_SCENE,
        "action": "claim_to_draft",
    },
    "stage_b": {
        "mode": "single_save",
        "confirmation": STAGE_B_CONFIRMATION,
        "publish_scene": STAGE_B_PUBLISH_SCENE,
        "action": "save_only",
    },
    "batch_draft_save": {
        "mode": "batch_draft_save",
        "confirmation": STAGE_B_CONFIRMATION,
        "publish_scene": STAGE_B_PUBLISH_SCENE,
        "action": "batch_draft_save_only",
    },
}
_AUTHORIZATION_CONTEXT_KEYS = frozenset(
    {
        "schema",
        "stage_task_facts",
        "runtime_instance_id",
        "browser_session_id",
        "git_head",
        "l2_evidence_fingerprint",
        "approved_by",
        "fingerprint",
    }
)
_AUTHORIZATION_CONTEXT_V2_KEYS = frozenset(
    {*_AUTHORIZATION_CONTEXT_KEYS, "worktree_identity"}
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


class TwoStageContractError(ValueError):
    """Invalid input to a pure two-stage contract helper."""

    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


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
        raise TwoStageContractError(
            "VALUE_NOT_JSON_SERIALIZABLE",
            "contract value must be JSON serializable",
        ) from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest().upper()


def _json_clone(value: Any) -> Any:
    return json.loads(_canonical_json(value))


def _check(ok: bool, reason_code: str = "OK") -> dict[str, bool | str]:
    return {"ok": ok, "reason_code": reason_code}


def _stable_verifier(reason_code: str):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except (TwoStageContractError, TypeError, ValueError, OverflowError):
                return _check(False, reason_code)

        return wrapped

    return decorate


def _positive_id(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TwoStageContractError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be a positive integer",
        )
    return value


def _canonical_sha256(value: Any, *, field_name: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or digest != digest.upper():
        raise TwoStageContractError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be an uppercase SHA-256 hex digest",
        )
    try:
        int(digest, 16)
    except ValueError as exc:
        raise TwoStageContractError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be an uppercase SHA-256 hex digest",
        ) from exc
    return digest


def _nonempty_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TwoStageContractError(
            f"{field_name.upper()}_REQUIRED",
            f"{field_name} is required",
        )
    return value.strip()


def _canonical_evidence_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {'path', 'sha256', 'size'}:
        raise TwoStageContractError(
            'EVIDENCE_REF_SHAPE_MISMATCH',
            'evidence_ref must contain exactly path, sha256, and size',
        )
    path_text = _nonempty_text(value.get('path'), field_name='evidence_ref_path')
    if not Path(path_text).is_absolute():
        raise TwoStageContractError(
            'EVIDENCE_REF_PATH_NOT_ABSOLUTE',
            'evidence_ref path must be absolute',
        )
    return {
        'path': str(Path(path_text)),
        'sha256': _canonical_sha256(value.get('sha256'), field_name='evidence_ref_sha256'),
        'size': _positive_id(value.get('size'), field_name='evidence_ref_size'),
    }


def _canonical_git_head(value: Any) -> str:
    git_head = _nonempty_text(value, field_name="git_head").lower()
    if len(git_head) not in {40, 64}:
        raise TwoStageContractError(
            "GIT_HEAD_INVALID",
            "git_head must be a full 40- or 64-character hex object ID",
        )
    try:
        int(git_head, 16)
    except ValueError as exc:
        raise TwoStageContractError(
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
        raise TwoStageContractError(
            "WORKTREE_IDENTITY_SHAPE_MISMATCH",
            "worktree identity must contain the exact v1 fields",
        )
    if value.get("schema") != WORKTREE_IDENTITY_SCHEMA:
        raise TwoStageContractError(
            "WORKTREE_IDENTITY_SCHEMA_MISMATCH",
            "worktree identity schema mismatch",
        )
    canonical_head = _canonical_git_head(value.get("git_head"))
    if canonical_head != git_head:
        raise TwoStageContractError(
            "WORKTREE_IDENTITY_HEAD_MISMATCH",
            "worktree identity HEAD differs from authorization HEAD",
        )
    if type(value.get("git_dirty")) is not bool:
        raise TwoStageContractError(
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
        raise TwoStageContractError(
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


def _canonical_source_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TwoStageContractError("SOURCE_URL_REQUIRED", "source URL is required")
    raw = value.strip()
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in raw):
        raise TwoStageContractError("SOURCE_URL_INVALID", "source URL contains whitespace or controls")
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        raise TwoStageContractError("SOURCE_URL_INVALID", "source URL contains invalid percent encoding")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise TwoStageContractError("SOURCE_URL_INVALID", "source URL is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise TwoStageContractError(
            "SOURCE_URL_INVALID",
            "source URL must be an absolute HTTP(S) URL",
        )
    if parsed.username is not None or parsed.password is not None:
        raise TwoStageContractError(
            "SOURCE_URL_CREDENTIALS_FORBIDDEN",
            "source URL must not contain credentials",
        )
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise TwoStageContractError("SOURCE_URL_INVALID", "source URL host is invalid") from exc
    if not hostname:
        raise TwoStageContractError("SOURCE_URL_INVALID", "source URL host is invalid")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        labels = hostname.split(".")
        invalid_dns = (
            len(hostname) > 253
            or any(
                not label
                or len(label) > 63
                or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
                for label in labels
            )
            or (all(character.isdigit() or character == "." for character in hostname))
        )
        if invalid_dns:
            raise TwoStageContractError("SOURCE_URL_INVALID", "source URL host is invalid")
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    canonical = SplitResult(
        scheme=scheme,
        netloc=host,
        path=parsed.path or "/",
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(canonical)


def canonical_source_identity(
    primary_url: str,
    source_urls: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a stable identity without dropping or reordering URL query data."""

    primary = _canonical_source_url(primary_url)
    if isinstance(source_urls, (str, bytes)):
        raise TwoStageContractError(
            "SOURCE_URLS_INVALID",
            "source_urls must be an iterable of URLs, not a string",
        )
    urls = {primary}
    for value in source_urls or ():
        urls.add(_canonical_source_url(value))
    unsigned = {
        "schema": SOURCE_IDENTITY_SCHEMA,
        "primary_url": primary,
        "urls": sorted(urls),
    }
    return {**unsigned, "fingerprint": _sha256(unsigned)}


def is_supported_product_detail_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname or port is not None:
        return False
    host = parsed.hostname.casefold().rstrip(".")
    path = parsed.path

    def host_matches(domain: str) -> bool:
        return host == domain or host.endswith(f".{domain}")

    if host_matches("dianxiaomi.com"):
        return False
    if host_matches("1688.com"):
        return re.fullmatch(r"/offer/[0-9]+\.html", path, flags=re.IGNORECASE) is not None
    if host_matches("yangkeduo.com"):
        goods_ids = parse_qs(parsed.query, keep_blank_values=True).get("goods_id", [])
        return (
            re.fullmatch(r"/goods2?\.html", path, flags=re.IGNORECASE) is not None
            and len(goods_ids) == 1
            and re.fullmatch(r"[0-9]+", goods_ids[0]) is not None
        )
    if host_matches("aliexpress.com"):
        return re.fullmatch(r"/item/[0-9]+\.html", path, flags=re.IGNORECASE) is not None
    return False


def _optional_match_hint(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TwoStageContractError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be text",
        )
    normalized = " ".join(value.split())
    return normalized or None


def _normalized_match_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _contains_normalized_hint(observed_text: str, hint: str) -> bool:
    normalized_hint = _normalized_match_text(hint)
    if any(character.isascii() and character.isalnum() for character in normalized_hint):
        pattern = rf"(?<![0-9a-z_]){re.escape(normalized_hint)}(?![0-9a-z_])"
        return re.search(pattern, observed_text) is not None
    return normalized_hint in observed_text


def canonical_claim_target_identity(
    source_url: str | None = None,
    source_urls: Iterable[str] | None = None,
    *,
    keyword: str | None = None,
    category_name: str | None = None,
) -> dict[str, Any]:
    """Identify a Stage A target from real URL and/or operator match hints."""

    if isinstance(source_urls, (str, bytes)):
        raise TwoStageContractError(
            "SOURCE_URLS_INVALID",
            "source_urls must be an iterable of URLs, not a string",
        )
    candidate_urls = list(source_urls or ())
    source: dict[str, Any] | None = None
    if source_url is not None and str(source_url).strip():
        source = canonical_source_identity(source_url, candidate_urls)
    elif candidate_urls:
        canonical_candidates = sorted({_canonical_source_url(value) for value in candidate_urls})
        source = canonical_source_identity(canonical_candidates[0], canonical_candidates)
    exact_keyword = _optional_match_hint(keyword, field_name="keyword")
    exact_category = _optional_match_hint(category_name, field_name="category_name")
    if source is None and exact_keyword is None and exact_category is None:
        raise TwoStageContractError(
            "CLAIM_TARGET_REQUIRED",
            "claim target requires a source URL, keyword, or category",
        )
    unsigned = {
        "schema": CLAIM_TARGET_IDENTITY_SCHEMA,
        "source_identity": source,
        "keyword": exact_keyword,
        "category_name": exact_category,
    }
    return {**unsigned, "fingerprint": _sha256(unsigned)}


def _validated_source_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_IDENTITY_KEYS:
        raise TwoStageContractError(
            "SOURCE_IDENTITY_SHAPE_MISMATCH",
            "source identity fields do not match the v1 contract",
        )
    urls = value.get("urls")
    if not isinstance(urls, list):
        raise TwoStageContractError(
            "SOURCE_IDENTITY_SHAPE_MISMATCH",
            "source identity urls must be a list",
        )
    rebuilt = canonical_source_identity(value.get("primary_url"), urls)
    if value.get("schema") != SOURCE_IDENTITY_SCHEMA:
        raise TwoStageContractError(
            "SOURCE_IDENTITY_SCHEMA_MISMATCH",
            "source identity schema mismatch",
        )
    actual_fingerprint = str(value.get("fingerprint") or "")
    if not hmac.compare_digest(actual_fingerprint, rebuilt["fingerprint"]):
        raise TwoStageContractError(
            "SOURCE_IDENTITY_FINGERPRINT_MISMATCH",
            "source identity fingerprint mismatch",
        )
    if _canonical_json(dict(value)) != _canonical_json(rebuilt):
        raise TwoStageContractError(
            "SOURCE_IDENTITY_NOT_CANONICAL",
            "source identity is not in canonical form",
        )
    return rebuilt


def _validated_claim_target_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _CLAIM_TARGET_IDENTITY_KEYS:
        raise TwoStageContractError(
            "CLAIM_TARGET_IDENTITY_SHAPE_MISMATCH",
            "claim target identity fields do not match the v1 contract",
        )
    if value.get("schema") != CLAIM_TARGET_IDENTITY_SCHEMA:
        raise TwoStageContractError(
            "CLAIM_TARGET_IDENTITY_SCHEMA_MISMATCH",
            "claim target identity schema mismatch",
        )
    source = value.get("source_identity")
    rebuilt_source = _validated_source_identity(source) if source is not None else None
    rebuilt = canonical_claim_target_identity(
        source_url=rebuilt_source["primary_url"] if rebuilt_source else None,
        source_urls=rebuilt_source["urls"] if rebuilt_source else None,
        keyword=value.get("keyword"),
        category_name=value.get("category_name"),
    )
    if not hmac.compare_digest(str(value.get("fingerprint") or ""), rebuilt["fingerprint"]):
        raise TwoStageContractError(
            "CLAIM_TARGET_IDENTITY_FINGERPRINT_MISMATCH",
            "claim target identity fingerprint mismatch",
        )
    if _canonical_json(dict(value)) != _canonical_json(rebuilt):
        raise TwoStageContractError(
            "CLAIM_TARGET_IDENTITY_NOT_CANONICAL",
            "claim target identity is not in canonical form",
        )
    return rebuilt


def _validated_draft_box_observation(
    value: Any,
    *,
    expected_target_identity: Mapping[str, Any],
    expected_store_id: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _DRAFT_BOX_OBSERVATION_KEYS:
        raise TwoStageContractError(
            "DRAFT_BOX_PROOF_CONTENT_SHAPE_MISMATCH",
            "draft-box proof content must use the exact v1 observation fields",
        )
    if value.get("schema") != DRAFT_BOX_OBSERVATION_SCHEMA:
        raise TwoStageContractError(
            "DRAFT_BOX_OBSERVATION_SCHEMA_MISMATCH",
            "draft-box observation schema mismatch",
        )
    if value.get("verification_state") != "VERIFY_DRAFT_BOX_CLAIM":
        raise TwoStageContractError(
            "DRAFT_BOX_OBSERVATION_STATE_MISMATCH",
            "draft-box observation state mismatch",
        )
    if value.get("action") != "verify_draft_box_claim":
        raise TwoStageContractError(
            "DRAFT_BOX_OBSERVATION_ACTION_MISMATCH",
            "draft-box observation action mismatch",
        )
    if value.get("draft_box_verified") is not True:
        raise TwoStageContractError("DRAFT_BOX_NOT_VERIFIED", "draft box was not verified")
    page_url = _canonical_source_url(value.get("page_url"))
    page = urlsplit(page_url)
    page_host = str(page.hostname or "").lower()
    if (
        page.scheme != "https"
        or not (page_host == "dianxiaomi.com" or page_host.endswith(".dianxiaomi.com"))
        or page.path.rstrip("/") != "/web/smt/smtProductList/draft"
    ):
        raise TwoStageContractError(
            "DRAFT_BOX_PAGE_URL_INVALID",
            "draft-box observation must reference the DXM draft-box page",
        )
    expected_target = _validated_claim_target_identity(expected_target_identity)
    authorized_target = _validated_claim_target_identity(value.get("authorized_target_identity"))
    if not hmac.compare_digest(expected_target["fingerprint"], authorized_target["fingerprint"]):
        raise TwoStageContractError(
            "DRAFT_BOX_AUTHORIZED_TARGET_MISMATCH",
            "observation target does not match Stage A authorization",
        )
    authorized_target_fingerprint = _canonical_sha256(
        value.get("authorized_target_fingerprint"),
        field_name="authorized_target_fingerprint",
    )
    if not hmac.compare_digest(authorized_target_fingerprint, expected_target["fingerprint"]):
        raise TwoStageContractError(
            "DRAFT_BOX_AUTHORIZED_TARGET_FINGERPRINT_MISMATCH",
            "observation target fingerprint does not match Stage A authorization",
        )
    observed_store = value.get("observed_store_identity")
    observed_store_keys = {
        "store_id",
        "store_name",
        "selected",
        "selected_store_names",
        "selection_evidence",
        "draft_box_cell_evidence",
    }
    if not isinstance(observed_store, Mapping) or set(observed_store) != observed_store_keys:
        raise TwoStageContractError(
            "DRAFT_BOX_OBSERVED_STORE_SHAPE_MISMATCH",
            "observed store identity must contain exact selection and structured cell evidence",
        )
    observed_store_id = _positive_id(
        observed_store.get("store_id"),
        field_name="observed_store_id",
    )
    exact_expected_store_id = _positive_id(expected_store_id, field_name="store_id")
    if observed_store_id != exact_expected_store_id:
        raise TwoStageContractError(
            "DRAFT_BOX_OBSERVED_STORE_MISMATCH",
            "observed store does not match Stage A store",
        )
    observed_store_name = _nonempty_text(
        observed_store.get("store_name"),
        field_name="observed_store_name",
    )
    if observed_store.get("selected") is not True:
        raise TwoStageContractError(
            "DRAFT_BOX_STORE_NOT_SELECTED",
            "observed store must be selected in the claim dialog",
        )
    raw_selected_store_names = observed_store.get("selected_store_names")
    if not isinstance(raw_selected_store_names, list):
        raise TwoStageContractError(
            "DRAFT_BOX_SELECTED_STORE_NAMES_INVALID",
            "selected_store_names must be a list of non-empty store names",
        )
    selected_store_names: list[str] = []
    selected_store_keys: set[str] = set()
    for raw_store_name in raw_selected_store_names:
        if not isinstance(raw_store_name, str) or not raw_store_name.strip():
            raise TwoStageContractError(
                "DRAFT_BOX_SELECTED_STORE_NAMES_INVALID",
                "selected_store_names must be a list of non-empty store names",
            )
        selected_store_name = " ".join(raw_store_name.split())
        if selected_store_name not in selected_store_keys:
            selected_store_keys.add(selected_store_name)
            selected_store_names.append(selected_store_name)
    if selected_store_names != [observed_store_name]:
        raise TwoStageContractError(
            "DRAFT_BOX_SELECTED_STORE_SET_MISMATCH",
            "selected_store_names must contain only the observed store",
        )
    selection_evidence = observed_store.get("selection_evidence")
    if not isinstance(selection_evidence, Mapping) or not selection_evidence:
        raise TwoStageContractError(
            "DRAFT_BOX_STORE_SELECTION_EVIDENCE_REQUIRED",
            "observed store requires non-empty selection readback evidence",
        )
    selection_class = str(selection_evidence.get("class_name") or "")
    selection_proven = (
        selection_evidence.get("input_checked") is True
        or str(selection_evidence.get("aria_checked") or "").lower() == "true"
        or str(selection_evidence.get("aria_selected") or "").lower() == "true"
        or re.search(r"(?:^|[-_\s])(checked|selected)(?:$|[-_\s])", selection_class, re.IGNORECASE) is not None
    )
    if not selection_proven:
        raise TwoStageContractError(
            "DRAFT_BOX_STORE_SELECTION_EVIDENCE_INVALID",
            "store selection readback does not prove selected state",
        )
    store_cell_evidence = observed_store.get("draft_box_cell_evidence")
    if not isinstance(store_cell_evidence, Mapping):
        raise TwoStageContractError(
            "DRAFT_BOX_STORE_CELL_EVIDENCE_REQUIRED",
            "observed store requires structured draft-box cell evidence",
        )
    if store_cell_evidence.get("source") != "structured_store_cell":
        raise TwoStageContractError(
            "DRAFT_BOX_STORE_CELL_SOURCE_INVALID",
            "store cell evidence must come from a structured store cell",
        )
    cell_store_name = _nonempty_text(
        store_cell_evidence.get("store_name"),
        field_name="draft_box_cell_store_name",
    )
    if cell_store_name != observed_store_name:
        raise TwoStageContractError(
            "DRAFT_BOX_STORE_CELL_NAME_MISMATCH",
            "store cell evidence must name the observed store exactly",
        )
    cell_text = _nonempty_text(
        store_cell_evidence.get("cell_text"),
        field_name="draft_box_cell_text",
    )
    if not re.search(
        rf"(?<!\w){re.escape(_normalized_match_text(observed_store_name))}(?!\w)",
        _normalized_match_text(cell_text),
    ):
        raise TwoStageContractError(
            "DRAFT_BOX_STORE_CELL_TEXT_MISMATCH",
            "structured store cell text must contain the observed store at exact boundaries",
        )
    raw_observed_source = value.get("observed_source_identity")
    observed_source = (
        _validated_source_identity(raw_observed_source)
        if raw_observed_source is not None
        else None
    )
    matched_by = value.get("matched_by")
    match_evidence = value.get("match_evidence")
    if not isinstance(matched_by, list) or not matched_by or not isinstance(match_evidence, Mapping):
        raise TwoStageContractError(
            "DRAFT_BOX_MATCH_EVIDENCE_REQUIRED",
            "observation requires matched_by and match_evidence",
        )
    product_identity = _nonempty_text(
        value.get("observed_product_identity"),
        field_name="observed_product_identity",
    )
    row_identity = _nonempty_text(
        value.get("observed_row_identity"),
        field_name="observed_row_identity",
    )
    evidence_ref = _canonical_evidence_ref(value.get("evidence_ref"))
    authorized_source = expected_target.get("source_identity")
    if authorized_source is not None:
        if observed_source is None:
            raise TwoStageContractError(
                "DRAFT_BOX_OBSERVED_SOURCE_REQUIRED",
                "URL-authorized claim requires an observed source identity",
            )
        authorized_urls = set(authorized_source["urls"])
        observed_urls = set(observed_source["urls"])
        if (
            observed_source["primary_url"] not in authorized_urls
            or not observed_urls.issubset(authorized_urls)
        ):
            raise TwoStageContractError(
                "DRAFT_BOX_OBSERVED_SOURCE_UNAUTHORIZED",
                "observed source is outside the Stage A authorized URLs",
            )
        expected_matched_by = ["source_url"]
        expected_match_evidence = {"source_url": observed_source["primary_url"]}
    else:
        if observed_source is None:
            raise TwoStageContractError(
                "DRAFT_BOX_OBSERVED_SOURCE_REQUIRED",
                "hint-authorized claim requires an observed source identity",
            )
        allowed_hint_order = [
            key
            for key in ("keyword", "category_name")
            if expected_target.get(key) is not None
        ]
        observed_texts = (
            _normalized_match_text(product_identity),
            _normalized_match_text(row_identity),
        )
        derived_matched_by = [
            key
            for key in allowed_hint_order
            if any(
                _contains_normalized_hint(observed_text, expected_target[key])
                for observed_text in observed_texts
            )
        ]
        required_hint = "keyword" if expected_target.get("keyword") is not None else "category_name"
        if required_hint not in derived_matched_by:
            raise TwoStageContractError(
                "DRAFT_BOX_REQUIRED_HINT_NOT_OBSERVED",
                "observed product and row identities do not contain the required hint",
            )
        if matched_by != derived_matched_by:
            raise TwoStageContractError(
                "DRAFT_BOX_MATCH_EVIDENCE_MISMATCH",
                "matched_by does not equal the matches derived from observed identities",
            )
        expected_matched_by = derived_matched_by
        expected_match_evidence = {key: expected_target[key] for key in expected_matched_by}
    if matched_by != expected_matched_by or dict(match_evidence) != expected_match_evidence:
        raise TwoStageContractError(
            "DRAFT_BOX_MATCH_EVIDENCE_MISMATCH",
            "match evidence does not exactly support the authorized target",
        )
    canonical = {
        "schema": DRAFT_BOX_OBSERVATION_SCHEMA,
        "verification_state": "VERIFY_DRAFT_BOX_CLAIM",
        "action": "verify_draft_box_claim",
        "draft_box_verified": True,
        "page_url": page_url,
        "authorized_target_identity": authorized_target,
        "authorized_target_fingerprint": authorized_target_fingerprint,
        "observed_source_identity": observed_source,
        "observed_store_identity": {
            "store_id": observed_store_id,
            "store_name": observed_store_name,
            "selected": True,
            "selected_store_names": list(selected_store_names),
            "selection_evidence": _json_clone(dict(selection_evidence)),
            "draft_box_cell_evidence": _json_clone(dict(store_cell_evidence)),
        },
        "matched_by": expected_matched_by,
        "match_evidence": expected_match_evidence,
        "observed_product_identity": product_identity,
        "observed_row_identity": row_identity,
        "evidence_ref": evidence_ref,
    }
    return canonical


def build_draft_box_proof(
    *,
    stage_a_task_facts: Mapping[str, Any],
    product_id: int,
    proof_content: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a tamper-evident proof bound to one exact Stage A result."""

    stage_check = verify_exact_stage_task_facts(stage_a_task_facts, expected_stage="stage_a")
    if stage_check["ok"] is not True:
        raise TwoStageContractError(
            str(stage_check["reason_code"]),
            "draft-box proof requires valid Stage A task facts",
        )
    stage_a = _json_clone(dict(stage_a_task_facts))
    task_id = stage_a["task_id"]
    job_id = stage_a["job_id"]
    exact_store_id = stage_a["store_id"]
    exact_product_id = _positive_id(product_id, field_name="product_id")
    target = _validated_claim_target_identity(stage_a["target_identity"])
    content = _validated_draft_box_observation(
        proof_content,
        expected_target_identity=target,
        expected_store_id=exact_store_id,
    )
    unsigned = {
        "schema": DRAFT_BOX_PROOF_SCHEMA,
        "claim_task_id": task_id,
        "claim_job_id": job_id,
        "store_id": exact_store_id,
        "product_id": exact_product_id,
        "claim_target_identity": target,
        "claim_target_fingerprint": target["fingerprint"],
        "stage_a_task_facts_fingerprint": stage_a["fingerprint"],
        "proof_content": content,
        "proof_content_sha256": _sha256(content),
    }
    return {**unsigned, "fingerprint": _sha256(unsigned)}


@_stable_verifier("DRAFT_BOX_PROOF_INVALID_VALUE")
def verify_draft_box_proof(
    proof: Mapping[str, Any],
    *,
    stage_a_task_facts: Mapping[str, Any],
    product_id: int,
) -> dict[str, bool | str]:
    """Verify proof integrity and every expected Stage A binding."""

    if not isinstance(proof, Mapping) or set(proof) != _DRAFT_BOX_PROOF_KEYS:
        return _check(False, "DRAFT_BOX_PROOF_SHAPE_MISMATCH")
    if proof.get("schema") != DRAFT_BOX_PROOF_SCHEMA:
        return _check(False, "DRAFT_BOX_PROOF_SCHEMA_MISMATCH")
    stage_check = verify_exact_stage_task_facts(stage_a_task_facts, expected_stage="stage_a")
    if stage_check["ok"] is not True:
        return _check(False, "EXPECTED_STAGE_A_TASK_FACTS_INVALID")
    stage_a = _json_clone(dict(stage_a_task_facts))
    try:
        expected_product_id = _positive_id(product_id, field_name="product_id")
    except TwoStageContractError as exc:
        return _check(False, f"EXPECTED_{exc.reason_code}")
    try:
        _positive_id(proof.get("claim_task_id"), field_name="claim_task_id")
        _positive_id(proof.get("claim_job_id"), field_name="claim_job_id")
        _positive_id(proof.get("store_id"), field_name="store_id")
        _positive_id(proof.get("product_id"), field_name="product_id")
        stored_target = _validated_claim_target_identity(proof.get("claim_target_identity"))
        claim_target_fingerprint = _canonical_sha256(
            proof.get("claim_target_fingerprint"),
            field_name="claim_target_fingerprint",
        )
        stage_a_fingerprint = _canonical_sha256(
            proof.get("stage_a_task_facts_fingerprint"),
            field_name="stage_a_task_facts_fingerprint",
        )
    except TwoStageContractError as exc:
        return _check(False, exc.reason_code)
    expected_target = _validated_claim_target_identity(stage_a["target_identity"])
    if not hmac.compare_digest(stored_target["fingerprint"], expected_target["fingerprint"]):
        return _check(False, "DRAFT_BOX_PROOF_TARGET_MISMATCH")
    if not hmac.compare_digest(claim_target_fingerprint, stored_target["fingerprint"]):
        return _check(False, "DRAFT_BOX_PROOF_TARGET_FINGERPRINT_MISMATCH")
    expected_bindings = (
        ("claim_task_id", stage_a["task_id"], "DRAFT_BOX_PROOF_TASK_MISMATCH"),
        ("claim_job_id", stage_a["job_id"], "DRAFT_BOX_PROOF_JOB_MISMATCH"),
        ("store_id", stage_a["store_id"], "DRAFT_BOX_PROOF_STORE_MISMATCH"),
        ("product_id", expected_product_id, "DRAFT_BOX_PROOF_PRODUCT_MISMATCH"),
    )
    for field_name, expected, reason_code in expected_bindings:
        if proof.get(field_name) != expected:
            return _check(False, reason_code)
    if not hmac.compare_digest(stage_a_fingerprint, stage_a["fingerprint"]):
        return _check(False, "DRAFT_BOX_PROOF_STAGE_A_FINGERPRINT_MISMATCH")
    content = proof.get("proof_content")
    if not isinstance(content, Mapping):
        return _check(False, "DRAFT_BOX_PROOF_CONTENT_SHAPE_MISMATCH")
    recomputed_content_sha = _sha256(dict(content))
    if not hmac.compare_digest(
        str(proof.get("proof_content_sha256") or ""),
        recomputed_content_sha,
    ):
        return _check(False, "DRAFT_BOX_PROOF_CONTENT_DIGEST_MISMATCH")
    try:
        canonical_content = _validated_draft_box_observation(
            content,
            expected_target_identity=stored_target,
            expected_store_id=proof.get("store_id"),
        )
    except TwoStageContractError as exc:
        return _check(False, exc.reason_code)
    if _canonical_json(dict(content)) != _canonical_json(canonical_content):
        return _check(False, "DRAFT_BOX_PROOF_CONTENT_NOT_CANONICAL")
    unsigned = {key: proof[key] for key in _DRAFT_BOX_PROOF_KEYS if key != "fingerprint"}
    recomputed_fingerprint = _sha256(unsigned)
    if not hmac.compare_digest(str(proof.get("fingerprint") or ""), recomputed_fingerprint):
        return _check(False, "DRAFT_BOX_PROOF_FINGERPRINT_MISMATCH")
    return _check(True)


def _build_stage_task_facts(
    *,
    stage: str,
    task_id: int,
    job_id: int,
    store_id: int,
    identity_field: str,
    identity_value: Mapping[str, Any] | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    static = _STAGE_STATIC_FACTS[stage]
    unsigned = {
        "schema": STAGE_TASK_FACTS_SCHEMA,
        "stage": stage,
        **static,
        "task_id": _positive_id(task_id, field_name="task_id"),
        "job_id": _positive_id(job_id, field_name="job_id"),
        "store_id": _positive_id(store_id, field_name="store_id"),
        identity_field: (
            _validated_claim_target_identity(identity_value)
            if identity_field == "target_identity"
            else (
                _validated_source_identity(identity_value)
                if identity_value is not None
                else None
            )
        ),
        **dict(extra or {}),
    }
    return {**unsigned, "fingerprint": _sha256(unsigned)}


def build_stage_a_task_facts(
    *,
    task_id: int,
    job_id: int,
    store_id: int,
    target_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the exact immutable facts authorized by Stage A approval."""

    return _build_stage_task_facts(
        stage="stage_a",
        task_id=task_id,
        job_id=job_id,
        store_id=store_id,
        identity_field="target_identity",
        identity_value=target_identity,
    )


def build_batch_draft_save_task_facts(
    *,
    task_id: int,
    store_id: int,
    product_ids: Iterable[Any],
    plan_snapshot_id: int,
    plan_snapshot_hash: str,
    path: str = "A",
) -> dict[str, Any]:
    """Build immutable facts authorized for batch_draft_save Path A only."""

    normalized_path = str(path or "").strip().upper()
    if normalized_path != "A":
        raise TwoStageContractError(
            "BATCH_PATH_FORBIDDEN",
            "batch_draft_save authorization only allows Path A",
        )
    ids: list[int] = []
    seen: set[int] = set()
    for raw in product_ids:
        value = _positive_id(raw, field_name="product_id")
        if value in seen:
            raise TwoStageContractError(
                "BATCH_PRODUCT_DUPLICATE",
                "batch_draft_save product_ids must be unique",
            )
        seen.add(value)
        ids.append(value)
    if not ids:
        raise TwoStageContractError(
            "BATCH_PRODUCT_IDS_REQUIRED",
            "batch_draft_save requires at least one product id",
        )
    snapshot_hash = _canonical_sha256(
        plan_snapshot_hash,
        field_name="plan_snapshot_hash",
    )
    static = _STAGE_STATIC_FACTS["batch_draft_save"]
    unsigned = {
        "schema": BATCH_DRAFT_TASK_FACTS_SCHEMA,
        "stage": "batch_draft_save",
        **static,
        "task_id": _positive_id(task_id, field_name="task_id"),
        "store_id": _positive_id(store_id, field_name="store_id"),
        "product_ids": ids,
        "plan_snapshot_id": _positive_id(plan_snapshot_id, field_name="plan_snapshot_id"),
        "plan_snapshot_hash": snapshot_hash,
        "path": "A",
    }
    if set(unsigned) | {"fingerprint"} != _BATCH_DRAFT_FACT_KEYS:
        raise TwoStageContractError(
            "BATCH_TASK_FACTS_SHAPE_MISMATCH",
            "batch_draft_save task facts shape is invalid",
        )
    return {**unsigned, "fingerprint": _sha256(unsigned)}


def build_stage_b_task_facts(
    *,
    task_id: int,
    job_id: int,
    store_id: int,
    product_id: int,
    stage_a_task_facts: Mapping[str, Any],
    draft_box_proof: Mapping[str, Any],
) -> dict[str, Any]:
    """Build Stage B facts only from an exact valid Stage A draft-box proof."""

    exact_product_id = _positive_id(product_id, field_name="product_id")
    exact_store_id = _positive_id(store_id, field_name="store_id")
    stage_check = verify_exact_stage_task_facts(stage_a_task_facts, expected_stage="stage_a")
    if stage_check["ok"] is not True:
        raise TwoStageContractError(
            str(stage_check["reason_code"]),
            "Stage B requires valid Stage A task facts",
        )
    stage_a = _json_clone(dict(stage_a_task_facts))
    if exact_store_id != stage_a["store_id"]:
        raise TwoStageContractError(
            "STAGE_B_STORE_MISMATCH",
            "Stage B store must match Stage A store",
        )
    target = _validated_claim_target_identity(stage_a["target_identity"])
    verification = verify_draft_box_proof(
        draft_box_proof,
        stage_a_task_facts=stage_a,
        product_id=exact_product_id,
    )
    if verification["ok"] is not True:
        raise TwoStageContractError(
            str(verification["reason_code"]),
            "Stage B requires an exact valid Stage A draft-box proof",
        )
    proof_fingerprint = _canonical_sha256(
        draft_box_proof.get("fingerprint"),
        field_name="draft_box_proof_fingerprint",
    )
    proof_content = draft_box_proof.get("proof_content")
    observed_source = proof_content.get("observed_source_identity") if isinstance(proof_content, Mapping) else None
    if observed_source is not None:
        observed_source = _validated_source_identity(observed_source)
    return _build_stage_task_facts(
        stage="stage_b",
        task_id=task_id,
        job_id=job_id,
        store_id=exact_store_id,
        identity_field="source_identity",
        identity_value=observed_source,
        extra={
            "product_id": exact_product_id,
            "claim_task_id": stage_a["task_id"],
            "claim_job_id": stage_a["job_id"],
            "target_identity": target,
            "claim_target_fingerprint": target["fingerprint"],
            "stage_a_task_facts_fingerprint": stage_a["fingerprint"],
            "draft_box_proof_fingerprint": proof_fingerprint,
        },
    )


@_stable_verifier("STAGE_TASK_FACTS_INVALID_VALUE")
def verify_exact_stage_task_facts(
    facts: Mapping[str, Any],
    *,
    expected_stage: str,
) -> dict[str, bool | str]:
    """Validate the exact field set and fixed semantics of one stage fact set."""

    if expected_stage not in _STAGE_STATIC_FACTS:
        return _check(False, "EXPECTED_STAGE_INVALID")
    if not isinstance(facts, Mapping):
        return _check(False, "STAGE_TASK_FACTS_SHAPE_MISMATCH")
    if facts.get("stage") != expected_stage:
        return _check(False, "STAGE_TASK_FACTS_STAGE_MISMATCH")
    if expected_stage == "batch_draft_save":
        expected_keys = _BATCH_DRAFT_FACT_KEYS
        expected_schema = BATCH_DRAFT_TASK_FACTS_SCHEMA
    elif expected_stage == "stage_a":
        expected_keys = _STAGE_A_FACT_KEYS
        expected_schema = STAGE_TASK_FACTS_SCHEMA
    else:
        expected_keys = _STAGE_B_FACT_KEYS
        expected_schema = STAGE_TASK_FACTS_SCHEMA
    if set(facts) != expected_keys:
        return _check(False, "STAGE_TASK_FACTS_SHAPE_MISMATCH")
    if facts.get("schema") != expected_schema:
        return _check(False, "STAGE_TASK_FACTS_SCHEMA_MISMATCH")
    for field_name, expected in _STAGE_STATIC_FACTS[expected_stage].items():
        if facts.get(field_name) != expected:
            return _check(False, f"STAGE_TASK_FACTS_{field_name.upper()}_MISMATCH")
    try:
        _positive_id(facts.get("task_id"), field_name="task_id")
        _positive_id(facts.get("store_id"), field_name="store_id")
        if expected_stage == "batch_draft_save":
            if facts.get("path") != "A":
                return _check(False, "BATCH_PATH_FORBIDDEN")
            product_ids = facts.get("product_ids")
            if not isinstance(product_ids, list) or not product_ids:
                return _check(False, "BATCH_PRODUCT_IDS_REQUIRED")
            seen: set[int] = set()
            for raw in product_ids:
                value = _positive_id(raw, field_name="product_id")
                if value in seen:
                    return _check(False, "BATCH_PRODUCT_DUPLICATE")
                seen.add(value)
            _positive_id(facts.get("plan_snapshot_id"), field_name="plan_snapshot_id")
            _canonical_sha256(
                facts.get("plan_snapshot_hash"),
                field_name="plan_snapshot_hash",
            )
        else:
            _positive_id(facts.get("job_id"), field_name="job_id")
            if expected_stage == "stage_a":
                _validated_claim_target_identity(facts.get("target_identity"))
            else:
                source = facts.get("source_identity")
                if source is not None:
                    _validated_source_identity(source)
                target = _validated_claim_target_identity(facts.get("target_identity"))
                if not hmac.compare_digest(
                    _canonical_sha256(
                        facts.get("claim_target_fingerprint"),
                        field_name="claim_target_fingerprint",
                    ),
                    target["fingerprint"],
                ):
                    raise TwoStageContractError(
                        "CLAIM_TARGET_FINGERPRINT_MISMATCH",
                        "Stage B target fingerprint mismatch",
                    )
                _canonical_sha256(
                    facts.get("stage_a_task_facts_fingerprint"),
                    field_name="stage_a_task_facts_fingerprint",
                )
                _positive_id(facts.get("product_id"), field_name="product_id")
                _positive_id(facts.get("claim_task_id"), field_name="claim_task_id")
                _positive_id(facts.get("claim_job_id"), field_name="claim_job_id")
                _canonical_sha256(
                    facts.get("draft_box_proof_fingerprint"),
                    field_name="draft_box_proof_fingerprint",
                )
    except TwoStageContractError as exc:
        return _check(False, exc.reason_code)
    unsigned = {key: facts[key] for key in expected_keys if key != "fingerprint"}
    if not hmac.compare_digest(str(facts.get("fingerprint") or ""), _sha256(unsigned)):
        return _check(False, "STAGE_TASK_FACTS_FINGERPRINT_MISMATCH")
    return _check(True)


def _authorization_context_unsigned(context: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(context, Mapping):
        raise TwoStageContractError(
            "AUTH_CONTEXT_SHAPE_MISMATCH",
            "authorization context fields do not match the v1 contract",
        )
    context_keys = frozenset(context)
    if context_keys in {
        _AUTHORIZATION_CONTEXT_KEYS,
        _AUTHORIZATION_CONTEXT_KEYS - {"fingerprint"},
    }:
        expected_schema = AUTHORIZATION_CONTEXT_SCHEMA
        has_worktree_identity = False
    elif context_keys in {
        _AUTHORIZATION_CONTEXT_V2_KEYS,
        _AUTHORIZATION_CONTEXT_V2_KEYS - {"fingerprint"},
    }:
        expected_schema = AUTHORIZATION_CONTEXT_SCHEMA_V2
        has_worktree_identity = True
    else:
        raise TwoStageContractError(
            "AUTH_CONTEXT_SHAPE_MISMATCH",
            "authorization context fields do not match a supported contract",
        )
    facts = context.get("stage_task_facts")
    stage = facts.get("stage") if isinstance(facts, Mapping) else None
    verification = verify_exact_stage_task_facts(facts, expected_stage=str(stage or ""))
    if verification["ok"] is not True:
        raise TwoStageContractError(
            str(verification["reason_code"]),
            "authorization context contains invalid stage task facts",
        )
    runtime_instance_id = _nonempty_text(
        context.get("runtime_instance_id"),
        field_name="runtime_instance_id",
    )
    browser_session_id = _nonempty_text(
        context.get("browser_session_id"),
        field_name="browser_session_id",
    )
    approved_by = _nonempty_text(context.get("approved_by"), field_name="approved_by")
    git_head = _canonical_git_head(context.get("git_head"))
    l2_evidence_fingerprint = _canonical_sha256(
        context.get("l2_evidence_fingerprint"),
        field_name="l2_evidence_fingerprint",
    )
    if context.get("schema") != expected_schema:
        raise TwoStageContractError(
            "AUTH_CONTEXT_SCHEMA_MISMATCH",
            "authorization context schema mismatch",
        )
    if runtime_instance_id != context.get("runtime_instance_id"):
        raise TwoStageContractError("AUTH_CONTEXT_NOT_CANONICAL", "runtime instance ID is not canonical")
    if browser_session_id != context.get("browser_session_id"):
        raise TwoStageContractError("AUTH_CONTEXT_NOT_CANONICAL", "browser session ID is not canonical")
    if approved_by != context.get("approved_by") or git_head != context.get("git_head"):
        raise TwoStageContractError("AUTH_CONTEXT_NOT_CANONICAL", "authorization context is not canonical")
    unsigned = {
        "schema": expected_schema,
        "stage_task_facts": _json_clone(dict(facts)),
        "runtime_instance_id": runtime_instance_id,
        "browser_session_id": browser_session_id,
        "git_head": git_head,
        "l2_evidence_fingerprint": l2_evidence_fingerprint,
        "approved_by": approved_by,
    }
    if has_worktree_identity:
        unsigned["worktree_identity"] = _canonical_worktree_identity(
            context.get("worktree_identity"),
            git_head=git_head,
        )
    return unsigned


def authorization_context_fingerprint(context: Mapping[str, Any]) -> str:
    """Recompute the canonical authorization digest without trusting a stored digest."""

    return _sha256(_authorization_context_unsigned(context))


def build_authorization_context(
    *,
    stage_task_facts: Mapping[str, Any],
    runtime_instance_id: str,
    browser_session_id: str,
    git_head: str,
    worktree_identity: Mapping[str, Any] | None = None,
    l2_evidence_fingerprint: str,
    approved_by: str,
) -> dict[str, Any]:
    """Bind approval to one task/store/action, browser session, runtime and HEAD."""

    canonical_git_head = _canonical_git_head(git_head)
    schema = (
        AUTHORIZATION_CONTEXT_SCHEMA_V2
        if worktree_identity is not None
        else AUTHORIZATION_CONTEXT_SCHEMA
    )
    unsigned = {
        "schema": schema,
        "stage_task_facts": _json_clone(dict(stage_task_facts)),
        "runtime_instance_id": _nonempty_text(
            runtime_instance_id,
            field_name="runtime_instance_id",
        ),
        "browser_session_id": _nonempty_text(
            browser_session_id,
            field_name="browser_session_id",
        ),
        "git_head": canonical_git_head,
        "l2_evidence_fingerprint": _canonical_sha256(
            l2_evidence_fingerprint,
            field_name="l2_evidence_fingerprint",
        ),
        "approved_by": _nonempty_text(approved_by, field_name="approved_by"),
    }
    if worktree_identity is not None:
        unsigned["worktree_identity"] = _canonical_worktree_identity(
            worktree_identity,
            git_head=canonical_git_head,
        )
    unsigned = _authorization_context_unsigned(unsigned)
    return {**unsigned, "fingerprint": _sha256(unsigned)}


@_stable_verifier("AUTH_CONTEXT_INVALID_VALUE")
def verify_authorization_context(
    context: Mapping[str, Any],
) -> dict[str, bool | str]:
    if not isinstance(context, Mapping) or frozenset(context) not in {
        _AUTHORIZATION_CONTEXT_KEYS,
        _AUTHORIZATION_CONTEXT_V2_KEYS,
    }:
        return _check(False, "AUTH_CONTEXT_SHAPE_MISMATCH")
    try:
        stored = _canonical_sha256(
            context.get("fingerprint"),
            field_name="authorization_context_fingerprint",
        )
        recomputed = authorization_context_fingerprint(context)
    except TwoStageContractError as exc:
        return _check(False, exc.reason_code)
    if not hmac.compare_digest(stored, recomputed):
        return _check(False, "AUTH_CONTEXT_FINGERPRINT_MISMATCH")
    return _check(True)


def compare_authorization_context(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> dict[str, bool | str]:
    """Timing-safely compare two internally valid canonical contexts."""

    expected_check = verify_authorization_context(expected)
    if expected_check["ok"] is not True:
        return _check(False, "EXPECTED_AUTH_CONTEXT_INVALID")
    actual_check = verify_authorization_context(actual)
    if actual_check["ok"] is not True:
        return actual_check
    expected_digest = authorization_context_fingerprint(expected)
    actual_digest = authorization_context_fingerprint(actual)
    if not hmac.compare_digest(expected_digest, actual_digest):
        return _check(False, "AUTH_CONTEXT_MISMATCH")
    return _check(True)
