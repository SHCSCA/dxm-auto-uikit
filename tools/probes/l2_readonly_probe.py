from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


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
LOGIN_URL_KEYWORDS = ("login", "passport")
LOGIN_TEXT_KEYWORDS = ("请登录", "登录店小秘", "账户登录", "账号登录", "密码登录")


class ReadOnlyProbeGuard:
    def __init__(
        self,
        forbidden_keywords: tuple[str, ...] = FORBIDDEN_URL_KEYWORDS,
        *,
        strict_active_requests: bool = False,
    ) -> None:
        self.forbidden_keywords = tuple(keyword.lower() for keyword in forbidden_keywords)
        self.strict_active_requests = strict_active_requests
        self.requests: list[dict[str, Any]] = []
        self.blocked_requests: list[dict[str, Any]] = []
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
        self.failures.append({
            "method": request.method,
            "url": sanitize_url(request.url),
            "error_text": failure.get("errorText"),
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

    def summary(self) -> dict[str, Any]:
        methods = sorted({item["method"] for item in self.requests})
        write_requests = [item for item in self.requests if item["method"] in WRITE_METHODS]
        non_read_requests = [item for item in self.requests if item["method"] not in READ_METHODS]
        forbidden_keyword_requests = [
            item for item in self.requests
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
            "blocked_request_count": len(self.blocked_requests),
            "forbidden_keyword_request_count": len(forbidden_keyword_requests),
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
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    screenshot_path = output_dir / f"{target}_{timestamp}.png"
    dom_path = output_dir / f"{target}_{timestamp}.html"
    json_path = output_dir / f"{target}_{timestamp}.json"
    markdown_path = output_dir / f"{target}_{timestamp}.md"

    target_is_dxm = is_dianxiaomi_url(url)
    guard = ReadOnlyProbeGuard(strict_active_requests=target_is_dxm)
    with sync_playwright() as playwright:
        options = chrome_launch_options(headless=headless)
        browser = playwright.chromium.launch(**options)
        context = browser.new_context(
            ignore_https_errors=True,
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
        "safety": {},
    }
    result["safety"] = evaluate_safety(result)
    result["ok"] = bool(result["safety"]["ok"])
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


def render_markdown(result: dict[str, Any]) -> str:
    network = result.get("network") or {}
    safety = result.get("safety") or {}
    reasons = safety.get("reasons") or ["无"]
    return f"""# L2 只读 Probe 证据

## 基本信息
- target：{result.get("target")}
- target_url：{result.get("target_url")}
- final_url：{result.get("final_url")}
- title：{result.get("title")}
- created_at：{result.get("created_at")}
- ok：{result.get("ok")}

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
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a guarded L2 read-only Dianxiaomi probe.")
    parser.add_argument("--target", choices=sorted(TARGETS), default="data_acquisition")
    parser.add_argument("--url", default=None, help="Override target URL, mainly for local/mock verification.")
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--wait-ms", type=int, default=3500)
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
    )
    print(json.dumps(summarize_for_stdout(result), ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


def summarize_for_stdout(result: dict[str, Any]) -> dict[str, Any]:
    network = result.get("network") or {}
    return {
        "schema": result.get("schema"),
        "ok": result.get("ok"),
        "target": result.get("target"),
        "final_url": result.get("final_url"),
        "safety": result.get("safety"),
        "network": {
            "request_count": network.get("request_count"),
            "methods_seen": network.get("methods_seen"),
            "write_request_count": network.get("write_request_count"),
            "non_read_request_count": network.get("non_read_request_count"),
            "blocked_request_count": network.get("blocked_request_count"),
            "forbidden_keyword_request_count": network.get("forbidden_keyword_request_count"),
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
