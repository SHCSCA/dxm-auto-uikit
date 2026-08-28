"""
BindingRegistry — unified binding resolution for DXM product editor fields.

Convergence point for all selector binding logic across the codebase.
Read and write share the same binding — no separate read/write selector sets.

This replaces duplicate binding logic in bundle_composer.py and selector_profile.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SelectorBinding:
    """Immutable binding result for a field key."""

    field_key: str
    read_selector: str | None = None
    write_selector: str | None = None
    read_action: str | None = None
    write_action: str | None = None
    validation_selector: str | None = None
    requires_js: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def selector(self) -> str | None:
        """Unified selector for read/write operations."""
        return self.write_selector or self.read_selector

    @property
    def action(self) -> str | None:
        """Unified action for read/write operations."""
        return self.write_action or self.read_action

    def is_read_only(self) -> bool:
        return self.read_selector is not None and self.write_selector is None

    def is_write_only(self) -> bool:
        return self.read_selector is None and self.write_selector is not None


class BindingRegistry:
    """Unified registry for resolving selector bindings.

    Read and write share the same binding — no separate read/write selector sets.
    """

    SECTION_BINDINGS: dict[str, dict[str, SelectorBinding]] = {
        "product_info": {
            "title": SelectorBinding(field_key="title", read_selector='[data-testid="field-title"]', write_selector='[data-testid="field-title"] input', write_action="fill_text"),
            "description": SelectorBinding(field_key="description", read_selector='[data-testid="field-description"]', write_selector='[data-testid="field-description"] textarea', write_action="fill_text"),
        },
        "basic_info": {
            "categoryId": SelectorBinding(field_key="categoryId", read_selector='[data-testid="category-select"]', write_selector='[data-testid="category-select"] input', write_action="select_option"),
            "category_match": SelectorBinding(field_key="category_match", read_selector='[data-testid="category-match"]', write_selector='[data-testid="category-match"] input', write_action="fill_text"),
        },
        "sale_info": {
            "price": SelectorBinding(field_key="price", read_selector='[data-testid="price-input"]', write_selector='[data-testid="price-input"] input', write_action="fill_text"),
            "stock": SelectorBinding(field_key="stock", read_selector='[data-testid="stock-input"]', write_selector='[data-testid="stock-input"] input', write_action="fill_text"),
            "sku_code": SelectorBinding(field_key="sku_code", read_selector='[data-testid="sku-code-input"]', write_selector='[data-testid="sku-code-input"] input', write_action="fill_text"),
        },
        "media_assets": {
            "main_images": SelectorBinding(field_key="main_images", read_selector='[data-testid="main-images"]', write_selector='[data-testid="main-images"] input[type="file"]', write_action="upload_file"),
            "description_images": SelectorBinding(field_key="description_images", read_selector='[data-testid="desc-images"]', write_selector='[data-testid="desc-images"] input[type="file"]', write_action="upload_file"),
        },
        "additional_info": {
            "package_weight": SelectorBinding(field_key="package_weight", read_selector='[data-testid="weight-input"]', write_selector='[data-testid="weight-input"] input', write_action="fill_text"),
            "package_length": SelectorBinding(field_key="package_length", read_selector='[data-testid="length-input"]', write_selector='[data-testid="length-input"] input', write_action="fill_text"),
            "package_width": SelectorBinding(field_key="package_width", read_selector='[data-testid="width-input"]', write_selector='[data-testid="width-input"] input', write_action="fill_text"),
            "package_height": SelectorBinding(field_key="package_height", read_selector='[data-testid="height-input"]', write_selector='[data-testid="height-input"] input', write_action="fill_text"),
        },
        "compliance": {
            "hs_code": SelectorBinding(field_key="hs_code", read_selector='[data-testid="hs-code-input"]', write_selector='[data-testid="hs-code-input"] input', write_action="fill_text"),
            "material": SelectorBinding(field_key="material", read_selector='[data-testid="material-input"]', write_selector='[data-testid="material-input"] input', write_action="fill_text"),
        },
        "logistics": {
            "shipping_mode": SelectorBinding(field_key="shipping_mode", read_selector='[data-testid="shipping-mode"]', write_selector='[data-testid="shipping-mode"] select', write_action="select_option"),
            "estimated_days": SelectorBinding(field_key="estimated_days", read_selector='[data-testid="estimated-days"]', write_selector='[data-testid="estimated-days"] input', write_action="fill_text"),
        },
        "video": {
            "video_id": SelectorBinding(field_key="video_id", read_selector='[data-testid="video-preview"]', write_selector='[data-testid="generate-video-btn"]', write_action="click"),
            "generate_btn": SelectorBinding(field_key="generate_btn", read_selector='[data-testid="generate-video-btn"]', write_selector='[data-testid="generate-video-btn"]', write_action="click"),
            "place_btn": SelectorBinding(field_key="place_btn", read_selector='[data-testid="place-video-btn"]', write_selector='[data-testid="place-video-btn"]', write_action="click"),
        },
        "wholesale": {
            "wholesale_enabled": SelectorBinding(field_key="wholesale_enabled", read_selector='[data-testid="wholesale-checkbox"]', write_selector='[data-testid="wholesale-checkbox"]', write_action="check"),
            "min_quantity": SelectorBinding(field_key="min_quantity", read_selector='[data-testid="min-quantity-input"]', write_selector='[data-testid="min-quantity-input"] input', write_action="fill_text"),
            "discount_percent": SelectorBinding(field_key="discount_percent", read_selector='[data-testid="discount-input"]', write_selector='[data-testid="discount-input"] input', write_action="fill_text"),
            "deduction_method": SelectorBinding(field_key="deduction_method", read_selector='[data-testid="deduction-method"]', write_selector='[data-testid="deduction-method"] input', write_action="select_option"),
        },
        "semi_countries": {
            "country_group": SelectorBinding(field_key="country_group", read_selector='[data-testid="country-group-select"]', write_selector='[data-testid="country-group-select"] input', write_action="select_option"),
            "country_select": SelectorBinding(field_key="country_select", read_selector='[data-testid="country-select"]', write_selector='[data-testid="country-select"] input[type="checkbox"]', write_action="check"),
        },
        "semi_goods": {
            "is_original_box": SelectorBinding(field_key="is_original_box", read_selector='[data-testid="original-box-select"]', write_selector='[data-testid="original-box-select"] input', write_action="select_option"),
            "logistics_attr": SelectorBinding(field_key="logistics_attr", read_selector='[data-testid="logistics-attr-select"]', write_selector='[data-testid="logistics-attr-select"] select', write_action="select_option"),
            "goods_weight": SelectorBinding(field_key="goods_weight", read_selector='[data-testid="goods-weight-input"]', write_selector='[data-testid="goods-weight-input"] input', write_action="fill_text"),
            "goods_length": SelectorBinding(field_key="goods_length", read_selector='[data-testid="goods-length-input"]', write_selector='[data-testid="goods-length-input"] input', write_action="fill_text"),
            "goods_width": SelectorBinding(field_key="goods_width", read_selector='[data-testid="goods-width-input"]', write_selector='[data-testid="goods-width-input"] input', write_action="fill_text"),
            "goods_height": SelectorBinding(field_key="goods_height", read_selector='[data-testid="goods-height-input"]', write_selector='[data-testid="goods-height-input"] input', write_action="fill_text"),
        },
        "semi_variants": {
            "product_price": SelectorBinding(field_key="product_price", read_selector='[data-testid="product-price-input"]', write_selector='[data-testid="product-price-input"] input', write_action="fill_text"),
            "sku_code": SelectorBinding(field_key="sku_code", read_selector='[data-testid="sku-code-input"]', write_selector='[data-testid="sku-code-input"] input', write_action="fill_text"),
            "goods_code": SelectorBinding(field_key="goods_code", read_selector='[data-testid="goods-code-input"]', write_selector='[data-testid="goods-code-input"] input', write_action="fill_text"),
            "barcode": SelectorBinding(field_key="barcode", read_selector='[data-testid="barcode-input"]', write_selector='[data-testid="barcode-input"] input', write_action="fill_text"),
            "jit_stock": SelectorBinding(field_key="jit_stock", read_selector='[data-testid="jit-stock-input"]', write_selector='[data-testid="jit-stock-input"] input', write_action="fill_text"),
            "generate_sku": SelectorBinding(field_key="generate_sku", read_selector='[data-testid="generate-sku-btn"]', write_selector='[data-testid="generate-sku-btn"]', write_action="click"),
            "generate_goods": SelectorBinding(field_key="generate_goods", read_selector='[data-testid="generate-goods-btn"]', write_selector='[data-testid="generate-goods-btn"]', write_action="click"),
            "generate_barcode": SelectorBinding(field_key="generate_barcode", read_selector='[data-testid="generate-barcode-btn"]', write_selector='[data-testid="generate-barcode-btn"]', write_action="click"),
        },
    }

    def resolve_binding(self, field_key: str, section: str | None = None) -> SelectorBinding:
        """Resolve the canonical binding for a field key.

        Args:
            field_key: the field identifier (e.g. "price", "min_quantity")
            section: optional section context (e.g. "wholesale", "semi_variants")

        Returns:
            SelectorBinding with unified read/write selectors

        Raises:
            KeyError: if field_key not found in any section
        """
        if section is not None and section in self.SECTION_BINDINGS:
            section_bindings = self.SECTION_BINDINGS[section]
            if field_key in section_bindings:
                return section_bindings[field_key]

        for sec_bindings in self.SECTION_BINDINGS.values():
            if field_key in sec_bindings:
                return sec_bindings[field_key]

        raise KeyError(f"Field '{field_key}' is not registered in BindingRegistry")

    def resolve_binding_for_section(
        self,
        field_key: str,
        section: str,
    ) -> SelectorBinding:
        """Resolve binding within a specific section (strict)."""
        if section not in self.SECTION_BINDINGS:
            raise KeyError(f"Section '{section}' is not registered")
        bindings = self.SECTION_BINDINGS[section]
        if field_key not in bindings:
            raise KeyError(f"Field '{field_key}' not found in section '{section}'")
        return bindings[field_key]

    def list_fields_in_section(self, section: str) -> list[str]:
        """List all registered field keys for a section."""
        if section not in self.SECTION_BINDINGS:
            return []
        return list(self.SECTION_BINDINGS[section].keys())

    def list_all_fields(self) -> dict[str, list[str]]:
        """List all sections and their registered field keys."""
        return {
            section: list(bindings.keys())
            for section, bindings in self.SECTION_BINDINGS.items()
        }

    def has_field(self, field_key: str, section: str | None = None) -> bool:
        """Check if a field is registered."""
        if section is not None:
            return section in self.SECTION_BINDINGS and field_key in self.SECTION_BINDINGS[section]
        for bindings in self.SECTION_BINDINGS.values():
            if field_key in bindings:
                return True
        return False


_global_registry: BindingRegistry | None = None


def get_binding_registry() -> BindingRegistry:
    """Get the global BindingRegistry singleton."""
    global _global_registry
    if _global_registry is None:
        _global_registry = BindingRegistry()
    return _global_registry


def resolve_binding(field_key: str, section: str | None = None) -> SelectorBinding:
    """Convenience function for global binding resolution."""
    return get_binding_registry().resolve_binding(field_key, section)
