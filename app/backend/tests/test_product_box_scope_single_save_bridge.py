from __future__ import annotations

import hashlib

import pytest

from src import db
from src.batch_edit.scope_contract import canonical_sha256 as scope_sha256
from src.repository import Repository
from src.state_machine.save_authorization import (
    SaveOnlyContractError,
    canonical_source_identity,
)
import src.repository as repository_module


def _scope_snapshot(
    store_name: str,
    observed_at: str = "2026-07-22T00:00:00.000Z",
) -> dict:
    source_url = "https://detail.1688.com/offer/1013604102950.html"
    source_identity = canonical_source_identity(source_url, [source_url])
    target_identity = {
        "schema_version": "dxm_draft_box_target.v1",
        "store_fingerprint": scope_sha256(
            {"store_name": store_name, "source": "structured_store_cell"}
        ),
        "stable_identity": {
            "kind": "source_url",
            "value": source_url,
            "fingerprint": source_identity["fingerprint"],
        },
        "source_urls": [source_url],
    }
    snapshot = {
        "schema_version": "dxm_draft_box_scope.v1",
        "observed_at": observed_at,
        "runtime_identity": {
            "instance_id": "runtime-1",
            "browser_runtime_id": "browser-1",
            "browser_session_id": "session-1",
            "git_head": "a" * 40,
        },
        "page_identity": {
            "url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "kind": "draft_box",
            "title": "商品箱",
            "business_marker": "商品箱",
        },
        "store_identity": {
            "store_name": store_name,
            "source": "structured_store_cell",
            "fingerprint": scope_sha256(
                {"store_name": store_name, "source": "structured_store_cell"}
            ),
        },
        "filter_state": {"controls": []},
        "sort_state": {"keys": [], "dom_order_authoritative": True},
        "page_state": {
            "current_page": 1,
            "page_size": 20,
            "total_items": 1,
            "visible_row_count": 1,
            "captured_count": 1,
            "max_items": 5,
            "truncated": False,
        },
        "items": [
            {
                "ordinal": 1,
                "title": "Live product",
                "dxm_product_id": None,
                "stable_record_key": f"source_url:{source_url}",
                "source_url": source_url,
                "source_urls": [source_url],
                "store_evidence": {
                    "store_name": store_name,
                    "cell_text": store_name,
                    "source": "structured_store_cell",
                    "column_index": 1,
                    "tag": "td",
                    "class_name": "store",
                    "dom_index": 0,
                },
                "target_identity": target_identity,
                "target_identity_sha256": scope_sha256(target_identity),
                "evidence_ref": {
                    "kind": "live_dom_row",
                    "browser_session_id": "session-1",
                    "page_kind": "draft_box",
                    "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
                    "dom_index": 0,
                    "row_sha256": "B" * 64,
                },
            }
        ],
        "evidence": {"kind": "live_dom_snapshot"},
        "zero_write_proof": {
            "strategy": "current_visible_page_dom_read",
            "navigation_attempted": False,
            "interactive_action_attempted": False,
            "mutation_dispatch_attempted": False,
        },
    }
    digest = scope_sha256(snapshot)
    return {**snapshot, "digest": digest, "snapshot_sha256": digest}


def test_live_product_box_capture_creates_one_verified_single_save_source(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "product-box-bridge.db")
    monkeypatch.setattr(repository_module, "EVIDENCE_DIR", tmp_path / "evidences")
    db.init_db()
    repo = Repository()
    store = repo.create_store("Live Store", "AliExpress")

    first = repo.create_draft_box_scope_snapshot(_scope_snapshot("Live Store"))
    repeated = repo.create_draft_box_scope_snapshot(_scope_snapshot("Live Store"))
    second = repo.create_draft_box_scope_snapshot(
        _scope_snapshot("Live Store", "2026-07-22T00:01:00.000Z")
    )

    assert first["store_identity"]["store_id"] == store["id"]
    assert repeated["id"] == first["id"]
    product_id = first["items"][0]["local_product_id"]
    assert isinstance(product_id, int) and product_id > 0
    assert second["items"][0]["local_product_id"] == product_id

    products = repo.list_products()
    assert len(products) == 1
    product = products[0]
    assert product["id"] == product_id
    assert product["source"] == "dxm_draft_box"
    assert product["status"] == "ready_for_edit"
    assert product["payload"]["draft_box_verified"] is True
    evidence_ref = product["payload"]["product_box_evidence_ref"]
    assert evidence_ref["path"].startswith(str(tmp_path))
    assert len(evidence_ref["sha256"]) == 64

    task = repo.create_task(
        {
            "name": "single save from live product box",
            "store_id": store["id"],
            "mode": "single_save",
            "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
            "product_ids": [product_id],
            "payload": {},
        }
    )
    assert task["mode"] == "single_save"
    assert task["payload"]["product_box_snapshot"]["product_id"] == product_id
    assert task["payload"]["product_box_snapshot"]["evidence_ref"] == evidence_ref


def test_scope_without_one_registered_store_never_creates_executable_product(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "product-box-no-store.db")
    monkeypatch.setattr(repository_module, "EVIDENCE_DIR", tmp_path / "evidences")
    db.init_db()
    repo = Repository()

    captured = repo.create_draft_box_scope_snapshot(_scope_snapshot("Unknown Store"))

    assert captured["store_identity"]["store_id"] is None
    assert captured["items"][0]["local_product_id"] is None
    assert repo.list_products() == []


def test_single_save_fails_closed_when_scope_evidence_is_deleted_or_tampered(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "product-box-evidence.db")
    monkeypatch.setattr(repository_module, "EVIDENCE_DIR", tmp_path / "evidences")
    db.init_db()
    repo = Repository()
    store = repo.create_store("Live Store", "AliExpress")
    captured = repo.create_draft_box_scope_snapshot(_scope_snapshot("Live Store"))
    product_id = captured["items"][0]["local_product_id"]
    task_data = {
        "name": "single save with immutable source evidence",
        "store_id": store["id"],
        "mode": "single_save",
        "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
        "product_ids": [product_id],
        "payload": {},
    }
    task = repo.create_task(task_data)
    task = repo.get_task_private(task["id"])
    product = repo.get_product(product_id)
    evidence_path = repository_module.EVIDENCE_DIR / (
        f"product-box-scope-{_scope_snapshot('Live Store')['digest']}.json"
    )
    original = evidence_path.read_bytes()

    evidence_path.unlink()
    assert "missing" in repo.single_save_product_box_snapshot_error(task, product)
    with pytest.raises(SaveOnlyContractError, match="missing"):
        repo.create_task(task_data)

    repo.create_draft_box_scope_snapshot(_scope_snapshot("Live Store"))
    evidence_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    assert "SHA-256" in repo.single_save_product_box_snapshot_error(task, product)
    with pytest.raises(SaveOnlyContractError, match="SHA-256"):
        repo.create_task(task_data)


def test_single_save_rejects_product_box_evidence_outside_configured_directory(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "product-box-evidence-root.db")
    monkeypatch.setattr(repository_module, "EVIDENCE_DIR", tmp_path / "evidences")
    db.init_db()
    repo = Repository()
    store = repo.create_store("Live Store", "AliExpress")
    captured = repo.create_draft_box_scope_snapshot(_scope_snapshot("Live Store"))
    product_id = captured["items"][0]["local_product_id"]
    product = repo.get_product(product_id)
    outside_path = tmp_path / "outside.json"
    outside_content = b'{"outside":true}'
    outside_path.write_bytes(outside_content)
    payload = dict(product["payload"])
    payload["product_box_evidence_ref"] = {
        "path": str(outside_path.resolve()),
        "sha256": hashlib.sha256(outside_content).hexdigest().upper(),
        "size": len(outside_content),
    }
    with db.connection() as conn:
        conn.execute(
            "UPDATE products SET payload_json=? WHERE id=?",
            (db.dumps(payload), product_id),
        )

    with pytest.raises(SaveOnlyContractError, match="outside the evidence directory"):
        repo.create_task(
            {
                "name": "single save with escaped evidence",
                "store_id": store["id"],
                "mode": "single_save",
                "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
                "product_ids": [product_id],
                "payload": {},
            }
        )
