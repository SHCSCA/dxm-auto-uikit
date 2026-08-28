import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_repository_imports_in_a_clean_interpreter_without_batch_edit_cycle():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.repository import Repository; print(Repository.__name__)",
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Repository"
