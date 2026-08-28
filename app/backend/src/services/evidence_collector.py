"""
.. deprecated::
    EvidenceCollector is a shallow in-memory collector.
    Use CanonicalReceipt from src.execution.canonical_receipt instead
    for the unified, durable evidence contract covering two-stage SAVE,
    three-proof chain, and persistent storage via Repository.add_receipt().
"""

from __future__ import annotations
from enum import StrEnum
import warnings as _warnings


class EvidenceType(StrEnum):
    """铁证类型枚举"""

    # 基础铁证类型
    SCREENSHOT = "screenshot"
    DOM_SNAPSHOT = "dom_snapshot"
    NETWORK_REQUEST = "network_request"
    NETWORK_RESPONSE = "network_response"
    URL_SNAPSHOT = "url_snapshot"
    TITLE_SNAPSHOT = "title_snapshot"

    # 执行过程铁证
    LOGIN_STATE = "login_state"
    DRAFT_BOX_ROW = "draft_box_row"
    EDIT_PAGE_LOADED = "edit_page_loaded"
    SAVE_SUCCESS_MODAL = "save_success_modal"
    SAVE_API_RESPONSE = "save_api_response"

    # 批量保存专属铁证
    BATCH_VIDEO_GENERATION_REQUEST = "batch_video_generation_request"
    BATCH_VIDEO_GENERATION_POLL = "batch_video_generation_poll"
    BATCH_VIDEO_PLACE = "batch_video_place"
    BATCH_TRANSLATE_REQUEST = "batch_translate_request"
    BATCH_TRANSLATE_RESULT = "batch_translate_result"
    BATCH_WHOLESALE_CONFIG = "batch_wholesale_config"
    BATCH_SEMI_MANAGED_DETECT = "batch_semi_managed_detect"
    BATCH_SEMI_MANAGED_MODAL = "batch_semi_managed_modal"
    BATCH_SEMI_MANAGED_BATCH_FILL = "batch_semi_managed_batch_fill"
    BATCH_SEMI_MANAGED_SAVE = "batch_semi_managed_save"
    BATCH_ROLLBACK = "batch_rollback"


class EvidenceCollector:
    """
    .. deprecated::
        Use CanonicalReceipt from src.execution.canonical_receipt instead.

    This shallow in-memory collector does not persist evidence.
    """

    def __init__(self):
        _warnings.warn(
            "EvidenceCollector is deprecated. Use CanonicalReceipt from "
            "src.execution.canonical_receipt instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._evidences: list[dict] = []

    def add_evidence(
        self,
        evidence_type: EvidenceType,
        data: dict,
        metadata: dict | None = None,
    ) -> None:
        """添加铁证"""
        self._evidences.append({
            "type": evidence_type.value,
            "data": data,
            "metadata": metadata or {},
        })

    def get_evidence(self) -> list[dict]:
        """获取所有铁证"""
        return list(self._evidences)

    def clear(self) -> None:
        """清除铁证"""
        self._evidences.clear()
