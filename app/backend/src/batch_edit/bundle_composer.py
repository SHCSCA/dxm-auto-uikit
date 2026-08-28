from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from src.batch_edit.batch_contract import (
    BATCH_TEMPLATE_REQUIRED_SECTIONS,
    BATCH_TEMPLATE_TYPE,
    TEMPLATE_BUNDLE_SCHEMA,
    BatchContractError,
    assert_no_publish_directives,
    normalize_bundle_source_section,
    source_template_snapshot,
)
from src.batch_edit.scope_contract import canonical_sha256
from src.db import connection, dumps, loads
from src.services.config_validation import ConfigValidationService
from src.services.dxm_reference_templates import REFERENCE_TEMPLATE_SECTIONS
from src.utils import now_iso


class BundleComposerError(ValueError):
    def __init__(
        self,
        reason_code: str,
        detail: str,
        *,
        status_code: int = 409,
        missing: list[str] | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.status_code = status_code
        self.missing = list(missing or [])
        super().__init__(detail)


class EditBatchBundleComposer:
    def options(self, *, store_id: int, category_name: str | None) -> dict[str, Any]:
        category = _optional_text(category_name)
        if category is not None:
            _reject(
                "BATCH_CATEGORY_SCOPE_UNVERIFIABLE",
                "category-bound edit batches are unavailable because live draft-box rows do not expose exact category evidence",
            )
        with connection() as conn:
            store = conn.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
            if not store:
                _reject("STORE_NOT_FOUND", "store does not exist", status_code=404)
            _assert_supported_batch_store(store)
            rows = conn.execute(
                "SELECT * FROM templates WHERE template_type != ? ORDER BY id DESC",
                (BATCH_TEMPLATE_TYPE,),
            ).fetchall()
        templates = [_decode_template(row) for row in rows]
        sections = []
        for section in BATCH_TEMPLATE_REQUIRED_SECTIONS:
            candidates = [
                self._candidate_summary(template, section, store, category)
                for template in templates
                if template["template_type"] == section
            ]
            ready = [candidate for candidate in candidates if candidate["ready"]]
            sections.append(
                {
                    "section": section,
                    "template_type": section,
                    "candidates": candidates,
                    "default_candidate": ready[0] if ready else None,
                    "ready_count": len(ready),
                }
            )
        ready_count = sum(section["default_candidate"] is not None for section in sections)
        return {
            "store": {"id": int(store["id"]), "name": store["name"], "platform": store["platform"]},
            "category_name": category,
            "required_sections": list(BATCH_TEMPLATE_REQUIRED_SECTIONS),
            "ready_count": ready_count,
            "ready": ready_count == len(BATCH_TEMPLATE_REQUIRED_SECTIONS),
            "sections": sections,
        }

    def compose(self, request: dict[str, Any]) -> dict[str, Any]:
        category = _optional_text(request.get("category_name"))
        if category is not None:
            _reject(
                "BATCH_CATEGORY_SCOPE_UNVERIFIABLE",
                "category-bound edit batches are unavailable because live draft-box rows do not expose exact category evidence",
            )
        template_name = str(request["template_name"]).strip()
        version = str(request["version"])
        selections = request["section_templates"]
        now = now_iso()
        with connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            store = conn.execute("SELECT * FROM stores WHERE id=?", (request["store_id"],)).fetchone()
            if not store:
                _reject("STORE_NOT_FOUND", "store does not exist", status_code=404)
            _assert_supported_batch_store(store)

            source_templates: dict[str, Any] = {}
            sections: dict[str, Any] = {}
            validation_templates: list[dict[str, Any]] = []
            for section in BATCH_TEMPLATE_REQUIRED_SECTIONS:
                selection = selections[section]
                row = conn.execute(
                    "SELECT * FROM templates WHERE id=?",
                    (selection["template_id"],),
                ).fetchone()
                if not row:
                    _reject("TEMPLATE_SOURCE_NOT_FOUND", f"source template {section} does not exist")
                template = _decode_template(row)
                snapshot = source_template_snapshot(template)
                digest = canonical_sha256(snapshot)
                if not isinstance(selection["source_digest"], str) or selection["source_digest"].upper() != digest:
                    _reject(
                        "TEMPLATE_SOURCE_DIGEST_DRIFT",
                        f"source template {section} changed after the operator selected it",
                    )
                if template["is_enabled"] is not True:
                    _reject("TEMPLATE_SOURCE_DISABLED", f"source template {section} is disabled")
                if template.get("requires_manual_configuration") is True:
                    _reject(
                        "TEMPLATE_SOURCE_REQUIRES_MANUAL_CONFIGURATION",
                        f"source template {section} is quarantined until an operator configures it",
                    )
                if template["template_type"] != section:
                    _reject("TEMPLATE_SOURCE_TYPE_MISMATCH", f"source template {section} has the wrong type")
                if not _binding_compatible(template, store, category):
                    _reject("TEMPLATE_SOURCE_BINDING_CONFLICT", f"source template {section} binding conflicts")
                try:
                    assert_no_publish_directives(template["payload"], path=f"sources.{section}")
                    normalized_section = normalize_bundle_source_section(section, template["payload"])
                except BatchContractError as exc:
                    raise BundleComposerError(exc.reason_code, str(exc)) from exc
                sections[section] = normalized_section
                source_templates[section] = {
                    "template_id": int(template["id"]),
                    "template_type": section,
                    "template_name": template["template_name"],
                    "binding_scope": template["binding_scope"],
                    "source_digest": digest,
                    "snapshot": snapshot,
                }
                validation_templates.append(template)

            validation = ConfigValidationService().validate_task(
                {
                    "mode": "single_save",
                    "store_id": int(store["id"]),
                    "store_name": store["name"],
                    "payload": {
                        "store_id": int(store["id"]),
                        "store_name": store["name"],
                        "category_name": category,
                        "publish": False,
                    },
                },
                validation_templates,
                product={"category_name": category, "payload": {}},
            )
            if validation["ok"] is not True:
                _reject(
                    "TEMPLATE_BUNDLE_INCOMPLETE",
                    "selected source templates do not satisfy single_save configuration",
                    missing=list(validation.get("missing") or []),
                )

            binding = {
                "store_id": int(store["id"]),
                "store_name": store["name"],
                "category_name": category,
                "platform": store["platform"],
            }
            payload = {
                "schema_version": TEMPLATE_BUNDLE_SCHEMA,
                "version": version,
                "required_sections": list(BATCH_TEMPLATE_REQUIRED_SECTIONS),
                "binding": binding,
                "source_templates": source_templates,
                "sections": sections,
            }
            try:
                assert_no_publish_directives(payload)
            except BatchContractError as exc:
                raise BundleComposerError(exc.reason_code, str(exc)) from exc
            identity_rows = conn.execute(
                "SELECT * FROM templates WHERE template_type=? AND template_name=? ORDER BY id ASC",
                (BATCH_TEMPLATE_TYPE, template_name),
            ).fetchall()
            for identity_row in identity_rows:
                existing = _decode_template(identity_row)
                existing_payload = existing["payload"]
                existing_binding = existing_payload.get("binding") if isinstance(existing_payload, Mapping) else None
                if (
                    isinstance(existing_binding, Mapping)
                    and existing_payload.get("version") == version
                    and existing_binding.get("store_id") == int(store["id"])
                    and existing_binding.get("category_name") == category
                ):
                    if canonical_sha256(existing_payload) == canonical_sha256(payload):
                        if existing.get("requires_manual_configuration") is True:
                            _reject(
                                "TEMPLATE_BUNDLE_REQUIRES_MANUAL_CONFIGURATION",
                                "matching bundle remains quarantined until its payload is substantively changed",
                            )
                        reactivated = existing["is_enabled"] is not True
                        if reactivated:
                            conn.execute(
                                "UPDATE templates SET is_enabled=1, updated_at=? WHERE id=?",
                                (now, existing["id"]),
                            )
                            refreshed = conn.execute(
                                "SELECT * FROM templates WHERE id=?",
                                (existing["id"],),
                            ).fetchone()
                            existing = _decode_template(refreshed)
                        return {**existing, "idempotent": True, "reactivated": reactivated}
                    _reject(
                        "TEMPLATE_BUNDLE_VERSION_CONFLICT",
                        "bundle identity already exists with different content",
                    )

            binding_scope = f"store:{int(store['id'])};category:{category or '*'}"
            cursor = conn.execute(
                """
                INSERT INTO templates (
                    template_type, template_name, binding_scope, payload_json,
                    is_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (BATCH_TEMPLATE_TYPE, template_name, binding_scope, dumps(payload), now, now),
            )
            created = conn.execute("SELECT * FROM templates WHERE id=?", (cursor.lastrowid,)).fetchone()
            return {**_decode_template(created), "idempotent": False, "reactivated": False}

    def _candidate_summary(
        self,
        template: dict[str, Any],
        section: str,
        store: dict[str, Any],
        category: str | None,
    ) -> dict[str, Any]:
        snapshot = source_template_snapshot(template)
        missing: list[str] = []
        if template["is_enabled"] is not True:
            missing.append("is_enabled")
        if template.get("requires_manual_configuration") is True:
            missing.append("requires_manual_configuration")
        if not _binding_compatible(template, store, category):
            missing.append("binding")
        try:
            assert_no_publish_directives(template["payload"], path=f"sources.{section}")
            normalized = normalize_bundle_source_section(section, template["payload"])
            missing.extend(_section_missing_fields(section, normalized))
        except BatchContractError as exc:
            missing.append(exc.reason_code)
        return {
            "template_id": int(template["id"]),
            "template_name": template["template_name"],
            "template_type": template["template_type"],
            "binding_scope": template["binding_scope"],
            "source_digest": canonical_sha256(snapshot),
            "missing_fields": list(dict.fromkeys(missing)),
            "ready": not missing,
        }


def _decode_template(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "template_type": row["template_type"],
        "template_name": row["template_name"],
        "binding_scope": row["binding_scope"],
        "payload": loads(row["payload_json"], {}),
        "is_enabled": bool(row["is_enabled"]),
        "requires_manual_configuration": bool(
            row.get("requires_manual_configuration")
        ),
        "quarantine_reason": row.get("quarantine_reason"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _binding_compatible(
    template: Mapping[str, Any],
    store: Mapping[str, Any],
    category: str | None,
) -> bool:
    payload = template.get("payload")
    binding = payload.get("binding") if isinstance(payload, Mapping) else None
    if isinstance(binding, Mapping):
        return (
            _binding_value_matches(
                binding,
                ("store_id",),
                int(store["id"]),
            )
            and _binding_value_matches(
                binding,
                ("store_name", "store", "stores", "store_names"),
                store["name"],
            )
            and _binding_value_matches(
                binding,
                ("category_name", "category", "categories", "category_names"),
                category,
            )
            and _binding_value_matches(binding, ("platform", "platforms"), store["platform"])
        )
    scope = str(template.get("binding_scope") or "").strip().casefold()
    if scope in {"*", "global"}:
        return True
    if not scope:
        return False
    store_name = str(store["name"]).strip().casefold()
    category_text = str(category or "").strip().casefold()
    platform = str(store["platform"] or "").strip().casefold()
    store_id = str(int(store["id"]))
    tokens = [token.strip() for token in re.split(r"[/|;,>]", scope) if token.strip()]
    if not tokens:
        return False
    plain_allowed = {store_name, platform, store_id}
    if category_text:
        plain_allowed.add(category_text)
    for token in tokens:
        if ":" not in token:
            if token not in plain_allowed:
                return False
            continue
        key, value = (part.strip() for part in token.split(":", 1))
        expected = {
            "store": store_name,
            "store_name": store_name,
            "store_id": store_id,
            "category": category_text,
            "category_name": category_text,
            "platform": platform,
        }.get(key)
        if expected is None or value not in {expected, "*"}:
            return False
    return True


def _binding_value_matches(binding: Mapping[str, Any], keys: tuple[str, ...], actual: Any) -> bool:
    expected = next((binding[key] for key in keys if key in binding), None)
    if expected is None or expected == "":
        return True
    values = expected if isinstance(expected, (list, tuple, set)) else [expected]
    normalized = {str(value or "").strip().casefold() for value in values}
    return bool(normalized & {"*", "all"}) or str(actual or "").strip().casefold() in normalized


def _section_missing_fields(section: str, value: Mapping[str, Any]) -> list[str]:
    if section == "logistics":
        return [f"logistics.{key}" for key in ("weight", "length", "width", "height") if not value.get(key)]
    if section == "image":
        return [
            field
            for field, key in (
                ("image.eu_outer_package_filename", "eu_outer_package_filename"),
                ("image.marketing_images_strategy", "marketing_images_strategy"),
            )
            if not value.get(key)
        ]
    if section == "semi_managed":
        missing = []
        if not (value.get("product_price") or value.get("supply_price")):
            missing.append("semi_managed.product_price_or_supply_price")
        for key in ("jit_stock", "is_original_box", "length", "width", "height", "goods_code_strategy", "barcode_strategy"):
            if value.get(key) in {None, ""}:
                missing.append(f"semi_managed.{key}")
        return missing
    if section == "category":
        if not any(value.get(key) for key in ("category_match", "category_name", "category_keyword", "template_category_id")):
            return ["category"]
    if section == "dxm_reference":
        references = value.get("dxm_reference_templates")
        if not isinstance(references, Mapping):
            return ["dxm_reference_templates"]
        return [
            f"dxm_reference_templates.{name}"
            for name in REFERENCE_TEMPLATE_SECTIONS
            if references.get(name, {}).get("required", True)
            and not references.get(name, {}).get("names")
        ]
    return []


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _assert_supported_batch_store(store: Mapping[str, Any]) -> None:
    if str(store.get("platform") or "").strip().casefold() != "aliexpress":
        _reject(
            "BATCH_PLATFORM_UNSUPPORTED",
            "controlled edit batches currently support only the AliExpress draft-box workflow",
        )


def _reject(
    reason_code: str,
    detail: str,
    *,
    status_code: int = 409,
    missing: list[str] | None = None,
) -> None:
    raise BundleComposerError(reason_code, detail, status_code=status_code, missing=missing)


class ContentFinalizeOrder:
    """Enforces the hard sequence for ContentFinalize steps.

    Hard sequence: Step 1=wholesale, Step 2=video, Step 3=translation
    Each step runs HVD checkpoint after completion.
    If Step N fails → subsequent steps are blocked_pre_write.
    No reordering allowed.
    """

    STEP_SEQUENCE = ["wholesale", "video", "translation"]

    def __init__(self) -> None:
        self._step_results: dict[str, dict[str, Any]] = {}
        self._failed_at_step: str | None = None

    def execute_step(
        self,
        step: str,
        executor: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute one ContentFinalize step if not already blocked.

        Args:
            step: one of "wholesale", "video", "translation"
            executor: the section executor (BatchVideoGenerator, WholesaleFiller, BatchTranslator)
            context: execution context

        Returns:
            dict with keys: status ("success", "blocked_pre_write", "failed"), checkpoint, result
        """
        if self._failed_at_step is not None:
            idx_failed = self.STEP_SEQUENCE.index(self._failed_at_step)
            idx_current = self._get_step_index(step)
            if idx_current > idx_failed:
                return {
                    "status": "blocked_pre_write",
                    "blocked_by": self._failed_at_step,
                    "blocked_reason": f"Step '{step}' blocked because '{self._failed_at_step}' failed",
                    "checkpoint": None,
                    "result": None,
                }

        if step not in self.STEP_SEQUENCE:
            return {
                "status": "failed",
                "error": f"Unknown ContentFinalize step: {step}",
                "checkpoint": None,
                "result": None,
            }

        idx_current = self.STEP_SEQUENCE.index(step)
        for prev_step in self.STEP_SEQUENCE[:idx_current]:
            if self._failed_at_step == prev_step:
                return {
                    "status": "blocked_pre_write",
                    "blocked_by": prev_step,
                    "blocked_reason": f"Step '{step}' blocked because '{prev_step}' failed",
                    "checkpoint": None,
                    "result": None,
                }

        try:
            result = executor(context)
        except Exception as exc:
            self._failed_at_step = step
            self._step_results[step] = {"success": False, "error": str(exc)}
            return {
                "status": "failed",
                "error": str(exc),
                "checkpoint": self._run_hvd_checkpoint(step),
                "result": None,
            }

        if not result.get("success", False):
            self._failed_at_step = step
            self._step_results[step] = result
            return {
                "status": "failed",
                "error": result.get("error_message") or result.get("error") or "unknown error",
                "checkpoint": self._run_hvd_checkpoint(step),
                "result": result,
            }

        self._step_results[step] = result
        return {
            "status": "success",
            "checkpoint": self._run_hvd_checkpoint(step),
            "result": result,
        }

    def is_step_blocked(self, step: str) -> bool:
        """Check if a step is blocked by a prior failure."""
        if self._failed_at_step is None:
            return False
        idx_failed = self.STEP_SEQUENCE.index(self._failed_at_step)
        idx_current = self._get_step_index(step)
        return idx_current > idx_failed

    def get_blocked_steps(self) -> list[str]:
        """Get list of blocked steps."""
        if self._failed_at_step is None:
            return []
        idx_failed = self.STEP_SEQUENCE.index(self._failed_at_step)
        return self.STEP_SEQUENCE[idx_failed + 1:]

    def get_step_results(self) -> dict[str, dict[str, Any]]:
        """Get results for all executed steps."""
        return dict(self._step_results)

    def is_complete(self) -> bool:
        """Check if all steps completed successfully."""
        if self._failed_at_step is not None:
            return False
        return all(step in self._step_results for step in self.STEP_SEQUENCE)

    def _get_step_index(self, step: str) -> int:
        try:
            return self.STEP_SEQUENCE.index(step)
        except ValueError:
            return -1

    def _run_hvd_checkpoint(self, completed_step: str) -> dict[str, Any]:
        """Run HVD checkpoint after step completion."""
        return {
            "checkpoint_step": completed_step,
            "checkpoint_type": "HVD",
            "completed_steps": list(self._step_results.keys()),
            "failed_step": self._failed_at_step,
            "blocked_steps": self.get_blocked_steps(),
        }

    def reset(self) -> None:
        """Reset all step results and failure state."""
        self._step_results.clear()
        self._failed_at_step = None
