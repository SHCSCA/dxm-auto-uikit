from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any


class StrictUtcTimestampError(ValueError):
    """Raised when an E3 authority timestamp is not explicit canonical UTC."""


class AuthorizationLeaseAuthorityError(ValueError):
    """The persisted approval lease cannot form one immutable authority."""


AUTHORIZATION_LEASE_AUTHORITY_SCHEMA = "dxm.authorization_lease.authority.v1"


def parse_strict_utc_timestamp(value: Any, *, field: str) -> datetime:
    """Parse an explicit UTC timestamp without dropping fractional seconds."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise StrictUtcTimestampError(f"{field} must be a non-empty UTC timestamp")
    if value.endswith("Z"):
        normalized = f"{value[:-1]}+00:00"
    elif value.endswith("+00:00"):
        normalized = value
    else:
        raise StrictUtcTimestampError(f"{field} must use Z or +00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise StrictUtcTimestampError(f"{field} is not a valid UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise StrictUtcTimestampError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc)


def authorization_lease_is_active(*, checked_at: Any, expires_at: Any) -> bool:
    """Fail closed unless the strict UTC check time is before lease expiry."""

    try:
        checked = parse_strict_utc_timestamp(checked_at, field="checked_at")
        expiry = parse_strict_utc_timestamp(expires_at, field="expires_at")
    except StrictUtcTimestampError:
        return False
    return checked < expiry


def canonical_authorization_lease_authority(approval: Any) -> dict[str, Any]:
    """Project every non-secret authorization fact of one consumed lease."""

    if not isinstance(approval, Mapping):
        raise AuthorizationLeaseAuthorityError("approval lease must be an object")
    if approval.get("approved") is not True or approval.get("source") != "server":
        raise AuthorizationLeaseAuthorityError("approval lease is not server approved")
    if approval.get("consumed") is not True:
        raise AuthorizationLeaseAuthorityError("approval lease is not consumed")
    lease_id = approval.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id.strip() or lease_id != lease_id.strip():
        raise AuthorizationLeaseAuthorityError("approval lease id is invalid")
    issued = parse_strict_utc_timestamp(approval.get("issued_at"), field="issued_at")
    expiry = parse_strict_utc_timestamp(approval.get("expires_at"), field="expires_at")
    consumed = parse_strict_utc_timestamp(
        approval.get("consumed_at"), field="consumed_at"
    )
    approved_at = parse_strict_utc_timestamp(
        approval.get("approved_at"), field="approved_at"
    )
    if (
        approved_at != issued
        or not (issued <= consumed < expiry)
        or expiry - issued > timedelta(minutes=5)
    ):
        raise AuthorizationLeaseAuthorityError("approval lease time window is invalid")
    approved_by = approval.get("approved_by")
    confirmation = approval.get("confirmation")
    token_hash = approval.get("token_hash")
    if (
        not isinstance(approved_by, str)
        or not approved_by.strip()
        or approved_by != approved_by.strip()
        or not isinstance(confirmation, str)
        or not confirmation.strip()
        or confirmation != confirmation.strip()
        or not isinstance(token_hash, str)
        or len(token_hash) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in token_hash)
    ):
        raise AuthorizationLeaseAuthorityError("approval identity is invalid")
    authorization_context = approval.get("authorization_context")
    stage_task_facts = approval.get("stage_task_facts")
    if not isinstance(authorization_context, Mapping) or not isinstance(
        stage_task_facts, Mapping
    ):
        raise AuthorizationLeaseAuthorityError("approval authority facts are missing")
    if (
        confirmation != "CONFIRM_DXM_SAVE_ONLY"
        or authorization_context.get("approved_by") != approved_by
        or authorization_context.get("stage_task_facts") != stage_task_facts
    ):
        raise AuthorizationLeaseAuthorityError(
            "approval authority cross-field binding is invalid"
        )
    try:
        canonical_context = json.loads(
            json.dumps(
                authorization_context,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        canonical_stage = json.loads(
            json.dumps(
                stage_task_facts,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise AuthorizationLeaseAuthorityError(
            "approval authority facts are not canonical JSON"
        ) from exc
    return {
        "schema": AUTHORIZATION_LEASE_AUTHORITY_SCHEMA,
        "approved": True,
        "source": "server",
        "approved_by": approved_by,
        "approved_at": approved_at.isoformat(timespec="microseconds"),
        "confirmation": confirmation,
        "token_hash": token_hash.upper(),
        "lease_id": lease_id,
        "issued_at": issued.isoformat(timespec="microseconds"),
        "expires_at": expiry.isoformat(timespec="microseconds"),
        "consumed": True,
        "consumed_at": consumed.isoformat(timespec="microseconds"),
        "authorization_context": canonical_context,
        "stage_task_facts": canonical_stage,
    }


def authorization_lease_authority_fingerprint(approval: Any) -> str:
    authority = canonical_authorization_lease_authority(approval)
    encoded = json.dumps(
        authority,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def utc_now_iso() -> str:
    """Return an explicit UTC clock reading while preserving microseconds."""

    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
