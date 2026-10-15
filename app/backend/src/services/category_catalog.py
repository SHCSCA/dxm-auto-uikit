"""版本化类目仅约束发现和冻结参考，不替代当前页面身份。"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from src.core.config_bus import env_string
from src.services.structured_logging import get_logger, log_exception


logger = get_logger("category_catalog")


class CategoryCatalogError(ValueError):
    reason_code = "CATEGORY_CATALOG_INVALID"


class CategoryCatalog:
    def __init__(self, directory: Path) -> None:
        try:
            manifest = json.loads((directory / "category-catalog.manifest.json").read_text(encoding="utf-8-sig"))
            content = (directory / "category-catalog.v1.json").read_bytes()
            digest = hashlib.sha256(content).hexdigest().upper()
            if digest != manifest["catalog"]["sha256"].upper():
                raise CategoryCatalogError("CATEGORY_CATALOG_CONTENT_DRIFT")
            document = json.loads(content.decode("utf-8-sig"))
            if document.get("schema") != "dxm.category_catalog.v1":
                raise CategoryCatalogError("CATEGORY_CATALOG_SCHEMA_UNSUPPORTED")
            nodes = document["nodes"]
            self._nodes = {node["categoryId"]: node for node in nodes}
            if len(self._nodes) != len(nodes):
                raise CategoryCatalogError("CATEGORY_CATALOG_DUPLICATE_ID")
            self.digest = digest
            self.version = document["schema"]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log_exception(logger, "category_catalog_load_failed", exc)
            if isinstance(exc, CategoryCatalogError):
                raise
            raise CategoryCatalogError("CATEGORY_CATALOG_UNAVAILABLE") from exc

    def get(self, category_id: str) -> dict[str, Any] | None:
        node = self._nodes.get(str(category_id))
        return deepcopy(node) if node is not None else None

    def annotate(self, record: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(record)
        node = self._nodes.get(str(record.get("categoryId")))
        status = "REFERENCE_MATCHED"
        executable = False
        if node is None:
            status = "NODE_NOT_IN_CATALOG"
        else:
            executable = node.get("executableLeaf") is True
            live_leaf = type(record.get("isleaf")) is int and record["isleaf"] == 1 or record.get("isleaf") == "1"
            if bool(node["isLeaf"]) != bool(live_leaf):
                status, executable = "LIVE_LEAF_DRIFT", False
            path = record.get("nodePathId")
            if path and re.findall(r"[1-9][0-9]*", str(path)) != node["nodePathIds"]:
                status, executable = "LIVE_ANCESTOR_DRIFT", False
            parent = record.get("pcid")
            if parent is not None and str(parent or "") != str(node.get("parentCategoryId") or ""):
                status, executable = "LIVE_PARENT_DRIFT", False
            if node.get("executableLeaf") is not True and node.get("isLeaf") is True:
                status = "CATALOG_LEAF_CONFLICT"
            result.update(catalogNodeIdentitySha256=node["nodeIdentitySha256"],
                          catalogNodePathIds=list(node["nodePathIds"]))
        result.update(executableLeaf=executable, catalogSha256=self.digest,
                      catalogVersion=self.version, catalogStatus=status)
        return result


@lru_cache(maxsize=4)
def _load_catalog(directory: str) -> CategoryCatalog:
    return CategoryCatalog(Path(directory))


def runtime_category_catalog() -> CategoryCatalog:
    root = Path(env_string("DXM_RESOURCE_ROOT") or Path(__file__).resolve().parents[4])
    return _load_catalog(str(root / "resources" / "dxm" / "category-catalog"))


def annotate_category_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    catalog = runtime_category_catalog()
    return [catalog.annotate(record) for record in records]
