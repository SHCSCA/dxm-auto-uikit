"""Regression tests for `ConcurrentEditorGuard.acquire_writer_fence`.

These tests pin the shop-scope invariant: any active writer fence on a shop
must block ALL other tasks on the same shop until released. A regression to
the (shop_id, task_id) scoped query would have let two concurrent tasks
mutate the same shop in parallel.
"""
from __future__ import annotations

import pytest

from src import db
from src.services.ownership_lock import ConcurrentEditorGuard


@pytest.fixture()
def fence_db(tmp_path, monkeypatch):
    db_path = tmp_path / "writer-fences.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    return db_path


def test_first_acquire_returns_acquired(fence_db):
    guard = ConcurrentEditorGuard()

    result = guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-aaa",
        generation=0,
    )

    assert result["acquired"] is True
    assert result["conflict"] is False
    assert result["status"] == "acquired"
    assert result["reason"] == "fence_acquired"
    assert result["shop_id"] == "shop-1"
    assert result["task_id"] == "task-aaa"


def test_same_task_same_generation_refreshes_fence(fence_db):
    guard = ConcurrentEditorGuard()
    first = guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-aaa",
        generation=0,
    )

    refresh = guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-aaa",
        generation=0,
    )

    assert refresh["acquired"] is True
    assert refresh["conflict"] is False
    assert refresh["status"] == "refreshed"
    assert refresh["writer_fence_id"] == first["writer_fence_id"]
    assert refresh["reason"] == "fence_refreshed"


def test_same_task_different_generation_conflicts(fence_db):
    guard = ConcurrentEditorGuard()
    guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-aaa",
        generation=0,
    )

    result = guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-aaa",
        generation=1,
    )

    assert result["acquired"] is False
    assert result["conflict"] is True
    assert result["reason"] == "generation_mismatch"


def test_different_task_same_shop_is_blocked_by_shop_writer_fence(fence_db):
    """Critical regression guard: a different task on the SAME shop must not
    be able to acquire a writer fence while another task still holds one.
    This is the shop-scope invariant that prevents parallel mutations.
    """
    guard = ConcurrentEditorGuard()
    first = guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-aaa",
        generation=0,
    )

    second = guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-bbb",
        generation=0,
    )

    assert second["acquired"] is False
    assert second["conflict"] is True
    assert second["status"] == "conflict"
    assert second["reason"] == "shop_writer_fence_held_by_other_task"
    assert second["writer_fence_id"] == first["writer_fence_id"]
    assert second["task_id"] == "task-bbb"


def test_different_shop_not_blocked(fence_db):
    guard = ConcurrentEditorGuard()
    guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-aaa",
        generation=0,
    )

    result = guard.acquire_writer_fence(
        shop_id="shop-2",
        task_id="task-aaa",
        generation=0,
    )

    assert result["acquired"] is True
    assert result["conflict"] is False
    assert result["shop_id"] == "shop-2"


def test_release_then_new_task_can_acquire_same_shop(fence_db):
    guard = ConcurrentEditorGuard()
    first = guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-aaa",
        generation=0,
    )

    release = guard.release_writer_fence(
        writer_fence_id=first["writer_fence_id"],
        generation=first["generation"],
    )
    assert release["status"] == "released"

    second = guard.acquire_writer_fence(
        shop_id="shop-1",
        task_id="task-bbb",
        generation=0,
    )
    assert second["acquired"] is True
    assert second["conflict"] is False
    assert second["shop_id"] == "shop-1"
    assert second["task_id"] == "task-bbb"
