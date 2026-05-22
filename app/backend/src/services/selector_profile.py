from __future__ import annotations

from copy import deepcopy
from typing import Any


class SelectorProfileService:
    _DEFAULT_PROFILES: tuple[dict[str, Any], ...] = (
        {
            "page_key": "smt_draft_list",
            "url_contains": ["draft"],
            "required_texts": ["草稿", "编辑"],
            "forbidden_buttons": ["发布", "立即发布", "继续发布", "保存并发布", "确认发布", "提交发布"],
        },
        {
            "page_key": "smt_edit",
            "url_contains": ["edit"],
            "required_texts": ["商品信息", "半托管服务"],
            "forbidden_buttons": ["发布", "立即发布", "继续发布", "保存并发布", "确认发布", "提交发布"],
            "semi_managed_button_text": "编辑半托管信息",
        },
        {
            "page_key": "smt_semi_edit",
            "url_contains": ["editFromSmt"],
            "required_texts": ["半托管信息"],
            "forbidden_buttons": ["发布", "立即发布", "继续发布", "保存并发布", "确认发布", "提交发布"],
            "save_button_text": "保存",
        },
    )

    def __init__(self, profiles: list[dict[str, Any]] | None = None) -> None:
        source_profiles = profiles if profiles is not None else self._DEFAULT_PROFILES
        self._profiles = {
            str(profile["page_key"]): deepcopy(dict(profile))
            for profile in source_profiles
        }

    def get_profile(self, page_key: str) -> dict[str, Any]:
        try:
            return deepcopy(self._profiles[page_key])
        except KeyError as exc:
            raise KeyError(f"unknown selector profile: {page_key}") from exc

    def list_profiles(self) -> list[dict[str, Any]]:
        return [deepcopy(profile) for profile in self._profiles.values()]

    def validate_page(
        self,
        page_key: str,
        url: str,
        body_text: str,
        visible_buttons: list[str] | tuple[str, ...],
    ) -> dict:
        profile = self.get_profile(page_key)
        missing: list[str] = []

        normalized_url = self._normalize(url)
        for term in profile["url_contains"]:
            if self._normalize(term) not in normalized_url:
                missing.append(f"url_contains:{term}")

        normalized_body = self._normalize(body_text)
        for text in profile["required_texts"]:
            if self._normalize(text) not in normalized_body:
                missing.append(f"required_text:{text}")

        forbidden_hits = self._forbidden_button_hits(
            visible_buttons,
            profile["forbidden_buttons"],
        )

        return {
            "ok": not missing and not forbidden_hits,
            "missing": missing,
            "forbidden_hits": forbidden_hits,
            "page_key": page_key,
        }

    def _forbidden_button_hits(
        self,
        visible_buttons: list[str] | tuple[str, ...],
        forbidden_buttons: list[str],
    ) -> list[str]:
        forbidden = {self._normalize(button) for button in forbidden_buttons}
        hits: list[str] = []
        for button in visible_buttons:
            normalized_button = self._normalize(button)
            if normalized_button in forbidden and button not in hits:
                hits.append(button)
        return hits

    def _normalize(self, value: Any) -> str:
        return "".join(str(value or "").lower().split())
