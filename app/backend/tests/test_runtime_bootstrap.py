from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]


def _isolated_env(data_dir: Path, **overrides: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "DXM_DATA_DIR",
        "DXM_DESKTOP",
        "DXM_RUNTIME_OWNER",
        "DXM_DESKTOP_PARENT_CHANNEL",
        "DXM_BACKEND_INSTANCE_ID",
        "DXM_BUILD_MANIFEST_JSON",
        "DXM_RESOURCE_ROOT",
        "DXM_WORKFLOW_PROFILE_DIR",
    ):
        env.pop(key, None)
    env["DXM_DATA_DIR"] = str(data_dir)
    env.update(overrides)
    return env


def _run_python(code: str, *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _last_json_line(stdout: str) -> dict[str, object]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, f"subprocess emitted no JSON: {stdout!r}"
    return json.loads(lines[-1])


def test_config_import_defines_paths_without_creating_any_runtime_directory(tmp_path):
    data_dir = tmp_path / "config-import-data"
    result = _run_python(
        """
import json
from src.core import config
print(json.dumps({
    'data': config.DATA_DIR.exists(),
    'sqlite': config.SQLITE_DIR.exists(),
    'evidences': config.EVIDENCE_DIR.exists(),
    'screenshots': config.SCREENSHOT_DIR.exists(),
    'sessions': config.SESSION_DIR.exists(),
    'ai': config.AI_DIR.exists(),
}))
""",
        env=_isolated_env(data_dir),
    )

    assert result.returncode == 0, result.stderr
    assert _last_json_line(result.stdout) == {
        "data": False,
        "sqlite": False,
        "evidences": False,
        "screenshots": False,
        "sessions": False,
        "ai": False,
    }
    assert data_dir.exists() is False


def test_config_explicit_directory_creation_creates_runtime_tree(tmp_path):
    data_dir = tmp_path / "explicit-runtime-data"
    result = _run_python(
        """
import json
from src.core import config
before = config.DATA_DIR.exists()
config.ensure_runtime_directories()
print(json.dumps({
    'before': before,
    'data': config.DATA_DIR.is_dir(),
    'sqlite': config.SQLITE_DIR.is_dir(),
    'evidences': config.EVIDENCE_DIR.is_dir(),
    'screenshots': config.SCREENSHOT_DIR.is_dir(),
    'sessions': config.SESSION_DIR.is_dir(),
    'ai': config.AI_DIR.is_dir(),
}))
""",
        env=_isolated_env(data_dir),
    )

    assert result.returncode == 0, result.stderr
    assert _last_json_line(result.stdout) == {
        "before": False,
        "data": True,
        "sqlite": True,
        "evidences": True,
        "screenshots": True,
        "sessions": True,
        "ai": True,
    }


@pytest.mark.parametrize(
    "owner_env",
    [
        {"DXM_RUNTIME_OWNER": "unknown-owner"},
        {"DXM_RUNTIME_OWNER": "direct", "DXM_DESKTOP": "1"},
        {"DXM_RUNTIME_OWNER": "package_probe", "DXM_DESKTOP": "1"},
        {"DXM_RUNTIME_OWNER": "start_mvp", "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1"},
        {"DXM_RUNTIME_OWNER": "package_probe", "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1"},
        {"DXM_RUNTIME_OWNER": "direct", "DXM_DESKTOP_PARENT_CHANNEL": "forged-v1"},
        {
            "DXM_RUNTIME_OWNER": "electron_desktop",
            "DXM_DESKTOP": "1",
            "DXM_BACKEND_INSTANCE_ID": "desktop-no-channel",
        },
    ],
)
def test_invalid_or_forged_owner_facts_fail_before_data_root_write(tmp_path, owner_env):
    from src.services.runtime_bootstrap import RuntimeBootstrapError, build_runtime_bootstrap

    data_dir = tmp_path / "must-not-exist"
    env = {"DXM_DATA_DIR": str(data_dir), **owner_env}

    with pytest.raises(RuntimeBootstrapError):
        build_runtime_bootstrap(
            data_dir=data_dir,
            repo_root=REPO_ROOT,
            environ=env,
            platform_name="nt",
        )

    assert data_dir.exists() is False


@pytest.mark.parametrize(
    "owner_env",
    [
        {"DXM_RUNTIME_OWNER": " direct "},
        {"DXM_RUNTIME_OWNER": "direct", "DXM_DESKTOP": " 0 "},
        {"DXM_RUNTIME_OWNER": "direct", "DXM_DESKTOP_PARENT_CHANNEL": " "},
        {
            "DXM_RUNTIME_OWNER": " electron_desktop ",
            "DXM_DESKTOP": "1",
            "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
            "DXM_BACKEND_INSTANCE_ID": "canonical-instance",
        },
        {
            "DXM_RUNTIME_OWNER": "electron_desktop",
            "DXM_DESKTOP": " 1 ",
            "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
            "DXM_BACKEND_INSTANCE_ID": "canonical-instance",
        },
        {
            "DXM_RUNTIME_OWNER": "electron_desktop",
            "DXM_DESKTOP": "1",
            "DXM_DESKTOP_PARENT_CHANNEL": " stdin-v1 ",
            "DXM_BACKEND_INSTANCE_ID": "canonical-instance",
        },
    ],
)
def test_noncanonical_owner_desktop_or_protocol_fails_before_root_callback(tmp_path, owner_env):
    from src.services.runtime_bootstrap import RuntimeBootstrapError, build_runtime_bootstrap

    data_dir = tmp_path / "noncanonical-facts"
    root_calls = []

    with pytest.raises(RuntimeBootstrapError):
        build_runtime_bootstrap(
            data_dir=data_dir,
            repo_root=REPO_ROOT,
            environ={"DXM_DATA_DIR": str(data_dir), **owner_env},
            identity_factory=_deterministic_identity_factory(),
            parent_channel_getter=lambda _expected: object(),
            data_root_creator=lambda path: root_calls.append(path),
            lease_factory=lambda _path, *, metadata: object(),
            remaining_directories_creator=lambda: None,
        )

    assert root_calls == []
    assert data_dir.exists() is False


def test_bootstrap_order_is_channel_identity_root_lease_job_then_remaining_dirs(tmp_path):
    from src.services.runtime_identity import RuntimeIdentity
    from src.services.runtime_bootstrap import build_runtime_bootstrap

    events: list[str] = []
    data_dir = tmp_path / "ordered-data"
    env = {
        "DXM_RUNTIME_OWNER": "electron_desktop",
        "DXM_DESKTOP": "1",
        "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
        "DXM_BACKEND_INSTANCE_ID": "ordered-instance",
        "DXM_DATA_DIR": str(data_dir),
    }
    channel = object()
    lease = object()
    job = object()

    def require_channel(expected_instance_id):
        events.append("channel")
        assert expected_instance_id == "ordered-instance"
        return channel

    def identity_factory(**kwargs):
        events.append("identity")
        return RuntimeIdentity.from_environment(
            **kwargs,
            git_probe=lambda _root: ("a" * 40, False),
            instance_id_factory=lambda: "must-not-generate",
        )

    def create_root(path):
        events.append("data-root")
        assert path == data_dir.resolve()

    def acquire_lease(path, *, metadata):
        events.append("lease")
        assert path == data_dir.resolve()
        assert metadata["owner"] == "electron_desktop"
        assert metadata["runtimeIdentity"]["instanceId"] == "ordered-instance"
        return lease

    def create_job():
        events.append("job")
        return job

    def create_remaining():
        events.append("remaining-dirs")

    state = build_runtime_bootstrap(
        data_dir=data_dir,
        repo_root=REPO_ROOT,
        package_version="0.1.0",
        environ=env,
        platform_name="nt",
        identity_factory=identity_factory,
        parent_channel_getter=require_channel,
        data_root_creator=create_root,
        lease_factory=acquire_lease,
        job_owner_factory=create_job,
        remaining_directories_creator=create_remaining,
    )

    assert events == ["channel", "identity", "data-root", "lease", "job", "remaining-dirs"]
    assert state.owner == "electron_desktop"
    assert state.data_dir == data_dir.resolve()
    assert state.parent_channel is channel
    assert state.lease is lease
    assert state.windows_job_owner is job
    assert state.runtime_identity.instance_id == "ordered-instance"


def test_main_declares_bootstrap_before_side_effectful_backend_imports():
    source = (BACKEND_ROOT / "src" / "main.py").read_text(encoding="utf-8")

    bootstrap_at = source.index("runtime_bootstrap_state = ensure_runtime_bootstrap(")
    for forbidden_before_bootstrap in (
        "from src.db import init_db",
        "from src.repository import Repository",
        "from src.execution.browser_agent_worker import BrowserAgentRuntime",
        "from src.execution.dxm_login_flow import DxmLoginFlow",
        "from src.services.agent_console import AgentConsoleService",
    ):
        assert bootstrap_at < source.index(forbidden_before_bootstrap)


def test_test_only_bootstrap_reset_has_no_production_call_site():
    call_sites = []
    for path in (BACKEND_ROOT / "src").rglob("*.py"):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "_reset_runtime_bootstrap_for_tests(" not in line:
                continue
            if line.lstrip().startswith("def _reset_runtime_bootstrap_for_tests("):
                continue
            call_sites.append(f"{path.relative_to(BACKEND_ROOT)}:{line_number}")

    assert call_sites == []


def test_invalid_main_owner_import_fails_before_db_artifacts_or_services(tmp_path):
    data_dir = tmp_path / "invalid-main-owner"
    result = _run_python(
        """
import json
import pathlib
import sys

data_dir = pathlib.Path(__import__('os').environ['DXM_DATA_DIR'])
error = None
try:
    import src.main
except BaseException as exc:
    error = {'type': type(exc).__name__, 'message': str(exc)}
print(json.dumps({
    'error': error,
    'dataRootExists': data_dir.exists(),
    'sqliteExists': (data_dir / 'sqlite').exists(),
    'screenshotsExist': (data_dir / 'screenshots').exists(),
    'evidencesExist': (data_dir / 'evidences').exists(),
    'modules': {
        name: name in sys.modules
        for name in (
            'src.db',
            'src.repository',
            'src.execution.browser_agent_worker',
            'src.execution.dxm_login_flow',
            'src.services.agent_console',
            'src.services.title_ai',
        )
    },
}))
""",
        env=_isolated_env(
            data_dir,
            DXM_RUNTIME_OWNER="forged-owner",
            DXM_DESKTOP="1",
        ),
    )

    assert result.returncode == 0, result.stderr
    payload = _last_json_line(result.stdout)
    assert payload["error"]["type"] == "RuntimeBootstrapError"
    assert payload["dataRootExists"] is False
    assert payload["sqliteExists"] is False
    assert payload["screenshotsExist"] is False
    assert payload["evidencesExist"] is False
    assert payload["modules"] == {
        "src.db": False,
        "src.repository": False,
        "src.execution.browser_agent_worker": False,
        "src.execution.dxm_login_flow": False,
        "src.services.agent_console": False,
        "src.services.title_ai": False,
    }


def _deterministic_identity_factory(events: list[str] | None = None):
    from src.services.runtime_identity import RuntimeIdentity

    def create_identity(**kwargs):
        if events is not None:
            events.append("identity")
        return RuntimeIdentity.from_environment(
            **kwargs,
            git_probe=lambda _root: ("b" * 40, False),
            instance_id_factory=lambda: "matrix-instance",
        )

    return create_identity


@pytest.mark.parametrize("owner", ["direct", "start_mvp", "package_probe"])
def test_non_desktop_owner_matrix_always_leases_without_parent_channel_or_job(tmp_path, owner):
    from src.services.runtime_bootstrap import build_runtime_bootstrap

    events: list[str] = []
    data_dir = tmp_path / owner
    lease = object()

    state = build_runtime_bootstrap(
        data_dir=data_dir,
        repo_root=REPO_ROOT,
        environ={
            "DXM_DATA_DIR": str(data_dir),
            "DXM_RUNTIME_OWNER": owner,
            "DXM_DESKTOP": "0",
        },
        platform_name="nt",
        identity_factory=_deterministic_identity_factory(events),
        parent_channel_getter=lambda _instance: (_ for _ in ()).throw(
            AssertionError("non-desktop owner must not inspect a parent channel")
        ),
        data_root_creator=lambda _path: events.append("data-root"),
        lease_factory=lambda _path, *, metadata: events.append("lease") or lease,
        job_owner_factory=lambda: (_ for _ in ()).throw(
            AssertionError("non-desktop owner must not create a Windows Job")
        ),
        remaining_directories_creator=lambda: events.append("remaining-dirs"),
    )

    assert events == ["identity", "data-root", "lease", "remaining-dirs"]
    assert state.owner == owner
    assert state.lease is lease
    assert state.parent_channel is None
    assert state.windows_job_owner is None


def test_electron_desktop_on_posix_requires_armed_channel_but_does_not_invent_windows_job(tmp_path):
    from src.services.runtime_bootstrap import build_runtime_bootstrap

    events: list[str] = []
    data_dir = tmp_path / "posix-electron"
    channel = object()
    env = {
        "DXM_DATA_DIR": str(data_dir),
        "DXM_RUNTIME_OWNER": "electron_desktop",
        "DXM_DESKTOP": "1",
        "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
        "DXM_BACKEND_INSTANCE_ID": "posix-electron-instance",
    }

    state = build_runtime_bootstrap(
        data_dir=data_dir,
        repo_root=REPO_ROOT,
        environ=env,
        platform_name="posix",
        identity_factory=_deterministic_identity_factory(events),
        parent_channel_getter=lambda expected: events.append(f"channel:{expected}") or channel,
        data_root_creator=lambda _path: events.append("data-root"),
        lease_factory=lambda _path, *, metadata: events.append("lease") or object(),
        job_owner_factory=lambda: (_ for _ in ()).throw(
            AssertionError("POSIX must not invent Windows Job ownership")
        ),
        remaining_directories_creator=lambda: events.append("remaining-dirs"),
    )

    assert events == [
        "channel:posix-electron-instance",
        "identity",
        "data-root",
        "lease",
        "remaining-dirs",
    ]
    assert state.parent_channel is channel
    assert state.windows_job_owner is None


def test_electron_parent_channel_getter_cannot_claim_armed_with_none(tmp_path):
    from src.services.runtime_bootstrap import RuntimeBootstrapError, build_runtime_bootstrap

    data_dir = tmp_path / "missing-channel-proof"
    root_calls = []
    with pytest.raises(RuntimeBootstrapError, match="armed parent channel"):
        build_runtime_bootstrap(
            data_dir=data_dir,
            repo_root=REPO_ROOT,
            environ={
                "DXM_DATA_DIR": str(data_dir),
                "DXM_RUNTIME_OWNER": "electron_desktop",
                "DXM_DESKTOP": "1",
                "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
                "DXM_BACKEND_INSTANCE_ID": "missing-channel-proof",
            },
            parent_channel_getter=lambda _expected: None,
            data_root_creator=lambda path: root_calls.append(path),
        )

    assert root_calls == []


def test_unknown_injected_platform_cannot_bypass_job_policy(tmp_path):
    from src.services.runtime_bootstrap import RuntimeBootstrapError, build_runtime_bootstrap

    data_dir = tmp_path / "unknown-platform"
    root_calls = []
    with pytest.raises(RuntimeBootstrapError, match="platform"):
        build_runtime_bootstrap(
            data_dir=data_dir,
            repo_root=REPO_ROOT,
            environ={"DXM_DATA_DIR": str(data_dir), "DXM_RUNTIME_OWNER": "direct"},
            platform_name="win32",
            data_root_creator=lambda path: root_calls.append(path),
        )

    assert root_calls == []


def test_lease_factory_cannot_claim_ownership_with_none(tmp_path):
    from src.services.runtime_bootstrap import RuntimeBootstrapError, build_runtime_bootstrap

    events = []
    data_dir = tmp_path / "none-lease"
    with pytest.raises(RuntimeBootstrapError, match="lease factory"):
        build_runtime_bootstrap(
            data_dir=data_dir,
            repo_root=REPO_ROOT,
            environ={"DXM_DATA_DIR": str(data_dir), "DXM_RUNTIME_OWNER": "direct"},
            identity_factory=_deterministic_identity_factory(events),
            data_root_creator=lambda _path: events.append("data-root"),
            lease_factory=lambda _path, *, metadata: events.append("lease") or None,
            remaining_directories_creator=lambda: events.append("remaining-dirs"),
        )

    assert events == ["identity", "data-root", "lease"]


def test_windows_job_factory_cannot_claim_ownership_with_none(tmp_path):
    from src.services.runtime_bootstrap import RuntimeBootstrapError, build_runtime_bootstrap

    events = []
    data_dir = tmp_path / "none-job"
    with pytest.raises(RuntimeBootstrapError, match="Job owner factory"):
        build_runtime_bootstrap(
            data_dir=data_dir,
            repo_root=REPO_ROOT,
            environ={
                "DXM_DATA_DIR": str(data_dir),
                "DXM_RUNTIME_OWNER": "electron_desktop",
                "DXM_DESKTOP": "1",
                "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
                "DXM_BACKEND_INSTANCE_ID": "none-job",
            },
            platform_name="nt",
            identity_factory=_deterministic_identity_factory(events),
            parent_channel_getter=lambda _expected: events.append("channel") or object(),
            data_root_creator=lambda _path: events.append("data-root"),
            lease_factory=lambda _path, *, metadata: events.append("lease") or object(),
            job_owner_factory=lambda: events.append("job") or None,
            remaining_directories_creator=lambda: events.append("remaining-dirs"),
        )

    assert events == ["channel", "identity", "data-root", "lease", "job"]


def test_runtime_bootstrap_state_is_frozen(tmp_path):
    from dataclasses import FrozenInstanceError

    from src.services.runtime_bootstrap import build_runtime_bootstrap

    data_dir = tmp_path / "frozen-state"
    state = build_runtime_bootstrap(
        data_dir=data_dir,
        repo_root=REPO_ROOT,
        environ={"DXM_DATA_DIR": str(data_dir), "DXM_RUNTIME_OWNER": "direct"},
        identity_factory=_deterministic_identity_factory(),
        data_root_creator=lambda _path: None,
        lease_factory=lambda _path, *, metadata: object(),
        remaining_directories_creator=lambda: None,
    )

    with pytest.raises(FrozenInstanceError):
        state.owner = "package_probe"
    with pytest.raises(TypeError):
        state.runtime_identity.payload["instanceId"] = "mutated"


def test_production_ensure_is_thread_safe_and_returns_one_frozen_state_in_subprocess(tmp_path):
    data_dir = tmp_path / "singleton-data"
    result = _run_python(
        """
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MappingProxyType

from src.services.runtime_bootstrap import ensure_runtime_bootstrap

data_dir = Path(__import__('os').environ['DXM_DATA_DIR']).resolve()
counts = {'identity': 0, 'root': 0, 'lease': 0, 'dirs': 0}
counts_lock = threading.Lock()

class Identity:
    instance_id = 'singleton-instance'
    payload = MappingProxyType({'instanceId': instance_id, 'dataDir': str(data_dir)})
    def as_dict(self):
        return dict(self.payload)

def counted(name, value=None):
    with counts_lock:
        counts[name] += 1
    time.sleep(0.01)
    return value

kwargs = dict(
    data_dir=data_dir,
    repo_root=data_dir.parent,
    environ={'DXM_DATA_DIR': str(data_dir), 'DXM_RUNTIME_OWNER': 'direct'},
    identity_factory=lambda **_kwargs: counted('identity', Identity()),
    data_root_creator=lambda _path: counted('root'),
    lease_factory=lambda _path, **_kwargs: counted('lease', object()),
    remaining_directories_creator=lambda: counted('dirs'),
)
with ThreadPoolExecutor(max_workers=32) as pool:
    states = list(pool.map(lambda _index: ensure_runtime_bootstrap(**kwargs), range(128)))
print(json.dumps({
    'counts': counts,
    'oneState': all(state is states[0] for state in states),
    'owner': states[0].owner,
}))
""",
        env=_isolated_env(data_dir),
    )

    assert result.returncode == 0, result.stderr
    assert _last_json_line(result.stdout) == {
        "counts": {"identity": 1, "root": 1, "lease": 1, "dirs": 1},
        "oneState": True,
        "owner": "direct",
    }


def test_lease_failure_stops_before_job_or_remaining_directories(tmp_path):
    from src.services.runtime_bootstrap import build_runtime_bootstrap
    from src.services.runtime_lease import RuntimeLeaseConflictError

    events: list[str] = []
    data_dir = tmp_path / "lease-failure"

    def fail_lease(path, *, metadata):
        events.append("lease")
        raise RuntimeLeaseConflictError(path, None)

    with pytest.raises(RuntimeLeaseConflictError):
        build_runtime_bootstrap(
            data_dir=data_dir,
            repo_root=REPO_ROOT,
            environ={"DXM_DATA_DIR": str(data_dir), "DXM_RUNTIME_OWNER": "direct"},
            identity_factory=_deterministic_identity_factory(events),
            data_root_creator=lambda _path: events.append("data-root"),
            lease_factory=fail_lease,
            job_owner_factory=lambda: events.append("job"),
            remaining_directories_creator=lambda: events.append("remaining-dirs"),
        )

    assert events == ["identity", "data-root", "lease"]


def test_live_lease_conflict_main_import_does_not_touch_db_artifacts_or_services(tmp_path):
    from src.services.runtime_lease import RuntimeDataLease

    data_dir = tmp_path / "leased-main-data"
    holder = RuntimeDataLease.acquire(data_dir, metadata={"test": "holder"})
    try:
        result = _run_python(
            """
import json
import pathlib
import sys

data_dir = pathlib.Path(__import__('os').environ['DXM_DATA_DIR'])
error = None
try:
    import src.main
except BaseException as exc:
    error = {'type': type(exc).__name__, 'message': str(exc)}
print(json.dumps({
    'error': error,
    'sqliteExists': (data_dir / 'sqlite').exists(),
    'screenshotsExist': (data_dir / 'screenshots').exists(),
    'evidencesExist': (data_dir / 'evidences').exists(),
    'modules': {name: name in sys.modules for name in (
        'src.db', 'src.repository', 'src.execution.browser_agent_worker',
        'src.execution.dxm_login_flow', 'src.services.agent_console',
    )},
}))
""",
            env=_isolated_env(data_dir, DXM_RUNTIME_OWNER="direct"),
        )
    finally:
        holder.release()

    assert result.returncode == 0, result.stderr
    payload = _last_json_line(result.stdout)
    assert payload["error"]["type"] == "RuntimeLeaseConflictError"
    assert payload["sqliteExists"] is False
    assert payload["screenshotsExist"] is False
    assert payload["evidencesExist"] is False
    assert all(loaded is False for loaded in payload["modules"].values())


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop Job bootstrap sentinel")
def test_windows_job_failure_main_import_does_not_touch_db_artifacts_or_services(tmp_path):
    data_dir = tmp_path / "job-failure-main-data"
    result = _run_python(
        """
import json
import os
import pathlib
import queue
import sys

from src.services import runtime_bootstrap
from src.services.desktop_parent_channel import arm_desktop_parent_channel

class Stream:
    def __init__(self):
        self.lines = queue.Queue()
        self.lines.put(b'START job-failure-instance\\n')
    def readline(self, _limit=-1):
        return self.lines.get(timeout=5)

stream = Stream()
channel = arm_desktop_parent_channel(
    stream,
    expected_instance_id='job-failure-instance',
    hard_exit=lambda _code: None,
)
def fail_job():
    raise RuntimeError('injected Windows Job failure')
runtime_bootstrap.ensure_backend_job_owner = fail_job
data_dir = pathlib.Path(os.environ['DXM_DATA_DIR'])
error = None
try:
    import src.main
except BaseException as exc:
    error = {'type': type(exc).__name__, 'message': str(exc)}
finally:
    stream.lines.put(b'SHUTDOWN\\n')
    channel.wait_for_reader(2)
print(json.dumps({
    'error': error,
    'sqliteExists': (data_dir / 'sqlite').exists(),
    'screenshotsExists': (data_dir / 'screenshots').exists(),
    'evidencesExists': (data_dir / 'evidences').exists(),
    'modules': {name: name in sys.modules for name in (
        'src.db', 'src.repository', 'src.execution.browser_agent_worker',
        'src.execution.dxm_login_flow', 'src.services.agent_console',
    )},
}))
""",
        env=_isolated_env(
            data_dir,
            DXM_RUNTIME_OWNER="electron_desktop",
            DXM_DESKTOP="1",
            DXM_DESKTOP_PARENT_CHANNEL="stdin-v1",
            DXM_BACKEND_INSTANCE_ID="job-failure-instance",
        ),
    )

    assert result.returncode == 0, result.stderr
    payload = _last_json_line(result.stdout)
    assert payload["error"] == {
        "type": "RuntimeError",
        "message": "injected Windows Job failure",
    }
    assert payload["sqliteExists"] is False
    assert payload["screenshotsExists"] is False
    assert payload["evidencesExists"] is False
    assert all(loaded is False for loaded in payload["modules"].values())
