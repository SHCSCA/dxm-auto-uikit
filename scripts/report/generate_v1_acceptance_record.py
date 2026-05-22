from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/sqlite/dxm_auto_uikit.db")
DEFAULT_REPORT_ID = 11
DEFAULT_OUTPUT_PATH = Path("docs/product/V1真实验收记录.md")
SAVE_SCREENSHOT = "data/screenshots/dianxiaomi_save_only.png"
NOT_PUBLISHED_SCREENSHOT = "data/screenshots/dianxiaomi_verify_not_published.png"


def _row_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _fetch_one(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    return conn.execute(sql, params).fetchone()


def _fetch_all(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return conn.execute(sql, params).fetchall()


def _to_repo_relative(path_value: str | None, repo_root: Path) -> str | None:
    if not path_value:
        return None
    normalized = path_value.replace("\\", "/")
    if normalized.startswith("/artifacts/screenshots/"):
        return f"data/screenshots/{Path(normalized).name}"
    path = Path(path_value)
    if path.is_absolute():
        try:
            return path.relative_to(repo_root).as_posix()
        except ValueError:
            return normalized
    return normalized


def _workflow_screenshot(summary: dict[str, Any], action: str, fallback: str, repo_root: Path) -> str:
    for result in summary.get("workflow_results") or []:
        if result.get("action") == action:
            relative = _to_repo_relative(result.get("screenshot_url"), repo_root)
            if relative:
                return relative
    return fallback


def _format_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _format_list(values: list[Any]) -> str:
    if not values:
        return "- 无"
    return "\n".join(f"- {value}" for value in values)


def _evidence_rows(evidences: list[dict[str, Any]], repo_root: Path) -> list[str]:
    rows: list[str] = []
    for evidence in _latest_run_evidences(evidences):
        meta = _loads(evidence.get("meta_json"), {})
        state = meta.get("state") or "-"
        action = meta.get("action") or "-"
        file_path = _to_repo_relative(evidence.get("file_path"), repo_root) or "-"
        rows.append(
            f"| {evidence.get('id')} | {evidence.get('evidence_type')} | {state} | {action} | `{file_path}` |"
        )
    return rows


def _latest_run_evidences(evidences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_start = 0
    for index, evidence in enumerate(evidences):
        meta = _loads(evidence.get("meta_json"), {})
        if meta.get("state") == "PRECHECK_CONFIG":
            latest_start = index
    return evidences[latest_start:]


def _network_gap(save_result: dict[str, Any]) -> str:
    network_events = save_result.get("network_events")
    network_save_result = save_result.get("network_save_result") or {}
    reason = network_save_result.get("reason") or "未记录保存接口响应"
    if network_events:
        return "保存动作记录到了网络事件；仍需人工核对是否覆盖保存接口完整响应。"
    if network_save_result.get("ok") is None:
        return f"{reason}；本次验收以页面保存成功文案、保存动作截图、未发布校验截图和 report.published=false 组成证据链。"
    return f"network_save_result={_format_json(network_save_result)}"


def _existing_note(path_value: str, repo_root: Path) -> str:
    return "存在" if (repo_root / path_value).exists() else "运行数据未随 git 提交"


def generate_markdown(db_path: str | Path, report_id: int = DEFAULT_REPORT_ID, repo_root: str | Path = ".") -> str:
    db_path = Path(db_path)
    repo_root = Path(repo_root).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = _row_factory
    try:
        report = _fetch_one(conn, "SELECT * FROM reports WHERE id=?", (report_id,))
        if not report:
            raise ValueError(f"report id {report_id} not found")

        summary = _loads(report.get("summary_json"), {})
        save_result = _loads(report.get("save_result_json"), {})
        task = _fetch_one(conn, "SELECT * FROM tasks WHERE id=?", (report["task_id"],))
        job = _fetch_one(conn, "SELECT * FROM jobs WHERE id=?", (report["job_id"],))
        product = _fetch_one(conn, "SELECT * FROM products WHERE id=?", (report["product_id"],))
        store = _fetch_one(conn, "SELECT * FROM stores WHERE id=?", (task["store_id"],)) if task and task.get("store_id") else None
        evidences = _fetch_all(
            conn,
            "SELECT * FROM job_evidences WHERE task_id=? AND job_id=? ORDER BY id",
            (report["task_id"], report["job_id"]),
        )
    finally:
        conn.close()

    task_payload = _loads(task.get("payload_json"), {}) if task else {}
    product_payload = _loads(product.get("payload_json"), {}) if product else {}
    evidence_paths = [
        _to_repo_relative(path, repo_root) or str(path)
        for path in summary.get("evidence_paths") or []
    ]
    save_screenshot = _workflow_screenshot(summary, "save_only", SAVE_SCREENSHOT, repo_root)
    not_published_screenshot = _workflow_screenshot(
        summary,
        "verify_not_published",
        NOT_PUBLISHED_SCREENSHOT,
        repo_root,
    )
    evidence_table = _evidence_rows(evidences, repo_root)
    if not evidence_table:
        evidence_table = ["| - | - | - | - | 未查询到 job_evidences 记录 |"]

    report_status = report.get("status")
    published_text = "true" if bool(report.get("published")) else "false"
    source_title = summary.get("source_title") or product_payload.get("source_title") or (product or {}).get("title") or "-"
    store_name = summary.get("store_name") or task_payload.get("store_name") or (store or {}).get("name") or "-"
    claim_mark = summary.get("claim_mark") or task_payload.get("claim_mark") or "-"
    category = summary.get("category") or (product or {}).get("category_name") or task_payload.get("category_name") or "-"

    return f"""# V1 真实验收记录

## 基本信息
- 验收对象：店小秘速卖通半托管 V1 只保存链路
- 证据索引：report_id={report_id} / task_id={report.get("task_id")} / job_id={report.get("job_id")}
- 验收时间：报告创建 {report.get("created_at")}；最近更新 {report.get("updated_at")}
- 执行模式：{summary.get("mode") or (task or {}).get("mode") or "-"}
- 发布场景：{(task or {}).get("publish_scene") or "-"}
- 报告状态：{report_status}
- published={published_text}

## 验收数据
- 商品：{source_title}
- 商品 ID：{report.get("product_id")}
- 店铺：{store_name}
- 平台：{(store or {}).get("platform") or task_payload.get("platform") or "-"}
- 类目：{category}
- claim_mark：{claim_mark}
- 任务名称：{(task or {}).get("name") or "-"}
- Job 状态：{(job or {}).get("status") or "-"} / {(job or {}).get("current_step_code") or "-"} / {(job or {}).get("current_step_name") or "-"}

## 验收结论
- 保存成功：save_result.ok={save_result.get("ok")}；message={save_result.get("message") or "-"}；success_text={save_result.get("success_text") or "-"}
- 未发布证明：report.published={published_text}；save_result.published={str(save_result.get("published")).lower()}
- 发布边界：任务 publish_scene={((task or {}).get("publish_scene") or "-")}，task.payload.publish_allowed={str(task_payload.get("publish_allowed")).lower()}
- 阻断原因：{summary.get("blocked_reason") or "无"}

## 字段覆盖
已填写字段域：
{_format_list(summary.get("filled_fields") or [])}

允许为空字段：
{_format_list(summary.get("empty_fields") or [])}

## 关键截图证据
| 证据 | 路径 | 状态 |
| --- | --- | --- |
| 保存成功截图 | `{save_screenshot}` | {_existing_note(save_screenshot, repo_root)} |
| 未发布校验截图 | `{not_published_screenshot}` | {_existing_note(not_published_screenshot, repo_root)} |

## 证据路径
状态快照路径：
{_format_list([f"`{path}`" for path in evidence_paths])}

job_evidences 摘要：
| id | 类型 | state | action | file_path |
| --- | --- | --- | --- | --- |
{chr(10).join(evidence_table)}

## 保存结果原文
```json
{_format_json(save_result)}
```

## 网络响应缺口说明
{_network_gap(save_result)}

## 测试命令
```powershell
app\\backend\\.venv\\Scripts\\python.exe -m pytest app\\backend\\tests\\test_v1_acceptance_record_generator.py -q
python scripts/report/generate_v1_acceptance_record.py --report-id 11 --output docs/product/V1真实验收记录.md
```

## 复现边界
- 本记录不启动浏览器、不操作真实店小秘，只整理已落库的 report/task/job/product/store/evidence 数据。
- `data/` 下 SQLite、截图、会话和日志是运行数据，受 `.gitignore` 保护；本文只提交路径和摘要。
- 若需重新验收，必须重新执行真实链路并现场保存截图、日志、网络 HAR 或接口响应。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate V1 real acceptance evidence record from a local SQLite report.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Path to local SQLite DB.")
    parser.add_argument("--report-id", type=int, default=DEFAULT_REPORT_ID, help="Report id to render.")
    parser.add_argument("--output", default=None, help="Optional Markdown output path. Defaults to stdout.")
    parser.add_argument("--repo-root", default=".", help="Repository root used for path normalization and evidence existence checks.")
    args = parser.parse_args()

    markdown = generate_markdown(db_path=args.db, report_id=args.report_id, repo_root=args.repo_root)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
