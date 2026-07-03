# DXM Production Version Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver DXM Agent Console as a production-grade, customer-usable desktop product for real Dianxiaomi two-stage automation: claim real products from Data Acquisition into Draft Box, then edit the claimed Draft Box product and save only.

**Architecture:** Keep the existing Electron + React/Vite + FastAPI + Playwright headed-browser stack. Reframe the product around two business stages, move technical gates and logs into diagnostics, make templates a first-class production asset, and preserve hard back-end guards for publish, batch, and unattended mutation paths.

**Tech Stack:** Electron portable desktop, React 18, TypeScript, Vite, FastAPI, SQLite repository, Playwright headed browser automation, pytest contracts, PowerShell packaging and verification scripts.

---

## 1. Product Definition

### 1.1 Production Workflow

The product must expose two large business stages:

1. **采集认领**
   - Open the visible Dianxiaomi browser.
   - Enter `数据采集`.
   - Locate a real source product.
   - Claim it into `采集箱`.
   - Verify the claimed product appears in the collection box or Draft Box.

2. **编辑保存**
   - Start only from a verified claimed product.
   - Choose or resolve an edit template.
   - Open the real edit page from the claimed product.
   - Fill fields by Chinese section forms.
   - Ask for human confirmation.
   - Click `保存` only.
   - Verify save success and not published.

### 1.2 Non-Negotiable Release Boundary

- Production users must not see QA products, demo products, `QA_CATEGORY`, `probe`, `L2`, `L3`, `run-id`, `fixture`, or internal selector names in the main path.
- Real browser must be visible and stay open unless the user closes it.
- Browser HUD must be persistent and explain the current automation step in Chinese.
- `发布`, batch save, unattended save, and any publish-equivalent action remain unavailable until a later separately approved release.
- Historical READY evidence is not permanent authorization. Each release and each real canary must be verified against fresh current evidence.

### 1.3 Completion Definition

The full project is not complete when source code builds. It is complete only when all of these are true:

- One portable EXE opens the desktop console without separate backend/frontend windows.
- A normal user can finish: login -> claim one real product -> select template -> edit from collection box -> save only -> view result.
- The same run proves `保存成功` and `未发布`.
- Browser remains visible, HUD remains visible, and the user can understand every blocking state.
- Reports and logs explain failures in business language first, technical details second.
- Final package verification, frontend build, backend tests, desktop smoke, and real canary evidence all pass on the same release commit.

---

## 2. Target Information Architecture

### 2.1 Sidebar Groups

The sidebar should be business-flow first:

| Group | Menu | Purpose |
| --- | --- | --- |
| 准备 | 操作首页 | Show the next step, current task, and blockers. |
| 准备 | 店小秘登录 | Manage visible browser login and remembered credentials. |
| 采集 | 采集认领 | Claim real products from Dianxiaomi Data Acquisition into collection box. |
| 采集 | 采集箱商品 | Show verified claimed products available for editing. |
| 配置 | 编辑页模板 | Fill Chinese section forms for the current edit page. |
| 配置 | 模板管理 | Create, copy, enable, disable, and bind multiple templates. |
| 保存 | 编辑保存 | Start save-only automation from a claimed product. |
| 保存 | 真实浏览器 | View browser session, HUD state, and manual takeover controls. |
| 复盘 | 保存结果 | Show save response, unpublished proof, and final result. |
| 复盘 | 问题与证据 | Show business-facing failures, evidence, and technical diagnostics. |
| 系统 | 设置与日志 | Keep advanced settings, raw logs, and maintenance actions. |

### 2.2 First Screen Rules

- The top status bar shows one current step, one blocker, one primary action, and one safe scope chip: `只保存，不发布`.
- Logs, run ids, evidence paths, network summaries, and selector details are hidden under diagnostics.
- Every error must follow this copy pattern:
  - `发生了什么`
  - `为什么不能继续`
  - `下一步点哪里`

---

## 3. Version Roadmap

### V0.9.6 - Browser Agent Stability And Persistent Progress HUD

**Objective:** Fix the current browser-agent trust gap before more product features are added.

**User-visible outcome:**
- Browser Agent window stays open after success or failure.
- The browser HUD stays mounted through the whole operation.
- The HUD shows Chinese business steps such as `开始任务`, `检查店小秘登录`, `进入数据采集`, `认领到采集箱`, `进入采集箱`, `填写编辑页`, `点击保存`, `核对未发布`.
- The console no longer makes the user infer progress from raw logs.

**Main files:**
- `app/backend/src/execution/dxm_login_flow.py`
- `app/backend/src/execution/v1_runner.py`
- `app/backend/src/execution/dxm_adapter.py`
- `app/frontend/src/components/workbench/BrowserConsolePage.tsx`
- `app/backend/tests/test_frontend_demo_workflow_contract.py`
- `app/backend/tests/test_login_flow.py`

**Acceptance gates:**
- Contract test proves HUD text is Chinese, persistent, and not removed by timeout.
- Backend test proves browser close is not called automatically on normal success or handled failure.
- Frontend build passes.
- Manual browser verification proves HUD stays visible during a simulated run.

**Not in scope:**
- No new claim automation.
- No publish or batch actions.

### V0.9.7 - Production Navigation And Main Window Restructure

**Objective:** Replace the current mixed diagnostic console with the final business navigation skeleton.

**User-visible outcome:**
- Sidebar uses the groups in section 2.1.
- `选择商品` is no longer the primary production path.
- `采集认领` and `编辑保存` are separate pages.
- Main window content is thinner: one primary action, one explanation, one next step.

**Main files:**
- `app/frontend/src/components/AppShell.tsx`
- `app/frontend/src/App.tsx`
- `app/frontend/src/types.ts`
- `app/frontend/src/components/SafetyStatusBar.tsx`
- `app/frontend/src/components/workbench/workbenchCopy.ts`
- `app/backend/tests/test_frontend_demo_workflow_contract.py`

**Acceptance gates:**
- Frontend contract test proves sidebar contains the new grouped menu.
- Normal-mode UI contains no `QA`, `测试商品`, `probe`, `L2`, `L3`, or `run-id` in first-screen copy.
- Browser verification proves the first screen fits without scrolling at 1366x768.

**Not in scope:**
- No full backend claim implementation yet.

### V0.9.8 - Production Data Model For Claimed Products And Templates

**Objective:** Add the data foundation so the save stage can only use real claimed products.

**User-visible outcome:**
- The app distinguishes `待认领商品`, `已认领商品`, `可编辑商品`, and `已保存结果`.
- A save task cannot be created from a QA or local-only product.
- Templates can be bound by store, category, platform, and one-time task override.

**Main files:**
- `app/backend/src/models.py`
- `app/backend/src/repository.py`
- `app/backend/src/main.py`
- `app/backend/src/services/dxm_reference_templates.py`
- `app/backend/tests/test_acquisition_claim_workflow.py`
- `app/backend/tests/test_task_start_guard.py`
- `app/backend/tests/test_template_center_contract.py`

**Acceptance gates:**
- Backend tests prove save task creation rejects products without claimed-product identity.
- Repository tests prove multiple templates can coexist and resolve by priority:
  `本次任务覆盖 > 手动选择模板 > 类目默认模板 > 店铺默认模板 > 系统默认模板`.
- API returns Chinese labels and source status for each final execution value.

**Not in scope:**
- No real browser claim click yet.

### V0.9.9 - Real Data Acquisition Claim Automation

**Objective:** Implement Stage A against the real visible Dianxiaomi browser.

**User-visible outcome:**
- User opens `采集认领`.
- User chooses store and source product search/filter.
- Agent opens `数据采集`, locates one product, clicks claim, and verifies it in `采集箱`.
- User sees a claimed product card with title, store, platform, source URL if available, claim time, and verification state.

**Main files:**
- `app/backend/src/execution/dxm_login_flow.py`
- `app/backend/src/execution/dxm_adapter.py`
- `app/backend/src/execution/v1_runner.py`
- `app/backend/src/main.py`
- `app/frontend/src/components/workbench/AcquisitionClaimPage.tsx`
- `app/backend/tests/test_acquisition_claim_workflow.py`
- `app/backend/tests/test_login_flow.py`

**Acceptance gates:**
- Real canary evidence shows claim action completed and no save or publish request occurred.
- UI shows `采集认领成功` and claimed product identity.
- Failure states explain whether the issue is login, no product found, claim button unavailable, duplicate claim, or collection-box verification failed.

**Not in scope:**
- No edit/save execution from this version unless Stage A already verified.

### V0.10.0 - Edit Save Starts Only From Collection Box

**Objective:** Make Stage B start from the verified product created by Stage A.

**User-visible outcome:**
- `编辑保存` page shows only verified claimed products.
- User selects one claimed product and template.
- Agent opens the product from collection box or Draft Box and fills the edit page.
- Save is blocked until human approval is complete.

**Main files:**
- `app/backend/src/execution/dxm_login_flow.py`
- `app/backend/src/execution/v1_runner.py`
- `app/backend/src/services/delivery_workspace.py`
- `app/frontend/src/components/workbench/EditSavePage.tsx`
- `app/frontend/src/components/workbench/SaveResultPage.tsx`
- `app/backend/tests/test_v1_runner.py`
- `app/backend/tests/test_delivery_workspace.py`
- `app/backend/tests/test_task_start_guard.py`

**Acceptance gates:**
- Backend tests prove Stage B rejects unclaimed, missing, archived, or QA products.
- Real canary proves one claimed product is edited and saved only.
- Evidence contains save response, unpublished proof, screenshot/path evidence, and business summary.

**Not in scope:**
- No batch save.
- No unattended run.
- No publish.

### V0.10.1 - Production Template Center

**Objective:** Turn configuration from a crowded field dump into reusable customer templates.

**User-visible outcome:**
- User can create multiple named templates.
- User can copy, rename, enable, disable, and bind templates.
- Template forms are grouped by Dianxiaomi edit-page sections:
  - 店铺与任务
  - 类目与标题
  - SKU / 价格 / 库存
  - 图片与素材
  - 包装物流
  - 合规 / 海关
  - 半托管
  - 店小秘引用模板
- Each field shows Chinese label, current value, saved state, source, and whether it will be used in execution.

**Main files:**
- `app/frontend/src/components/workbench/TemplateCenterPage.tsx`
- `app/frontend/src/components/workbench/EditConfigPage.tsx`
- `app/frontend/src/components/workbench/templateSections.ts`
- `app/frontend/src/styles.css`
- `app/backend/src/services/dxm_reference_templates.py`
- `app/backend/tests/test_template_center_contract.py`
- `app/backend/tests/test_frontend_demo_workflow_contract.py`

**Acceptance gates:**
- Contract tests prove no English internal keys appear in normal template forms.
- Browser verification proves the template center first screen shows current template, saved state, and current section without crowding.
- API test proves final execution values are resolved from the selected template.

**Not in scope:**
- No AI template generation unless separately specified.

### V0.10.2 - Failure Recovery, Logs, And Reports

**Objective:** Make the product recoverable for non-technical users.

**User-visible outcome:**
- Every failed task has a readable problem card.
- Report answers:
  - What happened?
  - Where did it stop?
  - What can the user do next?
  - Did it publish? The answer must be explicit.
- Real-time logs show only key business events by default.
- Raw logs remain available for maintenance.

**Main files:**
- `app/frontend/src/components/workbench/IssueCenterPage.tsx`
- `app/frontend/src/components/workbench/RunLogsPanel.tsx`
- `app/frontend/src/components/workbench/SaveResultPage.tsx`
- `app/backend/src/services/delivery_workspace.py`
- `app/backend/src/services/problem_summary.py`
- `app/backend/tests/test_delivery_workspace.py`
- `app/backend/tests/test_frontend_demo_workflow_contract.py`

**Acceptance gates:**
- Failed claim, failed login, failed template, failed save, and save-unknown states each have business-language cards.
- Logs do not overlap or render unreadable in the main content.
- Report center does not expose stack traces by default.

**Not in scope:**
- No silent automatic retry for write actions.

### V0.10.3 - Portable Desktop Hardening

**Objective:** Make the EXE behave like a customer product, not a development launcher.

**User-visible outcome:**
- User starts one EXE.
- No backend/frontend terminal windows appear.
- The desktop app checks resources, ports, data directory, and browser dependencies before the user starts work.
- Credentials can be remembered locally with clear controls.
- If an old process is running, the app explains how to close it.

**Main files:**
- `app/desktop/main.cjs`
- `app/desktop/package.json`
- `scripts/verify-desktop-package.ps1`
- `scripts/final-delivery-check.ps1`
- `scripts/start-mvp.bat`
- `docs/product/免安装版快速使用说明-20260615.md`
- `docs/product/用户交付使用说明-20260526.md`

**Acceptance gates:**
- Packaged smoke passes.
- Portable smoke passes.
- Desktop logs show backend start, frontend load, and clean shutdown.
- Copying the portable package to `D:\Desktop\DXM-Agent-Console-免安装版` still preserves required resources.

**Not in scope:**
- No installer/updater yet.

### V1.0-RC - Full Real Canary Release Candidate

**Objective:** Prove the full customer workflow on one real controlled product.

**User-visible outcome:**
- A customer operator can complete the full path without developer intervention:
  login -> data acquisition claim -> collection box verification -> template selection -> edit page fill -> human approval -> save only -> result report.

**Required evidence:**
- Fresh login proof.
- Claim proof.
- Collection-box product proof.
- Template resolution proof.
- Save response proof.
- Unpublished proof.
- Browser HUD proof.
- Final report JSON and Markdown.
- Portable EXE hash.

**Acceptance gates:**
- `app/backend/.venv/Scripts/python.exe -m pytest tests -q` passes, or documented full-suite equivalent passes.
- `cd app/frontend && npm run build` passes.
- `cd app/desktop && npm run build:portable` passes.
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-desktop-package.ps1` passes.
- `scripts/final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY` passes only after fresh real evidence exists.
- Manual real canary passes on one real product.

**Not in scope:**
- No multi-product batch.
- No unattended production.
- No publish.

### V1.0 - Controlled Production Release

**Objective:** Deliver to customer users as a controlled single-product save-only automation product.

**Release package:**
- Portable EXE directory.
- User guide.
- Acceptance report.
- Known limitations.
- Recovery guide.
- Evidence sample.

**Final user capability:**
- Real two-stage DXM automation for one product at a time.
- User-visible browser automation.
- Multi-template selection.
- Save-only result verification.
- No publish route.

**Release gate:**
- Same commit has source, package, docs, and canary evidence.
- The package path and SHA-256 are recorded.
- A non-developer can follow the quick-start guide and understand blockers without reading technical logs.

---

## 4. Later Versions After V1.0

### V1.1 - Batch Preparation Without Batch Save

**Purpose:** Allow operators to prepare and review multiple claimed products, but still execute save one product at a time.

**Boundary:** Batch write remains blocked.

### V1.2 - Controlled Batch Save Pilot

**Purpose:** Add limited batch save only after separate evidence and approval.

**Required before start:**
- Batch-specific read-only checks.
- Batch-specific rollback and interruption design.
- Batch evidence model.
- Explicit user approval per batch.

### V1.3 - Team/Role Controls

**Purpose:** Add operator/reviewer separation, approval records, and template ownership.

### V2.0 - Managed Automation Platform

**Purpose:** Move from local single-machine console to managed team operations if customer demand proves the need.

---

## 5. Execution Order

The recommended execution order is strict:

1. Finish V0.9.6 browser stability before adding more UI.
2. Finish V0.9.7 navigation before broad page refactors.
3. Finish V0.9.8 data model before real claim automation.
4. Finish V0.9.9 claim automation before save-from-collection enforcement.
5. Finish V0.10.0 save-from-collection before template polishing.
6. Finish V0.10.1 templates before final canary.
7. Finish V0.10.2 recovery before customer handoff.
8. Finish V0.10.3 package hardening before V1.0-RC.
9. Run V1.0-RC full evidence chain.
10. Cut V1.0 only after the same commit has package, docs, tests, and canary evidence.

---

## 6. Verification Matrix

| Gate | Command or Evidence | Required For |
| --- | --- | --- |
| Frontend contract | `app/backend/.venv/Scripts/python.exe -m pytest tests/test_frontend_demo_workflow_contract.py -q` | Every UI/navigation change |
| Backend guard | `app/backend/.venv/Scripts/python.exe -m pytest tests/test_task_start_guard.py tests/test_acquisition_claim_workflow.py -q` | Claim/save guard changes |
| Login/automation | `app/backend/.venv/Scripts/python.exe -m pytest tests/test_login_flow.py tests/test_v1_runner.py -q` | Browser automation changes |
| Template contract | `app/backend/.venv/Scripts/python.exe -m pytest tests/test_template_center_contract.py -q` | Template changes |
| Frontend build | `cd app/frontend && npm run build` | Every frontend release |
| Desktop build | `cd app/desktop && npm run build:portable` | Every EXE release |
| Package smoke | `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify-desktop-package.ps1` | Every EXE release |
| Final local check | `scripts/final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY` | V1.0-RC and V1.0 only, after fresh real evidence |
| Real canary | Manual controlled run on one real product | V0.9.9, V0.10.0, V1.0-RC, V1.0 |

---

## 7. Version Done Checklist

Every version is done only when:

- [ ] The user-visible behavior exists in the packaged or running app, not only in code.
- [ ] The normal user path uses Chinese business language.
- [ ] Technical details are hidden behind diagnostics.
- [ ] No new publish, batch, or unattended route is exposed.
- [ ] Relevant tests pass.
- [ ] Browser verification is performed when UI or browser automation changed.
- [ ] The version is committed with a focused message.
- [ ] If the version affects the EXE, the portable package is rebuilt and smoke-tested.

---

## 8. Current Priority

The next version to execute is **V0.9.6 - Browser Agent Stability And Persistent Progress HUD**.

Reason:
- The user currently cannot trust the browser-agent execution because the browser can disappear, the HUD can disappear, and logs are not readable enough.
- Product navigation and template improvements will still feel unreliable until the browser session is visibly stable.
- V0.9.6 is the smallest version that directly improves production trust without expanding write scope.

