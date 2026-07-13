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
- `app/desktop/src/main.cjs`
- `app/desktop/test/launch-policy.test.cjs`
- `app/desktop/test/runtime-start.test.cjs`
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

Fresh owner verification immediately before the independent commit:

- `npm test` in `app/desktop`: `39 passed`, `0 failed`;
- `python -m pytest tests/test_desktop_package_contract.py tests/test_qa_runtime_data_isolation.py -q`: `47 passed`;
- `npm run build` in `app/frontend`: TypeScript check and Vite production build passed (`49` modules transformed);
- `node --check` for `main.cjs`, `launch-policy.cjs`, and `runtime-start.cjs`: passed;
- `git diff --check`: passed (only Git's existing LF-to-CRLF working-copy notices).
