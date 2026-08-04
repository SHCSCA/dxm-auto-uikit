from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, TypeVar


_ContractError = TypeVar("_ContractError", bound=Exception)


class PlanValueContract:
    """Shared fail-closed primitives for E2 plan and template contracts."""

    def __init__(self, error_type: type[_ContractError]) -> None:
        self._error_type = error_type

    def assert_no_publish_true(
        self,
        value: Any,
        *,
        path: str = "plan",
    ) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                normalized_key = str(key).strip().casefold().replace("-", "_")
                if normalized_key in {
                    "publish",
                    "published",
                    "publish_allowed",
                    "auto_publish",
                    "save_and_publish",
                    "release",
                    "online",
                } and child is not False:
                    self.reject(
                        "PLAN_PUBLISH_FORBIDDEN",
                        f"{path}.{key} contains a publish directive",
                    )
                self.assert_no_publish_true(child, path=f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self.assert_no_publish_true(child, path=f"{path}[{index}]")

    def is_resolved_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True

    def exact_object(
        self,
        value: Any,
        keys: set[str],
        label: str,
    ) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != keys:
            self.reject(
                "PLAN_SCHEMA_INVALID",
                f"{label} has an unexpected shape",
            )
        return value

    def stable_field_key(self, value: Any) -> str:
        text = self.non_empty_text(value, "field_key")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text) is None:
            self.reject(
                "LOCAL_PLAN_FIELD_MAPPING_INVALID",
                "field_key must be stable ASCII",
            )
        return text

    def positive_id_text(self, value: Any, label: str) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[1-9][0-9]*", value) is None
        ):
            self.reject(
                "PLAN_IDENTIFIER_INVALID",
                f"{label} must be a positive integer string",
            )
        return value

    def sha256_text(self, value: Any, label: str) -> str:
        if (
            not isinstance(value, str)
            or re.fullmatch(r"[0-9A-Fa-f]{64}", value) is None
        ):
            self.reject("PLAN_HASH_INVALID", f"{label} must be SHA256")
        return value.upper()

    def non_empty_text(self, value: Any, label: str) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
        ):
            self.reject(
                "PLAN_TEXT_INVALID",
                f"{label} must be non-empty normalized text",
            )
        return value

    def clone(self, value: Any) -> Any:
        try:
            return json.loads(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
        except (TypeError, ValueError) as exc:
            raise self._error_type(
                "PLAN_NOT_CANONICAL",
                "plan data must be canonical JSON",
            ) from exc

    def reject(self, reason_code: str, detail: str) -> None:
        raise self._error_type(reason_code, detail)
