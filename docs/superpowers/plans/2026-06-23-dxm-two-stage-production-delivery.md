# DXM Two-Stage Production Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build DXM Agent Console into a production-grade, customer-usable Windows desktop console for real DXM two-stage automation: collect/claim product into the collection box, then edit that collection-box product and save only.

**Architecture:** Keep the current Electron + React + Vite frontend, Python backend, and Playwright/browser-agent runtime. Split the product into user-facing workflow modules while keeping fail-closed backend gates for publish, batch, and unattended actions.

**Tech Stack:** Electron desktop shell, React/Vite frontend, Python backend, Playwright-controlled visible Chrome/Chromium, pytest contract tests, npm build, portable Windows EXE.

---

## Product Boundary

The product is not a diagnostic workbench and not a local demo. The main customer path must be:

1. Login to DXM in a visible real browser.
2. Stage A: collect and claim a real product from DXM data acquisition into the collection box.
3. Stage B: open that claimed product from the collection box, fill the edit form from a selected template, and click save only.
4. Show a result report proving save success and not published.

Explicitly out of scope until separately released:

- Publish
- Save and publish
- Move to pending publish
- Batch save
- Batch claim
- Unattended publishing
- Local test-product main flow

## Version Roadmap

### V1.0 Production Trial: Single Store, Single Product, Save Only

**Purpose:** A normal operations user can complete one real product from DXM acquisition to collection box to edit-save without developer help.

**Must ship:**

- Visible DXM login browser with saved encrypted local credentials.
- Data acquisition claim task page.
- Collection-box edit-save task page.
- One selected template applied to the edit page.
- Human approval before save.
- Save-only result and not-published proof.
- Portable EXE rebuilt from the current branch.

**Acceptance:**

- User can understand the current step without reading raw logs.
- No `L2`, `L3`, `probe`, `run-id`, `greenlet`, or `Internal Server Error` in the normal path.
- One fresh real DXM end-to-end acceptance run is archived.

### V1.1 Data Acquisition Claim Hardening

**Purpose:** Make the first business stage stable and explainable.

**Must ship:**

- Claim task form: store, platform, acquisition source or keyword, claim mark.
- Browser steps: open data acquisition, locate product, claim into collection box, verify collection-box presence.
- Claim result record: source URL, title, store, platform, claim mark, collection-box title, timestamp, proof path.
- Failure reasons mapped to user actions: not logged in, product not found, permission issue, page changed, manual takeover needed.

**Acceptance:**

- A claimed product becomes selectable in Stage B.
- A failed claim never starts edit-save automatically.
- Claim stage never saves, publishes, or moves product to publish.

### V1.2 Collection-Box Edit Save Hardening

**Purpose:** Make the second business stage reliable and tied to a claimed product.

**Must ship:**

- Save task can only start from a real claimed product record.
- Pre-save confirmation shows product, store, source, selected template, changed sections, and save-only boundary.
- Edit page filling covers the current required DXM sections.
- Save result captures network response or page success text.
- Not-published proof is captured independently from save success.

**Acceptance:**

- Save only can be proven without relying on screenshots alone.
- Publish-like buttons are never clicked.
- If the target product is not from collection box, the user gets a clear recovery path.

### V1.3 Template Center Production UX

**Purpose:** Replace configuration sprawl with reusable customer templates.

**Must ship:**

- Template list with create, copy, rename, delete, enable/disable.
- Store default template and category default template.
- Category default overrides store default.
- Chinese section form: store/task basics, category/title, SKU/price/stock, images/materials, packaging/logistics, compliance/customs, semi-managed, DXM reference template.
- Clear save state: saved, unsaved changes, save failed.
- Execution value preview: task override, selected template, category default, store default, system example.
- System example template clearly marked as example, not customer data.

**Acceptance:**

- User can answer: which template is active, whether it is saved, and which values will be used at execution.
- English field keys are hidden from the normal customer path.

### V1.4 Visible Browser Agent and HUD Stability

**Purpose:** Make automation observable and recoverable instead of black-box execution.

**Must ship:**

- Execution browser stays visible and online during task lifecycle.
- Top-left browser HUD is injected and re-injected after navigation.
- HUD shows Chinese business steps: opening DXM, entering data acquisition, searching product, claiming to collection box, opening edit page, filling title, filling logistics, saving, checking not published.
- Agent crash or browser close becomes a recoverable user-facing state.
- Main window, HUD, logs, and report share the same task state.

**Acceptance:**

- Browser does not disappear after starting the agent unless user closes it.
- HUD does not disappear across DXM page navigation.
- User can manually take over captcha or page correction and continue.

### V1.5 Logs, Problems, and Reports

**Purpose:** Make failures understandable to customers and useful to support staff.

**Must ship:**

- Default log panel shows only 5-10 recent business events.
- Full raw logs move to maintenance details.
- Every failure card has: what happened, why stopped, next step, maintenance details.
- Result page groups: task result, save proof, not-published proof, browser proof, raw diagnostics.
- Repeated identical logs are collapsed.

**Acceptance:**

- Log format does not overlap or flood the page.
- Customer sees recovery buttons before technical text.
- Support staff can still open exact logs and evidence paths.

### V1.6 Portable Customer Delivery

**Purpose:** Ship a customer-runnable Windows package.

**Must ship:**

- One primary EXE entrypoint.
- No separate backend/frontend console windows as user workflow.
- Packaged resources verified.
- Startup checks: writable data dir, resources present, browser runtime present, port conflict resolved or explained.
- Delivery folder includes EXE, resources if required by packaging mode, quick guide, troubleshooting guide, version note, acceptance report.

**Acceptance:**

- Fresh Windows user can launch by double-clicking EXE.
- Current branch is rebuilt and smoke-tested; old portable packages are not reused as proof.
- Real two-stage DXM acceptance is either passed and archived, or release remains marked blocked.

## Target Information Architecture

### Sidebar

Use seven customer-facing entries:

1. 首页
2. 店小秘登录
3. 数据采集认领
4. 采集箱编辑保存
5. 模板中心
6. 执行浏览器
7. 结果与问题

Remove or merge from the normal path:

- Agent 控制台 -> 执行浏览器
- 配置中心 -> 模板中心
- 任务中心 -> 数据采集认领 + 采集箱编辑保存
- 证据中心 -> 结果与问题
- 异常池 -> 结果与问题

### Page Rule

Each page has one primary action:

- 首页: continue next required step.
- 店小秘登录: open/check login.
- 数据采集认领: start claim.
- 采集箱编辑保存: request approval and start save-only.
- 模板中心: save current template.
- 执行浏览器: recover or reconnect browser.
- 结果与问题: view result or retry using guided recovery.

## Implementation Tasks

### Task 1: Lock Two-Stage Task Model

**Files:**
- Modify: `app/backend/src/services/task_start_guard.py`
- Modify: `app/backend/src/execution/v1_runner.py`
- Modify: `app/backend/src/repository.py`
- Modify: `app/frontend/src/workspace.ts`
- Test: `app/backend/tests/test_task_start_guard.py`
- Test: `app/backend/tests/test_acquisition_claim_workflow.py`

- [ ] Add backend contract tests that reject save tasks without a claimed collection-box product.
- [ ] Add backend contract tests that allow a save task created from a successful claim record.
- [ ] Ensure claim task output stores source URL, collection-box title, claim mark, and task id.
- [ ] Ensure save task input references the claim output id, not a local QA product.
- [ ] Run `D:\Desktop\py\dxm-auto-uikit\app\backend\.venv\Scripts\python.exe -m pytest app\backend\tests\test_task_start_guard.py app\backend\tests\test_acquisition_claim_workflow.py -q`.
- [ ] Commit with `feat: enforce two-stage DXM task model`.

### Task 2: Rebuild Sidebar and Main User Path

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/components/workbench/*`
- Modify: `app/frontend/src/workspace.ts`
- Modify: `app/frontend/src/styles.css`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] Add frontend contract assertions for the seven sidebar labels.
- [ ] Remove normal-path labels that expose diagnostic concepts as primary navigation.
- [ ] Move task selection into `数据采集认领` and `采集箱编辑保存`.
- [ ] Ensure each page renders one primary action.
- [ ] Ensure default top status does not include raw gate terms.
- [ ] Run `D:\Desktop\py\dxm-auto-uikit\app\backend\.venv\Scripts\python.exe -m pytest app\backend\tests\test_frontend_demo_workflow_contract.py -q`.
- [ ] Commit with `feat: reorganize DXM console navigation`.

### Task 3: Production Template Center

**Files:**
- Modify: `app/backend/src/services/template_center.py`
- Modify: `app/frontend/src/components/workbench/TemplateCenterPage.tsx`
- Modify: `app/frontend/src/styles.css`
- Test: `app/backend/tests/test_template_center_contract.py`
- Test: `app/backend/tests/test_templates.py`

- [ ] Add tests for store default and category default template resolution.
- [ ] Add tests that category default overrides store default.
- [ ] Add tests that normal UI metadata uses Chinese labels only.
- [ ] Implement template list actions: create, copy, rename, delete, enable/disable, set store default, set category default.
- [ ] Implement section form with one expanded section at a time.
- [ ] Implement execution value preview with source labels.
- [ ] Run `D:\Desktop\py\dxm-auto-uikit\app\backend\.venv\Scripts\python.exe -m pytest app\backend\tests\test_template_center_contract.py app\backend\tests\test_templates.py -q`.
- [ ] Commit with `feat: productionize DXM template center`.

### Task 4: Visible Browser Agent and Persistent HUD

**Files:**
- Modify: `app/backend/src/execution/dxm_login_flow.py`
- Modify: `app/backend/src/execution/v1_runner.py`
- Modify: `app/backend/src/services/browser_agent_status.py`
- Modify: `app/frontend/src/components/workbench/BrowserConsolePage.tsx`
- Test: `app/backend/tests/test_browser_agent_status.py`
- Test: `app/backend/tests/test_agent_console.py`

- [ ] Add tests that browser status remains recoverable when the execution window is closed.
- [ ] Add tests that HUD status maps technical runner steps to Chinese business steps.
- [ ] Add runner events for claim stage and save stage.
- [ ] Re-inject HUD after page navigation and route changes.
- [ ] Keep the execution browser open after failure unless the user explicitly closes it.
- [ ] Run `D:\Desktop\py\dxm-auto-uikit\app\backend\.venv\Scripts\python.exe -m pytest app\backend\tests\test_browser_agent_status.py app\backend\tests\test_agent_console.py -q`.
- [ ] Validate with a real visible DXM browser session before claiming done.
- [ ] Commit with `fix: keep DXM browser agent visible and observable`.

### Task 5: User-Facing Logs and Problem Recovery

**Files:**
- Modify: `app/backend/src/services/operator_log.py`
- Modify: `app/backend/src/services/delivery_workspace.py`
- Modify: `app/frontend/src/components/workbench/ResultAndProblemsPage.tsx`
- Modify: `app/frontend/src/components/workbench/LiveLogPanel.tsx`
- Test: `app/backend/tests/test_delivery_workspace.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] Add tests that raw errors are mapped to customer-facing messages.
- [ ] Add tests that repeated log entries collapse.
- [ ] Add tests that maintenance details are present but collapsed.
- [ ] Implement failure card schema: happened, reason, next_action, maintenance_details.
- [ ] Default live log panel to the latest business events only.
- [ ] Run `D:\Desktop\py\dxm-auto-uikit\app\backend\.venv\Scripts\python.exe -m pytest app\backend\tests\test_delivery_workspace.py app\backend\tests\test_frontend_demo_workflow_contract.py -q`.
- [ ] Commit with `feat: simplify DXM logs and recovery guidance`.

### Task 6: Real DXM Acceptance and Portable Release

**Files:**
- Modify: `docs/product/最终交付验收记录-20260623-桌面包.md`
- Modify: `README.md`
- Modify: `scripts/verify-desktop-package.ps1`
- Output: `D:\Desktop\DXM-Agent-Console-免安装版`

- [ ] Build frontend with `cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend; npm run build`.
- [ ] Build portable with `cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\desktop; npm run build:portable`.
- [ ] Run package verification with `powershell -NoProfile -ExecutionPolicy Bypass -File D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180`.
- [ ] Launch the portable EXE and verify visible browser login.
- [ ] Run Stage A real DXM claim to collection box and archive result.
- [ ] Run Stage B real collection-box edit save-only and archive save/not-published proof.
- [ ] Copy the verified package to `D:\Desktop\DXM-Agent-Console-免安装版`.
- [ ] Write `验收报告.json` with git head, package hash, smoke status, real two-stage status, and mutation boundary.
- [ ] Commit with `docs: record DXM two-stage production acceptance`.

## Completion Definition

The project is complete only when all conditions are true:

1. Fresh real DXM Stage A claim succeeds.
2. Fresh real DXM Stage B edit save-only succeeds using the Stage A claimed product.
3. Save success and not-published proof are archived.
4. Visible browser stays open and HUD stays visible through the task.
5. Customer UI uses user language and hides technical details by default.
6. Template center supports multiple saved templates and clear execution value preview.
7. Publish, save-and-publish, batch, and unattended paths remain blocked in UI and backend.
8. Portable EXE from the current branch is rebuilt and package-smoke verified.
9. Delivery folder contains the verified EXE and customer instructions.
10. Tests and final acceptance command pass from a clean worktree.
