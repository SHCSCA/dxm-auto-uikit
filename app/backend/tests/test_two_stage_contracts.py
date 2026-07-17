from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from src.state_machine.two_stage import (
    STAGE_A_CONFIRMATION,
    STAGE_B_CONFIRMATION,
    TwoStageContractError,
    authorization_context_fingerprint,
    build_authorization_context,
    build_draft_box_proof,
    build_stage_a_task_facts,
    build_stage_b_task_facts,
    canonical_claim_target_identity,
    canonical_source_identity,
    compare_authorization_context,
    verify_authorization_context,
    verify_draft_box_proof,
    verify_exact_stage_task_facts,
)


def test_source_identity_is_deterministic_without_rewriting_meaningful_query():
    first = canonical_source_identity(
        " HTTPS://Example.COM:443/item/42?b=2&a=1#draft-row ",
        [
            "https://example.com/item/42?b=2&a=1#other-fragment",
            " https://example.com/item/7?sku=B&A=CaseSensitive ",
            "https://example.com/item/7?sku=B&A=CaseSensitive",
        ],
    )
    second = canonical_source_identity(
        "https://example.com/item/42?b=2&a=1",
        reversed(
            [
                "https://example.com/item/7?sku=B&A=CaseSensitive",
                "https://example.com/item/42?b=2&a=1",
            ]
        ),
    )

    assert first == second
    assert first["primary_url"] == "https://example.com/item/42?b=2&a=1"
    assert first["urls"] == [
        "https://example.com/item/42?b=2&a=1",
        "https://example.com/item/7?sku=B&A=CaseSensitive",
    ]
    assert len(first["fingerprint"]) == 64
    assert first["fingerprint"] == first["fingerprint"].upper()


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/item has-space",
        "https://example.com/item?bad=%ZZ",
        "https://example.com/item\nnext",
        "https://bad_host.example/item",
        "https://-bad.example/item",
        "https://bad..example/item",
    ],
)
def test_source_identity_rejects_unsafe_or_invalid_urls(url):
    with pytest.raises(TwoStageContractError) as error:
        canonical_source_identity(url)

    assert error.value.reason_code == "SOURCE_URL_INVALID"


def test_claim_target_identity_supports_hint_only_without_inventing_a_source_url():
    first = canonical_claim_target_identity(
        keyword="  Pokemon   acrylic stand ",
        category_name="  立牌  ",
    )
    second = canonical_claim_target_identity(
        keyword="Pokemon acrylic stand",
        category_name="立牌",
    )

    assert first == second
    assert first["source_identity"] is None
    assert first["keyword"] == "Pokemon acrylic stand"
    assert first["category_name"] == "立牌"
    assert len(first["fingerprint"]) == 64


def test_stage_a_facts_bind_hint_only_target_identity():
    target = canonical_claim_target_identity(keyword="Pokemon stand", category_name="立牌")

    facts = build_stage_a_task_facts(
        task_id=71,
        job_id=72,
        store_id=73,
        target_identity=target,
    )

    assert facts["target_identity"] == target
    assert "source_identity" not in facts
    assert verify_exact_stage_task_facts(facts, expected_stage="stage_a") == {
        "ok": True,
        "reason_code": "OK",
    }


_UNSET = object()


def _evidence_ref(name: str = "draft-row.png") -> dict:
    content = b"test-draft-box-evidence"
    return {
        "path": str((Path.cwd() / name).resolve()),
        "sha256": hashlib.sha256(content).hexdigest().upper(),
        "size": len(content),
    }


def _bound_draft_box_observation(
    target,
    *,
    store_id,
    observed_source_identity=_UNSET,
    **changes,
):
    authorized_source = target["source_identity"]
    if authorized_source is not None:
        observed_source = (
            authorized_source
            if observed_source_identity is _UNSET
            else observed_source_identity
        )
        matched_by = ["source_url"]
        match_evidence = {"source_url": observed_source["primary_url"]}
        default_product_identity = "product-893543996663"
        default_row_identity = "draft-row-893543996663 Dang Kang"
    else:
        observed_source = (
            canonical_source_identity(
                f"https://example.com/observed/{target['fingerprint'].lower()}"
            )
            if observed_source_identity is _UNSET
            else observed_source_identity
        )
        matched_by = [
            key
            for key in ("keyword", "category_name")
            if target.get(key) is not None
        ]
        match_evidence = {key: target[key] for key in matched_by}
        identity_text = " ".join(target[key] for key in matched_by)
        default_product_identity = f"Observed product {identity_text}"
        default_row_identity = f"DXM draft row {identity_text} Dang Kang"
    observation = {
        "schema": "dxm.draft_box.observation.v1",
        "verification_state": "VERIFY_DRAFT_BOX_CLAIM",
        "action": "verify_draft_box_claim",
        "draft_box_verified": True,
        "page_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft?status=0",
        "authorized_target_identity": target,
        "authorized_target_fingerprint": target["fingerprint"],
        "observed_source_identity": observed_source,
        "matched_by": matched_by,
        "match_evidence": match_evidence,
        "observed_product_identity": default_product_identity,
        "observed_row_identity": default_row_identity,
        "evidence_ref": _evidence_ref(),
    }
    observation.update(changes)
    if "observed_store_identity" not in changes:
        observation["observed_store_identity"] = {
            "store_id": store_id,
            "store_name": "Dang Kang",
            "selected": True,
            "selected_store_names": ["Dang Kang"],
            "selection_evidence": {"input_checked": True},
            "draft_box_cell_evidence": {
                "store_name": "Dang Kang",
                "cell_text": "「Dang Kang」",
                "source": "structured_store_cell",
            },
        }
    return observation


def test_draft_box_proof_uses_structured_store_cell_instead_of_row_text():
    source = canonical_source_identity("https://example.com/product/structured-store")
    target = canonical_claim_target_identity(source_url=source["primary_url"])
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target,
    )
    observation = _bound_draft_box_observation(
        target,
        store_id=13,
        observed_row_identity="draft-row-product-structured-store",
        observed_store_identity={
            "store_id": 13,
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
    )

    proof = build_draft_box_proof(
        stage_a_task_facts=stage_a,
        product_id=14,
        proof_content=observation,
    )

    assert proof["proof_content"]["observed_row_identity"] == "draft-row-product-structured-store"
    assert proof["proof_content"]["observed_store_identity"] == observation["observed_store_identity"]


def test_draft_box_proof_deduplicates_the_exact_selected_store():
    source = canonical_source_identity("https://example.com/product/deduplicated-store")
    target = canonical_claim_target_identity(source_url=source["primary_url"])
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target,
    )
    observation = _bound_draft_box_observation(target, store_id=13)
    observation["observed_store_identity"]["selected_store_names"] = [
        "Dang Kang",
        "Dang Kang",
    ]

    proof = build_draft_box_proof(
        stage_a_task_facts=stage_a,
        product_id=14,
        proof_content=observation,
    )

    assert proof["proof_content"]["observed_store_identity"]["selected_store_names"] == [
        "Dang Kang"
    ]


@pytest.mark.parametrize(
    ("invalid_store_proof", "reason_code"),
    [
        ("missing_selected_store_names", "DRAFT_BOX_OBSERVED_STORE_SHAPE_MISMATCH"),
        ("selected_store_names_string", "DRAFT_BOX_SELECTED_STORE_NAMES_INVALID"),
        ("multiple_selected_stores", "DRAFT_BOX_SELECTED_STORE_SET_MISMATCH"),
        ("selection_evidence_string", "DRAFT_BOX_STORE_SELECTION_EVIDENCE_REQUIRED"),
        ("store_cell_string", "DRAFT_BOX_STORE_CELL_EVIDENCE_REQUIRED"),
        ("wrong_cell_source", "DRAFT_BOX_STORE_CELL_SOURCE_INVALID"),
        ("wrong_cell_store", "DRAFT_BOX_STORE_CELL_NAME_MISMATCH"),
        ("wrong_cell_text_boundary", "DRAFT_BOX_STORE_CELL_TEXT_MISMATCH"),
    ],
)
def test_draft_box_proof_rejects_malformed_structured_store_evidence(
    invalid_store_proof,
    reason_code,
):
    source = canonical_source_identity("https://example.com/product/invalid-store-proof")
    target = canonical_claim_target_identity(source_url=source["primary_url"])
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target,
    )
    observation = _bound_draft_box_observation(target, store_id=13)
    store_proof = observation["observed_store_identity"]
    cell = store_proof["draft_box_cell_evidence"]
    if invalid_store_proof == "missing_selected_store_names":
        store_proof.pop("selected_store_names")
    elif invalid_store_proof == "selected_store_names_string":
        store_proof["selected_store_names"] = "Dang Kang"
    elif invalid_store_proof == "multiple_selected_stores":
        store_proof["selected_store_names"] = ["Dang Kang", "Another Store"]
    elif invalid_store_proof == "selection_evidence_string":
        store_proof["selection_evidence"] = "input_checked=true"
    elif invalid_store_proof == "store_cell_string":
        store_proof["draft_box_cell_evidence"] = "Dang Kang"
    elif invalid_store_proof == "wrong_cell_source":
        cell["source"] = "draft_box_row_text"
    elif invalid_store_proof == "wrong_cell_store":
        cell["store_name"] = "Another Store"
    elif invalid_store_proof == "wrong_cell_text_boundary":
        cell["cell_text"] = "Dang KangPlus"

    with pytest.raises(TwoStageContractError) as error:
        build_draft_box_proof(
            stage_a_task_facts=stage_a,
            product_id=14,
            proof_content=observation,
        )

    assert error.value.reason_code == reason_code


def test_draft_box_proof_rejects_url_b_under_url_a_stage_a_authorization():
    source_a = canonical_source_identity("https://example.com/product/A")
    source_b = canonical_source_identity("https://example.com/product/B")
    target_a = canonical_claim_target_identity(source_url=source_a["primary_url"])
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target_a,
    )

    with pytest.raises(TwoStageContractError) as error:
        build_draft_box_proof(
            stage_a_task_facts=stage_a,
            product_id=14,
            proof_content=_bound_draft_box_observation(
                target_a,
                store_id=13,
                observed_source_identity=source_b,
            ),
        )

    assert error.value.reason_code == "DRAFT_BOX_OBSERVED_SOURCE_UNAUTHORIZED"


def test_hint_only_proof_rejects_store_target_and_match_evidence_drift():
    target = canonical_claim_target_identity(keyword="Pokemon stand", category_name="立牌")
    other_target = canonical_claim_target_identity(keyword="Other product", category_name="立牌")
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=99,
        target_identity=target,
    )
    cases = [
        (
            _bound_draft_box_observation(target, store_id=3),
            "DRAFT_BOX_OBSERVED_STORE_MISMATCH",
        ),
        (
            _bound_draft_box_observation(other_target, store_id=99),
            "DRAFT_BOX_AUTHORIZED_TARGET_MISMATCH",
        ),
        (
            _bound_draft_box_observation(target, store_id=99, match_evidence={}),
            "DRAFT_BOX_MATCH_EVIDENCE_MISMATCH",
        ),
        (
            _bound_draft_box_observation(
                target,
                store_id=99,
                matched_by=["category_name"],
                match_evidence={"category_name": "立牌"},
            ),
            "DRAFT_BOX_MATCH_EVIDENCE_MISMATCH",
        ),
        (
            _bound_draft_box_observation(
                target,
                store_id=99,
                observed_store_identity={
                    "store_id": True,
                    "store_name": "Dang Kang",
                    "selected": True,
                    "selected_store_names": ["Dang Kang"],
                    "selection_evidence": {"input_checked": True},
                    "draft_box_cell_evidence": {
                        "store_name": "Dang Kang",
                        "cell_text": "Dang Kang",
                        "source": "structured_store_cell",
                    },
                },
            ),
            "OBSERVED_STORE_ID_INVALID",
        ),
        (
            _bound_draft_box_observation(
                target,
                store_id=99,
                observed_store_identity={
                    "store_id": 99,
                    "store_name": "Dang Kang",
                    "selected": True,
                    "selected_store_names": ["Dang Kang"],
                    "selection_evidence": {"input_checked": False, "aria_checked": "false"},
                    "draft_box_cell_evidence": {
                        "store_name": "Dang Kang",
                        "cell_text": "Dang Kang",
                        "source": "structured_store_cell",
                    },
                },
            ),
            "DRAFT_BOX_STORE_SELECTION_EVIDENCE_INVALID",
        ),
    ]

    for observation, reason_code in cases:
        with pytest.raises(TwoStageContractError) as error:
            build_draft_box_proof(
                stage_a_task_facts=stage_a,
                product_id=14,
                proof_content=observation,
            )
        assert error.value.reason_code == reason_code


@pytest.mark.parametrize(
    ("target", "reason_code"),
    [
        (
            canonical_claim_target_identity(keyword="Pokemon stand", category_name="立牌"),
            "DRAFT_BOX_REQUIRED_HINT_NOT_OBSERVED",
        ),
        (
            canonical_claim_target_identity(category_name="立牌"),
            "DRAFT_BOX_REQUIRED_HINT_NOT_OBSERVED",
        ),
    ],
)
def test_hint_observation_rejects_unrelated_product_even_when_claimed_match_echoes_target(
    target,
    reason_code,
):
    observed_source = canonical_source_identity("https://example.com/observed/product-14")
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target,
    )
    observation = _bound_draft_box_observation(
        target,
        store_id=13,
        observed_source_identity=observed_source,
        observed_product_identity="完全无关商品",
        observed_row_identity="完全无关商品",
    )

    with pytest.raises(TwoStageContractError) as error:
        build_draft_box_proof(
            stage_a_task_facts=stage_a,
            product_id=14,
            proof_content=observation,
        )

    assert error.value.reason_code == reason_code


def test_hint_observation_requires_real_observed_source_identity():
    target = canonical_claim_target_identity(keyword="Pokemon stand")
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target,
    )

    with pytest.raises(TwoStageContractError) as error:
        build_draft_box_proof(
            stage_a_task_facts=stage_a,
            product_id=14,
            proof_content=_bound_draft_box_observation(
                target,
                store_id=13,
                observed_source_identity=None,
                observed_product_identity="POKEMON   STAND",
                observed_row_identity="pokemon stand",
            ),
        )

    assert error.value.reason_code == "DRAFT_BOX_OBSERVED_SOURCE_REQUIRED"


def test_hint_observation_matches_by_collapsed_whitespace_and_casefold_only():
    target = canonical_claim_target_identity(keyword="Pokemon stand", category_name="立牌")
    observed_source = canonical_source_identity("https://example.com/observed/product-14")
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target,
    )
    observation = _bound_draft_box_observation(
        target,
        store_id=13,
        observed_source_identity=observed_source,
        observed_product_identity="SKU-14  POKEMON    STAND",
        observed_row_identity="商品箱行：立牌",
    )

    proof = build_draft_box_proof(
        stage_a_task_facts=stage_a,
        product_id=14,
        proof_content=observation,
    )

    assert proof["proof_content"]["matched_by"] == ["keyword", "category_name"]
    assert verify_draft_box_proof(
        proof,
        stage_a_task_facts=stage_a,
        product_id=14,
    ) == {"ok": True, "reason_code": "OK"}


def test_hint_observation_does_not_accept_latin_substring_inside_another_word():
    target = canonical_claim_target_identity(keyword="stand")
    observed_source = canonical_source_identity("https://example.com/observed/product-14")
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target,
    )

    with pytest.raises(TwoStageContractError) as error:
        build_draft_box_proof(
            stage_a_task_facts=stage_a,
            product_id=14,
            proof_content=_bound_draft_box_observation(
                target,
                store_id=13,
                observed_source_identity=observed_source,
                observed_product_identity="an understandable product",
                observed_row_identity="understanding",
            ),
        )

    assert error.value.reason_code == "DRAFT_BOX_REQUIRED_HINT_NOT_OBSERVED"


def test_hint_only_stage_b_preserves_stage_a_target_and_proof_fingerprints():
    target = canonical_claim_target_identity(keyword="Pokemon stand", category_name="立牌")
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=target,
    )
    proof = build_draft_box_proof(
        stage_a_task_facts=stage_a,
        product_id=14,
        proof_content=_bound_draft_box_observation(target, store_id=13),
    )
    stage_b = build_stage_b_task_facts(
        task_id=21,
        job_id=22,
        store_id=13,
        product_id=14,
        stage_a_task_facts=stage_a,
        draft_box_proof=proof,
    )

    assert stage_b["source_identity"] == proof["proof_content"]["observed_source_identity"]
    assert stage_b["target_identity"] == target
    assert stage_b["claim_target_fingerprint"] == target["fingerprint"]
    assert stage_b["stage_a_task_facts_fingerprint"] == stage_a["fingerprint"]
    assert stage_b["draft_box_proof_fingerprint"] == proof["fingerprint"]
    assert verify_exact_stage_task_facts(stage_b, expected_stage="stage_b") == {
        "ok": True,
        "reason_code": "OK",
    }


def test_stage_b_rejects_store_or_stage_a_target_drift_from_proof():
    source, proof = _draft_box_proof_fixture()
    stage_a = _stage_a_for_source(source)
    other_stage_a = _stage_a_for_source(
        canonical_source_identity("https://example.com/source?id=other")
    )

    with pytest.raises(TwoStageContractError) as store_error:
        build_stage_b_task_facts(
            task_id=21,
            job_id=22,
            store_id=99,
            product_id=14,
            stage_a_task_facts=stage_a,
            draft_box_proof=proof,
        )
    assert store_error.value.reason_code == "STAGE_B_STORE_MISMATCH"

    with pytest.raises(TwoStageContractError) as target_error:
        build_stage_b_task_facts(
            task_id=21,
            job_id=22,
            store_id=13,
            product_id=14,
            stage_a_task_facts=other_stage_a,
            draft_box_proof=proof,
        )
    assert target_error.value.reason_code == "DRAFT_BOX_PROOF_TARGET_MISMATCH"


def test_draft_box_proof_binds_verified_content_and_exact_claim_facts():
    source = canonical_source_identity(
        "https://mobile.yangkeduo.com/goods2.html?goods_id=893543996663"
    )
    target = canonical_claim_target_identity(source_url=source["primary_url"])
    stage_a = build_stage_a_task_facts(
        task_id=41,
        job_id=52,
        store_id=7,
        target_identity=target,
    )
    proof = build_draft_box_proof(
        stage_a_task_facts=stage_a,
        product_id=63,
        proof_content=_bound_draft_box_observation(target, store_id=7),
    )

    result = verify_draft_box_proof(
        proof,
        stage_a_task_facts=stage_a,
        product_id=63,
    )

    assert result == {"ok": True, "reason_code": "OK"}
    assert proof["proof_content_sha256"] == proof["proof_content_sha256"].upper()
    assert len(proof["proof_content_sha256"]) == 64
    assert len(proof["fingerprint"]) == 64
    json.dumps(proof, ensure_ascii=False, allow_nan=False)


def _draft_box_proof_fixture():
    source = canonical_source_identity("https://example.com/source?id=100&ref=kept")
    stage_a = _stage_a_for_source(source)
    proof = build_draft_box_proof(
        stage_a_task_facts=stage_a,
        product_id=14,
        proof_content=_bound_draft_box_observation(
            stage_a["target_identity"],
            store_id=13,
            observed_product_identity="product-100",
            observed_row_identity="draft-100",
        ),
    )
    return source, proof


def _claim_target_from_source(source):
    return canonical_claim_target_identity(
        source_url=source["primary_url"],
        source_urls=source["urls"],
    )


def _stage_a_for_source(source, *, task_id=11, job_id=12, store_id=13):
    return build_stage_a_task_facts(
        task_id=task_id,
        job_id=job_id,
        store_id=store_id,
        target_identity=_claim_target_from_source(source),
    )


def test_draft_box_proof_rejects_arbitrary_self_assertion_content():
    source = canonical_source_identity("https://example.com/source?id=100")
    stage_a = _stage_a_for_source(source)

    with pytest.raises(TwoStageContractError) as error:
        build_draft_box_proof(
            stage_a_task_facts=stage_a,
            product_id=14,
            proof_content={"draft_box_verified": True, "row_key": "claimed"},
        )

    assert error.value.reason_code == "DRAFT_BOX_PROOF_CONTENT_SHAPE_MISMATCH"


def test_draft_box_proof_requires_exact_verified_dxm_observation_facts():
    source = canonical_source_identity("https://example.com/source?id=100")
    other_source = canonical_source_identity("https://example.com/source?id=other")
    stage_a = _stage_a_for_source(source)
    target = stage_a["target_identity"]
    cases = [
        ({"verification_state": "DONE"}, "DRAFT_BOX_OBSERVATION_STATE_MISMATCH"),
        ({"action": "claim"}, "DRAFT_BOX_OBSERVATION_ACTION_MISMATCH"),
        ({"draft_box_verified": False}, "DRAFT_BOX_NOT_VERIFIED"),
        (
            {"page_url": "https://evil.example/web/smt/smtProductList/draft"},
            "DRAFT_BOX_PAGE_URL_INVALID",
        ),
        ({"observed_source_identity": other_source}, "DRAFT_BOX_OBSERVED_SOURCE_UNAUTHORIZED"),
        ({"observed_product_identity": "  "}, "OBSERVED_PRODUCT_IDENTITY_REQUIRED"),
        ({"observed_row_identity": ""}, "OBSERVED_ROW_IDENTITY_REQUIRED"),
        ({"evidence_ref": ""}, "EVIDENCE_REF_SHAPE_MISMATCH"),
    ]

    for changes, reason_code in cases:
        with pytest.raises(TwoStageContractError) as error:
            build_draft_box_proof(
                stage_a_task_facts=stage_a,
                product_id=14,
                proof_content=_bound_draft_box_observation(
                    target,
                    store_id=13,
                    **changes,
                ),
            )
        assert error.value.reason_code == reason_code


def test_draft_box_proof_rejects_tampered_binding_and_content_hashes():
    source, proof = _draft_box_proof_fixture()
    stage_a = _stage_a_for_source(source)
    tampered_store = copy.deepcopy(proof)
    tampered_store["store_id"] = 99
    tampered_content = copy.deepcopy(proof)
    tampered_content["proof_content"]["observed_row_identity"] = "other-row"
    tampered_store_cell = copy.deepcopy(proof)
    tampered_store_cell["proof_content"]["observed_store_identity"][
        "draft_box_cell_evidence"
    ]["cell_text"] = "Another Store"
    tampered_hash = copy.deepcopy(proof)
    tampered_hash["proof_content_sha256"] = "0" * 64

    assert verify_draft_box_proof(
        tampered_store,
        stage_a_task_facts=stage_a,
        product_id=14,
    )["reason_code"] == "DRAFT_BOX_PROOF_STORE_MISMATCH"
    for changed in (tampered_content, tampered_store_cell, tampered_hash):
        assert verify_draft_box_proof(
            changed,
            stage_a_task_facts=stage_a,
            product_id=14,
        )["reason_code"] == "DRAFT_BOX_PROOF_CONTENT_DIGEST_MISMATCH"


def test_draft_box_proof_rejects_wrong_expected_task_job_store_product_or_source():
    source, proof = _draft_box_proof_fixture()
    other_source = canonical_source_identity("https://example.com/source?id=other")
    cases = [
        (_stage_a_for_source(source, task_id=99), 14, "DRAFT_BOX_PROOF_TASK_MISMATCH"),
        (_stage_a_for_source(source, job_id=99), 14, "DRAFT_BOX_PROOF_JOB_MISMATCH"),
        (_stage_a_for_source(source, store_id=99), 14, "DRAFT_BOX_PROOF_STORE_MISMATCH"),
        (_stage_a_for_source(source), 99, "DRAFT_BOX_PROOF_PRODUCT_MISMATCH"),
        (_stage_a_for_source(other_source), 14, "DRAFT_BOX_PROOF_TARGET_MISMATCH"),
    ]

    for stage_a, product_id, reason_code in cases:
        result = verify_draft_box_proof(
            proof,
            stage_a_task_facts=stage_a,
            product_id=product_id,
        )
        assert result == {"ok": False, "reason_code": reason_code}


def test_draft_box_proof_rejects_invalid_expected_ids_before_comparison():
    source, proof = _draft_box_proof_fixture()
    stage_a = _stage_a_for_source(source)
    result = verify_draft_box_proof(
        proof,
        stage_a_task_facts=stage_a,
        product_id=True,
    )
    assert result == {
        "ok": False,
        "reason_code": "EXPECTED_PRODUCT_ID_INVALID",
    }

    for field_name in ("task_id", "job_id", "store_id"):
        with pytest.raises(TwoStageContractError) as error:
            build_stage_a_task_facts(
                task_id=True if field_name == "task_id" else 11,
                job_id=True if field_name == "job_id" else 12,
                store_id=True if field_name == "store_id" else 13,
                target_identity=_claim_target_from_source(source),
            )
        assert error.value.reason_code == f"{field_name.upper()}_INVALID"


def test_stage_a_and_b_facts_are_exact_and_link_b_to_the_verified_claim():
    source, proof = _draft_box_proof_fixture()
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=_claim_target_from_source(source),
    )
    stage_b = build_stage_b_task_facts(
        task_id=21,
        job_id=22,
        store_id=13,
        product_id=14,
        stage_a_task_facts=stage_a,
        draft_box_proof=proof,
    )

    assert stage_a["stage"] == "stage_a"
    assert stage_a["mode"] == "claim_only"
    assert stage_a["confirmation"] == STAGE_A_CONFIRMATION
    assert stage_a["action"] == "claim_to_draft"
    assert stage_b["stage"] == "stage_b"
    assert stage_b["mode"] == "single_save"
    assert stage_b["confirmation"] == STAGE_B_CONFIRMATION
    assert stage_b["action"] == "save_only"
    assert stage_b["claim_task_id"] == stage_a["task_id"]
    assert stage_b["claim_job_id"] == stage_a["job_id"]
    assert stage_b["draft_box_proof_fingerprint"] == proof["fingerprint"]
    assert stage_b["target_identity"] == stage_a["target_identity"]
    assert stage_b["claim_target_fingerprint"] == stage_a["target_identity"]["fingerprint"]
    assert verify_exact_stage_task_facts(stage_a, expected_stage="stage_a") == {
        "ok": True,
        "reason_code": "OK",
    }
    assert verify_exact_stage_task_facts(stage_b, expected_stage="stage_b") == {
        "ok": True,
        "reason_code": "OK",
    }
    json.dumps([stage_a, stage_b], ensure_ascii=False, allow_nan=False)


def test_stage_a_and_b_mode_and_confirmation_are_not_interchangeable():
    source, proof = _draft_box_proof_fixture()
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=_claim_target_from_source(source),
    )
    stage_b = build_stage_b_task_facts(
        task_id=21,
        job_id=22,
        store_id=13,
        product_id=14,
        stage_a_task_facts=stage_a,
        draft_box_proof=proof,
    )

    for original, expected_stage, field_name, wrong_value in (
        (stage_a, "stage_a", "mode", "single_save"),
        (stage_a, "stage_a", "confirmation", STAGE_B_CONFIRMATION),
        (stage_b, "stage_b", "mode", "claim_only"),
        (stage_b, "stage_b", "confirmation", STAGE_A_CONFIRMATION),
    ):
        changed = copy.deepcopy(original)
        changed[field_name] = wrong_value
        result = verify_exact_stage_task_facts(changed, expected_stage=expected_stage)
        assert result == {
            "ok": False,
            "reason_code": f"STAGE_TASK_FACTS_{field_name.upper()}_MISMATCH",
        }

    assert verify_exact_stage_task_facts(stage_a, expected_stage="stage_b") == {
        "ok": False,
        "reason_code": "STAGE_TASK_FACTS_STAGE_MISMATCH",
    }
    assert verify_exact_stage_task_facts(stage_b, expected_stage="stage_a") == {
        "ok": False,
        "reason_code": "STAGE_TASK_FACTS_STAGE_MISMATCH",
    }


def test_authorization_context_fingerprint_binds_task_store_session_head_and_approver():
    source, _proof = _draft_box_proof_fixture()
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=_claim_target_from_source(source),
    )
    context = build_authorization_context(
        stage_task_facts=stage_a,
        runtime_instance_id="backend-instance-a",
        browser_session_id="browser-session-a",
        git_head="a" * 40,
        l2_evidence_fingerprint="C" * 64,
        approved_by="张三",
    )

    assert context["fingerprint"] == authorization_context_fingerprint(context)
    assert len(context["fingerprint"]) == 64
    assert verify_authorization_context(context) == {"ok": True, "reason_code": "OK"}
    assert compare_authorization_context(context, copy.deepcopy(context)) == {
        "ok": True,
        "reason_code": "OK",
    }
    json.dumps(context, ensure_ascii=False, allow_nan=False)


def test_authorization_context_rejects_cross_task_store_session_head_and_tampering():
    source, _proof = _draft_box_proof_fixture()

    def context_for(
        *,
        task_id=11,
        store_id=13,
        browser_session_id="browser-a",
        git_head="a" * 40,
        l2_evidence_fingerprint="C" * 64,
    ):
        facts = build_stage_a_task_facts(
            task_id=task_id,
            job_id=12,
            store_id=store_id,
            target_identity=_claim_target_from_source(source),
        )
        return build_authorization_context(
            stage_task_facts=facts,
            runtime_instance_id="runtime-a",
            browser_session_id=browser_session_id,
            git_head=git_head,
            l2_evidence_fingerprint=l2_evidence_fingerprint,
            approved_by="ops-owner",
        )

    expected = context_for()
    for actual in (
        context_for(task_id=99),
        context_for(store_id=99),
        context_for(browser_session_id="browser-b"),
        context_for(git_head="b" * 40),
        context_for(l2_evidence_fingerprint="D" * 64),
    ):
        assert compare_authorization_context(expected, actual) == {
            "ok": False,
            "reason_code": "AUTH_CONTEXT_MISMATCH",
        }

    tampered = copy.deepcopy(expected)
    tampered["approved_by"] = "other-operator"
    assert verify_authorization_context(tampered) == {
        "ok": False,
        "reason_code": "AUTH_CONTEXT_FINGERPRINT_MISMATCH",
    }


def test_authorization_context_distinguishes_url_and_hint_only_stage_a_targets():
    source, _proof = _draft_box_proof_fixture()
    url_facts = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=_claim_target_from_source(source),
    )
    hint_facts = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=canonical_claim_target_identity(keyword="Pokemon stand", category_name="立牌"),
    )

    def authorize(facts):
        return build_authorization_context(
            stage_task_facts=facts,
            runtime_instance_id="runtime-a",
            browser_session_id="browser-a",
            git_head="a" * 40,
            l2_evidence_fingerprint="C" * 64,
            approved_by="ops-owner",
        )

    assert compare_authorization_context(authorize(url_facts), authorize(hint_facts)) == {
        "ok": False,
        "reason_code": "AUTH_CONTEXT_MISMATCH",
    }


def test_all_verifiers_convert_type_and_serialization_failures_to_reason_codes():
    class ExplodingMapping(dict):
        def get(self, *_args, **_kwargs):
            raise TypeError("malformed mapping")

    source, proof = _draft_box_proof_fixture()
    stage_a = build_stage_a_task_facts(
        task_id=11,
        job_id=12,
        store_id=13,
        target_identity=_claim_target_from_source(source),
    )
    auth = build_authorization_context(
        stage_task_facts=stage_a,
        runtime_instance_id="runtime-a",
        browser_session_id="browser-a",
        git_head="a" * 40,
        l2_evidence_fingerprint="C" * 64,
        approved_by="ops-owner",
    )

    assert verify_draft_box_proof(
        ExplodingMapping(proof),
        stage_a_task_facts=stage_a,
        product_id=14,
    ) == {"ok": False, "reason_code": "DRAFT_BOX_PROOF_INVALID_VALUE"}
    assert verify_exact_stage_task_facts(
        ExplodingMapping(stage_a),
        expected_stage="stage_a",
    ) == {"ok": False, "reason_code": "STAGE_TASK_FACTS_INVALID_VALUE"}
    assert verify_authorization_context(ExplodingMapping(auth)) == {
        "ok": False,
        "reason_code": "AUTH_CONTEXT_INVALID_VALUE",
    }
