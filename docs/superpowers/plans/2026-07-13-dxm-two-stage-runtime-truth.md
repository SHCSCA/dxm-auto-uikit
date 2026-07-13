# DXM Two-Stage Runtime Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Every behavior change follows red-green-refactor and every task receives spec and quality review.

**Goal:** Deliver a production-verifiable flow from an existing DXM pending item through claim-to-product-box, template-first edit, save-only proof, and a portable EXE built from the same clean commit.

**Architecture:** Keep Electron + React/Vite + FastAPI + the persistent Browser Agent. Make runtime identity, two-stage state, browser postconditions, template snapshots, evidence, and package identity one fail-closed truth chain.

**Tech Stack:** Python 3.11, FastAPI, SQLite, Playwright/visible Chrome, React/TypeScript/Vite, Electron, pytest, PowerShell delivery checks.

## Global Constraints

- Operate only DXM's existing pending-item list; never trigger acquisition or create a new source item. Source URLs are match hints only.
- Release only controlled single-item `claim_only` and `single_save`; publish, batch, and unattended paths remain blocked in UI and backend.
- Templates are mandatory and selected before editing; automatic manual-field fallback is disabled by default.
- Any browser action without a verified postcondition fails closed and leaves the browser/HUD visible for recovery.
- Task, job, report, exception, runtime, evidence, Git, and package identities must agree before READY.
- Preserve all pre-existing workspace changes. Never reset, overwrite, or discard user work.

---

### Task 1: Bind Runtime and Package Identity

**Primary areas:** backend health/runtime status, Electron backend launch handshake, frontend runtime types, desktop/package contract tests.

- [ ] Write failing tests for `RuntimeIdentity`: instance ID, Git HEAD, dirty flag, build ID, backend PID, Browser Agent PID, data/profile directories, and optional package SHA-256.
- [ ] Write failing desktop contract tests proving an old backend with a mismatched identity is rejected even when `/health` returns OK.
- [ ] Implement the shared runtime identity in `/health` and `/api/runtime/status`; Electron injects and validates the expected identity.
- [ ] Snapshot runtime identity into every real task start and fail if it changes while a task is active.
- [ ] Ensure the desktop only terminates process trees it owns and whose instance identity matches.
- [ ] Run focused health, runtime, desktop-package, and task-start tests; self-review and commit.

### Task 2: Enforce the Two-Stage State Machine

**Primary areas:** acquisition claim API, repository transitions, task start guard, runner and delivery workspace tests.

- [ ] Write failing tests showing failed jobs/reports/exceptions cannot be overwritten by claim completion.
- [ ] Write failing tests for separate Stage A and Stage B server approval tokens and confirmation strings.
- [ ] Release controlled `claim_only` alongside `single_save`; keep every other real mutation blocked.
- [ ] Treat legacy `source_url` as a match-hint alias only and prove no acquisition action is called.
- [ ] Replace unconditional claim completion with a transactional transition that requires verified draft-box proof and preserves failure history.
- [ ] Require `single_save` to reference the same completed claim task, claimed product, source identity, and draft-box proof.
- [ ] Add consistency detection for contradictory task/job/report/exception facts; inconsistent state blocks READY.
- [ ] Run focused acquisition, repository, start-guard, runner, and workspace tests; self-review and commit.

### Task 3: Make Browser Actions Verifiable and Recoverable

**Primary areas:** Browser Agent protocol/worker/runtime, DXM login flow, runner, browser/HUD tests.

- [ ] Write failing protocol tests for command ID, idempotency key, deadline, expected page, runtime binding, cancellation, and lease release.
- [ ] Write failing regressions for empty title readback, mismatched value, category placeholder, required template miss, loading page, and agent restart.
- [ ] Serialize commands through one persistent Browser Agent per session; remove cross-thread synchronous Playwright probes and one-shot-worker success fallbacks.
- [ ] Use bounded readiness predicates: URL identity, business DOM marker, and loading-overlay absence.
- [ ] Return a common action result containing attempted state, before/after values, postconditions, evidence, page identity, failure code, and recoverability.
- [ ] Never report native coordinate/clipboard input as success without non-empty DOM/CDP readback matching the expected value.
- [ ] Require save network success, page success, and an independent unpublished proof; keep browser/HUD open on failure and support re-verified manual takeover.
- [ ] Run protocol, browser-runtime, login-flow, agent-console, and runner tests; self-review and commit.

### Task 4: Replace Fragmented Starters with Versioned Template Packs

**Primary areas:** SQLite schema/repository, template resolver/validation, template center API/UI, config and template tests.

- [ ] Write failing tests for atomic pack completeness, version/hash snapshots, example isolation, draft/archive blocking, and immutable task resolution.
- [ ] Add a versioned `TemplatePack` grouping all required edit sections and DXM reference-template mappings.
- [ ] Import compatible legacy rows into grouped packs without destroying legacy data; incomplete groups remain draft.
- [ ] Stop auto-creating or repairing real-task templates during `single_save` creation.
- [ ] Mark bundled starter content as example-only; it can be copied but never run directly against real DXM.
- [ ] Snapshot the selected ready pack into the task, including ID, version, hash, resolved values, and value sources.
- [ ] Remove hardcoded Dang Kang/product/pricing/compliance fallback data from the live frontend; missing backend truth renders an explicit unavailable state.
- [ ] Run database, template, config, frontend contract, typecheck, and build tests; self-review and commit.

### Task 5: Make UI and READY Reflect One Truth

**Primary areas:** delivery workspace/readiness, task/result UI, operator copy and final-delivery checks.

- [ ] Write failing tests proving L2/L3 alone cannot produce production READY without current two-stage proof and matching runtime/package identity.
- [ ] Require clean Git, matching runtime/build/package identity, fresh L2, same-product Stage A/B proof, template snapshot, verified fields, save response, unpublished proof, and zero inconsistencies.
- [ ] Use customer navigation and copy: 首页、店小秘登录、待认领商品、商品箱、模板中心、执行浏览器、结果与问题.
- [ ] Render one primary action per page; move L2/L3/HAR/trace/PID/Git details into maintenance drawers.
- [ ] Derive UI status only from backend state-machine facts; never infer completion from a click or log line.
- [ ] Standardize failures as what happened, why stopped, and next action, with browser and maintenance entry points.
- [ ] Run workspace, final-check, frontend contract, typecheck, and build tests; self-review and commit.

### Task 6: Verify the Portable Two-Stage Delivery

**Primary areas:** full test suite, frontend/desktop builds, real packaged canary, final evidence and delivery docs.

- [ ] Run the complete backend test suite and frontend production build from a clean worktree.
- [ ] Build a new portable EXE from that exact commit; record Git HEAD, build ID, and SHA-256.
- [ ] Launch the new portable, verify runtime identity, persistent login/profile, Browser Agent visibility, HUD, and fresh L2.
- [ ] With explicit in-product approvals, run one existing pending item through claim, product-box verification, selected ready template pack, edit, save-only, and unpublished verification.
- [ ] Prove no acquisition-new-item request and no publish request occurred; reconcile task/job/report/exception/database state.
- [ ] Run `scripts/final-delivery-check.ps1` and require production READY; any failure returns the release to BLOCKED and requires a new commit/build/canary.
- [ ] Update the acceptance record, operator docs, artifact path, and checksum; dispatch final whole-branch review.

## Completion Definition

Completion requires fresh evidence for every Task 6 item from the current portable build. Historical canaries, source-only tests, or older EXEs cannot satisfy completion. Remote push/merge remains outside this plan until the user explicitly authorizes it.
