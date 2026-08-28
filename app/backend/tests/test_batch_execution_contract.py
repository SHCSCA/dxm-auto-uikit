from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone

import pytest

from src.batch_edit.batch_contract import (
    BATCH_TEMPLATE_REQUIRED_SECTIONS,
    BatchContractError,
    freeze_template_bundle,
    frozen_batch_policy,
)
from src.batch_edit.execution_contract import (
    BatchExecutionContractError,
    authorize_batch_start,
    classify_item_outcome,
    derive_next_item_grant,
    validate_and_consume_item_grant,
)
from src.batch_edit.scope_contract import canonical_sha256
from src.execution.browser_agent_protocol import build_mutation_scope_id
from src.services.dxm_reference_templates import EXECUTABLE_REFERENCE_TEMPLATE_SECTIONS


NOW = datetime(2026, 7, 21, 9, 2, tzinfo=timezone.utc)


def _facts() -> tuple[dict, dict]:
    runtime = {
        "instance_id": "desktop-1",
        "browser_runtime_id": "runtime-1",
        "browser_session_id": "session-1",
        "git_head": "a" * 40,
    }
    page = {
        "url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        "kind": "draft_box",
        "title": "DXM draft box",
        "business_marker": "product-id",
    }
    store = {"store_name": "DXM Shop A", "store_identity_sha256": "S" * 64}
    authoritative = {
        "runtime_identity": runtime,
        "browser_session_id": "session-1",
        "git_head": "a" * 40,
        "l2_evidence_fingerprint": "F" * 64,
        "store_identity": store,
        "page_identity": page,
    }
    return authoritative, {"runtime": runtime, "page": page, "store": store}


def _approved_batch() -> tuple[dict, str, str, dict]:
    authoritative, identity = _facts()
    targets = []
    scope_items = []
    batch_items = []
    for ordinal in (1, 2):
        target = {"kind": "product_id", "value": f"DXM-{ordinal}"}
        target_hash = canonical_sha256(target)
        scope_item = {
            "ordinal": ordinal,
            "target_identity": target,
            "target_identity_sha256": target_hash,
        }
        scope_items.append(scope_item)
        targets.append(copy.deepcopy(scope_item))
        batch_items.append(
            {
                "id": ordinal + 10,
                "batch_id": 7,
                "ordinal": ordinal,
                "status": "pending",
                "target_identity_sha256": target_hash,
                "item_snapshot": copy.deepcopy(scope_item),
                "created_at": "2026-07-21T09:00:00+00:00",
                "updated_at": "2026-07-21T09:00:00+00:00",
            }
        )
    scope_body = {
        "schema_version": "dxm_draft_box_scope.v1",
        "observed_at": "2026-07-21T09:00:00+00:00",
        "runtime_identity": identity["runtime"],
        "page_identity": identity["page"],
        "store_identity": identity["store"],
        "filter_state": {"status": "draft"},
        "sort_state": {"dom_order_authoritative": True},
        "page_state": {"max_items": 2, "captured_count": 2},
        "items": scope_items,
        "evidence": {"dom_sha256": "D" * 64, "refs_digest": "E" * 64},
        "zero_write_proof": {"mutation_dispatch_attempted": False},
    }
    scope_digest = canonical_sha256(scope_body)
    scope = {
        "id": 3,
        **scope_body,
        "digest": scope_digest,
        "snapshot_sha256": scope_digest,
        "created_at": "2026-07-21T09:00:00+00:00",
    }
    reference_templates = {
        name: {
            "names": [f"{name}-template"] if name in EXECUTABLE_REFERENCE_TEMPLATE_SECTIONS else [],
            "required": name in EXECUTABLE_REFERENCE_TEMPLATE_SECTIONS,
        }
        for name in (
            "attribute_info",
            "description",
            "freight",
            "service",
            "eu_responsible",
            "manufacturer",
            "compliance",
            "semi_managed",
        )
    }
    source_templates = {}
    sections = {}
    section_values = {
        "category": {"category_keyword": "车载用品"},
        "sku": {"sku_code_strategy": "use_product_or_dxm"},
        "pricing": {"retail_price_strategy": "preserve_or_template"},
        "logistics": {"weight": "0.5", "length": "20", "width": "15", "height": "10"},
        "image": {
            "eu_outer_package_filename": "eu-label.jpg",
            "marketing_images_strategy": "preserve_existing",
        },
        "compliance": {"material": "ABS"},
        "semi_managed": {
            "supply_price": "4.20",
            "jit_stock": "100",
            "is_original_box": "否",
            "length": "20",
            "width": "15",
            "height": "10",
            "goods_code_strategy": "allow_blank",
            "barcode_strategy": "allow_blank",
        },
        "dxm_reference": {"dxm_reference_templates": reference_templates},
    }
    for index, name in enumerate(BATCH_TEMPLATE_REQUIRED_SECTIONS, start=1):
        payload = (
            {"dxm_reference_templates": reference_templates}
            if name == "dxm_reference"
            else {name: section_values[name]}
        )
        section_value = section_values[name]
        snapshot = {
            "id": 100 + index,
            "template_type": name,
            "template_name": f"{name} source",
            "binding_scope": "DXM Shop A / 车载用品",
            "payload": payload,
            "is_enabled": True,
            "created_at": "2026-07-21T08:00:00+00:00",
            "updated_at": "2026-07-21T08:00:00+00:00",
        }
        source_templates[name] = {
            "template_id": snapshot["id"],
            "template_type": name,
            "template_name": snapshot["template_name"],
            "binding_scope": snapshot["binding_scope"],
            "source_digest": canonical_sha256(snapshot),
            "snapshot": snapshot,
        }
        sections[name] = section_value
    template = {
        "id": 5,
        "template_type": "edit_batch_bundle",
        "template_name": "safe bundle",
        "is_enabled": True,
        "payload": {
            "schema_version": "dxm_edit_template_bundle.v1",
            "version": "1.0.0",
            "required_sections": list(BATCH_TEMPLATE_REQUIRED_SECTIONS),
            "binding": {
                "store_id": 1,
                "store_name": "DXM Shop A",
                "category_name": None,
                "platform": "AliExpress",
            },
            "source_templates": source_templates,
            "sections": sections,
        },
    }
    policy = frozen_batch_policy()
    batch = {
        "id": 7,
        "schema_version": "dxm_edit_batch.v1",
        "status": "approved",
        "scope_snapshot_id": 3,
        "scope_snapshot_digest": scope_digest,
        "scope_snapshot": scope,
        "template_id": 5,
        "template_snapshot_digest": canonical_sha256(template),
        "template_snapshot": template,
        "policy_digest": canonical_sha256(policy),
        "policy": policy,
        "created_at": "2026-07-21T09:00:00+00:00",
        "updated_at": "2026-07-21T09:01:00+00:00",
        "items": batch_items,
    }
    token = "one-time-approval-token"
    token_hash = hashlib.sha256(token.encode()).hexdigest().upper()
    context_body = {
        "schema_version": "dxm_edit_batch_approval_context.v1",
        "batch": {"id": 7, "schema_version": "dxm_edit_batch.v1", "required_status": "draft"},
        "scope": {"snapshot_id": 3, "snapshot_digest": scope_digest},
        "template": {"id": 5, "snapshot_digest": batch["template_snapshot_digest"]},
        "policy": {"digest": batch["policy_digest"]},
        "ordered_targets": {"items": targets, "digest": canonical_sha256(targets)},
        "store_identity": identity["store"],
        "runtime_identity": identity["runtime"],
        "l2_evidence_fingerprint": "F" * 64,
        "read_attestation": {
            "kind": "scope_revalidation",
            "status": "matched",
            "captured_at": "2026-07-21T09:00:00+00:00",
            "frozen_scope_digest": scope_digest,
            "revalidated_scope_digest": scope_digest,
            "ordered_target_digest": canonical_sha256(targets),
            "dom_sha256": "D" * 64,
            "refs_digest": "E" * 64,
            "zero_write_digest": canonical_sha256(scope["zero_write_proof"]),
        },
        "approved_by": "operator@example.com",
        "confirmation": "CONFIRM_DXM_BATCH_SAVE_ONLY",
        "lease_id": "approval-lease-1",
        "issued_at": "2026-07-21T09:00:00+00:00",
        "expires_at": "2026-07-21T09:05:00+00:00",
    }
    context = {**context_body, "fingerprint": canonical_sha256(context_body)}
    return batch, token, token_hash, context


def test_old_batch_contract_rejects_category_bound_bundle_without_row_evidence() -> None:
    batch, _token, _token_hash, _context = _approved_batch()
    batch["template_snapshot"]["payload"]["binding"]["category_name"] = "车载用品"

    with pytest.raises(BatchContractError) as caught:
        freeze_template_bundle(batch["template_snapshot"])

    assert caught.value.reason_code == "BATCH_CATEGORY_SCOPE_UNVERIFIABLE"


def test_authorize_batch_start_returns_only_sanitized_frozen_context():
    batch, token, token_hash, approval_context = _approved_batch()
    authoritative, _identity = _facts()

    result = authorize_batch_start(
        batch,
        approval_token=token,
        stored_approval_token_hash=token_hash,
        approval_context=approval_context,
        now=NOW,
        authoritative_facts=authoritative,
    )

    assert result["schema_version"] == "dxm_edit_batch_start_context.v1"
    assert result["authorization_state"] == "approval_token_consumed"
    assert result["batch_id"] == 7
    assert result["approval_lease_id"] == "approval-lease-1"
    assert result["ordered_target_digest"] == approval_context["ordered_targets"]["digest"]
    assert result["runtime_identity"] == authoritative["runtime_identity"]
    assert token not in repr(result)
    assert token_hash not in repr(result)


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (lambda b, _t, _h, _c, _f: b.update(status="draft"), "BATCH_NOT_APPROVED"),
        (lambda _b, t, _h, _c, _f: t.__setitem__(0, "wrong-token"), "APPROVAL_TOKEN_MISMATCH"),
        (
            lambda _b, _t, _h, c, _f: c.update(fingerprint="0" * 64),
            "APPROVAL_CONTEXT_FINGERPRINT_INVALID",
        ),
        (
            lambda b, _t, _h, _c, _f: b.update(scope_snapshot_digest="0" * 64),
            "BATCH_SCOPE_BINDING_DRIFT",
        ),
        (
            lambda _b, _t, _h, _c, f: f["runtime_identity"].update(instance_id="drift"),
            "RUNTIME_IDENTITY_DRIFT",
        ),
        (
            lambda _b, _t, _h, _c, f: f.update(browser_session_id="drift"),
            "BROWSER_SESSION_DRIFT",
        ),
        (lambda _b, _t, _h, _c, f: f.update(git_head="b" * 40), "GIT_HEAD_DRIFT"),
        (
            lambda _b, _t, _h, _c, f: f["store_identity"].update(store_name="other"),
            "STORE_IDENTITY_DRIFT",
        ),
        (
            lambda _b, _t, _h, _c, f: f["page_identity"].update(kind="listing"),
            "PAGE_IDENTITY_DRIFT",
        ),
    ],
)
def test_authorize_batch_start_fails_closed_on_any_binding_tamper(mutation, reason_code):
    batch, token, token_hash, context = _approved_batch()
    facts, _identity = _facts()
    token_box = [token]
    mutation(batch, token_box, token_hash, context, facts)

    with pytest.raises(BatchExecutionContractError) as exc:
        authorize_batch_start(
            batch,
            approval_token=token_box[0],
            stored_approval_token_hash=token_hash,
            approval_context=context,
            now=NOW,
            authoritative_facts=facts,
        )

    assert exc.value.reason_code == reason_code


def test_authorize_batch_start_rejects_expired_approval_lease():
    batch, token, token_hash, context = _approved_batch()
    facts, _identity = _facts()

    with pytest.raises(BatchExecutionContractError) as exc:
        authorize_batch_start(
            batch,
            approval_token=token,
            stored_approval_token_hash=token_hash,
            approval_context=context,
            now=datetime(2026, 7, 21, 9, 5, tzinfo=timezone.utc),
            authoritative_facts=facts,
        )

    assert exc.value.reason_code == "APPROVAL_LEASE_EXPIRED"


def _start() -> tuple[dict, dict]:
    batch, token, token_hash, context = _approved_batch()
    facts, _identity = _facts()
    start = authorize_batch_start(
        batch,
        approval_token=token,
        stored_approval_token_hash=token_hash,
        approval_context=context,
        now=NOW,
        authoritative_facts=facts,
    )
    # The production grant contract consumes only a durably claimed running
    # item.  Model the repository's start/claim CAS before deriving the grant.
    batch["status"] = "running"
    batch["items"][0]["status"] = "running"
    return batch, start


def test_derive_next_item_grant_issues_only_first_pending_ordinal_with_all_bindings():
    batch, start = _start()

    issued = derive_next_item_grant(
        batch,
        start_context=start,
        now=NOW,
        grant_lease_id="grant-lease-1",
        one_time_nonce="grant-nonce-1",
    )

    grant = issued["grant"]
    assert issued["nonce"] == "grant-nonce-1"
    assert grant["schema_version"] == "dxm_edit_batch_item_grant.v1"
    assert (grant["batch_id"], grant["item_id"], grant["ordinal"]) == (7, 11, 1)
    assert grant["approval_lease_id"] == start["approval_lease_id"]
    assert grant["approval_context_fingerprint"] == start["approval_context_fingerprint"]
    assert grant["scope_digest"] == start["scope_digest"]
    assert grant["template_digest"] == start["template_digest"]
    assert grant["policy_digest"] == start["policy_digest"]
    assert grant["target_identity_sha256"] == batch["items"][0]["target_identity_sha256"]
    assert grant["store_identity"] == start["store_identity"]
    assert grant["runtime_identity"] == start["runtime_identity"]
    assert grant["page_identity"] == start["page_identity"]
    assert len(grant["mutation_scope_id"]) == 64
    assert grant["mutation_scope_id"] == grant["mutation_scope_id"].lower()
    assert grant["mutation_scope_id"] == build_mutation_scope_id(
        authorization_lease_id="grant-lease-1",
        task_id=7,
        job_id=11,
        state="SAVE_ONLY",
        action="save_only",
    )
    assert grant["nonce_hash"] == hashlib.sha256(b"grant-nonce-1").hexdigest().upper()
    unsigned = dict(grant)
    fingerprint = unsigned.pop("fingerprint")
    assert fingerprint == canonical_sha256(unsigned)


@pytest.mark.parametrize(
    ("statuses", "reason_code"),
    [
        (["running", "running"], "MULTIPLE_BATCH_ITEMS_RUNNING"),
        (["pending", "succeeded"], "BATCH_ITEM_ORDER_INVALID"),
        (["failed", "pending"], "BATCH_ITEM_ORDER_INVALID"),
        (["pending", "running"], "BATCH_ITEM_ORDER_INVALID"),
    ],
)
def test_derive_next_item_grant_rejects_running_prior_nonterminal_or_out_of_order(
    statuses, reason_code
):
    batch, start = _start()
    for item, status in zip(batch["items"], statuses):
        item["status"] = status

    with pytest.raises(BatchExecutionContractError) as exc:
        derive_next_item_grant(
            batch,
            start_context=start,
            now=NOW,
            grant_lease_id="grant-lease-1",
            one_time_nonce="grant-nonce-1",
        )

    assert exc.value.reason_code == reason_code


def test_derive_next_item_grant_accepts_running_batch_after_start_cas_and_selects_second_item():
    batch, start = _start()
    batch["items"][0]["status"] = "succeeded"
    batch["items"][1]["status"] = "running"

    issued = derive_next_item_grant(
        batch,
        start_context=start,
        now=NOW,
        grant_lease_id="grant-lease-2",
        one_time_nonce="grant-nonce-2",
    )

    assert issued["grant"]["item_id"] == 12
    assert issued["grant"]["ordinal"] == 2


def test_derive_next_item_grant_rechecks_ordered_target_snapshot_and_digest():
    batch, start = _start()
    batch["items"][0]["item_snapshot"]["target_identity"]["value"] = "tampered"

    with pytest.raises(BatchExecutionContractError) as exc:
        derive_next_item_grant(
            batch,
            start_context=start,
            now=NOW,
            grant_lease_id="grant-lease-1",
            one_time_nonce="grant-nonce-1",
        )

    assert exc.value.reason_code == "BATCH_TARGET_BINDING_DRIFT"


def test_authorize_batch_start_accepts_only_the_safe_public_approval_summary_shape():
    batch, token, token_hash, context = _approved_batch()
    facts, _identity = _facts()
    batch["approval"] = {
        "approved": True,
        "approved_by": context["approved_by"],
        "approved_at": context["issued_at"],
    }

    result = authorize_batch_start(
        batch,
        approval_token=token,
        stored_approval_token_hash=token_hash,
        approval_context=context,
        now=NOW,
        authoritative_facts=facts,
    )

    assert result["batch_id"] == 7
    assert "approval" not in result


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (
            lambda c: c.update(confirmation="CONFIRM_PUBLISH"),
            "APPROVAL_CONFIRMATION_INVALID",
        ),
        (
            lambda c: c.update(expires_at="2026-07-21T09:06:00+00:00"),
            "APPROVAL_LEASE_INTERVAL_INVALID",
        ),
        (
            lambda c: c["read_attestation"].update(status="unknown"),
            "APPROVAL_READ_ATTESTATION_INVALID",
        ),
    ],
)
def test_authorize_batch_start_rejects_invalid_confirmation_lease_or_read_attestation(
    mutation, reason_code
):
    batch, token, token_hash, context = _approved_batch()
    facts, _identity = _facts()
    mutation(context)
    unsigned = dict(context)
    unsigned.pop("fingerprint")
    context["fingerprint"] = canonical_sha256(unsigned)

    with pytest.raises(BatchExecutionContractError) as exc:
        authorize_batch_start(
            batch,
            approval_token=token,
            stored_approval_token_hash=token_hash,
            approval_context=context,
            now=NOW,
            authoritative_facts=facts,
        )

    assert exc.value.reason_code == reason_code


def _issued_grant() -> tuple[dict, str]:
    batch, start = _start()
    issued = derive_next_item_grant(
        batch,
        start_context=start,
        now=NOW,
        grant_lease_id="grant-lease-1",
        one_time_nonce="grant-nonce-1",
    )
    return issued["grant"], issued["nonce"]


def _execution_request(grant: dict) -> dict:
    return {
        "schema_version": "dxm_edit_batch_item_execution_request.v1",
        "action": "SAVE_ONLY",
        "mode": "batch_single_save",
        **{
            key: copy.deepcopy(grant[key])
            for key in (
                "batch_id",
                "item_id",
                "ordinal",
                "approval_lease_id",
                "approval_context_fingerprint",
                "scope_digest",
                "template_digest",
                "policy_digest",
                "target_identity_sha256",
                "store_identity",
                "runtime_identity",
                "browser_session_id",
                "git_head",
                "l2_evidence_fingerprint",
                "page_identity",
                "mutation_scope_id",
                "grant_lease_id",
            )
        },
        "grant_fingerprint": grant["fingerprint"],
    }


def test_validate_and_consume_grant_keeps_the_claimed_item_running():
    grant, nonce = _issued_grant()

    transition = validate_and_consume_item_grant(
        grant,
        raw_nonce=nonce,
        now=NOW,
        request=_execution_request(grant),
        consumed_nonce_hashes=set(),
    )

    assert transition == {
        "schema_version": "dxm_edit_batch_item_grant_consumption.v1",
        "batch_id": 7,
        "item_id": 11,
        "ordinal": 1,
        "from_status": "running",
        "to_status": "running",
        "grant_lease_id": "grant-lease-1",
        "grant_fingerprint": grant["fingerprint"],
        "mutation_scope_id": grant["mutation_scope_id"],
        "consumed_nonce_hash": grant["nonce_hash"],
        "retry_allowed": False,
    }


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (lambda r: r.update(action="PUBLISH"), "ITEM_ACTION_FORBIDDEN"),
        (lambda r: r.update(mode="batch_save"), "ITEM_MODE_FORBIDDEN"),
        (lambda r: r.update(ordinal=2), "GRANT_REQUEST_BINDING_DRIFT"),
        (
            lambda r: r["runtime_identity"].update(browser_runtime_id="drift"),
            "GRANT_REQUEST_BINDING_DRIFT",
        ),
        (
            lambda r: r["page_identity"].update(url="https://example.invalid"),
            "GRANT_REQUEST_BINDING_DRIFT",
        ),
    ],
)
def test_validate_and_consume_grant_rejects_action_mode_or_binding_tampering(
    mutation, reason_code
):
    grant, nonce = _issued_grant()
    request = _execution_request(grant)
    mutation(request)

    with pytest.raises(BatchExecutionContractError) as exc:
        validate_and_consume_item_grant(
            grant,
            raw_nonce=nonce,
            now=NOW,
            request=request,
            consumed_nonce_hashes=set(),
        )

    assert exc.value.reason_code == reason_code


def test_validate_and_consume_grant_rejects_expiry_bad_nonce_and_replay():
    grant, nonce = _issued_grant()
    request = _execution_request(grant)
    cases = (
        ("wrong", NOW, set(), "GRANT_NONCE_MISMATCH"),
        (nonce, datetime(2026, 7, 21, 9, 3, tzinfo=timezone.utc), set(), "GRANT_EXPIRED"),
        (nonce, NOW, {grant["nonce_hash"]}, "GRANT_REPLAY_FORBIDDEN"),
    )
    for raw_nonce, now, consumed, reason_code in cases:
        with pytest.raises(BatchExecutionContractError) as exc:
            validate_and_consume_item_grant(
                grant,
                raw_nonce=raw_nonce,
                now=now,
                request=request,
                consumed_nonce_hashes=consumed,
            )
        assert exc.value.reason_code == reason_code


def test_authorize_batch_start_rejects_consumed_approval_token_replay():
    batch, token, token_hash, context = _approved_batch()
    facts, _identity = _facts()

    with pytest.raises(BatchExecutionContractError) as exc:
        authorize_batch_start(
            batch,
            approval_token=token,
            stored_approval_token_hash=token_hash,
            approval_context=context,
            now=NOW,
            authoritative_facts=facts,
            approval_token_consumed=True,
        )

    assert exc.value.reason_code == "APPROVAL_TOKEN_REPLAY"


def _outcome(grant: dict, *, ok: bool = False) -> dict:
    execution_page = {
        "kind": "semi_managed",
        "url": "https://www.dianxiaomi.com/web/smt/editFromSmt",
        "runtime_id": grant["runtime_identity"]["browser_runtime_id"],
        "browser_session_id": grant["browser_session_id"],
    }
    return {
        "schema_version": "dxm_edit_batch_item_outcome_evidence.v1",
        "ok": ok,
        "error_code": None if ok else "PRE_SAVE_VALIDATION_NO_WRITE",
        "validation_reason": None if ok else "FIELD_VALIDATION_REJECTED",
        "ledger_status": "DISPATCHED" if ok else "RESERVED",
        "network_audit": {
            "complete": True,
            "mutation_request_count": 1 if ok else 0,
            "publish_request_count": 0,
        },
        "publish_signal": {
            "detected": False,
            "kind": "network_route_classification",
        },
        "save_proven": ok,
        "scope_page_identity": copy.deepcopy(grant["page_identity"]),
        "action_page_identity": None,
        "save_page_identity": copy.deepcopy(execution_page) if ok else None,
        "verification_page_identity": copy.deepcopy(execution_page) if ok else None,
        **{
            key: copy.deepcopy(grant[key])
            for key in (
                "runtime_identity",
                "browser_session_id",
                "git_head",
                "l2_evidence_fingerprint",
                "store_identity",
                "target_identity_sha256",
                "mutation_scope_id",
            )
        },
    }


def test_classify_item_outcome_allows_proven_success_and_stops_post_grant_failure():
    grant, _nonce = _issued_grant()

    succeeded = classify_item_outcome(grant, _outcome(grant, ok=True))
    isolated = classify_item_outcome(grant, _outcome(grant))

    assert succeeded["classification"] == "SUCCEEDED"
    assert succeeded["continue_batch"] is True
    assert succeeded["retry_allowed"] is False
    assert isolated["classification"] == "STOPPED_UNCERTAIN"
    assert isolated["continue_batch"] is False
    assert isolated["reason_code"] == "POST_GRANT_FAILURE_REQUIRES_REVIEW"
    assert isolated["retry_allowed"] is False


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    [
        (
            lambda o: o["network_audit"].update(mutation_request_count=1),
            "ZERO_WRITE_PROOF_FALSE",
        ),
        (lambda o: o.update(ledger_status="UNKNOWN"), "MUTATION_OUTCOME_UNCERTAIN"),
        (lambda o: o.update(ledger_status="DISPATCHING"), "MUTATION_OUTCOME_UNCERTAIN"),
        (
            lambda o: o["publish_signal"].update(detected=True, kind="button_click"),
            "PUBLISH_RISK_DETECTED",
        ),
        (
            lambda o: o["network_audit"].update(publish_request_count=1),
            "PUBLISH_RISK_DETECTED",
        ),
        (lambda o: o["network_audit"].update(complete=False), "EVIDENCE_MISSING"),
        (
            lambda o: o.update(validation_reason="NOT_ALLOWLISTED"),
            "POST_GRANT_FAILURE_REQUIRES_REVIEW",
        ),
        (lambda o: o.update(browser_session_id="drift"), "OUTCOME_IDENTITY_DRIFT"),
        (
            lambda o: o["scope_page_identity"].update(url="https://example.invalid"),
            "OUTCOME_IDENTITY_DRIFT",
        ),
        (lambda o: o.update(target_identity_sha256="0" * 64), "OUTCOME_IDENTITY_DRIFT"),
    ],
)
def test_classify_item_outcome_stops_on_false_zero_write_unknown_publish_or_drift(
    mutation, reason_code
):
    grant, _nonce = _issued_grant()
    outcome = _outcome(grant)
    mutation(outcome)

    decision = classify_item_outcome(grant, outcome)

    assert decision["classification"] == "STOPPED_UNCERTAIN"
    assert decision["continue_batch"] is False
    assert decision["retry_allowed"] is False
    assert decision["reason_code"] == reason_code


def test_classify_item_outcome_stops_when_required_evidence_is_missing_or_failure_unclassified():
    grant, _nonce = _issued_grant()
    missing = _outcome(grant)
    missing.pop("network_audit")
    unclassified = _outcome(grant)
    unclassified["error_code"] = "UI_TIMEOUT"

    assert classify_item_outcome(grant, missing)["reason_code"] == "EVIDENCE_MISSING"
    assert classify_item_outcome(grant, unclassified)["reason_code"] == "UNCLASSIFIED_ITEM_FAILURE"
