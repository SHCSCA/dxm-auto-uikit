from __future__ import annotations

import re
from typing import Any


_STABLE_PRODUCT_ID_RE = re.compile(r'^[A-Za-z0-9_-]{5,128}$')


def is_stable_product_id(value: Any) -> bool:
    """Return whether value is an auditable product identifier.

    Display labels made only of letters are not identities.  A stable product
    id is an exact string, uses the frozen ASCII token alphabet, has bounded
    length, and contains at least one digit.
    """

    return (
        isinstance(value, str)
        and value == value.strip()
        and _STABLE_PRODUCT_ID_RE.fullmatch(value) is not None
        and any(char.isdigit() for char in value)
    )
