import importlib.util
import json
from pathlib import Path


def _load_replay_module():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "tools" / "probes" / "l1_selector_replay.py"
    spec = importlib.util.spec_from_file_location("l1_selector_replay", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_l1_selector_replay_default_fixtures_pass(tmp_path):
    module = _load_replay_module()

    result = module.run_replay(output_dir=tmp_path)

    assert result["ok"] is True
    assert result["case_count"] == 3
    assert result["passed_count"] == 3
    assert result["failed_count"] == 0
    assert Path(result["json_path"]).exists()
    assert Path(result["markdown_path"]).exists()
    assert all(len(case["fixture_sha256"]) == 64 for case in result["cases"])
    assert any(
        check["check"] == "eu_outer_package_image_bank" and check["ok"]
        for case in result["cases"]
        for check in case["checks"]
    )


def test_l1_selector_replay_blocks_publish_fixture(tmp_path):
    module = _load_replay_module()
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "bad.html").write_text(
        "<html><body>商品信息 半托管服务 编辑半托管信息 <button>发布</button></body></html>",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "dxm_l1_selector_replay_manifest.v1",
        "cases": [{
            "id": "bad_publish",
            "page_key": "smt_edit",
            "url": "https://www.dianxiaomi.com/web/smt/product/edit?id=1",
            "fixture": "bad.html",
            "checks": ["publish_button_absent"],
        }],
    }), encoding="utf-8")

    result = module.run_replay(manifest_path=manifest, fixture_dir=fixture_dir, output_dir=tmp_path / "out")

    assert result["ok"] is False
    assert result["failed_count"] == 1
    assert "forbidden_button:发布" in result["cases"][0]["failures"]
    assert "publish_button_absent:missing_expected_dom_signal" in result["cases"][0]["failures"]


def test_l1_selector_replay_reports_missing_eu_image_bank(tmp_path):
    module = _load_replay_module()
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "missing.html").write_text(
        "<html><body>商品信息 半托管服务 外包装/标签实拍图-欧盟 <button>保存</button></body></html>",
        encoding="utf-8",
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema": "dxm_l1_selector_replay_manifest.v1",
        "cases": [{
            "id": "missing_bank",
            "page_key": "smt_edit",
            "url": "https://www.dianxiaomi.com/web/smt/product/edit?id=1",
            "fixture": "missing.html",
            "required_texts": ["图片银行（速卖通）"],
            "checks": ["eu_outer_package_image_bank"],
        }],
    }), encoding="utf-8")

    result = module.run_replay(manifest_path=manifest, fixture_dir=fixture_dir, output_dir=tmp_path / "out")

    assert result["ok"] is False
    assert "required_text:图片银行（速卖通）" in result["cases"][0]["failures"]
    assert "eu_outer_package_image_bank:missing_expected_dom_signal" in result["cases"][0]["failures"]


def test_l1_selector_replay_markdown_is_readable(tmp_path):
    module = _load_replay_module()
    result = module.run_replay(output_dir=tmp_path)
    markdown = Path(result["markdown_path"]).read_text(encoding="utf-8")

    assert "L1 Selector Replay 证据" in markdown
    assert "draft_list_product_box_item" in markdown
    assert "manifest_sha256" in markdown
    assert "failures：无" in markdown


def test_l1_selector_replay_has_no_removed_claim_fixture_contract():
    module = _load_replay_module()
    manifest = module.DEFAULT_MANIFEST.read_text(encoding="utf-8")
    source = Path(module.__file__).read_text(encoding="utf-8")
    fixture_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in module.DEFAULT_FIXTURE_DIR.glob("*.html")
    )

    for removed_token in (
        "draft_list_claimed_product",
        "claimed_row_ownership",
        "AI认领",
    ):
        assert removed_token not in manifest
        assert removed_token not in source
        assert removed_token not in fixture_text
