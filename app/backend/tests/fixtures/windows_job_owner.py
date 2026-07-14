from __future__ import annotations

import json
import os
import subprocess
import sys

from src.services.windows_job import WindowsJobError, ensure_backend_job_owner


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

    # The descendant is intentionally self-limiting. If Job ownership is
    # broken, a failed proof cannot leave a long-lived orphan behind.
    descendant = subprocess.Popen(
        [sys._base_executable, "-c", "import time; time.sleep(20)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    print(
        json.dumps(
            {"status": "ready", "ownerPid": os.getpid(), "descendantPid": descendant.pid},
            separators=(",", ":"),
        ),
        flush=True,
    )
    if sys.stdin.readline() != "EXIT\n":
        os._exit(71)
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
