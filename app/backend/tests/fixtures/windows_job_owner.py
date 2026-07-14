from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from src.services.windows_job import WindowsJobError, ensure_backend_job_owner


DESCENDANT_TTL_SECONDS = 120


def main() -> int:
    try:
        ensure_backend_job_owner()
    except WindowsJobError as exc:
        print(
            json.dumps(
                {"status": "error", "stage": exc.stage, "errorCode": exc.error_code},
                separators=(",", ":"),
            ),
            flush=True,
        )
        return 70

    # The TTL is far beyond every proof deadline, so a signal inside five
    # seconds of owner exit cannot be mistaken for natural expiry. The test
    # holds an exact PROCESS_TERMINATE handle for bounded failure cleanup.
    descendant_started_at_unix_ms = int(time.time() * 1000)
    descendant = subprocess.Popen(
        [
            sys._base_executable,
            "-c",
            f"import time; time.sleep({DESCENDANT_TTL_SECONDS})",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    print(
        json.dumps(
            {
                "status": "ready",
                "ownerPid": os.getpid(),
                "descendantPid": descendant.pid,
                "descendantTtlSeconds": DESCENDANT_TTL_SECONDS,
                "descendantStartedAtUnixMs": descendant_started_at_unix_ms,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )
    if sys.stdin.readline() != "EXIT\n":
        os._exit(71)
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
