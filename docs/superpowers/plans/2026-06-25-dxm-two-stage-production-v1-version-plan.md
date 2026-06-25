# DXM Two-Stage Production V1 Version Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver DXM Agent Console as a production-grade Windows desktop product for real Dianxiaomi two-stage automation: first claim real products from Data Acquisition into the collection box, then edit the verified collection-box product and save only.

**Architecture:** Keep the existing Electron + React/Vite + FastAPI + SQLite + Playwright headed-browser architecture. Rebuild the product experience around the real business workflow, keep the browser visible, keep the browser HUD persistent, hide engineering diagnostics from the normal path, and enforce publish/batch/unattended actions as backend and frontend hard stops.

**Tech Stack:** Electron portable desktop, React 18, TypeScript, Vite, FastAPI, SQLite repository, Playwright headed browser automation, pytest contract tests, PowerShell package verification.

---

## 0. Current Baseline

**Worktree:** `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage`

**Branch:** `feature/dxm-production-two-stage`

**Current shipped direction:**

- V0.9.7 production navigation is complete and pushed.
- V0.9.8 production data model/provenance work is complete and pushed.
- V0.9.9 source-URL claim, claimed-product handoff, operator-facing claim failure copy, and claim click-safety checks are complete in code; fresh real DXM canary evidence is still required.
- Current product boundary remains controlled single-product save-only.
- The old path "choose a local/test product and save" is invalid for production.

**Correct production workflow:**

1. User logs in to the real Dianxiaomi browser.
2. Stage A: Agent enters Dianxiaomi Data Acquisition and claims one real product into the collection box.
3. System verifies the same product exists in the collection box or Draft Box.
4. Stage B: User selects that verified claimed product.
5. User selects or confirms an edit template.
6. User gives explicit save-only approval.
7. Agent opens the real edit page and fills fields.
8. Agent clicks only `保存`.
9. System verifies save success and not published.

**Hard product bans until separately approved:**

- Publish.
- Save and publish.
- Move to pending publish.
- Batch save.
- Unattended write.
- Local/test/demo product saving.
- Hand-imported product direct save.
- Save stage without completed claim provenance.

## 1. Completion Definition

The project is complete only when all of these are true:

1. One portable EXE starts the desktop app without extra backend/frontend terminal windows.
2. A normal operator can complete the full flow without reading technical logs.
3. The visible browser stays open through success and failure unless the user closes it.
4. Browser HUD stays visible and shows Chinese business progress.
5. Stage A real canary succeeds: Data Acquisition product is claimed and verified in collection box.
6. Stage B real canary succeeds: verified product is edited and saved only.
7. Result evidence proves `保存成功`.
8. Result evidence proves `未发布`.
9. Template center supports multiple named templates, Chinese sections, saved/unsaved state, and final execution value preview.
10. Main UI does not expose `L2`, `L3`, `probe`, `run-id`, `HAR`, `greenlet`, `Internal Server Error`, stack traces, or English internal field keys.
11. Publish/batch/unattended actions are blocked in frontend and backend.
12. Backend focused tests pass.
13. Frontend build passes.
14. Desktop portable package verification passes.
15. Final acceptance report records Git HEAD, EXE path, EXE SHA-256, and fresh real DXM evidence from the same release commit.

## 2. Target Product Information Architecture

### 2.1 Sidebar

| Group | Menu | User Meaning | Main Subfunctions |
| --- | --- | --- | --- |
| 准备 | 操作首页 | Today what should I do next? | Current step, blocker, next action, latest result |
| 准备 | 店小秘登录 | Connect real Dianxiaomi | Remembered account, open login browser, detect login |
| 采集 | 采集认领 | Claim products from Data Acquisition | Store, source URL, keyword/category hint, claim mark, start claim |
| 采集 | 采集箱商品 | Products already claimed | Verified claimed list, source URL, store, claim proof, editable state |
| 配置 | 编辑页模板 | Edit-page filling rules | Chinese section forms, multiple templates, final value preview |
| 配置 | 模板管理 | Maintain reusable templates | Copy, rename, bind, enable/disable, store/category defaults |
| 保存 | 编辑保存 | Start save-only task | Select claimed product, approve save-only, start browser agent |
| 保存 | 真实浏览器 | Watch and take over | Browser state, HUD state, manual takeover, retry |
| 复盘 | 保存结果 | What happened? | Save response, unpublished proof, product summary |
| 复盘 | 问题与证据 | Fix failures | User-facing issue cards, evidence, maintenance diagnostics |
| 系统 | 设置与日志 | Local environment | Resource check, data directory, raw logs, version info |

### 2.2 Main Screen Rule

Every page must show, above the fold:

- What is happening now.
- Whether the user can continue.
- Why it is blocked if blocked.
- One primary next action.
- Scope chip: `只保存，不发布`.

Everything else goes into a drawer, details block, or maintenance diagnostics.

## 3. Version Roadmap

### V0.9.8 - Claimed Product Data Model And Provenance Gate

**Status:** Complete in code, pushed as `fff4ca7` plus UI semantics follow-up `94b9129`.

**Goal:** The save stage can only start from a real product produced by a completed claim task.

**User outcome:**

- Claimed products show Chinese lifecycle labels:
  - `待认领商品`
  - `已认领商品`
  - `可编辑商品`
  - `已保存结果`
- The user cannot start save from a QA product, old failed task, hand-imported product, or product without claim proof.
- Product cards show store, source, collection-box verification, and claim task provenance in user language.

**Main files:**

- `app/backend/src/repository.py`
- `app/backend/src/main.py`
- `app/backend/tests/test_acquisition_claim_workflow.py`
- `app/backend/tests/test_task_start_guard.py`
- `app/backend/tests/test_frontend_demo_workflow_contract.py`
- `app/frontend/src/types.ts`
- `app/frontend/src/components/workbench/DraftEditSavePage.tsx`

**Implementation tasks:**

- [x] Add lifecycle fields to product API responses.
- [x] Require completed `claim_only` provenance for claimed products.
- [x] Require completed `claim_only` provenance before creating `single_save`.
- [x] Update task guard tests that intentionally create valid claimed products.
- [x] Update frontend product cards to use top-level Chinese lifecycle fields.
- [x] Run focused backend and frontend contract tests.
- [x] Commit and push as `feat: harden claimed product data model`.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_task_start_guard.py tests\test_frontend_demo_workflow_contract.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_v1_runner.py -q
cd ..\frontend
npm run build
```

**Exit criteria:**

- Valid claimed product with completed claim task can start save stage after approval.
- Product without completed claim task is blocked.
- Main UI does not show QA/test product as saveable.

### V0.9.9 - Real Data Acquisition Claim Automation

**Status:** Source-level implementation, UX handoff, and claim click-safety checks complete; pending fresh real DXM canary.

**Goal:** Stage A becomes a real browser automation path.

**User outcome:**

- User enters a source URL, keyword, or category hint.
- Agent opens real Dianxiaomi Data Acquisition.
- Agent locates one product and claims it into the collection box.
- The browser stays visible.
- HUD shows Chinese steps: `打开数据采集`, `搜索商品`, `定位商品`, `认领到采集箱`, `确认采集箱商品`.
- After success, user is sent to `采集箱商品`, not directly to save.

**Main files:**

- `app/backend/src/execution/dxm_login_flow.py`
- `app/backend/src/execution/dxm_adapter.py`
- `app/backend/src/execution/v1_runner.py`
- `app/backend/src/main.py`
- `app/backend/tests/test_acquisition_claim_workflow.py`
- `app/backend/tests/test_login_flow.py`
- `app/backend/tests/test_v1_runner.py`
- `app/frontend/src/components/workbench/AcquisitionClaimPage.tsx`
- `app/frontend/src/components/workbench/ClaimedProductsPage.tsx`

**Implementation tasks:**

- [x] Add source URL matching to Data Acquisition claim flow.
- [x] Add collection-box verification after claim.
- [x] Store source URL, store, platform, claim mark, claimed title, and verification timestamp.
- [x] Convert claim browser failures to user-facing failure cards.
- [x] Remove any save-stage CTA from the Stage A page.
- [x] Send completed claim users to `采集箱商品` before save task creation.
- [x] Add read-only/click-safety checks before claim action.
- [ ] Run one real controlled claim canary.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_login_flow.py tests\test_v1_runner.py -q
cd ..\frontend
npm run build
```

**Real evidence required:**

- Claim task completed.
- Claimed product appears in collection box.
- No save request.
- No publish request.
- Browser HUD screenshots or DOM evidence.

### V0.10.0 - Edit Save From Verified Collection Product

**Status:** Save-stage provenance gate complete in API, runner, and delivery acceptance; remaining edit-fill/save evidence tasks and real save-only canary are pending.

**Goal:** Stage B starts only from a Stage A verified product.

**User outcome:**

- `编辑保存` page lists only verified claimed products.
- User selects one claimed product and one template.
- User explicitly approves `只保存，不发布`.
- Agent opens the real edit page from collection box/Draft Box.
- Agent fills the edit page and clicks only `保存`.
- Result page proves saved and not published.

**Main files:**

- `app/backend/src/execution/dxm_login_flow.py`
- `app/backend/src/execution/dxm_adapter.py`
- `app/backend/src/execution/v1_runner.py`
- `app/backend/src/services/delivery_workspace.py`
- `app/backend/tests/test_v1_runner.py`
- `app/backend/tests/test_delivery_workspace.py`
- `app/backend/tests/test_task_start_guard.py`
- `app/frontend/src/components/workbench/DraftEditSavePage.tsx`
- `app/frontend/src/components/workbench/ResultsPage.tsx`

**Implementation tasks:**

- [x] Block `single_save` if product status is not claimed and verified.
- [ ] Pass source URL/title/store into draft-box row matching.
- [ ] Fill edit page using selected template final values.
- [ ] Require manual approval immediately before save.
- [ ] Capture save network response.
- [ ] Capture unpublished proof.
- [ ] Map failures to business-language cards.
- [ ] Run one real save-only canary from a product produced by V0.9.9.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_v1_runner.py tests\test_delivery_workspace.py tests\test_task_start_guard.py -q
cd ..\frontend
npm run build
```

**Exit criteria:**

- Save success evidence exists.
- Unpublished proof exists.
- Report links the same product across claim, collection verification, edit save, and result.

### V0.10.1 - Production Template Center

**Goal:** Replace crowded configuration with multi-template Chinese section forms.

**User outcome:**

- User can save multiple named templates.
- User can choose a template per task.
- User can set store default and category default templates.
- User sees whether changes are saved.
- User sees final execution values before starting save.
- All normal labels are Chinese.

**Template priority:**

1. 本次任务覆盖
2. 手动选择模板
3. 类目默认模板
4. 店铺默认模板
5. 默认测试模板
6. 系统默认模板
7. 商品原始数据

**Sections:**

- 店铺与任务基础
- 类目与标题
- SKU / 价格 / 库存
- 图片与素材
- 包装物流
- 合规 / 海关
- 半托管
- 店小秘引用模板
- 执行策略

**Main files:**

- `app/backend/src/services/config_preview.py`
- `app/backend/src/services/dxm_reference_templates.py`
- `app/backend/tests/test_template_center_contract.py`
- `app/backend/tests/test_task_start_guard.py`
- `app/frontend/src/components/workbench/TemplateCenterPage.tsx`
- `app/frontend/src/components/workbench/EditConfigPage.tsx`
- `app/frontend/src/types.ts`
- `app/frontend/src/styles.css`

**Implementation tasks:**

- [ ] Add template priority resolver tests.
- [ ] Add Chinese section contract tests.
- [ ] Add API response for selected template, saved state, dirty state, and final values.
- [ ] Show only one active section by default.
- [ ] Move advanced matching explanation into collapsed diagnostics.
- [ ] Add actions: `仅本次任务使用`, `保存为店铺模板`, `保存为类目模板`, `另存为新模板`, `套用默认测试模板`.
- [ ] Verify normal UI has no English internal keys.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_template_center_contract.py tests\test_task_start_guard.py tests\test_frontend_demo_workflow_contract.py -q
cd ..\frontend
npm run build
```

### V0.10.2 - Browser Agent Stability And Persistent HUD

**Goal:** Make visible browser automation trustworthy.

**User outcome:**

- Browser does not flash-close after failure.
- Browser remains available for manual takeover.
- HUD stays in the browser top-left.
- HUD survives navigation, reload, and new page transitions.
- Main console state and HUD state match.

**Main files:**

- `app/backend/src/services/agent_console.py`
- `app/backend/src/services/browser_agent_status.py`
- `app/backend/src/execution/dxm_login_flow.py`
- `app/backend/tests/test_agent_console.py`
- `app/backend/tests/test_browser_agent_status.py`
- `app/frontend/src/components/workbench/BrowserConsolePage.tsx`

**Implementation tasks:**

- [ ] Define stable Chinese browser step map.
- [ ] Reinject HUD after navigation.
- [ ] Keep browser open on handled failure.
- [ ] Add manual takeover state.
- [ ] Add browser-session lifecycle diagnostics hidden from normal path.
- [ ] Verify HUD in a real visible browser run.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_agent_console.py tests\test_browser_agent_status.py tests\test_login_flow.py -q
cd ..\frontend
npm run build
```

### V0.10.3 - User-Facing Failure Recovery And Logs

**Goal:** A normal operator can recover from failures without reading raw logs.

**User outcome:**

- Each error says:
  - `发生了什么`
  - `为什么停止`
  - `下一步怎么做`
  - `维护人员查看技术状态`
- Main logs show 5-10 business events.
- Raw logs are available only in diagnostics.
- `Internal Server Error`, `greenlet`, stack traces, raw paths, and run ids do not appear in normal UI.

**Main files:**

- `app/backend/src/services/delivery_workspace.py`
- `app/backend/src/main.py`
- `app/backend/tests/test_delivery_workspace.py`
- `app/backend/tests/test_frontend_demo_workflow_contract.py`
- `app/frontend/src/components/workbench/IssueCenterPage.tsx`
- `app/frontend/src/components/workbench/RunLogsPanel.tsx`
- `app/frontend/src/components/workbench/ResultsPage.tsx`

**Implementation tasks:**

- [ ] Add normalized user problem schema.
- [ ] Map known backend exceptions to user problem cards.
- [ ] Keep technical detail in maintenance details.
- [ ] Fix log card layout overlap.
- [ ] Add first-screen copy tests.
- [ ] Verify browser view at 1366x768 and 1920x1080.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_frontend_demo_workflow_contract.py -q
cd ..\frontend
npm run build
```

### V0.10.4 - Portable EXE Release Candidate

**Goal:** Make the desktop package customer-usable.

**User outcome:**

- User opens one EXE.
- No extra service windows.
- Resources are bundled.
- Logs are visible inside the app, not through console windows.
- Old processes and port conflicts have understandable messages.
- Account/password memory works through local encrypted storage.

**Main files:**

- `app/desktop/main.cjs`
- `app/desktop/package.json`
- `scripts/verify-desktop-package.ps1`
- `scripts/final-delivery-check.ps1`
- `docs/product/免安装版快速使用说明-20260625.md`
- `docs/product/最终交付验收记录-20260625-两段式生产版.md`

**Implementation tasks:**

- [ ] Build frontend.
- [ ] Build portable desktop package.
- [ ] Copy package to `D:\Desktop\DXM-Agent-Console-免安装版`.
- [ ] Verify resource paths include backend, frontend, probe tools, and browser agent files.
- [ ] Verify desktop mode does not show frontend abnormal for `file://`.
- [ ] Verify packaged app starts backend and shuts it down cleanly.
- [ ] Record package path and SHA-256.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend
npm run build
cd ..\desktop
npm run build:portable
cd ..\..
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

### V1.0-RC - Full Real Canary Candidate

**Goal:** Prove the full customer path on one real product.

**Required run:**

1. Start portable EXE.
2. Login or reuse remembered Dianxiaomi account.
3. Stage A: claim one real product from Data Acquisition.
4. Verify collection-box product.
5. Choose template.
6. Approve save-only.
7. Stage B: edit and save only.
8. Verify save success.
9. Verify not published.
10. Export acceptance report.

**Required evidence:**

- Git HEAD.
- Portable EXE path.
- Portable EXE SHA-256.
- Login proof.
- Claim proof.
- Collection-box verification proof.
- Template final values.
- Browser HUD proof.
- Save response proof.
- Unpublished proof.
- Result report JSON and Markdown.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
cd ..\desktop
npm run build:portable
cd ..\..
scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY
```

**Exit criteria:**

- No blocker remains in the normal user path.
- Real canary evidence is fresh and tied to the same commit/package.
- Known limitations are documented.

### V1.0 - Controlled Production Release

**Goal:** Deliver the first customer-usable production release.

**Release scope:**

- Single store.
- Single product at a time.
- Real Data Acquisition claim.
- Real collection-box verification.
- Real edit page fill.
- Save only.
- Human confirmation before save.
- No publish.
- No batch.
- No unattended writes.

**Release package:**

- `DXM-Agent-Console-Portable-0.1.0.exe`
- `resources`
- quick-start guide
- recovery guide
- acceptance report
- known limitations
- EXE hash
- Git HEAD

**Release exit criteria:**

- A non-developer can use the quick-start guide to complete the full path.
- Normal UI explains blockers in Chinese.
- Maintenance diagnostics remain available but are not the product surface.
- Source, package, docs, and evidence all match.

## 4. Later Versions

### V1.1 - Multi-Product Preparation, Still One-By-One Save

Allow operators to collect and prepare several products, but save execution remains one product at a time.

### V1.2 - Controlled Batch Save Pilot

Only after explicit approval. Requires batch-specific read-only checks, batch evidence, interruption handling, and rollback/stop design.

### V1.3 - Team Approval And Roles

Add operator/reviewer split, approval records, and template ownership.

### V2.0 - Managed Automation Platform

Only if customer usage proves the need for team, queue, and cloud-managed operations.

## 5. Execution Order

1. Finish V0.9.8 and push.
2. Implement V0.9.9 claim automation.
3. Implement V0.10.0 edit save from verified claimed product.
4. Implement V0.10.1 template center.
5. Implement V0.10.2 browser/HUD stability.
6. Implement V0.10.3 recovery/logs.
7. Implement V0.10.4 portable EXE release candidate.
8. Run V1.0-RC full real canary.
9. Cut V1.0 controlled production release.

Each version must be committed separately. UI and browser changes require live browser verification. Real DXM changes require real evidence, not mocked success.

## 6. Current Next Action

Continue V0.9.9:

- Review claim-only read-only/click-safety checks before the actual claim click.
- Run one real controlled claim canary from Data Acquisition to collection box.
- Record the claim evidence and verify the UI moves the operator to `采集箱商品` rather than directly to save.

After that, start V0.10.0 with subagents split as:

- Backend automation agent: real Data Acquisition claim and collection-box verification.
- Backend save agent: collection-box product edit/save-only path.
- Frontend UX agent: `编辑保存` and save result handoff.
- Browser/HUD agent: persistent in-browser progress window.
- Reviewer/main agent: contract tests, browser verification, and release boundary review.

## 7. Self-Review

**Spec coverage:** This plan covers the corrected two-stage workflow, production UI/menu structure, multi-template configuration, visible browser, persistent HUD, customer-readable failures, portable EXE, and final real canary.

**Placeholder scan:** No task is left as TBD; every milestone has scope, files, commands, and exit criteria.

**Boundary check:** Publish, batch, and unattended writes remain excluded through V1.0 and are only introduced as later separately approved versions.
