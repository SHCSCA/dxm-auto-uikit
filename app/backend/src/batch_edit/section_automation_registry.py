"""
SectionAutomationRegistry — the single registry for section module → adapter mapping.

Each of the 11 product-edit sections registers its module path and adapter class here.
The registry does NOT own independent task state / process / browser session.
"""

from __future__ import annotations

from typing import Any, TypeVar

T = TypeVar("T")


class SectionNotFoundError(Exception):
    """Raised when a section is not registered."""

    def __init__(self, section_id: str) -> None:
        self.section_id = section_id
        super().__init__(f"Section '{section_id}' is not registered in SectionAutomationRegistry")


class SectionAlreadyRegisteredError(Exception):
    """Raised when trying to register a section that already exists."""

    def __init__(self, section_id: str) -> None:
        self.section_id = section_id
        super().__init__(f"Section '{section_id}' is already registered")


class SectionAutomationRegistry:
    """Central registry mapping section IDs to module paths and adapter classes.

    Lifecycle:
      - register(section_id, module_path, adapter_class) → register mapping
      - get_adapter(section_id) → adapter instance (cached per section)
      - list_sections() → list of registered section IDs

    Each section adapter must not own independent task state / process / browser session.
    """

    SECTION_IDS = frozenset(
        {
            "product_info",
            "basic_info",
            "sale_info",
            "media_assets",
            "additional_info",
            "compliance",
            "logistics",
            "video",
            "wholesale",
            "semi_countries",
            "semi_goods",
            "semi_variants",
        }
    )

    def __init__(self) -> None:
        self._registry: dict[str, tuple[str, type]] = {}
        self._adapters: dict[str, object] = {}

    def register(
        self,
        section_id: str,
        module_path: str,
        adapter_class: type,
    ) -> None:
        """Register a section module path and its adapter class.

        Args:
            section_id: unique section identifier (e.g. "video", "wholesale")
            module_path: dotted Python module path (e.g. "src.batch_edit.video_generator")
            adapter_class: adapter class for this section

        Raises:
            SectionAlreadyRegisteredError: if section_id already registered
            ValueError: if section_id not in SECTION_IDS
        """
        if section_id not in self.SECTION_IDS:
            raise ValueError(
                f"Unknown section_id '{section_id}'. "
                f"Valid section IDs: {sorted(self.SECTION_IDS)}"
            )
        if section_id in self._registry:
            raise SectionAlreadyRegisteredError(section_id)
        self._registry[section_id] = (module_path, adapter_class)

    def get_adapter(
        self,
        section_id: str,
        **init_kwargs: Any,
    ) -> Any:
        """Get (or create) an adapter instance for the given section.

        Adapters are cached per section_id after first instantiation.

        Raises:
            SectionNotFoundError: if section_id not registered
        """
        if section_id not in self._registry:
            raise SectionNotFoundError(section_id)
        if section_id not in self._adapters:
            module_path, adapter_class = self._registry[section_id]
            self._adapters[section_id] = self._instantiate_adapter(
                module_path, adapter_class, **init_kwargs
            )
        return self._adapters[section_id]

    def list_sections(self) -> list[str]:
        """List all registered section IDs in registration order."""
        return list(self._registry.keys())

    def is_registered(self, section_id: str) -> bool:
        """Check if a section is registered."""
        return section_id in self._registry

    def unregister(self, section_id: str) -> None:
        """Unregister a section (for testing)."""
        if section_id in self._registry:
            del self._registry[section_id]
        if section_id in self._adapters:
            del self._adapters[section_id]

    def clear(self) -> None:
        """Clear all registrations and cached adapters (for testing)."""
        self._registry.clear()
        self._adapters.clear()

    def _instantiate_adapter(
        self,
        module_path: str,
        adapter_class: type[T],
        **init_kwargs: Any,
    ) -> T:
        """Dynamically import module and instantiate the adapter class."""
        import importlib
        import sys

        if module_path in sys.modules:
            module = sys.modules[module_path]
        else:
            module = importlib.import_module(module_path)

        if not hasattr(module, adapter_class.__name__):
            raise ImportError(
                f"Module '{module_path}' does not contain class '{adapter_class.__name__}'"
            )

        cls = getattr(module, adapter_class.__name__)
        return cls(**init_kwargs)


_global_registry: SectionAutomationRegistry | None = None


def get_section_registry() -> SectionAutomationRegistry:
    """Get the global SectionAutomationRegistry singleton."""
    global _global_registry
    if _global_registry is None:
        _global_registry = SectionAutomationRegistry()
    return _global_registry


def register_standard_sections() -> SectionAutomationRegistry:
    """Register all 11 standard product-edit sections."""
    registry = get_section_registry()
    if registry.list_sections():
        return registry

    registry.register(
        "product_info",
        "src.batch_edit.section_adapters.product_info_adapter",
        type("ProductInfoAdapter", (), {}),
    )
    registry.register(
        "basic_info",
        "src.batch_edit.section_adapters.basic_info_adapter",
        type("BasicInfoAdapter", (), {}),
    )
    registry.register(
        "sale_info",
        "src.batch_edit.section_adapters.sale_info_adapter",
        type("SaleInfoAdapter", (), {}),
    )
    registry.register(
        "media_assets",
        "src.batch_edit.section_adapters.media_assets_adapter",
        type("MediaAssetsAdapter", (), {}),
    )
    registry.register(
        "additional_info",
        "src.batch_edit.section_adapters.additional_info_adapter",
        type("AdditionalInfoAdapter", (), {}),
    )
    registry.register(
        "compliance",
        "src.batch_edit.section_adapters.compliance_adapter",
        type("ComplianceAdapter", (), {}),
    )
    registry.register(
        "logistics",
        "src.batch_edit.section_adapters.logistics_adapter",
        type("LogisticsAdapter", (), {}),
    )
    registry.register(
        "video",
        "src.batch_edit.video_generator",
        type("BatchVideoGenerator", (), {}),
    )
    registry.register(
        "wholesale",
        "src.batch_edit.wholesale_filler",
        type("WholesaleFiller", (), {}),
    )
    registry.register(
        "semi_countries",
        "src.batch_edit.section_adapters.semi_countries_adapter",
        type("SemiCountriesAdapter", (), {}),
    )
    registry.register(
        "semi_goods",
        "src.batch_edit.section_adapters.semi_goods_adapter",
        type("SemiGoodsAdapter", (), {}),
    )
    registry.register(
        "semi_variants",
        "src.batch_edit.section_adapters.semi_variants_adapter",
        type("SemiVariantsAdapter", (), {}),
    )
    return registry
