from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.state_machine.save_authorization import (
    SAVE_ONLY_CONFIRMATION,
    SAVE_ONLY_PUBLISH_SCENE,
    SaveOnlyContractError,
    build_authorization_context,
    build_product_box_snapshot,
    build_save_task_facts,
    canonical_source_identity,
    compare_authorization_context,
    verify_authorization_context,
    verify_exact_save_task_facts,
    verify_product_box_snapshot,
)


SHA_A = "A" * 64
SHA_B = "B" * 64


def _target(source_identity: dict) -> dict:
    return {
        "schema_version": "dxm_draft_box_target.v1",
        "store_fingerprint": SHA_A,
        "stable_identity": {
            "kind": "source_url",
            "value": source_identity["primary_url"],
            "fingerprint": source_identity["fingerprint"],
        },
        "source_urls": list(source_identity["urls"]),
    }


def _snapshot() -> dict:
    source_identity = canonical_source_identity(
        "https://detail.1688.com/offer/123456.html",
    )
    return build_product_box_snapshot(
        product_id=7,
        store_id=3,
        store_name="Dang Kang",
        product_title="Current product-box item",
        product_status="ready_for_edit",
        source_identity=source_identity,
        target_identity=_target(source_identity),
        captured_at=datetime.now(timezone.utc).isoformat(),
        evidence_ref={
            "path": "D:/evidence/product-box.png",
            "sha256": SHA_B,
            "size": 10,
        },
    )


def test_product_box_snapshot_is_canonical_and_tamper_evident() -> None:
    snapshot = _snapshot()

    assert verify_product_box_snapshot(snapshot) == {"ok": True, "reason_code": "OK"}

    tampered = {**snapshot, "product_title": "different"}
    assert verify_product_box_snapshot(tampered)["ok"] is False


def test_save_task_facts_bind_exact_task_job_store_product_and_snapshot() -> None:
    snapshot = _snapshot()
    facts = build_save_task_facts(
        task_id=11,
        job_id=12,
        store_id=3,
        product_id=7,
        product_box_snapshot_fingerprint=snapshot["fingerprint"],
    )

    assert facts["mode"] == "single_save"
    assert facts["confirmation"] == SAVE_ONLY_CONFIRMATION
    assert facts["publish_scene"] == SAVE_ONLY_PUBLISH_SCENE
    assert facts["action"] == "save_only"
    assert verify_exact_save_task_facts(facts) == {"ok": True, "reason_code": "OK"}

    tampered = {**facts, "product_id": 8}
    assert verify_exact_save_task_facts(tampered)["ok"] is False


def test_authorization_context_rejects_runtime_or_facts_drift() -> None:
    snapshot = _snapshot()
    facts = build_save_task_facts(
        task_id=11,
        job_id=12,
        store_id=3,
        product_id=7,
        product_box_snapshot_fingerprint=snapshot["fingerprint"],
    )
    context = build_authorization_context(
        stage_task_facts=facts,
        runtime_instance_id="runtime-1",
        browser_session_id="browser-1",
        git_head="1" * 40,
        l2_evidence_fingerprint=SHA_A,
        approved_by="operator",
    )

    assert verify_authorization_context(context) == {"ok": True, "reason_code": "OK"}
    assert compare_authorization_context(context, context) == {"ok": True, "reason_code": "OK"}

    changed_runtime = {**context, "runtime_instance_id": "runtime-2"}
    assert verify_authorization_context(changed_runtime)["ok"] is False
    assert compare_authorization_context(context, changed_runtime)["ok"] is False


def test_source_identity_requires_an_absolute_supported_shape() -> None:
    identity = canonical_source_identity(
        "HTTPS://DETAIL.1688.COM/offer/123456.html#fragment",
    )
    assert identity["primary_url"] == "https://detail.1688.com/offer/123456.html"

    with pytest.raises(SaveOnlyContractError):
        canonical_source_identity("not-a-url")
