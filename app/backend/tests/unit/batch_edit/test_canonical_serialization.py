"""Tests for canonical serialization stability in PlanSnapshotCompiler.

Verifies:
1. Same input → same plan_content_sha256 across two freeze calls (determinism)
2. Same plan_content_sha256 + different idempotency_key → different snapshot_instance_sha256
3. Canonical JSON serialization (sorted keys, no timestamps)
"""

from __future__ import annotations

import pytest

from src.batch_edit.plan_snapshot_compiler import (
    PlanSnapshotCompiler,
    _SCHEMA_VERSION,
    MANDATORY_CAPABILITIES,
    CAPABILITY_NAMES,
    SNAPSHOT_INSTANCE_SCHEMA,
)
from src.batch_edit.plan_template_contract import (
    PlanTemplateContractError,
)
from src.execution.browser_agent_protocol import (
    build_frozen_product_target_identity,
)


class DummyError(Exception):
    def __init__(self, reason_code: str, detail: str, *, status_code: int = 409):
        super().__init__(f"[{reason_code}] {detail}")
        self.reason_code = reason_code
        self.detail = detail
        self.status_code = status_code


class DummyCapabilityChecker:
    def __init__(self, available: bool = True):
        self._available = available

    def is_available(self, capability: str) -> dict:
        if capability in MANDATORY_CAPABILITIES:
            return {"ok": self._available}
        return {"ok": False}


class DummyLocalPlanStore:
    def load_snapshot_inputs(self, plan_id: int):
        plan = {
            "id": plan_id,
            "version": "v1.0",
            "path": "A",
            "shop_id": "12345",
            "category_ids": ["2621"],
            "field_mappings": {
                "2621": {
                    "mapping_version": "1.0.0",
                    "entries": [
                        {
                            "ui_label_zh": "商品标题",
                            "field_key": "title",
                            "category_schema_path": "$.properties.title",
                            "ui_binding": "dxm_editor:title",
                        }
                    ],
                },
            },
            "fill_rules": {
                "2621": {
                    "title": {"value": "Test Product"},
                },
            },
            "source_policies": {},
            "fixed_values": {
                "field_values": {
                    "2621": {},
                },
            },
        }
        from src.batch_edit.plan_reference_store import ResolvedTemplateReferences
        from src.batch_edit.plan_value_contract import PlanValueContract
        values = PlanValueContract(PlanTemplateContractError)
        template_refs = ResolvedTemplateReferences([], values=values)
        return plan, template_refs


def _make_request(idempotency_key: str = "test-key-001") -> dict:
    target_identity = build_frozen_product_target_identity(
        product_id="70001",
        store_name="Test Shop",
        source_urls=["https://www.aliexpress.com/item/70001.html"],
    )
    return {
        "local_plan_template_id": 1,
        "shop_id": "12345",
        "session_context": {
            "session_ref": "0011223344556677",
            "account_ref_hash": "A" * 64,
            "shop_id": "12345",
            "shop_name": "Test Shop",
        },
        "idempotency_key": idempotency_key,
        "items": [
            {
                "product_id": "70001",
                "shop_id": "12345",
                "category_id": "2621",
                "category_schema": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "ui_binding": "dxm_editor:title",
                        },
                    },
                    "required": ["title"],
                },
                "expected_schema_hash": "ED4B86ABEDF624E8E3D95E7B1891E19BA47860D4E9F99DA4B6DA192A3E2818E9",
                "current_values": {"title": "Test Product"},
                "target_identity": target_identity,
            }
        ],
    }


class TestCanonicalSerializationDeterminism:
    """Test 1: Same input → same plan_content_sha256 across two freeze calls."""

    def test_same_input_produces_same_hash(self):
        """Two compile() calls with identical input must produce identical hashes."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request(idempotency_key="same-key")
        result1 = compiler.compile(request)
        result2 = compiler.compile(request)

        assert result1["snapshot_hash"] == result2["snapshot_hash"], (
            "Identical inputs must produce identical snapshot_hash"
        )
        assert result1["plan_content_sha256"] == result2["plan_content_sha256"], (
            "Identical inputs must produce identical plan_content_sha256"
        )

    def test_hash_does_not_include_timestamps(self):
        """Hash computation must not include any timestamp fields."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request()
        result = compiler.compile(request)
        import json
        serialized = json.dumps(result, sort_keys=True)
        assert "created_at" not in serialized, (
            "snapshot must not contain timestamp fields in hash input"
        )
        assert "updated_at" not in serialized, (
            "snapshot must not contain timestamp fields in hash input"
        )

    def test_hash_does_not_include_approval_fields(self):
        """Hash computation must not include approval/attempt_id fields."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request()
        result = compiler.compile(request)
        import json
        serialized = json.dumps(result, sort_keys=True)
        assert "approved_at" not in serialized, (
            "snapshot must not include approval fields in hash input"
        )
        assert "attempt_id" not in serialized, (
            "snapshot must not include attempt_id in hash input"
        )


class TestInstanceIdempotency:
    """Test 2: Same plan_content_sha256 + different idempotency_key → different snapshot_instance_sha256."""

    def test_different_idempotency_key_produces_different_instance_sha(self):
        """Different idempotency keys must produce different snapshot_instance_sha256."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request(idempotency_key="key-A")
        snapshot = compiler.compile(request)

        instance_a = compiler.compile_instance(snapshot, idempotency_key="key-A")
        instance_b = compiler.compile_instance(snapshot, idempotency_key="key-B")

        assert instance_a["snapshot_instance_sha256"] != instance_b["snapshot_instance_sha256"], (
            "Different idempotency_key must produce different snapshot_instance_sha256"
        )

    def test_same_idempotency_key_produces_same_instance_sha(self):
        """Same idempotency key must produce identical snapshot_instance_sha256."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request(idempotency_key="stable-key")
        snapshot = compiler.compile(request)

        instance_a = compiler.compile_instance(snapshot, idempotency_key="stable-key")
        instance_b = compiler.compile_instance(snapshot, idempotency_key="stable-key")

        assert instance_a["snapshot_instance_sha256"] == instance_b["snapshot_instance_sha256"], (
            "Same idempotency_key must produce identical snapshot_instance_sha256"
        )

    def test_instance_preserves_plan_content_sha256(self):
        """Instance must preserve the plan_content_sha256 from its snapshot."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request(idempotency_key="test-key")
        snapshot = compiler.compile(request)
        instance = compiler.compile_instance(snapshot, idempotency_key="test-key")

        assert instance["plan_content_sha256"] == snapshot["plan_content_sha256"]
        assert instance["schema"] == SNAPSHOT_INSTANCE_SCHEMA
        assert "idempotency_key" in instance
        assert instance["idempotency_key"] == "test-key"


class TestMandatoryCapabilities:
    """Test that mandatory capabilities block is properly constructed."""

    def test_all_five_capabilities_present(self):
        """All 5 mandatory capabilities must be present and enabled."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request()
        result = compiler.compile(request)

        caps = result.get("mandatory_capabilities", {})
        for capability in MANDATORY_CAPABILITIES:
            assert capability in caps, f"Capability {capability} must be in mandatory_capabilities"
            assert caps[capability].get("enabled") is True, (
                f"Capability {capability} must be enabled"
            )
            assert caps[capability].get("required") is True, (
                f"Capability {capability} must be required"
            )

    def test_fail_closed_when_capability_unavailable(self):
        """Compilation must fail when any mandatory capability is unavailable."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=False),
        )
        request = _make_request()
        with pytest.raises(DummyError) as exc_info:
            compiler.compile(request)
        assert "MANDATORY_CAPABILITY_UNAVAILABLE" in exc_info.value.reason_code


class TestExecutionConstraints:
    """Test that execution_constraints block is properly constructed."""

    def test_max_age_hours_default(self):
        """max_age_hours must default to 24 hours."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request()
        result = compiler.compile(request)

        constraints = result.get("execution_constraints", {})
        assert constraints.get("max_age_hours") == 24

    def test_drift_policies_are_abort(self):
        """schema_drift_policy and catalog_drift_policy must be ABORT."""
        compiler = PlanSnapshotCompiler(
            DummyError,
            local_plan_store=DummyLocalPlanStore(),
            capability_checker=DummyCapabilityChecker(available=True),
        )
        request = _make_request()
        result = compiler.compile(request)

        constraints = result.get("execution_constraints", {})
        assert constraints.get("schema_drift_policy") == "ABORT"
        assert constraints.get("catalog_drift_policy") == "ABORT"
        assert constraints.get("plan_drift_policy") == "ABORT"
