from importlib import import_module
from typing import Any


_EXPORTS = {
    "BatchEditContractError": ("src.batch_edit.coordinator", "BatchEditContractError"),
    "BatchEditCoordinator": ("src.batch_edit.coordinator", "BatchEditCoordinator"),
    "BundleComposerError": ("src.batch_edit.bundle_composer", "BundleComposerError"),
    "EditBatchBundleComposer": ("src.batch_edit.bundle_composer", "EditBatchBundleComposer"),
    "BatchExecutionRuntime": ("src.batch_edit.runtime_coordinator", "BatchExecutionRuntime"),
    "BatchRuntimeError": ("src.batch_edit.runtime_coordinator", "BatchRuntimeError"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
