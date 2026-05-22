import importlib.util
import json
from pathlib import Path

import pytest


def _load_probe_module():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "tools" / "probes" / "l2_readonly_probe.py"
    spec = importlib.util.spec_from_file_location("l2_readonly_probe", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRequest:
    def __init__(self, method: str, url: str, resource_type: str = "xhr"):
        self.method = method
        self.url = url
        self.resource_type = resource_type


class FakeRoute:
    def __init__(self, request: FakeRequest):
        self.request = request
        self.aborted = False
        self.continued = False

    def abort(self):
        self.aborted = True

    def continue_(self):
        self.continued = True


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_readonly_probe_guard_allows_read_methods(method):
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard()
    route = FakeRoute(FakeRequest(method, "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition"))

    guard._route(route)

    assert route.continued is True
    assert route.aborted is False
    summary = guard.summary()
    assert summary["write_request_count"] == 0
    assert summary["non_read_request_count"] == 0
    assert summary["blocked_request_count"] == 0
    assert method in summary["methods_seen"]


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_readonly_probe_guard_blocks_write_methods(method):
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard()
    route = FakeRoute(FakeRequest(method, "https://www.dianxiaomi.com/api/readOnlyProbe"))

    guard._route(route)

    summary = guard.summary()
    assert route.aborted is True
    assert route.continued is False
    assert summary["write_request_count"] == 1
    assert summary["non_read_request_count"] == 1
    assert summary["blocked_request_count"] == 1
    assert f"non_read_method:{method}" in summary["blocked_requests"][0]["reasons"]
    assert f"write_method:{method}" in summary["blocked_requests"][0]["reasons"]
    safety = module.evaluate_safety({
        "final_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        "login_state": {"required": False},
        "network": summary,
    })
    assert safety["ok"] is False


@pytest.mark.parametrize("keyword", ["save", "publish", "submitPublish", "claim", "remark", "note"])
def test_readonly_probe_guard_blocks_forbidden_url_keywords(keyword):
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard()
    route = FakeRoute(FakeRequest("GET", f"https://www.dianxiaomi.com/api/smt/{keyword}?token=secret"))

    guard._route(route)

    summary = guard.summary()
    assert route.aborted is True
    assert route.continued is False
    assert summary["write_request_count"] == 0
    assert summary["blocked_request_count"] == 1
    assert summary["forbidden_keyword_request_count"] == 1
    assert "token=secret" not in summary["blocked_requests"][0]["url"]
    assert any("forbidden_url_keywords" in reason for reason in summary["blocked_requests"][0]["reasons"])


def test_readonly_probe_guard_records_combined_block_reasons_case_insensitive():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard()
    route = FakeRoute(FakeRequest("POST", "https://www.dianxiaomi.com/api/smt/product/submitPublish"))

    guard._route(route)

    summary = guard.summary()
    assert route.aborted is True
    assert route.continued is False
    assert summary["write_request_count"] == 1
    assert summary["blocked_request_count"] == 1
    assert summary["forbidden_keyword_request_count"] == 1
    assert "non_read_method:POST" in summary["blocked_requests"][0]["reasons"]
    assert "write_method:POST" in summary["blocked_requests"][0]["reasons"]
    assert any("submitpublish" in reason for reason in summary["blocked_requests"][0]["reasons"])


def test_readonly_probe_safety_fails_on_final_write_url():
    module = _load_probe_module()
    result = {
        "final_url": "https://www.dianxiaomi.com/web/smt/save",
        "network": {
            "write_request_count": 0,
            "non_read_request_count": 0,
            "blocked_request_count": 0,
            "forbidden_keyword_request_count": 0,
        },
        "login_state": {"required": False},
    }

    safety = module.evaluate_safety(result)

    assert safety["ok"] is False
    assert any("最终 URL" in reason for reason in safety["reasons"])


def test_readonly_probe_safety_fails_when_required_login_cookie_missing():
    module = _load_probe_module()
    result = {
        "final_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        "network": {
            "write_request_count": 0,
            "non_read_request_count": 0,
            "blocked_request_count": 0,
            "forbidden_keyword_request_count": 0,
        },
        "login_state": {
            "required": True,
            "cookies_loaded": False,
            "suspected_login_page": False,
            "signals": [],
        },
    }

    safety = module.evaluate_safety(result)

    assert safety["ok"] is False
    assert any("登录 cookie" in reason for reason in safety["reasons"])


def test_readonly_probe_markdown_contains_core_evidence_fields(tmp_path):
    module = _load_probe_module()
    screenshot = tmp_path / "probe.png"
    screenshot.write_bytes(b"png")
    dom = tmp_path / "probe.html"
    dom.write_text("<html><body>店小秘</body></html>", encoding="utf-8")
    result = {
        "target": "draft_box",
        "target_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        "final_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
        "title": "店小秘",
        "created_at": "2026-05-22T00:00:00+00:00",
        "ok": True,
        "environment": {"os": "Windows", "browser_version": "Chrome", "python": "3.11", "headless": True},
        "screenshot_path": str(screenshot),
        "screenshot_sha256": module.sha256_file(screenshot),
        "dom_path": str(dom),
        "dom_sha256": module.sha256_file(dom),
        "json_path": str(tmp_path / "probe.json"),
        "markdown_path": str(tmp_path / "probe.md"),
        "login_state": {
            "required": False,
            "cookies_loaded": False,
            "suspected_login_page": False,
            "signals": [],
        },
        "network": {
            "write_request_count": 0,
            "non_read_request_count": 0,
            "blocked_request_count": 0,
            "forbidden_keyword_request_count": 0,
            "websocket_count": 0,
            "forbidden_keyword_websocket_count": 0,
        },
        "safety": module.evaluate_safety({
            "final_url": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
            "login_state": {"required": False},
            "network": {
                "write_request_count": 0,
                "non_read_request_count": 0,
                "blocked_request_count": 0,
                "forbidden_keyword_request_count": 0,
            },
        }),
    }

    markdown = module.render_markdown(result)

    assert "L2 只读 Probe 证据" in markdown
    assert "写请求数量：0" in markdown
    assert "screenshot_sha256" in markdown
    assert "dom_sha256" in markdown
    assert "markdown" in markdown
    assert "draft_box" in markdown
    assert "None" not in markdown


def test_sha256_and_url_sanitization_helpers(tmp_path):
    module = _load_probe_module()
    dom = tmp_path / "probe.html"
    dom.write_text("<html></html>", encoding="utf-8")

    assert len(module.sha256_file(dom)) == 64
    assert module.sanitize_url("https://www.dianxiaomi.com/path?token=secret#frag") == (
        "https://www.dianxiaomi.com/path?__redacted__#__redacted__"
    )


def test_load_cookies_normalizes_exported_cookie_shape(tmp_path):
    module = _load_probe_module()
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps([
        {
            "name": "sid",
            "value": "abc",
            "domain": ".dianxiaomi.com",
            "path": "/",
            "sameSite": "lax",
            "expirationDate": 1893456000,
        }
    ]), encoding="utf-8")

    cookies = module.load_cookies(cookie_file)

    assert cookies == [
        {
            "name": "sid",
            "value": "abc",
            "domain": ".dianxiaomi.com",
            "path": "/",
            "httpOnly": False,
            "secure": False,
            "sameSite": "Lax",
            "expires": 1893456000,
        }
    ]
