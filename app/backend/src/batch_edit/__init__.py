"""
DXM Batch Edit Module

.. deprecated::
    BatchExecutionRuntime is deprecated. Use V1TaskRunner in execution/v1_runner.py instead.
    All batch execution assembly (scheduling, approval, task advancement, write-dispatch)
    has been removed from this module.
"""

from importlib import import_module
from typing import Any
import warnings as _warnings


_EXPORTS = {
    "BatchEditContractError": ("src.batch_edit.coordinator", "BatchEditContractError"),
    "BatchEditCoordinator": ("src.batch_edit.coordinator", "BatchEditCoordinator"),
    "BundleComposerError": ("src.batch_edit.bundle_composer", "BundleComposerError"),
    "EditBatchBundleComposer": ("src.batch_edit.bundle_composer", "EditBatchBundleComposer"),
}

__all__ = list(_EXPORTS)


class _DeprecatedBatchExecutionRuntime:
    """Deprecated: BatchExecutionRuntime has been removed."""

    def __init__(self, *args, **kwargs):
        _warnings.warn(
            "BatchExecutionRuntime is deprecated and has been removed. "
            "Use V1TaskRunner from execution/v1_runner instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise RuntimeError(
            "BatchExecutionRuntime has been removed. "
            "Use V1TaskRunner from execution/v1_runner instead."
        )


class _DeprecatedBatchRuntimeError(RuntimeError):
    """Deprecated: BatchRuntimeError has been removed."""

    def __init__(self, *args, **kwargs):
        _warnings.warn(
            "BatchRuntimeError is deprecated.", DeprecationWarning, stacklevel=2
        )
        super().__init__(*args, **kwargs)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is not None:
        module_name, attribute_name = target
        value = getattr(import_module(module_name), attribute_name)
        globals()[name] = value
        return value
    if name == "BatchExecutionRuntime":
        _warnings.warn(
            "BatchExecutionRuntime is deprecated and has been removed. "
            "Use V1TaskRunner from execution/v1_runner instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return _DeprecatedBatchExecutionRuntime
    if name == "BatchRuntimeError":
        _warnings.warn(
            "BatchRuntimeError is deprecated.", DeprecationWarning, stacklevel=2
        )
        return _DeprecatedBatchRuntimeError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
