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
        "src.db": True,
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
    # src.db is imported at line 44 of main.py, before bootstrap is called;
    # all other modules must not be loaded.
    loaded_modules = payload["modules"]
    assert loaded_modules["src.db"] is True
    assert all(v is False for k, v in loaded_modules.items() if k != "src.db")


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
    # src.db is imported at line 44 of main.py, before bootstrap is called;
    # all other modules must not be loaded.
    loaded_modules = payload["modules"]
    assert loaded_modules["src.db"] is True
    assert all(v is False for k, v in loaded_modules.items() if k != "src.db")


@pytest.mark.parametrize(
    "changed_fact",
    [
        "data_dir",
        "owner",
        "desktop",
        "channel",
        "instance",
        "repo_root",
        "package_version",
        "platform",
        "resource_root",
        "workflow_profile",
        "build_manifest",
        "package_sha",
        "dependency",
    ],
)
def test_ready_singleton_rejects_every_different_request_contract_fact(tmp_path, changed_fact):
    first_data = tmp_path / "signature-a"
    second_data = tmp_path / "signature-b"
    result = _run_python(
        """
import json
import os
from pathlib import Path
from types import MappingProxyType

from src.services.runtime_bootstrap import RuntimeBootstrapError, ensure_runtime_bootstrap

case = os.environ['DXM_SIGNATURE_CASE']
first_data = Path(os.environ['DXM_FIRST_DATA']).resolve()
second_data = Path(os.environ['DXM_SECOND_DATA']).resolve()
repo_a = first_data.parent / 'repo-a'
repo_b = first_data.parent / 'repo-b'
calls = {'identity': 0, 'root': 0, 'lease': 0, 'dirs': 0}

class Identity:
    def __init__(self, env):
        self.instance_id = env.get('DXM_BACKEND_INSTANCE_ID') or 'signature-instance'
        self.payload = MappingProxyType({
            'instanceId': self.instance_id,
            'dataDir': env['DXM_DATA_DIR'],
        })
    def as_dict(self):
        return dict(self.payload)

def identity_a(**kwargs):
    calls['identity'] += 1
    return Identity(kwargs['env'])

def identity_b(**kwargs):
    calls['identity'] += 1
    return Identity(kwargs['env'])

def create_root(_path):
    calls['root'] += 1

lease = object()
def acquire_lease(_path, **_kwargs):
    calls['lease'] += 1
    return lease

def create_dirs():
    calls['dirs'] += 1

base_env = {'DXM_DATA_DIR': str(first_data), 'DXM_RUNTIME_OWNER': 'direct'}
first = dict(
    data_dir=first_data,
    repo_root=repo_a,
    package_version='1.0.0',
    environ=base_env,
    platform_name=os.name,
    identity_factory=identity_a,
    data_root_creator=create_root,
    lease_factory=acquire_lease,
    remaining_directories_creator=create_dirs,
)
winner = ensure_runtime_bootstrap(**first)
second = dict(first)
second['environ'] = dict(base_env)
if case == 'data_dir':
    second['data_dir'] = second_data
    second['environ']['DXM_DATA_DIR'] = str(second_data)
elif case == 'owner':
    second['environ']['DXM_RUNTIME_OWNER'] = 'start_mvp'
elif case == 'desktop':
    second['environ']['DXM_DESKTOP'] = '0'
elif case == 'channel':
    second['environ']['DXM_DESKTOP_PARENT_CHANNEL'] = ''
elif case == 'instance':
    second['environ']['DXM_BACKEND_INSTANCE_ID'] = 'different-instance'
elif case == 'repo_root':
    second['repo_root'] = repo_b
elif case == 'package_version':
    second['package_version'] = '2.0.0'
elif case == 'platform':
    second['platform_name'] = 'posix' if os.name == 'nt' else 'nt'
elif case == 'resource_root':
    second['environ']['DXM_RESOURCE_ROOT'] = str(repo_b)
elif case == 'workflow_profile':
    second['environ']['DXM_WORKFLOW_PROFILE_DIR'] = str(second_data / 'profile')
elif case == 'build_manifest':
    second['environ']['DXM_BUILD_MANIFEST_JSON'] = 'different-manifest'
elif case == 'package_sha':
    second['environ']['DXM_PACKAGE_SHA256'] = 'A' * 64
elif case == 'dependency':
    second['identity_factory'] = identity_b
else:
    raise AssertionError(case)

error = None
try:
    ensure_runtime_bootstrap(**second)
except BaseException as exc:
    error = {'type': type(exc).__name__, 'message': str(exc)}
print(json.dumps({
    'error': error,
    'calls': calls,
    'winnerOwner': winner.owner,
}))
""",
        env={
            **_isolated_env(first_data),
            "DXM_SIGNATURE_CASE": changed_fact,
            "DXM_FIRST_DATA": str(first_data),
            "DXM_SECOND_DATA": str(second_data),
        },
    )

    assert result.returncode == 0, result.stderr
    payload = _last_json_line(result.stdout)
    assert payload["error"]["type"] == "RuntimeBootstrapError"
    assert "mismatch" in payload["error"]["message"]
    assert payload["calls"] == {"identity": 1, "root": 1, "lease": 1, "dirs": 1}
    assert payload["winnerOwner"] == "direct"


def test_ten_rounds_of_heterogeneous_concurrent_ensure_have_one_winner_and_one_mismatch(tmp_path):
    data_dir = tmp_path / "heterogeneous-concurrency"
    result = _run_python(
        """
import json
import os
import threading
from pathlib import Path
from types import MappingProxyType

import src.services.runtime_bootstrap as runtime_bootstrap

root = Path(os.environ['DXM_DATA_DIR']).resolve()
rounds = []

class Identity:
    def __init__(self, env):
        self.instance_id = 'concurrent-instance'
        self.payload = MappingProxyType({'instanceId': self.instance_id, 'dataDir': env['DXM_DATA_DIR']})
    def as_dict(self):
        return dict(self.payload)

def identity_factory(**kwargs):
    return Identity(kwargs['env'])

def create_root(_path):
    return None

def acquire_lease(_path, **_kwargs):
    return object()

def create_dirs():
    return None

for index in range(10):
    runtime_bootstrap._reset_runtime_bootstrap_for_tests()
    barrier = threading.Barrier(3)
    outcomes = []
    lock = threading.Lock()
    def invoke(label):
        data_dir = root / label / str(index)
        kwargs = dict(
            data_dir=data_dir,
            repo_root=root / 'repo',
            environ={'DXM_DATA_DIR': str(data_dir), 'DXM_RUNTIME_OWNER': 'direct'},
            platform_name=os.name,
            identity_factory=identity_factory,
            data_root_creator=create_root,
            lease_factory=acquire_lease,
            remaining_directories_creator=create_dirs,
        )
        barrier.wait(timeout=2)
        try:
            state = runtime_bootstrap.ensure_runtime_bootstrap(**kwargs)
            outcome = {'kind': 'winner', 'dataDir': str(state.data_dir)}
        except BaseException as exc:
            outcome = {'kind': 'error', 'type': type(exc).__name__, 'message': str(exc)}
        with lock:
            outcomes.append(outcome)
    workers = [
        threading.Thread(target=invoke, args=('a',)),
        threading.Thread(target=invoke, args=('b',)),
    ]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=2)
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    rounds.append(outcomes)

print(json.dumps(rounds))
""",
        env=_isolated_env(data_dir),
    )

    assert result.returncode == 0, result.stderr
    rounds = _last_json_line(result.stdout)
    assert len(rounds) == 10
    for outcomes in rounds:
        assert [item["kind"] for item in outcomes].count("winner") == 1
        errors = [item for item in outcomes if item["kind"] == "error"]
        assert len(errors) == 1
        assert errors[0]["type"] == "RuntimeBootstrapError"
        assert "mismatch" in errors[0]["message"]


@pytest.mark.parametrize("failure_stage", ["lease", "job", "remaining"])
def test_first_ensure_failure_is_one_shot_and_later_call_requires_restart(tmp_path, failure_stage):
    data_dir = tmp_path / f"one-shot-{failure_stage}"
    result = _run_python(
        """
import json
import os
from pathlib import Path
from types import MappingProxyType

from src.services.runtime_bootstrap import RuntimeBootstrapError, ensure_runtime_bootstrap

stage = os.environ['DXM_FAILURE_STAGE']
data_dir = Path(os.environ['DXM_DATA_DIR']).resolve()
events = []

class MarkerError(RuntimeError):
    pass
marker = MarkerError('first ' + stage + ' failure')

class Identity:
    instance_id = 'failure-instance'
    payload = MappingProxyType({'instanceId': instance_id, 'dataDir': str(data_dir)})
    def as_dict(self):
        return dict(self.payload)

def identity_factory(**_kwargs):
    events.append('identity')
    return Identity()

def create_root(path):
    events.append('root')
    path.mkdir(parents=True, exist_ok=True)

def lease_factory(path, **_kwargs):
    events.append('lease')
    if stage == 'lease':
        raise marker
    if stage == 'remaining':
        from src.services.runtime_lease import RuntimeDataLease
        return RuntimeDataLease.acquire(path, metadata={'stage': stage})
    return object()

def job_factory():
    events.append('job')
    if stage == 'job':
        raise marker
    return object()

def remaining_factory():
    events.append('remaining')
    if stage == 'remaining':
        raise marker

env = {'DXM_DATA_DIR': str(data_dir), 'DXM_RUNTIME_OWNER': 'direct'}
kwargs = dict(
    data_dir=data_dir,
    repo_root=data_dir.parent / 'repo',
    environ=env,
    platform_name=os.name,
    identity_factory=identity_factory,
    data_root_creator=create_root,
    lease_factory=lease_factory,
    remaining_directories_creator=remaining_factory,
)
if stage == 'job':
    env.update({
        'DXM_RUNTIME_OWNER': 'electron_desktop',
        'DXM_DESKTOP': '1',
        'DXM_DESKTOP_PARENT_CHANNEL': 'stdin-v1',
        'DXM_BACKEND_INSTANCE_ID': 'failure-instance',
    })
    kwargs['parent_channel_getter'] = lambda _expected: object()
    kwargs['job_owner_factory'] = job_factory

first = None
try:
    ensure_runtime_bootstrap(**kwargs)
except BaseException as exc:
    first = {'sameMarker': exc is marker, 'type': type(exc).__name__, 'message': str(exc)}

second = None
try:
    ensure_runtime_bootstrap(**kwargs)
except BaseException as exc:
    second = {
        'type': type(exc).__name__,
        'message': str(exc),
        'causeIsMarker': exc.__cause__ is marker,
    }

print(json.dumps({'first': first, 'second': second, 'events': events}))
""",
        env={**_isolated_env(data_dir), "DXM_FAILURE_STAGE": failure_stage},
    )

    assert result.returncode == 0, result.stderr
    payload = _last_json_line(result.stdout)
    assert payload["first"] == {
        "sameMarker": True,
        "type": "MarkerError",
        "message": f"first {failure_stage} failure",
    }
    assert payload["second"]["type"] == "RuntimeBootstrapError"
    assert "restart required" in payload["second"]["message"]
    assert payload["second"]["causeIsMarker"] is True
    expected_events = {
        "lease": ["identity", "root", "lease"],
        "job": ["identity", "root", "lease", "job"],
        "remaining": ["identity", "root", "lease", "remaining"],
    }
    assert payload["events"] == expected_events[failure_stage]


def test_test_reset_clears_ready_signature_and_latched_failure(tmp_path):
    data_dir = tmp_path / "reset-state-machine"
    result = _run_python(
        """
import json
import os
from pathlib import Path
from types import MappingProxyType

import src.services.runtime_bootstrap as runtime_bootstrap

data_dir = Path(os.environ['DXM_DATA_DIR']).resolve()
calls = {'lease': 0}
class Identity:
    instance_id = 'reset-instance'
    def __init__(self, data_text):
        self.payload = MappingProxyType({'instanceId': self.instance_id, 'dataDir': data_text})
    def as_dict(self):
        return dict(self.payload)
def identity_factory(**kwargs):
    return Identity(kwargs['env']['DXM_DATA_DIR'])
def failing_lease(_path, **_kwargs):
    calls['lease'] += 1
    raise RuntimeError('latched failure')
base = dict(
    data_dir=data_dir,
    repo_root=data_dir.parent,
    environ={'DXM_DATA_DIR': str(data_dir), 'DXM_RUNTIME_OWNER': 'direct'},
    identity_factory=identity_factory,
    data_root_creator=lambda _path: None,
    lease_factory=failing_lease,
    remaining_directories_creator=lambda: None,
)
try:
    runtime_bootstrap.ensure_runtime_bootstrap(**base)
except RuntimeError:
    pass
runtime_bootstrap._reset_runtime_bootstrap_for_tests()
base['lease_factory'] = lambda _path, **_kwargs: object()
state = runtime_bootstrap.ensure_runtime_bootstrap(**base)
runtime_bootstrap._reset_runtime_bootstrap_for_tests()
base['data_dir'] = data_dir / 'third'
base['environ'] = {'DXM_DATA_DIR': str(data_dir / 'third'), 'DXM_RUNTIME_OWNER': 'direct'}
state_after_ready_reset = runtime_bootstrap.ensure_runtime_bootstrap(**base)
print(json.dumps({
    'calls': calls,
    'firstOwner': state.owner,
    'secondData': str(state_after_ready_reset.data_dir),
}))
""",
        env=_isolated_env(data_dir),
    )

    assert result.returncode == 0, result.stderr
    assert _last_json_line(result.stdout) == {
        "calls": {"lease": 1},
        "firstOwner": "direct",
        "secondData": str((data_dir / "third").resolve()),
    }


class _FalseyCallable:
    def __init__(self, name, callback, calls):
        self.name = name
        self.callback = callback
        self.calls = calls

    def __bool__(self):
        return False

    def __call__(self, *args, **kwargs):
        self.calls.append(self.name)
        return self.callback(*args, **kwargs)


@pytest.mark.parametrize(
    "dependency_name",
    [
        "parent_channel_getter",
        "identity_factory",
        "data_root_creator",
        "lease_factory",
        "job_owner_factory",
        "remaining_directories_creator",
    ],
)
def test_falsey_injected_callable_is_used_by_identity_not_truthiness(
    tmp_path,
    monkeypatch,
    dependency_name,
):
    from types import MappingProxyType

    import src.services.runtime_bootstrap as runtime_bootstrap

    data_dir = (tmp_path / dependency_name).resolve()
    calls = []
    channel = object()
    lease = object()
    job = object()

    class Identity:
        instance_id = "falsey-instance"
        payload = MappingProxyType({"instanceId": instance_id, "dataDir": str(data_dir)})

        def as_dict(self):
            return dict(self.payload)

    callbacks = {
        "parent_channel_getter": lambda _expected: channel,
        "identity_factory": lambda **_kwargs: Identity(),
        "data_root_creator": lambda _path: None,
        "lease_factory": lambda _path, **_kwargs: lease,
        "job_owner_factory": lambda: job,
        "remaining_directories_creator": lambda: None,
    }
    dependencies = {
        name: (lambda callback=callback: callback)
        for name, callback in callbacks.items()
    }
    dependencies = {name: factory() for name, factory in dependencies.items()}
    dependencies[dependency_name] = _FalseyCallable(
        dependency_name,
        callbacks[dependency_name],
        calls,
    )

    monkeypatch.setattr(
        runtime_bootstrap,
        "require_armed_desktop_parent_channel",
        lambda _expected: calls.append("fallback-parent") or object(),
    )
    monkeypatch.setattr(
        runtime_bootstrap.RuntimeIdentity,
        "from_environment",
        staticmethod(lambda **_kwargs: calls.append("fallback-identity") or Identity()),
    )
    monkeypatch.setattr(
        runtime_bootstrap,
        "_create_data_root",
        lambda _path: calls.append("fallback-root"),
    )
    monkeypatch.setattr(
        runtime_bootstrap.RuntimeDataLease,
        "acquire",
        staticmethod(lambda _path, **_kwargs: calls.append("fallback-lease") or object()),
    )
    monkeypatch.setattr(
        runtime_bootstrap,
        "ensure_backend_job_owner",
        lambda: calls.append("fallback-job") or object(),
    )
    monkeypatch.setattr(
        runtime_bootstrap,
        "ensure_runtime_directories",
        lambda _path: calls.append("fallback-remaining"),
    )

    state = runtime_bootstrap.build_runtime_bootstrap(
        data_dir=data_dir,
        repo_root=REPO_ROOT,
        environ={
            "DXM_DATA_DIR": str(data_dir),
            "DXM_RUNTIME_OWNER": "electron_desktop",
            "DXM_DESKTOP": "1",
            "DXM_DESKTOP_PARENT_CHANNEL": "stdin-v1",
            "DXM_BACKEND_INSTANCE_ID": "falsey-instance",
        },
        platform_name="nt",
        **dependencies,
    )

    assert calls == [dependency_name]
    assert state.parent_channel is channel
    assert state.runtime_identity.instance_id == "falsey-instance"
    assert state.lease is lease
    assert state.windows_job_owner is job


@pytest.mark.skipif(os.name != "nt", reason="Windows canonical path casing proof")
def test_identity_receives_frozen_canonical_data_env_without_mutating_original_mapping(tmp_path):
    from types import MappingProxyType

    from src.services.runtime_bootstrap import build_runtime_bootstrap

    actual_data = tmp_path / "MiXeD-Canonical-Data"
    actual_data.mkdir()
    lower_alias = actual_data.with_name(actual_data.name.lower())
    canonical_text = str(lower_alias.resolve(strict=False))
    assert str(lower_alias) != canonical_text
    original_env = {
        "DXM_DATA_DIR": str(lower_alias),
        "DXM_RUNTIME_OWNER": "direct",
    }
    seen = {}
    lease_paths = []

    class Identity:
        instance_id = "canonical-instance"

        def __init__(self, data_text):
            self.payload = MappingProxyType(
                {"instanceId": self.instance_id, "dataDir": data_text}
            )

        def as_dict(self):
            return dict(self.payload)

    def identity_factory(**kwargs):
        env = kwargs["env"]
        seen["dataDir"] = env["DXM_DATA_DIR"]
        try:
            env["MUTATION_PROBE"] = "forbidden"
        except TypeError:
            seen["immutable"] = True
        else:
            seen["immutable"] = False
            del env["MUTATION_PROBE"]
        return Identity(env["DXM_DATA_DIR"])

    state = build_runtime_bootstrap(
        data_dir=lower_alias,
        repo_root=REPO_ROOT,
        environ=original_env,
        identity_factory=identity_factory,
        data_root_creator=lambda _path: None,
        lease_factory=lambda path, **_kwargs: lease_paths.append(path) or object(),
        remaining_directories_creator=lambda: None,
    )

    assert original_env["DXM_DATA_DIR"] == str(lower_alias)
    assert seen == {"dataDir": canonical_text, "immutable": True}
    assert str(state.data_dir) == canonical_text
    assert state.runtime_identity.as_dict()["dataDir"] == canonical_text
    assert [str(path) for path in lease_paths] == [canonical_text]


@pytest.mark.skipif(os.name != "nt", reason="Windows exact canonical identity proof")
def test_noncanonical_identity_data_text_fails_before_root_even_when_windows_path_equal(tmp_path):
    from types import MappingProxyType

    from src.services.runtime_bootstrap import RuntimeBootstrapError, build_runtime_bootstrap

    actual_data = tmp_path / "MiXeD-Identity-Data"
    actual_data.mkdir()
    lower_alias = actual_data.with_name(actual_data.name.lower())
    canonical_text = str(lower_alias.resolve(strict=False))
    assert str(lower_alias) != canonical_text
    root_calls = []

    class NoncanonicalIdentity:
        instance_id = "noncanonical-instance"
        payload = MappingProxyType(
            {"instanceId": instance_id, "dataDir": str(lower_alias)}
        )

        def as_dict(self):
            return dict(self.payload)

    with pytest.raises(RuntimeBootstrapError, match="canonical data directory"):
        build_runtime_bootstrap(
            data_dir=lower_alias,
            repo_root=REPO_ROOT,
            environ={"DXM_DATA_DIR": str(lower_alias), "DXM_RUNTIME_OWNER": "direct"},
            identity_factory=lambda **_kwargs: NoncanonicalIdentity(),
            data_root_creator=lambda path: root_calls.append(path),
            lease_factory=lambda _path, **_kwargs: object(),
            remaining_directories_creator=lambda: None,
        )

    assert root_calls == []
    assert str(lower_alias.resolve(strict=False)) == canonical_text


def test_explicit_data_env_conflict_fails_before_identity_or_root(tmp_path):
    from src.services.runtime_bootstrap import RuntimeBootstrapError, build_runtime_bootstrap

    requested_data = tmp_path / "configured-data"
    conflicting_data = tmp_path / "different-env-data"
    events = []

    with pytest.raises(RuntimeBootstrapError, match="DXM_DATA_DIR"):
        build_runtime_bootstrap(
            data_dir=requested_data,
            repo_root=REPO_ROOT,
            environ={
                "DXM_DATA_DIR": str(conflicting_data),
                "DXM_RUNTIME_OWNER": "direct",
            },
            identity_factory=lambda **_kwargs: events.append("identity"),
            data_root_creator=lambda _path: events.append("root"),
            lease_factory=lambda _path, **_kwargs: object(),
            remaining_directories_creator=lambda: None,
        )

    assert events == []
    assert requested_data.exists() is False
    assert conflicting_data.exists() is False
