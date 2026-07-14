# DXM two-stage runtime truth progress

Branch start: `99ea3e044ea550a9e529794f2c35dd2e89b6725f`
Working branch: `fix/dxm-two-stage-runtime-truth`
Pre-work tracked-change backup: `refs/backup/pre-dxm-runtime-truth-20260713-113752` (`9b0ac7d005bbb2395cd5a3b240359a49fb932688`)

- Task 1: in progress
- Task 2: pending
- Task 3: pending
- Task 4: pending
- Task 5: pending
- Task 6: pending

Minor review findings: none recorded.

Task 0: complete (pre-checkpoint copy fix; focused 1 passed, contract file 207 passed, full backend 1043 passed, frontend build passed; independent spec and quality review clean).

Baseline blocker A1: complete (backend releases only `claim_only` + `single_save`, binds Stage A/B starts to server-issued approval and the stored approver, includes two-stage acceptance in READY; focused approval regressions 24 passed, full start-guard 120 passed, merged regression 501 passed; third-round independent spec and quality review clean).

Baseline blocker A2: complete (frontend binds both released stages to a fresh current-task server approval, removes empty claim start, keeps config preview exclusive to `single_save`, and treats global L3 as history only in ProductTasksPage; full frontend contract 209 passed and production build passed in both implementer and reviewer runs; independent spec and quality review clean).

Baseline blocker B: complete (native title input now succeeds only after a non-empty normalized DOM readback matches the requested title; empty readback is traced, retried across all candidates, and fails closed without a success event; focused 4 passed, full login-flow 358 passed; independent spec and quality review clean).

Baseline blocker C: complete (`single_save` creation no longer creates or repairs templates; the active production template page can no longer persist bundled hardcoded defaults through either pack or single-section paths; normal CRUD remains; focused 356 passed plus frontend build, independent review clean after the ignored report was force-added, and owner recheck 5 passed plus frontend build).

Baseline blocker sweep: complete (all six inherited blockers closed; no real DXM action was run).

Task 1A: complete at `9c50bfe` + `b52ce2b` (desktop/backend runtime identity handshake, portable marker binding, exact-child termination hardening; full owner verification passed and independent spec/quality reviews were clean after fixes).

Task 1A2-A: native-exit follow-up implementation and implementer verification complete, independent re-review pending (the earlier findings remain closed; QA failure now records a pending native status, enters `app.quit()`, requests exact-child cleanup in `will-quit`, and only then uses guarded `app.exit(1)` because Electron 33.4.11 `Browser::Quit` does not set the native code; success never calls `app.exit`; desktop Node 56 passed, focused Python contracts 49 passed, frontend production build passed, syntax/diff checks passed; no browser, Electron launch, portable build, or DXM action).
