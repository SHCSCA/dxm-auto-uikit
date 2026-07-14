# Task 1A2-A report: Electron launch policy

## Scope and result

Phase A implements only the Electron-side launch policy. It does not implement the Python data lease, `src.desktop_server`, parent pipe, Windows Job Object, graceful/fallback shutdown, launcher cleanup, or package-smoke cleanup assigned to phases B/C. No browser, Electron application, portable package, or DXM workflow was launched.

Implemented boundaries:

- ordinary launches keep backend port `8000`; only a validated isolated QA launch may select a free port in `8000..8079`;
- the normal Electron `userData` path is frozen before QA parsing; parsing/canonical comparison performs no filesystem writes;
- valid QA requires an absolute disjoint `--qa-user-data-dir` and at least one absolute known smoke output; unknown/duplicate `--qa-*`, partial combinations, normal-tree aliases, and junction/realpath aliases fail closed;
- optional `--qa-deadline-ms` is accepted only for an already-valid QA launch and is bounded to `1000..600000` ms; it does not grant QA identity by itself;
- after validation, only the QA userData root may be created before `app.setPath` and `app.requestSingleInstanceLock()`;
- invalid policy or a false single-instance lock registers no ready/activate lifecycle and creates no backend/window;
- a second instance only restores, shows, and focuses the existing window;
- ordinary startup performs bounded compatibility diagnostics on `8000..8079` before spawn, with independent TCP occupancy and HTTP identity evidence, a shared `2000` ms deadline, `64 KiB` body cap, abort cleanup, and late-result suppression;
- QA port selection probes its bounded range concurrently under one `1500` ms deadline, rather than waiting up to 80 seconds serially;
- backend startup is cached in one promise; `activate` can create a window only after the runtime has already been verified and cannot start a second backend.

## TDD evidence

RED was captured before the production implementation:

- `node --test test/launch-policy.test.cjs test/runtime-start.test.cjs` first failed because the pure modules did not exist, then failed `20/20` against explicit not-implemented stubs;
- focused Python desktop contracts failed `3/3` because QA classification, single-instance ordering, fixed-port diagnostics, and runtime/window separation were absent;
- the explicit invalid-policy/lock gate test failed because `registerPrimaryInstanceLifecycle` did not exist and its Python contract lacked `launchPolicyValid` gating;
- the QA port concurrency regression failed with `3 !== 80`, proving the old sequential free-port selection did not satisfy the shared-deadline requirement;
- the actionable fixed-port/same-data startup-message contract failed before the new user-facing conflict branches were added.

GREEN evidence collected during implementation:

- focused launch-policy tests: `20 passed`;
- focused runtime-start tests: `4 passed`;
- complete desktop Node suite: `37 passed` before the final QA shared-deadline additions;
- desktop package contracts: `33 passed` after updating obsolete `findFreePort/createWindow` assertions to the new package entry and lifecycle;
- QA runtime data-isolation contracts: `14 passed`;
- Node syntax checks for `main.cjs`, `launch-policy.cjs`, and `runtime-start.cjs`: passed.

## Independent-review follow-up

The first independent spec review passed, while the first quality review returned four important and two minor findings. A separate TDD follow-up closes all six without entering phases B/C:

- startup-user classification now consumes stable `error.code` values and never the diagnostic stack; same-data and fixed-port fixtures deliberately include a packaged `resources/app.asar` stack and retain the correct conflict message;
- the startup controller now exposes explicit `idle / starting / ready / failed / stopped` states, caches a runtime only after the first window and all requested smoke work succeed, treats pre-ready `activate` as a no-op, and invalidates only for the exact current ownership on `exit`, `close`, or a successful exact-child kill request;
- window creation is transactional: a load/credential/capture/visible-smoke failure destroys the exact failed `BrowserWindow` and clears only a matching global reference; repeated startup failures focus the one existing error window instead of creating duplicates;
- desktop-log availability is an observed fact set only after `appendFileSync` succeeds. Preflight conflicts before data-directory creation display the stable error code and state that no startup log was generated, without claiming a nonexistent path or giving a generic old-browser-process instruction;
- `--qa-capture` and `--qa-visible-smoke` are mutually exclusive, while credential smoke may accompany either one;
- production startup now calls the injected `prepareElectronLaunchOwnership` helper. Its behavior test proves classify → QA root creation → `setPath` → lock, and proves invalid policy or a false lock registers no lifecycle.

A second independent quality pass found three important lifecycle gaps and one minor error-window gap. A second TDD follow-up closes them without expanding Phase A:

- an exact child `kill()` request is accepted only when `ChildProcess.kill()` returns `true`; `false` and thrown errors do not invalidate the startup controller, and the Electron quit seam contains/logs a thrown kill error so `will-quit` is not broken;
- if exact backend invalidation races the first window initialization, the controller now destroys the exact returned window, clears only its matching global reference, retains the terminal `stopped/failed` state, and leaves no apparently healthy window that could suppress the startup error window;
- capture and visible-smoke QA exits now share `app.quit()` and the registered `will-quit` cleanup path; a failed visible smoke sets a nonzero process exit code without calling `app.exit(1)`;
- startup error content loads through a contained rich-to-minimal fallback helper. A first `loadURL` rejection gets one visible minimal fallback attempt, and a second rejection is logged and resolved without recursion or an unhandled rejection.

Phase A still only requests termination through the exact owned `ChildProcess` handle. Waiting for confirmed child close, parent-pipe graceful shutdown, bounded fallback, and Job Object teardown remain explicitly owned by Phase B.

Follow-up RED evidence:

- focused Node run: `26` tests, `3` expected failures (capture+visible accepted, idle/starting activate threw, and explicit controller state was absent);
- second focused Node run: `11` tests, `6` expected failures because the stable presentation, transactional-window, bootstrap-order, and exact-invalidation helpers did not yet exist;
- focused Python desktop contract: `34` tests, `3` expected failures before production used the bootstrap/transaction helpers and preflight log truth; the unique-error-window follow-up then failed `1/1` before the old one-shot boolean gate was removed.
- second-pass batch 1 focused Node run: `29` tests, `3` expected failures proving `kill() === false` was misreported, an initialize/invalidate race retained the normal window, and the termination-to-invalidation seam was absent;
- second-pass batch 2 focused runtime-start run: `18` tests, `5` expected failures proving a thrown `kill()` escaped the quit seam, unified QA quit behavior was absent, and rich/fallback error content rejections were not contained.

Fresh final verification evidence is recorded below after the last documentation-only changes.

## Runtime ordering and policies

The runtime order is now:

1. set the product name and freeze normal `userData`;
2. parse all QA arguments and resolve existing-target/nearest-existing-ancestor realpaths without writes;
3. for a valid isolated QA launch only, create its root and select it with `app.setPath`;
4. acquire `app.requestSingleInstanceLock()` for the selected userData scope;
5. register primary lifecycle only when validation and lock both succeeded;
6. after `whenReady`, resolve repo/data policy, choose the port, and for normal launch run legacy diagnostics;
7. only after diagnostics succeed, create the selected data directory, freeze launch identity, spawn/verify the backend, and resolve frontend resources;
8. create the first window; later `activate` calls reuse the verified runtime.

Data selection is explicit: isolated QA always uses `<qaUserData>/data` in development and packaged modes; normal development keeps `<repo>/data`; normal packaged mode uses `<userData>/data`.

Legacy diagnostics never adopt or kill a process. Same-data identity from `/health.runtimeIdentity.dataDir` or legacy `/api/runtime/status.paths.data_dir` fails with port/PID/instance facts when present. Any proven occupant on port `8000`, including malformed or HTTP-timeout cases after TCP acceptance, fails closed. A different-data shifted runtime is reported in diagnostic facts but does not block fixed-port startup when `8000` is proven free. If port `8000` cannot be proven free by the shared deadline, startup also fails closed.

## Files changed

- `app/desktop/src/launch-policy.cjs`
- `app/desktop/src/runtime-start.cjs`
- `app/desktop/src/runtime-identity.cjs`
- `app/desktop/src/main.cjs`
- `app/desktop/test/launch-policy.test.cjs`
- `app/desktop/test/runtime-start.test.cjs`
- `app/desktop/test/runtime-identity.test.cjs`
- `app/backend/tests/test_desktop_package_contract.py`
- `.superpowers/sdd/progress.md`
- `.superpowers/sdd/task-1a2-runtime-ownership-brief.md` (revised governing brief, force-added)
- `.superpowers/sdd/task-1a2a-electron-launch-policy-report.md`

## Explicit deferrals

- **1A2-B:** backend fixed-byte OS data lease, side-effect-free Python bootstrap, `src.desktop_server`, exact Electron parent pipe, Windows Job Object, graceful/fallback termination, and `terminationRequested` integration.
- **1A2-C:** `start-mvp.ps1` early conflict stop/exact Job cleanup and `verify-desktop-package.ps1` exact-process/internal-deadline cleanup.
- **Task 1B:** immutable runtime binding and active-identity checkpoints.
- **Task 3:** Browser Agent command ownership and external Chrome lifecycle.
- **Task 4:** atomic versioned template packs and immutable task snapshots.
- **Task 6:** packaged portable build and real normal-plus-isolated-QA canary.

The optional parsed `--qa-deadline-ms` is intentionally not wired to inner graceful shutdown in Phase A; that lifecycle depends on the exact parent channel and termination chain delivered by B/C.

## Final verification

Fresh implementer verification immediately before the second follow-up commit:

- `npm test` in `app/desktop`: `55 passed`, `0 failed`;
- `python -m pytest tests/test_desktop_package_contract.py tests/test_qa_runtime_data_isolation.py -q`: `49 passed`;
- `npm run build` in `app/frontend`: TypeScript check and Vite production build passed (`49` modules transformed);
- `node --check` for `main.cjs`, `launch-policy.cjs`, `runtime-start.cjs`, and `runtime-identity.cjs`: passed;
- `git diff --check`: passed (only Git's existing LF-to-CRLF working-copy notices).
