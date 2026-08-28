"""
Real adapter for one-click translation in batch edit workflow.

Translates title, attributes, description (PC + mobile), custom name.
Records before/after values and evidence.
Dispatch uncertain → execution_state=UNKNOWN.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.batch_edit.path_a_section_templates import AutoTranslateConfig


class TranslateError(StrEnum):
    """翻译错误类型"""

    TRANSLATION_FAILED = "translation_failed"
    TIMEOUT = "timeout"
    NO_CHANGES = "no_changes"
    DISPATCH_UNCERTAIN = "dispatch_uncertain"
    FIELD_MISSING = "field_missing"


@dataclass
class TranslateResult:
    """翻译结果 (real adapter with full evidence)."""

    success: bool
    translated_fields: int = 0
    field_changes: dict[str, dict[str, str]] = field(default_factory=dict)
    error_type: TranslateError | None = None
    error_message: str | None = None
    dispatch_state: str = "unknown"
    evidence: dict[str, Any] = field(default_factory=dict)


class BatchTranslator:
    """Real one-click translation adapter for DXM batch edit workflow.

    Translates: title, attributes, description_pc, description_mobile, custom_name
    Records before/after values for every field.
    """

    DIRECTION_MAP = {
        "zh_en": ("中文", "英文"),
        "en_zh": ("英文", "中文"),
    }

    TRANSLATE_TYPE_MAP = {
        "normal": "普通翻译",
        "ai": "AI智能翻译",
    }

    def __init__(self, dxm_client: Any | None = None):
        self._dxm_client = dxm_client
        self._selector_profile = {
            "translate_btn": "[data-testid='translate-btn']",
            "translate_modal": "[data-testid='translate-modal']",
            "translate_type_normal": "[data-testid='translate-type-normal']",
            "translate_type_ai": "[data-testid='translate-type-ai']",
            "direction_zh_en": "[data-testid='direction-zh-en']",
            "direction_en_zh": "[data-testid='direction-en-zh']",
            "translate_confirm": "[data-testid='translate-confirm-btn']",
            "translate_cancel": "[data-testid='translate-cancel-btn']",
            "translate_loading": "[data-testid='translating']",
            "translate_success": "[data-testid='translate-complete']",
            "translate_error": "[data-testid='translate-error']",
            "field_title": "[data-testid='field-title'] input",
            "field_description_pc": "[data-testid='field-desc-pc'] textarea",
            "field_description_mobile": "[data-testid='field-desc-mobile'] textarea",
            "field_custom_name": "[data-testid='field-custom-name'] input",
            "field_attributes": "[data-testid='attribute-item']",
        }

    async def execute(
        self,
        page: Any,
        config: AutoTranslateConfig,
        ctx: dict[str, Any],
    ) -> TranslateResult:
        """Execute the translation pipeline.

        Args:
            page: Playwright page object
            config: AutoTranslateConfig with enabled, translate_type, direction, apply_to
            ctx: execution context with product_id, shop_id, field values

        Returns:
            TranslateResult with full evidence
        """
        if not config.enabled:
            return TranslateResult(
                success=False,
                translated_fields=0,
                error_type=TranslateError.FIELD_MISSING,
                error_message="翻译功能未启用，本步骤被跳过而非完成",
                dispatch_state="skipped",
                evidence={"skipped_reason": "config.enabled=False"},
            )

        product_id = ctx.get("product_id", "unknown")
        apply_to = config.apply_to or ["title", "attributes", "description_pc"]

        before_values = await self._capture_field_values(page, apply_to)

        modal_opened = await self._open_translate_modal(page, config)
        if not modal_opened.get("opened"):
            return TranslateResult(
                success=False,
                error_type=TranslateError.TRANSLATION_FAILED,
                error_message=modal_opened.get("error", "无法打开翻译弹窗"),
                dispatch_state="unknown",
                evidence={"modal_opened": modal_opened, "before_values": before_values},
            )

        confirmed = await self._configure_and_confirm(page, config)
        if not confirmed.get("confirmed"):
            return TranslateResult(
                success=False,
                error_type=TranslateError.TRANSLATION_FAILED,
                error_message=confirmed.get("error", "无法确认翻译"),
                dispatch_state="unknown",
                evidence={"confirmed": confirmed, "before_values": before_values},
            )

        completion_result = await self._wait_translation_complete(page)
        if not completion_result.get("completed"):
            return TranslateResult(
                success=False,
                error_type=completion_result.get("error_type", TranslateError.TIMEOUT),
                error_message=completion_result.get("error", "翻译超时"),
                dispatch_state="unknown",
                evidence={"completion_result": completion_result, "before_values": before_values},
            )

        after_values = await self._capture_field_values(page, apply_to)

        field_changes = self._compute_field_changes(before_values, after_values, apply_to)
        translated_count = len(field_changes)

        if translated_count == 0:
            return TranslateResult(
                success=True,
                translated_fields=0,
                field_changes={},
                dispatch_state="success",
                evidence={
                    "product_id": product_id,
                    "before_values": before_values,
                    "after_values": after_values,
                    "note": "no fields changed after translation",
                },
            )

        return TranslateResult(
            success=True,
            translated_fields=translated_count,
            field_changes=field_changes,
            dispatch_state="success",
            evidence={
                "product_id": product_id,
                "before_values": before_values,
                "after_values": after_values,
                "completion_result": completion_result,
            },
        )

    async def _open_translate_modal(
        self,
        page: Any,
        config: AutoTranslateConfig,
    ) -> dict[str, Any]:
        """Open the translate modal."""
        try:
            btn = await page.query_selector(self._selector_profile["translate_btn"])
            if not btn:
                return {"opened": False, "error": "翻译按钮未找到"}

            await btn.click()
            await asyncio.sleep(1)

            modal = await page.query_selector(self._selector_profile["translate_modal"])
            if not modal:
                return {"opened": False, "error": "翻译弹窗未出现"}

            return {"opened": True, "modal_visible": True}
        except Exception as exc:
            return {"opened": False, "error": str(exc)}

    async def _configure_and_confirm(
        self,
        page: Any,
        config: AutoTranslateConfig,
    ) -> dict[str, Any]:
        """Configure translate type and direction, then confirm."""
        try:
            translate_type = getattr(config, "translate_type", "normal")
            if translate_type == "ai":
                type_selector = self._selector_profile["translate_type_ai"]
            else:
                type_selector = self._selector_profile["translate_type_normal"]

            type_btn = await page.query_selector(type_selector)
            if type_btn:
                await type_btn.click()
                await asyncio.sleep(0.5)

            direction = getattr(config, "direction", "zh_en")
            if direction == "en_zh":
                dir_selector = self._selector_profile["direction_en_zh"]
            else:
                dir_selector = self._selector_profile["direction_zh_en"]

            dir_btn = await page.query_selector(dir_selector)
            if dir_btn:
                await dir_btn.click()
                await asyncio.sleep(0.5)

            confirm_btn = await page.query_selector(self._selector_profile["translate_confirm"])
            if not confirm_btn:
                return {"confirmed": False, "error": "翻译确认按钮未找到"}

            await confirm_btn.click()
            return {"confirmed": True}
        except Exception as exc:
            return {"confirmed": False, "error": str(exc)}

    async def _wait_translation_complete(self, page: Any, timeout: int = 120) -> dict[str, Any]:
        """Wait for translation to complete."""
        elapsed = 0
        interval = 3

        while elapsed < timeout:
            await asyncio.sleep(interval)
            elapsed += interval

            try:
                error_elem = await page.query_selector(self._selector_profile["translate_error"])
                if error_elem:
                    error_text = await error_elem.inner_text()
                    return {
                        "completed": False,
                        "error_type": TranslateError.TRANSLATION_FAILED,
                        "error": f"翻译失败：{error_text}",
                    }

                success_elem = await page.query_selector(self._selector_profile["translate_success"])
                if success_elem:
                    return {"completed": True, "state": "success"}

                loading_elem = await page.query_selector(self._selector_profile["translate_loading"])
                if not loading_elem:
                    any_modal = await page.query_selector(self._selector_profile["translate_modal"])
                    if not any_modal:
                        return {"completed": True, "state": "auto_closed"}

            except Exception:
                pass

        return {
            "completed": False,
            "error_type": TranslateError.TIMEOUT,
            "error": f"翻译超时（等待 {timeout} 秒）",
        }

    async def _capture_field_values(
        self,
        page: Any,
        apply_to: list[str],
    ) -> dict[str, str]:
        """Capture field values before/after translation."""
        result = {}

        if "title" in apply_to:
            try:
                elem = await page.query_selector(self._selector_profile["field_title"])
                if elem:
                    result["title"] = await elem.input_value() or await elem.inner_text() or ""
                else:
                    result["title"] = ""
            except Exception:
                result["title"] = ""

        if "description_pc" in apply_to:
            try:
                elem = await page.query_selector(self._selector_profile["field_description_pc"])
                if elem:
                    result["description_pc"] = await elem.input_value() or await elem.inner_text() or ""
                else:
                    result["description_pc"] = ""
            except Exception:
                result["description_pc"] = ""

        if "description_mobile" in apply_to:
            try:
                elem = await page.query_selector(self._selector_profile["field_description_mobile"])
                if elem:
                    result["description_mobile"] = await elem.input_value() or await elem.inner_text() or ""
                else:
                    result["description_mobile"] = ""
            except Exception:
                result["description_mobile"] = ""

        if "custom_name" in apply_to:
            try:
                elem = await page.query_selector(self._selector_profile["field_custom_name"])
                if elem:
                    result["custom_name"] = await elem.input_value() or await elem.inner_text() or ""
                else:
                    result["custom_name"] = ""
            except Exception:
                result["custom_name"] = ""

        if "attributes" in apply_to:
            try:
                attr_elems = await page.query_selector_all(self._selector_profile["field_attributes"])
                attr_values = []
                for elem in attr_elems:
                    val = await elem.inner_text() or ""
                    if val.strip():
                        attr_values.append(val.strip())
                result["attributes"] = "\n".join(attr_values)
            except Exception:
                result["attributes"] = ""

        return result

    def _compute_field_changes(
        self,
        before: dict[str, str],
        after: dict[str, str],
        apply_to: list[str],
    ) -> dict[str, dict[str, str]]:
        """Compute field changes between before and after values."""
        changes = {}
        for field_name in apply_to:
            before_val = before.get(field_name, "")
            after_val = after.get(field_name, "")
            if before_val != after_val:
                changes[field_name] = {
                    "before": before_val,
                    "after": after_val,
                }
        return changes
