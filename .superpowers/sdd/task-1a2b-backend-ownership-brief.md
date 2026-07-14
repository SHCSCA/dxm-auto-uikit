# Task 1A2-B: backend data lease, exact parent channel, and Windows Job ownership

## Objective

Close the backend half of the runtime-ownership contract after Phase 1A2-A is independently accepted. A backend must acquire the canonical data-directory lease before SQLite, artifact mounts, service construction, or browser-profile creation. An Electron-owned backend must also prove the exact Electron stdin channel and bind itself and descendants to a backend-owned Windows Job Object before application import can create runtime state.

This phase runs no Electron UI, browser, portable package, or DXM action. It does not edit the Phase 1A2-C PowerShell launchers or smoke scripts.

## Current seams that must change

- `src/core/config.py` currently creates six directories at import time.
- `src/main.py` currently creates artifact roots, mounts them, calls `init_db()`, and constructs repositories, thread pools, Browser Agent, and Agent Console services at module import without an ownership bootstrap.
- Electron currently starts `python -m uvicorn src.main:app` without a piped parent-lifetime protocol.
- Exact-child identity and exit/close authority exist, but graceful shutdown, `terminationRequested`, START acknowledgement, and a bounded exact-child fallback do not.

## Required module boundaries

### `src/services/runtime_lease.py`

- `RuntimeDataLease` owns one non-inheritable file descriptor for `<canonicalDataDir>/.dxm-runtime.lock`.
- Creating the canonical data root is the only directory write allowed before the lease.
- Windows:
  1. open/create the permanent lock file;
  2. make the descriptor non-inheritable;
  3. guarantee at least one byte exists;
  4. `seek(0)` and acquire exactly `[0,1)` with `msvcrt.locking(..., LK_NBLCK, 1)`;
  5. write diagnostic JSON only after byte 0, without moving the authority range;
  6. `seek(0)` again before an explicit test-only unlock.
- POSIX uses non-blocking exclusive `fcntl.flock` on a non-inheritable descriptor.
- The live OS lock is the sole authority. The permanent file and diagnostic metadata may be stale and are never deleted as takeover logic.
- A dedicated contention exception reports the canonical directory plus best-effort owner metadata and explicitly labels metadata as non-authoritative.
- The production lease is held in a module global until process teardown. FastAPI lifespan exit must not release it. `release()` exists only for isolated unit/app-factory owners.

### `src/services/desktop_parent_channel.py`

- The environment variable is only a requested protocol; a process-global armed channel object is the proof.
- The first bounded line must be exactly `START <DXM_BACKEND_INSTANCE_ID>\n`. EOF, unknown commands, oversized lines, or an instance mismatch fail before importing `src.main`.
- After START, a daemon reader accepts one terminal fact:
  - `SHUTDOWN\n`: atomically set pending shutdown, apply `server.should_exit = True` if attached, then return immediately even while Electron keeps the writer open;
  - EOF: the exact writer disappeared, so call `os._exit` and let OS teardown release the lease, port, and Job.
- Provide a lock-linearized `run_if_not_shutdown(callback)` plus `attach_server(server)`. If SHUTDOWN won the race, the callback must never run.
- Do not poll a parent PID and do not infer ownership from environment variables alone.

### `src/services/windows_job.py`

- Wrap the required Win32 calls and structures with `ctypes`, allowing an injected API for deterministic unit tests.
- Create an unnamed Job with an explicitly non-inheritable handle, set `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, then assign the current backend process.
- Preserve `GetLastError` and the failing stage in every exception.
- The successful production handle is process-global and must not be closed from a context manager, `finally`, FastAPI lifespan, or `atexit`; closing the last handle while Python is assigned would terminate the backend mid-shutdown.
- Electron desktop mode fails closed if creation, limits, or assignment fail. No claimed fallback process-tree ownership is allowed.
- Non-Windows direct/package-probe owners do not invent Windows ownership.

### `src/services/runtime_bootstrap.py`

- This is the sole backend ownership bootstrap and stores the frozen runtime identity, production lease, parent-channel fact, and Windows Job owner.
- Owner matrix:
  - `electron_desktop`: requires `DXM_DESKTOP=1`, `DXM_DESKTOP_PARENT_CHANNEL=stdin-v1`, an in-process armed channel, and matching instance ID; Windows Job binding is mandatory on Windows.
  - `package_probe`: explicit non-desktop probe owner; no stdin or Job requirement and must not claim `DXM_DESKTOP=1`.
  - `start_mvp` / `direct`: no desktop parent pipe; still hold the data lease.
  - `DXM_DESKTOP=1` without the exact `electron_desktop` contract fails before the data root is created.
- Refactor `src/core/config.py` to expose only path constants at import plus explicit `ensure_runtime_directories()`.
- The bootstrap owns the following exact sequence:
  1. parse and validate owner/channel facts without writes;
  2. freeze `RuntimeIdentity` and canonical paths;
  3. create only the canonical data root;
  4. acquire the module-process data lease;
  5. on Windows Electron desktop, create/configure/assign the Job;
  6. call `ensure_runtime_directories()`;
  7. return frozen bootstrap state.
- Lease or Job failure must occur before importing modules that mount paths, open SQLite, construct services, or create browser profiles.

### `src/desktop_server.py`

- Electron's only backend host becomes `python -m src.desktop_server`.
- Synchronously arm and validate stdin-v1 before constructing a programmatic `uvicorn.Config("src.main:app", ...)` and `uvicorn.Server`.
- Production app target is fixed in code. Tests use injected factories; no production environment variable may redirect the import target.
- Call `server.run()` only inside the channel's `run_if_not_shutdown` gate. Setting `server.should_exit` before `run()` is insufficient because current uvicorn loads/imports the app first.
- Attach the server so a later SHUTDOWN sets `should_exit` and allows FastAPI lifespan cleanup before child close.

### Node shutdown integration

- Add a pure CommonJS shutdown controller rather than growing `main.cjs` further.
- Spawn the backend with `stdio: ['pipe', 'pipe', 'pipe']`, set `DXM_RUNTIME_OWNER=electron_desktop` and `DXM_DESKTOP_PARENT_CHANNEL=stdin-v1`, then write `START <instanceId>\n` once through the exact `child.stdin`.
- Extend the exact ownership record with `channelStarted`, `terminationRequested`, `terminationPromise`, and exit/close facts.
- One termination request writes `SHUTDOWN\n`, waits a bounded interval for exact child `close`, then calls only that exact live `ChildProcess.kill()` once and waits a final bounded interval.
- Repeated startup-failure, app-quit, and later QA-deadline paths share the same termination promise. A kill return value does not clear authority; only exact exit/close does.
- `before-quit` prevents the first quit long enough to run the chain, then permits one final quit. Unexpected exact child exit invalidates the Phase A startup controller. Stale/unrelated child events remain inert.
- Phase B may add the reusable QA-deadline shutdown hook, but Phase C owns packaged-wrapper/PowerShell invocation and proof.

## Single startup order

1. Electron completes Phase A QA classification, selected `userData`, and single-instance lock.
2. Electron freezes identity/env and spawns the exact Python child with piped stdin/stdout/stderr.
3. Electron writes `START <instanceId>\n`.
4. `desktop_server` validates START, arms the watchdog, and records the in-process channel.
5. Only then may uvicorn import `src.main`.
6. `src.main` invokes the sole runtime bootstrap before artifact mounts, `init_db()`, repositories, thread pools, Browser Agent, Agent Console, or other service construction.
7. Bootstrap freezes identity, creates only the data root, acquires the data lease, binds the Windows Job when required, and creates remaining runtime directories.
8. `src.main` may then mount artifacts, initialize SQLite/services, and expose health.

Health cannot become available before all ownership steps succeed.

## TDD sequence and mandatory evidence

### 1. Config and fixed-byte lease

- importing config constants creates no directories;
- same canonical directory conflicts across real subprocesses;
- different directories coexist;
- different-length metadata still conflicts on Windows byte `[0,1)`;
- a stale file with no live lock does not block and is never deleted;
- descriptor/handle inheritance is disabled;
- process exit permits a later owner;
- repeated TestClient/FastAPI lifespan exit does not release the production module lease.

### 2. Bootstrap order and owner gates

- injected sentinels prove validate -> identity -> data root -> lease -> Job -> remaining dirs;
- lease contention proves `src.db`, artifact mounts, Browser services, and SQLite are untouched;
- forged `DXM_DESKTOP=1`, missing/unarmed pipe, or instance mismatch fails before any write;
- `package_probe` and direct/start-mvp matrices do not impersonate Electron.

### 3. Parent channel and desktop host

- bounded START validation and mismatch/EOF rejection;
- shutdown-before-run does not import the app, create SQLite, or bind a port;
- SHUTDOWN reader returns so a child can close while the parent writer remains open;
- SHUTDOWN after server attach sets `should_exit` and a cleanup marker precedes child close;
- EOF exits immediately and releases a held test lease/port.

### 4. Windows Job

- fake Win32 API tests verify structure sizes/flags, call order, non-inheritance, accurate stage/error reporting, failure cleanup, and no explicit close on success;
- a required Windows integration starts a separate `job_owner` Python process, which creates/assigns its own Job and starts a harmless waiting descendant;
- pytest never assigns itself to the Job;
- after exact owner exit, use `OpenProcess(SYNCHRONIZE)` and `WaitForSingleObject` to prove descendant exit;
- nested-Job assignment failure is a hard failing result with `GetLastError`, never a skip or silent downgrade.

### 5. Exact Electron shutdown

- START is written once;
- graceful close does not kill;
- timeout kills only the exact current live child once;
- repeated/stale/unrelated/exited ownership is untouched;
- termination authority remains until exact exit/close;
- startup failure, repeated quit, and QA deadline share one promise;
- a Windows forced-parent-EOF subprocess proof releases backend, harmless descendant, lease, and port.

## Verification gate

Run, at minimum:

- the complete desktop Node suite;
- all new lease/bootstrap/channel/desktop-server/Job tests;
- `tests/test_desktop_package_contract.py`;
- `tests/test_runtime_lifespan.py` and runtime identity/health tests;
- the full backend suite after focused tests are green;
- frontend production build;
- Python/Node syntax checks and `git diff --check`.

No Electron launch, browser launch, portable build, or DXM request is allowed in this phase.

## Explicit deferrals

- Do not edit `scripts/start-mvp.ps1`, `scripts/verify-desktop-package.ps1`, or other Phase C launcher/smoke cleanup.
- Do not implement Task 1B task runtime bindings, Task 2 state transitions, Task 3 Browser Agent command ownership, Task 4 template snapshots, or Task 6 packaged canary.
- Do not claim portable or production READY from pure unit/subprocess proof.

## Deliverable

Produce `.superpowers/sdd/task-1a2b-backend-ownership-report.md` with RED/GREEN evidence, exact bootstrap order, owner matrix, lease/Job semantics, parent-channel races, changed files, and explicit deferrals. Commit Phase B independently only after Phase A re-review is clean.
