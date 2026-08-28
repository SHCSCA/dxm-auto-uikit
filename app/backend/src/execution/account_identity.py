from __future__ import annotations

import hashlib
import re
from typing import Any


_ACCOUNT_REF_PATTERN = re.compile(r"[0-9a-f]{32}")
_ACCOUNT_CONTEXT_HASH_PATTERN = re.compile(r"[0-9A-F]{64}")


def account_context_hash(account_ref: Any) -> str:
    """Derive the E2/E3 account binding from a trusted userInfo identity."""

    if not isinstance(account_ref, str) or _ACCOUNT_REF_PATTERN.fullmatch(account_ref) is None:
        raise ValueError("account_ref must be the canonical authenticated identity digest")
    return hashlib.sha256(
        f"dxm-e2-account-context:{account_ref}".encode("utf-8")
    ).hexdigest().upper()


def canonical_account_context_hash(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("account context hash is required")
    normalized = value.upper()
    if _ACCOUNT_CONTEXT_HASH_PATTERN.fullmatch(normalized) is None:
        raise ValueError("account context hash must be SHA256")
    return normalized
