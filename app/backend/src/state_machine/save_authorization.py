from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, parse_qs, urlsplit, urlunsplit


SOURCE_IDENTITY_SCHEMA = "dxm.source.identity.v1"
PRODUCT_BOX_SNAPSHOT_SCHEMA = "dxm.product_box.snapshot.v1"
SAVE_TASK_FACTS_SCHEMA = "dxm.save_only.task_facts.v1"
SAVE_ONLY_CONFIRMATION = "CONFIRM_DXM_SAVE_ONLY"
SAVE_ONLY_PUBLISH_SCENE = "SMT_SEMI_MANAGED_SAVE_ONLY"
AUTHORIZATION_CONTEXT_SCHEMA = "dxm.save_only.authorization.context.v1"

_SOURCE_IDENTITY_KEYS = frozenset({"schema", "primary_url", "urls", "fingerprint"})
_PRODUCT_BOX_SNAPSHOT_KEYS = frozenset(
    {
        "schema",
        "product_id",
        "store_id",
        "store_name",
        "product_title",
        "product_status",
        "source_identity",
        "target_identity",
        "target_identity_sha256",
        "captured_at",
        "evidence_ref",
        "fingerprint",
    }
)
_SAVE_TASK_FACT_KEYS = frozenset(
    {
        "schema",
        "mode",
        "confirmation",
        "publish_scene",
        "action",
        "task_id",
        "job_id",
        "store_id",
        "product_id",
        "product_box_snapshot_fingerprint",
        "fingerprint",
    }
)
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


class SaveOnlyContractError(ValueError):
    """Invalid input to an immutable save-only authorization contract."""

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
        raise SaveOnlyContractError(
            "VALUE_NOT_JSON_SERIALIZABLE",
            "contract value must be JSON serializable",
        ) from exc


def canonical_sha256(value: Any) -> str:
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
            except (SaveOnlyContractError, TypeError, ValueError, OverflowError):
                return _check(False, reason_code)

        return wrapped

    return decorate


def _positive_id(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SaveOnlyContractError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be a positive integer",
        )
    return value


def _canonical_sha256(value: Any, *, field_name: str) -> str:
    digest = str(value or "")
    if len(digest) != 64 or digest != digest.upper():
        raise SaveOnlyContractError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be an uppercase SHA-256 hex digest",
        )
    try:
        int(digest, 16)
    except ValueError as exc:
        raise SaveOnlyContractError(
            f"{field_name.upper()}_INVALID",
            f"{field_name} must be an uppercase SHA-256 hex digest",
        ) from exc
    return digest


def _nonempty_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SaveOnlyContractError(
            f"{field_name.upper()}_REQUIRED",
            f"{field_name} is required",
        )
    return value.strip()


def _canonical_evidence_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256", "size"}:
        raise SaveOnlyContractError(
            "EVIDENCE_REF_SHAPE_MISMATCH",
            "evidence_ref must contain exactly path, sha256, and size",
        )
    path_text = _nonempty_text(value.get("path"), field_name="evidence_ref_path")
    if not Path(path_text).is_absolute():
        raise SaveOnlyContractError(
            "EVIDENCE_REF_PATH_NOT_ABSOLUTE",
            "evidence_ref path must be absolute",
        )
    return {
        "path": str(Path(path_text)),
        "sha256": _canonical_sha256(value.get("sha256"), field_name="evidence_ref_sha256"),
        "size": _positive_id(value.get("size"), field_name="evidence_ref_size"),
    }


def _canonical_git_head(value: Any) -> str:
    git_head = _nonempty_text(value, field_name="git_head").lower()
    if len(git_head) not in {40, 64}:
        raise SaveOnlyContractError("GIT_HEAD_INVALID", "git_head must be a full object ID")
    try:
        int(git_head, 16)
    except ValueError as exc:
        raise SaveOnlyContractError("GIT_HEAD_INVALID", "git_head must be hexadecimal") from exc
    return git_head


def _canonical_source_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SaveOnlyContractError("SOURCE_URL_REQUIRED", "source URL is required")
    raw = value.strip()
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in raw):
        raise SaveOnlyContractError("SOURCE_URL_INVALID", "source URL contains whitespace or controls")
    if re.search(r"%(?![0-9A-Fa-f]{2})", raw):
        raise SaveOnlyContractError("SOURCE_URL_INVALID", "source URL contains invalid percent encoding")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise SaveOnlyContractError("SOURCE_URL_INVALID", "source URL is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise SaveOnlyContractError("SOURCE_URL_INVALID", "source URL must be absolute HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise SaveOnlyContractError("SOURCE_URL_CREDENTIALS_FORBIDDEN", "source URL credentials are forbidden")
    try:
        hostname = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise SaveOnlyContractError("SOURCE_URL_INVALID", "source URL host is invalid") from exc
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        labels = hostname.split(".")
        if (
            len(hostname) > 253
            or any(
                not label
                or len(label) > 63
                or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
                for label in labels
            )
            or all(character.isdigit() or character == "." for character in hostname)
        ):
            raise SaveOnlyContractError("SOURCE_URL_INVALID", "source URL host is invalid")
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    return urlunsplit(
        SplitResult(
            scheme=scheme,
            netloc=host,
            path=parsed.path or "/",
            query=parsed.query,
            fragment="",
        )
    )


def canonical_source_identity(
    primary_url: str,
    source_urls: Iterable[str] | None = None,
) -> dict[str, Any]:
    primary = _canonical_source_url(primary_url)
    if isinstance(source_urls, (str, bytes)):
        raise SaveOnlyContractError("SOURCE_URLS_INVALID", "source_urls must be an iterable")
    urls = {primary}
    for value in source_urls or ():
        urls.add(_canonical_source_url(value))
    unsigned = {"schema": SOURCE_IDENTITY_SCHEMA, "primary_url": primary, "urls": sorted(urls)}
    return {**unsigned, "fingerprint": canonical_sha256(unsigned)}


def _validated_source_identity(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_IDENTITY_KEYS:
        raise SaveOnlyContractError("SOURCE_IDENTITY_SHAPE_MISMATCH", "source identity shape mismatch")
    if value.get("schema") != SOURCE_IDENTITY_SCHEMA:
        raise SaveOnlyContractError("SOURCE_IDENTITY_SCHEMA_MISMATCH", "source identity schema mismatch")
    rebuilt = canonical_source_identity(value.get("primary_url"), value.get("urls"))
    if dict(value) != rebuilt:
        raise SaveOnlyContractError("SOURCE_IDENTITY_NOT_CANONICAL", "source identity is not canonical")
    return rebuilt


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
            re.fullmatch(r"/goods\d*\.html", path, flags=re.IGNORECASE) is not None
            and len(goods_ids) == 1
            and re.fullmatch(r"[0-9]+", goods_ids[0]) is not None
        )
    if host_matches("aliexpress.com"):
        return re.fullmatch(r"/item/[0-9]+\.html", path, flags=re.IGNORECASE) is not None
    return False


def _canonical_timestamp(value: Any) -> str:
    text = _nonempty_text(value, field_name="captured_at")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SaveOnlyContractError("CAPTURED_AT_INVALID", "captured_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise SaveOnlyContractError("CAPTURED_AT_INVALID", "captured_at requires timezone")
    return text


def build_product_box_snapshot(
    *,
    product_id: int,
    store_id: int,
    store_name: str,
    product_title: str,
    product_status: str,
    source_identity: Mapping[str, Any],
    target_identity: Mapping[str, Any],
    captured_at: str,
    evidence_ref: Mapping[str, Any],
) -> dict[str, Any]:
    source = _validated_source_identity(source_identity)
    if not isinstance(target_identity, Mapping):
        raise SaveOnlyContractError("PRODUCT_BOX_TARGET_INVALID", "target identity is required")
    target = _json_clone(dict(target_identity))
    target_sha256 = canonical_sha256(target)
    unsigned = {
        "schema": PRODUCT_BOX_SNAPSHOT_SCHEMA,
        "product_id": _positive_id(product_id, field_name="product_id"),
        "store_id": _positive_id(store_id, field_name="store_id"),
        "store_name": _nonempty_text(store_name, field_name="store_name"),
        "product_title": _nonempty_text(product_title, field_name="product_title"),
        "product_status": _nonempty_text(product_status, field_name="product_status"),
        "source_identity": source,
        "target_identity": target,
        "target_identity_sha256": target_sha256,
        "captured_at": _canonical_timestamp(captured_at),
        "evidence_ref": _canonical_evidence_ref(evidence_ref),
    }
    return {**unsigned, "fingerprint": canonical_sha256(unsigned)}


@_stable_verifier("PRODUCT_BOX_SNAPSHOT_INVALID_VALUE")
def verify_product_box_snapshot(snapshot: Mapping[str, Any]) -> dict[str, bool | str]:
    if not isinstance(snapshot, Mapping) or set(snapshot) != _PRODUCT_BOX_SNAPSHOT_KEYS:
        return _check(False, "PRODUCT_BOX_SNAPSHOT_SHAPE_MISMATCH")
    rebuilt = build_product_box_snapshot(
        product_id=snapshot.get("product_id"),
        store_id=snapshot.get("store_id"),
        store_name=snapshot.get("store_name"),
        product_title=snapshot.get("product_title"),
        product_status=snapshot.get("product_status"),
        source_identity=snapshot.get("source_identity"),
        target_identity=snapshot.get("target_identity"),
        captured_at=snapshot.get("captured_at"),
        evidence_ref=snapshot.get("evidence_ref"),
    )
    if dict(snapshot) != rebuilt:
        return _check(False, "PRODUCT_BOX_SNAPSHOT_FINGERPRINT_MISMATCH")
    return _check(True)


def build_save_task_facts(
    *,
    task_id: int,
    job_id: int,
    store_id: int,
    product_id: int,
    product_box_snapshot_fingerprint: str,
) -> dict[str, Any]:
    unsigned = {
        "schema": SAVE_TASK_FACTS_SCHEMA,
        "mode": "single_save",
        "confirmation": SAVE_ONLY_CONFIRMATION,
        "publish_scene": SAVE_ONLY_PUBLISH_SCENE,
        "action": "save_only",
        "task_id": _positive_id(task_id, field_name="task_id"),
        "job_id": _positive_id(job_id, field_name="job_id"),
        "store_id": _positive_id(store_id, field_name="store_id"),
        "product_id": _positive_id(product_id, field_name="product_id"),
        "product_box_snapshot_fingerprint": _canonical_sha256(
            product_box_snapshot_fingerprint,
            field_name="product_box_snapshot_fingerprint",
        ),
    }
    return {**unsigned, "fingerprint": canonical_sha256(unsigned)}


@_stable_verifier("SAVE_TASK_FACTS_INVALID_VALUE")
def verify_exact_save_task_facts(facts: Mapping[str, Any]) -> dict[str, bool | str]:
    if not isinstance(facts, Mapping) or set(facts) != _SAVE_TASK_FACT_KEYS:
        return _check(False, "SAVE_TASK_FACTS_SHAPE_MISMATCH")
    rebuilt = build_save_task_facts(
        task_id=facts.get("task_id"),
        job_id=facts.get("job_id"),
        store_id=facts.get("store_id"),
        product_id=facts.get("product_id"),
        product_box_snapshot_fingerprint=facts.get("product_box_snapshot_fingerprint"),
    )
    if dict(facts) != rebuilt:
        return _check(False, "SAVE_TASK_FACTS_FINGERPRINT_MISMATCH")
    return _check(True)


def _authorization_context_unsigned(context: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(context, Mapping) or frozenset(context) not in {
        _AUTHORIZATION_CONTEXT_KEYS,
        _AUTHORIZATION_CONTEXT_KEYS - {"fingerprint"},
    }:
        raise SaveOnlyContractError("AUTH_CONTEXT_SHAPE_MISMATCH", "authorization context shape mismatch")
    facts = context.get("stage_task_facts")
    if verify_exact_save_task_facts(facts).get("ok") is not True:
        raise SaveOnlyContractError("SAVE_TASK_FACTS_INVALID", "authorization save facts are invalid")
    unsigned = {
        "schema": AUTHORIZATION_CONTEXT_SCHEMA,
        "stage_task_facts": _json_clone(dict(facts)),
        "runtime_instance_id": _nonempty_text(context.get("runtime_instance_id"), field_name="runtime_instance_id"),
        "browser_session_id": _nonempty_text(context.get("browser_session_id"), field_name="browser_session_id"),
        "git_head": _canonical_git_head(context.get("git_head")),
        "l2_evidence_fingerprint": _canonical_sha256(
            context.get("l2_evidence_fingerprint"),
            field_name="l2_evidence_fingerprint",
        ),
        "approved_by": _nonempty_text(context.get("approved_by"), field_name="approved_by"),
    }
    if context.get("schema") != AUTHORIZATION_CONTEXT_SCHEMA:
        raise SaveOnlyContractError("AUTH_CONTEXT_SCHEMA_MISMATCH", "authorization context schema mismatch")
    return unsigned


def authorization_context_fingerprint(context: Mapping[str, Any]) -> str:
    return canonical_sha256(_authorization_context_unsigned(context))


def build_authorization_context(
    *,
    stage_task_facts: Mapping[str, Any],
    runtime_instance_id: str,
    browser_session_id: str,
    git_head: str,
    l2_evidence_fingerprint: str,
    approved_by: str,
) -> dict[str, Any]:
    unsigned = _authorization_context_unsigned(
        {
            "schema": AUTHORIZATION_CONTEXT_SCHEMA,
            "stage_task_facts": _json_clone(dict(stage_task_facts)),
            "runtime_instance_id": runtime_instance_id,
            "browser_session_id": browser_session_id,
            "git_head": git_head,
            "l2_evidence_fingerprint": l2_evidence_fingerprint,
            "approved_by": approved_by,
        }
    )
    return {**unsigned, "fingerprint": canonical_sha256(unsigned)}


@_stable_verifier("AUTH_CONTEXT_INVALID_VALUE")
def verify_authorization_context(context: Mapping[str, Any]) -> dict[str, bool | str]:
    if not isinstance(context, Mapping) or set(context) != _AUTHORIZATION_CONTEXT_KEYS:
        return _check(False, "AUTH_CONTEXT_SHAPE_MISMATCH")
    if not hmac.compare_digest(
        _canonical_sha256(context.get("fingerprint"), field_name="authorization_context_fingerprint"),
        authorization_context_fingerprint(context),
    ):
        return _check(False, "AUTH_CONTEXT_FINGERPRINT_MISMATCH")
    return _check(True)


def compare_authorization_context(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> dict[str, bool | str]:
    expected_check = verify_authorization_context(expected)
    if expected_check.get("ok") is not True:
        return _check(False, "EXPECTED_AUTH_CONTEXT_INVALID")
    actual_check = verify_authorization_context(actual)
    if actual_check.get("ok") is not True:
        return actual_check
    if not hmac.compare_digest(
        authorization_context_fingerprint(expected),
        authorization_context_fingerprint(actual),
    ):
        return _check(False, "AUTH_CONTEXT_MISMATCH")
    return _check(True)
