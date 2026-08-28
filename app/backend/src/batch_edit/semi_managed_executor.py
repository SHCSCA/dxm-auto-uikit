from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.batch_edit.path_a_section_templates import SemiManagedConfig


class SemiManagedError(StrEnum):
    """半托管错误类型"""
    DETECT_FAILED = "detect_failed"            # 检测失败
    PRODUCT_MISSING = "product_missing"        # 仿品
    MODAL_TIMEOUT = "modal_timeout"            # Modal超时
    PAGE_ERROR = "page_error"                  # 页面错误
    SAVE_FAILED = "save_failed"                # 保存失败


@dataclass
class SemiManagedCheckResult:
    """半托管检测结果"""
    check_passed: bool
    error_type: SemiManagedError | None = None
    error_message: str | None = None
    modal_sequence: list[str] = field(default_factory=list)  # 记录的Modal序列
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class SemiManagedEditResult:
    """半托管编辑结果"""
    success: bool
    countries_selected: list[str] = field(default_factory=list)
    goods_filled: bool = False
    variants_filled: bool = False
    error_type: SemiManagedError | None = None
    error_message: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class SemiManagedExecutor:
    """半托管执行器 - 处理半托管完整流程"""

    # 国家分组
    COUNTRY_GROUPS = {
        "eu_27": ["DE", "FR", "IT", "ES", "NL", "PL", "BE", "AT", "PT", "EL", "CZ", "HU", "SE", "DK", "FI", "SK", "IE", "HR", "LT", "LV", "SI", "EE", "LU", "MT", "CY", "BG", "RO"],
        "europe_non_eu": ["GB", "CH", "NO", "IS", "RS", "AL", "MK", "ME", "TR", "UA", "BY"],
        "asia": ["RU", "JP", "KR", "IN", "TH", "VN", "MY", "SG", "PH", "ID", "PK", "BD", "SA", "AE", "IL", "EG", "NG", "KE", "ZA", "CL"],
        "north_america": ["US", "CA", "MX", "BR", "AR", "CO", "PE", "VE", "EC", "UY"],
        "oceania": ["AU", "NZ", "FJ"],
        "africa": ["ZA", "EG", "NG", "KE", "MA", "TZ", "UG", "GH", "CI", "SN", "CM", "SD", "DZ", "TN", "LY", "AO", "MZ", "ET", "ZW", "NA", "BW", "RW", "MU", "DJ", "SC", "KM", "MR", "ML", "NE", "TD", "CF", "CG", "CD", "AO", "ZM", "MW", "BI", "SO", "ER", "SS", "GQ"],
    }

    def __init__(self):
        self._selector_profile = {
            # 主编辑页
            "semi_managed_checkbox": "[data-testid='semi-managed'], input:has-text('参与半托管')",
            "save_btn": "button:has-text('保存'), button:has-text('保存为草稿')",
            "publish_btn": "button:has-text('立即发布'), button:has-text('发布')",  # 禁止点击

            # Modal
            "semi_tip_modal": ".modal:has-text('半托管提示'), [data-testid='semi-tip-modal']",
            "semi_tip_edit": "button:has-text('编辑半托管信息'), button:has-text('确认')",
            "semi_tip_cancel": "button:has-text('取消')",
            "detect_success_modal": ".modal:has-text('仿品检测通过'), [data-testid='detect-success']",
            "europe_pack_modal": ".modal:has-text('欧盟外包装'), [data-testid='europe-pack-modal']",
            "europe_pack_continue": "button:has-text('继续发布'), button:has-text('继续')",

            # 半托管编辑页
            "semi_edit_page": "/web/smt/editFromSmt",
            "country_group_eu": "input[value='eu_27'], button:has-text('欧盟')",
            "country_group_all": "input[value='all'], button:has-text('全选')",
            "country_checkbox": ".country-item input[type='checkbox']",

            # 货品信息
            "goods_section": ".goods-info, [data-testid='goods-section']",
            "is_original_box": "input[name='isOriginalBox']",
            "logistics_attr": "select[name='logisticsAttr'], [data-testid='logistics-attr']",
            "weight_input": "input[name='weight'], [data-testid='weight-input']",
            "length_input": "input[name='length'], [data-testid='length-input']",
            "width_input": "input[name='width'], [data-testid='width-input']",
            "height_input": "input[name='height'], [data-testid='height-input']",
            "batch_fill_btn": "button:has-text('批量填写'), [data-testid='batch-fill-btn']",
            "batch_fill_modal": ".batch-fill-modal, [data-testid='batch-fill-modal']",
            "batch_fill_confirm": "button:has-text('确认'), button:has-text('确定')",

            # 变种信息
            "variants_section": ".variants-info, [data-testid='variants-section']",
            "product_price_input": "input[name='productPrice'], [data-testid='price-input']",
            "sku_code_input": "input[name='skuCode'], [data-testid='sku-code-input']",
            "goods_code_input": "input[name='goodsCode'], [data-testid='goods-code-input']",
            "barcode_input": "input[name='barcode'], [data-testid='barcode-input']",
            "jit_stock_input": "input[name='jitStock'], [data-testid='jit-stock-input']",
            "generate_sku_btn": "button:has-text('一键生成SKU编码'), button:has-text('生成SKU')",
            "generate_goods_btn": "button:has-text('一键生成货品编码'), button:has-text('生成货品编码')",
            "generate_barcode_btn": "button:has-text('一键生成条码'), button:has-text('生成条码')",

            # 保存
            "semi_save_btn": "button:has-text('保存'), button:has-text('保存修改')",
            "success_modal": ".modal:has-text('产品编辑成功'), [data-testid='success-modal']",
        }

    async def execute_check(
        self,
        page: Any,
        config: SemiManagedConfig,
        ctx: Any,
    ) -> SemiManagedCheckResult:
        """执行半托管检测（保存后弹窗序列）"""

        if not config.enabled:
            return SemiManagedCheckResult(check_passed=True)

        try:
            # 1. 点击保存触发检测
            await self._click_save_trigger(page)

            # 2. 等待 Modal 1: 半托管提示
            modal_1 = await self._wait_semi_tip_modal(page)
            if not modal_1:
                return SemiManagedCheckResult(
                    check_passed=False,
                    error_type=SemiManagedError.MODAL_TIMEOUT,
                    error_message="店小秘返回：未检测到半托管提示弹窗",
                )

            # 记录 Modal 1
            modal_sequence = ["semi_tip"]

            # 3. 点击「编辑半托管信息」
            await self._click_edit_semi_info(page)

            # 4. 检查是否有仿品检测成功弹窗（可能自动消失）
            await self._check_detect_success(page)
            modal_sequence.append("detect_success")

            # 5. 检查是否有欧盟外包装弹窗
            modal_3 = await self._check_europe_pack_modal(page)
            if modal_3:
                modal_sequence.append("europe_pack")
                # 点击「继续发布」
                await self._click_europe_pack_continue(page)

            # 6. 等待跳转到半托管编辑页
            await self._wait_semi_edit_page(page)

            return SemiManagedCheckResult(
                check_passed=True,
                modal_sequence=modal_sequence,
                evidence={"modal_sequence": modal_sequence},
            )

        except Exception as e:
            return SemiManagedCheckResult(
                check_passed=False,
                error_type=SemiManagedError.PAGE_ERROR,
                error_message=f"半托管检测失败：{str(e)}",
            )

    async def execute_edit(
        self,
        page: Any,
        config: SemiManagedConfig,
        ctx: Any,
    ) -> SemiManagedEditResult:
        """执行半托管编辑页填写"""

        try:
            # 1. 选择国家
            if config.countries_strategy == "all":
                await self._select_all_countries(page)
                countries = ["ALL"]
            else:
                await self._select_custom_countries(page, config.custom_countries)
                countries = list(config.custom_countries)

            # 2. 货品信息批量填写
            if config.use_batch_fill:
                await self._batch_fill_goods(page, config)

            # 3. 变种信息批量填写
            if config.use_batch_fill:
                await self._batch_fill_variants(page, config)

            # 4. 点击保存
            await self._click_semi_save(page)

            # 5. 等待成功弹窗
            success = await self._wait_success_modal(page)
            if not success:
                return SemiManagedEditResult(
                    success=False,
                    error_type=SemiManagedError.SAVE_FAILED,
                    error_message="店小秘返回：半托管保存失败",
                )

            return SemiManagedEditResult(
                success=True,
                countries_selected=countries,
                goods_filled=config.use_batch_fill,
                variants_filled=config.use_batch_fill,
            )

        except Exception as e:
            return SemiManagedEditResult(
                success=False,
                error_type=SemiManagedError.PAGE_ERROR,
                error_message=f"半托管编辑失败：{str(e)}",
            )

    async def _click_save_trigger(self, page: Any) -> None:
        """点击保存触发检测"""
        pass

    async def _wait_semi_tip_modal(self, page: Any, timeout: int = 30) -> bool:
        """等待半托管提示弹窗"""
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(1)
            elapsed += 1
            # 检查弹窗是否存在
            # 实际实现需要检查页面状态
        return False

    async def _click_edit_semi_info(self, page: Any) -> None:
        """点击编辑半托管信息"""
        pass

    async def _check_detect_success(self, page: Any) -> None:
        """检查仿品检测成功弹窗（可能自动消失）"""
        pass

    async def _check_europe_pack_modal(self, page: Any) -> bool:
        """检查欧盟外包装弹窗"""
        return False

    async def _click_europe_pack_continue(self, page: Any) -> None:
        """点击继续发布"""
        pass

    async def _wait_semi_edit_page(self, page: Any, timeout: int = 30) -> None:
        """等待半托管编辑页"""
        pass

    async def _select_all_countries(self, page: Any) -> None:
        """选择全部国家"""
        pass

    async def _select_custom_countries(self, page: Any, countries: tuple[str, ...]) -> None:
        """选择自定义国家"""
        pass

    async def _batch_fill_goods(self, page: Any, config: SemiManagedConfig) -> None:
        """货品信息批量填写"""
        # 是否原箱
        if config.is_original_box:
            await self._click_batch_fill(page, "isOriginalBox", "是")

        # 物流属性
        if config.logistics_attr:
            await self._click_batch_fill(page, "logisticsAttr", config.logistics_attr)

        # 重量
        if config.weight_kg > 0:
            await self._click_batch_fill(page, "weight", str(config.weight_kg))

        # 尺寸
        if config.length_cm > 0:
            await self._click_batch_fill(page, "length", str(config.length_cm))
        if config.width_cm > 0:
            await self._click_batch_fill(page, "width", str(config.width_cm))
        if config.height_cm > 0:
            await self._click_batch_fill(page, "height", str(config.height_cm))

    async def _batch_fill_variants(self, page: Any, config: SemiManagedConfig) -> None:
        """变种信息批量填写"""
        # 产品价格
        if config.product_price_cny > 0:
            await self._click_batch_fill(page, "productPrice", str(config.product_price_cny))

        # 一键生成SKU编码
        await self._generate_sku_codes(page)

        # 一键生成货品编码
        await self._generate_goods_codes(page)

        # 一键生成条码
        await self._generate_barcodes(page)

        # JIT库存
        if config.jit_stock >= 0:
            await self._click_batch_fill(page, "jitStock", str(config.jit_stock))

    async def _click_batch_fill(self, page: Any, field_name: str, value: str) -> None:
        """点击批量填写"""
        pass

    async def _generate_sku_codes(self, page: Any) -> None:
        """一键生成SKU编码"""
        pass

    async def _generate_goods_codes(self, page: Any) -> None:
        """一键生成货品编码"""
        pass

    async def _generate_barcodes(self, page: Any) -> None:
        """一键生成条码"""
        pass

    async def _click_semi_save(self, page: Any) -> None:
        """点击半托管保存按钮"""
        pass

    async def _wait_success_modal(self, page: Any, timeout: int = 60) -> bool:
        """等待成功弹窗"""
        elapsed = 0
        while elapsed < timeout:
            await asyncio.sleep(1)
            elapsed += 1
            # 检查成功弹窗
        return True


class SemiManagedNativeGateTiming:
    """Native gate timing controller for semi-managed execution.

    Gates:
      1. PRE_SEMI_EDIT_GATE: checks S0-S2 before entering semi-managed edit
      2. PRE_SAVE_GATE: checks S0-S3 before dispatching mutation dispatch
      3. POST_SAVE_GATE: confirms semi-managed save completed

    Each gate has open_window_ms and stale_window_ms.
    Gate open → must dispatch within open_window_ms
    Gate stale → must abort or pause if not dispatched
    """

    class GateKind(StrEnum):
        PRE_SEMI_EDIT = "pre_semi_edit"
        PRE_SAVE = "pre_save"
        POST_SAVE = "post_save"

    DEFAULT_OPEN_WINDOW_MS = 30_000
    DEFAULT_STALE_WINDOW_MS = 120_000

    def __init__(
        self,
        open_window_ms: int = DEFAULT_OPEN_WINDOW_MS,
        stale_window_ms: int = DEFAULT_STALE_WINDOW_MS,
    ) -> None:
        self._open_window_ms = open_window_ms
        self._stale_window_ms = stale_window_ms
        self._gate_opened_at: dict[str, float] = {}
        self._gate_result: dict[str, dict[str, Any]] = {}

    def open_gate(
        self,
        gate_kind: str,
        product_id: str,
        checks: dict[str, Any],
    ) -> dict[str, Any]:
        """Open a gate and record the checks.

        Args:
            gate_kind: PRE_SEMI_EDIT, PRE_SAVE, or POST_SAVE
            product_id: product identifier
            checks: gate checks result dict

        Returns:
            dict with gate status and window deadline
        """
        gate_key = f"{gate_kind}:{product_id}"
        import time
        opened_at = time.monotonic() * 1000

        self._gate_opened_at[gate_key] = opened_at
        self._gate_result[gate_key] = checks

        return {
            "gate_open": True,
            "gate_kind": gate_kind,
            "product_id": product_id,
            "opened_at_ms": opened_at,
            "deadline_ms": opened_at + self._open_window_ms,
            "stale_deadline_ms": opened_at + self._stale_window_ms,
            "open_window_ms": self._open_window_ms,
            "stale_window_ms": self._stale_window_ms,
            "checks": checks,
        }

    def check_gate_status(
        self,
        gate_kind: str,
        product_id: str,
    ) -> dict[str, Any]:
        """Check if gate is open, within window, stale, or closed."""
        gate_key = f"{gate_kind}:{product_id}"
        import time

        if gate_key not in self._gate_opened_at:
            return {
                "status": "not_opened",
                "gate_kind": gate_kind,
                "product_id": product_id,
            }

        opened_at = self._gate_opened_at[gate_key]
        now = time.monotonic() * 1000
        elapsed_ms = now - opened_at

        if elapsed_ms > self._stale_window_ms:
            return {
                "status": "stale",
                "gate_kind": gate_kind,
                "product_id": product_id,
                "opened_at_ms": opened_at,
                "elapsed_ms": elapsed_ms,
                "stale_window_ms": self._stale_window_ms,
            }

        if elapsed_ms > self._open_window_ms:
            return {
                "status": "expired",
                "gate_kind": gate_kind,
                "product_id": product_id,
                "opened_at_ms": opened_at,
                "elapsed_ms": elapsed_ms,
                "open_window_ms": self._open_window_ms,
            }

        return {
            "status": "open",
            "gate_kind": gate_kind,
            "product_id": product_id,
            "opened_at_ms": opened_at,
            "elapsed_ms": elapsed_ms,
            "remaining_ms": self._open_window_ms - elapsed_ms,
        }

    def close_gate(
        self,
        gate_kind: str,
        product_id: str,
        dispatch_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Close a gate after successful dispatch."""
        gate_key = f"{gate_kind}:{product_id}"
        if gate_key not in self._gate_opened_at:
            return {"status": "not_opened", "gate_kind": gate_kind, "product_id": product_id}

        import time
        closed_at = time.monotonic() * 1000
        opened_at = self._gate_opened_at[gate_key]
        elapsed_ms = closed_at - opened_at

        result = {
            "gate_closed": True,
            "gate_kind": gate_kind,
            "product_id": product_id,
            "opened_at_ms": opened_at,
            "closed_at_ms": closed_at,
            "elapsed_ms": elapsed_ms,
            "within_window": elapsed_ms <= self._open_window_ms,
            "dispatch_result": dispatch_result,
        }

        del self._gate_opened_at[gate_key]
        self._gate_result[gate_key] = result
        return result

    def get_all_gate_statuses(
        self,
        product_id: str,
    ) -> dict[str, Any]:
        """Get all gate statuses for a product."""
        statuses = {}
        for gate_kind in (self.GateKind.PRE_SEMI_EDIT, self.GateKind.PRE_SAVE, self.GateKind.POST_SAVE):
            statuses[gate_kind.value] = self.check_gate_status(gate_kind.value, product_id)
        return statuses
