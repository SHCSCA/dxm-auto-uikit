from src.batch_edit.scope_contract import canonical_sha256
from src.execution.canonical_receipt import ContentFinalizeReceipt, FieldReadback, ReceiptPhase


OBSERVED_AT = "2026-08-31T00:00:01Z"


def section_receipt(section: str) -> dict:
    body = {"schema_version": "dxm.path-b.section-receipt.v1", "section": section,
            "action_grant_id": "section-" + section, "success": True, "readback_proven": True,
            "started_at": OBSERVED_AT, "completed_at": OBSERVED_AT,
            "field_readbacks": [FieldReadback(field_key=section, field_label="字段",
                source="visible_production_runtime", before_value="Before", after_value="After",
                readback_proven=True, timestamp=OBSERVED_AT).to_dict()]}
    return {**body, "receipt_sha256": canonical_sha256(body)}


def capability_receipt(capability: str) -> dict:
    phase = "rollback_preparation" if capability == "rollbackPreparation" else "content_finalize_" + capability
    receipt = ContentFinalizeReceipt(phase=ReceiptPhase(phase), action_grant_id="action-" + capability,
        result_ok=True, started_at=OBSERVED_AT, completed_at=OBSERVED_AT,
        media_identity="https://example.test/video.mp4" if capability == "video" else None,
        field_readbacks=[])
    digest = receipt.finalize()
    raw = receipt.to_dict()
    if capability == "rollbackPreparation":
        raw["preimage_sha256"] = "a" * 64
    return {"canonical_receipt": raw, "receipt_sha256": digest}
