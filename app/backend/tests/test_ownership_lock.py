import sqlite3

import pytest

from src import db
from src.services.ownership_lock import OwnershipLockService


@pytest.fixture()
def ownership_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ownership-locks.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return db_path


def test_build_ownership_tag_generates_task_scoped_tag():
    service = OwnershipLockService()

    assert service.build_ownership_tag("DXM-LOCK", 12) == "DXM-LOCK-12"
    assert service.build_ownership_tag("DXM-LOCK", 12, 34) == "DXM-LOCK-12-34"


def test_acquire_lock_succeeds_for_first_owner(ownership_db):
    service = OwnershipLockService()

    result = service.acquire_lock(
        task_id=12,
        job_id=34,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    assert result["acquired"] is True
    assert result["conflict"] is False
    assert result["status"] == "acquired"
    assert result["reason"] == "lock_acquired"
    assert result["ownership_tag"] == "DXM-LOCK-12-34"
    assert result["lock_token"]


def test_acquire_lock_conflicts_when_other_task_holds_same_fingerprint(ownership_db):
    service = OwnershipLockService()
    first = service.acquire_lock(
        task_id=12,
        job_id=34,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    result = service.acquire_lock(
        task_id=13,
        job_id=35,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    assert result["acquired"] is False
    assert result["conflict"] is True
    assert result["status"] == "conflict"
    assert result["reason"] == "ownership_locked"
    assert result["ownership_tag"] == first["ownership_tag"]
    assert result["lock_token"] == first["lock_token"]


def test_same_task_reuses_and_refreshes_lock(ownership_db):
    service = OwnershipLockService()
    first = service.acquire_lock(
        task_id=12,
        job_id=34,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    refreshed = service.acquire_lock(
        task_id=12,
        job_id=99,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    assert refreshed["acquired"] is True
    assert refreshed["conflict"] is False
    assert refreshed["status"] == "refreshed"
    assert refreshed["reason"] == "lock_refreshed"
    assert refreshed["lock_token"] == first["lock_token"]
    assert refreshed["ownership_tag"] == "DXM-LOCK-12-99"


def test_release_lock_allows_new_task_to_acquire_same_fingerprint(ownership_db):
    service = OwnershipLockService()
    first = service.acquire_lock(
        task_id=12,
        job_id=34,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    released = service.release_lock(first["lock_token"])
    second = service.acquire_lock(
        task_id=13,
        job_id=35,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    assert released["acquired"] is False
    assert released["conflict"] is False
    assert released["status"] == "released"
    assert released["reason"] == "lock_released"
    assert second["acquired"] is True
    assert second["status"] == "acquired"
    assert second["ownership_tag"] == "DXM-LOCK-13-35"


def test_init_db_creates_ownership_locks_table(ownership_db):
    with sqlite3.connect(ownership_db) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ownership_locks'"
        ).fetchone()

    assert table == ("ownership_locks",)
