# Task 1A2: single runtime ownership, data lease, and fixed-port fail-closed startup

## Goal

Close the ownership gaps deliberately deferred by Task 1A. One normal DXM Agent Console data/profile directory may have exactly one desktop owner and one backend runtime. A second launch, a legacy backend, a port conflict, or an invalid QA bypass must stop before SQLite, browser-profile, or DXM workflow work begins. This subtask runs no browser and no real DXM action.

## Non-negotiable ownership rules

1. Normal development and packaged launches use backend port `8000`. They must never silently shift to another port.
2. The Electron application acquires its single-instance lock before creating any backend data/profile directory, starting a backend, or creating a window. Electron requires an isolated QA `userData` root to exist before `app.setPath`; creating that one already-validated root is the only allowed pre-lock filesystem side effect. A second instance only focuses/restores the existing window and exits without spawning anything.
3. An isolated QA launch is recognized only when all of these are true:
   - `--qa-user-data-dir` is present, non-empty, absolute, and filesystem-disjoint from the normal Electron `userData` directory: it is not equal to, an ancestor of, a descendant of, or a junction/realpath alias of that directory;
   - at least one known non-mutating smoke argument is present with a non-empty absolute output path: `--qa-capture`, `--qa-visible-smoke`, or `--qa-credential-smoke`;
   - no unknown `--qa-*` flag may turn an ordinary launch into an isolated QA launch; unrelated Chromium/Electron flags remain allowed;
   - every QA output path is outside the normal `userData` tree after canonical/realpath resolution.
   `--qa-deadline-ms` is an optional bounded positive timeout for an already-valid isolated QA launch; it never counts as the required smoke argument and can never grant QA identity by itself. Invalid or partial QA arguments fail closed before `setPath`, `mkdir`, backend spawn, or window creation. Validation itself is side-effect-free; after it succeeds Electron creates only the isolated QA `userData` root, calls `setPath`, and then acquires the lock. A valid isolated QA launch uses `<qaUserData>/data` in both development and packaged modes and may choose a free loopback port in `8000..8079`, because its data and backend lease are independent.
4. Before a normal backend spawn, inspect loopback ports `8000..8079` with one total deadline, bounded response bodies, and cancellation/cleanup of late probes. Detect a same-data legacy backend from either canonical `/health.runtimeIdentity.dataDir` or the legacy `/api/runtime/status.paths.data_dir`. TCP occupancy and identity are separate facts: if port `8000` accepts a connection, timeout or malformed HTTP/JSON still means occupied, never free. If a same-data runtime is found, report its port/PID/instance when available and stop; never adopt or kill it. If port `8000` is occupied by anything else, stop with an actionable conflict. Do not scan process command lines to infer authority.
5. The backend holds a non-blocking OS file lease for its canonical `dataDir` for the entire process lifetime. The lease is acquired before SQLite initialization, public artifact directory creation, service construction that creates directories, or browser-profile creation. Contention is fatal; no stale-file deletion or PID-based takeover is allowed.
6. Electron may terminate only exact process objects it launched. No `taskkill`, `process.kill(pid)`, `Get-Process ... Path`, command-line matching, or other PID/path rediscovery is allowed. Ownership is not cleared by a `kill()` return value; Task 1A's exit/close lifecycle remains authoritative.
7. The Electron backend runtime starts once per app process. Recreating a macOS/activated window must reuse the already verified runtime and must never spawn a second backend. Backend lifetime is also bound to the exact Electron parent through the already-owned child stdio pipe; a desktop crash must not leave Python, its lease, or port 8000 alive.

## Backend runtime lease

Add a small standard-library lease service, with dependency injection where useful for tests:

- Lease file: a permanent, non-sensitive file inside the canonical data directory (for example `.dxm-runtime.lock`). The file may contain diagnostic JSON such as schema, instance ID, PID, data directory, and acquisition time, but file contents never prove ownership; only the live OS lock does.
- Windows: guarantee the file has at least one byte, `seek(0)`, and hold exactly byte range `[0,1)` with `msvcrt.locking(..., LK_NBLCK, 1)` on a non-inheritable descriptor. Metadata length must never change the lock offset. Seek to zero again before unlock.
- POSIX: hold `fcntl.flock(..., LOCK_EX | LOCK_NB)` on a non-inheritable descriptor.
- Keep the production lease as a module-level bootstrap owner until the Python process actually terminates. FastAPI lifespan may be entered/exited repeatedly by tests while the same global app/services remain usable, so lifespan cleanup must **not** release the production lease. Orderly shutdown first runs browser/runtime lifespan cleanup, then process exit/`atexit` or OS teardown releases the lease. A startup exception relies on process teardown; a direct `release()` API exists only for isolated lease unit tests/app-factory-style owners.
- Never delete the lease file to resolve contention. A crashed process releases the OS lock automatically.
- Raise a dedicated, actionable conflict error containing the canonical data directory and any diagnostic owner metadata, while clearly stating that the metadata may be stale.

Refactor `src/core/config.py` so importing path constants has no directory-creation side effects. Add an explicit `ensure_runtime_directories()` and call it only after the data lease is acquired. `src/main.py` must have one concrete module bootstrap boundary, exercised by a real subprocess test: import side-effect-free constants/classes; freeze identity; create only the canonical data root required to open the lease file; acquire the lease; establish the required desktop parent-lifetime channel and Windows process-group ownership; create subdirectories; then mount artifact directories, call `init_db()`, and construct repositories/services/browser runtime. Do not defer lease acquisition to FastAPI lifespan because today's SQLite, mounts, and services initialize at module import.

On Windows, also bind the backend and descendants to a backend-owned kill-on-close Job Object using `ctypes` and `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, before any Browser Agent child can be created. Keep its non-inheritable unnamed handle alive until process teardown. **Do not explicitly close the last Job handle from FastAPI lifespan while the current backend is assigned to it**, because that would terminate Python mid-shutdown. If safe Job Object binding cannot be established in desktop mode, fail closed rather than claiming process-tree ownership. Direct non-desktop POSIX startup may use its native process/session semantics, but must not invent Windows ownership. Unit-test the Win32 wrapper through injected API calls and add a guarded Windows subprocess proof. External Chrome PID reporting and Browser Agent command ownership remain Task 3.

### Exact Electron-parent lifetime channel

A backend-owned Job Object alone is insufficient: if Electron crashes, Python would otherwise remain alive while holding the Job and data lease. Use the exact pipe Electron already owns for the spawned child rather than parent-PID polling:

- Electron must spawn the backend with piped stdin and keep that exact `child.stdin` open for the full runtime. Inject an explicit desktop parent-channel contract in the backend environment and fail before health if no pipe is available.
- Add a dedicated `python -m src.desktop_server` host for Electron rather than trying to stop the opaque `python -m uvicorn` CLI from a background thread. The host validates/arms a daemon watchdog on `sys.stdin.buffer`, constructs a programmatic `uvicorn.Server`, and only then lets uvicorn import `src.main:app`; health can become available only after the watchdog is armed. Direct launcher and package-probe modes remain explicit separate hosts. The host owns a pending-shutdown event before constructing the server: a `shutdown` received early prevents app import/SQLite/port startup, or is applied immediately to `server.should_exit` once constructed. After one shutdown command the reader returns; it must never keep Python alive while Electron keeps the writer open awaiting child close.
- Pipe EOF means the exact Electron parent/writer disappeared. The backend exits immediately; OS teardown releases the data lease and closes the backend-owned Job handle, which kills assigned descendants. Do not replace this with PID polling.
- For orderly quit, Electron writes one bounded `shutdown` command through the same exact pipe and waits for the owned child `close`. The programmatic host sets `uvicorn.Server.should_exit`, allowing FastAPI browser/runtime cleanup to run; the lease remains held until the server process actually exits. Do not approximate this with a background-thread `os.kill(SIGINT)` on Windows. If the child does not close by the deadline, Electron calls only that exact `ChildProcess.kill()` as fallback and waits a final bounded interval.
- A forced Electron crash/package-smoke timeout subprocess test must prove the backend, a harmless spawned descendant, lease, and port are all released. A graceful-quit test must prove lifespan cleanup happens before child close.
- An inner Electron QA deadline uses the same graceful/fallback chain and then exits non-zero. This is mandatory for portable smoke because the PowerShell `$PortableProcess` is the NSIS outer wrapper and killing that exact wrapper does not prove its `ExecWait` inner Electron or backend stopped.

## Electron startup structure

Extract pure CommonJS helpers rather than growing `main.cjs` further:

- Parse and classify launch arguments before mutating paths.
- Canonically compare paths using existing-target realpaths and nearest-existing-ancestor resolution for not-yet-created paths; Windows comparisons are case-insensitive and containment-aware.
- Probe legacy runtime facts with injected TCP/HTTP functions, a total deadline, per-response body cap, and cancellation of pending/late responses.
- Resolve the port policy: fixed `8000` for normal launches; bounded free-port selection only for validated isolated QA.
- Cache one `startRuntimeOnce()` promise. Separate backend/runtime startup from `createMainWindow()`.
- Add `terminationRequested` to the exact ownership record. Graceful/fallback termination may be requested once only, but authority remains present until exact child `exit`/`close`; repeated startup-catch/quit paths are no-ops.

Required lifecycle:

1. Freeze the normal `userData` path.
2. Validate the complete QA policy without filesystem writes. Only after success, create the isolated QA root and set that `userData` path; create no `data` or profile subdirectory yet.
3. Call `app.requestSingleInstanceLock()` for the selected user-data scope. If false, quit immediately without creating backend data/profile paths.
4. Register `second-instance` to restore/show/focus the existing window only.
5. After `whenReady`, start the runtime once, then create the window.
6. `activate` with no windows calls only `createMainWindow()` against the cached verified runtime.

Do not use the single-instance lock as the backend data lease: Electron and direct backend launches are separate authorities, so both layers are required.

## Launcher and package-smoke cleanup

- In `scripts/start-mvp.ps1`, delete the command-line/path-based detection and automatic killing of an older backend on port 8000. Perform the read-only port-busy hard stop before deleting `runtime-control-command.json`, installing dependencies, or creating service processes. Retain cleanup only for exact `System.Diagnostics.Process` objects and Job Object handles created by that launcher. On restart/stop: close the owned Job first, wait boundedly for the exact wrapper process and port release, then start; remove recursive PID discovery.
- In `scripts/verify-desktop-package.ps1`, remove the global `Get-Process | Where-Object Path ... | taskkill` sweep. Every win-unpacked smoke process must be cleaned through its exact `Process` object and followed by `WaitForExit` before data-directory deletion/reuse. Its timeout tests must prove killing exact inner Electron triggers parent-channel/Job cleanup. Portable smoke must pass a bounded internal `--qa-deadline-ms` and wait for the NSIS outer `ExecWait` result; killing only `$PortableProcess` is not accepted as inner ownership proof. The independent bundled-backend resource check is an explicit `package_probe` owner/mode with isolated data and a random port; it must not impersonate an Electron-owned backend or require the Electron parent channel.
- Update any old contract tests that positively require `taskkill`, command-line takeover, or dynamic normal ports. The new tests must require their absence.

## TDD sequence

Write and capture RED tests before production changes.

### A. QA and single-instance policy

- valid absolute isolated QA data/output paths are accepted;
- relative, empty, equal/ancestor/descendant/junction-alias, QA output inside normal userData, smoke-without-user-data, user-data-without-known-smoke, and unknown `--qa-*` combinations reject before side effects;
- unrelated Chromium flags remain allowed; validated QA creates only its root before lock and uses `<qaUserData>/data` in both direct and packaged modes;
- `--qa-deadline-ms` rejects missing/invalid/out-of-range values and never authorizes QA without a known smoke output plus isolated userData;
- ordinary launch cannot use a shifting port;
- validated QA may use a free port in the bounded range;
- second-instance and `activate` tests/contracts prove backend spawn count remains one and only the existing/new window is focused/created.

### B. Legacy runtime and port conflicts

- same canonical data directory on port 8000 or a shifted legacy port is rejected even when health is otherwise OK;
- legacy `paths.data_dir` is recognized;
- unrelated occupant on 8000 is rejected without kill/adoption;
- a different-data runtime on 8001 does not block a normal launch when 8000 is free;
- all 80 probes share a short total deadline and body cap; timeout/malformed JSON on occupied 8000 stays occupied, pending probes are cancelled, and late responses cannot change the decision.
- the `8000..8079` scan is compatibility diagnostics for the historical Electron shifter, not the authority for current runtimes; the OS data lease remains authoritative even when shifted probes time out. Different-data shifted runtimes do not block normal 8000 startup.

### C. Backend lease and initialization order

- config import alone creates no runtime directories;
- first lease succeeds, its descriptor is non-inheritable, and a second process on the same canonical directory fails;
- Windows contenders with different-length diagnostic metadata still conflict on the same fixed `[0,1)` byte;
- a different data directory succeeds concurrently;
- release/process exit allows a later owner;
- repeated TestClient/FastAPI lifespan exit while the module process remains alive does not release the production bootstrap lease; a contender remains blocked until process exit;
- contention fails before `init_db`/profile/service initialization (assert call order with injected sentinels or a subprocess fixture);
- lease file presence without a live OS lock does not block startup and is never deleted as takeover logic.

### D. Exact process cleanup

- Electron/launcher ownership code uses no `taskkill`, PID-form `process.kill(pid)`, path-wide process sweeps, or command-line ownership matching. Exact `ChildProcess.kill()`/`Popen.kill()` on an already-owned object remains allowed; do not apply this ban indiscriminately to unrelated workflow code.
- exact owned child/process termination is behavior-tested as requested once only through `terminationRequested`; stale, repeated, exited, or unrelated objects are untouched, and authority clears only on exact exit/close;
- Windows Job Object configuration sets kill-on-close and holds its handle without explicitly closing it while Python is live; failure in desktop mode is fail-closed;
- on Windows, a required guarded subprocess test (not only a fake API unit) creates a child-owned unnamed non-inheritable Job plus harmless descendant, triggers owner exit, and proves descendant exit without ever assigning the pytest process itself. Nested-Job failure reports `GetLastError` and desktop startup fails closed;
- exact parent-pipe EOF and forced Electron termination release backend, harmless descendant, lease, and port; graceful pipe command runs lifespan cleanup, with exact-child kill only as bounded fallback;
- desktop host subprocess tests prove shutdown-before-server prevents app import/SQLite/port creation, and a shutdown reader returns so the child closes while Electron's writer remains open;
- portable-wrapper timeout tests prove the inner QA deadline exits through the owned shutdown chain and the outer wrapper returns; no test treats killing the outer NSIS PID alone as cleanup proof;
- package-smoke and MVP-launcher contracts use only their own process objects/job handles.

Run at minimum:

- new desktop pure Node tests plus the complete desktop Node suite;
- new backend lease/process-group tests;
- `tests/test_desktop_package_contract.py`;
- `tests/test_start_mvp_launcher.py`;
- `tests/test_runtime_lifespan.py` and runtime identity/health tests;
- the full backend suite if focused tests are green;
- frontend production build (startup contract regression check);
- `git diff --check`.

The fixed-port rule applies to the ordinary Electron backend only. Valid isolated QA/final-delivery checks, the explicit package probe, and frontend port 5173 retain their separately bounded port policies. Reuse Task 1A path normalization where possible. Static desktop contracts follow `app/desktop/package.json` main=`src/main.cjs`; do not accidentally treat legacy `src/main.js` as the package entry (delete it only if independently proven dead and tests require that cleanup).

Implement and review this subtask serially in three independent commits to keep risk bounded:

1. **1A2-A — Electron launch policy:** strict QA/disjoint paths, selected-data-dir policy, single-instance ordering, fixed normal port plus bounded legacy diagnostics, and runtime-once/window separation. No browser/DXM.
2. **1A2-B — backend ownership:** side-effect-free config/bootstrap, fixed-byte data lease, `src.desktop_server` exact parent channel, Windows backend Job Object, graceful/forced shutdown, and Electron integration. No browser/DXM.
3. **1A2-C — launcher/smoke cleanup:** early start-mvp conflict stop, exact owned Job/process cleanup, explicit package-probe mode, timeout waits, merged full regression.

Each phase must have its own RED/GREEN report, spec review, and quality review before the next phase. A normal instance and isolated-QA coexistence must be proven in the final packaged Task 6 canary; pure fakes in this task establish ordering/contracts but do not substitute for that package proof.

Do not build the portable EXE in this subtask. Do not launch a browser or call DXM. Do not change Task 1B task-snapshot behavior.

## Deliverable

Write phase reports `.superpowers/sdd/task-1a2a-electron-launch-policy-report.md`, `.superpowers/sdd/task-1a2b-backend-ownership-report.md`, and `.superpowers/sdd/task-1a2c-launcher-cleanup-report.md`, plus a short final `.superpowers/sdd/task-1a2-runtime-ownership-report.md` reconciliation. Include RED/GREEN evidence, exact initialization order, QA exception policy, port behavior, lease/Job semantics, files changed, and explicit Task 1B/Task 3/Task 6 boundaries. Force-add only this brief and intended reports if ignored; commit each phase independently.
