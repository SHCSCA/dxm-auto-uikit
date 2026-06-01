from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "app" / "backend"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from src.execution.browser_runtime import chrome_launch_options  # noqa: E402


TARGETS = {
    "data_acquisition": "https://www.dianxiaomi.com/web/productCrawl/dataAcquisition",
    "draft_box": "https://www.dianxiaomi.com/web/smt/smtProductList/draft",
}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PASSIVE_RESOURCE_TYPES = {"document", "stylesheet", "script", "image", "font", "media"}
ACTIVE_RESOURCE_TYPES = {"xhr", "fetch", "eventsource", "websocket"}
SUPPRESSED_THIRD_PARTY_TELEMETRY = (
    {
        "id": "sellfox-events",
        "host": "events.sellfox.com",
        "path": "/events",
        "methods": {"POST"},
        "resource_types": {"fetch"},
    },
    {
        "id": "qiyukf-remote-storage",
        "host": "qiyukf.com",
        "path": "/webapi/user/remoteStorage.action",
        "methods": {"POST"},
        "resource_types": {"xhr"},
    },
    {
        "id": "qiyukf-unread",
        "host": "qiyukf.com",
        "path": "/webapi/user/getUnread.action",
        "methods": {"GET"},
        "resource_types": {"xhr"},
    },
    {
        "id": "qiyukf-sdk-setting",
        "host": "qiyukf.com",
        "path": "/webapi/sdk/setting/data",
        "methods": {"GET"},
        "resource_types": {"xhr"},
    },
)
FORBIDDEN_URL_KEYWORDS = (
    "save",
    "publish",
    "submitPublish",
    "claim",
    "remark",
    "note",
)
DEFAULT_COOKIE_FILE = ROOT / "data" / "sessions" / "dianxiaomi_cookies.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "l2_readonly_probe"
DEFAULT_ALLOWLIST_FILE = ROOT / "config" / "l2_readonly_allowlist.json"
LOGIN_URL_KEYWORDS = ("login", "passport")
LOGIN_TEXT_KEYWORDS = ("请登录", "登录店小秘", "账户登录", "账号登录", "密码登录")


class ReadOnlyProbeGuard:
    def __init__(
        self,
        forbidden_keywords: tuple[str, ...] = FORBIDDEN_URL_KEYWORDS,
        *,
        strict_active_requests: bool = False,
        allowlist_entries: list[dict[str, Any]] | None = None,
        allowlist_file: Path | None = None,
        allowlist_errors: list[str] | None = None,
    ) -> None:
        self.forbidden_keywords = tuple(keyword.lower() for keyword in forbidden_keywords)
        self.strict_active_requests = strict_active_requests
        self.allowlist_entries = allowlist_entries or []
        self.allowlist_file = allowlist_file
        self.allowlist_errors = allowlist_errors or []
        self.requests: list[dict[str, Any]] = []
        self.blocked_requests: list[dict[str, Any]] = []
        self.allowlisted_requests: list[dict[str, Any]] = []
        self.suppressed_requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []
        self.websockets: list[dict[str, Any]] = []

    def install(self, context) -> None:
        context.route("**/*", self._route)

    def bind_page(self, page) -> None:
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)
        page.on("websocket", self._on_websocket)

    def _route(self, route) -> None:
        request = route.request
        method = request.method.upper()
        url = request.url
        record = {
            "method": method,
            "url": sanitize_url(url),
            "resource_type": request.resource_type,
        }
        telemetry_policy = _matching_suppressed_telemetry(method, url, request.resource_type)
        if telemetry_policy is not None:
            self.suppressed_requests.append({
                **record,
                "reasons": ["third_party_telemetry_suppressed"],
                "policy_id": telemetry_policy["id"],
            })
            route.abort()
            return
        blocked_reasons = []
        if method not in READ_METHODS:
            blocked_reasons.append(f"non_read_method:{method}")
        if method in WRITE_METHODS:
            blocked_reasons.append(f"write_method:{method}")
        if self.strict_active_requests and request.resource_type not in PASSIVE_RESOURCE_TYPES:
            blocked_reasons.append(f"active_or_unknown_resource_type:{request.resource_type}")
        keyword_hits = self._keyword_hits(url)
        record["forbidden_keyword_hits"] = keyword_hits
        self.requests.append(record)
        if keyword_hits:
            blocked_reasons.append("forbidden_url_keywords:" + ",".join(keyword_hits))
        if blocked_reasons:
            allowlist_match = self._matching_allowlist_entry(record, blocked_reasons, keyword_hits)
            if allowlist_match is not None:
                record["allowlisted"] = True
                record["allowlist_id"] = allowlist_match.get("id")
                record["allowlist_rationale"] = allowlist_match.get("rationale")
                allowed = {
                    **record,
                    "reasons": blocked_reasons,
                }
                self.allowlisted_requests.append(allowed)
                route.continue_()
                return
            blocked = {**record, "reasons": blocked_reasons}
            self.blocked_requests.append(blocked)
            route.abort()
            return
        route.continue_()

    def _on_response(self, response) -> None:
        self.responses.append({
            "status": response.status,
            "url": sanitize_url(response.url),
            "method": response.request.method,
        })

    def _on_request_failed(self, request) -> None:
        failure = request.failure or {}
        error_text = failure.get("errorText") if isinstance(failure, dict) else str(failure)
        self.failures.append({
            "method": request.method,
            "url": sanitize_url(request.url),
            "error_text": error_text,
        })

    def _on_websocket(self, websocket) -> None:
        url = websocket.url
        self.websockets.append({
            "url": sanitize_url(url),
            "forbidden_keyword_hits": self._keyword_hits(url),
        })

    def _keyword_hits(self, url: str) -> list[str]:
        lowered = url.lower()
        return [keyword for keyword in self.forbidden_keywords if keyword.lower() in lowered]

    def _matching_allowlist_entry(
        self,
        record: dict[str, Any],
        blocked_reasons: list[str],
        keyword_hits: list[str],
    ) -> dict[str, Any] | None:
        if not self.allowlist_entries:
            return None
        method = str(record.get("method") or "").upper()
        if method not in READ_METHODS and method not in WRITE_METHODS:
            return None
        parts = _split_url(str(record.get("url") or ""))
        for entry in self.allowlist_entries:
            if not _allowlist_entry_matches(
                entry=entry,
                method=method,
                host=parts["host"],
                path=parts["path"],
                resource_type=str(record.get("resource_type") or ""),
                blocked_reasons=blocked_reasons,
                keyword_hits=keyword_hits,
            ):
                continue
            return entry
        return None

    def summary(self) -> dict[str, Any]:
        methods = sorted({item["method"] for item in self.requests})
        unapproved_requests = [item for item in self.requests if not item.get("allowlisted")]
        observed_write_requests = [item for item in self.requests if item["method"] in WRITE_METHODS]
        write_requests = [item for item in unapproved_requests if item["method"] in WRITE_METHODS]
        non_read_requests = [item for item in unapproved_requests if item["method"] not in READ_METHODS]
        allowlisted_non_read_requests = [
            item for item in self.allowlisted_requests
            if item.get("method") not in READ_METHODS
        ]
        forbidden_keyword_requests = [
            item for item in self.blocked_requests
            if item.get("forbidden_keyword_hits")
        ]
        observed_forbidden_keyword_requests = [item for item in self.requests if item.get("forbidden_keyword_hits")]
        allowlisted_forbidden_keyword_requests = [
            item for item in self.allowlisted_requests
            if item.get("forbidden_keyword_hits")
        ]
        forbidden_keyword_websockets = [
            item for item in self.websockets
            if item.get("forbidden_keyword_hits")
        ]
        return {
            "request_count": len(self.requests),
            "methods_seen": methods,
            "read_methods_allowed": sorted(READ_METHODS),
            "passive_resource_types_allowed": sorted(PASSIVE_RESOURCE_TYPES),
            "active_resource_types_blocked": sorted(ACTIVE_RESOURCE_TYPES),
            "strict_active_requests": self.strict_active_requests,
            "write_request_count": len(write_requests),
            "non_read_request_count": len(non_read_requests),
            "observed_write_method_request_count": len(observed_write_requests),
            "allowlisted_non_read_request_count": len(allowlisted_non_read_requests),
            "blocked_request_count": len(self.blocked_requests),
            "forbidden_keyword_request_count": len(forbidden_keyword_requests),
            "observed_forbidden_keyword_request_count": len(observed_forbidden_keyword_requests),
            "allowlisted_forbidden_keyword_request_count": len(allowlisted_forbidden_keyword_requests),
            "allowlist_applied": bool(self.allowlisted_requests),
            "allowlist_file": str(self.allowlist_file) if self.allowlist_file else None,
            "allowlist_entries_loaded": len(self.allowlist_entries),
            "allowlist_error_count": len(self.allowlist_errors),
            "allowlist_errors": self.allowlist_errors,
            "allowlisted_request_count": len(self.allowlisted_requests),
            "allowlisted_requests": self.allowlisted_requests[:50],
            "suppressed_request_count": len(self.suppressed_requests),
            "suppressed_requests": self.suppressed_requests[:50],
            "websocket_count": len(self.websockets),
            "forbidden_keyword_websocket_count": len(forbidden_keyword_websockets),
            "blocked_requests": self.blocked_requests[:50],
            "failed_requests": self.failures[:50],
            "websockets": self.websockets[:50],
            "http_error_responses": [item for item in self.responses if item["status"] >= 400][:50],
        }


def run_probe(
    *,
    target: str,
    url: str,
    cookie_file: Path = DEFAULT_COOKIE_FILE,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    headless: bool = True,
    wait_ms: int = 3500,
    body_limit: int = 6000,
    run_id: str | None = None,
    allowlist_file: Path | None = None,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_metadata = build_probe_run_metadata(run_id=run_id or f"l2-{timestamp}-{uuid4().hex[:8]}", cookie_file=cookie_file)
    screenshot_path = output_dir / f"{target}_{timestamp}.png"
    dom_path = output_dir / f"{target}_{timestamp}.html"
    json_path = output_dir / f"{target}_{timestamp}.json"
    markdown_path = output_dir / f"{target}_{timestamp}.md"

    target_is_dxm = is_dianxiaomi_url(url)
    allowlist_entries, allowlist_errors, resolved_allowlist_file = load_allowlist(allowlist_file)
    guard = ReadOnlyProbeGuard(
        strict_active_requests=target_is_dxm,
        allowlist_entries=allowlist_entries if target_is_dxm else [],
        allowlist_file=resolved_allowlist_file if target_is_dxm else None,
        allowlist_errors=allowlist_errors if target_is_dxm else [],
    )
    with sync_playwright() as playwright:
        options = chrome_launch_options(headless=headless)
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            ignore_https_errors=not target_is_dxm,
            service_workers="block",
            viewport={"width": 1440, "height": 1200},
        )
        cookies_loaded = False
        if target_is_dxm and cookie_file.exists():
            cookies = load_cookies(cookie_file)
            if cookies:
                context.add_cookies(cookies)
                cookies_loaded = True
        guard.install(context)
        page = context.new_page()
        guard.bind_page(page)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(wait_ms)
        body = page.locator("body").inner_text(timeout=10000)
        matches = collect_visible_matches(page)
        dom_path.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(screenshot_path), full_page=True)
        title = page.title()
        current_url = page.url
        browser_version = browser.version
        browser.close()

    result = {
        "schema": "dxm_l2_readonly_probe.v1",
        **run_metadata,
        "ok": True,
        "target": target,
        "target_url": sanitize_url(url),
        "final_url": sanitize_url(current_url),
        "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "browser_version": browser_version,
            "headless": headless,
        },
        "cookies_loaded": cookies_loaded,
        "login_state": detect_login_state(
            required=target_is_dxm,
            cookies_loaded=cookies_loaded,
            final_url=current_url,
            title=title,
            body_text=body,
        ),
        "screenshot_path": str(screenshot_path),
        "screenshot_sha256": sha256_file(screenshot_path),
        "dom_path": str(dom_path),
        "dom_sha256": sha256_file(dom_path),
        "body_preview": redact_sensitive_text(body[:body_limit]),
        "visible_matches": sanitize_visible_matches(matches),
        "network": guard.summary(),
        "allowlist": {
            "file": str(resolved_allowlist_file) if resolved_allowlist_file and target_is_dxm else None,
            "file_sha256": sha256_file(resolved_allowlist_file) if resolved_allowlist_file and target_is_dxm and resolved_allowlist_file.exists() else None,
            "entries_loaded": len(allowlist_entries) if target_is_dxm else 0,
            "errors": allowlist_errors if target_is_dxm else [],
            "applied": bool(guard.allowlisted_requests) if target_is_dxm else False,
        },
        "safety": {},
    }
    result["safety"] = evaluate_safety(result)
    result["ok"] = bool(result["safety"]["ok"])
    result["diagnostics"] = build_probe_diagnostics(result)
    result["json_path"] = str(json_path)
    result["markdown_path"] = str(markdown_path)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    return result


def evaluate_safety(result: dict[str, Any]) -> dict[str, Any]:
    reasons = []
    network = result.get("network") or {}
    if network.get("write_request_count"):
        reasons.append(f"写请求数量非零：{network['write_request_count']}")
    if network.get("non_read_request_count"):
        reasons.append(f"非只读请求数量非零：{network['non_read_request_count']}")
    if network.get("blocked_request_count"):
        reasons.append(f"被拦截请求数量非零：{network['blocked_request_count']}")
    if network.get("forbidden_keyword_request_count"):
        reasons.append(f"网络 URL 命中禁用关键词：{network['forbidden_keyword_request_count']}")
    if network.get("allowlist_error_count"):
        reasons.append(f"allowlist 配置错误：{network['allowlist_error_count']}")
    if network.get("websocket_count"):
        reasons.append(f"检测到 WebSocket 连接：{network['websocket_count']}")
    if network.get("forbidden_keyword_websocket_count"):
        reasons.append(f"WebSocket URL 命中禁用关键词：{network['forbidden_keyword_websocket_count']}")
    final_hits = [
        keyword for keyword in FORBIDDEN_URL_KEYWORDS
        if keyword.lower() in str(result.get("final_url") or "").lower()
    ]
    if final_hits:
        reasons.append("最终 URL 命中禁用关键词：" + ",".join(final_hits))
    login_state = result.get("login_state") or {}
    if login_state.get("required") and not login_state.get("cookies_loaded"):
        reasons.append("真实店小秘目标未加载登录 cookie")
    if login_state.get("required") and login_state.get("suspected_login_page"):
        reasons.append("疑似停留在登录页：" + ",".join(login_state.get("signals") or []))
    return {
        "ok": not reasons,
        "mode": "L2_READ_ONLY",
        "read_methods_allowed": sorted(READ_METHODS),
        "write_methods_forbidden": sorted(WRITE_METHODS),
        "forbidden_url_keywords": list(FORBIDDEN_URL_KEYWORDS),
        "reasons": reasons,
    }


def build_probe_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "strict_pass_checks": _strict_pass_checks(result),
        "navigation": _navigation_diagnostics(result),
        "render_state": _render_state_diagnostics(result),
        "blocked_request_groups": _group_blocked_requests(result),
        "allowlisted_request_groups": _group_allowlisted_requests(result),
        "suppressed_request_groups": _group_suppressed_requests(result),
        "allowlist_review_candidates": _allowlist_review_candidates(result),
    }


def _strict_pass_checks(result: dict[str, Any]) -> dict[str, bool]:
    network = result.get("network") or {}
    login_state = result.get("login_state") or {}
    safety = result.get("safety") or {}
    return {
        "ok": result.get("ok") is True,
        "safety_ok": safety.get("ok") is True,
        "target_url_matches": _target_url_matches(result.get("target"), result.get("target_url")),
        "final_url_matches": _target_url_matches(result.get("target"), result.get("final_url")),
        "cookies_loaded": login_state.get("cookies_loaded") is True,
        "not_login_page": login_state.get("suspected_login_page") is False,
        "zero_write": int(network.get("write_request_count") or 0) == 0,
        "zero_non_read": int(network.get("non_read_request_count") or 0) == 0,
        "zero_blocked": int(network.get("blocked_request_count") or 0) == 0,
        "zero_forbidden": int(network.get("forbidden_keyword_request_count") or 0) == 0,
        "zero_websocket": int(network.get("websocket_count") or 0) == 0,
    }


def _navigation_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    target = str(result.get("target") or "")
    target_path = _url_path(result.get("target_url"))
    final_path = _url_path(result.get("final_url"))
    final_matches = _target_url_matches(target, result.get("final_url"))
    return {
        "requested_target_path": target_path,
        "final_path": final_path,
        "left_target_path": bool(is_dianxiaomi_url(str(result.get("target_url") or "")) and not final_matches),
        "final_path_class": _classify_final_path(target, result.get("final_url")),
    }


def _render_state_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    body = str(result.get("body_preview") or "")
    visible_matches = result.get("visible_matches") or []
    target_markers = _target_markers(str(result.get("target") or ""))
    target_markers_found = sorted({
        marker
        for marker in target_markers
        if marker and (marker in body or any(marker in str(match.get("text") or "") for match in visible_matches))
    })
    loading_screen_detected = any(marker in body for marker in ("加载", "loading", "Loading"))
    app_shell_only = not target_markers_found and (len(body.strip()) < 200 or loading_screen_detected)
    return {
        "body_text_length": len(body),
        "visible_match_count": len(visible_matches),
        "loading_screen_detected": loading_screen_detected,
        "target_markers_found": target_markers_found,
        "app_shell_only": app_shell_only,
    }


def _group_blocked_requests(result: dict[str, Any]) -> list[dict[str, Any]]:
    return _group_network_requests((result.get("network") or {}).get("blocked_requests") or [])


def _group_allowlisted_requests(result: dict[str, Any]) -> list[dict[str, Any]]:
    groups = _group_network_requests((result.get("network") or {}).get("allowlisted_requests") or [])
    for group in groups:
        group["allowlist_applied"] = True
    return groups


def _group_suppressed_requests(result: dict[str, Any]) -> list[dict[str, Any]]:
    groups = _group_network_requests((result.get("network") or {}).get("suppressed_requests") or [])
    for group in groups:
        group["suppressed"] = True
    return groups


def _group_network_requests(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in items:
        parts = _split_url(str(item.get("url") or ""))
        reasons = tuple(item.get("reasons") or [])
        keyword_hits = tuple(item.get("forbidden_keyword_hits") or [])
        key = (
            item.get("method"),
            parts["host"],
            parts["path"],
            item.get("resource_type"),
            reasons,
            keyword_hits,
        )
        current = grouped.setdefault(key, {
            "count": 0,
            "method": item.get("method"),
            "host": parts["host"],
            "path": parts["path"],
            "resource_type": item.get("resource_type"),
            "reasons": list(reasons),
            "keyword_hits": list(keyword_hits),
            "sample_url": item.get("url"),
        })
        if item.get("allowlist_id"):
            current["allowlist_id"] = item.get("allowlist_id")
            current["allowlist_rationale"] = item.get("allowlist_rationale")
        current["count"] += 1
    return sorted(grouped.values(), key=lambda group: (-int(group["count"]), str(group["host"]), str(group["path"])))[:25]


def _allowlist_review_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for group in _group_blocked_requests(result):
        reasons = group.get("reasons") or []
        if (
            group.get("method") in READ_METHODS
            and group.get("resource_type") in ACTIVE_RESOURCE_TYPES
            and not group.get("keyword_hits")
            and all(str(reason).startswith("active_or_unknown_resource_type:") for reason in reasons)
        ):
            candidates.append({
                **group,
                "review_only": True,
                "allowlist_applied": False,
            })
    return candidates[:20]


def _target_url_matches(target: Any, url: Any) -> bool:
    target_key = str(target or "")
    expected = TARGETS.get(target_key)
    if not expected or not is_dianxiaomi_url(str(url or "")):
        return False
    return _url_path(url).lower().startswith(_url_path(expected).lower())


def _classify_final_path(target: str, url: Any) -> str:
    path = _url_path(url).lower()
    if not path:
        return "unknown"
    if not is_dianxiaomi_url(str(url or "")):
        return "mock_or_external"
    if any(keyword in str(url).lower() for keyword in LOGIN_URL_KEYWORDS):
        return "login"
    if path.startswith("/web/home"):
        return "home"
    if _target_url_matches(target, url):
        return "target"
    return "other"


def _target_markers(target: str) -> tuple[str, ...]:
    if target == "data_acquisition":
        return ("采集箱", "数据采集", "采集")
    if target == "draft_box":
        return ("草稿箱", "草稿", "产品列表")
    return ()


def _url_path(url: Any) -> str:
    try:
        return urlsplit(str(url or "")).path
    except ValueError:
        return ""


def _split_url(url: str) -> dict[str, str]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return {"host": "", "path": ""}
    return {"host": parts.netloc, "path": parts.path}


def load_allowlist(allowlist_file: Path | None) -> tuple[list[dict[str, Any]], list[str], Path | None]:
    if allowlist_file is None:
        return [], [], None
    resolved = allowlist_file if allowlist_file.is_absolute() else ROOT / allowlist_file
    if not resolved.exists():
        return [], [f"allowlist file not found: {resolved}"], resolved
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [], [f"allowlist JSON parse error: {exc}"], resolved
    if not isinstance(payload, dict):
        return [], ["allowlist root must be an object"], resolved
    if payload.get("schema") != "dxm_l2_readonly_allowlist.v1":
        return [], ["allowlist schema must be dxm_l2_readonly_allowlist.v1"], resolved
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return [], ["allowlist entries must be an array"], resolved
    approved_entries = []
    errors = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entry {index} must be an object")
            continue
        error = _validate_allowlist_entry(entry, index)
        if error:
            errors.append(error)
            continue
        if entry.get("decision") == "approve":
            approved_entries.append(entry)
    return approved_entries, errors, resolved


def _validate_allowlist_entry(entry: dict[str, Any], index: int) -> str | None:
    prefix = f"entry {index}"
    method = str(entry.get("method") or "").upper()
    if method not in READ_METHODS and method not in WRITE_METHODS:
        return f"{prefix} method must be one of {sorted(READ_METHODS | WRITE_METHODS)}"
    if method in WRITE_METHODS and entry.get("readonly_post") is not True:
        return f"{prefix} write-like method {method} requires readonly_post=true"
    if method in WRITE_METHODS and str(entry.get("host") or "").lower() != "www.dianxiaomi.com":
        return f"{prefix} readonly_post is limited to first-party DXM APIs"
    resource_type = str(entry.get("resource_type") or "")
    if resource_type == "websocket":
        return f"{prefix} cannot allow websocket"
    if not resource_type:
        return f"{prefix} resource_type is required"
    if not str(entry.get("host") or "").strip():
        return f"{prefix} host is required"
    has_path = bool(str(entry.get("path") or "").strip())
    has_path_regex = bool(str(entry.get("path_regex") or "").strip())
    if has_path == has_path_regex:
        return f"{prefix} must define exactly one of path or path_regex"
    allowed_reasons = entry.get("allowed_reasons")
    if not isinstance(allowed_reasons, list) or not allowed_reasons:
        return f"{prefix} allowed_reasons must be a non-empty array"
    if method in READ_METHODS and any(str(reason).startswith(("non_read_method:", "write_method:")) for reason in allowed_reasons):
        return f"{prefix} cannot allow non-read/write block reasons"
    if has_path_regex:
        try:
            re.compile(str(entry.get("path_regex")))
        except re.error as exc:
            return f"{prefix} path_regex is invalid: {exc}"
    return None


def _allowlist_entry_matches(
    *,
    entry: dict[str, Any],
    method: str,
    host: str,
    path: str,
    resource_type: str,
    blocked_reasons: list[str],
    keyword_hits: list[str],
) -> bool:
    if entry.get("decision") != "approve":
        return False
    if str(entry.get("method") or "").upper() != method:
        return False
    if method in WRITE_METHODS and entry.get("readonly_post") is not True:
        return False
    if str(entry.get("host") or "").lower() != host.lower():
        return False
    if str(entry.get("resource_type") or "") != resource_type:
        return False
    entry_path = str(entry.get("path") or "")
    if entry_path and entry_path != path:
        return False
    entry_path_regex = str(entry.get("path_regex") or "")
    if entry_path_regex and not re.fullmatch(entry_path_regex, path):
        return False
    allowed_keywords = {str(keyword).lower() for keyword in entry.get("allow_forbidden_keywords") or []}
    if any(keyword.lower() not in allowed_keywords for keyword in keyword_hits):
        return False
    allowed_reasons = {str(reason) for reason in entry.get("allowed_reasons") or []}
    return all(reason in allowed_reasons for reason in blocked_reasons)


def _matching_suppressed_telemetry(method: str, url: str, resource_type: str) -> dict[str, Any] | None:
    parts = _split_url(sanitize_url(url))
    host = parts["host"].lower()
    path = parts["path"]
    if is_dianxiaomi_url(url):
        return None
    for policy in SUPPRESSED_THIRD_PARTY_TELEMETRY:
        if host != str(policy["host"]).lower():
            continue
        if path != policy["path"]:
            continue
        if method.upper() not in policy["methods"]:
            continue
        if resource_type not in policy["resource_types"]:
            continue
        return policy
    return None


def load_cookies(cookie_file: Path) -> list[dict[str, Any]]:
    raw = json.loads(cookie_file.read_text(encoding="utf-8"))
    cookies = []
    for cookie in raw:
        item = {
            "name": cookie["name"],
            "value": cookie["value"],
            "domain": cookie["domain"],
            "path": cookie.get("path", "/"),
            "httpOnly": cookie.get("httpOnly", False),
            "secure": cookie.get("secure", False),
        }
        same_site = cookie.get("sameSite")
        if same_site in ("lax", "strict", "none", "Lax", "Strict", "None"):
            item["sameSite"] = same_site.capitalize() if same_site.lower() != "none" else "None"
        if "expirationDate" in cookie:
            item["expires"] = int(cookie["expirationDate"])
        cookies.append(item)
    return cookies


def collect_visible_matches(page) -> list[dict[str, Any]]:
    return page.evaluate(
        """
        () => {
          const targets = ['速卖通','AliExpress','采集箱','认领','编辑','发布','保存','店铺','所属店铺','授权店铺','半托管'];
          const out = [];
          for (const el of document.querySelectorAll('a,button,span,div,td,th,input')) {
            const txt = (el.innerText || el.textContent || el.getAttribute('value') || '').replace(/\\s+/g, ' ').trim();
            if (!txt) continue;
            if (!targets.some(t => txt === t || txt.includes(t))) continue;
            const st = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity || '1') === 0 || r.width < 5 || r.height < 5) continue;
            out.push({text: txt.slice(0,120), tag: el.tagName, href: el.getAttribute('href'), cls: String(el.className || ''), id: el.id || '', rect: {x:r.x,y:r.y,w:r.width,h:r.height}});
          }
          return out.slice(0,150);
        }
        """
    )


def sanitize_visible_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized = []
    for item in matches:
        sanitized.append({
            **item,
            "text": redact_sensitive_text(str(item.get("text") or "")),
            "href": sanitize_url(str(item.get("href") or "")) if item.get("href") else None,
            "cls": redact_sensitive_text(str(item.get("cls") or ""))[:160],
            "id": redact_sensitive_text(str(item.get("id") or ""))[:80],
        })
    return sanitized


def is_dianxiaomi_url(url: str) -> bool:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return False
    return host == "dianxiaomi.com" or host.endswith(".dianxiaomi.com")


def detect_login_state(
    *,
    required: bool,
    cookies_loaded: bool,
    final_url: str,
    title: str,
    body_text: str,
) -> dict[str, Any]:
    signals = []
    lowered_url = final_url.lower()
    if any(keyword in lowered_url for keyword in LOGIN_URL_KEYWORDS):
        signals.append("login_url")
    login_text_source = f"{title}\n{body_text[:3000]}"
    if any(keyword in login_text_source for keyword in LOGIN_TEXT_KEYWORDS):
        signals.append("login_text")
    return {
        "required": required,
        "cookies_loaded": cookies_loaded,
        "suspected_login_page": bool(signals),
        "signals": signals,
    }


def redact_sensitive_text(text: str) -> str:
    redacted = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", text)
    redacted = re.sub(r"\b1[3-9]\d{9}\b", "[redacted-phone]", redacted)
    redacted = re.sub(
        r"(?i)\b(password|passwd|token|cookie|session|sid)\s*[:=]\s*[^\s<>&]{4,}",
        r"\1=[redacted]",
        redacted,
    )
    return redacted


def sanitize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "[invalid-url]"
    query = "__redacted__" if parts.query else ""
    fragment = "__redacted__" if parts.fragment else ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, fragment))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_probe_run_metadata(*, run_id: str, cookie_file: Path) -> dict[str, Any]:
    cookie_sha256 = sha256_file(cookie_file) if cookie_file.exists() else None
    try:
        git_head = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        git_head = "unknown"
    metadata = {
        "run_id": run_id,
        "script_sha256": sha256_file(Path(__file__)),
        "git_head": git_head,
        "cookie_file_sha256": cookie_sha256,
    }
    metadata["evidence_binding"] = {
        "schema": "dxm_l2_evidence_binding.v1",
        "run_id": run_id,
        "target_set": sorted(TARGETS),
        "session_fingerprint_sha256": cookie_sha256,
        "script_path": "tools/probes/l2_readonly_probe.py",
        "script_sha256": metadata["script_sha256"],
        "git_head": git_head,
        "git_dirty": None,
        "git_diff_sha256": None,
    }
    return metadata


def render_markdown(result: dict[str, Any]) -> str:
    network = result.get("network") or {}
    safety = result.get("safety") or {}
    allowlist = result.get("allowlist") or {}
    reasons = safety.get("reasons") or ["无"]
    run_id = result.get("run_id") or "未记录"
    script_sha256 = result.get("script_sha256") or "未记录"
    git_head = result.get("git_head") or "未记录"
    cookie_file_sha256 = result.get("cookie_file_sha256") or "未记录"
    return f"""# L2 只读 Probe 证据

## 基本信息
- target：{result.get("target")}
- target_url：{result.get("target_url")}
- final_url：{result.get("final_url")}
- title：{result.get("title")}
- created_at：{result.get("created_at")}
- ok：{result.get("ok")}
- run_id：{run_id}
- script_sha256：{script_sha256}
- git_head：{git_head}
- cookie_file_sha256：{cookie_file_sha256}
- evidence_binding：`{json.dumps(result.get("evidence_binding") or {}, ensure_ascii=False)}`

## 环境
- OS：{result.get("environment", {}).get("os")}
- Browser：{result.get("environment", {}).get("browser_version")}
- Python：{result.get("environment", {}).get("python")}
- headless：{result.get("environment", {}).get("headless")}

## 只读安全断言
- 允许只读方法：{", ".join(safety.get("read_methods_allowed") or [])}
- 允许被动资源类型：{", ".join(network.get("passive_resource_types_allowed") or sorted(PASSIVE_RESOURCE_TYPES))}
- 阻断主动资源类型：{", ".join(network.get("active_resource_types_blocked") or sorted(ACTIVE_RESOURCE_TYPES))}
- 真实站点严格拦截主动请求：{network.get("strict_active_requests", False)}
- allowlist 文件：{allowlist.get("file") or "未启用"}
- allowlist_sha256：{allowlist.get("file_sha256") or "未记录"}
- allowlist_applied：{network.get("allowlist_applied", False)}
- allowlist 放行请求数量：{network.get("allowlisted_request_count", 0)}
- 观测到 HTTP 写方法数量：{network.get("observed_write_method_request_count", 0)}
- allowlist 放行查询型非 GET 数量：{network.get("allowlisted_non_read_request_count", 0)}
- 预拦截第三方请求数量：{network.get("suppressed_request_count", 0)}
- 写方法禁止：{", ".join(safety.get("write_methods_forbidden") or [])}
- 禁用 URL 关键词：{", ".join(safety.get("forbidden_url_keywords") or [])}
- 写请求数量：{network.get("write_request_count")}
- 非只读请求数量：{network.get("non_read_request_count")}
- 被拦截请求数量：{network.get("blocked_request_count")}
- 禁用关键词命中请求数量：{network.get("forbidden_keyword_request_count")}
- WebSocket 数量：{network.get("websocket_count")}
- 安全原因：{"；".join(reasons)}

## 登录态
```json
{json.dumps(result.get("login_state") or {}, ensure_ascii=False, indent=2)}
```

## 证据文件
- screenshot：`{result.get("screenshot_path")}`
- screenshot_sha256：`{result.get("screenshot_sha256")}`
- dom：`{result.get("dom_path")}`
- dom_sha256：`{result.get("dom_sha256")}`
- json：`{result.get("json_path")}`
- markdown：`{result.get("markdown_path")}`

## 网络摘要
```json
{json.dumps(network, ensure_ascii=False, indent=2)}
```

## 失败诊断
```json
{json.dumps(result.get("diagnostics") or {}, ensure_ascii=False, indent=2)}
```
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a guarded L2 read-only Dianxiaomi probe.")
    parser.add_argument("--target", choices=sorted(TARGETS), default="data_acquisition")
    parser.add_argument("--url", default=None, help="Override target URL, mainly for local/mock verification.")
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--wait-ms", type=int, default=3500)
    parser.add_argument("--run-id", default=None, help="Shared identifier for both real L2 targets in one approved probe run.")
    parser.add_argument(
        "--allowlist-file",
        default=None,
        help="Explicit reviewed L2 read-only allowlist JSON. Not applied unless this flag is provided.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = args.target
    url = args.url or TARGETS[target]
    result = run_probe(
        target=target,
        url=url,
        cookie_file=Path(args.cookie_file),
        output_dir=Path(args.output_dir),
        headless=not args.headed,
        wait_ms=args.wait_ms,
        run_id=args.run_id,
        allowlist_file=Path(args.allowlist_file) if args.allowlist_file else None,
    )
    print(json.dumps(summarize_for_stdout(result), ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


def summarize_for_stdout(result: dict[str, Any]) -> dict[str, Any]:
    network = result.get("network") or {}
    return {
        "schema": result.get("schema"),
        "ok": result.get("ok"),
        "target": result.get("target"),
        "run_id": result.get("run_id"),
        "script_sha256": result.get("script_sha256"),
        "git_head": result.get("git_head"),
        "final_url": result.get("final_url"),
        "safety": result.get("safety"),
        "network": {
            "request_count": network.get("request_count"),
            "methods_seen": network.get("methods_seen"),
            "write_request_count": network.get("write_request_count"),
            "non_read_request_count": network.get("non_read_request_count"),
            "blocked_request_count": network.get("blocked_request_count"),
            "forbidden_keyword_request_count": network.get("forbidden_keyword_request_count"),
            "allowlisted_request_count": network.get("allowlisted_request_count"),
            "suppressed_request_count": network.get("suppressed_request_count"),
            "websocket_count": network.get("websocket_count"),
        },
        "evidence": {
            "screenshot_path": result.get("screenshot_path"),
            "screenshot_sha256": result.get("screenshot_sha256"),
            "dom_path": result.get("dom_path"),
            "dom_sha256": result.get("dom_sha256"),
            "json_path": result.get("json_path"),
            "markdown_path": result.get("markdown_path"),
        },
    }


if __name__ == "__main__":
    raise SystemExit(main())
