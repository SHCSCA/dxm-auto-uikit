from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "app" / "backend"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from src.services.selector_profile import SelectorProfileService  # noqa: E402


DEFAULT_FIXTURE_DIR = ROOT / "tools" / "probes" / "fixtures" / "l1_selector_replay"
DEFAULT_MANIFEST = DEFAULT_FIXTURE_DIR / "manifest.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "l1_selector_replay"
FORBIDDEN_VISIBLE_TEXTS = ("发布", "立即发布", "继续发布", "保存并发布", "确认发布", "提交发布", "移入待发布")


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[dict[str, Any]] = []
        self.nodes: list[dict[str, Any]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack.append({"tag": tag.lower(), "attrs": dict(attrs), "text": []})

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] != lowered:
                continue
            node = self._stack.pop(index)
            text = normalize_text("".join(node["text"]))
            if text:
                self.nodes.append({"tag": node["tag"], "attrs": node["attrs"], "text": text})
            if self._stack:
                self._stack[-1]["text"].append(text)
            return

    def handle_data(self, data: str) -> None:
        text = normalize_text(data)
        if not text:
            return
        self.text_parts.append(text)
        if self._stack:
            self._stack[-1]["text"].append(text)

    def close(self) -> None:
        super().close()
        while self._stack:
            node = self._stack.pop()
            text = normalize_text("".join(node["text"]))
            if text:
                self.nodes.append({"tag": node["tag"], "attrs": node["attrs"], "text": text})


def run_replay(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"l1_selector_replay_{timestamp}.json"
    markdown_path = output_dir / f"l1_selector_replay_{timestamp}.md"

    service = SelectorProfileService()
    cases = []
    for case in manifest.get("cases") or []:
        cases.append(replay_case(service, case, fixture_dir))

    result = {
        "schema": "dxm_l1_selector_replay.v1",
        "ok": all(case["ok"] for case in cases),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
        },
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "case_count": len(cases),
        "passed_count": sum(1 for case in cases if case["ok"]),
        "failed_count": sum(1 for case in cases if not case["ok"]),
        "cases": cases,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(result), encoding="utf-8")
    return result


def replay_case(service: SelectorProfileService, case: dict[str, Any], fixture_dir: Path) -> dict[str, Any]:
    fixture_path = fixture_dir / str(case["fixture"])
    html = fixture_path.read_text(encoding="utf-8")
    parsed = parse_html(html)
    visible_buttons = [node["text"] for node in parsed["nodes"] if node["tag"] in {"button", "a"}]
    profile_result = service.validate_page(
        page_key=str(case["page_key"]),
        url=str(case["url"]),
        body_text=parsed["body_text"],
        visible_buttons=visible_buttons,
    )
    required_missing = [
        text for text in case.get("required_texts") or []
        if normalize_compact(text) not in normalize_compact(parsed["body_text"])
    ]
    check_results = [run_named_check(name, parsed, visible_buttons) for name in case.get("checks") or []]
    failures = [
        *[f"profile:{item}" for item in profile_result.get("missing") or []],
        *[f"required_text:{item}" for item in required_missing],
        *[f"forbidden_button:{item}" for item in profile_result.get("forbidden_hits") or []],
        *[f"{item['check']}:{item['reason']}" for item in check_results if not item["ok"]],
    ]
    return {
        "id": case.get("id"),
        "page_key": case.get("page_key"),
        "url": case.get("url"),
        "fixture_path": str(fixture_path),
        "fixture_sha256": sha256_file(fixture_path),
        "ok": not failures,
        "profile_result": profile_result,
        "required_missing": required_missing,
        "visible_button_count": len(visible_buttons),
        "visible_buttons": visible_buttons[:50],
        "checks": check_results,
        "failures": failures,
    }


def parse_html(html: str) -> dict[str, Any]:
    parser = TextExtractor()
    parser.feed(html)
    parser.close()
    return {
        "body_text": normalize_text(" ".join(parser.text_parts)),
        "nodes": parser.nodes,
    }


def run_named_check(name: str, parsed: dict[str, Any], visible_buttons: list[str]) -> dict[str, Any]:
    body = parsed["body_text"]
    nodes = parsed["nodes"]
    checks = {
        "product_box_row_identity": lambda: contains_all(
            body,
            ["绝区零妄想天使南宫羽猫咪话筒麦克风cos道具", "Dang Kang"],
        ),
        "publish_button_absent": lambda: not any(exact_or_contains(button, FORBIDDEN_VISIBLE_TEXTS) for button in visible_buttons),
        "eu_outer_package_image_bank": lambda: contains_all(body, ["外包装/标签实拍图-欧盟", "添加图片", "图片银行（速卖通）"]),
        "marketing_white_background": lambda: contains_all(body, ["营销图片", "1:1白底图", "3:4场景图", "图片白底", "一键白底"]),
        "semi_managed_fields": lambda: contains_all(body, ["半托管信息", "JIT库存", "是否原箱", "物流属性"]),
        "save_only_button_filter": lambda: any(node["tag"] == "button" and normalize_compact(node["text"]) == "保存" for node in nodes),
    }
    if name not in checks:
        return {"check": name, "ok": False, "reason": "unknown_check"}
    ok = bool(checks[name]())
    return {"check": name, "ok": ok, "reason": None if ok else "missing_expected_dom_signal"}


def contains_all(text: str, values: list[str]) -> bool:
    compact = normalize_compact(text)
    return all(normalize_compact(value) in compact for value in values)


def exact_or_contains(text: str, values: tuple[str, ...]) -> bool:
    compact = normalize_compact(text)
    return any(compact == normalize_compact(value) or normalize_compact(value) in compact for value in values)


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def normalize_compact(value: Any) -> str:
    return "".join(str(value or "").lower().split())


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# L1 Selector Replay 证据",
        "",
        "## 基本信息",
        f"- ok：{result['ok']}",
        f"- created_at：{result['created_at']}",
        f"- manifest：`{result['manifest_path']}`",
        f"- manifest_sha256：`{result['manifest_sha256']}`",
        f"- case_count：{result['case_count']}",
        f"- passed_count：{result['passed_count']}",
        f"- failed_count：{result['failed_count']}",
        "",
        "## 用例",
    ]
    for case in result["cases"]:
        failures = "；".join(case["failures"]) if case["failures"] else "无"
        lines.extend(
            [
                f"### {case['id']}",
                f"- page_key：{case['page_key']}",
                f"- ok：{case['ok']}",
                f"- fixture：`{case['fixture_path']}`",
                f"- fixture_sha256：`{case['fixture_sha256']}`",
                f"- failures：{failures}",
                "",
            ]
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run offline L1 selector/DOM fixture replay.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--fixture-dir", default=str(DEFAULT_FIXTURE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_replay(
        manifest_path=Path(args.manifest),
        fixture_dir=Path(args.fixture_dir),
        output_dir=Path(args.output_dir),
    )
    print(json.dumps({
        "schema": result["schema"],
        "ok": result["ok"],
        "case_count": result["case_count"],
        "passed_count": result["passed_count"],
        "failed_count": result["failed_count"],
        "json_path": result["json_path"],
        "markdown_path": result["markdown_path"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
