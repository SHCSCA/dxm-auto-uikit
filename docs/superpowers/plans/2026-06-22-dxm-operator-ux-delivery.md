# DXM Operator UX Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current DXM Agent Console from a diagnostic-heavy workbench into a normal-operator console for real-browser single-product save-only work.

**Architecture:** Keep the existing React/Vite/Electron architecture. Move technical concepts into system/diagnostic surfaces, and make the main sidebar and first-screen pages use operator language. Preserve controlled `single_save` only; publish, batch, and unattended writes remain blocked.

**Tech Stack:** React, TypeScript, Vite, Electron, Python backend contract tests, Playwright/browser QA scripts.

---

### Task 1: Split Help From System Settings

**Files:**
- Modify: `app/frontend/src/types.ts`
- Modify: `app/frontend/src/components/AppShell.tsx`
- Modify: `app/frontend/src/App.tsx`
- Create: `app/frontend/src/components/workbench/HelpPage.tsx`
- Modify: `app/frontend/src/components/workbench/SystemSettingsPage.tsx`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add a `help` workbench section**

Add `help` to the `WorkbenchSection` union, and map the legacy `guide` alias to `help`.

- [x] **Step 2: Split sidebar entries**

Change the final sidebar group from one mixed `帮助与设置` item into two entries:

```tsx
{ id: 'help', label: '使用帮助', short: '帮', hint: '按步骤查看首次使用、日常只保存和失败恢复' },
{ id: 'settings', label: '系统设置', short: '设', hint: '查看服务状态、日志路径和高级诊断' },
```

- [x] **Step 3: Create the operator help page**

Create a first-screen guide that answers only operator questions:

```text
第一次使用怎么走
每次只保存怎么走
失败后先看哪里
系统不会做什么
```

The page must not expose `L2`, `HAR`, `run-id`, or probe language in the default help content.

- [x] **Step 4: Rename the settings page**

Rename visible copy from `帮助与设置` to `系统设置`, and keep runtime state, log paths, gate details, and advanced diagnostics there.

- [x] **Step 5: Update contract tests**

Update sidebar and extraction tests so they require `使用帮助` and `系统设置` as separate entries.

- [x] **Step 6: Verify**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
```

Expected: the frontend contract suite passes.

### Task 2: Make Main Pages Operator-First

**Files:**
- Modify: `app/frontend/src/components/workbench/HomePage.tsx`
- Modify: `app/frontend/src/components/workbench/DxmAccessPage.tsx`
- Modify: `app/frontend/src/components/workbench/ProductTasksPage.tsx`
- Modify: `app/frontend/src/components/workbench/AgentExecutionPage.tsx`

- [x] **Step 1: Make each page answer one question**

Each page title should map to a user decision:

```text
今天做什么
登录店小秘
选择商品
填写编辑页
开始只保存
```

- [x] **Step 2: Keep one primary action per page**

The first screen should show only the next main button. Secondary diagnostics stay in details/drawers.

- [x] **Step 3: Rewrite blockers into operator language**

Every blocker should follow:

```text
发生了什么
为什么不能继续
下一步点哪里
```

- [x] **Step 4: Verify visually**

Run the app and confirm the first screen is understandable without reading diagnostic details.

Verification completed on 2026-06-22:
- `app/backend/.venv/Scripts/python.exe -m pytest tests/test_frontend_demo_workflow_contract.py tests/test_desktop_package_contract.py::test_execution_console_focus_panel_keeps_primary_summary_small tests/test_desktop_package_contract.py::test_app_shell_presents_agent_console_as_user_first_navigation -q`
- `cd app/frontend && npm run build`
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/qa-browser-check.ps1 -Url http://127.0.0.1:15195`

Result: all focused contract checks, build, and browser QA passed. Completed tasks now route to save results, stale read-only-check errors are hidden and cleared for completed tasks, and task-center quick actions stay visible in the first viewport.

### Task 3: Browser Progress Overlay Maturity

**Files:**
- Modify: `app/backend/src/execution/v1_runner.py`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/backend/tests/test_v1_runner.py`
- Modify: `app/backend/tests/test_agent_console.py`

- [ ] **Step 1: Standardize progress phrases**

Use short operator phrases:

```text
开始任务
打开草稿箱
查找商品
输入标题
选择分类
填写价格库存
处理图片
设置包装物流
点击保存
确认未发布
```

- [ ] **Step 2: Keep the browser overlay visible and non-blocking**

The overlay should sit in the browser top-left, use Chinese progress text, and never cover the DXM main navigation or critical form controls.

- [ ] **Step 3: Verify with browser evidence**

Use DOM/text evidence or a targeted browser screenshot. Do not rely on whole-screen screenshots if the user is using the machine.

### Task 4: Final Portable Delivery Gate

**Files:**
- Modify only if needed: `scripts/final-delivery-check.ps1`
- Modify only if needed: `scripts/verify-desktop-package.ps1`
- Output: portable EXE under the user-facing delivery directory

- [ ] **Step 1: Run backend and frontend gates**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest -q
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

- [ ] **Step 2: Run desktop package gate**

```powershell
cd D:\Desktop\py\dxm-auto-uikit
.\scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY
```

- [ ] **Step 3: Verify user path**

From the portable EXE:

```text
open console
login to DXM in visible browser
run read-only check
create/select one single-save task
start visible browser save-only execution
finish with saved=true and published=false
```

Completion requires current evidence for this path, not only static tests.
