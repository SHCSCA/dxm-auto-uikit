"""
DXM Batch Edit Module

.. deprecated::
    BatchExecutionRuntime is deprecated. Use V1TaskRunner in execution/v1_runner.py instead.
    All batch execution assembly (scheduling, approval, task advancement, write-dispatch)
    has been removed from this module.
"""

import warnings as _warnings

from src.batch_edit.coordinator import BatchEditContractError, BatchEditCoordinator
from src.batch_edit.bundle_composer import BundleComposerError, EditBatchBundleComposer

__all__ = [
    "BatchEditContractError",
    "BatchEditCoordinator",
    "BundleComposerError",
    "EditBatchBundleComposer",
]


class _DeprecatedBatchExecutionRuntime:
    """Deprecated: BatchExecutionRuntime has been removed."""

    def __init__(self, *args, **kwargs):
        _warnings.warn(
            "BatchExecutionRuntime is deprecated and has been removed. "
            "Use V1TaskRunner from execution.v1_runner instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        raise RuntimeError(
            "BatchExecutionRuntime has been removed. "
            "Use V1TaskRunner from execution.v1_runner instead."
        )


class _DeprecatedBatchRuntimeError(RuntimeError):
    """Deprecated: BatchRuntimeError has been removed."""

    def __init__(self, *args, **kwargs):
        _warnings.warn(
            "BatchRuntimeError is deprecated.", DeprecationWarning, stacklevel=2
        )
        super().__init__(*args, **kwargs)


def __getattr__(name: str):
    if name == "BatchExecutionRuntime":
        _warnings.warn(
            "BatchExecutionRuntime is deprecated and has been removed. "
            "Use V1TaskRunner from execution.v1_runner instead.",
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
