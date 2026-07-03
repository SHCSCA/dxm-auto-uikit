from __future__ import annotations

import argparse
import json
import os
import traceback
from pathlib import Path
from typing import Any

from src.execution.dxm_adapter import DxmWorkflowAdapter
from src.execution.dxm_live import DxmLiveClient
from src.execution.dxm_login_flow import DxmLoginFlow
from src.execution.browser_agent_worker import execute_browser_agent_action


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one DXM workflow action in an isolated process.")
    parser.add_argument("--request-file", required=True)
    parser.add_argument("--result-file", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    request_file = Path(args.request_file)
    result_file = Path(args.result_file)
    trace_file = result_file.with_suffix(".trace.jsonl")
    os.environ.setdefault("DXM_WORKFLOW_TRACE_FILE", str(trace_file))
    os.environ.setdefault("DXM_WORKFLOW_PERSISTENT_PROFILE", "1")
    try:
        request = json.loads(request_file.read_text(encoding="utf-8"))
        result = run_action(request)
        if isinstance(result, dict):
            result.setdefault("workflow_trace_file", str(trace_file))
        result_file.parent.mkdir(parents=True, exist_ok=True)
        result_file.write_text(
            json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        result_file.parent.mkdir(parents=True, exist_ok=True)
        result_file.write_text(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=8),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return 1


def run_action(request: dict[str, Any]) -> dict[str, Any]:
    action = str(request.get("action") or "").strip()
    params = request.get("params") if isinstance(request.get("params"), dict) else {}
    adapter = DxmWorkflowAdapter(DxmLoginFlow(DxmLiveClient()))
    return execute_browser_agent_action(adapter, action, params)


if __name__ == "__main__":
    raise SystemExit(main())
