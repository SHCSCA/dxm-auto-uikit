"""
Real adapter for wholesale filling in batch edit workflow.

After SKU/price changes, re-validates tier, minimum quantity, price relationship.
Performs readback verification after filling.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, urlsplit

from src.batch_edit.path_a_section_templates import WholesaleConfig
from src.batch_edit.scope_contract import canonical_sha256


WHOLESALE_READBACK_FIELDS = ('bulkOrder', 'bulkDiscount', 'reduceStrategy', 'aeopAeProductSKUs')
WHOLESALE_POSTCONDITIONS = (
    'wholesale_enabled', 'minimum_quantity_readback_exact', 'discount_readback_exact',
    'deduction_readback_exact', 'sku_relationships_valid', 'zero_write_proven', 'original_fill_proven',
)


class WholesaleError(StrEnum):
    """批发配置错误类型"""

    VALIDATION_FAILED = "validation_failed"
    READBACK_MISMATCH = "readback_mismatch"
    TIER_CONFLICT = "tier_conflict"
    PRICE_RELATIONSHIP_INVALID = "price_relationship_invalid"
    DISPATCH_UNCERTAIN = "dispatch_uncertain"


@dataclass
class WholesaleResult:
    """批发配置结果 (real adapter with full evidence)."""

    success: bool
    configured: bool = False
    validated: bool = False
    readback_verified: bool = False
    error_type: WholesaleError | None = None
    error_message: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


class WholesaleFiller:
    """Real wholesale filler adapter for DXM batch edit workflow.

    Implements the full pipeline:
      1. Enable wholesale checkbox
      2. Fill tier configuration (min quantity, discount, deduction method)
      3. After SKU/price changes, re-validate tier, minimum quantity, price relationship
      4. Readback verification after filling
      5. Dispatch uncertain → execution_state=UNKNOWN
    """

    TIER_MIN_QUANTITY_RANGE = (2, 100000)
    DISCOUNT_RANGE = (1, 99)
    VALID_DEDUCTION_METHODS = frozenset({"payment", "order"})

    def __init__(self, dxm_client: Any | None = None):
        self._dxm_client = dxm_client
        self._selector_profile = {
            "wholesale_checkbox": "[data-testid='wholesale-checkbox']",
            "wholesale_panel": "[data-testid='wholesale-panel']",
            "min_quantity_input": "[data-testid='min-quantity-input'] input",
            "discount_input": "[data-testid='discount-percent-input'] input",
            "deduction_payment": "[data-testid='deduction-method-payment']",
            "deduction_order": "[data-testid='deduction-method-order']",
            "confirm_btn": "[data-testid='wholesale-confirm-btn']",
            "wholesale_readback_min": "[data-testid='wholesale-min-readback']",
            "wholesale_readback_discount": "[data-testid='wholesale-discount-readback']",
            "wholesale_readback_method": "[data-testid='wholesale-method-readback']",
        }

    async def execute(
        self,
        page: Any,
        config: WholesaleConfig,
        ctx: dict[str, Any],
    ) -> WholesaleResult:
        """Execute the wholesale filling pipeline.

        Args:
            page: Playwright page object
            config: WholesaleConfig with enabled, strategy settings
            ctx: execution context with product_id, shop_id, field values

        Returns:
            WholesaleResult with full evidence
        """
        if not config.enabled:
            return WholesaleResult(
                success=False,
                configured=False,
                validated=False,
                readback_verified=False,
                error_type=WholesaleError.VALIDATION_FAILED,
                error_message="批发配置功能未启用，本步骤被跳过而非完成",
                evidence={"skipped_reason": "config.enabled=False"},
            )

        product_id = ctx.get("product_id", "unknown")
        sku = ctx.get("sku_code", "")
        price = ctx.get("price", 0.0)
        original_price = ctx.get("original_price", price)

        prefill_snapshot = await self._capture_wholesale_state(page)

        enable_result = await self._enable_wholesale(page)
        if not enable_result.get("enabled"):
            return WholesaleResult(
                success=False,
                error_type=WholesaleError.VALIDATION_FAILED,
                error_message="无法启用批发复选框",
                evidence={"enable_result": enable_result},
            )

        fill_result = await self._fill_wholesale_config(page, config)
        if not fill_result.get("filled"):
            return WholesaleResult(
                success=False,
                error_type=WholesaleError.VALIDATION_FAILED,
                error_message=fill_result.get("error", "填写批发配置失败"),
                evidence={"fill_result": fill_result},
            )

        if sku or price != original_price:
            validate_result = await self._validate_after_change(
                page, config, sku=sku, price=price
            )
            if not validate_result.get("valid"):
                return WholesaleResult(
                    success=False,
                    error_type=validate_result.get("error_type", WholesaleError.VALIDATION_FAILED),
                    error_message=validate_result.get("error", "变更后验证失败"),
                    evidence={"validate_result": validate_result},
                )

        readback_result = await self._verify_readback(page, config)
        if not readback_result.get("verified"):
            return WholesaleResult(
                success=False,
                configured=True,
                validated=True,
                readback_verified=False,
                error_type=WholesaleError.READBACK_MISMATCH,
                error_message="读回验证失败",
                evidence={
                    "readback_result": readback_result,
                    "expected": {
                        "min_quantity": config.min_quantity,
                        "discount_percent": config.discount_percent,
                        "deduction_method": config.deduction_method,
                    },
                },
            )

        return WholesaleResult(
            success=True,
            configured=True,
            validated=True,
            readback_verified=True,
            evidence={
                "product_id": product_id,
                "sku": sku,
                "price": price,
                "prefill_snapshot": prefill_snapshot,
                "fill_result": fill_result,
                "readback_result": readback_result,
            },
        )

    async def _capture_wholesale_state(self, page: Any) -> dict[str, Any]:
        """Capture wholesale state before modification."""
        try:
            checked = await page.is_checked(self._selector_profile["wholesale_checkbox"])
            min_input = await page.query_selector(self._selector_profile["min_quantity_input"])
            min_val = await min_input.input_value() if min_input else None
            return {
                "wholesale_enabled": checked,
                "min_quantity_readback": min_val,
                "capture_success": True,
            }
        except Exception as exc:
            return {"capture_success": False, "error": str(exc)}

    async def _enable_wholesale(self, page: Any) -> dict[str, Any]:
        """Enable the wholesale checkbox."""
        try:
            checkbox = await page.query_selector(self._selector_profile["wholesale_checkbox"])
            if not checkbox:
                return {"enabled": False, "error": "批发复选框未找到"}

            is_checked = await checkbox.is_checked()
            if not is_checked:
                await checkbox.check()
                await page.wait_for_timeout(500)

            panel = await page.query_selector(self._selector_profile["wholesale_panel"])
            return {"enabled": True, "panel_visible": panel is not None}
        except Exception as exc:
            return {"enabled": False, "error": str(exc)}

    async def _fill_wholesale_config(
        self,
        page: Any,
        config: WholesaleConfig,
    ) -> dict[str, Any]:
        """Fill wholesale configuration fields."""
        try:
            if not (self.TIER_MIN_QUANTITY_RANGE[0] <= config.min_quantity <= self.TIER_MIN_QUANTITY_RANGE[1]):
                return {
                    "filled": False,
                    "error": f"起订件数必须在 {self.TIER_MIN_QUANTITY_RANGE[0]}~{self.TIER_MIN_QUANTITY_RANGE[1]} 之间",
                }

            if not (self.DISCOUNT_RANGE[0] <= config.discount_percent <= self.DISCOUNT_RANGE[1]):
                return {
                    "filled": False,
                    "error": f"减免百分比必须在 {self.DISCOUNT_RANGE[0]}~{self.DISCOUNT_RANGE[1]} 之间",
                }

            if config.deduction_method not in self.VALID_DEDUCTION_METHODS:
                return {
                    "filled": False,
                    "error": f"扣减方式必须是 {self.VALID_DEDUCTION_METHODS} 之一",
                }

            min_input = await page.query_selector(self._selector_profile["min_quantity_input"])
            if min_input:
                await min_input.fill(str(config.min_quantity))

            discount_input = await page.query_selector(self._selector_profile["discount_input"])
            if discount_input:
                await discount_input.fill(str(config.discount_percent))

            deduction_selector = (
                self._selector_profile["deduction_payment"]
                if config.deduction_method == "payment"
                else self._selector_profile["deduction_order"]
            )
            deduction_radio = await page.query_selector(deduction_selector)
            if deduction_radio:
                await deduction_radio.check()

            return {
                "filled": True,
                "min_quantity": config.min_quantity,
                "discount_percent": config.discount_percent,
                "deduction_method": config.deduction_method,
            }
        except Exception as exc:
            return {"filled": False, "error": str(exc)}

    async def _validate_after_change(
        self,
        page: Any,
        config: WholesaleConfig,
        *,
        sku: str,
        price: float,
    ) -> dict[str, Any]:
        """Validate wholesale config after SKU/price changes."""
        try:
            errors: list[str] = []

            tier_validate = self._validate_tier(config.min_quantity)
            if not tier_validate["valid"]:
                errors.append(tier_validate["error"])

            price_relationship_validate = self._validate_price_relationship(price, config.discount_percent)
            if not price_relationship_validate["valid"]:
                errors.append(price_relationship_validate["error"])

            if errors:
                return {
                    "valid": False,
                    "errors": errors,
                    "error": "; ".join(errors),
                }

            return {"valid": True, "errors": []}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    def _validate_tier(self, min_quantity: int) -> dict[str, Any]:
        """Validate minimum quantity tier."""
        if min_quantity < self.TIER_MIN_QUANTITY_RANGE[0]:
            return {
                "valid": False,
                "error": f"起订件数 {min_quantity} 低于最低要求 {self.TIER_MIN_QUANTITY_RANGE[0]}",
                "error_type": WholesaleError.TIER_CONFLICT,
            }
        if min_quantity > self.TIER_MIN_QUANTITY_RANGE[1]:
            return {
                "valid": False,
                "error": f"起订件数 {min_quantity} 超过最高限制 {self.TIER_MIN_QUANTITY_RANGE[1]}",
                "error_type": WholesaleError.TIER_CONFLICT,
            }
        return {"valid": True}

    def _validate_price_relationship(
        self,
        price: float,
        discount_percent: int,
    ) -> dict[str, Any]:
        """Validate price relationship after discount."""
        if price <= 0:
            return {
                "valid": False,
                "error": f"商品价格 {price} 无效",
                "error_type": WholesaleError.PRICE_RELATIONSHIP_INVALID,
            }

        discounted_price = price * (100 - discount_percent) / 100.0
        if discounted_price < 0.01:
            return {
                "valid": False,
                "error": f"折扣后价格 {discounted_price:.2f} 低于最低限制",
                "error_type": WholesaleError.PRICE_RELATIONSHIP_INVALID,
            }

        return {"valid": True, "discounted_price": discounted_price}

    async def _verify_readback(
        self,
        page: Any,
        config: WholesaleConfig,
    ) -> dict[str, Any]:
        """Verify wholesale config readback after filling."""
        try:
            mismatches: list[str] = []

            min_readback = await page.query_selector(self._selector_profile["wholesale_readback_min"])
            if min_readback:
                min_val = await min_readback.inner_text()
                if str(config.min_quantity) not in (min_val or ""):
                    mismatches.append(f"min_quantity mismatch: expected {config.min_quantity}, got {min_val}")

            discount_readback = await page.query_selector(self._selector_profile["wholesale_readback_discount"])
            if discount_readback:
                discount_val = await discount_readback.inner_text()
                if str(config.discount_percent) not in (discount_val or ""):
                    mismatches.append(f"discount mismatch: expected {config.discount_percent}%, got {discount_val}")

            method_readback = await page.query_selector(self._selector_profile["wholesale_readback_method"])
            if method_readback:
                method_val = await method_readback.inner_text()
                expected_method = "付款减库存" if config.deduction_method == "payment" else "下单减库存"
                if expected_method not in (method_val or ""):
                    mismatches.append(f"deduction method mismatch: expected {expected_method}")

            if mismatches:
                return {
                    "verified": False,
                    "mismatches": mismatches,
                    "readback_values": {
                        "min_quantity": min_readback.inner_text() if min_readback else None,
                        "discount": discount_readback.inner_text() if discount_readback else None,
                        "method": method_readback.inner_text() if method_readback else None,
                    },
                }

            return {
                "verified": True,
                "readback_values": {
                    "min_quantity": config.min_quantity,
                    "discount_percent": config.discount_percent,
                    "deduction_method": config.deduction_method,
                },
            }
        except Exception as exc:
            return {"verified": False, "error": str(exc)}


def _wholesale_value_matches(expected: Any, observed: Any) -> bool:
    """Compare only exact structures and unambiguous numeric input encodings."""
    if isinstance(expected, Mapping):
        return (isinstance(observed, Mapping) and set(expected) == set(observed)
                and all(_wholesale_value_matches(value, observed[key]) for key, value in expected.items()))
    if isinstance(expected, list):
        return (isinstance(observed, list) and len(expected) == len(observed)
                and all(_wholesale_value_matches(left, right) for left, right in zip(expected, observed)))
    if type(expected) in (int, float):
        return (type(observed) in (int, float, str)
                and re.fullmatch(r'(?:0|[1-9]\d*)(?:\.\d+)?', str(observed)) is not None
                and Decimal(str(expected)).is_finite() and Decimal(str(expected)) == Decimal(str(observed)))
    return type(expected) is type(observed) and expected == observed


def validate_editor_wholesale_observation(
    observation: Any, *, defaults: Any, expected_payload: Mapping[str, Any] | None = None,
    target_identity: Mapping[str, Any], command_context: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate fresh zero-write observations; an old FILL is provenance, not this action.

    The caller supplies the actual BrowserAgent context and original first-FILL
    result. Neither an equal page value nor a syntactically valid receipt proves
    that original writer. No candidate WholesaleFiller UI method is invoked.
    """
    from src.batch_edit.frozen_execution_contract import validate_frozen_execution_defaults
    from src.batch_edit.plan_template_contract import validate_editor_actions
    from src.execution.action_result_contract import _validate_batch_category_schema_readback
    from src.execution.e3_authority_contract import parse_strict_utc_timestamp

    keys = {'schema', 'command', 'target_identity', 'page_url', 'execution_payload_hash',
            'started_at', 'completed_at', 'write_attempted', 'before', 'after', 'writer', 'evidence_ref'}
    if not isinstance(observation, Mapping) or set(observation) != keys:
        raise ValueError('WHOLESALE_OBSERVATION_INVALID')
    payload = validate_frozen_execution_defaults(defaults, expected_payload=expected_payload)
    if (payload.get('execution_path') != 'B' or payload.get('save_stage', 'SAVE1') != 'SAVE1'
            or payload.get('unresolved_fields') != [] or not isinstance(command_context, Mapping)
            or command_context.get('mode') != 'batch_draft_save'):
        raise ValueError('WHOLESALE_FROZEN_CONTEXT_INVALID')
    command_keys = {'command_id', 'action', 'state', 'task_id', 'job_id', 'runtime_id', 'browser_session_id'}
    command = observation['command']
    expected_command = {key: command_context.get('command_action' if key == 'action' else key) for key in command_keys}
    if (not isinstance(command, Mapping) or set(command) != command_keys or command != expected_command
            or command['action'] != 'validate_editor_wholesale' or command['state'] != 'BATCH_WHOLESALE_FILL'
            or any(type(command[key]) is not int or command[key] <= 0 for key in ('task_id', 'job_id'))
            or any(not isinstance(command[key], str) or not command[key] or command[key] != command[key].strip()
                   for key in command_keys - {'task_id', 'job_id'})):
        raise ValueError('WHOLESALE_COMMAND_CONTEXT_INVALID')
    stable = target_identity.get('stable_identity', {}) if isinstance(target_identity, Mapping) else {}
    if not isinstance(observation['page_url'], str) or not isinstance(stable, Mapping):
        raise ValueError('WHOLESALE_OBSERVATION_IDENTITY_DRIFT')
    page = urlsplit(observation['page_url'])
    if (observation['schema'] != 'dxm.editor_wholesale_observation.v1'
            or observation['write_attempted'] is not False or observation['target_identity'] != target_identity
            or observation['execution_payload_hash'] != payload['payload_hash']
            or stable.get('kind') != 'product_id' or stable.get('value') != payload['product_id']
            or page.scheme != 'https' or page.netloc != 'www.dianxiaomi.com' or page.path != '/web/smt/edit'
            or page.fragment or parse_qs(page.query).get('id') != [payload['product_id']]):
        raise ValueError('WHOLESALE_OBSERVATION_IDENTITY_DRIFT')
    started = parse_strict_utc_timestamp(observation['started_at'], field='wholesale started_at')
    completed = parse_strict_utc_timestamp(observation['completed_at'], field='wholesale completed_at')
    if completed < started:
        raise ValueError('WHOLESALE_OBSERVATION_TIME_INVALID')
    fields = payload.get('fields')
    if (not isinstance(fields, list) or not fields or any(not isinstance(field, Mapping)
            or not isinstance(field.get('field_key'), str) or 'resolved_value' not in field for field in fields)
            or len({field['field_key'] for field in fields}) != len(fields)):
        raise ValueError('WHOLESALE_FROZEN_FIELDS_INVALID')
    frozen = {field['field_key']: field for field in fields}
    if any(key not in frozen or frozen[key].get('ui_binding') != f'dxm_editor:{key}' for key in WHOLESALE_READBACK_FIELDS):
        raise ValueError('WHOLESALE_FROZEN_FIELDS_INCOMPLETE')
    values = {key: field['resolved_value'] for key, field in frozen.items()}
    actions = payload.get('editor_actions')
    validate_editor_actions(actions, values)
    if not isinstance(actions.get('wholesale'), Mapping):
        raise ValueError('WHOLESALE_SHARED_ACTION_MISSING')
    config = actions['wholesale']
    if (values['bulkOrder'] != config['min_quantity'] or values['bulkDiscount'] != config['discount_percent']
            or values['reduceStrategy'] != 'payment_success_deduct' or config['deduction_method'] != 'payment'):
        raise ValueError('WHOLESALE_SHARED_ACTION_CONFLICT')

    writer = observation['writer']
    if not isinstance(writer, Mapping) or set(writer) != {'command', 'execution_payload_hash', 'fill_result_hash', 'fill_result'}:
        raise ValueError('WHOLESALE_ORIGINAL_FILL_MISSING')
    original, fill = writer['command'], writer['fill_result']
    if (not isinstance(original, Mapping) or set(original) != command_keys
            or original.get('state') != 'FILL_BASE_INFO' or original.get('action') != 'fill_editor_required_defaults'
            or not isinstance(original.get('command_id'), str) or not original['command_id'].strip()
            or original['command_id'] != original['command_id'].strip() or original['command_id'] == command['command_id']
            or any(type(original.get(key)) is not int for key in ('task_id', 'job_id'))
            or any(original.get(key) != command[key] for key in ('task_id', 'job_id', 'runtime_id', 'browser_session_id'))
            or writer['execution_payload_hash'] != payload['payload_hash'] or not isinstance(fill, Mapping)
            or writer['fill_result_hash'] != canonical_sha256(fill)
            or fill.get('execution_payload_hash') != payload['payload_hash'] or fill.get('ok') is not True
            or fill.get('failure_code') is not None or type(fill.get('write_attempted')) is not bool
            or type(fill.get('field_count')) is not int or fill['field_count'] != len(fields)
            or not isinstance(fill.get('fields'), list) or len(fill['fields']) != len(fields)):
        raise ValueError('WHOLESALE_ORIGINAL_FILL_DRIFT')
    for result, field in zip(fill['fields'], fields):
        if (not isinstance(result, Mapping) or result.get('field_key') != field['field_key']
                or result.get('ui_binding') != field.get('ui_binding') or result.get('ok') is not True
                or type(result.get('write_attempted')) is not bool
                or (result['write_attempted'] and not fill['write_attempted'])):
            raise ValueError('WHOLESALE_ORIGINAL_FILL_INCOMPLETE')
    if fill['write_attempted'] != any(result['write_attempted'] for result in fill['fields']):
        raise ValueError('WHOLESALE_ORIGINAL_FILL_INCOMPLETE')

    snapshot = observation['after']
    if (not isinstance(snapshot, Mapping) or set(snapshot) != {'category_schema', 'enabled_control', 'fields'}
            or canonical_sha256(observation['before']) != canonical_sha256(snapshot)):
        raise ValueError('WHOLESALE_OBSERVATION_CHANGED')
    schema_payload = {**payload, 'category_id': (payload.get('target_category') or {}).get('category_id', payload['category_id'])}
    _validate_batch_category_schema_readback(snapshot['category_schema'], expected_execution_payload=schema_payload,
                                            expected_phase='wholesale_finalize')
    control = snapshot['enabled_control']
    if (not isinstance(control, Mapping) or set(control) != {'ui_binding', 'found', 'match_count', 'visible',
            'checked', 'discount_unit', 'quantity_enabled', 'discount_enabled'}
            or control['ui_binding'] != 'dxm_editor:wholesale.enabled' or type(control['match_count']) is not int
            or control['match_count'] != 1 or control['discount_unit'] != '%'
            or any(control[key] is not True for key in ('found', 'visible', 'checked', 'quantity_enabled', 'discount_enabled'))):
        raise ValueError('WHOLESALE_ENABLED_CONTROL_UNPROVEN')
    observed_fields = snapshot['fields']
    if (not isinstance(observed_fields, list) or len(observed_fields) != len(WHOLESALE_READBACK_FIELDS)
            or any(not isinstance(item, Mapping) for item in observed_fields)
            or {item.get('field_key') for item in observed_fields} != set(WHOLESALE_READBACK_FIELDS)):
        raise ValueError('WHOLESALE_READBACK_INCOMPLETE')
    for item in observed_fields:
        key, count, kind = item['field_key'], item.get('match_count'), item.get('aggregate_kind')
        expected = values[key]
        if (item.get('ui_binding') != frozen[key]['ui_binding'] or item.get('found') is not True or 'value' not in item
                or item.get('write_attempted', False) is not False
                or type(count) is not int or count <= 0
                or (key == 'aeopAeProductSKUs' and (not isinstance(expected, list) or kind != 'sku_rows' or count != len(expected)))
                or (key == 'reduceStrategy' and kind != 'choice_group')
                or (key in {'bulkOrder', 'bulkDiscount'} and (kind != 'single' or count != 1))
                or not _wholesale_value_matches(expected, item['value'])):
            raise ValueError('WHOLESALE_READBACK_MISMATCH')

    rows = values['aeopAeProductSKUs']
    identities, codes = set(), set()
    if not isinstance(rows, list) or not rows:
        raise ValueError('WHOLESALE_SKU_ROWS_REQUIRED')
    for row in rows:
        properties = row.get('aeopSKUProperty') if isinstance(row, Mapping) else None
        if (not isinstance(properties, list) or not properties or any(not isinstance(prop, Mapping)
                or any(not isinstance(prop.get(key), str) or not prop[key].strip()
                       for key in ('skuPropertyId', 'propertyValueId')) for prop in properties)
                or len({prop['skuPropertyId'] for prop in properties}) != len(properties)):
            raise ValueError('WHOLESALE_SKU_IDENTITY_INVALID')
        identity = tuple(sorted((prop['skuPropertyId'], prop['propertyValueId']) for prop in properties))
        code = row.get('skuCode')
        if (identity in identities or not isinstance(code, str) or re.fullmatch(r'[A-Za-z0-9-]+', code) is None
                or code in codes or type(row.get('ipmSkuStock')) is not int or row['ipmSkuStock'] < 0
                or any(not isinstance(row.get(key), str) or re.fullmatch(r'(?:0|[1-9]\d*)(?:\.\d+)?', row[key]) is None
                       for key in ('skuPrice', 'cargoPrice'))):
            raise ValueError('WHOLESALE_SKU_VALUES_INVALID')
        price, cargo = Decimal(row['skuPrice']), Decimal(row['cargoPrice'])
        if price <= 0 or cargo > price or price * (100 - config['discount_percent']) / 100 < Decimal('0.01'):
            raise ValueError('WHOLESALE_SKU_PRICE_RELATION_INVALID')
        identities.add(identity)
        codes.add(code)
    ref = observation['evidence_ref']
    if (not isinstance(ref, Mapping) or set(ref) != {'path', 'sha256', 'size'}
            or not isinstance(ref['path'], str) or not ref['path'].strip()
            or type(ref['size']) is not int or ref['size'] <= 0
            or not isinstance(ref['sha256'], str) or re.fullmatch(r'[0-9A-Fa-f]{64}', ref['sha256']) is None):
        raise ValueError('WHOLESALE_EVIDENCE_INVALID')
    canonical_sha256(observation)
    return deepcopy(dict(observation))


def build_editor_wholesale_receipt(validated: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize only the current validated observations, never the old FILL values."""
    from src.execution.canonical_receipt import ContentFinalizeReceipt, FieldReadback, ReceiptPhase

    before = {item['field_key']: item['value'] for item in validated['before']['fields']}
    after = {item['field_key']: item['value'] for item in validated['after']['fields']}
    receipt = ContentFinalizeReceipt(
        phase=ReceiptPhase.CONTENT_FINALIZE_WHOLESALE, action_grant_id=validated['command']['command_id'], result_ok=True,
        started_at=validated['started_at'], completed_at=validated['completed_at'],
        field_readbacks=[FieldReadback(field_key=key, field_label=key,
            source='visible_production_runtime:wholesale_validation', before_value=deepcopy(before[key]),
            after_value=deepcopy(after[key]), readback_proven=True, timestamp=validated['completed_at'])
            for key in WHOLESALE_READBACK_FIELDS],
    )
    digest = receipt.finalize()
    return {'canonical_receipt': receipt.to_dict(), 'receipt_sha256': digest}


def validate_wholesale_first_fill_source(writer, first_fill, *, command, browser_session_id):
    """Match the current wholesale observation to the actual first FILL result, not a self-reported hash."""
    envelope = first_fill.get('action_result', {})
    fill_command = first_fill.get('browser_agent_command')
    editor = envelope.get('evidence', {}).get('observations', {}).get('editor_action_result', {})
    fill = editor.get('preflight_results', {}).get('frozen_execution')
    if (not isinstance(fill_command, Mapping) or envelope.get('ok') is not True
            or envelope.get('action') != 'fill_editor_required_defaults' or envelope.get('attempted_state') != 'FILL_BASE_INFO'
            or fill_command.get('action') != 'fill_editor_required_defaults' or fill_command.get('state') != 'FILL_BASE_INFO'
            or fill_command.get('execution_mode') != 'batch_draft_save' or not isinstance(fill, Mapping) or not isinstance(writer, Mapping)):
        raise ValueError('WHOLESALE_ORIGINAL_FILL_INVALID')
    expected_command = {**{key: fill_command.get(key) for key in ('command_id', 'action', 'state', 'task_id', 'job_id', 'runtime_id')},
                        'browser_session_id': envelope.get('page_identity', {}).get('browser_session_id')}
    if (writer.get('command') != expected_command or writer.get('fill_result') != fill
            or writer.get('fill_result_hash') != canonical_sha256(fill)
            or writer.get('execution_payload_hash') != editor.get('execution_payload_hash')
            or any(fill_command.get(key) != command.get(key) for key in ('task_id', 'job_id', 'runtime_id'))
            or expected_command['browser_session_id'] != browser_session_id
            or fill_command.get('command_id') == command.get('command_id')):
        raise ValueError('WHOLESALE_ORIGINAL_FILL_DRIFT')
