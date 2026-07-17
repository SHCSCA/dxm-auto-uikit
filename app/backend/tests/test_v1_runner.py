import asyncio
import hashlib
import json
import sqlite3
import struct
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from src import db, repository as repository_module
from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.browser_agent_worker import BrowserAgentRuntime
from src.execution import v1_runner as v1_runner_module
from src.execution.v1_runner import V1ExecutionError, V1TaskRunner
from src.repository import Repository
from src.state_machine.contracts import StateName
from src.state_machine.two_stage import canonical_claim_target_identity, canonical_source_identity


def _test_runner(*args, **kwargs):
    kwargs.setdefault("authorization_verifier", lambda *_args: {"ok": True, "reason_code": "OK"})
    return V1TaskRunner(*args, **kwargs)


def _evidence_ref(name: str) -> dict:
    path = (Path(v1_runner_module.SCREENSHOT_DIR) / name).resolve()
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
    }


_TEST_PAGE_URLS = {
    "authenticated_dxm": "https://www.dianxiaomi.com/web/index.htm",
    "data_acquisition": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    "draft_box": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
    "editor": "https://www.dianxiaomi.com/web/smt/edit",
    "semi_managed": "https://www.dianxiaomi.com/web/smt/editFromSmt",
}

_TEST_ACTION_CONTRACTS = {
    "check_login_state": ("PRECHECK_SESSION", "authenticated_dxm", ("session_authenticated", "business_page_ready", "loading_absent")),
    "open_data_acquisition": ("OPEN_DATA_ACQUISITION", "data_acquisition", ("expected_page", "business_marker_present", "loading_absent", "blocking_modal_absent")),
    "claim_from_data_acquisition": ("CLAIM_TO_DRAFT_BOX", "data_acquisition", ("target_unique", "source_identity_match", "store_selected_exact", "category_selected_exact", "claim_dispatched", "publish_not_attempted")),
    "verify_draft_box_claim": ("VERIFY_DRAFT_BOX_CLAIM", "draft_box", ("draft_box_verified", "target_unique", "product_identity_match", "store_match", "source_identity_match", "claim_mark_match")),
    "open_draft_box": ("OPEN_DRAFT_LIST", "draft_box", ("expected_page", "business_marker_present", "loading_absent", "blocking_modal_absent")),
    "claim_product": ("CLAIM_PRODUCT", "draft_box", ("target_unique", "note_write_attempted", "note_readback_exact", "ownership_binding_match")),
    "open_editor": ("OPEN_EDIT_PAGE", "editor", ("expected_editor_page", "editor_ready", "product_identity_match", "store_match", "source_identity_match")),
    "verify_edit_ownership": ("VERIFY_EDIT_OWNERSHIP", "editor", ("editor_identity_match", "product_identity_match", "store_match", "source_identity_match")),
    "fill_editor_required_defaults": ("FILL_BASE_INFO", "editor", ("title_readback_nonempty", "title_readback_exact", "category_selected_exact", "required_templates_resolved", "required_fields_complete")),
    "fill_editor_variants": ("FILL_VARIANTS", "editor", ("variant_rows_present", "sku_readback_exact", "price_readback_exact", "stock_readback_exact", "all_required_cells_complete")),
    "fill_media_assets": ("FILL_MEDIA", "editor", ("main_images_present", "required_assets_match", "invalid_images_absent", "marketing_assets_complete")),
    "fill_compliance_defaults": ("FILL_COMPLIANCE", "editor", ("required_compliance_complete", "eu_responsible_readback_exact", "manufacturer_readback_exact", "customs_readback_exact", "required_templates_applied")),
    "enable_semi_managed": ("ENABLE_SEMI_MANAGED", "editor", ("semi_managed_visible", "semi_managed_enabled", "toggle_readback_exact", "publish_not_attempted")),
    "open_semi_managed_page": ("OPEN_SEMI_MANAGED_PAGE", "semi_managed", ("expected_semi_managed_page", "business_marker_present", "loading_absent", "source_editor_identity_preserved")),
    "fill_semi_managed_defaults": ("FILL_SEMI_GOODS", "semi_managed", ("weight_readback_exact", "dimensions_readback_exact", "logistics_attribute_readback_exact", "freight_template_readback_exact", "service_template_readback_exact", "required_goods_fields_complete")),
    "save_only": ("SAVE_ONLY", "semi_managed", ("mutation_authorized", "exact_save_target", "save_click_dispatched", "network_save_success", "page_save_success", "published_false", "publish_action_not_clicked")),
    "verify_not_published": ("VERIFY_NOT_PUBLISHED", "semi_managed", ("independent_probe", "product_identity_match", "unpublished_verified", "publish_status_absent_or_false", "save_evidence_not_reused")),
}

_TEST_SEMI_VARIANT_CONTRACT = (
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
)


def _canonical_test_action_result(
    action: str,
    legacy_result: dict,
    *,
    state_override: str | None = None,
    runtime_id: str = "test-runtime",
    browser_session_id: str = "test-browser-session",
) -> dict:
    state, page_kind, condition_names = _TEST_ACTION_CONTRACTS[action]
    if state_override == "FILL_SEMI_VARIANTS":
        state, page_kind, condition_names = _TEST_SEMI_VARIANT_CONTRACT
    ok = legacy_result.get("ok") is True
    evidence = legacy_result.get("evidence") if isinstance(legacy_result.get("evidence"), dict) else {}
    if action == "claim_product" and evidence.get("note_verified") is False:
        ok = False
    save_result = legacy_result.get("save_result")
    if action == "save_only" and (not isinstance(save_result, dict) or save_result.get("ok") is not True):
        ok = False

    product_query = legacy_result.get("product_query") or "test-product"
    store_name = legacy_result.get("store_name") or "test-store"
    before_values = {
        "requested_action": action,
        "product_query": product_query,
        "store_name": store_name,
    }
    if action in {"save_only", "verify_not_published"}:
        before_values["target_identity"] = {
            "product_query": "test-product",
            "store_name": "test-store",
        }

    after_values = {
        "observed_action": action,
        "page_url": _TEST_PAGE_URLS[page_kind],
    }
    if action == "save_only":
        after_values.update({"published": False, "save_result": dict(save_result or {})})
    if action == "verify_not_published":
        after_values.update({"published": False, "fresh_probe": {"ok": True}})

    observations = {
        **evidence,
        "page_title": legacy_result.get("page_title"),
        "page_url": _TEST_PAGE_URLS[page_kind],
        "product_query": product_query,
        "store_name": store_name,
    }
    for key in (
        "save_result",
        "fill_result",
        "unpublished_proof",
        "dxm_reference_template_results",
    ):
        if legacy_result.get(key) is not None:
            observations[key] = legacy_result[key]

    refs = []
    basic_ref = legacy_result.get("evidence_ref") or evidence.get("evidence_ref")
    if isinstance(basic_ref, dict):
        kind = {
            "VERIFY_DRAFT_BOX_CLAIM": "draft_box_screenshot",
            "SAVE_ONLY": "save_screenshot",
            "VERIFY_NOT_PUBLISHED": "unpublished_screenshot",
        }.get(state, "screenshot")
        captured_at = (
            "2026-05-22T00:00:02+00:00"
            if state == "VERIFY_NOT_PUBLISHED"
            else "2026-05-22T00:00:01+00:00"
        )
        refs.append({**basic_ref, "kind": kind, "captured_at": captured_at})

    return {
        "schema_version": "dxm.action-result.v1",
        "ok": ok,
        "action": action,
        "attempted_state": state,
        "before_values": before_values,
        "after_values": after_values,
        "postconditions": {name: ok for name in condition_names},
        "evidence": {"observations": observations, "refs": refs},
        "page_identity": {
            "kind": page_kind,
            "url": _TEST_PAGE_URLS[page_kind],
            "runtime_id": runtime_id,
            "browser_session_id": browser_session_id,
        },
        "failure_code": None if ok else "TEST_ACTION_FAILED",
        "recoverability": (
            {
                "kind": "none",
                "retryable": False,
                "requires_page_reverify": False,
                "reason": None,
            }
            if ok
            else {
                "kind": "manual_takeover",
                "retryable": False,
                "requires_page_reverify": True,
                "reason": "test action failed",
            }
        ),
    }


def _test_action_observations(result: dict) -> dict:
    return result["evidence"]["observations"]


def _test_action_first_ref(result: dict) -> dict:
    return result["evidence"]["refs"][0]


class DummyManager:
    def __init__(self):
        self.events = []

    async def broadcast(self, task_id, payload):
        self.events.append((task_id, payload))


class FakeWorkflowAdapter:
    def __init__(
        self,
        fail_action: str | None = None,
        note_verified: bool = True,
        save_result: dict | None = None,
        include_save_result: bool = True,
    ):
        self.calls = []
        self.fail_action = fail_action
        self.note_verified = note_verified
        self.save_result = save_result or {"ok": True, "code": 0, "msg": "真实保存成功", "published": False}
        self.include_save_result = include_save_result
        self.live_hud_calls = []

    def check_login_state(self):
        return self._record("check_login_state")

    def open_draft_box(self):
        return self._record("open_draft_box")

    def open_data_acquisition(self):
        return self._record("open_data_acquisition")

    def claim_from_data_acquisition(
        self,
        claim_mark,
        product_query=None,
        category_name=None,
        store_name=None,
        target_source_urls=None,
    ):
        return self._record(
            "claim_from_data_acquisition",
            claim_mark,
            product_query,
            category_name,
            store_name,
            target_source_urls,
        )

    def verify_draft_box_claim(
        self,
        claim_mark,
        product_query=None,
        category_name=None,
        store_name=None,
        target_source_urls=None,
    ):
        return self._record(
            "verify_draft_box_claim",
            claim_mark,
            product_query,
            category_name,
            store_name,
            target_source_urls,
        )

    def claim_product(self, note_text, product_query=None, store_name=None, target_source_urls=None):
        return self._record("claim_product", note_text, product_query, store_name, target_source_urls)

    def open_editor(self, product_query=None, store_name=None, note_text=None, target_source_urls=None):
        return self._record("open_editor", product_query, store_name, note_text, target_source_urls)

    def verify_edit_ownership(self, product_query=None, store_name=None, target_source_urls=None):
        return self._record("verify_edit_ownership", product_query, store_name, target_source_urls)

    def fill_editor_required_defaults(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_editor_required_defaults", defaults, product_query, store_name)

    def fill_editor_variants(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_editor_variants", defaults, product_query, store_name)

    def fill_media_assets(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_media_assets", defaults, product_query, store_name)

    def fill_compliance_defaults(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_compliance_defaults", defaults, product_query, store_name)

    def enable_semi_managed(self, product_query=None, store_name=None):
        return self._record("enable_semi_managed", product_query, store_name)

    def open_semi_managed_page(self, defaults=None, product_query=None, store_name=None):
        return self._record("open_semi_managed_page", defaults, product_query, store_name)

    def fill_semi_managed_defaults(self, defaults=None, product_query=None, store_name=None):
        return self._record("fill_semi_managed_defaults", defaults, product_query, store_name)

    def save_only(self, defaults=None, product_query=None, store_name=None):
        return self._record("save_only", defaults, product_query, store_name)

    def verify_not_published(self, product_query=None, store_name=None):
        return self._record("verify_not_published", product_query, store_name)

    def update_live_hud(self, hud):
        self.live_hud_calls.append(hud)
        return {
            "ok": True,
            "updated": True,
            "reason": "live_browser_hud_updated",
            "current_url": "https://www.dianxiaomi.com/web/smt/edit",
            "page_title": "店小秘--编辑速卖通产品",
            "hud": hud,
            "updated_at": "2026-05-22T00:00:02+00:00",
        }

    def _record(self, action, *args):
        self.calls.append((action, *args))
        evidence = {"action": action}
        if action == "claim_product":
            evidence["note_verified"] = self.note_verified
        if action == "verify_draft_box_claim":
            product_query = args[1] or "ACG Stand Product 1"
            category_name = args[2] or "立牌类谷子"
            store_name = args[3] or "Dang Kang"
            target_source_urls = list(args[4] or [])
            observed_source_url = "https://detail.1688.com/offer/from-acquisition.html"
            row_text = f"采集箱商品行 {product_query} {category_name} {store_name} AI认领"
            evidence["claimed_product"] = {
                "title": product_query,
                "category_name": category_name,
                "source_url": observed_source_url,
                "row_text": row_text,
            }
            semantic_match = (
                ("source_url", observed_source_url)
                if target_source_urls
                else (("keyword", product_query) if product_query else ("category_name", category_name))
            )
            evidence["draft_box_match"] = {
                "matched_by": semantic_match[0],
                "matched_value": semantic_match[1],
                "raw_matched_by": semantic_match[0],
                "row_text": row_text,
                "source_urls": [observed_source_url],
                "store_name": store_name,
                "store_evidence": {
                    "store_name": store_name,
                    "cell_text": f"「{store_name}」",
                    "source": "structured_store_cell",
                },
                "store_observation": {
                    "observed_store_name": store_name,
                    "selected": True,
                    "selected_store_names": [store_name],
                    "selection_evidence": {"input_checked": True},
                    "draft_box_cell_evidence": {
                        "store_name": store_name,
                        "cell_text": f"「{store_name}」",
                        "source": "structured_store_cell",
                    },
                },
            }
            evidence["evidence_ref"] = _evidence_ref(f"workflow-verify-{len(self.calls)}.png")
            evidence["claim_target"] = {
                "matchedBy": "source_url",
                "rowText": "待认领商品行 ACG Stand Product 1 认领",
                "sourceUrls": ["https://detail.1688.com/offer/from-acquisition.html"],
            }
            evidence["search_result"] = {
                "query": "https://detail.1688.com/offer/from-acquisition.html",
                "query_source": "target_source_url",
                "filled": True,
                "clicked_search": True,
            }
        if action == "fill_editor_required_defaults" and args:
            defaults = args[0] if isinstance(args[0], dict) else {}
            resolved = defaults.get("dxm_reference_templates_resolved") or {}
            applied = {
                section: {"ok": True, "section": section, **config}
                for section, config in resolved.items()
            }
            evidence["dxm_reference_template_results"] = applied
        if action == "save_only" and self.include_save_result:
            evidence["save_result"] = self.save_result
        if action in {"save_only", "verify_not_published"}:
            evidence["evidence_ref"] = _evidence_ref(
                f"workflow-{action}-{len(self.calls)}.png"
            )
        result = {
            "ok": action != self.fail_action,
            "action": action,
            "stage": f"{action}_stage",
            "page_title": "速卖通采集箱",
            "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "screenshot_url": f"/artifacts/{action}.png",
            "product_query": args[-2] if len(args) >= 2 else None,
            "store_name": args[-1] if len(args) >= 1 else None,
            "evidence": evidence,
        }
        if action == "save_only" and self.include_save_result:
            result["save_result"] = self.save_result
        if action in {"save_only", "verify_not_published"}:
            result["evidence_ref"] = evidence["evidence_ref"]
        if "dxm_reference_template_results" in evidence:
            result["dxm_reference_template_results"] = evidence["dxm_reference_template_results"]
        semi_call_count = sum(
            1 for recorded in self.calls if recorded and recorded[0] == "fill_semi_managed_defaults"
        )
        state_override = (
            "FILL_SEMI_VARIANTS"
            if action == "fill_semi_managed_defaults" and semi_call_count % 2 == 0
            else None
        )
        return _canonical_test_action_result(
            action,
            result,
            state_override=state_override,
        )


class ThreadRecordingWorkflowAdapter(FakeWorkflowAdapter):
    def __init__(self):
        super().__init__()
        self.thread_names = []
        self.hud_thread_names = []

    def _record(self, action, *args):
        self.thread_names.append(threading.current_thread().name)
        return super()._record(action, *args)

    def update_live_hud(self, hud):
        self.hud_thread_names.append(threading.current_thread().name)
        return super().update_live_hud(hud)


class FakeBrowserAgentRuntime:
    def __init__(self):
        self.commands = []

    def run(self, command, *, timeout_seconds=None):
        self.commands.append((command, timeout_seconds))
        if command.action == "update_live_hud":
            hud = command.params.get("hud") or {}
            return {
                "ok": True,
                "updated": True,
                "reason": "live_browser_hud_updated",
                "current_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "page_title": "店小秘数据采集",
                "hud": hud,
                "updated_at": "2026-05-22T00:00:03+00:00",
            }
        result = {
            "ok": True,
            "action": command.action,
            "stage": f"{command.action}_stage",
            "page_title": "店小秘商品箱" if command.action == "verify_draft_box_claim" else "店小秘数据采集",
            "page_url": (
                "https://www.dianxiaomi.com/web/smt/smtProductList/draft"
                if command.action == "verify_draft_box_claim"
                else "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition"
            ),
            "screenshot_url": f"/artifacts/{command.action}.png",
            "evidence": {
                "action": command.action,
                "claimed_product": {
                    "title": command.params.get("product_query") or "ACG Stand Product 1",
                    "category_name": command.params.get("category_name") or "立牌类谷子",
                    "source_url": "https://detail.1688.com/offer/from-acquisition.html",
                    "row_text": "采集箱商品行 ACG Stand Product 1 AI认领",
                } if command.action == "verify_draft_box_claim" else None,
                "draft_box_match": {
                    "matched_by": "source_url" if command.params.get("target_source_urls") else "keyword",
                    "matched_value": (
                        "https://detail.1688.com/offer/from-acquisition.html"
                        if command.params.get("target_source_urls")
                        else command.params.get("product_query") or "ACG Stand Product 1"
                    ),
                    "raw_matched_by": "source_url" if command.params.get("target_source_urls") else "keyword",
                    "row_text": (
                        f"采集箱商品行 {command.params.get('product_query') or 'ACG Stand Product 1'} "
                        f"{command.params.get('category_name') or '立牌类谷子'} "
                        f"{command.params.get('store_name') or 'Dang Kang'} AI认领"
                    ),
                    "source_urls": ["https://detail.1688.com/offer/from-acquisition.html"],
                    "store_name": command.params.get("store_name") or "Dang Kang",
                    "store_evidence": {
                        "store_name": command.params.get("store_name") or "Dang Kang",
                        "cell_text": f"「{command.params.get('store_name') or 'Dang Kang'}」",
                        "source": "structured_store_cell",
                    },
                    "store_observation": {
                        "observed_store_name": command.params.get("store_name") or "Dang Kang",
                        "selected": True,
                        "selected_store_names": [command.params.get("store_name") or "Dang Kang"],
                        "selection_evidence": {"input_checked": True},
                        "draft_box_cell_evidence": {
                            "store_name": command.params.get("store_name") or "Dang Kang",
                            "cell_text": f"「{command.params.get('store_name') or 'Dang Kang'}」",
                            "source": "structured_store_cell",
                        },
                    },
                } if command.action == "verify_draft_box_claim" else None,
                "evidence_ref": _evidence_ref(
                    f"browser-task-{command.task_id}-job-{command.job_id}-verify.png"
                ) if command.action == "verify_draft_box_claim" else None,
            },
        }
        if command.action == "save_only":
            result["save_result"] = {"ok": True, "code": 0, "msg": "真实保存成功", "published": False}
            result["evidence"]["save_result"] = result["save_result"]
        if command.action in {"save_only", "verify_not_published"}:
            evidence_ref = _evidence_ref(
                f"browser-task-{command.task_id}-job-{command.job_id}-{command.action}.png"
            )
            result["evidence_ref"] = evidence_ref
            result["evidence"]["evidence_ref"] = evidence_ref
        return _canonical_test_action_result(
            command.action,
            result,
            state_override=command.state,
            runtime_id=command.runtime_id,
            browser_session_id="fake-browser-agent-session",
        )


class FakeAgentConsole:
    def __init__(self, fail: bool = False):
        self.calls = []
        self.action_calls = []
        self.fail = fail
        self.start_calls = []

    def update_task_step(self, **payload):
        if self.fail:
            raise RuntimeError("console unavailable")
        self.calls.append(payload)
        return {
            "ok": True,
            "updated": True,
            "reason": "updated",
            "active": True,
            "session_id": "agent-test",
            "task_id": payload.get("task_id"),
            "job_id": payload.get("job_id"),
            "product_id": payload.get("product_id"),
            "browser_visible": False,
            "current_url": "about:blank",
            "last_step_code": payload.get("step_code"),
            "last_step_name": payload.get("step_name"),
            "hud": {
                "title": payload.get("step_name"),
                "state": payload.get("step_code"),
                "action": payload.get("field_domain"),
                "next_step": payload.get("next_step"),
                "store_name": payload.get("store_name"),
                "guard": "只保存不发布",
            },
            "screenshot": None,
            "updated_at": "2026-05-22T00:00:00+00:00",
            "last_error": None,
        }

    def record_action_event(self, **payload):
        if self.fail:
            raise RuntimeError("console unavailable")
        self.action_calls.append(payload)
        return {
            "ok": True,
            "updated": True,
            "reason": "action_recorded",
            "active": True,
            "session_id": "agent-test",
            "task_id": payload.get("task_id"),
            "job_id": payload.get("job_id"),
            "product_id": payload.get("product_id"),
            "browser_visible": False,
            "current_url": payload.get("page_url") or "about:blank",
            "last_step_code": payload.get("step_code") or payload.get("state"),
            "last_step_name": payload.get("label") or payload.get("action"),
            "hud": {
                "title": payload.get("label") or payload.get("action"),
                "state": payload.get("step_code") or payload.get("state"),
                "action": payload.get("action"),
                "next_step": None,
                "store_name": payload.get("store_name"),
                "guard": "只保存不发布",
            },
            "action_events": [payload],
            "screenshot": payload.get("screenshot_url"),
            "updated_at": "2026-05-22T00:00:01+00:00",
            "last_error": None,
        }


@pytest.fixture()
def v1_db(tmp_path, monkeypatch):
    db_path = tmp_path / "v1-runner.db"
    screenshot_dir = tmp_path / "screenshots"
    screenshot_dir.mkdir()
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(repository_module, "SCREENSHOT_DIR", screenshot_dir)
    monkeypatch.setattr(v1_runner_module, "SCREENSHOT_DIR", screenshot_dir)
    db.init_db()
    return db_path


def _create_task(
    repo: Repository,
    mode: str = "single_save",
    product_count: int = 1,
    manual_approval: bool = True,
):
    store = repo.create_store("Dang Kang", "AliExpress")
    dxm_reference_templates = {
        "attribute_info": {"names": ["立牌类谷子"]},
        "description": {"names": ["详情模板"]},
        "freight": {"names": ["40g普货包裹"]},
        "service": {"names": ["Service Template for New Sellers"]},
        "eu_responsible": {"names": ["Jacqueiline Marti"]},
        "manufacturer": {"names": ["jiyang county thunder"]},
        "compliance": {"names": ["合规模板"]},
        "semi_managed": {"names": ["半托管模板"]},
    }
    template_payloads = {
        "category": {
            "category_name": "模板类目",
            "dxm_reference_templates": dxm_reference_templates,
            "category": {
                "template_category_id": "tmpl-cat",
            },
        },
        "sku": {"stock": "100", "sku": {"template_sku_rule": "tmpl-sku"}},
        "pricing": {"price": "9.99", "pricing": {"currency": "USD"}},
        "logistics": {
            "weight": "0.03",
            "logistics": {
                "length": "10",
                "width": "10",
                "height": "2",
            },
        },
        "image": {
            "image": {
                "eu_outer_package_filename": "template-eu.jpg",
                "marketing_images_strategy": "generate",
            },
        },
        "compliance": {"compliance": {"material": "PVC"}},
        "semi_managed": {
            "semi_managed": {
                "supply_price": "4.20",
                "jit_stock": "100",
                "is_original_box": "否",
                "length": "10",
                "width": "10",
                "height": "2",
                "goods_code_strategy": "allow_blank",
                "barcode_strategy": "allow_blank",
            },
        },
    }
    for template_type, template_payload in template_payloads.items():
        repo.create_template(
            {
                "template_type": template_type,
                "template_name": f"{template_type} template",
                "binding_scope": "V1",
                "payload": template_payload,
                "is_enabled": True,
            }
        )
    product_ids = []
    for idx in range(product_count):
        source_url = f"https://detail.1688.com/offer/test-{idx + 1}.html"
        claim_task = None
        if mode == "single_save":
            claim_task = repo.create_acquisition_claim_request(
                {
                    "store_id": store["id"],
                    "source_url": source_url,
                    "keyword": f"ACG Stand Product {idx + 1}",
                    "category_name": "立牌类谷子",
                    "claim_mark": "AI认领",
                    "template_id": None,
                }
            )
        product_data = {
                "title": f"ACG Stand Product {idx + 1}",
                "source": "dxm_data_acquisition" if mode == "single_save" else "test",
                "status": "claimed_to_draft" if mode == "single_save" else "draft",
                "category_name": "立牌类谷子",
                "price": 7.01,
                "currency": "USD",
                "sku_count": 8,
                "image_count": 8,
                "payload": {
                    "source": "dxm_data_acquisition" if mode == "single_save" else "test",
                    "source_title": f"ACG Stand Product {idx + 1}",
                    "source_url": source_url,
                    "source_urls": [source_url],
                    "claim_task_id": claim_task["id"] if claim_task else None,
                    "draft_box_verified": mode == "single_save",
                    "store_name": "Dang Kang",
                    "category": {"template_category_id": f"product-cat-{idx + 1}"},
                    "image": {"eu_outer_package_filename": f"product-eu-{idx + 1}.jpg"},
                    "compliance": {"battery": "none"},
                },
            }
        if claim_task:
            claim_job = repo.get_task_private(claim_task["id"])["jobs"][0]
            repo.update_task_status(claim_task["id"], "running")
            repo.update_job(claim_job["id"], status="running")
            target_identity = canonical_claim_target_identity(
                source_url,
                [source_url],
                keyword=f"ACG Stand Product {idx + 1}",
                category_name="立牌类谷子",
            )
            source_identity = canonical_source_identity(source_url, [source_url])
            product = repo.create_claimed_product_and_complete_acquisition(
                claim_task["id"],
                product_data,
                draft_box_observation={
                    "schema": "dxm.draft_box.observation.v1",
                    "verification_state": "VERIFY_DRAFT_BOX_CLAIM",
                    "action": "verify_draft_box_claim",
                    "draft_box_verified": True,
                    "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
                    "authorized_target_identity": target_identity,
                    "authorized_target_fingerprint": target_identity["fingerprint"],
                    "observed_source_identity": source_identity,
                    "observed_store_identity": {
                        "store_id": store["id"],
                        "store_name": "Dang Kang",
                        "selected": True,
                        "selected_store_names": ["Dang Kang"],
                        "selection_evidence": {"input_checked": True},
                        "draft_box_cell_evidence": {
                            "store_name": "Dang Kang",
                            "cell_text": "「Dang Kang」",
                            "source": "structured_store_cell",
                        },
                    },
                    "matched_by": ["source_url"],
                    "match_evidence": {"source_url": source_identity["primary_url"]},
                    "observed_product_identity": f"ACG Stand Product {idx + 1}",
                    "observed_row_identity": f"商品箱行 ACG Stand Product {idx + 1} 立牌类谷子 Dang Kang",
                    "evidence_ref": _evidence_ref(f"v1-claim-{claim_task['id']}.png"),
                },
            ).product
        else:
            product = repo.create_product(product_data)
        product_ids.append(product["id"])
    task = repo.create_task(
        {
            "name": "V1 半托管保存任务",
            "store_id": store["id"],
            "mode": mode,
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "claim_mark": "AI认领",
            "product_ids": product_ids,
            "payload": {
                "store_name": "Dang Kang",
                "category_name": "任务类目",
                "template_overrides": {"logistics": {"weight": "0.05"}},
                "image": {"alt_text": "任务图片说明"},
                "compliance": {"material": "ABS"},
                "semi_managed": {"supply_price": "5.60"},
            },
        }
    )
    if mode in {"single_save", "batch_save"} and manual_approval:
        return repo.set_task_manual_approval(task["id"], approved=True, token="runner-approval-token", approved_by="ops-owner")
    return task


def test_single_save_generates_success_report_and_never_publishes(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job_id = repo.get_task(task["id"])["jobs"][0]["id"]
    manager = DummyManager()

    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "completed"
    assert len(reports) == 1
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["msg"] == "真实保存成功"
    assert reports[0]["summary"]["claim_mark"] == f"AI认领-{task['id']}-{job_id}"
    assert "semi_goods" in reports[0]["summary"]["filled_fields"]


def test_single_save_late_success_cannot_override_manual_review_after_save_authorization(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()

    class ManualReviewDuringSaveAdapter(FakeWorkflowAdapter):
        def save_only(self, defaults=None, product_query=None, store_name=None):
            repo.update_task_status(task["id"], "needs_manual_review")
            return super().save_only(defaults, product_query, store_name)

    asyncio.run(
        _test_runner(
            repo,
            manager,
            workflow_adapter=ManualReviewDuringSaveAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "needs_manual_review"
    assert refreshed["jobs"][0]["status"] == "running"
    assert repo.list_reports(task["id"]) == []
    assert not any(payload.get("type") == "job_completed" for _, payload in manager.events)
    assert not any(
        payload.get("type") == "task_status" and payload.get("status") in {"completed", "partial_success"}
        for _, payload in manager.events
    )


def test_create_task_preserves_payload_overrides(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    assert task["payload"]["store_name"] == "Dang Kang"
    assert task["payload"]["category_name"] == "任务类目"
    assert task["payload"]["template_overrides"]["logistics"]["weight"] == "0.05"
    assert task["payload"]["image"]["alt_text"] == "任务图片说明"
    assert task["payload"]["compliance"]["material"] == "ABS"
    assert task["payload"]["semi_managed"]["supply_price"] == "5.60"


def test_single_save_calls_workflow_adapter_in_complete_save_order(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job_id = repo.get_task(task["id"])["jobs"][0]["id"]
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == [
        ("check_login_state",),
        ("open_draft_box",),
        ("open_editor", "ACG Stand Product 1", "Dang Kang", f"AI认领-{task['id']}-{job_id}", ["https://detail.1688.com/offer/test-1.html"]),
        ("verify_edit_ownership", "ACG Stand Product 1", "Dang Kang", ["https://detail.1688.com/offer/test-1.html"]),
        ("fill_editor_required_defaults", adapter.calls[4][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_editor_variants", adapter.calls[5][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_media_assets", adapter.calls[6][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_compliance_defaults", adapter.calls[7][1], "ACG Stand Product 1", "Dang Kang"),
        ("enable_semi_managed", "ACG Stand Product 1", "Dang Kang"),
        ("open_semi_managed_page", adapter.calls[9][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_semi_managed_defaults", adapter.calls[10][1], "ACG Stand Product 1", "Dang Kang"),
        ("fill_semi_managed_defaults", adapter.calls[11][1], "ACG Stand Product 1", "Dang Kang"),
        ("save_only", adapter.calls[12][1], "ACG Stand Product 1", "Dang Kang"),
        ("verify_not_published", "ACG Stand Product 1", "Dang Kang"),
    ]
    defaults = adapter.calls[4][1]
    assert defaults["category_name"] == "任务类目"
    assert defaults["category"]["template_category_id"] == "tmpl-cat"
    assert defaults["logistics"]["weight"] == "0.05"
    assert defaults["image"]["eu_outer_package_filename"] == "template-eu.jpg"
    assert defaults["image"]["alt_text"] == "任务图片说明"
    assert defaults["compliance"]["material"] == "PVC"
    assert defaults["compliance"]["battery"] == "none"
    assert defaults["semi_managed"]["supply_price"] == "4.20"
    assert adapter.calls[9][1] == defaults
    reports = repo.list_reports(task["id"])
    assert reports[0]["published"] is False
    assert reports[0]["summary"]["workflow_actions"] == [
        "check_login_state",
        "open_draft_box",
        "open_editor",
        "verify_edit_ownership",
        "fill_editor_required_defaults",
        "fill_editor_variants",
        "fill_media_assets",
        "fill_compliance_defaults",
        "enable_semi_managed",
        "open_semi_managed_page",
        "fill_semi_managed_defaults",
        "fill_semi_managed_defaults",
        "save_only",
        "verify_not_published",
    ]
    assert reports[0]["summary"]["workflow_results"][-1]["product_query"] == "ACG Stand Product 1"
    assert reports[0]["summary"]["workflow_results"][-1]["store_name"] == "Dang Kang"
    assert reports[0]["summary"]["category"] == "立牌类谷子"
    assert reports[0]["summary"]["template_trace"]
    assert "_template_trace" not in reports[0]["summary"]["resolved_defaults"]


def test_single_save_fill_actions_use_manually_selected_template_over_store_default(v1_db):
    repo = Repository()
    store_template = repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "Dang Kang 店铺包装模板",
            "binding_scope": "Dang Kang",
            "payload": {
                "binding": {"store_name": "Dang Kang", "category_name": "立牌类谷子", "platform": "AliExpress"},
                "logistics": {"weight": "0.03", "length": "10", "width": "10", "height": "2"},
            },
            "is_enabled": True,
        }
    )
    selected_template = repo.create_template(
        {
            "template_type": "logistics",
            "template_name": "本次选择包装模板",
            "binding_scope": "手动选择",
            "payload": {
                "binding": {"store_name": "Other Store", "category_name": "Other Category", "platform": "AliExpress"},
                "logistics": {"weight": "0.09", "length": "18", "width": "12", "height": "4"},
            },
            "is_enabled": True,
        }
    )
    task = _create_task(repo, mode="single_save", product_count=1)
    payload = dict(task["payload"])
    payload["template_id"] = selected_template["id"]
    payload.pop("template_overrides", None)
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (db.dumps(payload), task["id"]),
        )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    fill_defaults = next(call[1] for call in adapter.calls if call[0] == "fill_editor_required_defaults")
    assert fill_defaults["logistics"]["weight"] == "0.09"
    assert fill_defaults["logistics"]["length"] == "18"
    assert fill_defaults["logistics"]["width"] == "12"
    assert fill_defaults["logistics"]["height"] == "4"
    fill_action_defaults = [
        call[1]
        for call in adapter.calls
        if call[0]
        in {
            "fill_editor_required_defaults",
            "fill_editor_variants",
            "fill_media_assets",
            "fill_compliance_defaults",
            "open_semi_managed_page",
            "fill_semi_managed_defaults",
            "save_only",
        }
    ]
    assert fill_action_defaults
    assert all(defaults["logistics"]["weight"] == "0.09" for defaults in fill_action_defaults)
    reports = repo.list_reports(task["id"])
    trace_names = [item["template_name"] for item in reports[0]["summary"]["template_trace"]]
    assert trace_names.index(store_template["template_name"]) < trace_names.index(selected_template["template_name"])


def test_single_save_syncs_agent_console_hud_without_changing_workflow_order(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()
    console = FakeAgentConsole()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    states = [call["step_code"] for call in console.calls]
    assert "PRECHECK_CONFIG" in states
    assert "PRECHECK_PUBLISH_GUARD" in states
    assert "SELECT_CATEGORY" in states
    assert "SAVE_ONLY" in states
    assert "VERIFY_NOT_PUBLISHED" in states
    assert "WRITE_REPORT" in states
    assert "RELEASE_LOCK" in states
    precheck_config = next(call for call in console.calls if call["step_code"] == "PRECHECK_CONFIG")
    open_draft = next(call for call in console.calls if call["step_code"] == "OPEN_DRAFT_LIST")
    find_product = next(call for call in console.calls if call["step_code"] == "FIND_PRODUCT")
    open_editor = next(call for call in console.calls if call["step_code"] == "OPEN_EDIT_PAGE")
    base_info = next(call for call in console.calls if call["step_code"] == "FILL_BASE_INFO")
    variants = next(call for call in console.calls if call["step_code"] == "FILL_VARIANTS")
    media = next(call for call in console.calls if call["step_code"] == "FILL_MEDIA")
    semi_goods = next(call for call in console.calls if call["step_code"] == "FILL_SEMI_GOODS")
    select_category = next(call for call in console.calls if call["step_code"] == "SELECT_CATEGORY")
    save_only = next(call for call in console.calls if call["step_code"] == "SAVE_ONLY")
    verify_not_published = next(call for call in console.calls if call["step_code"] == "VERIFY_NOT_PUBLISHED")
    release_lock = next(call for call in console.calls if call["step_code"] == "RELEASE_LOCK")
    assert precheck_config["human_title"] == "开始任务"
    assert precheck_config["phase"] == "准备执行"
    assert open_draft["human_title"] == "正在打开商品箱"
    assert open_draft["human_action"] == "进入店小秘商品箱"
    assert find_product["human_title"] == "正在定位商品"
    assert open_editor["human_title"] == "正在打开编辑页"
    assert base_info["human_title"] == "正在编辑商品"
    assert base_info["human_action"] == "正在填写标题"
    assert base_info["human_next"] == "继续填写价格、图片和物流信息"
    assert select_category["human_title"] == "正在选择分类"
    assert select_category["human_action"] == "确认商品分类和属性"
    assert select_category["progress_index"] == 6
    assert select_category["progress_total"] == 12
    assert variants["human_action"] == "正在填写价格、库存和 SKU"
    assert media["human_action"] == "正在处理图片"
    assert semi_goods["human_title"] == "正在设置包装物流"
    assert save_only["human_title"] == "正在只保存"
    assert save_only["human_action"] == "只点击保存，不发布"
    assert verify_not_published["human_title"] == "正在检查结果"
    assert verify_not_published["human_action"] == "确认商品没有发布"
    assert release_lock["human_title"] == "任务完成"
    assert release_lock["progress_index"] == 12
    assert release_lock["progress_total"] == 12
    operator_phrases = [
        "开始任务",
        "进入店小秘商品箱",
        "查找本次要编辑保存的商品",
        "进入商品编辑页",
        "正在填写标题",
        "确认商品分类和属性",
        "正在填写价格、库存和 SKU",
        "正在处理图片",
        "填写重量、尺寸和物流信息",
        "只点击保存，不发布",
        "确认商品没有发布",
        "任务完成",
    ]
    hud_text = "\n".join(
        str(call.get(key) or "")
        for call in console.calls
        for key in ("phase", "human_title", "human_action", "human_next")
    )
    for phrase in operator_phrases:
        assert phrase in hud_text
    assert all(call["progress_total"] == 12 for call in console.calls if call.get("progress_total"))
    compact_progress = []
    for call in console.calls:
        progress = call.get("progress_index")
        if not progress or progress == (compact_progress[-1] if compact_progress else None):
            continue
        compact_progress.append(progress)
    assert compact_progress == list(range(1, 13))
    assert all(call["severity"] == "running" for call in console.calls)
    assert all(call["requires_user_action"] is False for call in console.calls)
    assert all(call["store_name"] == "Dang Kang" for call in console.calls)
    assert console.start_calls == []
    assert [call["action"] for call in console.action_calls] == [call[0] for call in adapter.calls]
    assert next(call for call in console.action_calls if call["action"] == "fill_editor_required_defaults")["type"] == "fill"
    assert next(call for call in console.action_calls if call["action"] == "fill_media_assets")["type"] == "upload"
    save_action = next(call for call in console.action_calls if call["action"] == "save_only")
    assert save_action["type"] == "save"
    assert save_action["save_result"]["published"] is False
    assert [call[0] for call in adapter.calls].count("save_only") == 1
    assert [call[0] for call in adapter.calls].index("save_only") < [call[0] for call in adapter.calls].index("verify_not_published")

    report = repo.list_reports(task["id"])[0]
    assert report["published"] is False
    assert report["save_result"]["published"] is False
    assert report["summary"]["agent_console"]["session_id"] == "agent-test"
    assert report["summary"]["agent_console"]["hud"]["guard"] == "只保存不发布"
    assert report["summary"]["agent_console"]["last_step_code"] == "RELEASE_LOCK"
    assert report["summary"]["agent_action_events"][-1]["action"] == "verify_not_published"
    assert any(event["action"] == "save_only" and event["type"] == "save" for event in report["summary"]["agent_action_events"])
    assert any(
        evidence["meta"].get("agent_console", {}).get("hud", {}).get("guard") == "只保存不发布"
        for evidence in repo.list_evidences(task["id"])
    )
    assert any(
        evidence["evidence_type"] == "workflow_action"
        and evidence["meta"].get("agent_action", {}).get("action") == "save_only"
        for evidence in repo.list_evidences(task["id"])
    )


def test_single_save_updates_live_browser_hud_without_agent_console(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    states = [call["step_code"] for call in adapter.live_hud_calls]
    assert "PRECHECK_CONFIG" in states
    assert "FILL_BASE_INFO" in states
    assert "SELECT_CATEGORY" in states
    assert "SAVE_ONLY" in states
    assert "VERIFY_NOT_PUBLISHED" in states
    select_category = next(call for call in adapter.live_hud_calls if call["step_code"] == "SELECT_CATEGORY")
    assert select_category["human_title"] == "正在选择分类"
    assert select_category["human_action"] == "确认商品分类和属性"
    assert select_category["progress_index"] == 6
    assert select_category["progress_total"] == 12
    save_only = next(call for call in adapter.live_hud_calls if call["step_code"] == "SAVE_ONLY")
    assert save_only["human_title"] == "正在只保存"
    assert save_only["human_action"] == "只点击保存，不发布"
    assert save_only["progress_total"] == 12
    assert save_only["store_name"] == "Dang Kang"
    assert save_only["requires_user_action"] is False

    report = repo.list_reports(task["id"])[0]
    assert report["summary"]["agent_console_events"] == []
    assert report["summary"]["agent_console"] is None
    assert report["summary"]["live_browser_hud_events"]
    assert report["summary"]["live_browser_hud"]["last_step_code"] == "RELEASE_LOCK"
    assert report["summary"]["live_browser_hud"]["hud"]["guard"] == "只保存不发布"
    assert any(
        evidence["meta"].get("live_browser_hud", {}).get("hud", {}).get("human_title") == "正在只保存"
        for evidence in repo.list_evidences(task["id"])
    )


def test_single_save_persists_save_and_unpublished_evidence_refs_in_workflow_meta(v1_db):
    class EvidenceWorkflowAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action in {"save_only", "verify_not_published"}:
                evidence_ref = _evidence_ref(f"{action}-proof.png")
                result["evidence"]["refs"] = [
                    {
                        **evidence_ref,
                        "kind": (
                            "save_screenshot"
                            if action == "save_only"
                            else "unpublished_screenshot"
                        ),
                        "captured_at": (
                            "2026-05-22T00:00:01+00:00"
                            if action == "save_only"
                            else "2026-05-22T00:00:02+00:00"
                        ),
                    }
                ]
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(_test_runner(repo, DummyManager(), workflow_adapter=EvidenceWorkflowAdapter()).run_task(task["id"]))

    workflow_evidence = {
        evidence["meta"].get("state"): evidence
        for evidence in repo.list_evidences(task["id"])
        if evidence["evidence_type"] == "workflow_action"
    }
    for state in {"SAVE_ONLY", "VERIFY_NOT_PUBLISHED"}:
        evidence = workflow_evidence[state]
        evidence_ref = evidence["meta"]["evidence_ref"]
        assert set(evidence_ref) == {"path", "sha256", "size"}
        assert evidence["file_path"] == evidence_ref["path"]


def test_agent_console_sync_failure_does_not_fail_save_flow(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()
    console = FakeAgentConsole(fail=True)

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    report = repo.list_reports(task["id"])[0]
    assert refreshed["status"] == "completed"
    assert report["status"] == "success"
    assert report["published"] is False
    assert report["summary"]["agent_console"]["reason"] == "agent_console_exception"
    assert "console unavailable" in report["summary"]["agent_console"]["last_error"]


def test_execution_defaults_task_payload_overrides_stale_product_media_slots(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product = repo.list_products()[0]
    product["payload"]["image"]["slots"] = [
        {"slot_key": "marketing_scene_3_4", "strategy": "generate", "label": "(3:4场景图)"},
        {"slot_key": "eu_outer_package", "filename": "product-eu-1.jpg", "label": "外包装/标签实拍图-欧盟"},
    ]
    task["payload"]["image"]["slots"] = [
        {"slot_key": "marketing_scene_3_4", "strategy": "generate", "label": "(3:4场景图)", "filename": "scene-750x1000.jpg"},
        {"slot_key": "eu_outer_package", "filename": "task-eu.jpg", "label": "外包装/标签实拍图-欧盟"},
    ]

    defaults = _test_runner(repo, DummyManager())._execution_defaults(task, product)

    assert defaults["image"]["slots"][0]["filename"] == "scene-750x1000.jpg"
    assert defaults["image"]["slots"][1]["filename"] == "task-eu.jpg"


def test_execution_defaults_only_applies_matching_template_bindings():
    class TemplateRepo:
        def list_templates(self):
            return [
                {
                    "id": 1,
                    "template_type": "category",
                    "template_name": "Other category",
                    "binding_scope": "store/category",
                    "payload": {
                        "binding": {"store_name": "Other Store", "category_name": "运动鞋"},
                        "category": {"category_match": "Shoes"},
                    },
                    "is_enabled": True,
                },
                {
                    "id": 2,
                    "template_type": "category",
                    "template_name": "ACG Stand",
                    "binding_scope": "store/category",
                    "payload": {
                        "binding": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
                        "category": {
                            "category_keyword": "立牌",
                            "category_match": "ACG Stand",
                            "attribute_template_priorities": ["立牌类谷子"],
                        },
                    },
                    "is_enabled": True,
                },
            ]

    runner = _test_runner(TemplateRepo(), DummyManager())
    defaults = runner._execution_defaults(
        {"payload": {"store_name": "Dang Kang"}},
        {"category_name": "立牌类谷子", "payload": {}},
    )

    assert defaults["category"]["category_match"] == "ACG Stand"
    assert defaults["category"]["attribute_template_priorities"] == ["立牌类谷子"]
    assert defaults["dxm_reference_templates_resolved"]["attribute_info"] == {
        "names": ["立牌类谷子"],
        "required": True,
    }
    assert defaults["_template_trace"] == [
        {
            "template_id": 2,
            "template_type": "category",
            "template_name": "ACG Stand",
            "binding_scope": "store/category",
        }
    ]


def test_execution_defaults_resolves_new_dxm_reference_templates():
    class TemplateRepo:
        def list_templates(self):
            return [
                {
                    "id": 1,
                    "template_type": "dxm_reference",
                    "template_name": "Dxm Reference",
                    "binding_scope": "V1",
                    "payload": {
                        "dxm_reference_templates": {
                            "freight": {"names": ["40g普货包裹"]},
                            "service": {"names": [], "required": False},
                        },
                        "logistics": {
                            "freight_template_priorities": ["旧运费模板"],
                            "service_template_priorities": ["旧服务模板"],
                        },
                    },
                    "is_enabled": True,
                },
            ]

    runner = _test_runner(TemplateRepo(), DummyManager())
    defaults = runner._execution_defaults({"payload": {}}, {"payload": {}})

    assert defaults["dxm_reference_templates_resolved"]["freight"] == {"names": ["40g普货包裹"], "required": True}
    assert defaults["dxm_reference_templates_resolved"]["service"] == {"names": [], "required": False}
    assert defaults["dxm_reference_templates_resolved"]["attribute_info"] == {"names": [], "required": True}


def test_single_save_missing_required_dxm_reference_template_fails_before_save(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    with db.connection() as conn:
        conn.execute(
            "UPDATE templates SET payload_json=? WHERE template_type='category'",
            (
                db.dumps(
                    {
                        "category_name": "模板类目",
                        "dxm_reference_templates": {
                            "attribute_info": {"names": ["立牌类谷子"]},
                            "description": {"names": ["详情模板"]},
                            "freight": {"names": [], "required": True},
                            "service": {"names": ["Service Template for New Sellers"]},
                            "eu_responsible": {"names": ["Jacqueiline Marti"]},
                            "manufacturer": {"names": ["jiyang county thunder"]},
                            "compliance": {"names": ["合规模板"]},
                            "semi_managed": {"names": ["半托管模板"]},
                        },
                        "category": {
                            "template_category_id": "tmpl-cat",
                        },
                    }
                ),
            ),
        )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "dxm_reference_templates.freight" in reports[0]["summary"]["blocked_reason"]
    assert "save_only" not in [call[0] for call in adapter.calls]


def test_single_save_report_includes_resolved_dxm_reference_templates(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    with db.connection() as conn:
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (
                db.dumps(
                    {
                        **task["payload"],
                        "dxm_reference_templates": {
                            "freight": {"names": ["40g普货包裹"], "required": True},
                            "description": {"names": [], "required": False},
                        },
                    }
                ),
                task["id"],
            ),
        )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    resolved = reports[0]["summary"]["dxm_reference_templates_resolved"]
    assert resolved["description"] == {"names": ["详情模板"], "required": False}
    assert resolved["freight"] == {"names": ["40g普货包裹"], "required": True}
    reference_results = reports[0]["summary"]["dxm_reference_template_results"]
    assert set(reference_results) == {
        "attribute_info",
        "description",
        "freight",
        "service",
        "eu_responsible",
        "manufacturer",
        "compliance",
        "semi_managed",
    }
    assert reference_results["description"] == {"ok": True, "section": "description", "names": ["详情模板"], "required": False}
    assert reference_results["freight"] == {"ok": True, "section": "freight", "names": ["40g普货包裹"], "required": True}


def test_claim_only_calls_adapter_without_opening_editor_or_saving(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == [
        ("check_login_state",),
        ("open_data_acquisition",),
        (
            "claim_from_data_acquisition",
            f"AI认领-{task['id']}",
            "Hazbin Hotel 立牌",
            "立牌类谷子",
            "Dang Kang",
            ["https://detail.1688.com/offer/from-acquisition.html"],
        ),
        (
            "verify_draft_box_claim",
            f"AI认领-{task['id']}",
            "Hazbin Hotel 立牌",
            "立牌类谷子",
            "Dang Kang",
            ["https://detail.1688.com/offer/from-acquisition.html"],
        ),
    ]
    assert not any(call[0] in {"open_editor", "save_only"} for call in adapter.calls)
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["message"] == "待认领入箱已完成，商品已进入商品箱"
    products = repo.list_products()
    claimed = [product for product in products if product["status"] == "claimed_to_draft"]
    assert len(claimed) == 1
    assert claimed[0]["title"] == "Hazbin Hotel 立牌"
    assert claimed[0]["source"] == "dxm_data_acquisition"
    assert claimed[0]["payload"]["store_id"] == store["id"]
    assert claimed[0]["payload"]["store_name"] == "Dang Kang"
    assert claimed[0]["payload"]["claim_task_id"] == task["id"]
    assert claimed[0]["payload"]["claim_mark"] == f"AI认领-{task['id']}"
    assert claimed[0]["payload"]["source_url"] == "https://detail.1688.com/offer/from-acquisition.html"
    assert claimed[0]["payload"]["source_urls"] == ["https://detail.1688.com/offer/from-acquisition.html"]
    assert claimed[0]["payload"]["data_acquisition_match"] == "source_url"
    assert "待认领商品行" in claimed[0]["payload"]["data_acquisition_row_text"]
    assert "采集箱商品行" in claimed[0]["payload"]["draft_box_row_text"]
    assert claimed[0]["payload"]["acquisition_search"]["query_source"] == "target_source_url"
    assert reports[0]["product_id"] == claimed[0]["id"]
    assert reports[0]["save_result"]["claimed_product_id"] == claimed[0]["id"]
    assert reports[0]["summary"]["claimed_product"]["id"] == claimed[0]["id"]
    assert "商品箱编辑保存" in reports[0]["summary"]["next_action"]

    refreshed_task = repo.get_task_private(task["id"])
    assert refreshed_task["payload"]["stage"] == "claimed_to_draft"
    assert refreshed_task["payload"]["status"] == "completed"
    assert refreshed_task["payload"]["claimed_product_id"] == claimed[0]["id"]
    assert refreshed_task["payload"]["claimed_product_source_url"] == "https://detail.1688.com/offer/from-acquisition.html"
    assert refreshed_task["payload"]["claimed_product_category_name"] == "立牌类谷子"
    assert refreshed_task["payload"]["draft_box_verified"] is True
    assert "商品箱编辑保存" in refreshed_task["payload"]["next_step"]


def test_claim_only_rejects_store_proof_without_exact_selected_store_names(v1_db):
    class MissingSelectedStoreNamesAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "verify_draft_box_claim":
                _test_action_observations(result)["draft_box_match"]["store_observation"].pop(
                    "selected_store_names",
                    None,
                )
            return result

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=MissingSelectedStoreNamesAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E202"
    assert repo.list_claimed_draft_products() == []
    assert repo.list_products(include_fixtures=True) == []


def test_claim_only_rejects_store_proof_without_structured_store_cell(v1_db):
    class MissingStoreCellAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "verify_draft_box_claim":
                _test_action_observations(result)["draft_box_match"]["store_observation"].pop(
                    "draft_box_cell_evidence",
                    None,
                )
            return result

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=MissingStoreCellAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E202"
    assert repo.list_claimed_draft_products() == []
    assert repo.list_products(include_fixtures=True) == []


@pytest.mark.parametrize(
    "invalid_store_proof",
    [
        "multiple_selected_stores",
        "selected_store_names_string",
        "selection_evidence_string",
        "store_cell_string",
        "top_level_store_evidence_string",
        "wrong_cell_source",
        "wrong_cell_store",
        "wrong_cell_text_boundary",
        "top_level_observation_mismatch",
    ],
)
def test_claim_only_rejects_malformed_or_inconsistent_store_proof(
    v1_db,
    invalid_store_proof,
):
    class InvalidStoreProofAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action != "verify_draft_box_claim":
                return result
            draft_box_match = _test_action_observations(result)["draft_box_match"]
            observation = draft_box_match["store_observation"]
            cell = observation["draft_box_cell_evidence"]
            if invalid_store_proof == "multiple_selected_stores":
                observation["selected_store_names"] = ["Dang Kang", "Another Store"]
            elif invalid_store_proof == "selected_store_names_string":
                observation["selected_store_names"] = "Dang Kang"
            elif invalid_store_proof == "selection_evidence_string":
                observation["selection_evidence"] = "input_checked=true"
            elif invalid_store_proof == "store_cell_string":
                observation["draft_box_cell_evidence"] = "Dang Kang"
            elif invalid_store_proof == "top_level_store_evidence_string":
                draft_box_match["store_evidence"] = draft_box_match["row_text"]
            elif invalid_store_proof == "wrong_cell_source":
                cell["source"] = "draft_box_row_text"
                draft_box_match["store_evidence"] = dict(cell)
            elif invalid_store_proof == "wrong_cell_store":
                cell["store_name"] = "Another Store"
                draft_box_match["store_evidence"] = dict(cell)
            elif invalid_store_proof == "wrong_cell_text_boundary":
                cell["cell_text"] = "Dang KangPlus"
                draft_box_match["store_evidence"] = dict(cell)
            elif invalid_store_proof == "top_level_observation_mismatch":
                draft_box_match["store_evidence"] = {**cell, "cell_text": "Another Store"}
            return result

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=InvalidStoreProofAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E202"
    assert repo.list_claimed_draft_products() == []
    assert repo.list_products(include_fixtures=True) == []


def test_claim_only_missing_authorization_verifier_fails_before_first_mutation(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "keyword": "Hazbin Hotel 立牌",
            "category_name": "立牌类谷子",
            "source_url": "https://detail.1688.com/offer/from-acquisition.html",
            "claim_mark": "AI认领",
            "template_id": "template-1",
        }
    )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(V1TaskRunner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert [call[0] for call in adapter.calls] == ["check_login_state", "open_data_acquisition"]
    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert report["save_result"]["error_code"] == "AUTH_VERIFIER_MISSING"


@pytest.mark.parametrize("invalid_result", [None, True, "unexpected"])
def test_real_mutation_authorizer_malformed_result_fails_closed(v1_db, invalid_result):
    runner = V1TaskRunner(
        Repository(),
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        authorization_verifier=lambda *_args: invalid_result,
    )

    with pytest.raises(V1ExecutionError) as exc_info:
        runner._assert_real_mutation_authorized(1, "single_save", StateName.SAVE_ONLY)

    assert exc_info.value.error_code == "AUTH_REVALIDATION_FAILED"


def test_claim_only_revalidates_consumed_lease_immediately_before_first_mutation(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request(
        {
            "store_id": store["id"],
            "keyword": "Hazbin Hotel 立牌",
            "category_name": "立牌类谷子",
            "source_url": "https://detail.1688.com/offer/from-acquisition.html",
            "claim_mark": "AI认领",
            "template_id": "template-1",
        }
    )
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()
    verifier_calls = []

    def reject_drift(task_id, mode, state):
        verifier_calls.append((task_id, mode, state))
        return {"ok": False, "reason_code": "AUTH_CONTEXT_MISMATCH"}

    asyncio.run(
        _test_runner(
            repo,
            manager,
            workflow_adapter=adapter,
            authorization_verifier=reject_drift,
        ).run_task(task["id"])
    )

    assert verifier_calls == [(task["id"], "claim_only", "CLAIM_TO_DRAFT_BOX")]
    assert [call[0] for call in adapter.calls] == ["check_login_state", "open_data_acquisition"]
    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert report["save_result"]["error_code"] == "AUTH_CONTEXT_MISMATCH"


def test_single_save_revalidates_consumed_lease_immediately_before_save_mutation(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    adapter = FakeWorkflowAdapter()
    verifier_calls = []

    def reject_drift(task_id, mode, state):
        verifier_calls.append((task_id, mode, state))
        return {"ok": False, "reason_code": "AUTH_LEASE_EXPIRED"}

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=adapter,
            authorization_verifier=reject_drift,
        ).run_task(task["id"])
    )

    assert verifier_calls == [(task["id"], "single_save", "SAVE_ONLY")]
    assert "save_only" not in [call[0] for call in adapter.calls]
    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert report["save_result"]["error_code"] == "AUTH_LEASE_EXPIRED"


def test_claim_only_failure_uses_operator_chinese_detail(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(fail_action="claim_from_data_acquisition")

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    detail = report["save_result"]["message"]
    blocked_reason = report["summary"]["blocked_reason"]
    refreshed_task = repo.get_task_private(task["id"])
    job_error = refreshed_task["jobs"][0]["error_message"]
    exception = repo.list_exceptions()[0]

    for value in [detail, blocked_reason, job_error, exception["detail"]]:
        assert "待认领入箱" in value or "已有待认领" in value
        assert "不会保存或发布" in value
        assert "claim_from_data_acquisition" not in value
        assert "dianxiaomi.com" not in value


def test_claim_only_browser_action_timeout_fails_task_instead_of_staying_running(v1_db):
    class HangingWorkflowAdapter(FakeWorkflowAdapter):
        def open_data_acquisition(self):
            time.sleep(0.2)
            return super().open_data_acquisition()

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = HangingWorkflowAdapter()

    asyncio.run(
        _test_runner(
            repo,
            manager,
            workflow_adapter=adapter,
            workflow_action_timeout_seconds=0.01,
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    report = repo.list_reports(task["id"])[0]
    exception = repo.list_exceptions()[0]

    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E901"
    assert "真实浏览器操作超时" in refreshed["jobs"][0]["error_message"]
    assert "重新打开执行浏览器" in refreshed["jobs"][0]["error_message"]
    assert report["save_result"]["ok"] is False
    assert "真实浏览器操作超时" in report["summary"]["blocked_reason"]
    assert exception["title"] == "真实浏览器操作超时"
    messages = [item["message"] for item in repo.list_logs(task["id"])]
    assert "真实浏览器动作开始：打开已有待认领列表" in messages
    assert "真实浏览器动作超时：打开已有待认领列表" in messages


def test_claim_only_browser_closed_error_is_operator_readable(v1_db):
    class ClosedBrowserWorkflowAdapter(FakeWorkflowAdapter):
        def open_data_acquisition(self):
            return {
                "ok": False,
                "action": "open_data_acquisition",
                "stage": "workflow_navigation_failed",
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "message": "进入业务页失败：Page.evaluate: Target page, context or browser has been closed",
            }

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = ClosedBrowserWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    detail = report["summary"]["blocked_reason"]
    job_error = repo.get_task_private(task["id"])["jobs"][0]["error_message"]

    for value in [detail, job_error]:
        assert "真实浏览器窗口已关闭或失去连接" in value
        assert "重新打开执行浏览器" in value
        assert "不会保存或发布" in value
        assert "Page.evaluate" not in value
        assert "Target page" not in value
    messages = [item["message"] for item in repo.list_logs(task["id"])]
    assert "真实浏览器动作开始：打开已有待认领列表" in messages
    assert "真实浏览器动作失败：打开已有待认领列表" in messages


def test_claim_only_does_not_record_claimed_product_without_source_url(v1_db):
    class MissingSourceUrlAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "verify_draft_box_claim":
                evidence = _test_action_observations(result)
                claimed_product = evidence.get("claimed_product") or {}
                claimed_product.pop("source_url", None)
                draft_box_match = evidence.get("draft_box_match") or {}
                draft_box_match["source_urls"] = []
            return result

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = MissingSourceUrlAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert repo.list_claimed_draft_products() == []
    assert repo.list_products(include_fixtures=True) == []


def test_claim_only_rejects_draft_box_source_outside_stage_a_authorized_url(v1_db):
    class WrongObservedSourceAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "verify_draft_box_claim":
                evidence = _test_action_observations(result)
                wrong_url = "https://detail.1688.com/offer/different-product.html"
                evidence["claimed_product"]["source_url"] = wrong_url
                evidence["draft_box_match"]["source_urls"] = [wrong_url]
                evidence["draft_box_match"]["matched_value"] = wrong_url
            return result

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })

    asyncio.run(_test_runner(repo, DummyManager(), workflow_adapter=WrongObservedSourceAdapter()).run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E202"
    assert repo.list_products(include_fixtures=True) == []


def test_claim_only_rejects_claim_mark_row_that_does_not_observe_authorized_hint(v1_db):
    class ClaimMarkOnlyAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "verify_draft_box_claim":
                evidence = _test_action_observations(result)
                row_text = "AI认领 已进入商品箱 Dang Kang"
                evidence["claimed_product"]["title"] = "无关商品"
                evidence["claimed_product"]["row_text"] = row_text
                evidence["draft_box_match"].update({
                    "matched_by": "keyword",
                    "matched_value": "Hazbin Hotel 立牌",
                    "raw_matched_by": "claim_mark",
                    "row_text": row_text,
                })
            return result

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })

    asyncio.run(_test_runner(repo, DummyManager(), workflow_adapter=ClaimMarkOnlyAdapter()).run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E202"
    assert repo.list_products(include_fixtures=True) == []


def test_claim_only_rejects_page_store_name_spoofed_against_authoritative_store_id(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "store_name": "Spoof Store",
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })

    asyncio.run(_test_runner(repo, DummyManager(), workflow_adapter=FakeWorkflowAdapter()).run_task(task["id"]))

    refreshed = repo.get_task_private(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E202"
    assert repo.list_products(include_fixtures=True) == []


def test_claim_click_revalidates_after_outer_guard_and_before_adapter_mutation(v1_db):
    class ClickAuthorizingAdapter(FakeWorkflowAdapter):
        def __init__(self):
            super().__init__()
            self.authorizer = None
            self.context = None
            self.clicked = False

        def set_mutation_authorizer(self, authorizer, context=None):
            self.authorizer = authorizer
            self.context = context

        def clear_mutation_authorizer(self):
            self.authorizer = None

        def claim_from_data_acquisition(self, *args, **kwargs):
            def click_operation():
                self.clicked = True
                return True

            result = self.authorizer(
                {**self.context, "mutation_action": "claim_confirm_click"},
                click_operation,
            )
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise RuntimeError(result.get("reason_code") if isinstance(result, dict) else "AUTH_REVALIDATION_FAILED")
            return super().claim_from_data_acquisition(*args, **kwargs)

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "store_name": store["name"],
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    adapter = ClickAuthorizingAdapter()
    checks = []

    def verifier(*_args):
        checks.append(_args)
        return (
            {"ok": True, "reason_code": "OK"}
            if len(checks) == 1
            else {"ok": False, "reason_code": "AUTH_LEASE_EXPIRED"}
        )

    asyncio.run(V1TaskRunner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        authorization_verifier=verifier,
    ).run_task(task["id"]))

    assert len(checks) == 2
    assert adapter.clicked is False
    assert repo.get_task_private(task["id"])["status"] == "failed"


def test_claim_only_keeps_source_url_as_match_hint_not_acquisition_query(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    source_url = "https://detail.1688.com/offer/from-acquisition.html"
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "source_url": source_url,
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls[2] == (
        "claim_from_data_acquisition",
        f"AI认领-{task['id']}",
        None,
        None,
        "Dang Kang",
        [source_url],
    )
    assert adapter.calls[3] == (
        "verify_draft_box_claim",
        f"AI认领-{task['id']}",
        None,
        None,
        "Dang Kang",
        [source_url],
    )


def test_single_save_fails_when_adapter_lacks_media_or_compliance_methods(v1_db):
    class LegacyWorkflowAdapter(FakeWorkflowAdapter):
        fill_media_assets = None
        fill_compliance_defaults = None

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = LegacyWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["save_result"]["ok"] is False
    assert "fill_media_assets adapter method unavailable" in reports[0]["save_result"]["message"]
    assert "fill_media_assets adapter method unavailable" in reports[0]["summary"]["blocked_reason"]
    assert "fill_compliance_defaults" not in reports[0]["summary"]["workflow_actions"]


def test_single_save_missing_eu_outer_package_image_config_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = repo.get_task(task["id"])["jobs"][0]["product_id"]
    with db.connection() as conn:
        conn.execute(
            "UPDATE products SET payload_json=? WHERE id=?",
            (db.dumps({"source_title": "ACG Stand Product 1", "compliance": {"battery": "none"}}), product_id),
        )
        conn.execute(
            "UPDATE templates SET payload_json=? WHERE template_type='image'",
            (db.dumps({"image": {"alt_text": "no eu image"}}),),
        )
        conn.execute(
            "UPDATE tasks SET payload_json=? WHERE id=?",
            (
                db.dumps({
                    **task["payload"],
                    "image": {"alt_text": "task no eu image"},
                }),
                task["id"],
            ),
        )

    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "eu_outer_package" in reports[0]["summary"]["blocked_reason"]


def test_workflow_adapter_failure_fails_job_and_writes_exception_and_report(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(fail_action="open_editor")

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    reports = repo.list_reports(task["id"])
    exceptions = repo.list_exceptions()
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is False
    assert "open_editor" in reports[0]["summary"]["blocked_reason"]
    assert exceptions[0]["error_code"] == "E901"
    assert any(
        payload.get("type") == "task_status" and payload.get("status") == "failed"
        for _, payload in manager.events
    )
    assert not any(payload.get("type") == "job_completed" for _, payload in manager.events)
    assert exceptions[0]["field_domain"] == "v1_executor"


@pytest.mark.parametrize("impostor_ok", ["true", 1])
def test_workflow_action_rejects_non_boolean_success_values(v1_db, impostor_ok):
    class ImpostorOkAdapter(FakeWorkflowAdapter):
        def open_draft_box(self):
            result = super().open_draft_box()
            result["ok"] = impostor_ok
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=ImpostorOkAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E201"
    assert [report for report in reports if report["status"] == "success"] == []


def test_single_save_uses_existing_claimed_draft_product_without_rewriting_claim_note(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(note_verified=False)

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    actions = [call[0] for call in adapter.calls]
    assert "claim_product" not in actions
    assert "open_editor" in actions
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    assert "claim_product" not in reports[0]["summary"]["workflow_actions"]


def test_single_save_runner_requires_server_manual_approval_immediately_before_save(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1, manual_approval=False)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert "save_only" not in [call[0] for call in adapter.calls]
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is False
    assert "人工确认" in reports[0]["summary"]["blocked_reason"]


def test_single_save_browser_agent_still_requires_manual_approval_before_save(v1_db, monkeypatch):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1, manual_approval=False)
    manager = DummyManager()
    runtime = FakeBrowserAgentRuntime()
    runner = _test_runner(
        repo,
        manager,
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    asyncio.run(runner.run_task(task["id"]))

    actions = [command.action for command, _timeout in runtime.commands]
    assert "open_editor" in actions
    assert "save_only" not in actions
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is False
    assert "人工确认" in reports[0]["summary"]["blocked_reason"]


def test_single_save_browser_agent_records_save_only_result(v1_db, monkeypatch):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    runtime = FakeBrowserAgentRuntime()
    runner = _test_runner(
        repo,
        manager,
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    asyncio.run(runner.run_task(task["id"]))

    actions = [command.action for command, _timeout in runtime.commands]
    assert "save_only" in actions
    assert actions.index("save_only") < actions.index("verify_not_published")
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["ok"] is True


def test_save_only_false_save_result_fails_job(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(save_result={"ok": False, "message": "保存失败", "published": False})

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is False
    assert "save_result" in reports[0]["summary"]["blocked_reason"]


def test_single_save_fails_when_action_result_has_no_evidence_descriptor(v1_db):
    class MissingEvidenceAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action in {"save_only", "verify_not_published"}:
                result["evidence"]["refs"] = []
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=MissingEvidenceAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E999"
    assert [report for report in reports if report["status"] == "success"] == []


def test_single_save_rejects_nested_only_evidence_descriptor(v1_db):
    class NestedOnlyEvidenceAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "save_only":
                result["evidence"]["refs"] = []
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=NestedOnlyEvidenceAdapter(),
        ).run_task(task["id"])
    )

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "immutable evidence refs" in report["summary"]["blocked_reason"]


@pytest.mark.parametrize(
    ("corruption", "reason_code"),
    [
        ("outside", "EVIDENCE_REF_OUTSIDE_SCREENSHOT_DIR"),
        ("extension", "EVIDENCE_REF_EXTENSION_INVALID"),
        ("signature", "EVIDENCE_REF_PNG_SIGNATURE_INVALID"),
        ("hash", "EVIDENCE_REF_SHA256_MISMATCH"),
        ("size", "EVIDENCE_REF_SIZE_MISMATCH"),
    ],
)
def test_single_save_rejects_invalid_live_evidence(
    v1_db,
    tmp_path,
    corruption,
    reason_code,
):
    class InvalidEvidenceAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action != "save_only":
                return result

            extended_ref = dict(_test_action_first_ref(result))
            evidence_ref = {
                "path": extended_ref["path"],
                "sha256": extended_ref["sha256"],
                "size": extended_ref["size"],
            }
            evidence_path = Path(evidence_ref["path"])
            if corruption == "outside":
                evidence_path = tmp_path / "outside.png"
                content = b"\x89PNG\r\n\x1a\noutside"
                evidence_path.write_bytes(content)
                evidence_ref = {
                    "path": str(evidence_path.resolve()),
                    "sha256": hashlib.sha256(content).hexdigest().upper(),
                    "size": len(content),
                }
            elif corruption == "extension":
                evidence_path = Path(v1_runner_module.SCREENSHOT_DIR) / "save-proof.txt"
                content = b"\x89PNG\r\n\x1a\nwrong-extension"
                evidence_path.write_bytes(content)
                evidence_ref = {
                    "path": str(evidence_path.resolve()),
                    "sha256": hashlib.sha256(content).hexdigest().upper(),
                    "size": len(content),
                }
            elif corruption == "signature":
                content = b"not-a-real-png"
                evidence_path.write_bytes(content)
                evidence_ref["sha256"] = hashlib.sha256(content).hexdigest().upper()
                evidence_ref["size"] = len(content)
            elif corruption == "hash":
                content = bytearray(evidence_path.read_bytes())
                content[-1] = (content[-1] + 1) % 256
                evidence_path.write_bytes(bytes(content))
            elif corruption == "size":
                evidence_ref["size"] += 1

            result["evidence"]["refs"] = [
                {
                    **evidence_ref,
                    "kind": extended_ref["kind"],
                    "captured_at": extended_ref["captured_at"],
                }
            ]
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=InvalidEvidenceAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E999"
    assert reason_code in reports[0]["summary"]["blocked_reason"]
    assert [report for report in reports if report["status"] == "success"] == []


def test_single_save_revalidates_save_evidence_before_finalize(v1_db):
    class LateTamperAdapter(FakeWorkflowAdapter):
        def __init__(self):
            super().__init__()
            self.save_evidence_path = None

        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "save_only":
                self.save_evidence_path = Path(_test_action_first_ref(result)["path"])
            elif action == "verify_not_published" and self.save_evidence_path:
                content = bytearray(self.save_evidence_path.read_bytes())
                content[-1] = (content[-1] + 1) % 256
                self.save_evidence_path.write_bytes(bytes(content))
            return result

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)

    asyncio.run(
        _test_runner(
            repo,
            DummyManager(),
            workflow_adapter=LateTamperAdapter(),
        ).run_task(task["id"])
    )

    refreshed = repo.get_task_private(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert refreshed["jobs"][0]["error_code"] == "E999"
    assert "EVIDENCE_REF_SHA256_MISMATCH" in reports[0]["summary"]["blocked_reason"]
    assert [report for report in reports if report["status"] == "success"] == []


def test_save_only_smt_add_json_network_success_does_not_leave_failure_summary(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(
        save_result={
            "ok": True,
            "message": "您的产品编辑成功！",
            "success_text": "您的产品编辑成功！",
            "published": False,
            "network_save_result": {
                "ok": True,
                "url": "https://www.dianxiaomi.com/api/smtProduct/add.json",
                "method": "POST",
                "status": 200,
                "code": 0,
                "msg": "您的产品编辑成功！",
                "raw": {
                    "code": 0,
                    "msg": "Successful",
                    "data": {
                        "msg": "您的产品编辑成功！",
                        "code": 0,
                        "productId": "130658341344670934",
                    },
                },
            },
            "network_events": [
                {
                    "url": "https://www.dianxiaomi.com/api/smtProduct/add.json",
                    "method": "POST",
                    "resource_type": "xhr",
                    "status": 200,
                    "json": {
                        "code": 0,
                        "msg": "Successful",
                        "data": {
                            "msg": "您的产品编辑成功！",
                            "code": 0,
                            "productId": "130658341344670934",
                        },
                    },
                }
            ],
        },
    )

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "success"
    assert reports[0]["published"] is False
    assert reports[0]["save_result"]["network_save_result"]["url"].endswith("/api/smtProduct/add.json")
    assert reports[0]["summary"].get("blocked_reason") is None
    action_evidence = {
        item["meta"].get("action"): item
        for item in repo.list_evidences(task["id"])
        if item["evidence_type"] == "workflow_action"
        and item["meta"].get("action") in {"save_only", "verify_not_published"}
    }
    assert set(action_evidence) == {"save_only", "verify_not_published"}
    for item in action_evidence.values():
        evidence_ref = item["meta"]["evidence_ref"]
        content = Path(evidence_ref["path"]).read_bytes()
        assert set(evidence_ref) == {"path", "sha256", "size"}
        assert item["file_path"] == evidence_ref["path"]
        assert evidence_ref["size"] == len(content)
        assert evidence_ref["sha256"] == hashlib.sha256(content).hexdigest().upper()


def test_single_save_runner_rejects_product_that_lost_claimed_status_before_browser(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = task["payload"]["product_ids"][0]
    with sqlite3.connect(v1_db) as conn:
        conn.execute("UPDATE products SET status='draft' WHERE id=?", (product_id,))
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == []
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "已认领的商品箱商品" in reports[0]["summary"]["blocked_reason"]


def test_single_save_runner_rejects_product_without_draft_box_verification_before_browser(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    product_id = task["payload"]["product_ids"][0]
    with sqlite3.connect(v1_db) as conn:
        row = conn.execute("SELECT payload_json FROM products WHERE id=?", (product_id,)).fetchone()
        payload = json.loads(row[0])
        payload["draft_box_verified"] = False
        conn.execute("UPDATE products SET payload_json=? WHERE id=?", (json.dumps(payload, ensure_ascii=False), product_id))
    manager = DummyManager()
    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    assert adapter.calls == []
    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "商品箱验证" in reports[0]["summary"]["blocked_reason"]


def test_save_only_missing_save_result_fails_job(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(include_save_result=False)

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert reports[0]["published"] is False
    assert "save_result" in reports[0]["summary"]["blocked_reason"]


def test_save_only_failure_report_includes_save_result_reason(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = FakeWorkflowAdapter(
        fail_action="save_only",
        save_result={
            "ok": False,
            "message": "保存按钮已点击但未成功",
            "reason": "未检测到保存成功提示",
            "published": False,
            "network_save_result": {"ok": False, "reason": "未捕获保存相关接口响应"},
            "network_events": [],
        },
    )
    console = FakeAgentConsole()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter, agent_console=console).run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "未检测到保存成功提示" in report["summary"]["blocked_reason"]
    assert "未捕获保存相关接口响应" in report["summary"]["blocked_reason"]
    assert "保存接口捕获 0 条" in report["summary"]["blocked_reason"]
    assert "未检测到保存成功提示" in report["save_result"]["message"]
    failure_console_call = console.calls[-1]
    assert failure_console_call["step_code"] == "TASK_FAILED"
    assert failure_console_call["severity"] == "error"
    assert failure_console_call["requires_user_action"] is True
    assert "查看结果与问题" in failure_console_call["human_next"]
    failure_live_hud = adapter.live_hud_calls[-1]
    assert failure_live_hud["step_code"] == "TASK_FAILED"
    assert failure_live_hud["severity"] == "error"
    assert failure_live_hud["requires_user_action"] is True
    assert "真实保存不会继续" in failure_live_hud["human_action"]


def test_runner_uses_injected_workflow_executor_for_thread_bound_login_flow(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()
    adapter = ThreadRecordingWorkflowAdapter()

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="dxm-login-flow") as executor:
        asyncio.run(
            _test_runner(
                repo,
                manager,
                workflow_adapter=adapter,
                workflow_executor=executor,
            ).run_task(task["id"])
        )

    assert adapter.thread_names
    assert all(name.startswith("dxm-login-flow") for name in adapter.thread_names)
    assert adapter.hud_thread_names
    assert all(name.startswith("dxm-login-flow") for name in adapter.hud_thread_names)
    assert repo.get_task(task["id"])["status"] == "completed"


def test_real_dxm_adapter_always_requires_persistent_browser_agent_runtime(v1_db, monkeypatch):
    class MinimalFlow:
        pass

    repo = Repository()
    manager = DummyManager()
    real_adapter = DxmWorkflowAdapter(MinimalFlow())
    fake_adapter = FakeWorkflowAdapter()

    persistent_runtime = object()

    assert _test_runner(
        repo,
        manager,
        workflow_adapter=real_adapter,
        browser_agent_runtime=persistent_runtime,
    )._use_browser_agent_runtime() is True
    assert _test_runner(repo, manager, workflow_adapter=real_adapter)._use_process_workflow_runtime() is False
    assert _test_runner(repo, manager, workflow_adapter=fake_adapter)._use_process_workflow_runtime() is False

    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "thread")
    forced_thread = _test_runner(
        repo,
        manager,
        workflow_adapter=real_adapter,
        browser_agent_runtime=persistent_runtime,
    )
    assert forced_thread._use_browser_agent_runtime() is True
    assert forced_thread._use_process_workflow_runtime() is False

    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "process")
    forced_process = _test_runner(
        repo,
        manager,
        workflow_adapter=real_adapter,
        browser_agent_runtime=persistent_runtime,
    )
    assert forced_process._use_browser_agent_runtime() is True
    assert forced_process._use_process_workflow_runtime() is False
    assert _test_runner(repo, manager, workflow_adapter=fake_adapter)._use_process_workflow_runtime() is True


def test_claim_only_process_worker_request_contains_acquisition_context(v1_db, monkeypatch):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    job = repo.get_task(task["id"])["jobs"][0]
    runner = _test_runner(repo, DummyManager(), workflow_adapter=FakeWorkflowAdapter())
    captured = {}

    def fake_invoke_worker(**kwargs):
        captured.update(kwargs)
        legacy_result = {
            "ok": True,
            "action": kwargs["action_name"],
            "stage": "data_acquisition_claim",
            "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
            "evidence": {"stage": "data_acquisition_claim"},
        }
        return _canonical_test_action_result(
            kwargs["action_name"],
            legacy_result,
            state_override=kwargs["state_name"].value,
        )

    monkeypatch.setattr(runner, "_invoke_workflow_worker", fake_invoke_worker)

    result = runner._run_workflow_action_process(
        task,
        job,
        StateName.CLAIM_TO_DRAFT_BOX,
        f"AI认领-{task['id']}",
        {},
    )

    request = captured["request"]
    assert request["action"] == "claim_from_data_acquisition"
    assert request["state"] == StateName.CLAIM_TO_DRAFT_BOX.value
    assert request["params"] == {
        "claim_mark": f"AI认领-{task['id']}",
        "product_query": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "store_name": "Dang Kang",
        "target_source_urls": ["https://detail.1688.com/offer/from-acquisition.html"],
    }
    assert result["ok"] is True
    assert result["workflow_runtime"] == "process"


def test_single_save_process_worker_keeps_source_urls_for_editor_identity(v1_db, monkeypatch):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    runner = _test_runner(repo, DummyManager(), workflow_adapter=FakeWorkflowAdapter())
    requests = []

    def fake_invoke_worker(**kwargs):
        requests.append(kwargs["request"])
        legacy_result = {
            "ok": True,
            "action": kwargs["action_name"],
            "stage": f"{kwargs['action_name']}_stage",
            "page_url": "https://www.dianxiaomi.com/web/smt/edit?id=123",
            "evidence": {"stage": f"{kwargs['action_name']}_stage"},
        }
        return _canonical_test_action_result(
            kwargs["action_name"],
            legacy_result,
            state_override=kwargs["state_name"].value,
        )

    monkeypatch.setattr(runner, "_invoke_workflow_worker", fake_invoke_worker)

    for state_name in (StateName.OPEN_EDIT_PAGE, StateName.VERIFY_EDIT_OWNERSHIP):
        runner._run_workflow_action_process(
            task,
            job,
            state_name,
            f"AI认领-{task['id']}-{job['id']}",
            {},
        )

    assert [request["action"] for request in requests] == ["open_editor", "verify_edit_ownership"]
    assert requests[0]["params"]["target_source_urls"] == ["https://detail.1688.com/offer/test-1.html"]
    assert requests[1]["params"]["target_source_urls"] == ["https://detail.1688.com/offer/test-1.html"]


def test_claim_only_browser_agent_command_contains_acquisition_context(v1_db, monkeypatch):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
        "template_id": "template-1",
    })
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = FakeBrowserAgentRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=33,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    result = runner._run_workflow_action_browser_agent(
        task,
        job,
        StateName.CLAIM_TO_DRAFT_BOX,
        f"AI认领-{task['id']}",
        {},
    )

    command, timeout_seconds = runtime.commands[0]
    assert command.command_id
    assert command.idempotency_key
    assert datetime.fromisoformat(command.deadline).tzinfo is not None
    assert command.expected_page == "data_acquisition"
    assert command.runtime_id
    assert command.action == "claim_from_data_acquisition"
    assert command.state == StateName.CLAIM_TO_DRAFT_BOX.value
    assert command.step_label == "认领到商品箱"
    assert command.params == {
        "claim_mark": f"AI认领-{task['id']}",
        "product_query": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "store_name": "Dang Kang",
        "target_source_urls": ["https://detail.1688.com/offer/from-acquisition.html"],
    }
    assert timeout_seconds == 33
    assert result["workflow_runtime"] == "browser_agent"
    assert result["browser_agent_command"]["action"] == "claim_from_data_acquisition"


def test_v1_rebuilds_command_with_stable_idempotency_key_and_runtime_reuses_result(v1_db):
    class Adapter:
        def __init__(self):
            self.calls = 0

        def browser_session_id(self):
            return "stable-browser-session"

        def check_login_state(self):
            self.calls += 1
            return {
                "ok": True,
                "action": "check_login_state",
                "stage": "login_success",
                "page_url": "https://www.dianxiaomi.com/web/home",
                "evidence": {},
                "contract_facts": {
                    "before_values": {"probe": "visible_browser"},
                    "after_values": {"authenticated": True, "loading": False},
                    "postconditions": {
                        "session_authenticated": True,
                        "business_page_ready": True,
                        "loading_absent": True,
                    },
                    "evidence_observations": {
                        "login_check": {"authenticated": True, "loading": False}
                    },
                    "failure_code": None,
                    "recoverability": {
                        "kind": "none",
                        "retryable": False,
                        "requires_page_reverify": False,
                        "reason": None,
                    },
                },
            }

    class RecordingRuntime(BrowserAgentRuntime):
        def __init__(self, adapter):
            super().__init__(adapter)
            self.submissions = []

        def run(self, command, *, timeout_seconds=None):
            self.submissions.append(command)
            return super().run(command, timeout_seconds=timeout_seconds)

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    adapter = Adapter()
    runtime = RecordingRuntime(adapter)
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )

    first = runner._run_workflow_action_browser_agent(
        task,
        job,
        StateName.PRECHECK_SESSION,
        "AI认领",
        {},
    )
    second = runner._run_workflow_action_browser_agent(
        task,
        job,
        StateName.PRECHECK_SESSION,
        "AI认领",
        {},
    )

    assert first["ok"] is True and second["ok"] is True
    assert runtime.submissions[0].command_id != runtime.submissions[1].command_id
    assert runtime.submissions[0].idempotency_key == runtime.submissions[1].idempotency_key
    assert adapter.calls == 1
    runtime.shutdown()


def test_v1_command_uses_one_runtime_id_snapshot_for_binding_and_idempotency(v1_db):
    class ResetBetweenReadsRuntime(FakeBrowserAgentRuntime):
        def __init__(self):
            super().__init__()
            self.runtime_reads = 0

        @property
        def runtime_id(self):
            self.runtime_reads += 1
            return "runtime-before-reset" if self.runtime_reads == 1 else "runtime-after-reset"

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = ResetBetweenReadsRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )

    runner._run_workflow_action_browser_agent(
        task,
        job,
        StateName.CLAIM_TO_DRAFT_BOX,
        f"AI认领-{task['id']}",
        {},
    )

    command = runtime.commands[0][0]
    assert command.idempotency_key.startswith(f"v1:{command.runtime_id}:")
    assert runtime.runtime_reads == 1


def test_v1_runtime_reset_between_snapshot_and_reservation_fails_closed_without_execution(v1_db, monkeypatch):
    class Adapter:
        def __init__(self):
            self.calls = 0

        def check_login_state(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/home",
            }

        def close_browser_session(self):
            return None

    class ResetOnReserveRuntime(BrowserAgentRuntime):
        def __init__(self, adapter):
            super().__init__(adapter)
            self.did_reset = False

        def reserve_command(self, command):
            if not self.did_reset:
                self.did_reset = True
                self.reset(self.adapter)
            return super().reserve_command(command)

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    adapter = Adapter()
    runtime = ResetOnReserveRuntime(adapter)
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    with pytest.raises(V1ExecutionError, match="预留失败"):
        asyncio.run(
            runner._run_workflow_action_async(
                task,
                job,
                StateName.PRECHECK_SESSION,
                "AI认领",
                {},
            )
        )

    assert adapter.calls == 0
    assert runtime.status()["reservedCommandCount"] == 0
    runtime.shutdown()


def test_browser_agent_runtime_does_not_queue_live_hud_updates(v1_db, monkeypatch):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    job = repo.get_task(task["id"])["jobs"][0]
    adapter = FakeWorkflowAdapter()
    runtime = FakeBrowserAgentRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=33,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    event = runner._sync_live_browser_hud(
        task,
        job,
        "claim_only",
        StateName.CLAIM_TO_DRAFT_BOX,
        "认领到商品箱",
        "acquisition",
        "/artifacts/claim.txt",
    )

    assert runtime.commands == []
    assert adapter.live_hud_calls == []
    assert event["updated"] is False
    assert event["reason"] == "live_browser_hud_deferred_to_browser_agent"
    assert event["last_step_code"] == "CLAIM_TO_DRAFT_BOX"
    assert event["hud"]["state"] == "CLAIM_TO_DRAFT_BOX"
    assert event["hud"]["human_action"].endswith("认领到商品箱")


def test_live_hud_update_skips_unhealthy_browser_agent_runtime(v1_db, monkeypatch):
    class UnhealthyRuntime:
        def __init__(self):
            self.commands = []

        def status(self):
            return {
                "status": "needs_restart",
                "healthy": False,
                "lastError": "claim_from_data_acquisition timed out",
            }

        def run(self, command, *, timeout_seconds=None):
            self.commands.append((command, timeout_seconds))
            raise AssertionError("unhealthy Browser Agent must not receive HUD work")

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = UnhealthyRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=33,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    event = runner._sync_live_browser_hud(
        task,
        job,
        "claim_only",
        StateName.CLAIM_TO_DRAFT_BOX,
        "当前步骤失败",
        "acquisition",
        "/artifacts/claim.txt",
        hud_override={"step_code": "TASK_FAILED", "step_name": "当前步骤失败"},
    )

    assert runtime.commands == []
    assert event["updated"] is False
    assert event["reason"] == "live_browser_hud_runtime_unhealthy"
    assert event["last_error"] == "claim_from_data_acquisition timed out"
    assert event["last_step_code"] == "TASK_FAILED"


def test_claim_only_browser_agent_runtime_replaces_process_worker(v1_db, monkeypatch):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    runtime = FakeBrowserAgentRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    def fail_process_worker(*_args, **_kwargs):
        raise AssertionError("workflow_worker subprocess should not be used in browser_agent mode")

    monkeypatch.setattr(runner, "_invoke_workflow_worker", fail_process_worker)

    asyncio.run(runner.run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "completed"
    assert reports[0]["status"] == "success"
    actions = [command.action for command, _timeout in runtime.commands]
    assert [action for action in actions if action != "update_live_hud"] == [
        "check_login_state",
        "open_data_acquisition",
        "claim_from_data_acquisition",
        "verify_draft_box_claim",
    ]
    assert "update_live_hud" not in actions
    logs = repo.list_logs(task["id"])
    assert any(item["context"].get("runtime") == "browser_agent" for item in logs)


def test_browser_agent_timeout_detail_includes_last_internal_claim_step(v1_db, monkeypatch):
    class TimeoutAtClaimRuntime(FakeBrowserAgentRuntime):
        def __init__(self):
            super().__init__()
            self.last_step = None

        def status(self):
            return {
                "status": "running",
                "healthy": True,
                "currentStep": self.last_step or "待启动",
                "lastWorkflowEvent": {
                    "event": "data_acquisition_claim:target_find_start",
                    "human_step": self.last_step,
                } if self.last_step else None,
            }

        def run(self, command, *, timeout_seconds=None):
            if command.action == "claim_from_data_acquisition":
                self.commands.append((command, timeout_seconds))
                self.last_step = "定位待认领商品"
                raise TimeoutError("Browser Agent command timed out: claim_from_data_acquisition")
            return super().run(command, timeout_seconds=timeout_seconds)

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    runtime = TimeoutAtClaimRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=33,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    asyncio.run(runner.run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    report = repo.list_reports(task["id"])[0]
    assert refreshed["status"] == "failed"
    assert "定位待认领商品" in refreshed["jobs"][0]["error_message"]
    assert "定位待认领商品" in report["summary"]["blocked_reason"]


def test_browser_agent_timeout_explicitly_cancels_the_same_command_identity(v1_db):
    class TimeoutRuntime:
        runtime_id = "runtime-timeout-cancel"

        def __init__(self):
            self.command = None
            self.cancelled = []

        def run(self, command, *, timeout_seconds=None):
            self.command = command
            raise TimeoutError("deadline")

        def cancel_command(self, command_id, runtime_id):
            self.cancelled.append((command_id, runtime_id))
            return {"ok": True}

        def status(self):
            return {
                "runtimeId": self.runtime_id,
                "status": "idle",
                "healthy": True,
                "active": False,
            }

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = TimeoutRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=0.01,
    )

    with pytest.raises(V1ExecutionError, match="超时"):
        runner._run_workflow_action_browser_agent(
            task,
            job,
            StateName.CLAIM_TO_DRAFT_BOX,
            f"AI认领-{task['id']}",
            {},
        )

    assert runtime.cancelled == [
        (runtime.command.command_id, runtime.command.runtime_id),
    ]


def test_async_caller_cancellation_explicitly_cancels_browser_agent_command(v1_db, monkeypatch):
    class CancellableRuntime:
        runtime_id = "runtime-async-cancel"

        def __init__(self):
            self.started = threading.Event()
            self.release = threading.Event()
            self.command = None
            self.cancelled = []

        def run(self, command, *, timeout_seconds=None):
            self.command = command
            self.started.set()
            assert self.release.wait(timeout=2)
            return {
                "ok": True,
                "action": command.action,
                "stage": "claim_complete",
                "page_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
                "evidence": {},
            }

        def cancel_command(self, command_id, runtime_id):
            self.cancelled.append((command_id, runtime_id))
            self.release.set()
            return {"ok": True}

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    job = repo.get_task(task["id"])["jobs"][0]
    runtime = CancellableRuntime()
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=FakeWorkflowAdapter(),
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    async def scenario():
        pending = asyncio.create_task(
            runner._run_workflow_action_async(
                task,
                job,
                StateName.CLAIM_TO_DRAFT_BOX,
                f"AI认领-{task['id']}",
                {},
            )
        )
        assert await asyncio.to_thread(runtime.started.wait, 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending

    asyncio.run(scenario())
    runtime.release.set()

    assert runtime.cancelled == [
        (runtime.command.command_id, runtime.command.runtime_id),
    ]


def test_async_cancel_before_executor_start_consumes_reservation_without_adapter_call(v1_db, monkeypatch):
    class Adapter:
        def __init__(self):
            self.calls = 0

        def check_login_state(self):
            self.calls += 1
            return {
                "ok": True,
                "page_url": "https://www.dianxiaomi.com/web/home",
            }

    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    job = repo.get_task(task["id"])["jobs"][0]
    adapter = Adapter()
    runtime = BrowserAgentRuntime(adapter)
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=adapter,
        browser_agent_runtime=runtime,
        workflow_action_timeout_seconds=5,
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")
    blocker_started = threading.Event()
    release_blocker = threading.Event()

    async def scenario():
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)

        def occupy_executor():
            blocker_started.set()
            assert release_blocker.wait(timeout=2)

        blocker = loop.run_in_executor(None, occupy_executor)
        for _ in range(100):
            if blocker_started.is_set():
                break
            await asyncio.sleep(0.01)
        assert blocker_started.is_set()
        pending = asyncio.create_task(
            runner._run_workflow_action_async(
                task,
                job,
                StateName.PRECHECK_SESSION,
                "AI认领",
                {},
            )
        )
        for _ in range(100):
            if runtime.status()["reservedCommandCount"] == 1:
                break
            await asyncio.sleep(0.01)
        assert runtime.status()["reservedCommandCount"] == 1
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        release_blocker.set()
        await blocker
        for _ in range(100):
            if runtime.status()["reservedCommandCount"] == 0:
                break
            await asyncio.sleep(0.01)
        assert runtime.status()["reservedCommandCount"] == 0

    asyncio.run(scenario())

    assert adapter.calls == 0
    runtime.shutdown()


def test_browser_agent_runtime_setting_fails_closed_when_runtime_missing(v1_db, monkeypatch):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    adapter = FakeWorkflowAdapter()
    runner = _test_runner(repo, DummyManager(), workflow_adapter=adapter)
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "browser_agent")

    asyncio.run(runner.run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    reports = repo.list_reports(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "自动浏览器" in reports[0]["summary"]["blocked_reason"]
    assert "不会保存或发布" in reports[0]["summary"]["blocked_reason"]
    assert adapter.calls == []


def test_real_dxm_adapter_fails_closed_when_persistent_runtime_is_missing_even_if_thread_requested(v1_db, monkeypatch):
    class FlowThatMustNotRun:
        def get_state(self):
            raise AssertionError("real DxmWorkflowAdapter must not run outside BrowserAgent")

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=DxmWorkflowAdapter(FlowThatMustNotRun()),
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "thread")

    asyncio.run(runner.run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "持久在线真实浏览器" in report["summary"]["blocked_reason"]


@pytest.mark.parametrize(
    "runtime_status",
    [
        {"runtimeId": "runtime-real-1", "status": "needs_restart", "healthy": False, "active": False},
        {"runtimeId": "runtime-wrong", "status": "idle", "healthy": True, "active": False},
    ],
)
def test_real_dxm_adapter_fails_closed_on_unhealthy_or_wrong_runtime_binding(
    v1_db,
    monkeypatch,
    runtime_status,
):
    class FlowThatMustNotRun:
        def get_state(self):
            raise AssertionError("real DxmWorkflowAdapter must not run with invalid BrowserAgent binding")

    class Runtime:
        runtime_id = "runtime-real-1"

        def status(self):
            return dict(runtime_status)

        def run(self, *_args, **_kwargs):
            raise AssertionError("invalid BrowserAgent runtime must not dispatch")

    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel 立牌",
        "category_name": "立牌类谷子",
        "source_url": "https://detail.1688.com/offer/from-acquisition.html",
        "claim_mark": "AI认领",
    })
    runner = _test_runner(
        repo,
        DummyManager(),
        workflow_adapter=DxmWorkflowAdapter(FlowThatMustNotRun()),
        browser_agent_runtime=Runtime(),
    )
    monkeypatch.setenv("DXM_WORKFLOW_ACTION_RUNTIME", "process")

    asyncio.run(runner.run_task(task["id"]))

    report = repo.list_reports(task["id"])[0]
    assert report["status"] == "failed"
    assert "不会保存或发布" in report["summary"]["blocked_reason"]


def test_single_save_without_workflow_adapter_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="single_save", product_count=1)
    manager = DummyManager()

    asyncio.run(_test_runner(repo, manager).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "workflow_adapter" in reports[0]["summary"]["blocked_reason"]


def test_batch_save_without_workflow_adapter_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="batch_save", product_count=1)
    manager = DummyManager()

    asyncio.run(_test_runner(repo, manager).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "failed"
    assert reports[0]["status"] == "failed"
    assert "workflow_adapter" in reports[0]["summary"]["blocked_reason"]


def test_claim_only_without_workflow_adapter_fails(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="claim_only", product_count=1)
    manager = DummyManager()

    asyncio.run(_test_runner(repo, manager).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    assert reports[0]["status"] == "failed"
    assert "workflow_adapter" in reports[0]["summary"]["blocked_reason"]


def test_batch_save_runs_jobs_serially_with_independent_reports(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="batch_save", product_count=3)
    manager = DummyManager()

    adapter = FakeWorkflowAdapter()

    asyncio.run(_test_runner(repo, manager, workflow_adapter=adapter).run_task(task["id"]))

    reports = repo.list_reports(task["id"])
    refreshed = repo.get_task(task["id"])
    assert refreshed["status"] == "completed"
    assert refreshed["completed_jobs"] == 3
    assert refreshed["failed_jobs"] == 0
    assert len(reports) == 3
    assert all(report["published"] is False for report in reports)


def test_forbidden_publish_mode_fails_before_actions(v1_db):
    repo = Repository()
    task = _create_task(repo, mode="publish", product_count=1)
    manager = DummyManager()

    asyncio.run(_test_runner(repo, manager).run_task(task["id"]))

    refreshed = repo.get_task(task["id"])
    exceptions = repo.list_exceptions()
    assert refreshed["status"] == "failed"
    assert exceptions[0]["error_code"] == "E999"


def test_reports_table_exists_after_init(v1_db):
    with sqlite3.connect(v1_db) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='reports'"
        ).fetchone()

    assert table == ("reports",)
