from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROBE_SCRIPT = ROOT / "tools" / "probes" / "l2_readonly_probe.py"
DEFAULT_COOKIE_FILE = ROOT / "data" / "sessions" / "dianxiaomi_cookies.json"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "l2_readonly_probe"
DEFAULT_ALLOWLIST_FILE = ROOT / "config" / "l2_readonly_allowlist.json"
REQUIRED_TARGETS = ("data_acquisition", "draft_box")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the approved dual-target L2 readonly probe.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--script", default=str(DEFAULT_PROBE_SCRIPT))
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE_FILE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--allowlist-file", default=str(DEFAULT_ALLOWLIST_FILE))
    parser.add_argument("--lock-file", default="")
    parser.add_argument("--headed", action="store_true", help="Show the real browser window while running read-only probes.")
    parser.add_argument("--target", action="append", choices=REQUIRED_TARGETS, dest="targets")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        targets = tuple(args.targets or REQUIRED_TARGETS)
        print(f"[l2-readonly-runner] started run_id={args.run_id} targets={','.join(targets)} at={_now()}", flush=True)
        exit_codes: list[int] = []
        for target in targets:
            command = [
                args.python,
                str(args.script),
                "--target",
                target,
                "--run-id",
                args.run_id,
                "--cookie-file",
                str(args.cookie_file),
                "--output-dir",
                str(args.output_dir),
                "--allowlist-file",
                str(args.allowlist_file),
            ]
            if args.headed:
                command.append("--headed")
            print(f"[l2-readonly-runner] target={target} command={' '.join(command)}", flush=True)
            result = subprocess.run(command, cwd=str(ROOT), check=False)
            exit_codes.append(result.returncode)
            print(f"[l2-readonly-runner] target={target} exit_code={result.returncode} at={_now()}", flush=True)
        final_code = max(exit_codes or [1])
        print(f"[l2-readonly-runner] finished run_id={args.run_id} exit_code={final_code} at={_now()}", flush=True)
        return final_code
    finally:
        _release_lock(args.lock_file, args.run_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _release_lock(lock_file: str, run_id: str) -> None:
    if not lock_file:
        return
    path = Path(lock_file)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if payload.get("run_id") == run_id:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
