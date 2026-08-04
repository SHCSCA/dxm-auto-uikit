from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from src.batch_edit.plan_schema_contract import (
    PlanSchemaError,
    normalize_wire_value,
)
from src.batch_edit.scope_contract import canonical_sha256
from src.services.dxm_draft_reader import DxmDraftReader


DXM_E2_TEMPLATE_REF_TYPES = {
    "product",
    "attribute",
    "variation",
    "freight",
    "service",
    "size",
}
DXM_E2_READ_APIS = {
    "/api/userTemplate/pageList.json",
    "/api/smtAttributeTemplate/pageList.json",
    "/api/smtAttributeTemplate/pageList.json",
    "/api/variationTemplate/com/smt/pageList.json",
    "/api/smtShopInfoSync/list.json",
    "/api/smtAttributeTemplate/getTemplateListByCategory.json",
    "/api/variationTemplate/com/smt/getNameListByCategory.json",
    "/api/smtShopInfoSync/sizeChartList.json",
    "/api/smtCategory/attributeList.json",
    "/api/smtCategory/childAttributeList.json",
}


class DxmPlanReaderError(RuntimeError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


class DxmPlanReader:
    """Validate E2 plan inputs read from the current authenticated browser."""

    def __init__(self, source: Any) -> None:
        self._source = source

    def read_scope(self, *, shop_id: str, category_ids: list[str]) -> dict[str, Any]:
        normalized_shop_id = _positive_id_text(shop_id, "shop_id")
        normalized_category_ids = [
            _positive_id_text(value, "category_id")
            for value in category_ids
        ]
        if (
            not normalized_category_ids
            or len(normalized_category_ids) > 50
            or len(set(normalized_category_ids)) != len(normalized_category_ids)
        ):
            raise DxmPlanReaderError(
                "DXM_PLAN_SCOPE_INVALID",
                "类目作用域必须包含 1–50 个不重复的稳定类目 ID。",
            )
        reader = getattr(self._source, "read_e2_plan_scope", None)
        if not callable(reader):
            raise DxmPlanReaderError(
                "DXM_PLAN_READER_UNAVAILABLE",
                "当前真实浏览器没有提供 E2 只读模板与类目读取能力。",
            )
        envelope = reader(
            shop_id=normalized_shop_id,
            category_ids=normalized_category_ids,
        )
        browser_session_id, account_ref, payload = self._validated_envelope(envelope)
        raw_records = payload.get("template_records")
        if not isinstance(raw_records, list):
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_RESPONSE_INVALID",
                "店小秘模板只读回包缺少 template_records。",
            )
        records = [
            self._normalize_template_record(
                raw,
                index=index,
                shop_id=normalized_shop_id,
                category_ids=set(normalized_category_ids),
            )
            for index, raw in enumerate(raw_records)
        ]
        if len({self._record_identity(record) for record in records}) != len(records):
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_IDENTITY_CONFLICT",
                "店小秘模板只读回包含重复身份，已停止同步。",
            )
        return {
            "source": "api",
            "session_bound": True,
            "session_ref": self._session_ref(browser_session_id, account_ref),
            "account_context_hash": self._account_context_hash(account_ref),
            "shop_id": normalized_shop_id,
            "category_ids": normalized_category_ids,
            "template_records": records,
            "category_schemas": payload.get("category_schemas"),
        }

    def build_snapshot_request(
        self,
        *,
        local_plan_template_id: int,
        shop_id: str,
        product_ids: list[str],
        expected_session_ref: str,
    ) -> dict[str, Any]:
        normalized_shop_id = _positive_id_text(shop_id, "shop_id")
        if (
            isinstance(local_plan_template_id, bool)
            or not isinstance(local_plan_template_id, int)
            or local_plan_template_id <= 0
        ):
            raise DxmPlanReaderError(
                "LOCAL_PLAN_NOT_FOUND",
                "local_plan_template_id 必须是正整数。",
            )
        if (
            not isinstance(expected_session_ref, str)
            or re.fullmatch(r"[0-9a-f]{16}", expected_session_ref) is None
        ):
            raise DxmPlanReaderError(
                "DXM_PLAN_SESSION_REF_INVALID",
                "快照请求缺少当次 Reader 的 session_ref。",
            )
        if not isinstance(product_ids, list) or not 3 <= len(product_ids) <= 100:
            raise DxmPlanReaderError(
                "PLAN_ITEM_COUNT_INVALID",
                "plan_snapshot 必须绑定 3–100 件当次草稿。",
            )
        normalized_product_ids = [
            _positive_id_text(value, "product_id")
            for value in product_ids
        ]
        if len(set(normalized_product_ids)) != len(normalized_product_ids):
            raise DxmPlanReaderError(
                "PLAN_PRODUCT_DUPLICATE",
                "product_ids 必须唯一。",
            )

        draft_reader = DxmDraftReader(self._source)
        shops = draft_reader.list_shops()
        if shops["session_ref"] != expected_session_ref:
            raise DxmPlanReaderError(
                "DXM_PLAN_SESSION_MISMATCH",
                "当前真实浏览器会话与选品确认时的 Reader 证明不一致。",
            )
        if normalized_shop_id not in {shop["id"] for shop in shops["shops"]}:
            raise DxmPlanReaderError(
                "PLAN_SCOPE_CONFLICT",
                "快照店铺不在当前登录账号的真实 shopMap 中。",
            )

        requested = set(normalized_product_ids)
        observed: dict[str, dict[str, Any]] = {}
        page_no = 1
        total_pages = 1
        while page_no <= total_pages:
            page = draft_reader.list_products(
                shop_id=normalized_shop_id,
                page_no=page_no,
                page_size=100,
            )
            if page["session_ref"] != expected_session_ref:
                raise DxmPlanReaderError(
                    "DXM_PLAN_SESSION_MISMATCH",
                    "分页重验期间真实浏览器或登录账号已变化。",
                )
            pagination = page["pagination"]
            total_pages = pagination["total_pages"]
            if total_pages > 100_000:
                raise DxmPlanReaderError(
                    "DXM_TEMPLATE_PAGINATION_INVALID",
                    "草稿分页超过安全上限。",
                )
            for item in page["items"]:
                product_id = item["id"]
                if product_id not in requested:
                    continue
                previous = observed.get(product_id)
                if previous is not None and previous != item:
                    raise DxmPlanReaderError(
                        "PRODUCT_IDENTITY_CONFLICT",
                        "跨页读取到冲突的草稿商品身份。",
                    )
                observed[product_id] = item
            page_no += 1
        missing = [
            product_id
            for product_id in normalized_product_ids
            if product_id not in observed
        ]
        if missing:
            raise DxmPlanReaderError(
                "PLAN_PRODUCT_NOT_IN_CURRENT_READER",
                "部分商品已不在当前真实 draft 读回范围中。",
            )
        ordered_products = [observed[product_id] for product_id in normalized_product_ids]
        if any(item["shop_id"] != normalized_shop_id for item in ordered_products):
            raise DxmPlanReaderError(
                "PLAN_SCOPE_CONFLICT",
                "草稿商品与快照店铺不一致。",
            )
        if any(item["category_id"] is None for item in ordered_products):
            raise DxmPlanReaderError(
                "PLAN_CATEGORY_SCOPE_CONFLICT",
                "存在尚未取得稳定 categoryId 的草稿商品。",
            )
        detail_reader = getattr(self._source, "read_e2_product_details", None)
        if not callable(detail_reader):
            raise DxmPlanReaderError(
                "DXM_PRODUCT_DETAIL_READER_UNAVAILABLE",
                "当前真实浏览器没有提供编辑页商品当前值只读能力。",
            )
        detail_envelope = detail_reader(
            shop_id=normalized_shop_id,
            product_ids=normalized_product_ids,
        )
        detail_browser_id, detail_account_ref, detail_payload = (
            self._validated_envelope(detail_envelope)
        )
        if (
            self._session_ref(detail_browser_id, detail_account_ref)
            != expected_session_ref
        ):
            raise DxmPlanReaderError(
                "DXM_PLAN_SESSION_MISMATCH",
                "编辑页当前值与选品范围来自不同的真实浏览器会话或账号。",
            )
        raw_details = detail_payload.get("products")
        if not isinstance(raw_details, list):
            raise DxmPlanReaderError(
                "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                "编辑页商品当前值回包缺少 products。",
            )
        details_by_id: dict[str, Mapping[str, Any]] = {}
        for raw_detail in raw_details:
            detail_id, detail = self._validated_product_detail(
                raw_detail,
                shop_id=normalized_shop_id,
            )
            previous = details_by_id.get(detail_id)
            if previous is not None and previous != detail:
                raise DxmPlanReaderError(
                    "PRODUCT_IDENTITY_CONFLICT",
                    "编辑页重读到冲突的草稿商品身份或当前值。",
                )
            details_by_id[detail_id] = detail
        if set(details_by_id) != requested:
            raise DxmPlanReaderError(
                "DXM_PRODUCT_DETAIL_SCOPE_INVALID",
                "编辑页当前值没有完整覆盖当次确认商品范围。",
            )
        category_ids = list(
            dict.fromkeys(str(item["category_id"]) for item in ordered_products)
        )
        scope = self.read_scope(
            shop_id=normalized_shop_id,
            category_ids=category_ids,
        )
        if scope["session_ref"] != expected_session_ref:
            raise DxmPlanReaderError(
                "DXM_PLAN_SESSION_MISMATCH",
                "模板/Schema 与选品范围来自不同的真实浏览器会话。",
            )
        raw_schemas = scope.get("category_schemas")
        if not isinstance(raw_schemas, Mapping):
            raise DxmPlanReaderError(
                "CATEGORY_SCHEMA_INVALID",
                "E2 Reader 没有返回类目 Schema 映射。",
            )
        if set(raw_schemas) != set(category_ids):
            raise DxmPlanReaderError(
                "CATEGORY_SCHEMA_INVALID",
                "E2 Reader 返回的类目 Schema 作用域不完整或越界。",
            )
        items = []
        for product in ordered_products:
            category_id = str(product["category_id"])
            schema = raw_schemas[category_id]
            if not isinstance(schema, dict):
                raise DxmPlanReaderError(
                    "CATEGORY_SCHEMA_INVALID",
                    f"类目 {category_id} 的 Schema 不是对象。",
                )
            detail = details_by_id[product["id"]]
            if (
                _positive_id_text(detail.get("categoryId"), "detail category_id")
                != category_id
            ):
                raise DxmPlanReaderError(
                    "PLAN_CATEGORY_SCOPE_CONFLICT",
                    "编辑页当前类目与草稿列表已确认类目不一致。",
                )
            current_values = self._current_values_from_detail(
                detail,
                schema=schema,
            )
            items.append(
                {
                    "product_id": product["id"],
                    "shop_id": product["shop_id"],
                    "category_id": category_id,
                    "category_schema": schema,
                    "expected_schema_hash": canonical_sha256(schema),
                    "current_values": current_values,
                }
            )
        return {
            "request": {
                "local_plan_template_id": local_plan_template_id,
                "shop_id": normalized_shop_id,
                "items": items,
                "session_context": {
                    "session_ref": expected_session_ref,
                    "account_ref_hash": scope["account_context_hash"],
                    "shop_id": normalized_shop_id,
                },
            },
            "template_records": scope["template_records"],
            "category_ids": category_ids,
            "session_ref": expected_session_ref,
        }

    @staticmethod
    def _account_context_hash(account_ref: str) -> str:
        return hashlib.sha256(
            f"dxm-e2-account-context:{account_ref}".encode("utf-8")
        ).hexdigest().upper()

    @staticmethod
    def _validated_product_detail(
        value: Any,
        *,
        shop_id: str,
    ) -> tuple[str, Mapping[str, Any]]:
        if not isinstance(value, Mapping):
            raise DxmPlanReaderError(
                "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                "编辑页商品当前值中存在无效对象。",
            )
        declared_ids = [
            item
            for item in (value.get("idStr"), value.get("id"))
            if item not in (None, "")
        ]
        if not declared_ids:
            raise DxmPlanReaderError(
                "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                "编辑页商品当前值缺少稳定商品 ID。",
            )
        product_ids = {
            _positive_id_text(item, "detail product_id")
            for item in declared_ids
        }
        if len(product_ids) != 1:
            raise DxmPlanReaderError(
                "PRODUCT_IDENTITY_CONFLICT",
                "编辑页商品 id 与 idStr 不一致。",
            )
        if _positive_id_text(value.get("shopId"), "detail shop_id") != shop_id:
            raise DxmPlanReaderError(
                "PLAN_SCOPE_CONFLICT",
                "编辑页商品不属于快照店铺。",
            )
        if value.get("dxmState") != "draft":
            raise DxmPlanReaderError(
                "PRODUCT_STATE_MISMATCH",
                "编辑页当前值已不是 draft，已停止冻结。",
            )
        return next(iter(product_ids)), value

    @staticmethod
    def _current_values_from_detail(
        detail: Mapping[str, Any],
        *,
        schema: Mapping[str, Any],
    ) -> dict[str, Any]:
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            raise DxmPlanReaderError(
                "CATEGORY_SCHEMA_INVALID",
                "类目 Schema 缺少 properties。",
            )
        attribute_values: dict[str, Any] = {}
        custom_attributes: list[dict[str, Any]] = []

        def add_attribute_value(field_key: str, raw_value: Any) -> None:
            previous = attribute_values.get(field_key)
            if previous is None:
                attribute_values[field_key] = raw_value
                return
            if previous == raw_value:
                return
            values = list(previous) if isinstance(previous, list) else [previous]
            if raw_value not in values:
                values.append(raw_value)
            attribute_values[field_key] = values

        raw_attributes = detail.get("aeopAeProductPropertys")
        if isinstance(raw_attributes, str):
            try:
                raw_attributes = json.loads(raw_attributes)
            except json.JSONDecodeError as exc:
                raise DxmPlanReaderError(
                    "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                    "编辑页类目属性不是有效 JSON 数组。",
                ) from exc
        if raw_attributes is not None:
            if not isinstance(raw_attributes, list):
                raise DxmPlanReaderError(
                    "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                    "编辑页类目属性不是数组。",
                )
            for raw_attribute in raw_attributes:
                if not isinstance(raw_attribute, Mapping):
                    raise DxmPlanReaderError(
                        "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                        "编辑页类目属性中存在无效对象。",
                    )
                raw_attr_name_id = raw_attribute.get("attrNameId")
                raw_value_id = raw_attribute.get("attrValueId")
                if raw_value_id not in (None, ""):
                    raw_value = _positive_id_text(
                        raw_value_id,
                        "detail attrValueId",
                    )
                else:
                    raw_value = (
                        raw_attribute.get("attrValue")
                        or raw_attribute.get("attrValueName")
                        or raw_attribute.get("customValue")
                    )
                if raw_value in (None, ""):
                    continue
                if raw_attr_name_id not in (None, ""):
                    attr_name_id = _positive_id_text(
                        raw_attr_name_id,
                        "detail attrNameId",
                    )
                    add_attribute_value(f"attr_{attr_name_id}", raw_value)
                    continue
                custom_name = next(
                    (
                        str(raw_attribute.get(key)).strip()
                        for key in (
                            "attrName",
                            "attrNameValue",
                            "customAttrName",
                        )
                        if str(raw_attribute.get(key) or "").strip()
                    ),
                    "",
                )
                if not custom_name:
                    raise DxmPlanReaderError(
                        "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                        "编辑页无 ID 自定义属性缺少稳定显示名。",
                    )
                custom_attributes.append(
                    {
                        "name": custom_name,
                        "value": json.loads(
                            json.dumps(
                                raw_value,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                        ),
                    }
                )

        current_values: dict[str, Any] = {}
        for field_key in properties:
            value = None
            if field_key == "title":
                value = detail.get("subject")
            elif field_key in attribute_values:
                value = attribute_values[field_key]
            elif field_key in detail:
                value = detail[field_key]
            if field_key == "aeopAeProductSKUs" and isinstance(value, str):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as exc:
                    raise DxmPlanReaderError(
                        "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                        "编辑页 SKU 当前值不是有效 JSON 数组。",
                    ) from exc
                if not isinstance(value, list):
                    raise DxmPlanReaderError(
                        "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                        "编辑页 SKU 当前值不是数组。",
                    )
            if value is None or value == "" or value == [] or value == {}:
                continue
            try:
                current_values[field_key] = normalize_wire_value(
                    value,
                    properties[field_key],
                    field_key=field_key,
                )
            except PlanSchemaError as exc:
                raise DxmPlanReaderError(
                    "DXM_PRODUCT_DETAIL_RESPONSE_INVALID",
                    f"编辑页字段 {field_key} 无法按类目 Schema 归一化。",
                ) from exc
        if custom_attributes:
            current_values["__unmapped_custom_attributes__"] = custom_attributes
        return current_values

    @staticmethod
    def _validated_envelope(value: Any) -> tuple[str, str, Mapping[str, Any]]:
        if not isinstance(value, Mapping):
            raise DxmPlanReaderError(
                "DXM_PLAN_READER_ENVELOPE_INVALID",
                "E2 Reader 没有返回会话绑定回包。",
            )
        browser_session_id = str(value.get("browser_session_id") or "").strip()
        account_ref = str(value.get("account_ref") or "").strip()
        payload = value.get("payload")
        if not browser_session_id or not account_ref or not isinstance(payload, Mapping):
            raise DxmPlanReaderError(
                "DXM_PLAN_READER_ENVELOPE_INVALID",
                "E2 Reader 回包缺少浏览器会话、账号证明或 payload。",
            )
        return browser_session_id, account_ref, payload

    @staticmethod
    def _normalize_template_record(
        value: Any,
        *,
        index: int,
        shop_id: str,
        category_ids: set[str],
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_RESPONSE_INVALID",
                f"template_records[{index}] 不是对象。",
            )
        ref_type = _normalized_text(value.get("ref_type"), "ref_type")
        if ref_type not in DXM_E2_TEMPLATE_REF_TYPES:
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_TYPE_INVALID",
                "店小秘模板类型不在 E2 稳定类型集合内。",
            )
        record_shop_id = _positive_id_text(value.get("shop_id"), "record shop_id")
        if record_shop_id != shop_id:
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_SCOPE_CONFLICT",
                "店小秘模板引用属于另一个店铺。",
            )
        raw_category_id = value.get("category_id")
        category_id = (
            None
            if raw_category_id is None
            else _positive_id_text(raw_category_id, "record category_id")
        )
        if category_id is not None and category_id not in category_ids:
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_SCOPE_CONFLICT",
                "店小秘模板引用属于请求作用域以外的类目。",
            )
        source_api = _normalized_text(value.get("source_api"), "source_api")
        if source_api not in DXM_E2_READ_APIS:
            raise DxmPlanReaderError(
                "DXM_PLAN_READ_ALLOWLIST_VIOLATION",
                "模板来源接口不在 E2 只读白名单内。",
            )
        availability = _normalized_text(value.get("availability"), "availability")
        if availability != "available":
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_AVAILABILITY_INVALID",
                "实时同步只允许写入本次实际观察到的可用模板。",
            )
        raw_resolved_values = value.get("resolved_values")
        if not isinstance(raw_resolved_values, Mapping):
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_RESPONSE_INVALID",
                "模板只读回包缺少 resolved_values。",
            )
        resolved_values: dict[str, Any] = {}
        for raw_field_key, raw_value in raw_resolved_values.items():
            field_key = str(raw_field_key)
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", field_key) is None:
                raise DxmPlanReaderError(
                    "DXM_TEMPLATE_RESPONSE_INVALID",
                    "模板解析值包含不稳定 field_key。",
                )
            if raw_value is None or (isinstance(raw_value, str) and not raw_value.strip()):
                continue
            if "publish" in field_key.casefold() or "release" in field_key.casefold():
                raise DxmPlanReaderError(
                    "DXM_TEMPLATE_PUBLISH_FORBIDDEN",
                    "模板解析值包含发布指令，已停止同步。",
                )
            try:
                resolved_values[field_key] = json.loads(
                    json.dumps(
                        raw_value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise DxmPlanReaderError(
                    "DXM_TEMPLATE_RESPONSE_INVALID",
                    "模板解析值不是规范 JSON。",
                ) from exc
        raw_audit_items = value.get("audit_items", [])
        if not isinstance(raw_audit_items, list):
            raise DxmPlanReaderError(
                "DXM_TEMPLATE_RESPONSE_INVALID",
                "模板只读回包 audit_items 不是数组。",
            )
        audit_items: list[dict[str, Any]] = []
        for audit_index, raw_audit in enumerate(raw_audit_items):
            expected_keys = {
                "kind",
                "executable",
                "source_index",
                "attr_name",
                "attr_value",
                "reason_code",
            }
            if (
                not isinstance(raw_audit, Mapping)
                or set(raw_audit) != expected_keys
                or raw_audit.get("kind") != "unmapped_custom_attribute"
                or raw_audit.get("executable") is not False
                or isinstance(raw_audit.get("source_index"), bool)
                or not isinstance(raw_audit.get("source_index"), int)
                or raw_audit["source_index"] < 0
                or raw_audit.get("reason_code")
                != "DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED"
            ):
                raise DxmPlanReaderError(
                    "DXM_TEMPLATE_RESPONSE_INVALID",
                    f"模板审计项 {audit_index} 结构无效。",
                )
            attr_name = _normalized_text(
                raw_audit.get("attr_name"),
                "audit attr_name",
            )
            try:
                attr_value = json.loads(
                    json.dumps(
                        raw_audit.get("attr_value"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                )
            except (TypeError, ValueError) as exc:
                raise DxmPlanReaderError(
                    "DXM_TEMPLATE_RESPONSE_INVALID",
                    "模板审计项属性值不是规范 JSON。",
                ) from exc
            if attr_value is None or (
                isinstance(attr_value, str) and not attr_value.strip()
            ):
                raise DxmPlanReaderError(
                    "DXM_TEMPLATE_RESPONSE_INVALID",
                    "模板审计项属性值为空。",
                )
            audit_items.append(
                {
                    "kind": "unmapped_custom_attribute",
                    "executable": False,
                    "source_index": raw_audit["source_index"],
                    "attr_name": attr_name,
                    "attr_value": attr_value,
                    "reason_code": "DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED",
                }
            )
        digest_body = {
            "ref_type": ref_type,
            "dxm_template_id": _positive_id_text(
                value.get("dxm_template_id"),
                "dxm_template_id",
            ),
            "shop_id": record_shop_id,
            "category_id": category_id,
            "observed_display_name": _normalized_text(
                value.get("observed_display_name"),
                "observed_display_name",
            ),
            "source_api": source_api,
            "source_record": value.get("source_record"),
            "resolved_values": resolved_values,
            "audit_items": audit_items,
        }
        return {
            **{key: item for key, item in digest_body.items() if key != "source_record"},
            "availability": "available",
            "source_digest": canonical_sha256(digest_body),
        }

    @staticmethod
    def _record_identity(record: Mapping[str, Any]) -> tuple[str, str, str, str | None]:
        return (
            str(record["ref_type"]),
            str(record["dxm_template_id"]),
            str(record["shop_id"]),
            None if record["category_id"] is None else str(record["category_id"]),
        )

    @staticmethod
    def _session_ref(browser_session_id: str, account_ref: str) -> str:
        return hashlib.sha256(
            f"dxm-draft-reader:{browser_session_id}:{account_ref}".encode("utf-8")
        ).hexdigest()[:16]


def _positive_id_text(value: Any, label: str) -> str:
    if isinstance(value, bool):
        raise DxmPlanReaderError(
            "DXM_PLAN_IDENTITY_INVALID",
            f"{label} 不是稳定正整数身份。",
        )
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value
    else:
        text = ""
    if re.fullmatch(r"[1-9][0-9]*", text) is None:
        raise DxmPlanReaderError(
            "DXM_PLAN_IDENTITY_INVALID",
            f"{label} 不是稳定正整数身份。",
        )
    return text


def _normalized_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DxmPlanReaderError(
            "DXM_TEMPLATE_RESPONSE_INVALID",
            f"{label} 必须是规范化非空文本。",
        )
    return value
