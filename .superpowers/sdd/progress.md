# DXM two-stage runtime truth progress

Branch start: `99ea3e044ea550a9e529794f2c35dd2e89b6725f`
Working branch: `fix/dxm-two-stage-runtime-truth`
Pre-work tracked-change backup: `refs/backup/pre-dxm-runtime-truth-20260713-113752` (`9b0ac7d005bbb2395cd5a3b240359a49fb932688`)

Current truth (2026-07-17): production delivery remains `BLOCKED`. The working branch contains the controlled Stage A `claim_only` + Stage B `single_save` source surface and is still hardening Browser Agent lifecycle, mutation dispatch durability, live identity rechecks, and fail-closed recovery. No same-HEAD portable/live two-stage production proof has been recorded for this branch.

Git authority (2026-07-17): the user authorized documentation updates, branch merge, and push. This removes the remote-operation authority blocker only; it does not waive Task 2-6 verification, clean-source, package-identity, L2/L3, two-stage, state-consistency, or mutation-ledger gates.

- Task 1: complete
- Task 2: in progress
- Task 3: pending
- Task 4: pending
- Task 5: pending
- Task 6: pending

Documentation reconciliation: complete on 2026-07-17 for current-truth routing and historical banners. This entry does not assert final code tests, merge, push, packaging, or live DXM acceptance.

Minor review findings: none recorded.

Task 0: complete (pre-checkpoint copy fix; focused 1 passed, contract file 207 passed, full backend 1043 passed, frontend build passed; independent spec and quality review clean).

Baseline blocker A1: complete (backend releases only `claim_only` + `single_save`, binds Stage A/B starts to server-issued approval and the stored approver, includes two-stage acceptance in READY; focused approval regressions 24 passed, full start-guard 120 passed, merged regression 501 passed; third-round independent spec and quality review clean).

Baseline blocker A2: complete (frontend binds both released stages to a fresh current-task server approval, removes empty claim start, keeps config preview exclusive to `single_save`, and treats global L3 as history only in ProductTasksPage; full frontend contract 209 passed and production build passed in both implementer and reviewer runs; independent spec and quality review clean).

Baseline blocker B: complete (native title input now succeeds only after a non-empty normalized DOM readback matches the requested title; empty readback is traced, retried across all candidates, and fails closed without a success event; focused 4 passed, full login-flow 358 passed; independent spec and quality review clean).

Baseline blocker C: complete (`single_save` creation no longer creates or repairs templates; the active production template page can no longer persist bundled hardcoded defaults through either pack or single-section paths; normal CRUD remains; focused 356 passed plus frontend build, independent review clean after the ignored report was force-added, and owner recheck 5 passed plus frontend build).

Baseline blocker sweep: complete (all six inherited blockers closed; no real DXM action was run).

Task 1A: complete at `9c50bfe` + `b52ce2b` (desktop/backend runtime identity handshake, portable marker binding, exact-child termination hardening; full owner verification passed and independent spec/quality reviews were clean after fixes).

Task 1A2-A: complete at `06a72ab` + `09f2d9b` + `f8616e1` + `9ff20ae` (strict QA/single-instance/fixed-port policy, explicit startup states, exact invalidation, transactional windows, truthful error/log presentation, and Electron 33.4.11 native failure-exit sequencing; owner rerun passed desktop Node 56, focused Python contracts 49, frontend production build, syntax and diff checks; final independent spec and quality reviews passed; no browser, Electron launch, portable build, or DXM action).

Task 1A2-B: complete on top of `02e04d9` (canonical data lease, exact stdin-v1 parent channel, backend-owned Windows Job, programmatic desktop host, controller-owned pending spawn authority, graceful SHUTDOWN with exact-child bounded fallback, and before-quit/current-or-pending promise reuse; final backend 1211, shutdown 35, desktop Node 89, package contract 40, real graceful/EOF process proof 2, frontend build and syntax/diff gates passed; final spec, quality, and report reviews passed with P0/P1 cleared; no Electron, browser, DXM, portable, or production READY action).
