from __future__ import annotations

import hashlib
from typing import Any

from src.db import connection, dumps, loads
from src.utils import now_iso


def _is_fixture_product(row: dict[str, Any]) -> bool:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    payload_text = " ".join(str(value or "") for value in payload.values()).casefold()
    product_text = " ".join(
        str(value or "")
        for value in (
            row.get("title"),
            row.get("category_name"),
            row.get("source"),
            payload_text,
        )
    ).casefold()
    fixture_markers = (
        "qa guarded",
        "qa_category",
        "fixture",
        "测试商品",
        "示例商品",
        "本地演示",
    )
    return any(marker in product_text for marker in fixture_markers)


class Repository:
    def list_stores(self):
        with connection() as conn:
            return conn.execute("SELECT * FROM stores ORDER BY id DESC").fetchall()

    def create_store(self, name: str, platform: str):
        now = now_iso()
        with connection() as conn:
            cur = conn.execute(
                "INSERT INTO stores (name, platform, status, created_at, updated_at) VALUES (?, ?, 'connected', ?, ?)",
                (name, platform, now, now),
            )
            return conn.execute("SELECT * FROM stores WHERE id=?", (cur.lastrowid,)).fetchone()

    def list_templates(self):
        with connection() as conn:
            rows = conn.execute("SELECT * FROM templates ORDER BY id DESC").fetchall()
            for row in rows:
                row['payload'] = loads(row.pop('payload_json'), {})
                row['is_enabled'] = bool(row['is_enabled'])
            return rows

    def create_template(self, data: dict[str, Any]):
        now = now_iso()
        with connection() as conn:
            cur = conn.execute(
                "INSERT INTO templates (template_type, template_name, binding_scope, payload_json, is_enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    data['template_type'], data['template_name'], data['binding_scope'], dumps(data['payload']), int(data['is_enabled']), now, now,
                ),
            )
            row = conn.execute("SELECT * FROM templates WHERE id=?", (cur.lastrowid,)).fetchone()
            row['payload'] = loads(row.pop('payload_json'), {})
            row['is_enabled'] = bool(row['is_enabled'])
            return row

    def update_template(self, template_id: int, data: dict[str, Any]):
        current = self.get_template(template_id)
        if not current:
            return None
        next_payload = {
            'template_type': data.get('template_type') or current['template_type'],
            'template_name': data.get('template_name') or current['template_name'],
            'binding_scope': data.get('binding_scope') or current['binding_scope'],
            'payload': data['payload'] if data.get('payload') is not None else current['payload'],
            'is_enabled': current['is_enabled'] if data.get('is_enabled') is None else bool(data['is_enabled']),
        }
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "UPDATE templates SET template_type=?, template_name=?, binding_scope=?, payload_json=?, is_enabled=?, updated_at=? WHERE id=?",
                (
                    next_payload['template_type'],
                    next_payload['template_name'],
                    next_payload['binding_scope'],
                    dumps(next_payload['payload']),
                    int(next_payload['is_enabled']),
                    now,
                    template_id,
                ),
            )
        return self.get_template(template_id)

    def get_template(self, template_id: int):
        with connection() as conn:
            row = conn.execute("SELECT * FROM templates WHERE id=?", (template_id,)).fetchone()
            if not row:
                return None
            row['payload'] = loads(row.pop('payload_json'), {})
            row['is_enabled'] = bool(row['is_enabled'])
            return row

    def list_products(self, *, include_fixtures: bool = False):
        with connection() as conn:
            rows = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
            for row in rows:
                row['payload'] = loads(row.pop('payload_json'), {})
            if include_fixtures:
                return rows
            return [row for row in rows if not _is_fixture_product(row)]

    def get_product(self, product_id: int):
        with connection() as conn:
            row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
            if not row:
                return None
            row['payload'] = loads(row.pop('payload_json'), {})
            return row

    def create_product(self, data: dict[str, Any]):
        now = now_iso()
        status = str(data.get('status') or 'draft')
        with connection() as conn:
            cur = conn.execute(
                "INSERT INTO products (title, source, status, category_name, price, currency, sku_count, image_count, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (data['title'], data.get('source', 'manual'), status, data['category_name'], data['price'], data['currency'], data['sku_count'], data['image_count'], dumps(data['payload']), now, now),
            )
            row = conn.execute("SELECT * FROM products WHERE id=?", (cur.lastrowid,)).fetchone()
            row['payload'] = loads(row.pop('payload_json'), {})
            return row

    def create_acquisition_claim_request(self, data: dict[str, Any]):
        payload = {
            'stage': 'pending_acquisition_claim',
            'status': 'pending',
            'store_id': data['store_id'],
            'keyword': data.get('keyword'),
            'category_name': data.get('category_name'),
            'claim_mark': data['claim_mark'],
            'template_id': data.get('template_id'),
        }
        task = self.create_task({
            'name': f"采集认领 - {payload.get('keyword') or payload.get('category_name') or '待选择商品'}",
            'store_id': payload['store_id'],
            'mode': 'claim_only',
            'publish_scene': 'CONTROLLED_CLAIM_TO_DRAFT_ONLY',
            'claim_mark': payload['claim_mark'],
            'product_ids': [],
            'payload': payload,
        })
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "UPDATE tasks SET total_jobs=1, updated_at=? WHERE id=?",
                (now, task['id']),
            )
            conn.execute(
                "INSERT INTO jobs (task_id, product_id, status, created_at, updated_at) VALUES (?, NULL, 'pending', ?, ?)",
                (task['id'], now, now),
            )
        task = self.get_task_private(task['id'])
        task['payload'] = self._public_task_payload(task.get('payload') or {})
        return task

    def bulk_import_products(self, rows: list[dict[str, Any]]):
        created = []
        for row in rows:
            created.append(self.create_product({
                'title': row.get('title', '未命名商品'),
                'source': 'import',
                'category_name': row.get('category_name', '未分类'),
                'price': float(row.get('price', 0) or 0),
                'currency': row.get('currency', 'USD'),
                'sku_count': int(row.get('sku_count', 1) or 1),
                'image_count': int(row.get('image_count', 0) or 0),
                'payload': row,
            }))
        return created

    def list_tasks(self):
        with connection() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
            for row in rows:
                row['payload'] = self._public_task_payload(loads(row.pop('payload_json'), {}))
            return rows

    def get_task(self, task_id: int, *, include_private: bool = False):
        with connection() as conn:
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return None
            payload = loads(task.pop('payload_json'), {})
            task['payload'] = payload if include_private else self._public_task_payload(payload)
            task['jobs'] = conn.execute("SELECT * FROM jobs WHERE task_id=? ORDER BY id ASC", (task_id,)).fetchall()
            return task

    def get_task_private(self, task_id: int):
        return self.get_task(task_id, include_private=True)

    def create_task(self, data: dict[str, Any]):
        now = now_iso()
        payload = dict(data.get('payload') or {})
        payload.pop('manual_approval', None)
        payload.update({
            'product_ids': data.get('product_ids', []),
            'claim_mark': data.get('claim_mark', 'AI认领'),
            'execution_mode': data['mode'],
            'publish_allowed': False,
            'max_count': len(data.get('product_ids', [])),
        })
        with connection() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (name, store_id, status, mode, publish_scene, total_jobs, payload_json, created_at, updated_at) VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
                (data['name'], data.get('store_id'), data['mode'], data['publish_scene'], len(data.get('product_ids', [])), dumps(payload), now, now),
            )
            task_id = cur.lastrowid
            for product_id in data.get('product_ids', []):
                conn.execute(
                    "INSERT INTO jobs (task_id, product_id, status, created_at, updated_at) VALUES (?, ?, 'pending', ?, ?)",
                    (task_id, product_id, now, now),
                )
            task = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            task['payload'] = loads(task.pop('payload_json'), {})
            return task

    def set_task_manual_approval(self, task_id: int, *, approved: bool, token: str, approved_by: str = "system"):
        now = now_iso()
        with connection() as conn:
            task = conn.execute("SELECT payload_json FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return None
            payload = loads(task['payload_json'], {})
            payload['manual_approval'] = {
                'approved': bool(approved),
                'token_hash': hashlib.sha256(token.encode("utf-8")).hexdigest(),
                'approved_by': approved_by,
                'approved_at': now,
                'source': 'server',
            }
            conn.execute(
                "UPDATE tasks SET payload_json=?, updated_at=? WHERE id=?",
                (dumps(payload), now, task_id),
            )
        return self.get_task(task_id)

    def update_task_template_override(self, task_id: int, section: str, values: dict[str, Any]):
        now = now_iso()
        with connection() as conn:
            task = conn.execute("SELECT payload_json FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return None
            payload = loads(task['payload_json'], {})
            if section == 'task_basic':
                allowed = {'store_name', 'category_name', 'claim_mark', 'execution_mode'}
                for key, value in dict(values or {}).items():
                    if key not in allowed:
                        continue
                    if value is None or (isinstance(value, str) and value.strip() == ''):
                        payload.pop(key, None)
                    else:
                        payload[key] = value
                conn.execute(
                    "UPDATE tasks SET payload_json=?, updated_at=? WHERE id=?",
                    (dumps(payload), now, task_id),
                )
                return self.get_task(task_id)
            overrides = payload.get('template_overrides')
            if not isinstance(overrides, dict):
                overrides = {}
            cleaned_values = self._prune_empty_config_values(dict(values or {}))
            if cleaned_values:
                overrides[section] = cleaned_values
            else:
                overrides.pop(section, None)
            if overrides:
                payload['template_overrides'] = overrides
            else:
                payload.pop('template_overrides', None)
            conn.execute(
                "UPDATE tasks SET payload_json=?, updated_at=? WHERE id=?",
                (dumps(payload), now, task_id),
            )
        return self.get_task(task_id)

    def _prune_empty_config_values(self, value: Any):
        if value is None:
            return None
        if isinstance(value, str):
            return value if value.strip() != '' else None
        if isinstance(value, dict):
            cleaned = {}
            for key, child in value.items():
                cleaned_child = self._prune_empty_config_values(child)
                if cleaned_child is not None:
                    cleaned[key] = cleaned_child
            return cleaned or None
        if isinstance(value, list):
            cleaned_items = [
                cleaned_child
                for item in value
                if (cleaned_child := self._prune_empty_config_values(item)) is not None
            ]
            return cleaned_items or None
        return value

    def update_task_status(self, task_id: int, status: str, completed_jobs: int | None = None, failed_jobs: int | None = None):
        now = now_iso()
        with connection() as conn:
            existing = conn.execute("SELECT completed_jobs, failed_jobs FROM tasks WHERE id=?", (task_id,)).fetchone()
            conn.execute(
                "UPDATE tasks SET status=?, completed_jobs=?, failed_jobs=?, updated_at=? WHERE id=?",
                (status, completed_jobs if completed_jobs is not None else existing['completed_jobs'], failed_jobs if failed_jobs is not None else existing['failed_jobs'], now, task_id),
            )

    def try_start_task(self, task_id: int) -> bool:
        now = now_iso()
        with connection() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status='running', updated_at=? WHERE id=? AND status='draft'",
                (now, task_id),
            )
            return cur.rowcount == 1

    def try_pause_task(self, task_id: int) -> bool:
        now = now_iso()
        with connection() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status='paused', updated_at=? WHERE id=? AND status='running'",
                (now, task_id),
            )
            return cur.rowcount == 1

    def try_resume_task(self, task_id: int) -> bool:
        return False

    def _public_task_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        public_payload = dict(payload or {})
        approval = public_payload.get('manual_approval')
        if isinstance(approval, dict):
            public_approval = {
                key: value
                for key, value in approval.items()
                if key not in {'token', 'token_hash'}
            }
            public_payload['manual_approval'] = public_approval
        return public_payload

    def update_job(self, job_id: int, **fields):
        now = now_iso()
        cols = []
        values = []
        for key, value in fields.items():
            cols.append(f"{key}=?")
            values.append(value)
        cols.append("updated_at=?")
        values.append(now)
        values.append(job_id)
        with connection() as conn:
            conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id=?", values)

    def add_log(self, task_id: int, job_id: int | None, level: str, message: str, context: dict[str, Any] | None = None):
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "INSERT INTO job_logs (task_id, job_id, level, message, context_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, job_id, level, message, dumps(context or {}), now),
            )

    def list_logs(self, task_id: int | None = None):
        with connection() as conn:
            if task_id is None:
                rows = conn.execute("SELECT * FROM job_logs ORDER BY id DESC LIMIT 200").fetchall()
            else:
                rows = conn.execute("SELECT * FROM job_logs WHERE task_id=? ORDER BY id DESC LIMIT 200", (task_id,)).fetchall()
            for row in rows:
                row['context'] = loads(row.pop('context_json'), {})
            return rows

    def add_evidence(self, task_id: int, job_id: int | None, evidence_type: str, file_path: str | None, meta: dict[str, Any] | None = None):
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "INSERT INTO job_evidences (task_id, job_id, evidence_type, file_path, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, job_id, evidence_type, file_path, dumps(meta or {}), now),
            )

    def list_evidences(self, task_id: int | None = None):
        with connection() as conn:
            if task_id is None:
                rows = conn.execute("SELECT * FROM job_evidences ORDER BY id DESC LIMIT 200").fetchall()
            else:
                rows = conn.execute("SELECT * FROM job_evidences WHERE task_id=? ORDER BY id DESC LIMIT 200", (task_id,)).fetchall()
            for row in rows:
                row['meta'] = loads(row.pop('meta_json'), {})
            return rows

    def add_exception(self, task_id: int, job_id: int | None, error_code: str, field_domain: str, title: str, detail: str, suggestion: str):
        now = now_iso()
        with connection() as conn:
            conn.execute(
                "INSERT INTO exceptions (task_id, job_id, error_code, field_domain, title, detail, suggestion, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, job_id, error_code, field_domain, title, detail, suggestion, now, now),
            )

    def list_exceptions(self):
        with connection() as conn:
            return conn.execute("SELECT * FROM exceptions ORDER BY id DESC LIMIT 200").fetchall()

    def add_report(
        self,
        task_id: int,
        job_id: int | None,
        product_id: int | None,
        status: str,
        published: bool,
        save_result: dict[str, Any],
        summary: dict[str, Any],
    ):
        now = now_iso()
        with connection() as conn:
            existing = conn.execute(
                "SELECT id FROM reports WHERE task_id=? AND job_id=?",
                (task_id, job_id),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE reports
                    SET product_id=?, status=?, published=?, save_result_json=?, summary_json=?, updated_at=?
                    WHERE id=?
                    """,
                    (product_id, status, int(published), dumps(save_result), dumps(summary), now, existing['id']),
                )
                report_id = existing['id']
            else:
                cur = conn.execute(
                    """
                    INSERT INTO reports (
                        task_id, job_id, product_id, status, published,
                        save_result_json, summary_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (task_id, job_id, product_id, status, int(published), dumps(save_result), dumps(summary), now, now),
                )
                report_id = cur.lastrowid
            return self.get_report(report_id)

    def get_report(self, report_id: int):
        with connection() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                return None
            row['published'] = bool(row['published'])
            row['save_result'] = loads(row.pop('save_result_json'), {})
            row['summary'] = loads(row.pop('summary_json'), {})
            return row

    def list_reports(self, task_id: int | None = None):
        with connection() as conn:
            if task_id is None:
                rows = conn.execute("SELECT * FROM reports ORDER BY id DESC LIMIT 200").fetchall()
            else:
                rows = conn.execute("SELECT * FROM reports WHERE task_id=? ORDER BY id ASC", (task_id,)).fetchall()
            for row in rows:
                row['published'] = bool(row['published'])
                row['save_result'] = loads(row.pop('save_result_json'), {})
                row['summary'] = loads(row.pop('summary_json'), {})
            return rows
