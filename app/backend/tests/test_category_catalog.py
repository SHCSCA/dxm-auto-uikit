import json
from pathlib import Path

import pytest

from src.services.category_catalog import CategoryCatalog, CategoryCatalogError


DIRECTORY = Path(__file__).resolve().parents[3] / "resources/dxm/category-catalog"


@pytest.fixture(scope="module")
def catalog():
    return CategoryCatalog(DIRECTORY)


def test_deep_leaf_keeps_its_entire_reference_ancestry(catalog):
    document = json.loads((DIRECTORY / "category-catalog.v1.json").read_text(encoding="utf-8-sig"))
    node = max((row for row in document["nodes"] if row["executableLeaf"]), key=lambda row: row["derivedDepth"])
    result = catalog.annotate({"categoryId": node["categoryId"], "isleaf": 1,
                               "nodePathId": ",".join(node["nodePathIds"])})
    assert result["executableLeaf"] is True
    assert len(result["catalogNodePathIds"]) >= 4
    assert result["catalogSha256"] == catalog.digest
    assert catalog.get(node["categoryId"])["nodePathIds"] == node["nodePathIds"]


def test_catalog_conflicts_and_live_drift_cannot_become_executable(catalog):
    document = json.loads((DIRECTORY / "category-catalog.v1.json").read_text(encoding="utf-8-sig"))
    conflicts = [row for row in document["nodes"] if row["isLeaf"] and not row["executableLeaf"]]
    assert len(conflicts) == 12
    for node in conflicts:
        assert catalog.annotate({"categoryId": node["categoryId"], "isleaf": 1})["executableLeaf"] is False
    node = next(row for row in document["nodes"] if row["executableLeaf"])
    assert catalog.annotate({"categoryId": node["categoryId"], "isleaf": 0})["executableLeaf"] is False
    assert catalog.annotate({"categoryId": node["categoryId"], "isleaf": 1,
                             "nodePathId": "999999999"})["catalogStatus"] == "LIVE_ANCESTOR_DRIFT"
    assert catalog.annotate({"categoryId": "999999999", "isleaf": 1})["executableLeaf"] is False


def test_catalog_tampering_is_rejected_before_any_node_is_used(tmp_path):
    (tmp_path / "category-catalog.manifest.json").write_text(json.dumps({"catalog": {"sha256": "0" * 64}}))
    (tmp_path / "category-catalog.v1.json").write_text('{"nodes":[]}')
    with pytest.raises(CategoryCatalogError, match="CONTENT_DRIFT"):
        CategoryCatalog(tmp_path)
