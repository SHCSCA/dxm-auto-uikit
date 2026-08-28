"""
InspectEffectArbiter — classifies browser inspect effects into verdict classes.

Four final verdict classes:
  - PURE_READ: only reads page state, no mutations
  - UI_REVEAL: expands/collapses UI without data mutation
  - READ_ONLY_DXM_REQUEST: DXM API read requests only
  - FORBIDDEN: any mutation (HTTP request with mutation_request_count > 0 → FORBIDDEN directly)

All inspect actions must come from a versioned allowlist at resources/inspect_allowlist.v1.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class EffectVerdict(Enum):
    """Final verdict for an inspect effect."""

    PURE_READ = "PURE_READ"
    UI_REVEAL = "UI_REVEAL"
    READ_ONLY_DXM_REQUEST = "READ_ONLY_DXM_REQUEST"
    FORBIDDEN = "FORBIDDEN"


@dataclass
class EffectClassification:
    """Classification result for an inspect effect."""

    verdict: EffectVerdict
    effect_type: str
    reason: str
    allowlist_entry: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class InspectEffectArbiter:
    """Classifies inspect effects into verdict classes.

    HTTP requests with mutation_request_count > 0 are FORBIDDEN directly.
    All inspect actions must come from a versioned allowlist.
    """

    ALLOWLIST_VERSION = "v1"
    ALLOWLIST_FILENAME = "inspect_allowlist.v1.json"

    def __init__(
        self,
        allowlist_path: str | Path | None = None,
        allowlist_data: dict[str, Any] | None = None,
    ) -> None:
        self._allowlist: dict[str, Any] = {}
        if allowlist_data is not None:
            self._allowlist = allowlist_data
        elif allowlist_path is not None:
            self._load_allowlist(Path(allowlist_path))
        else:
            self._load_default_allowlist()

    def classify(self, effect: dict[str, Any]) -> EffectClassification:
        """Classify an inspect effect into a verdict.

        Args:
            effect: effect dict with keys like "effect_type", "effect_action",
                    "http_requests", "dom_operations", etc.

        Returns:
            EffectClassification with verdict, reason, and metadata
        """
        effect_type = str(effect.get("effect_type") or effect.get("type") or "unknown")
        effect_action = str(effect.get("effect_action") or effect.get("action") or "")

        http_requests = effect.get("http_requests") or []
        mutation_request_count = sum(
            1 for req in http_requests if self._is_mutation_request(req)
        )
        if mutation_request_count > 0:
            return EffectClassification(
                verdict=EffectVerdict.FORBIDDEN,
                effect_type=effect_type,
                reason=f"HTTP mutation requests detected ({mutation_request_count} mutation requests)",
                allowlist_entry=self._find_allowlist_entry(effect_type, effect_action),
                metadata={
                    "mutation_request_count": mutation_request_count,
                    "total_requests": len(http_requests),
                },
            )

        dom_operations = effect.get("dom_operations") or []
        if self._is_read_only_dom(dom_operations):
            allowlist_entry = self._find_allowlist_entry(effect_type, effect_action)
            if allowlist_entry is None:
                return EffectClassification(
                    verdict=EffectVerdict.FORBIDDEN,
                    effect_type=effect_type,
                    reason=f"Effect '{effect_type}/{effect_action}' not in allowlist",
                    allowlist_entry=None,
                )
            if allowlist_entry.get("verdict") == "PURE_READ":
                return EffectClassification(
                    verdict=EffectVerdict.PURE_READ,
                    effect_type=effect_type,
                    reason=allowlist_entry.get("reason", "read operation"),
                    allowlist_entry=allowlist_entry,
                )
            elif allowlist_entry.get("verdict") == "UI_REVEAL":
                return EffectClassification(
                    verdict=EffectVerdict.UI_REVEAL,
                    effect_type=effect_type,
                    reason=allowlist_entry.get("reason", "UI reveal operation"),
                    allowlist_entry=allowlist_entry,
                )
            elif allowlist_entry.get("verdict") == "READ_ONLY_DXM_REQUEST":
                return EffectClassification(
                    verdict=EffectVerdict.READ_ONLY_DXM_REQUEST,
                    effect_type=effect_type,
                    reason=allowlist_entry.get("reason", "DXM read request"),
                    allowlist_entry=allowlist_entry,
                )
            else:
                return EffectClassification(
                    verdict=EffectVerdict.FORBIDDEN,
                    effect_type=effect_type,
                    reason=allowlist_entry.get("reason", "unknown allowlist verdict"),
                    allowlist_entry=allowlist_entry,
                )

        if self._is_ui_reveal(dom_operations):
            allowlist_entry = self._find_allowlist_entry(effect_type, effect_action)
            if allowlist_entry is None:
                return EffectClassification(
                    verdict=EffectVerdict.FORBIDDEN,
                    effect_type=effect_type,
                    reason=f"UI reveal effect '{effect_type}/{effect_action}' not in allowlist",
                )
            return EffectClassification(
                verdict=EffectVerdict.UI_REVEAL,
                effect_type=effect_type,
                reason=allowlist_entry.get("reason", "UI reveal operation"),
                allowlist_entry=allowlist_entry,
            )

        if self._is_dxm_read_request(http_requests):
            allowlist_entry = self._find_allowlist_entry(effect_type, effect_action)
            if allowlist_entry is None:
                return EffectClassification(
                    verdict=EffectVerdict.FORBIDDEN,
                    effect_type=effect_type,
                    reason=f"DXM read request '{effect_type}/{effect_action}' not in allowlist",
                )
            return EffectClassification(
                verdict=EffectVerdict.READ_ONLY_DXM_REQUEST,
                effect_type=effect_type,
                reason=allowlist_entry.get("reason", "DXM read request"),
                allowlist_entry=allowlist_entry,
            )

        return EffectClassification(
            verdict=EffectVerdict.FORBIDDEN,
            effect_type=effect_type,
            reason="Effect does not match any allowed category",
        )

    def _is_mutation_request(self, request: dict[str, Any]) -> bool:
        """Check if an HTTP request is a mutation (POST/PUT/PATCH/DELETE)."""
        method = str(request.get("method") or request.get("http_method") or "").upper()
        return method in {"POST", "PUT", "PATCH", "DELETE"}

    def _is_read_only_dom(self, operations: list) -> bool:
        """Check if DOM operations are read-only (query/observe only)."""
        if not operations:
            return False
        read_only_ops = {"querySelector", "querySelectorAll", "getComputedStyle", "getBoundingClientRect", "observe", "observe_attributes"}
        for op in operations:
            op_name = str(op.get("operation") or op.get("name") or "")
            if op_name not in read_only_ops:
                return False
        return True

    def _is_ui_reveal(self, operations: list) -> bool:
        """Check if DOM operations are UI reveals (no data mutation)."""
        if not operations:
            return False
        ui_reveal_ops = {"click", "scroll", "focus", "blur", "expand", "collapse", "toggle"}
        for op in operations:
            op_name = str(op.get("operation") or op.get("name") or "")
            if op_name not in ui_reveal_ops:
                return False
        return True

    def _is_dxm_read_request(self, requests: list) -> bool:
        """Check if HTTP requests are DXM read-only API calls."""
        if not requests:
            return False
        read_methods = {"GET", "HEAD", "OPTIONS"}
        dxm_hosts = {"dianxiaomi.com", "dxm.com", "aliexpress.com"}

        for req in requests:
            method = str(req.get("method") or req.get("http_method") or "").upper()
            url = str(req.get("url") or "")
            if method not in read_methods:
                return False
            host = self._extract_host(url)
            if host and not any(h in host for h in dxm_hosts):
                return False
        return True

    def _extract_host(self, url: str) -> str | None:
        """Extract host from URL."""
        if not url:
            return None
        if "://" in url:
            return url.split("://")[1].split("/")[0].split("?")[0]
        return None

    def _find_allowlist_entry(
        self,
        effect_type: str,
        effect_action: str,
    ) -> dict[str, Any] | None:
        """Find an allowlist entry for the given effect type/action."""
        entries = self._allowlist.get("entries", [])
        for entry in entries:
            if entry.get("effect_type") == effect_type and entry.get("effect_action") == effect_action:
                return entry
            if entry.get("effect_type") == effect_type and not entry.get("effect_action"):
                return entry
        return None

    def _load_allowlist(self, path: Path) -> None:
        """Load allowlist from a JSON file."""
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._validate_allowlist(data)
            self._allowlist = data
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise ValueError(f"Failed to load inspect allowlist from {path}: {exc}") from exc

    def _load_default_allowlist(self) -> None:
        """Load the default built-in allowlist."""
        self._allowlist = {
            "version": self.ALLOWLIST_VERSION,
            "entries": [
                {
                    "effect_type": "collapse_trigger",
                    "effect_action": "click",
                    "verdict": "UI_REVEAL",
                    "reason": "Collapse/expand trigger click is UI reveal only",
                },
                {
                    "effect_type": "control_click",
                    "effect_action": "click",
                    "verdict": "UI_REVEAL",
                    "reason": "Generic control click is UI reveal only",
                },
                {
                    "effect_type": "modal_open",
                    "effect_action": "click",
                    "verdict": "UI_REVEAL",
                    "reason": "Modal open is UI reveal",
                },
                {
                    "effect_type": "modal_close",
                    "effect_action": "click",
                    "verdict": "UI_REVEAL",
                    "reason": "Modal close is UI reveal",
                },
                {
                    "effect_type": "readback_field",
                    "effect_action": "querySelector",
                    "verdict": "PURE_READ",
                    "reason": "Field value readback is pure read",
                },
                {
                    "effect_type": "readback_validation",
                    "effect_action": "getComputedStyle",
                    "verdict": "PURE_READ",
                    "reason": "Style validation readback is pure read",
                },
                {
                    "effect_type": "readback_position",
                    "effect_action": "getBoundingClientRect",
                    "verdict": "PURE_READ",
                    "reason": "Position readback is pure read",
                },
                {
                    "effect_type": "dxm_api_read",
                    "effect_action": "GET",
                    "verdict": "READ_ONLY_DXM_REQUEST",
                    "reason": "DXM API GET request is read-only",
                },
                {
                    "effect_type": "element_visibility",
                    "effect_action": "observe",
                    "verdict": "PURE_READ",
                    "reason": "Element visibility observation is pure read",
                },
            ],
        }

    def _validate_allowlist(self, data: dict[str, Any]) -> None:
        """Validate the structure of an allowlist."""
        if "version" not in data:
            raise ValueError("Allowlist must have a 'version' field")
        if "entries" not in data:
            raise ValueError("Allowlist must have an 'entries' field")
        if not isinstance(data["entries"], list):
            raise ValueError("Allowlist 'entries' must be a list")
        for i, entry in enumerate(data["entries"]):
            if "effect_type" not in entry:
                raise ValueError(f"Allowlist entry {i} missing 'effect_type'")
            if "verdict" not in entry:
                raise ValueError(f"Allowlist entry {i} missing 'verdict'")


def classify_inspect_effect(effect: dict[str, Any]) -> EffectClassification:
    """Convenience function for global effect classification."""
    arbiter = InspectEffectArbiter()
    return arbiter.classify(effect)
