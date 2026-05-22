import importlib.util
import json
import sqlite3
from pathlib import Path


def _load_generator():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "report" / "generate_v1_acceptance_record.py"
    spec = importlib.util.spec_from_file_location("generate_v1_acceptance_record", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_acceptance_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE stores (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            platform TEXT NOT NULL,
            status TEXT NOT NULL,
            last_login_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            category_name TEXT,
            price REAL,
            currency TEXT,
            sku_count INTEGER,
            image_count INTEGER,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            store_id INTEGER,
            status TEXT NOT NULL,
            mode TEXT NOT NULL,
            publish_scene TEXT NOT NULL,
            total_jobs INTEGER NOT NULL,
            completed_jobs INTEGER NOT NULL,
            failed_jobs INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            product_id INTEGER,
            status TEXT NOT NULL,
            current_step_code TEXT,
            current_step_name TEXT,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE reports (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            job_id INTEGER,
            product_id INTEGER,
            status TEXT NOT NULL,
            published INTEGER NOT NULL,
            save_result_json TEXT NOT NULL,
            summary_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE job_evidences (
            id INTEGER PRIMARY KEY,
            task_id INTEGER NOT NULL,
            job_id INTEGER,
            evidence_type TEXT NOT NULL,
            file_path TEXT,
            meta_json TEXT,
            created_at TEXT NOT NULL
        );
        """
    )
    save_result = {
        "ok": True,
        "message": "已点击保存",
        "published": False,
        "clicked": True,
        "success_text": "编辑成功",
        "network_events": [],
        "network_save_result": {"ok": None, "reason": "未捕获保存相关接口响应"},
    }
    summary = {
        "task_id": 19,
        "job_id": 31,
        "product_id": 24,
        "store_name": "Dang Kang",
        "source_title": "绝区零妄想天使南宫羽猫咪话筒麦克风cos道具",
        "category": "立牌",
        "claim_mark": "AI认领-19-31",
        "mode": "single_save",
        "status": "success",
        "blocked_reason": None,
        "empty_fields": ["货品条码：配置允许留空"],
        "filled_fields": ["base_info", "variants", "media", "compliance", "semi_goods", "semi_variants"],
        "evidence_paths": [
            "data/screenshots/v1_task_19_job_31_SAVE_ONLY.txt",
            "data/screenshots/v1_task_19_job_31_VERIFY_NOT_PUBLISHED.txt",
        ],
        "workflow_actions": ["save_only", "verify_not_published"],
        "workflow_results": [
            {
                "action": "save_only",
                "ok": True,
                "screenshot_url": "/artifacts/screenshots/dianxiaomi_save_only.png",
                "save_result": save_result,
            },
            {
                "action": "verify_not_published",
                "ok": True,
                "screenshot_url": "/artifacts/screenshots/dianxiaomi_verify_not_published.png",
            },
        ],
        "agent_console": {
            "session_id": "agent-test",
            "browser_visible": True,
            "current_url": "https://www.dianxiaomi.com/web/smt/editFromSmt",
            "last_step_code": "RELEASE_LOCK",
            "last_step_name": "释放商品归属锁",
            "hud": {
                "state": "RELEASE_LOCK",
                "guard": "只保存不发布",
                "next_step": "任务收尾与报告",
            },
            "screenshot": "data/screenshots/agent_console/agent-test.png",
        },
        "agent_console_events": [
            {"last_step_code": "PRECHECK_CONFIG"},
            {"last_step_code": "SAVE_ONLY"},
            {"last_step_code": "RELEASE_LOCK"},
        ],
        "published": False,
    }
    conn.execute(
        "INSERT INTO stores VALUES (5, 'Dang Kang', 'AliExpress', 'connected', NULL, '2026-05-19T08:10:55Z', '2026-05-19T08:10:55Z')"
    )
    conn.execute(
        """
        INSERT INTO products VALUES (
            24, '绝区零妄想天使南宫羽猫咪话筒麦克风cos道具', 'live_validation', 'draft',
            '立牌类谷子', 7.15, 'USD', 1, 1, ?, '2026-05-21T07:40:19Z', '2026-05-21T07:40:19Z'
        )
        """,
        (json.dumps({"source_title": summary["source_title"]}, ensure_ascii=False),),
    )
    conn.execute(
        """
        INSERT INTO tasks VALUES (
            19, '真实验收-只保存', 5, 'completed', 'single_save', 'SMT_SEMI_MANAGED_SAVE_ONLY',
            1, 1, 0, ?, '2026-05-21T08:07:01Z', '2026-05-22T01:57:14Z'
        )
        """,
        (json.dumps({"claim_mark": "AI认领", "store_name": "Dang Kang"}, ensure_ascii=False),),
    )
    conn.execute(
        "INSERT INTO jobs VALUES (31, 19, 24, 'succeeded', 'DONE', 'V1 执行完成', NULL, NULL, '2026-05-21T08:07:01Z', '2026-05-22T01:57:14Z')"
    )
    conn.execute(
        "INSERT INTO reports VALUES (11, 19, 31, 24, 'success', 0, ?, ?, '2026-05-21T08:11:49Z', '2026-05-22T01:57:14Z')",
        (json.dumps(save_result, ensure_ascii=False), json.dumps(summary, ensure_ascii=False)),
    )
    conn.execute(
        "INSERT INTO job_evidences VALUES (1, 19, 31, 'state_snapshot', 'data/screenshots/old_PRECHECK_CONFIG.txt', ?, '2026-05-22T00:00:00Z')",
        (json.dumps({"state": "PRECHECK_CONFIG"}, ensure_ascii=False),),
    )
    conn.execute(
        "INSERT INTO job_evidences VALUES (2, 19, 31, 'workflow_action', '/artifacts/screenshots/old_save.png', ?, '2026-05-22T00:01:00Z')",
        (json.dumps({"state": "SAVE_ONLY", "action": "save_only"}, ensure_ascii=False),),
    )
    conn.execute(
        "INSERT INTO job_evidences VALUES (676, 19, 31, 'state_snapshot', 'data/screenshots/v1_task_19_job_31_PRECHECK_CONFIG.txt', ?, '2026-05-22T01:55:49Z')",
        (json.dumps({"state": "PRECHECK_CONFIG"}, ensure_ascii=False),),
    )
    conn.execute(
        "INSERT INTO job_evidences VALUES (677, 19, 31, 'workflow_action', '/artifacts/screenshots/dianxiaomi_save_only.png', ?, '2026-05-22T01:56:56Z')",
        (json.dumps({"state": "SAVE_ONLY", "action": "save_only"}, ensure_ascii=False),),
    )
    conn.execute(
        "INSERT INTO job_evidences VALUES (680, 19, 31, 'workflow_action', '/artifacts/screenshots/dianxiaomi_verify_not_published.png', ?, '2026-05-22T01:57:14Z')",
        (json.dumps({"state": "VERIFY_NOT_PUBLISHED", "action": "verify_not_published"}, ensure_ascii=False),),
    )
    conn.commit()
    conn.close()


def test_generate_v1_acceptance_record_covers_required_evidence(tmp_path):
    module = _load_generator()
    db_path = tmp_path / "acceptance.db"
    _create_acceptance_db(db_path)

    markdown = module.generate_markdown(db_path=db_path, report_id=11, repo_root=tmp_path)

    assert "report_id=11 / task_id=19 / job_id=31" in markdown
    assert "绝区零妄想天使南宫羽猫咪话筒麦克风cos道具" in markdown
    assert "Dang Kang" in markdown
    assert "AI认领-19-31" in markdown
    assert "data/screenshots/dianxiaomi_save_only.png" in markdown
    assert "data/screenshots/dianxiaomi_verify_not_published.png" in markdown
    assert "python scripts/report/generate_v1_acceptance_record.py --report-id 11" in markdown
    assert "data/screenshots/v1_task_19_job_31_SAVE_ONLY.txt" in markdown
    assert "未捕获保存相关接口响应" in markdown
    assert "published=false" in markdown
    assert "Agent Console 可见执行证据" in markdown
    assert "session_id：agent-test" in markdown
    assert "guard=只保存不发布" in markdown
    assert "event_count：3" in markdown
    assert "old_save.png" not in markdown
