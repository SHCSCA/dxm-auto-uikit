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


def test_build_claim_mark_generates_task_scoped_mark():
    service = OwnershipLockService()

    assert service.build_claim_mark("AI认领", 12) == "AI认领-12"
    assert service.build_claim_mark("AI认领", 12, 34) == "AI认领-12-34"


def test_acquire_lock_succeeds_for_first_claim(ownership_db):
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
    assert result["claim_mark"] == "AI认领-12-34"
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
    assert result["claim_mark"] == first["claim_mark"]
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
    assert refreshed["claim_mark"] == "AI认领-12-99"


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
    assert second["claim_mark"] == "AI认领-13-35"


def test_mark_page_claim_verified_checks_returned_page_mark(ownership_db):
    service = OwnershipLockService()
    lock = service.acquire_lock(
        task_id=12,
        job_id=34,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    mismatch = service.mark_page_claim_verified(lock["lock_token"], "AI认领-999")
    verified = service.mark_page_claim_verified(lock["lock_token"], "AI认领-12-34")

    assert mismatch["acquired"] is True
    assert mismatch["conflict"] is True
    assert mismatch["status"] == "claim_mismatch"
    assert mismatch["reason"] == "page_claim_mark_mismatch"
    assert verified["acquired"] is True
    assert verified["conflict"] is False
    assert verified["status"] == "verified"
    assert verified["reason"] == "page_claim_mark_verified"


def test_verified_page_claim_mark_is_persisted(ownership_db):
    service = OwnershipLockService()
    lock = service.acquire_lock(
        task_id=12,
        job_id=34,
        product_id=56,
        store_name="店铺A",
        source_title="地狱客栈阿拉斯托亚克力立牌桌面摆件",
    )

    service.mark_page_claim_verified(lock["lock_token"], "AI认领-12-34")

    with sqlite3.connect(ownership_db) as conn:
        row = conn.execute(
            "SELECT page_claim_mark, page_claim_verified FROM ownership_locks WHERE lock_token=?",
            (lock["lock_token"],),
        ).fetchone()

    assert row == ("AI认领-12-34", 1)


def test_init_db_creates_ownership_locks_table(ownership_db):
    with sqlite3.connect(ownership_db) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ownership_locks'"
        ).fetchone()

    assert table == ("ownership_locks",)
