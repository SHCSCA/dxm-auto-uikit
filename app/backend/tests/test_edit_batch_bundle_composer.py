import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from src import db
from src.main import app
from src.repository import Repository


SECTIONS = (
    "category",
    "sku",
    "pricing",
    "logistics",
    "image",
    "compliance",
    "semi_managed",
    "dxm_reference",
)


def _canonical_sha256(value):
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest().upper()


def _source_digest(template):
    return _canonical_sha256(
        {
            key: template[key]
            for key in (
                "id",
                "template_type",
                "template_name",
                "binding_scope",
                "payload",
                "is_enabled",
                "created_at",
                "updated_at",
            )
        }
    )


def _source_payloads(store_name="DXM Shop A", category_name="车载用品"):
    binding = {
        "store_name": store_name,
        "category_name": category_name,
        "platform": "AliExpress",
    }
    references = {
        name: {"names": [f"{name}-template"], "required": True}
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
    return {
        "category": {"binding": binding, "category": {"category_keyword": category_name}},
        "sku": {"binding": binding, "sku": {"sku_code_strategy": "use_product_or_dxm"}},
        "pricing": {"binding": binding, "pricing": {"retail_price_strategy": "preserve_or_template"}},
        "logistics": {
            "binding": binding,
            "logistics": {"weight": "0.5", "length": "20", "width": "15", "height": "10"},
        },
        "image": {
            "binding": binding,
            "image": {
                "eu_outer_package_filename": "eu-label.jpg",
                "marketing_images_strategy": "preserve_existing",
            },
        },
        "compliance": {"binding": binding, "compliance": {"material": "ABS"}},
        "semi_managed": {
            "binding": binding,
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
        },
        "dxm_reference": {"binding": binding, "dxm_reference_templates": references},
    }


def _setup_composer(tmp_path, monkeypatch, *, db_name="bundle-composer.db"):
    db_path = tmp_path / db_name
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    import src.main as main

    repository = Repository()
    monkeypatch.setattr(main, "repo", repository)
    store = repository.create_store("DXM Shop A", "AliExpress")
    sources = {}
    for section, payload in _source_payloads().items():
        sources[section] = repository.create_template(
            {
                "template_type": section,
                "template_name": f"{section}-source",
                "binding_scope": "DXM Shop A / 车载用品",
                "payload": payload,
                "is_enabled": True,
            }
        )
    return TestClient(app), repository, store, sources


def _selection_from_options(options):
    return {
        section["section"]: {
            "template_id": section["default_candidate"]["template_id"],
            "source_digest": section["default_candidate"]["source_digest"],
        }
        for section in options["sections"]
    }


def test_operator_can_compose_complete_frozen_bundle_from_eight_source_templates(
    tmp_path,
    monkeypatch,
):
    client, _repository, store, _sources = _setup_composer(tmp_path, monkeypatch)

    options_response = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    )
    assert options_response.status_code == 200
    options = options_response.json()
    assert [section["section"] for section in options["sections"]] == list(SECTIONS)
    assert options["ready_count"] == 8
    assert options["ready"] is True
    assert all(section["ready_count"] == 1 for section in options["sections"])
    assert all(section["default_candidate"]["ready"] is True for section in options["sections"])

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "车载商品编辑包",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": _selection_from_options(options),
        },
    )

    assert response.status_code == 201
    bundle = response.json()
    assert bundle["template_type"] == "edit_batch_bundle"
    assert bundle["is_enabled"] is True
    assert set(bundle["payload"]) == {
        "schema_version",
        "version",
        "required_sections",
        "binding",
        "source_templates",
        "sections",
    }
    assert bundle["payload"]["schema_version"] == "dxm_edit_template_bundle.v1"
    assert bundle["payload"]["version"] == "1.0.0"
    assert bundle["payload"]["required_sections"] == list(SECTIONS)
    assert bundle["payload"]["binding"] == {
        "store_id": store["id"],
        "store_name": "DXM Shop A",
        "category_name": "车载用品",
        "platform": "AliExpress",
    }
    assert set(bundle["payload"]["source_templates"]) == set(SECTIONS)
    assert set(bundle["payload"]["sections"]) == set(SECTIONS)
    assert bundle["payload"]["sections"]["dxm_reference"] == {
        "dxm_reference_templates": _source_payloads()["dxm_reference"]["dxm_reference_templates"]
    }
    for source in bundle["payload"]["source_templates"].values():
        assert source["source_digest"]
        assert source["snapshot"]["id"] == source["template_id"]


def test_composer_normalizes_grouped_dxm_reference_source(tmp_path, monkeypatch):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-grouped-dxm-reference.db",
    )
    original = _source_payloads()["dxm_reference"]
    repository.update_template(
        sources["dxm_reference"]["id"],
        {
            "payload": {
                "binding": original["binding"],
                "dxm_reference": {
                    "dxm_reference_templates": original["dxm_reference_templates"],
                },
            }
        },
    )
    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "grouped-reference",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": _selection_from_options(options),
        },
    )

    assert response.status_code == 201
    assert response.json()["payload"]["sections"]["dxm_reference"] == {
        "dxm_reference_templates": original["dxm_reference_templates"]
    }


def test_bundle_composer_supports_store_only_binding_when_category_is_omitted(
    tmp_path,
    monkeypatch,
):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-null-category.db",
    )
    for section, source in sources.items():
        payload = _source_payloads()[section]
        payload["binding"].pop("category_name")
        repository.update_template(
            source["id"],
            {"binding_scope": "DXM Shop A", "payload": payload},
        )

    options_response = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"]},
    )
    assert options_response.status_code == 200
    options = options_response.json()
    assert options["category_name"] is None
    assert options["ready"] is True

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "store-only-bundle",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": None,
            "section_templates": _selection_from_options(options),
        },
    )
    assert response.status_code == 201
    assert response.json()["payload"]["binding"]["category_name"] is None


def test_bundle_composer_requires_existing_store(tmp_path, monkeypatch):
    client, _repository, store, _sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-store-required.db",
    )
    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()

    missing_options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": 999999},
    )
    missing_compose = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "missing-store",
            "version": "1.0.0",
            "store_id": 999999,
            "category_name": "车载用品",
            "section_templates": _selection_from_options(options),
        },
    )
    assert missing_options.status_code == 404
    assert missing_compose.status_code == 404
    assert missing_compose.json()["detail"]["reason_code"] == "STORE_NOT_FOUND"


@pytest.mark.parametrize("shape_error", ["missing_section", "extra_section", "extra_selection_field"])
def test_bundle_composer_requires_exact_eight_section_selection_shape(
    tmp_path,
    monkeypatch,
    shape_error,
):
    client, _repository, store, _sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name=f"bundle-shape-{shape_error}.db",
    )
    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    selection = _selection_from_options(options)
    if shape_error == "missing_section":
        selection.pop("image")
    elif shape_error == "extra_section":
        selection["publish"] = dict(selection["category"])
    else:
        selection["category"]["payload"] = {"category": {"category_keyword": "injected"}}

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "shape-check",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": selection,
        },
    )

    assert response.status_code == 422


def test_bundle_composer_reloads_sources_in_transaction_and_rejects_digest_drift(
    tmp_path,
    monkeypatch,
):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-source-digest-drift.db",
    )
    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    selection = _selection_from_options(options)
    changed_payload = _source_payloads()["pricing"]
    changed_payload["pricing"]["retail_price_strategy"] = "changed-after-options"
    repository.update_template(sources["pricing"]["id"], {"payload": changed_payload})

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "digest-drift",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": selection,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "TEMPLATE_SOURCE_DIGEST_DRIFT"
    assert not [
        template
        for template in repository.list_templates()
        if template["template_type"] == "edit_batch_bundle"
    ]


@pytest.mark.parametrize(
    ("invalid_source", "reason_code"),
    [
        ("disabled", "TEMPLATE_SOURCE_DISABLED"),
        ("wrong_type", "TEMPLATE_SOURCE_TYPE_MISMATCH"),
        ("binding_conflict", "TEMPLATE_SOURCE_BINDING_CONFLICT"),
    ],
)
def test_bundle_composer_rejects_disabled_wrong_type_or_incompatible_source(
    tmp_path,
    monkeypatch,
    invalid_source,
    reason_code,
):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name=f"bundle-invalid-source-{invalid_source}.db",
    )
    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    selection = _selection_from_options(options)
    source_id = sources["category"]["id"]
    if invalid_source == "disabled":
        repository.update_template(source_id, {"is_enabled": False})
    elif invalid_source == "wrong_type":
        repository.update_template(source_id, {"template_type": "pricing"})
    else:
        payload = _source_payloads()["category"]
        payload["binding"]["store_name"] = "Other Store"
        repository.update_template(source_id, {"payload": payload})
    current = repository.get_template(source_id)
    selection["category"] = {
        "template_id": source_id,
        "source_digest": _source_digest(current),
    }

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": f"invalid-{invalid_source}",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": selection,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == reason_code


def test_binding_scope_requires_exact_tokens_and_rejects_store_name_substrings(
    tmp_path,
    monkeypatch,
):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-binding-token-boundary.db",
    )
    valid_options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    selection = _selection_from_options(valid_options)
    category_id = sources["category"]["id"]
    category_payload = {"category": {"category_keyword": "车载用品"}}
    repository.update_template(
        category_id,
        {
            "binding_scope": "notDXM Shop A / 车载用品",
            "payload": category_payload,
        },
    )
    selection["category"]["source_digest"] = _source_digest(repository.get_template(category_id))

    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    category = next(section for section in options["sections"] if section["section"] == "category")
    assert category["candidates"][0]["ready"] is False
    assert "binding" in category["candidates"][0]["missing_fields"]

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "substring-binding",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": selection,
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "TEMPLATE_SOURCE_BINDING_CONFLICT"


def test_options_report_missing_fields_and_composer_rejects_incomplete_configuration(
    tmp_path,
    monkeypatch,
):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-required-field-missing.db",
    )
    valid_options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    selection = _selection_from_options(valid_options)
    payload = _source_payloads()["logistics"]
    payload["logistics"].pop("weight")
    source_id = sources["logistics"]["id"]
    repository.update_template(source_id, {"payload": payload})
    current = repository.get_template(source_id)
    selection["logistics"] = {
        "template_id": source_id,
        "source_digest": _source_digest(current),
    }

    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    logistics = next(section for section in options["sections"] if section["section"] == "logistics")
    assert logistics["ready_count"] == 0
    assert logistics["default_candidate"] is None
    assert logistics["candidates"][0]["ready"] is False
    assert logistics["candidates"][0]["missing_fields"] == ["logistics.weight"]

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "missing-required-field",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": selection,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "TEMPLATE_BUNDLE_INCOMPLETE"
    assert "logistics.weight" in response.json()["detail"]["missing"]


def test_ordinary_source_section_must_be_a_non_empty_nested_object(tmp_path, monkeypatch):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-flat-source-rejected.db",
    )
    valid_options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    selection = _selection_from_options(valid_options)
    category_id = sources["category"]["id"]
    repository.update_template(
        category_id,
        {
            "payload": {
                "binding": _source_payloads()["category"]["binding"],
                "category_keyword": "flat-is-not-accepted",
            }
        },
    )
    selection["category"]["source_digest"] = _source_digest(repository.get_template(category_id))

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "flat-source",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": selection,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "TEMPLATE_SOURCE_INCOMPLETE"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("publish", True),
        ("publish", 1),
        ("publish", "true"),
        ("publish", "false"),
        ("published", True),
        ("should_publish", True),
        ("auto_publish", True),
        ("action", "publish"),
        ("intended_action", "continue_publish"),
        ("target_action", "save_and_publish"),
    ],
)
def test_bundle_composer_recursively_rejects_every_publish_directive(
    tmp_path,
    monkeypatch,
    field,
    value,
):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name=f"bundle-publish-{field}.db",
    )
    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    selection = _selection_from_options(options)
    payload = _source_payloads()["category"]
    payload["category"]["deep"] = {"items": [{field: value}]}
    source_id = sources["category"]["id"]
    repository.update_template(source_id, {"payload": payload})
    selection["category"]["source_digest"] = _source_digest(repository.get_template(source_id))

    response = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": f"publish-{field}",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": selection,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason_code"] == "TEMPLATE_PUBLISH_FORBIDDEN"


def test_bundle_composer_is_idempotent_but_rejects_same_identity_with_new_content(
    tmp_path,
    monkeypatch,
):
    client, repository, store, sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-idempotency.db",
    )
    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    request = {
        "template_name": "stable-identity",
        "version": "1.2.3",
        "store_id": store["id"],
        "category_name": "车载用品",
        "section_templates": _selection_from_options(options),
    }

    first = client.post("/api/template-center/edit-batch-bundles", json=request)
    repeated = client.post("/api/template-center/edit-batch-bundles", json=request)

    assert first.status_code == 201
    assert repeated.status_code == 201
    assert repeated.json()["id"] == first.json()["id"]
    assert first.json()["idempotent"] is False
    assert repeated.json()["idempotent"] is True

    disabled = client.patch(
        f"/api/templates/{first.json()['id']}",
        json={"is_enabled": False},
    )
    assert disabled.status_code == 200
    reactivated = client.post("/api/template-center/edit-batch-bundles", json=request)
    assert reactivated.status_code == 201
    assert reactivated.json()["id"] == first.json()["id"]
    assert reactivated.json()["is_enabled"] is True
    assert reactivated.json()["reactivated"] is True

    changed_payload = _source_payloads()["pricing"]
    changed_payload["pricing"]["retail_price_strategy"] = "new-but-valid-strategy"
    pricing_id = sources["pricing"]["id"]
    repository.update_template(pricing_id, {"payload": changed_payload})
    request["section_templates"]["pricing"]["source_digest"] = _source_digest(
        repository.get_template(pricing_id)
    )
    conflict = client.post("/api/template-center/edit-batch-bundles", json=request)

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reason_code"] == "TEMPLATE_BUNDLE_VERSION_CONFLICT"
    assert len(
        [
            template
            for template in repository.list_templates()
            if template["template_type"] == "edit_batch_bundle"
        ]
    ) == 1


def test_generic_template_api_cannot_create_convert_or_mutate_bundle_content(
    tmp_path,
    monkeypatch,
):
    client, _repository, store, _sources = _setup_composer(
        tmp_path,
        monkeypatch,
        db_name="bundle-generic-api-guard.db",
    )
    direct_create = client.post(
        "/api/templates",
        json={
            "template_type": "edit_batch_bundle",
            "template_name": "bypass",
            "binding_scope": "*",
            "payload": {},
            "is_enabled": True,
        },
    )
    assert direct_create.status_code == 409

    ordinary = client.post(
        "/api/templates",
        json={
            "template_type": "category",
            "template_name": "ordinary",
            "binding_scope": "*",
            "payload": {"category": {"category_keyword": "ordinary"}},
            "is_enabled": True,
        },
    ).json()
    convert = client.patch(
        f"/api/templates/{ordinary['id']}",
        json={"template_type": "edit_batch_bundle"},
    )
    assert convert.status_code == 409

    options = client.get(
        "/api/template-center/edit-batch-bundle-options",
        params={"store_id": store["id"], "category_name": "车载用品"},
    ).json()
    bundle = client.post(
        "/api/template-center/edit-batch-bundles",
        json={
            "template_name": "guarded-bundle",
            "version": "1.0.0",
            "store_id": store["id"],
            "category_name": "车载用品",
            "section_templates": _selection_from_options(options),
        },
    ).json()
    for mutation in (
        {"template_name": "renamed"},
        {"binding_scope": "Other Store"},
        {"payload": {}},
        {"template_type": "category"},
        {"is_enabled": False, "payload": {}},
        {"is_enabled": None},
    ):
        response = client.patch(f"/api/templates/{bundle['id']}", json=mutation)
        assert response.status_code == 409

    disabled = client.patch(
        f"/api/templates/{bundle['id']}",
        json={"is_enabled": False},
    )
    enabled = client.patch(
        f"/api/templates/{bundle['id']}",
        json={"is_enabled": True},
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_enabled"] is False
    assert enabled.status_code == 200
    assert enabled.json()["is_enabled"] is True
    unknown = client.patch(
        f"/api/templates/{bundle['id']}",
        json={"is_enabled": False, "unknown_bundle_field": True},
    )
    assert unknown.status_code == 422
