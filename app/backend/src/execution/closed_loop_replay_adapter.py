"""Shop-locked Path B website stand-in for isolated closed-loop replay.

This adapter replaces dianxiaomi.com only.  FastAPI, snapshot, Runner, ledger
and receipts remain production code.  It must never be the default start-mvp
assembly.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.core.config import SCREENSHOT_DIR
from src.execution.account_identity import account_context_hash
from src.execution.action_result_contract import ACTION_RESULT_SCHEMA_VERSION

CLOSED_LOOP_ENV = "DXM_PATH_B_CLOSED_LOOP"
SHOP_ID = "88001"
SHOP_NAME = "Dang Kang"
PRODUCT_ID = "88001001"
PRODUCT_IDS = ("88001001", "88001002", "88001003")
CATEGORY_ID = "100"
BROWSER_SESSION_ID = "closed-loop-browser-dangkang"
ACCOUNT_REF = "c" * 32
TITLE_VALUE = "Car Phone Holder Stand"
MATERIAL_VALUE = "ABS"
SEMI_FIELD_VALUE = "general_cargo"

PAGE_URLS = {
    "authenticated_dxm": "https://www.dianxiaomi.com/web/index.htm",
    "draft_box": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
    "editor": "https://www.dianxiaomi.com/web/smt/edit",
    "semi_managed": "https://www.dianxiaomi.com/web/smt/editFromSmt",
}

ACTION_CONTRACTS = {
    "check_login_state": (
        "PRECHECK_SESSION",
        "authenticated_dxm",
        ("session_authenticated", "business_page_ready", "loading_absent"),
    ),
    "open_draft_box": (
        "OPEN_DRAFT_LIST",
        "draft_box",
        ("expected_page", "business_marker_present", "loading_absent", "blocking_modal_absent"),
    ),
    "open_editor": (
        "OPEN_EDIT_PAGE",
        "editor",
        (
            "expected_editor_page",
            "editor_ready",
            "product_identity_match",
            "store_match",
            "source_identity_match",
        ),
    ),
    "verify_edit_ownership": (
        "VERIFY_EDIT_OWNERSHIP",
        "editor",
        (
            "editor_identity_match",
            "product_identity_match",
            "store_match",
            "source_identity_match",
        ),
    ),
    "fill_editor_required_defaults": (
        "FILL_BASE_INFO",
        "editor",
        (
            "title_readback_nonempty",
            "title_readback_exact",
            "category_selected_exact",
            "required_templates_resolved",
            "required_fields_complete",
        ),
    ),
    "fill_editor_variants": (
        "FILL_VARIANTS",
        "editor",
        (
            "variant_rows_present",
            "sku_readback_exact",
            "price_readback_exact",
            "stock_readback_exact",
            "all_required_cells_complete",
        ),
    ),
    "fill_media_assets": (
        "FILL_MEDIA",
        "editor",
        (
            "main_images_present",
            "required_assets_match",
            "invalid_images_absent",
            "marketing_assets_complete",
        ),
    ),
    "fill_compliance_defaults": (
        "FILL_COMPLIANCE",
        "editor",
        (
            "required_compliance_complete",
            "eu_responsible_readback_exact",
            "manufacturer_readback_exact",
            "customs_readback_exact",
            "required_templates_applied",
        ),
    ),
    "enable_semi_managed": (
        "ENABLE_SEMI_MANAGED",
        "editor",
        (
            "semi_managed_visible",
            "semi_managed_enabled",
            "toggle_readback_exact",
            "publish_not_attempted",
        ),
    ),
    "open_semi_managed_page": (
        "SAVE_INTENT_MODAL",
        "semi_managed",
        (
            "expected_semi_managed_page",
            "business_marker_present",
            "loading_absent",
            "source_editor_identity_preserved",
        ),
    ),
    "fill_semi_goods": (
        "FILL_SEMI_GOODS",
        "semi_managed",
        (
            "weight_readback_exact",
            "dimensions_readback_exact",
            "logistics_attribute_readback_exact",
            "freight_template_readback_exact",
            "service_template_readback_exact",
            "required_goods_fields_complete",
        ),
    ),
    "fill_semi_variants": (
        "FILL_SEMI_VARIANTS",
        "semi_managed",
        (
            "variant_rows_present",
            "product_price_readback_exact",
            "supply_price_readback_exact",
            "jit_stock_readback_exact",
            "goods_code_readback_exact",
            "required_variant_fields_complete",
        ),
    ),
    "save_only": (
        "SAVE_ONLY",
        "semi_managed",
        (
            "mutation_authorized",
            "exact_save_target",
            "save_click_dispatched",
            "network_save_success",
            "page_save_success",
            "published_false",
            "publish_action_not_clicked",
        ),
    ),
    "save2_only": (
        "SAVE2_ONLY",
        "semi_managed",
        (
            "mutation_authorized",
            "exact_save_target",
            "save_click_dispatched",
            "network_save_success",
            "page_save_success",
            "published_false",
            "publish_action_not_clicked",
        ),
    ),
    "verify_save1": (
        "VERIFY_SAVE1_NOT_PUBLISHED",
        "editor",
        (
            "independent_probe",
            "product_identity_match",
            "unpublished_verified",
            "publish_status_absent_or_false",
            "save_evidence_not_reused",
        ),
    ),
    "verify_save2": (
        "VERIFY_SAVE2_NOT_PUBLISHED",
        "semi_managed",
        (
            "independent_probe",
            "product_identity_match",
            "unpublished_verified",
            "publish_status_absent_or_false",
            "save_evidence_not_reused",
        ),
    ),
}

MAIN_SECTIONS = (
    "basic_info",
    "dxm_info",
    "attribute_info",
    "product_info",
    "regional_pricing",
    "description_info",
    "packaging_info",
    "template_main",
    "template_tax",
    "compliance_info",
    "other_info",
)
SEMI_SECTIONS = ("semi_countries", "semi_goods", "semi_variants")
CAPABILITIES = (
    "video",
    "wholesale",
    "translation",
    "semiManaged",
    "rollbackPreparation",
)


def closed_loop_replay_enabled() -> bool:
    return os.environ.get(CLOSED_LOOP_ENV, "").strip() == "1"


def is_closed_loop_replay_adapter(adapter: Any) -> bool:
    if adapter is None:
        return False
    cls = adapter.__class__
    return (
        cls.__name__ == "ClosedLoopReplayAdapter"
        and str(cls.__module__).endswith("closed_loop_replay_adapter")
    )


def session_ref() -> str:
    return hashlib.sha256(
        f"dxm-draft-reader:{BROWSER_SESSION_ID}:{ACCOUNT_REF}".encode("utf-8")
    ).hexdigest()[:16]


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tiny_png_ref(name: str, kind: str, captured_at: str) -> dict[str, Any]:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = (SCREENSHOT_DIR / name).resolve()
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)

    content = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(content)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(content).hexdigest().upper(),
        "size": len(content),
        "kind": kind,
        "captured_at": captured_at,
    }


def _readback(field_key: str, label: str, before: Any, after: Any) -> dict[str, Any]:
    return {
        "field_key": field_key,
        "field_label": label,
        "source": "closed_loop_replay",
        "before_value": before,
        "after_value": after,
        "readback_proven": True,
        "timestamp": _now(),
    }


def _section_receipt(section: str, field_key: str, label: str, value: Any) -> dict[str, Any]:
    started = _now()
    body = {
        "schema_version": "dxm.path-b.section-receipt.v1",
        "section": section,
        "action_grant_id": f"closed-loop-{section}",
        "success": True,
        "readback_proven": True,
        "field_readbacks": [_readback(field_key, label, value, value)],
        "started_at": started,
        "completed_at": started,
    }
    return {**body, "receipt_sha256": _canonical_sha256(body)}


def _capability_receipt(
    capability: str,
    phase: str,
    *,
    media_identity: str | None = None,
    preimage: bool = False,
) -> dict[str, Any]:
    started = _now()
    raw: dict[str, Any] = {
        "phase": phase,
        "action_grant_id": f"closed-loop-{capability}",
        "result_ok": True,
        "error_code": None,
        "error_detail": None,
        "unresolved": False,
        "media_identity": media_identity,
        "started_at": started,
        "completed_at": started,
        "field_readbacks": [],
    }
    digest = _canonical_sha256(raw)
    raw["canonical_sha256"] = digest
    if preimage:
        raw["preimage_sha256"] = digest
    return {"canonical_receipt": raw, "receipt_sha256": digest}


def category_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "minLength": 8,
                "natural_language": True,
                "ui_binding": "dxm_editor:title",
                "ui_section": "basic_info",
            },
            "material": {
                "type": "string",
                "ui_binding": "dxm_attribute:1001",
                "ui_section": "attribute_info",
            },
            "semi_packaging": {
                "type": "string",
                "ui_binding": "dxm_editor:semi_packaging",
                "ui_section": "semi_managed",
            },
        },
        "required": ["title", "material"],
        "price_policy": {
            "sku_cargo_not_above_sale": True,
            "sku_prices_within_range": True,
        },
    }


class ClosedLoopReplayAdapter:
    """Replay dianxiaomi page actions for Dang Kang Path B only."""

    requires_persistent_browser_agent = False

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.envelopes: list[dict[str, Any]] = []
        self.accepted_session_refs: list[str] = []
        self._save_count = 0
        self._verify_count = 0
        self._semi_fill_count = 0
        self._account_hash = account_context_hash(ACCOUNT_REF)

    def browser_session_id(self) -> str:
        return BROWSER_SESSION_ID

    def refresh_account_context_hash(self) -> str:
        return self._account_hash

    def current_account_context_hash(self) -> str:
        return self._account_hash

    def mandatory_capability_status(self, capability: str) -> dict[str, Any]:
        allowed = {
            "video",
            "translation",
            "wholesale",
            "semiManaged",
            "rollbackPreparation",
        }
        canonical = str(capability or "").strip()
        if canonical not in allowed:
            return {
                "ok": False,
                "capability": canonical,
                "reason_code": "MANDATORY_CAPABILITY_UNKNOWN",
            }
        return {"ok": True, "capability": canonical, "reason_code": "CLOSED_LOOP_REPLAY"}

    def _envelope(self, action: str, **kwargs: Any) -> dict[str, Any]:
        self._assert_shop(kwargs.get("store_name"))
        contract_key = action
        if action == "save_only":
            self._save_count += 1
            contract_key = "save_only" if self._save_count == 1 else "save2_only"
        elif action == "verify_not_published":
            self._verify_count += 1
            contract_key = "verify_save1" if self._verify_count == 1 else "verify_save2"
        elif action == "fill_semi_managed_defaults":
            self._semi_fill_count += 1
            contract_key = (
                "fill_semi_goods" if self._semi_fill_count == 1 else "fill_semi_variants"
            )
        state, page_kind, conditions = ACTION_CONTRACTS[contract_key]
        self.calls.append(action)
        self.envelopes.append({"action": action, "state": state, "postconditions": conditions})
        captured_at = _now()
        target_identity = kwargs.get("target_identity")
        product_query = kwargs.get("product_query") or PRODUCT_ID
        store_name = kwargs.get("store_name") or SHOP_NAME
        self.accepted_session_refs.append(session_ref())
        page_url = PAGE_URLS[page_kind]
        before_values = {
            "requested_action": action,
            "product_query": product_query,
            "store_name": store_name,
        }
        if isinstance(target_identity, dict):
            before_values["target_identity"] = dict(target_identity)
        after_values = {"observed_action": action, "page_url": page_url}
        observations: dict[str, Any] = {
            "action": action,
            "page_title": "店小秘--编辑速卖通产品",
            "page_url": page_url,
            "product_query": product_query,
            "store_name": store_name,
        }
        refs: list[dict[str, Any]] = []
        if action == "fill_compliance_defaults":
            observations["path_b_section_receipts"] = {
                section: _section_receipt(section, "title", "英文标题", TITLE_VALUE)
                for section in MAIN_SECTIONS
            }
            observations["mandatory_capability_receipts"] = {
                "video": _capability_receipt(
                    "video",
                    "content_finalize_video",
                    media_identity="closed-loop-video-1",
                ),
                "wholesale": _capability_receipt(
                    "wholesale", "content_finalize_wholesale"
                ),
                "translation": _capability_receipt(
                    "translation", "content_finalize_translation"
                ),
                "rollbackPreparation": _capability_receipt(
                    "rollbackPreparation",
                    "rollback_preparation",
                    preimage=True,
                ),
            }
        if action == "fill_semi_managed_defaults" and self._semi_fill_count >= 2:
            observations["path_b_section_receipts"] = {
                section: _section_receipt(
                    section, "semi_packaging", "半托管包装", SEMI_FIELD_VALUE
                )
                for section in SEMI_SECTIONS
            }
            observations["mandatory_capability_receipts"] = {
                "semiManaged": _capability_receipt(
                    "semiManaged", "semi_managed_entry"
                )
            }
        if action == "open_semi_managed_page":
            observations["save_intent_handshake"] = {
                "save1_verified": True,
                "exactly_one_save_request": True,
                "gate_outcome": "admitted",
                "semi_entry_triggered": True,
                "handshake_id": "closed-loop-handshake-1",
                "same_handshake": True,
            }
        if action == "save_only":
            save_result = self._save_result(target_identity, store_name)
            observations["save_result"] = save_result
            observations["exact_save_target"] = {
                "text": "保存",
                "exact_save_count": 1,
                "click_method": "locator.click",
            }
            observations["save_click_dispatched"] = True
            for key in (
                "mutation_authorization",
                "pre_dispatch_readback",
                "network_save_result",
                "network_audit",
                "publish_signal",
                "page_save_result",
            ):
                observations[key] = save_result.get(key)
                after_values[key] = save_result.get(key)
            after_values.update(
                {
                    "published": False,
                    "save_result": save_result,
                    "exact_save_target": True,
                    "save_click_dispatched": True,
                }
            )
            refs.append(
                _tiny_png_ref(
                    f"closed-loop-{state.lower()}-{self._save_count}.png",
                    "save_screenshot",
                    captured_at,
                )
            )
        if action == "verify_not_published":
            proof = self._unpublished_proof(target_identity, page_url)
            observed_target = {
                "product_matched": True,
                "store_matched": True,
                "source_identity_match": True,
                "target_bound": True,
                "target_identity_sha256": proof["target_identity_sha256"],
            }
            after_values.update(
                {
                    "published": False,
                    "fresh_probe": proof,
                    "target_identity": observed_target,
                    "identity_readback": proof["identity_readback"],
                }
            )
            observations.update(
                {
                    "fresh_probe": proof,
                    "unpublished_proof": proof,
                    "target_identity": observed_target,
                    "identity_readback": proof["identity_readback"],
                }
            )
            refs.append(
                _tiny_png_ref(
                    f"closed-loop-{state.lower()}-{self._verify_count}.png",
                    "unpublished_screenshot",
                    captured_at,
                )
            )
        contract_facts = {
            "before_values": before_values,
            "after_values": after_values,
            "postconditions": {name: True for name in conditions},
            "evidence_observations": observations,
            "failure_code": None,
            "recoverability": {
                "kind": "none",
                "retryable": False,
                "requires_page_reverify": False,
                "reason": None,
            },
        }
        envelope = {
            "schema_version": ACTION_RESULT_SCHEMA_VERSION,
            "ok": True,
            "action": action,
            "attempted_state": state,
            "before_values": before_values,
            "after_values": after_values,
            "postconditions": contract_facts["postconditions"],
            "evidence_observations": observations,
            "refs": refs,
            "page_identity": {
                "kind": page_kind,
                "url": page_url,
                "browser_session_id": BROWSER_SESSION_ID,
            },
            "failure_code": None,
            "recoverability": contract_facts["recoverability"],
            "contract_facts": contract_facts,
            "store_name": store_name,
            "target_identity": target_identity,
        }
        self.envelopes.append(envelope)
        return envelope

    def _save_result(self, target_identity: Any, store_name: str) -> dict[str, Any]:
        identity = target_identity if isinstance(target_identity, dict) else {}
        digest = _canonical_sha256(identity)
        return {
            "ok": True,
            "code": 0,
            "msg": "真实保存成功",
            "published": False,
            "click_method": "locator.click",
            "mutation_authorization": {
                "ok": True,
                "reason_code": "CLOSED_LOOP_REPLAY",
            },
            "pre_dispatch_readback": {"ok": True},
            "network_save_result": {
                "ok": True,
                "http_status": 200,
                "business_code": 0,
            },
            "network_audit": {
                "ok": True,
                "write_count": 1,
                "publish_count": 0,
            },
            "publish_signal": {"ok": True, "published": False},
            "page_save_result": {"ok": True, "text": "保存成功"},
            "save_decision": {
                "ok": True,
                "rule": "page_success_and_network_success",
                "page_ok": True,
                "network_ok": True,
                "network_receipt_ok": True,
                "network_audit_ok": True,
            },
            "target_identity_sha256": digest,
            "store_name": store_name,
        }

    def _unpublished_proof(self, target_identity: Any, page_url: str) -> dict[str, Any]:
        identity = target_identity if isinstance(target_identity, dict) else {}
        digest = _canonical_sha256(identity)
        return {
            "ok": True,
            "published": False,
            "proof_kind": "structured_unpublished_status",
            "status_text": "待发布",
            "verified_on_current_page": True,
            "status_scope_unique": True,
            "bound_candidate_count": 1,
            "structured_candidate_count": 1,
            "target_bound": True,
            "product_matched": True,
            "store_matched": True,
            "source_identity_match": True,
            "identity_binding_kind": "frozen_target_structured_page_readback",
            "publish_risk_term": None,
            "target_identity_sha256": digest,
            "page_url": page_url,
            "identity_readback": {
                "product_identity_match": True,
                "store_identity_match": True,
                "source_identity_match": True,
            },
        }

    @staticmethod
    def _assert_shop(store_name: Any) -> None:
        if store_name in (None, "", SHOP_NAME):
            return
        raise RuntimeError(f"CLOSED_LOOP_SHOP_FORBIDDEN:{store_name}")

    def _envelope_read(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "browser_session_id": BROWSER_SESSION_ID,
            "account_ref": ACCOUNT_REF,
            "payload": payload,
        }

    def read_draft_shops(self) -> dict[str, Any]:
        return self._envelope_read(
            {
                "code": 0,
                "data": {
                    "userId": "42",
                    "shopMap": {
                        SHOP_ID: {
                            "idStr": SHOP_ID,
                            "id": int(SHOP_ID),
                            "name": SHOP_NAME,
                            "platform": "smt",
                        }
                    },
                    "shopSmtTypeMap": {SHOP_ID: "POP"},
                },
            }
        )

    def read_draft_page(
        self,
        *,
        shop_id: str,
        page_no: int,
        page_size: int,
    ) -> dict[str, Any]:
        if shop_id not in {SHOP_ID, "-1"}:
            raise RuntimeError(f"CLOSED_LOOP_SHOP_FORBIDDEN:{shop_id}")
        items = [
            {
                "idStr": pid,
                "id": int(pid),
                "shopId": SHOP_ID,
                "subject": TITLE_VALUE,
                "categoryId": CATEGORY_ID,
                "dxmState": "draft",
                "sourceUrl": f"https://detail.1688.com/offer/{pid}.html",
            }
            for pid in PRODUCT_IDS
        ]
        return self._envelope_read(
            {
                "code": 0,
                "data": {
                    "page": {
                        "pageNo": page_no,
                        "pageSize": page_size,
                        "totalPage": 1,
                        "totalSize": len(PRODUCT_IDS),
                        "list": items if page_no == 1 else [],
                    }
                },
            }
        )

    def read_e2_plan_scope(
        self,
        *,
        shop_id: str,
        category_ids: list[str],
        representative_product_ids: Any = None,
    ) -> dict[str, Any]:
        if shop_id != SHOP_ID:
            raise RuntimeError(f"CLOSED_LOOP_SHOP_FORBIDDEN:{shop_id}")
        records = [
            {
                "ref_type": "freight",
                "dxm_template_id": "901",
                "shop_id": shop_id,
                "category_id": None,
                "observed_display_name": "店铺运费模板",
                "source_api": "/api/smtShopInfoSync/list.json",
                "availability": "available",
                "source_record": {"revision": "v1"},
                "resolved_values": {},
            },
            {
                "ref_type": "service",
                "dxm_template_id": "911",
                "shop_id": shop_id,
                "category_id": None,
                "observed_display_name": "店铺服务模板",
                "source_api": "/api/smtCommMsr/list.json",
                "availability": "available",
                "source_record": {"revision": "v1"},
                "resolved_values": {},
            },
            {
                "ref_type": "attribute",
                "dxm_template_id": "902",
                "shop_id": shop_id,
                "category_id": CATEGORY_ID,
                "observed_display_name": "普货属性模板",
                "source_api": "/api/smtAttributeTemplate/getTemplateListByCategory.json",
                "availability": "available",
                "source_record": {"revision": "v1"},
                "resolved_values": {"material": MATERIAL_VALUE},
            },
        ]
        schemas = {cid: category_schema() for cid in category_ids}
        return self._envelope_read(
            {
                "template_records": records,
                "category_schemas": schemas,
            }
        )

    def read_e2_product_details(
        self,
        *,
        shop_id: str,
        product_ids: list[str],
    ) -> dict[str, Any]:
        if shop_id != SHOP_ID:
            raise RuntimeError(f"CLOSED_LOOP_SHOP_FORBIDDEN:{shop_id}")
        products = [
            {
                "idStr": pid,
                "id": int(pid),
                "shopId": SHOP_ID,
                "subject": TITLE_VALUE,
                "categoryId": CATEGORY_ID,
                "dxmState": "draft",
                "material": MATERIAL_VALUE,
                "semi_packaging": SEMI_FIELD_VALUE,
                "aeopAeProductPropertys": json.dumps(
                    [{"attrNameId": 1001, "attrValueId": 2001}]
                ),
            }
            for pid in product_ids
        ]
        return self._envelope_read({"products": products})

    def read_dxm_template_library(self, *, shop_id: str) -> dict[str, Any]:
        return self.read_e2_plan_scope(shop_id=shop_id, category_ids=[CATEGORY_ID])

    def check_login_state(self) -> dict[str, Any]:
        return self._envelope("check_login_state")

    def open_draft_box(self) -> dict[str, Any]:
        return self._envelope("open_draft_box")

    def open_editor(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("open_editor", **kwargs)

    def verify_edit_ownership(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("verify_edit_ownership", **kwargs)

    def fill_editor_required_defaults(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("fill_editor_required_defaults", **kwargs)

    def fill_editor_variants(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("fill_editor_variants", **kwargs)

    def fill_media_assets(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("fill_media_assets", **kwargs)

    def fill_compliance_defaults(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("fill_compliance_defaults", **kwargs)

    def enable_semi_managed(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("enable_semi_managed", **kwargs)

    def open_semi_managed_page(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("open_semi_managed_page", **kwargs)

    def fill_semi_managed_defaults(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("fill_semi_managed_defaults", **kwargs)

    def save_only(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("save_only", **kwargs)

    def verify_not_published(self, **kwargs: Any) -> dict[str, Any]:
        return self._envelope("verify_not_published", **kwargs)
