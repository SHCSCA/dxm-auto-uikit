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


class FakeWebSocket:
    def __init__(self, url: str):
        self.url = url


class FakeFailedRequest:
    method = "GET"
    url = "https://www.dianxiaomi.com/static/app.js?token=secret"

    def __init__(self, failure):
        self.failure = failure


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


def test_readonly_probe_guard_blocks_active_requests_in_strict_mode():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard(strict_active_requests=True)
    route = FakeRoute(FakeRequest("GET", "https://www.dianxiaomi.com/api/read", resource_type="xhr"))

    guard._route(route)

    summary = guard.summary()
    assert route.aborted is True
    assert summary["blocked_request_count"] == 1
    assert summary["strict_active_requests"] is True
    assert "active_or_unknown_resource_type:xhr" in summary["blocked_requests"][0]["reasons"]
    safety = module.evaluate_safety({
        "final_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        "login_state": {"required": False},
        "network": summary,
    })
    assert safety["ok"] is False


def test_readonly_probe_guard_applies_explicit_readonly_allowlist_for_bootstrap_xhr():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard(
        strict_active_requests=True,
        allowlist_entries=[
            {
                "id": "dxm-user-info-readonly",
                "decision": "approve",
                "method": "GET",
                "host": "www.dianxiaomi.com",
                "path": "/api/userInfo.json",
                "resource_type": "xhr",
                "allowed_reasons": ["active_or_unknown_resource_type:xhr"],
                "allow_forbidden_keywords": [],
                "rationale": "DXM SPA bootstrap identity read.",
            }
        ],
    )
    route = FakeRoute(FakeRequest("GET", "https://www.dianxiaomi.com/api/userInfo.json", resource_type="xhr"))

    guard._route(route)

    summary = guard.summary()
    assert route.continued is True
    assert route.aborted is False
    assert summary["blocked_request_count"] == 0
    assert summary["forbidden_keyword_request_count"] == 0
    assert summary["allowlist_applied"] is True
    assert summary["allowlisted_request_count"] == 1
    assert summary["allowlisted_requests"][0]["allowlist_id"] == "dxm-user-info-readonly"
    safety = module.evaluate_safety({
        "final_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        "login_state": {"required": False},
        "network": summary,
    })
    assert safety["ok"] is True


def test_readonly_probe_guard_applies_explicit_allowlist_for_reviewed_static_publish_chunk():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard(
        strict_active_requests=True,
        allowlist_entries=[
            {
                "id": "dxm-static-publish-detection-script",
                "decision": "approve",
                "method": "GET",
                "host": "s1.dianxiaomi.com",
                "path_regex": r"/dxm-web/2026-05/assets/publishDetection-[A-Za-z0-9_-]+\.js",
                "resource_type": "script",
                "allowed_reasons": ["forbidden_url_keywords:publish"],
                "allow_forbidden_keywords": ["publish"],
                "rationale": "Reviewed passive DXM static asset required by SPA bootstrap.",
            }
        ],
    )
    route = FakeRoute(FakeRequest(
        "GET",
        "https://s1.dianxiaomi.com/dxm-web/2026-05/assets/publishDetection-COrhuT0d.js",
        resource_type="script",
    ))

    guard._route(route)

    summary = guard.summary()
    assert route.continued is True
    assert summary["blocked_request_count"] == 0
    assert summary["forbidden_keyword_request_count"] == 0
    assert summary["observed_forbidden_keyword_request_count"] == 1
    assert summary["allowlisted_forbidden_keyword_request_count"] == 1


def test_readonly_probe_allowlist_never_allows_write_methods():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard(
        strict_active_requests=True,
        allowlist_entries=[
            {
                "id": "invalid-write-attempt",
                "decision": "approve",
                "method": "GET",
                "host": "www.dianxiaomi.com",
                "path": "/api/save.json",
                "resource_type": "xhr",
                "allowed_reasons": ["write_method:POST", "non_read_method:POST"],
                "allow_forbidden_keywords": ["save"],
            }
        ],
    )
    route = FakeRoute(FakeRequest("POST", "https://www.dianxiaomi.com/api/save.json", resource_type="xhr"))

    guard._route(route)

    summary = guard.summary()
    assert route.aborted is True
    assert summary["write_request_count"] == 1
    assert summary["blocked_request_count"] == 1
    assert summary["allowlisted_request_count"] == 0


def test_readonly_probe_guard_applies_explicit_readonly_post_allowlist():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard(
        strict_active_requests=True,
        allowlist_entries=[
            {
                "id": "dxm-draft-count-readonly-post",
                "decision": "approve",
                "method": "POST",
                "readonly_post": True,
                "host": "www.dianxiaomi.com",
                "path": "/api/smtProduct/getOfflineCounts.json",
                "resource_type": "xhr",
                "allowed_reasons": [
                    "non_read_method:POST",
                    "write_method:POST",
                    "active_or_unknown_resource_type:xhr",
                ],
                "allow_forbidden_keywords": [],
                "rationale": "DXM uses POST for a count query.",
            }
        ],
    )
    route = FakeRoute(FakeRequest("POST", "https://www.dianxiaomi.com/api/smtProduct/getOfflineCounts.json", resource_type="xhr"))

    guard._route(route)

    summary = guard.summary()
    assert route.continued is True
    assert summary["observed_write_method_request_count"] == 1
    assert summary["allowlisted_non_read_request_count"] == 1
    assert summary["write_request_count"] == 0
    assert summary["non_read_request_count"] == 0
    assert summary["blocked_request_count"] == 0


def test_readonly_probe_suppresses_exact_third_party_telemetry_without_counting_as_dxm_write():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard(strict_active_requests=True)
    route = FakeRoute(FakeRequest("POST", "https://events.sellfox.com/events", resource_type="fetch"))

    guard._route(route)

    summary = guard.summary()
    assert route.aborted is True
    assert route.continued is False
    assert summary["request_count"] == 0
    assert summary["write_request_count"] == 0
    assert summary["non_read_request_count"] == 0
    assert summary["blocked_request_count"] == 0
    assert summary["suppressed_request_count"] == 1
    assert summary["suppressed_requests"][0]["policy_id"] == "sellfox-events"


def test_readonly_probe_never_suppresses_first_party_posts():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard(strict_active_requests=True)
    route = FakeRoute(FakeRequest("POST", "https://www.dianxiaomi.com/events", resource_type="fetch"))

    guard._route(route)

    summary = guard.summary()
    assert route.aborted is True
    assert summary["write_request_count"] == 1
    assert summary["blocked_request_count"] == 1
    assert summary["suppressed_request_count"] == 0


def test_readonly_probe_guard_records_string_request_failure():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard()

    guard._on_request_failed(FakeFailedRequest("net::ERR_FAILED"))

    assert guard.summary()["failed_requests"] == [{
        "method": "GET",
        "url": "https://www.dianxiaomi.com/static/app.js?__redacted__",
        "error_text": "net::ERR_FAILED",
    }]


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


def test_readonly_probe_safety_fails_on_websocket_or_login_page():
    module = _load_probe_module()
    guard = module.ReadOnlyProbeGuard()
    guard._on_websocket(FakeWebSocket("wss://www.dianxiaomi.com/ws/read"))

    safety = module.evaluate_safety({
        "final_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        "network": guard.summary(),
        "login_state": {
            "required": True,
            "cookies_loaded": True,
            "suspected_login_page": True,
            "signals": ["login_text"],
        },
    })

    assert safety["ok"] is False
    assert any("WebSocket" in reason for reason in safety["reasons"])
    assert any("登录页" in reason for reason in safety["reasons"])


def test_detect_login_state_records_url_and_text_signals():
    module = _load_probe_module()

    state = module.detect_login_state(
        required=True,
        cookies_loaded=True,
        final_url="https://www.dianxiaomi.com/passport/login",
        title="店小秘",
        body_text="请登录后继续",
    )

    assert state["suspected_login_page"] is True
    assert state["signals"] == ["login_url", "login_text"]


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


def test_readonly_probe_diagnostics_group_failed_real_navigation_and_requests():
    module = _load_probe_module()
    result = {
        "target": "data_acquisition",
        "target_url": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
        "final_url": "https://www.dianxiaomi.com/web/home?__redacted__",
        "ok": False,
        "body_preview": "店小秘",
        "visible_matches": [],
        "login_state": {
            "required": True,
            "cookies_loaded": True,
            "suspected_login_page": False,
            "signals": [],
        },
        "network": {
            "write_request_count": 1,
            "non_read_request_count": 1,
            "blocked_request_count": 3,
            "forbidden_keyword_request_count": 1,
            "websocket_count": 0,
            "blocked_requests": [
                {
                    "method": "GET",
                    "url": "https://www.dianxiaomi.com/api/userInfo.json",
                    "resource_type": "xhr",
                    "reasons": ["active_or_unknown_resource_type:xhr"],
                    "forbidden_keyword_hits": [],
                },
                {
                    "method": "GET",
                    "url": "https://www.dianxiaomi.com/api/userInfo.json",
                    "resource_type": "xhr",
                    "reasons": ["active_or_unknown_resource_type:xhr"],
                    "forbidden_keyword_hits": [],
                },
                {
                    "method": "POST",
                    "url": "https://events.sellfox.com/events",
                    "resource_type": "fetch",
                    "reasons": ["non_read_method:POST", "write_method:POST"],
                    "forbidden_keyword_hits": [],
                },
                {
                    "method": "GET",
                    "url": "https://s1.dianxiaomi.com/assets/publishDetection.js",
                    "resource_type": "script",
                    "reasons": ["forbidden_url_keywords:publish"],
                    "forbidden_keyword_hits": ["publish"],
                },
            ],
        },
        "safety": {"ok": False, "reasons": ["blocked"]},
    }

    diagnostics = module.build_probe_diagnostics(result)

    assert diagnostics["navigation"]["left_target_path"] is True
    assert diagnostics["navigation"]["final_path_class"] == "home"
    assert diagnostics["strict_pass_checks"]["zero_blocked"] is False
    assert diagnostics["strict_pass_checks"]["final_url_matches"] is False
    assert diagnostics["render_state"]["app_shell_only"] is True
    assert diagnostics["blocked_request_groups"][0]["count"] == 2
    assert diagnostics["blocked_request_groups"][0]["path"] == "/api/userInfo.json"
    assert diagnostics["allowlist_review_candidates"][0]["review_only"] is True


def test_sha256_and_url_sanitization_helpers(tmp_path):
    module = _load_probe_module()
    dom = tmp_path / "probe.html"
    dom.write_text("<html></html>", encoding="utf-8")

    assert len(module.sha256_file(dom)) == 64
    assert module.sanitize_url("https://www.dianxiaomi.com/path?token=secret#frag") == (
        "https://www.dianxiaomi.com/path?__redacted__#__redacted__"
    )


def test_visible_match_and_stdout_summary_are_sanitized():
    module = _load_probe_module()
    matches = module.sanitize_visible_matches([
        {
            "text": "联系 13812345678",
            "href": "https://www.dianxiaomi.com/path?token=secret",
            "cls": "session=abcdefg",
            "id": "user@example.com",
            "tag": "A",
            "rect": {"x": 0, "y": 0, "w": 10, "h": 10},
        }
    ])
    result = {
        "schema": "dxm_l2_readonly_probe.v1",
        "ok": True,
        "target": "draft_box",
        "final_url": "https://www.dianxiaomi.com/path?__redacted__",
        "body_preview": "secret body",
        "visible_matches": matches,
        "safety": {"ok": True, "reasons": []},
        "network": {"request_count": 1, "methods_seen": ["GET"]},
        "screenshot_path": "probe.png",
        "screenshot_sha256": "a" * 64,
        "dom_path": "probe.html",
        "dom_sha256": "b" * 64,
        "json_path": "probe.json",
        "markdown_path": "probe.md",
    }

    summary = module.summarize_for_stdout(result)

    assert matches[0]["text"] == "联系 [redacted-phone]"
    assert matches[0]["href"] == "https://www.dianxiaomi.com/path?__redacted__"
    assert matches[0]["id"] == "[redacted-email]"
    assert "body_preview" not in summary
    assert "visible_matches" not in summary


def test_probe_run_metadata_includes_run_and_code_identity(tmp_path):
    module = _load_probe_module()
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text('[{"name":"sid","value":"abc"}]', encoding="utf-8")

    metadata = module.build_probe_run_metadata(run_id="l2-real-20260526T000000Z", cookie_file=cookie_file)

    assert metadata["run_id"] == "l2-real-20260526T000000Z"
    assert len(metadata["script_sha256"]) == 64
    assert metadata["git_head"] == "unknown" or len(metadata["git_head"]) == 40
    assert metadata["cookie_file_sha256"] == module.sha256_file(cookie_file)


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


def test_load_allowlist_requires_reviewed_readonly_shape(tmp_path):
    module = _load_probe_module()
    allowlist_file = tmp_path / "l2_allowlist.json"
    allowlist_file.write_text(json.dumps({
        "schema": "dxm_l2_readonly_allowlist.v1",
        "entries": [
            {
                "id": "approved",
                "decision": "approve",
                "method": "GET",
                "host": "www.dianxiaomi.com",
                "path": "/api/userInfo.json",
                "resource_type": "xhr",
                "allowed_reasons": ["active_or_unknown_resource_type:xhr"],
                "allow_forbidden_keywords": [],
            },
            {
                "id": "rejected",
                "decision": "reject",
                "method": "GET",
                "host": "www.dianxiaomi.com",
                "path": "/api/unsafe.json",
                "resource_type": "xhr",
                "allowed_reasons": ["active_or_unknown_resource_type:xhr"],
            },
            {
                "id": "bad-write",
                "decision": "approve",
                "method": "POST",
                "host": "www.dianxiaomi.com",
                "path": "/api/save.json",
                "resource_type": "xhr",
                "allowed_reasons": ["write_method:POST"],
            },
        ],
    }), encoding="utf-8")

    entries, errors, resolved = module.load_allowlist(allowlist_file)

    assert resolved == allowlist_file
    assert [entry["id"] for entry in entries] == ["approved"]
    assert len(errors) == 1
    assert "requires readonly_post=true" in errors[0]
