# DXM Two-Stage Production V1 Version Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver DXM Agent Console as a production-grade Windows desktop product for real Dianxiaomi two-stage automation: first claim products that already exist in Dianxiaomi's claimable-product list into the collection box, then edit the verified collection-box product and save only. The product does not collect or crawl new products.

**Architecture:** Keep the existing Electron + React/Vite + FastAPI + SQLite + Playwright headed-browser architecture. Rebuild the product experience around the real business workflow, keep the browser visible, keep the browser HUD persistent, hide engineering diagnostics from the normal path, and enforce publish/batch/unattended actions as backend and frontend hard stops.

**Tech Stack:** Electron portable desktop, React 18, TypeScript, Vite, FastAPI, SQLite repository, Playwright headed browser automation, pytest contract tests, PowerShell package verification.

---

## 0. Current Baseline

**Worktree:** `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage`

**Branch:** `feature/dxm-production-two-stage`

**Current shipped direction:**

- V0.9.7 production navigation is complete and pushed.
- V0.9.8 production data model/provenance work is complete and pushed.
- V0.9.9 source-URL claim, claimed-product handoff, operator-facing claim failure copy, and claim click-safety checks are complete in code, but fresh real DXM canary evidence has not passed.
- Latest real runs prove the remaining blocker is not ordinary selector polish: the real execution model must move to a persistent visible Browser Agent before Stage A can be called production-ready.
- Current product boundary remains controlled single-product save-only.
- The old path "choose a local/test product and save" is invalid for production.

**Correct production workflow:**

1. User logs in to the real Dianxiaomi browser.
2. Stage A: Agent opens Dianxiaomi's existing claimable-product list and claims one real product into the collection box.
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

## 0.1 Latest Real Browser Diagnosis

**Date:** 2026-06-26

**Real evidence checked:** AppData runtime tasks `#25` through `#37`, including workflow trace files under `C:\Users\wz\AppData\Roaming\DXM Agent Console\data\workflow_worker`.

**What passed:**

- Login browser can show an already logged-in Dianxiaomi home page.
- L2 readonly checks can pass for the existing claimable-product list and Draft Box without write requests.
- Backend task guards can block save when claim provenance is missing.
- Failure copy can be translated away from raw `greenlet` and stack trace errors in many normal UI surfaces.
- Focused backend tests around claim source URL matching, worker payloads, and lightweight ready checks pass.

**What did not pass:**

- Stage A real existing-product claim did not complete on a fresh real product.
- Multiple selector, timeout, source URL, locator, keyboard, and CDP-level patches moved the failure point but did not make the run stable.
- The worker often opens Dianxiaomi's claimable-product page into an incomplete or unstable state; trace evidence includes hidden first input rectangles such as `0x0` and no reliable target-row progress.
- Per-action fresh browser/process execution makes the user experience look like a disappearing debug action rather than a stable controlled browser agent.

**Current engineering conclusion:**

The next version must not keep adding blind selectors. Production requires a persistent, visible Browser Agent with one stable browser context, one Playwright owner, structured Chinese progress events, and a persistent in-browser HUD. Stage A canary should resume only after that runtime exists.

## 1. Completion Definition

The project is complete only when all of these are true:

1. One portable EXE starts the desktop app without extra backend/frontend terminal windows.
2. A normal operator can complete the full flow without reading technical logs.
3. The visible browser stays open through success and failure unless the user closes it.
4. Browser HUD stays visible and shows Chinese business progress.
5. Stage A real canary succeeds: an existing claimable product is claimed and verified in collection box.
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
| 认领 | 已有商品认领 | Claim existing Dianxiaomi claimable products | Store, source URL, keyword/category hint, claim mark, start claim |
| 认领 | 采集箱商品 | Products already claimed | Verified claimed list, source URL, store, claim proof, editable state |
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

### V0.9.9 - Existing Product Claim Automation

**Status:** Source-level implementation, UX handoff, and claim click-safety checks complete; real canary blocked by browser runtime instability.

**Goal:** Stage A becomes a real browser automation path for existing Dianxiaomi claimable products.

**User outcome:**

- User enters a source URL, keyword, or category hint.
- Agent opens the real Dianxiaomi existing claimable-product list.
- Agent locates one product and claims it into the collection box.
- The browser stays visible.
- HUD shows Chinese steps: `打开待认领列表`, `定位已有商品`, `认领到采集箱`, `确认采集箱商品`.
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

- [x] Add source URL matching to the existing claimable-product flow.
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

**Exit rule:** V0.9.9 cannot be marked production-ready until V0.9.10 persistent browser runtime is in place and a fresh Stage A canary passes.

### V0.9.10 - Persistent Visible Browser Agent Runtime

**Status:** Required next version.

**Goal:** Replace fragile per-action browser execution with one persistent visible Browser Agent that stays online through login, existing-product claim, collection-box verification, edit-page save, failure, and manual takeover.

**User outcome:**

- User opens the EXE and sees one stable control console.
- User opens one visible Dianxiaomi browser and it remains open.
- Agent actions happen inside that visible browser or a clearly named execution browser, not in a hidden/flash-closing process.
- The browser top-left HUD stays visible and shows Chinese task progress:
  - `开始任务`
  - `打开待认领列表`
  - `定位已有商品`
  - `认领到采集箱`
  - `确认采集箱商品`
  - `打开编辑页`
  - `填写标题`
  - `选择分类`
  - `填写物流`
  - `点击保存`
  - `确认未发布`
- On failure, browser remains open and HUD says where it stopped.
- The main console and browser HUD show the same current step.

**Architecture requirement:**

- One long-lived browser worker per user session or active task.
- One owner for the Playwright browser/page lifecycle.
- No fresh browser subprocess per business action.
- Backend communicates with the worker by explicit commands and receives structured events.
- Worker emits business-level events and raw maintenance traces separately.
- Worker supports `health`, `reset`, `manual_takeover`, `resume`, and `shutdown`.

**Main files to modify or create:**

- Create: `app/backend/src/execution/browser_agent_worker.py`
- Create: `app/backend/src/execution/browser_agent_protocol.py`
- Modify: `app/backend/src/execution/v1_runner.py`
- Modify: `app/backend/src/execution/workflow_worker.py`
- Modify: `app/backend/src/execution/dxm_login_flow.py`
- Modify: `app/backend/src/main.py`
- Modify: `app/backend/tests/test_v1_runner.py`
- Create: `app/backend/tests/test_browser_agent_worker.py`
- Modify: `app/backend/tests/test_login_flow.py`
- Modify: `app/frontend/src/components/workbench/BrowserConsolePage.tsx`
- Modify: `app/frontend/src/components/workbench/RunLogsPanel.tsx`
- Modify: `app/frontend/src/types.ts`
- Modify: `app/frontend/src/styles.css`

**Implementation tasks:**

- [ ] Write a failing backend test proving `claim_only` uses the persistent Browser Agent command path instead of spawning a fresh per-action browser process.
- [ ] Define a small command/event protocol: `open_login`, `check_login`, `open_claimable_list`, `locate_existing_product`, `claim_product`, `verify_collection_box`, `open_edit_page`, `fill_edit_page`, `save_only`, `verify_not_published`, `manual_takeover`, `reset`.
- [ ] Implement the worker process with a long-lived headed browser context and a single Playwright owner.
- [ ] Persist browser session metadata in runtime status: `browserAgent.status`, `currentStep`, `visibleWindow`, `manualTakeover`, `lastEventAt`, `lastError`.
- [ ] Make the runner execute Stage A and Stage B through Browser Agent commands.
- [ ] Inject and reinject the in-browser HUD after navigation and reload.
- [ ] Keep the browser open after handled failure.
- [ ] Add console controls: `打开真实浏览器`, `运行已有商品认领`, `人工接管`, `继续执行`, `重启浏览器 Agent`.
- [ ] Convert raw worker failures into user-facing problem cards.
- [ ] Hide raw trace paths and run ids under maintenance diagnostics.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_browser_agent_worker.py tests\test_v1_runner.py tests\test_login_flow.py -q
cd ..\frontend
npm run build
```

**Real acceptance evidence:**

- EXE or dev runtime opens a visible Dianxiaomi browser.
- Browser remains open after login detection.
- Running Stage A does not spawn a separate flash-closing browser.
- Browser HUD remains visible during existing claimable-product list navigation.
- Console recent logs show 5-10 Chinese business events, not raw technical trace lines.
- If the run fails, the browser remains open and the UI gives a recovery action.

**Exit criteria:** one real Stage A canary can run through the persistent Browser Agent and either claim an existing product with proof or fail cleanly with the browser still open, no stuck task, and no backend unusable state.

### V0.10.0 - Stage A Real Claim Production Closure

**Status:** Depends on V0.9.10.

**Goal:** Complete real existing-product claim as a production workflow.

**User outcome:**

- User selects store and enters a real source URL or matching condition for an existing claimable product.
- Agent claims one real existing product into the collection box.
- User sees the claimed product in `采集箱商品`.
- Save controls remain unavailable until claim proof exists.

**Implementation tasks:**

- [ ] Run Stage A through persistent Browser Agent.
- [ ] Verify source URL/title/store match in collection box.
- [ ] Save claim proof with source URL, claimed title, collection-box URL/state, timestamp, and screenshot/path evidence.
- [ ] Add retry guidance for no result, duplicate product, wrong row, and login expired.
- [ ] Prove no save, publish, batch, or unattended write request happened.

**Acceptance commands:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_v1_runner.py tests\test_login_flow.py -q
cd ..\frontend
npm run build
```

**Exit criteria:** one real existing product is claimed and appears as a verified claimed product available for the save stage.

### V0.10.1 - Edit Save From Verified Collection Product

**Status:** Save-stage provenance gate, selected-template execution defaults, runner-level save-time manual approval, save network response capture, unpublished proof capture, and operator-facing failure copy are complete in API, runner, delivery acceptance, and frontend contract coverage; remaining real save-only canary is pending.

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
- [x] Pass source URL/title/store into draft-box row matching.
- [x] Fill edit page using selected template final values.
- [x] Require manual approval immediately before save.
- [x] Capture save network response.
- [x] Capture unpublished proof.
- [x] Map failures to business-language cards.
- [ ] Run one real save-only canary from a product produced by V0.9.9.

**Latest verification:**

- `tests\test_v1_runner.py::test_single_save_fill_actions_use_manually_selected_template_over_store_default` proves a task-level `template_id` is applied to all edit/save fill actions even when its binding does not match the default store/category template.
- `tests\test_v1_runner.py::test_single_save_runner_requires_server_manual_approval_immediately_before_save` proves the runner cannot reach `save_only` without server-generated manual approval.
- `tests\test_login_flow.py::test_save_only_records_network_success_as_save_evidence` proves the save action records `network_save_result` and related network events.
- `tests\test_login_flow.py::test_network_save_result_prefers_real_add_json_over_related_history_calls` proves the real save add endpoint is preferred over history requests.
- `tests\test_login_flow.py::test_verify_not_published_accepts_prior_save_success_without_publish_risk` and `tests\test_login_flow.py::test_verify_not_published_ignores_ambient_online_text_after_save_success` prove unpublished verification can use save-success evidence while ignoring ambient published-menu text.
- `tests\test_delivery_workspace.py::test_delivery_workspace_accepts_dxm_add_json_code_zero_as_save_response`, `tests\test_delivery_workspace.py::test_delivery_workspace_accepts_smt_add_json_nested_success_as_save_response`, and `tests\test_delivery_workspace.py::test_delivery_workspace_report_published_false_is_not_unpublished_proof_without_verify` prove delivery readiness recognizes real save network responses and still requires explicit unpublished proof.
- `tests\test_frontend_demo_workflow_contract.py::test_frontend_translates_failed_execution_technical_errors_for_operators` and `tests\test_frontend_demo_workflow_contract.py::test_extracted_pages_do_not_fallback_to_raw_gate_details` prove normal operator surfaces translate technical failures and keep raw diagnostics out of default view.
- `tests\test_v1_runner.py -q` passed with `33 passed`.
- `tests\test_task_start_guard.py tests\test_config_defaults.py -q` passed with `101 passed`.
- `tests\test_frontend_demo_workflow_contract.py -q` passed with `205 passed`.
- Selected save evidence tests passed with `7 passed`.
- `app\frontend npm run build` passed.
- Headless Chrome against `http://127.0.0.1:4179/` loaded the app shell, showed the two-stage sidebar, and did not expose `greenlet`, `workflow_adapter`, or `save_result` in the visible fallback UI.

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

### V0.10.2 - Production Template Center

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

### V0.10.3 - Browser Agent UI Polish And Persistent HUD

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

### V0.10.4 - User-Facing Failure Recovery And Logs

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

### V0.10.5 - Portable EXE Release Candidate

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
3. Stage A: claim one real existing product from Dianxiaomi's claimable-product list.
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
- Real existing-product claim.
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

## 5. Detailed Execution Order From Current State

The current branch has already implemented the core source-level gates through V0.10.0. The remaining work is not "more mocked testing"; it is production proof, operator experience, packaging, and final delivery hardening.

### Phase 1 - Real Two-Stage Canary Closure

**Goal:** Prove the correct business flow on real Dianxiaomi, with real browser evidence.

**2026-06-25 execution status:**

- AppData runtime database did not contain any real claimed product; it only contained historical QA/test product tasks and failed reports.
- Fresh L2 dual-target readonly proof was rerun successfully for `data_acquisition` and `draft_box`; both targets passed with write, blocked, forbidden-keyword, and WebSocket counts at zero.
- Stage A task `#10` was created from a real existing-product source URL but exposed the existing production defect: the browser action could stay `running` at `OPEN_DATA_ACQUISITION` without a user-visible result.
- A backend fix was implemented so a hanging real browser workflow action fails the task instead of remaining permanently `running`.
- Startup recovery was implemented so orphaned `running` or `paused` tasks from a crashed/stopped backend no longer survive as active tasks.
- Stage A task `#11` verified the new failure behavior: it failed while opening the claimable-product list with user-facing copy, did not claim, did not save, did not publish, and did not remain running.
- A visible recovery control was added for `reset_workflow_runtime`, exposed in `/api/runtime/status` as `workflowRuntime` and in the frontend maintenance panel as `重启真实浏览器执行器`.
- Action-level browser logs were added for real workflow actions: `真实浏览器动作开始`, `真实浏览器动作完成`, `真实浏览器动作失败`, and `真实浏览器动作超时`.
- Stage A task `#12` was run against the real AppData DXM session with a 90-second action timeout. It proved login success, then timed out at `OPEN_DATA_ACQUISITION`; logs showed the internal open-claimable-list action timing out at `2026-06-25T09:53:21Z`.
- After task `#12`, `/api/runtime/status` correctly reported `workflowRuntime.status=needs_restart`; `/api/runtime/control reset_workflow_runtime` reset it back to `ready`.
- Current Phase 1 blocker is not L2 and not data availability; it is Browser Agent execution stability inside the long-lived backend workflow executor.

**2026-06-26 execution status update:**

- Additional real Stage A tasks `#25` through `#37` were run after targeted backend patches.
- The patches improved observability and moved failure points, but Stage A still did not complete.
- Task `#25` failed at `CLAIM_TO_DRAFT_BOX`; trace ended around search-result waiting.
- Task `#26` proved repeated full ready scans could hang after the first poll.
- Tasks `#27` and `#28` showed claimable-list readiness waits were still unstable in a fresh worker browser.
- Task `#29` passed the search-result wait skip but failed while locating the claim target.
- Tasks `#30` through `#36` tried source URL locator, token, keyboard, and CDP approaches; these did not produce a stable real claim.
- Task `#37` still failed at `CLAIM_TO_DRAFT_BOX`; trace showed the claimable-product page reported ready while the first input rectangle was `0x0`, then no reliable target-row progress occurred.
- Focused tests passed for source URL token priority, source URL claim-target matching, search-ready wait skipping, and process-worker acquisition context.
- This confirms the remaining defect is architectural: a fresh per-action/fresh-worker browser is not a production-stable basis for Dianxiaomi automation.

**Current backend hardening completed in this phase:**

- Action-level workflow timeout with operator-readable failure.
- Browser closed/Playwright/greenlet failures mapped away from raw engineering errors.
- Runner unhealthy state after workflow timeout.
- Start guard blocks new real tasks when the workflow executor needs restart.
- Runtime control can reset the real browser workflow executor without restarting the full desktop app.
- Runtime status exposes workflow executor health so the UI can guide the user to the correct recovery action.
- Real browser action logs now identify the exact business step that started, completed, failed, or timed out.
- Backend startup recovery moves orphaned real tasks to manual review and cancels non-real orphaned tasks.

1. Inspect current runtime data, task records, reports, and logs.
2. Confirm whether a fresh V0.9.9 claimed product exists with source URL, store, platform, claim proof, and collection-box verification.
3. If not, run one controlled Stage A canary: existing claimable-product list -> collection box.
4. Confirm Stage A did not save, publish, batch, or perform unattended writes.
5. Create Stage B only from the verified claimed product.
6. Select an edit template and record the final execution values.
7. Require explicit save-only approval.
8. Run one controlled Stage B canary: collection-box/Draft Box edit page -> click only `保存`.
9. Confirm save network response and unpublished proof.
10. Save the canary evidence under the release evidence directory and link it from the acceptance report.

**Exit criteria:** one real product can be traced from acquisition source, to claimed product, to edit page, to save-only result, with no publish or batch action.

**Immediate next implementation task:** implement V0.9.10 persistent visible Browser Agent runtime. The previous acceptable option "dedicated browser worker process per real task" is no longer sufficient if it recreates the browser per action. The chosen design must keep one visible browser context alive across the full business flow and prove Stage A can open the existing claimable-product list and either claim successfully or fail without closing the browser or leaving the backend unusable.

### Phase 2 - Operator Information Architecture

**Goal:** Make the product understandable to a non-developer operator.

1. Keep sidebar aligned to the two-stage workflow:
   - `准备`: 操作首页, 店小秘登录
   - `认领`: 已有商品认领, 采集箱商品
   - `配置`: 编辑页模板, 模板管理
   - `保存`: 编辑保存, 真实浏览器
   - `复盘`: 保存结果, 问题与证据
   - `系统`: 设置与日志
2. Ensure each page has one primary user task.
3. Move maintenance details, raw logs, run ids, paths, HAR/network terms, and internal gate language into diagnostics.
4. Rewrite blockers as:
   - `发生了什么`
   - `为什么停止`
   - `下一步点哪里`
5. Verify the normal UI contains no `L2`, `L3`, `probe`, `run-id`, `HAR`, `greenlet`, `Internal Server Error`, stack traces, or English internal field keys.

**Exit criteria:** a first-time user can tell which stage they are in, why they are blocked, and which button to press next without reading logs.

### Phase 3 - Template Center Productionization

**Goal:** Replace "configuration dump" with reusable customer templates.

1. Support multiple named templates.
2. Support manual task template selection.
3. Support store default and category default templates.
4. Show saved/unsaved state clearly.
5. Show final execution values before save starts.
6. Render edit-page fields as Chinese section forms:
   - 店铺与任务基础
   - 类目与标题
   - SKU / 价格 / 库存
   - 图片与素材
   - 包装物流
   - 合规 / 海关
   - 半托管
   - 店小秘引用模板
   - 执行策略
7. Provide three obvious actions per section:
   - `仅本次任务使用`
   - `保存为模板`
   - `套用模板`

**Exit criteria:** the operator knows which template is active, whether it is saved, and which values the agent will write into Dianxiaomi.

### Phase 4 - Visible Browser Agent Reliability

**Goal:** Make the real browser behave like a controlled agent, not a disappearing debug process.

1. Keep login browser and execution browser visible.
2. Keep browser open after handled failure.
3. Make the browser HUD persistent in the upper-left or top-safe visible area.
4. Reinject HUD after navigation, reload, and page transition.
5. Show Chinese business progress in the HUD, for example:
   - `开始任务`
   - `打开待认领列表`
   - `定位商品`
   - `认领到采集箱`
   - `打开编辑页`
   - `填写标题`
   - `选择分类`
   - `填写物流`
   - `点击保存`
   - `确认未发布`
6. Keep console state and browser HUD state synchronized.

**Exit criteria:** while the real browser is operating, the user can see what the agent is doing, where it stopped, and when manual takeover is needed.

### Phase 5 - Recovery, Logs, And Evidence

**Goal:** Make failures recoverable without exposing engineering internals.

1. Normalize all known backend/browser failures into operator problem cards.
2. Keep raw logs available only under `系统 / 设置与日志` or maintenance diagnostics.
3. Default recent logs to 5-10 high-signal business events.
4. Fix log panel layout so entries do not overlap surrounding content.
5. Ensure result reports say:
   - which product was processed
   - what stage succeeded or failed
   - whether save happened
   - whether publish happened
   - what the next recovery action is

**Exit criteria:** every common failure has a visible recovery route and does not require reading stack traces.

### Phase 6 - Portable EXE Release Candidate

**Goal:** Deliver a single no-install desktop package.

1. Build the frontend.
2. Build the portable Electron package.
3. Copy the package to `D:\Desktop\DXM-Agent-Console-免安装版`.
4. Verify bundled resources include backend, frontend, probe tools, and browser automation files.
5. Verify EXE launch does not open extra backend/frontend terminal windows.
6. Verify `file://` desktop mode is not reported as frontend failure.
7. Verify account memory works through local encrypted storage.
8. Verify packaged backend starts and exits cleanly.
9. Record EXE path, size, SHA-256, Git HEAD, and build timestamp.

**Exit criteria:** user can open the EXE, login, run the two-stage controlled flow, and view logs/results inside the app.

### Phase 7 - V1.0 Release Acceptance

**Goal:** Cut the first customer-usable controlled production release.

1. Run backend focused tests.
2. Run full frontend build.
3. Run desktop package verification.
4. Run one fresh real two-stage canary from the same release build.
5. Run final delivery check.
6. Update quick-start, recovery guide, known limitations, and final acceptance record.
7. Merge and push only after all acceptance evidence is attached.

**Exit criteria:** source, package, docs, and evidence all describe the same release and the same supported scope.

Each version or phase must be committed separately. UI and browser changes require live browser verification. Real DXM changes require real evidence, not mocked success.

## 6. Current Next Action

Continue with Phase 1, but do not spend another cycle on blind Stage A retries. The current evidence from tasks `#10`, `#11`, `#12`, and the later real attempts `#25` through `#37` proves the next engineering item is the persistent visible Browser Agent runtime:

1. Keep the current timeout/recovery/start-guard hardening.
2. Implement V0.9.10: one persistent visible Browser Agent with one Playwright owner, structured Chinese step events, browser HUD reinjection, manual takeover, reset, and clean shutdown.
3. Route `claim_only` Stage A through that Browser Agent.
4. Re-run Stage A canary from a real existing claimable-product row only after the Browser Agent remains visible and healthy through login and claimable-list navigation.
5. Confirm the claimed product appears in the collection box and is recorded as `dxm_data_acquisition`.
6. Only after Stage A has real claim evidence, run the Stage B save-only canary.
7. Update this plan and the acceptance report with exact evidence paths.

Recommended subagent split for implementation continues to be:

- Browser Agent agent: persistent visible browser worker, command/event protocol, health/reset/manual takeover, and HUD reinjection.
- Backend automation agent: real existing-product claim and collection-box verification on top of the Browser Agent.
- Backend save agent: collection-box product edit/save-only path on top of the Browser Agent.
- Frontend UX agent: menu/page simplification, two-stage navigation, template center, and user-readable recovery.
- Reviewer/main agent: contract tests, live browser verification, release boundary review, and final packaging evidence.

## 7. Self-Review

**Spec coverage:** This plan covers the corrected two-stage workflow, production UI/menu structure, multi-template configuration, visible browser, persistent HUD, customer-readable failures, portable EXE, and final real canary.

**Placeholder scan:** No task is left as TBD; every milestone has scope, files, commands, and exit criteria.

**Boundary check:** Publish, batch, and unattended writes remain excluded through V1.0 and are only introduced as later separately approved versions.
