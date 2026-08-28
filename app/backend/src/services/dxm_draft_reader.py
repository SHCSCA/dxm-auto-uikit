from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

from src.state_machine.two_stage import (
    TwoStageContractError,
    canonical_source_identity,
    is_supported_product_detail_url,
)


class DxmDraftReaderError(RuntimeError):
    """A read-only DXM response could not be proven safe to expose."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


class DxmDraftReader:
    """Normalize two explicitly allowlisted DXM read APIs.

    The source owns the visible authenticated browser boundary.  This service
    owns response validation, session binding, store/product identity, and
    pagination closure.  It never falls back to local or mock data.
    """

    def __init__(self, source: Any) -> None:
        self._source = source

    def list_shops(self) -> dict[str, Any]:
        envelope = self._read_shop_envelope()
        shops = self._normalize_shops(envelope["payload"])
        return {
            "source": "api",
            "session_bound": True,
            "session_ref": self._session_ref(
                envelope["browser_session_id"],
                envelope["account_ref"],
            ),
            "shops": shops,
        }

    def list_products(
        self,
        *,
        shop_id: str,
        page_no: int,
        page_size: int,
    ) -> dict[str, Any]:
        normalized_shop_id = self._normalize_shop_filter(shop_id)
        self._require_positive_int(page_no, "page_no", maximum=100_000)
        # The console exposes 20/50/100/200 rows per page.  Keep the backend
        # ceiling exactly aligned so an operator selecting 200 does not get a
        # misleading generic reader failure.
        self._require_positive_int(page_size, "page_size", maximum=200)

        shop_envelope = self._read_shop_envelope()
        shops = self._normalize_shops(shop_envelope["payload"])
        known_shop_ids = {shop["id"] for shop in shops}
        if normalized_shop_id != "-1" and normalized_shop_id not in known_shop_ids:
            raise DxmDraftReaderError(
                "SHOP_FILTER_UNKNOWN",
                "所选店铺不在当前真实会话的店铺列表中，已停止读取。",
            )

        page_envelope = self._read_page_envelope(
            shop_id=normalized_shop_id,
            page_no=page_no,
            page_size=page_size,
        )
        if page_envelope["browser_session_id"] != shop_envelope["browser_session_id"]:
            raise DxmDraftReaderError(
                "BROWSER_SESSION_MISMATCH",
                "店铺与商品列表来自不同的真实浏览器会话，已停止读取。",
            )
        if page_envelope["account_ref"] != shop_envelope["account_ref"]:
            raise DxmDraftReaderError(
                "AUTH_ACCOUNT_MISMATCH",
                "店铺与商品列表来自不同的登录账号，已停止读取。",
            )
        result = self._normalize_page(
            page_envelope["payload"],
            shop_id=normalized_shop_id,
            page_no=page_no,
            page_size=page_size,
            known_shop_ids=known_shop_ids,
        )
        result["session_ref"] = self._session_ref(
            page_envelope["browser_session_id"],
            page_envelope["account_ref"],
        )
        return result

    def _read_shop_envelope(self) -> dict[str, Any]:
        try:
            envelope = self._source.read_draft_shops()
        except DxmDraftReaderError:
            raise
        except Exception as exc:
            raise DxmDraftReaderError(
                "DXM_SHOP_READ_FAILED",
                "当前真实店小秘会话的店铺列表读取失败。",
            ) from exc
        return self._normalize_envelope(envelope)

    def _read_page_envelope(
        self,
        *,
        shop_id: str,
        page_no: int,
        page_size: int,
    ) -> dict[str, Any]:
        try:
            envelope = self._source.read_draft_page(
                shop_id=shop_id,
                page_no=page_no,
                page_size=page_size,
            )
        except DxmDraftReaderError:
            raise
        except Exception as exc:
            raise DxmDraftReaderError(
                "DXM_PAGE_READ_FAILED",
                "当前真实店小秘会话的草稿列表读取失败。",
            ) from exc
        return self._normalize_envelope(envelope)

    @staticmethod
    def _normalize_envelope(value: Any) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise DxmDraftReaderError(
                "READ_ENVELOPE_INVALID",
                "真实店小秘只读响应缺少会话绑定，已停止读取。",
            )
        browser_session_id = str(value.get("browser_session_id") or "").strip()
        account_ref = str(value.get("account_ref") or "").strip()
        payload = value.get("payload")
        if not browser_session_id or not account_ref or not isinstance(payload, Mapping):
            raise DxmDraftReaderError(
                "READ_ENVELOPE_INVALID",
                "真实店小秘只读响应缺少浏览器或账号绑定，已停止读取。",
            )
        return {
            "browser_session_id": browser_session_id,
            "account_ref": account_ref,
            "payload": dict(payload),
        }

    @classmethod
    def _normalize_shops(cls, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        data = cls._success_data(payload, label="店铺")
        shop_map = data.get("shopMap")
        if not isinstance(shop_map, Mapping):
            raise DxmDraftReaderError(
                "SHOP_MAP_MISSING",
                "店铺响应缺少 shopMap，已按 Schema 漂移停止读取。",
            )
        raw_type_map = data.get("shopSmtTypeMap")
        type_map = raw_type_map if isinstance(raw_type_map, Mapping) else {}
        shops: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for raw_key, raw_shop in shop_map.items():
            if not isinstance(raw_shop, Mapping):
                raise DxmDraftReaderError(
                    "SHOP_SCHEMA_INVALID",
                    "shopMap 中存在无效店铺对象，已停止读取。",
                )
            platform = str(raw_shop.get("platform") or "").strip().casefold()
            if platform and platform != "smt":
                continue
            if platform != "smt":
                raise DxmDraftReaderError(
                    "SHOP_SCHEMA_INVALID",
                    "店铺响应缺少可验证的平台字段，已停止读取。",
                )
            key = cls._canonical_positive_id(raw_key, label="店铺")
            declared_values = [
                value
                for value in (raw_shop.get("idStr"), raw_shop.get("id"))
                if value not in (None, "")
            ]
            declared_ids = {
                cls._canonical_positive_id(value, label="店铺")
                for value in declared_values
            }
            if declared_ids and declared_ids != {key}:
                raise DxmDraftReaderError(
                    "SHOP_IDENTITY_MISMATCH",
                    "shopMap 键与店铺身份字段不一致，已停止读取。",
                )
            name = str(raw_shop.get("name") or "").strip()
            if not name:
                raise DxmDraftReaderError(
                    "SHOP_NAME_MISSING",
                    "店铺身份缺少展示名称，已停止读取。",
                )
            if key in seen_ids:
                raise DxmDraftReaderError(
                    "SHOP_IDENTITY_DUPLICATE",
                    "店铺身份重复，已停止读取。",
                )
            seen_ids.add(key)
            raw_shop_type = type_map.get(str(raw_key))
            shop_type = str(raw_shop_type).strip() if raw_shop_type not in (None, "") else None
            shops.append(
                {
                    "id": key,
                    "name": name,
                    "platform": "smt",
                    "shop_type": shop_type,
                }
            )
        return shops

    @classmethod
    def _normalize_page(
        cls,
        payload: Mapping[str, Any],
        *,
        shop_id: str,
        page_no: int,
        page_size: int,
        known_shop_ids: set[str],
    ) -> dict[str, Any]:
        data = cls._success_data(payload, label="草稿列表")
        page = data.get("page")
        if not isinstance(page, Mapping):
            raise DxmDraftReaderError(
                "PAGE_SCHEMA_INVALID",
                "草稿列表响应缺少 page，已按 Schema 漂移停止读取。",
            )
        observed_page_no = cls._strict_nonnegative_int(page.get("pageNo"), "pageNo")
        observed_page_size = cls._strict_nonnegative_int(page.get("pageSize"), "pageSize")
        total_pages = cls._strict_nonnegative_int(page.get("totalPage"), "totalPage")
        total_items = cls._strict_nonnegative_int(page.get("totalSize"), "totalSize")
        raw_items = page.get("list")
        if (
            observed_page_no != page_no
            or observed_page_size != page_size
            or not isinstance(raw_items, list)
        ):
            raise DxmDraftReaderError(
                "PAGINATION_INCONSISTENT",
                "草稿列表分页回包与请求不一致，已停止读取。",
            )

        cls._validate_pagination(
            page_no=page_no,
            page_size=page_size,
            total_pages=total_pages,
            total_items=total_items,
            raw_item_count=len(raw_items),
        )

        normalized_items: list[dict[str, Any]] = []
        items_by_id: dict[str, dict[str, Any]] = {}
        duplicate_count = 0
        for raw_item in raw_items:
            item = cls._normalize_product(
                raw_item,
                shop_id=shop_id,
                known_shop_ids=known_shop_ids,
            )
            existing = items_by_id.get(item["id"])
            if existing is None:
                items_by_id[item["id"]] = item
                normalized_items.append(item)
                continue
            if existing != item:
                raise DxmDraftReaderError(
                    "PRODUCT_IDENTITY_CONFLICT",
                    "同页重复商品身份携带了冲突字段，已停止读取。",
                )
            duplicate_count += 1

        return {
            "source": "api",
            "session_bound": True,
            "filter": {
                "shop_id": shop_id,
                "dxm_state": "draft",
            },
            "pagination": {
                "page_no": page_no,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_items": total_items,
                "has_previous": page_no > 1,
                "has_next": total_pages > 0 and page_no < total_pages,
            },
            "items": normalized_items,
            "deduplicated_count": duplicate_count,
        }

    @classmethod
    def _normalize_product(
        cls,
        value: Any,
        *,
        shop_id: str,
        known_shop_ids: set[str],
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise DxmDraftReaderError(
                "PRODUCT_SCHEMA_INVALID",
                "草稿列表中存在无效商品对象，已停止读取。",
            )
        declared_product_ids = [
            item
            for item in (value.get("idStr"), value.get("id"))
            if item not in (None, "")
        ]
        if not declared_product_ids:
            raise DxmDraftReaderError(
                "PRODUCT_ID_MISSING",
                "草稿商品缺少稳定商品 ID，已停止读取。",
            )
        product_ids = {
            cls._canonical_positive_id(item, label="商品")
            for item in declared_product_ids
        }
        if len(product_ids) != 1:
            raise DxmDraftReaderError(
                "PRODUCT_IDENTITY_MISMATCH",
                "草稿商品的 id 与 idStr 不一致，已停止读取。",
            )
        product_id = next(iter(product_ids))
        product_shop_id = cls._canonical_positive_id(value.get("shopId"), label="商品店铺")
        if product_shop_id not in known_shop_ids:
            raise DxmDraftReaderError(
                "PRODUCT_SHOP_UNKNOWN",
                "草稿商品绑定了当前真实会话以外的店铺，已停止读取。",
            )
        if shop_id != "-1" and product_shop_id != shop_id:
            raise DxmDraftReaderError(
                "PRODUCT_SHOP_MISMATCH",
                "草稿商品与所选店铺绑定不一致，已停止读取。",
            )
        if value.get("dxmState") != "draft":
            raise DxmDraftReaderError(
                "PRODUCT_STATE_MISMATCH",
                "草稿列表回包含非草稿状态商品，已停止读取。",
            )
        subject = value.get("subject")
        if not isinstance(subject, str):
            raise DxmDraftReaderError(
                "PRODUCT_SUBJECT_INVALID",
                "草稿商品标题字段结构无效，已停止读取。",
            )
        raw_category_id = value.get("categoryId")
        category_id = (
            None
            if raw_category_id in (None, "")
            else cls._canonical_positive_id(raw_category_id, label="商品类目")
        )
        normalized = {
            "id": product_id,
            "shop_id": product_shop_id,
            "subject": subject.strip(),
            "category_id": category_id,
            "dxm_state": "draft",
        }
        category_name = cls._optional_text(value.get("categoryNameZh"))
        if category_name:
            normalized["category_name"] = category_name
        thumbnail_url = cls._optional_thumbnail_url(value.get("imageURLs"))
        if thumbnail_url:
            normalized["thumbnail_url"] = thumbnail_url
        remark = cls._optional_text(value.get("comment"))
        if remark:
            normalized["remark"] = remark
        source_platform = cls._optional_text(value.get("sourceName"))
        if source_platform:
            normalized["source_platform"] = source_platform
        source_urls = cls._normalize_product_source_urls(value)
        if source_urls:
            normalized["source_urls"] = source_urls
        return normalized

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        text = " ".join(value.split())
        return text or None

    @staticmethod
    def _optional_thumbnail_url(value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        for candidate in value.split(";"):
            url = candidate.strip()
            if url.startswith("https://") or url.startswith("http://"):
                return url
        return None

    @staticmethod
    def _normalize_product_source_urls(value: Mapping[str, Any]) -> list[str]:
        """Preserve only explicit, canonical product-detail URLs from pageList."""

        raw_primary = value.get("sourceUrl")
        raw_many = value.get("sourceUrls")
        if raw_primary in (None, "") and raw_many in (None, [], ()):
            return []
        candidates: list[str] = []
        if raw_primary not in (None, ""):
            if not isinstance(raw_primary, str) or raw_primary != raw_primary.strip():
                raise DxmDraftReaderError(
                    "PRODUCT_SOURCE_URL_INVALID",
                    "草稿商品来源链接字段结构无效，已停止读取。",
                )
            candidates.append(raw_primary)
        if raw_many not in (None, [], ()):
            if not isinstance(raw_many, (list, tuple)) or any(
                not isinstance(item, str) or not item.strip() or item != item.strip()
                for item in raw_many
            ):
                raise DxmDraftReaderError(
                    "PRODUCT_SOURCE_URL_INVALID",
                    "草稿商品来源链接列表结构无效，已停止读取。",
                )
            candidates.extend(raw_many)
        if not candidates:
            return []
        try:
            identity = canonical_source_identity(candidates[0], candidates)
        except TwoStageContractError:
            return []
        source_urls = list(identity["urls"])
        if any(
            not is_supported_product_detail_url(candidate)
            for candidate in source_urls
        ):
            return []
        return source_urls

    @staticmethod
    def _success_data(payload: Mapping[str, Any], *, label: str) -> Mapping[str, Any]:
        code = payload.get("code")
        is_success = (
            (type(code) is int and code == 0)
            or (type(code) is str and code == "0")
        )
        if not is_success:
            raise DxmDraftReaderError(
                "DXM_READ_REJECTED",
                f"店小秘{label}只读接口未返回成功状态，已停止读取。",
            )
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise DxmDraftReaderError(
                "DXM_RESPONSE_SCHEMA_INVALID",
                f"店小秘{label}响应缺少 data，已停止读取。",
            )
        return data

    @staticmethod
    def _validate_pagination(
        *,
        page_no: int,
        page_size: int,
        total_pages: int,
        total_items: int,
        raw_item_count: int,
    ) -> None:
        if total_items == 0:
            if page_no != 1 or total_pages not in (0, 1) or raw_item_count != 0:
                raise DxmDraftReaderError(
                    "PAGINATION_INCONSISTENT",
                    "空草稿列表的分页信息不闭合，已停止读取。",
                )
            return
        expected_total_pages = (total_items + page_size - 1) // page_size
        if total_pages != expected_total_pages or not 1 <= page_no <= total_pages:
            raise DxmDraftReaderError(
                "PAGINATION_INCONSISTENT",
                "草稿列表总页数与总条数不闭合，已停止读取。",
            )
        expected_page_items = (
            page_size
            if page_no < total_pages
            else total_items - (total_pages - 1) * page_size
        )
        if raw_item_count != expected_page_items:
            raise DxmDraftReaderError(
                "PAGINATION_INCONSISTENT",
                "草稿列表当前页条数与分页信息不闭合，已停止读取。",
            )

    @classmethod
    def _normalize_shop_filter(cls, value: Any) -> str:
        if value == "-1":
            return "-1"
        return cls._canonical_positive_id(value, label="店铺筛选")

    @staticmethod
    def _canonical_positive_id(value: Any, *, label: str) -> str:
        if isinstance(value, bool):
            raise DxmDraftReaderError(
                "IDENTITY_INVALID",
                f"{label}身份不是稳定正整数，已停止读取。",
            )
        if isinstance(value, int):
            number = value
        elif isinstance(value, str) and value == value.strip() and value.isdecimal():
            number = int(value)
        else:
            raise DxmDraftReaderError(
                "IDENTITY_INVALID",
                f"{label}身份不是稳定正整数，已停止读取。",
            )
        if number <= 0:
            raise DxmDraftReaderError(
                "IDENTITY_INVALID",
                f"{label}身份不是稳定正整数，已停止读取。",
            )
        return str(number)

    @staticmethod
    def _strict_nonnegative_int(value: Any, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DxmDraftReaderError(
                "PAGINATION_INCONSISTENT",
                f"草稿列表分页字段 {field} 无效，已停止读取。",
            )
        return value

    @staticmethod
    def _require_positive_int(value: Any, field: str, *, maximum: int) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > maximum
        ):
            raise DxmDraftReaderError(
                "PAGINATION_REQUEST_INVALID",
                f"{field} 超出允许范围。",
            )

    @staticmethod
    def _session_ref(browser_session_id: str, account_ref: str) -> str:
        return hashlib.sha256(
            f"dxm-draft-reader:{browser_session_id}:{account_ref}".encode("utf-8")
        ).hexdigest()[:16]
