# DXM Mature Self-Service Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DXM Agent Console 做成普通运营用户能自助完成“真实店小秘单商品只保存”的生产级桌面产品。

**Architecture:** 保持 React/Vite/Electron/FastAPI/Playwright 架构，产品入口收敛为一个免安装 EXE，一个主控制台，一个可见真实店小秘浏览器。主窗口只承载任务决策、配置、接管和结果；工程诊断、门禁证据、日志路径、run-id 统一下沉到诊断抽屉和系统设置。真实浏览器内通过中文 HUD 显示 Agent 当前进度，确保用户知道系统正在做什么、卡在哪里、下一步如何恢复。

**Tech Stack:** React 18 + TypeScript + Vite, Electron portable desktop, FastAPI backend, Playwright headed browser automation, pytest contract tests, PowerShell package and browser QA.

---

## 1. Product Contract

### 1.1 交付范围

- 交付：单商品、真实店小秘、只点击保存、不发布。
- 不交付：发布、批量保存、无人值守、绕过验证码、绕过店小秘人工确认。
- 产品定位：DXM 单商品只保存 Agent，不是测试台、诊断台、截图演示工具。
- 执行模式：控制台 Agent + 可见真实浏览器。主窗口不伪造浏览器画面，截图只作为证据和诊断。

### 1.2 完成判定

项目算完成必须同时满足：

1. 用户双击免安装 EXE 后只看到一个 DXM Agent Console 主窗口。
2. 主窗口能指导用户完成：登录店小秘、选择商品、填写配置、运行检查、人工确认、启动只保存、查看结果。
3. 用户能明确知道当前控制权在谁手里：用户、Agent、系统等待确认。
4. 店小秘浏览器显式打开，并在左上角显示中文任务进度 HUD。
5. 账号密码可本机加密记住，重启后能自动填入。
6. 配置中心能回答：当前模板是谁、是否已保存、执行会使用哪些值。
7. 失败页不暴露工程异常作为主文案，而是给出“发生了什么 / 为什么阻断 / 下一步怎么做”。
8. 发布、批量、无人值守入口在 UI 和 API 两层均被阻断。
9. 最终验收通过后，输出明确 EXE 路径和验收证据。

## 2. Information Architecture

### 2.1 侧边栏目标结构

侧边栏不再按技术模块拆，而按用户工作流拆：

```text
今日任务
登录店小秘
选择商品
填写编辑页
开始只保存
保存结果
问题处理
使用帮助
系统设置
```

### 2.2 页面职责

```text
今日任务
  只回答：当前该做什么、为什么、点哪里。

登录店小秘
  账号密码、本机记住、打开真实登录页、检测登录状态、验证码完成后的恢复。

选择商品
  商品来源、店铺、类目、任务创建、历史任务恢复。

填写编辑页
  店小秘编辑页配置，分区编辑、模板选择、执行取值预览。

开始只保存
  运行前检查、人工确认、启动 Agent 执行浏览器。

保存结果
  保存成功了吗、有没有发布、保存证据、商品、时间、下一步。

问题处理
  所有失败的用户恢复动作。

使用帮助
  第一次使用、日常使用、常见问题。

系统设置
  日志、端口、服务、诊断、证据路径、维护信息。
```

### 2.3 默认界面禁用词

普通用户默认路径不显示：

```text
L2
L3
probe
HAR
run-id
greenlet
Playwright Sync API
Cannot switch to a different thread
network_save_result
published=false proof
```

这些词只允许出现在：

- 状态详情折叠区。
- 系统设置。
- 证据归档。
- 维护人员技术细节。

## 3. File-Level Work Plan

### Task 1: Lock Product Scope And Safety Gates

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_delivery_workspace.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_frontend_demo_workflow_contract.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\scripts\qa-browser-check.ps1`

- [ ] Add backend tests asserting `realDxmMutationScope == controlled_single_save_only`.
- [ ] Add backend tests asserting publish, batch, unattended, `claim_only`, and `batch_save` creation or start requests return blocked status.
- [ ] Add frontend contract tests asserting those modes do not appear as clickable user actions.
- [ ] Add QA script assertions that no visible button contains `发布`, `批量保存`, or `无人值守启动`.
- [ ] Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_frontend_demo_workflow_contract.py -q
```

**Expected:** all pass. Any failure blocks UI work.

### Task 2: Rebuild Sidebar And Route Boundaries

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\types.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\AppShell.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\App.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] Replace current sidebar labels with the 9 user-facing entries from section 2.1.
- [ ] Keep detailed config subsections inside `填写编辑页`, not in the primary sidebar.
- [ ] Keep evidence and diagnostics reachable from result/system pages, not as first-level working steps.
- [ ] Add collapsed sidebar tooltips and `aria-label` values matching full menu names.
- [ ] Add route aliases so existing internal links do not break:

```ts
const sectionAliases = {
  guide: 'help',
  agent_execution: 'start_save',
  real_browser: 'start_save',
  evidence: 'results',
  issues: 'issues',
}
```

- [ ] Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
```

**Expected:** contract confirms the sidebar reads like a product workflow.

### Task 3: Redesign Top Status Bar

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\SafetyStatusBar.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\styles.css`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] Make the top bar one-line by default.
- [ ] Show only:

```text
当前步骤
只保存，不发布
主按钮
一个阻断原因
状态详情
刷新
```

- [ ] Move full gate text, evidence counts, path, run-id, and logs into `状态详情`.
- [ ] Ensure top bar height stays under 72px at 1365x768.
- [ ] Ensure the main action panel appears above the fold.

**Expected first screen:** 用户不用滚动就能看到“现在做什么”和主按钮。

### Task 4: Rebuild Main Window By Menu Page

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\HomePage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\DxmAccessPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\ProductTaskPanels.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\WorkbenchModules.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\ResultsPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\IssuesPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\styles.css`

- [ ] `今日任务`: one primary card with current action, blocker, next click.
- [ ] `登录店小秘`: login credentials, remember checkbox, login state, open login page, detect login.
- [ ] `选择商品`: product/store selection, create one single-save task, history task recovery.
- [ ] `填写编辑页`: focused config section plus template state and execution value preview.
- [ ] `开始只保存`: precheck, manual approval, launch real browser, manual takeover.
- [ ] `保存结果`: success/fail summary first, evidence second.
- [ ] `问题处理`: recoverable issue cards.
- [ ] `使用帮助`: first-use guide and daily-use guide.
- [ ] `系统设置`: service status, logs, diagnostics, evidence paths.

**Layout rule:** no page may show more than one primary decision at the top.

### Task 5: Configuration Center As Execution Brief

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\WorkbenchModules.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\workbenchCopy.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_config_defaults.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_config_validation.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] Add a sticky compact header:

```text
当前使用模板
保存状态
执行会使用这些值
```

- [ ] Support three clear actions per editable section:

```text
仅本次任务使用
保存为店铺模板
套用默认测试模板
```

- [ ] Default template selector must say `请选择要套用的模板` when no saved template is available.
- [ ] Default test template must be visibly labeled as example/test data.
- [ ] Every edited field must show source:

```text
来自当前任务
来自店铺模板
来自默认测试模板
未填写
```

- [ ] Advanced template match explanation goes under collapsed `字段来源详情`.

**Expected:** 用户知道“我填的内容是否保存了，启动 Agent 时会不会用它”。

### Task 6: Visible Browser And Chinese HUD

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\src\services\agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\src\execution\v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_v1_runner.py`

- [ ] Maintain a visible headed browser for real DXM operation.
- [ ] Inject a top-left non-blocking HUD into the real DXM page.
- [ ] Use canonical Chinese progress steps:

```text
开始任务
打开草稿箱
查找商品
打开编辑页
输入标题
选择分类
填写价格库存
处理图片
设置包装物流
点击保存
确认未发布
任务完成
```

- [ ] HUD must show:

```text
当前步骤
进度 3/12
正在做什么
下一步
只保存不发布
```

- [ ] HUD must use `pointer-events: none` so it does not block店小秘操作.
- [ ] If login captcha or human check appears, HUD switches to `等待人工处理`.

**Expected:** 用户看真实浏览器就能判断 Agent 正在做什么。

### Task 7: Login And Credential Memory

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\DxmAccessPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\desktop\src\main.cjs`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_desktop_package_contract.py`

- [ ] Store account/password only through Electron local encrypted storage.
- [ ] Show saved state:

```text
账号密码已保存到本机加密存储
下次打开会自动填入
只保存在当前 Windows 用户
```

- [ ] Login page state must show:

```text
DXM 已登录
等待验证码
登录未通过
真实浏览器停留在 ...
```

- [ ] Login detection must prefer the visible DXM browser session before fallback probing.

**Expected:** 用户登录后主窗口不再误判“登录未通过”。

### Task 8: Error Recovery And Issue Language

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\workbenchCopy.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\IssuesPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\ResultsPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_frontend_api_error_contract.py`

- [ ] Map `greenlet` and thread errors to `浏览器会话异常`.
- [ ] Map readonly/precheck failures to `运行前检查未通过`.
- [ ] Map missing save evidence to `保存结果证据不完整`.
- [ ] Every issue card must contain:

```text
发生了什么
为什么不能继续
下一步
```

- [ ] Raw technical details go into `维护人员查看技术细节`.

**Expected:** 用户可以根据页面恢复，不需要理解异常栈。

### Task 9: Logs And Diagnostics Downshift

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\WorkbenchModules.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\components\workbench\SystemSettingsPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\frontend\src\styles.css`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] Default working pages show only latest 5-10 important log lines.
- [ ] Full log source, path, filter, raw count, and JSON go into `系统设置`.
- [ ] Main pages may show:

```text
最近日志
正在实时刷新
查看完整日志
```

- [ ] Main pages must not show:

```text
400 条
日志路径
run-id
完整 JSON
```

**Expected:** 日志支持排错，但不压过主操作。

### Task 10: Desktop No-Install Delivery

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\desktop\src\main.cjs`
- Modify: `D:\Desktop\py\dxm-auto-uikit\scripts\verify-desktop-package.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\scripts\final-delivery-check.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\app\backend\tests\test_desktop_package_contract.py`

- [ ] EXE startup must not require visible backend/frontend terminal windows.
- [ ] Old process/port conflict must show user-readable recovery.
- [ ] `file://` Electron mode must not be reported as frontend abnormal.
- [ ] Build portable:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\desktop
npm run build:portable
```

- [ ] Copy final artifact:

```powershell
Copy-Item -Force `
  D:\Desktop\py\dxm-auto-uikit\outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe `
  D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
```

**Expected:** 用户只需要打开 `D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe`。

### Task 11: Browser-Backed Acceptance

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\scripts\qa-browser-check.ps1`
- Output: `D:\Desktop\py\dxm-auto-uikit\outputs\browser-checks\production-self-service-ux\qa-browser-check.json`

- [ ] Run frontend build:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

- [ ] Run backend focused tests:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_frontend_demo_workflow_contract.py tests\test_frontend_api_error_contract.py tests\test_agent_console.py tests\test_v1_runner.py tests\test_desktop_package_contract.py tests\test_config_defaults.py tests\test_config_validation.py -q
```

- [ ] Run browser QA:

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1 -OutDir outputs\browser-checks\production-self-service-ux
```

- [ ] Run desktop package verification:

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

- [ ] Run final delivery check:

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\final-delivery-check.ps1 -ExpectedRealDxmWriteReadiness READY -CheckPortableDesktop
```

**Expected final state:**

```text
frontend build: pass
backend tests: pass
browser QA: ok=true
desktop package: pass
realDxmWriteReadiness: READY
realDxmMutationScope: controlled_single_save_only
batchUnattendedPublishAllowed: false
```

### Task 12: User Documentation

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\README.md`
- Modify: `D:\Desktop\py\dxm-auto-uikit\docs\product\用户交付使用说明-20260526.md`
- Modify: `D:\Desktop\py\dxm-auto-uikit\docs\product\交付状态报告-20260525.md`

- [ ] README first screen shows EXE path and 7-step use flow.
- [ ] User guide explains:

```text
这是什么
第一次怎么用
每天怎么用
它不会做什么
失败怎么恢复
证据怎么看
```

- [ ] Delivery report lists exact verification commands and artifact paths.
- [ ] Docs must not claim publish, batch, or unattended are released.

## 4. Subagent Plan

Use short-lived subagents only, close each after its task:

1. **IA/UI subagent:** Task 2, Task 3, Task 4.
2. **Config subagent:** Task 5.
3. **Browser/HUD subagent:** Task 6, Task 7 login-state review.
4. **Error/contract subagent:** Task 1, Task 8, Task 9.
5. **Package QA subagent:** Task 10, Task 11.
6. **Docs subagent:** Task 12.

Main agent controls:

- Scope gate.
- Code review.
- Browser verification.
- Final package copy.
- Final completion decision.

## 5. Product Acceptance Checklist

Before saying “完成”, verify all items:

- [x] EXE opens without backend/frontend terminal windows.
- [x] Sidebar has user workflow labels, not technical labels.
- [x] First screen shows one current action and one main button.
- [x] Login account/password memory works locally.
- [x] User can open visible DXM browser.
- [x] Login success is detected from visible browser session.
- [x] Configuration page shows template, save state, and execution values.
- [x] Real browser HUD shows Chinese progress.
- [x] Precheck passes and refreshes gate state.
- [x] Single-save can proceed only after manual confirmation.
- [x] Save result page shows saved/not published in user language.
- [x] Issue page gives recovery instructions.
- [x] Publish/batch/unattended have no UI entry.
- [x] Backend rejects publish/batch/unattended requests.
- [x] Browser QA has no failed requests, console errors, or overflow.
- [x] Final delivery check passes with READY for controlled single-save only.

## 6. Risk Register

1. **DXM page structure changes.**
   Mitigation: selector tests, source URL matching, browser QA, visible HUD failure state.

2. **Login state mismatch.**
   Mitigation: visible browser session check first, fallback probe second, user recovery copy.

3. **User confuses test template with production template.**
   Mitigation: label default data as test/example, require confirmation before execution.

4. **Technical readiness text overwhelms users.**
   Mitigation: default hide engineering fields, only expose in diagnostics.

5. **Real save evidence incomplete even when DXM saved.**
   Mitigation: result page explains evidence gap, allows recreate task, keeps raw evidence in diagnostics.

6. **Portable package differs from dev mode.**
   Mitigation: verify packaged EXE and portable EXE, not just local dev server.

## 7. Execution Order

1. Task 1: safety gates.
2. Task 2: sidebar and routes.
3. Task 3: top bar.
4. Task 4: main window pages.
5. Task 5: configuration center.
6. Task 6: real browser HUD.
7. Task 7: login and credentials.
8. Task 8: error recovery.
9. Task 9: diagnostics downshift.
10. Task 10: desktop package.
11. Task 11: browser-backed acceptance.
12. Task 12: docs and handoff.

Do not rebuild and deliver the EXE until Task 1-9 tests and frontend build pass.

## 8. 2026-06-22 Execution Evidence

This run completed the production self-service UX pass for controlled single-product save-only.

### Verified Scope

- Released path: controlled `single_save` only.
- Blocked paths: publish, batch save, unattended operation, `claim_only`, `batch_save`.
- Desktop deliverable: `D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe`.
- Portable exe SHA256: `24319C572777C40D9B1C3B2D46CD8582859ED0FE834EE204E1FAC51C5E15FFA4`.

### Verification Commands And Results

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_frontend_demo_workflow_contract.py tests\test_frontend_api_error_contract.py tests\test_agent_console.py tests\test_v1_runner.py tests\test_desktop_package_contract.py tests\test_config_defaults.py tests\test_config_validation.py -q
# 310 passed
```

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
# PASS
```

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1 -Url "http://127.0.0.1:4173/?apiBase=http://127.0.0.1:8000" -OutDir outputs\browser-checks\production-self-service-ux
# ok=true
```

```powershell
$tmp='D:\Desktop\py\dxm-auto-uikit\.tmp\final-check-run'
$env:TEMP=$tmp; $env:TMP=$tmp
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\final-delivery-check.ps1 -ExpectedRealDxmWriteReadiness READY -CheckPortableDesktop
# PASS
# Backend pytest: 678 passed
# Frontend production build: PASS
# Desktop production build: PASS
# Packaged desktop smoke: PASS
# Browser workbench QA: PASS
# Final report center QA: PASS
# realDxmWriteReadiness: READY
# realDxmMutationScope: controlled_single_save_only
# batchUnattendedPublishAllowed: false
```

### Evidence Artifacts

- Final delivery report: `D:\Desktop\py\dxm-auto-uikit\outputs\final-delivery-check\final-delivery-check.md`.
- Final delivery JSON: `D:\Desktop\py\dxm-auto-uikit\outputs\final-delivery-check\final-delivery-check.json`.
- Browser QA JSON: `D:\Desktop\py\dxm-auto-uikit\outputs\final-delivery-check\browser-checks\qa-browser-check.json`.
- Final report QA JSON: `D:\Desktop\py\dxm-auto-uikit\outputs\final-delivery-check\browser-checks\qa-final-report-check.json`.
- Desktop smoke screenshot: `D:\Desktop\py\dxm-auto-uikit\outputs\final-delivery-check\packaged-desktop-smoke.png`.
- Portable smoke screenshot: `D:\Desktop\py\dxm-auto-uikit\outputs\final-delivery-check\portable-desktop-smoke.png`.

### Notes

- `sourcePackageReadiness` remains `DIRTY` because the working tree contains this delivery work and generated artifacts; final delivery check was intentionally run with clean worktree not required.
- The final user-facing delivery state is `local_workbench_and_controlled_single_save_ready`, not publish/batch/unattended production release.
