# DXM Agent Console Deliverable UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DXM Agent Console 从“功能堆叠型工作台”改成普通用户可自助使用的生产级真实浏览器自动化控制台：真实打开店小秘、按步骤配置、只读检查、人工确认、Agent 操作真实浏览器只保存、不发布，并能看懂失败原因和下一步。

**Architecture:** 保持现有 React/Vite/Electron/FastAPI/Playwright 架构，不重写技术栈。前端按用户主流程拆成菜单与页面模块，后端继续作为可信门禁和真实浏览器执行引擎；技术证据、L2/L3、run-id、日志路径默认下沉到诊断抽屉。真实浏览器左上角注入黑色任务进度 HUD，用中文显示“开始任务、填写标题、选择分类、点击保存”等业务动作。

**Tech Stack:** React 18 + Vite + TypeScript, Electron portable exe, FastAPI, SQLite, Playwright, pytest, PowerShell delivery checks.

---

## Scope And Release Boundary

- 当前可交付范围只放行 `controlled_single_save_only`：单店、单商品、人工确认、只保存、不发布。
- `claim_only`、`batch_save`、批量、无人值守和任何发布动作继续阻断，不复用 `single_save` 证据扩大解释。
- 控制台必须操控可见真实浏览器；截图只作为报告证据，不作为实时操作替代。
- 普通用户界面默认不展示 `L2/L3/probe/run-id/HAR/hash/greenlet` 等技术概念；这些信息只进入诊断抽屉、系统设置或证据页。
- 免安装版必须能从 exe 直接启动，用户不需要同时管理两个 bat 窗口。

---

## Merged Plan Source Map

本计划合并两条要求，后续实现、验收和汇报只按这一份推进：

| Source | User Requirement | Implemented In |
| --- | --- | --- |
| 可交付体验改造计划 | 修复真实状态误判、Electron `file://` 误报、L2 证据目录不一致 | Task 1 |
| 可交付体验改造计划 | 侧边栏从技术入口改为普通用户业务入口 | Task 2 |
| 可交付体验改造计划 | 配置中心可选模板、可保存、能说明执行取值来源 | Task 5 |
| 可交付体验改造计划 | 执行控制台从诊断台改为 Agent 操控真实浏览器的操作台 | Task 6 |
| 主窗口与浏览器计划 | 主窗口按菜单栏重构，每个菜单只承担一个用户任务 | Task 3 |
| 主窗口与浏览器计划 | 真实浏览器左上角黑色进度窗口，中文实时显示当前动作 | Task 4 |
| 主窗口与浏览器计划 | 技术概念下沉，普通用户只看到“发生什么、为何阻断、下一步点哪里” | Task 6 and Task 7 |
| 交付计划 | 免安装 exe、portable smoke、真实流程和 clean worktree 最终门禁 | Task 9, Task 10, Task 11 |

---

## Current Implementation Snapshot

这些内容在当前工作区已经有未提交改动，需要后续按本计划继续验收和补齐：

- [x] 侧边栏已从技术入口改为业务入口：`首页 / 店小秘接入 / 商品任务 / 编辑页配置 / Agent 执行 / 结果与报告 / 问题处理 / 系统设置`。
- [x] `WorkbenchSection` 已扩展新路由，并兼容旧路由别名。
- [x] `AgentConsoleHud` 已扩展中文进度字段：`human_title`、`human_action`、`human_next`、`recent_actions`、`progress_index`、`progress_total`。
- [x] 真实店小秘页面已规划为左上角黑色 HUD，展示中文业务进度和“只保存不发布”。
- [x] 登录区账号密码已收纳到折叠区，减少首屏拥挤。
- [x] 已新增 `系统设置` 页面承载后端、前端、真实浏览器、日志路径和高级诊断。
- [x] 已通过一轮聚焦测试、前端构建和 portable 构建；仍需最终真实流程与 clean worktree 交付验收。

---

## Target Information Architecture

### Sidebar

| Group | Menu | User Job |
| --- | --- | --- |
| 开始 | 首页 | 看当前能不能继续、下一步做什么 |
| 开始 | 店小秘接入 | 登录真实店小秘、保存账号密码、检测登录状态 |
| 任务 | 商品任务 | 选择商品、创建单商品只保存任务、查看任务状态 |
| 任务 | 编辑页配置 | 按店小秘编辑页分区填写配置、选择模板、确认执行取值 |
| 执行 | Agent 执行 | 运行真实只读检查、人工确认、启动 Agent 执行浏览器 |
| 复盘 | 结果与报告 | 查看保存结果、未发布证明、失败报告 |
| 复盘 | 问题处理 | 查看可处理异常、恢复建议、重新创建任务 |
| 系统 | 系统设置 | 查看技术诊断、日志路径、桌面运行状态、交付门禁 |

### Top Bar

顶部只保留一条决策信息：

- 当前步骤：例如 `继续下一步：登录真实店小秘`。
- 当前权限：例如 `只保存，不发布`。
- 主按钮：例如 `下一步`、`运行只读检查`、`启动 Agent 执行浏览器`。
- 一个阻断原因：例如 `需要先完成真实只读检查`。
- 详细状态进入 `状态详情与技术诊断` 折叠区或右侧抽屉。

### Real Browser HUD

真实店小秘页面左上角显示黑色小窗：

- 标题：`DXM Agent 正在执行`。
- 进度：`4 / 12`。
- 当前动作：`填写标题`、`选择分类`、`上传主图`、`填写 SKU / 价格 / 库存`、`点击保存`。
- 最近动作：最多 3 条，例如 `已打开编辑页`、`已选择分类`、`已填写标题`。
- 下一步：例如 `继续填写半托管信息`。
- 安全标识：`只保存，不发布`。

---

## Main Window Page Contracts

每个菜单页面必须满足下面的页面契约。普通用户默认只看主流程，技术诊断只在折叠区、抽屉、系统设置或证据页出现。

### 首页

- **用户目的:** 一眼判断现在能不能继续，以及下一步点哪里。
- **首屏必须出现:** 当前步骤、主按钮、当前任务、店小秘登录、编辑页配置、真实只读检查、人工确认、最近保存结果。
- **首屏禁止出现:** run-id、HAR、hash、完整日志、Python 异常堆栈、L2/L3 原始术语。
- **主按钮规则:** 按当前阻断状态跳转到 `店小秘接入`、`商品任务`、`编辑页配置` 或 `Agent 执行`。
- **验收:** 1280x720 首屏无需滚动即可看到主按钮和五个业务状态卡。

### 店小秘接入

- **用户目的:** 打开真实店小秘登录浏览器，完成账号密码、验证码和登录检测。
- **首屏必须出现:** 店小秘账号、店小秘密码、记住账号密码、打开真实登录页、验证码已完成检测登录状态。
- **默认收纳:** 本机加密存储细节、桌面日志路径、浏览器 profile 路径。
- **失败文案:** 登录失败必须写成“登录还没完成，请在真实浏览器内完成验证码后再检测”，不能直接暴露 greenlet 或 Playwright API 错误。
- **验收:** 用户登录成功后，状态显示 `DXM 已登录`，不再提示 `login_failed`。

### 商品任务

- **用户目的:** 选择一个商品并创建“单商品只保存”任务。
- **首屏必须出现:** 选择商品、创建单商品只保存任务、当前任务、任务是否草稿、失败后重新创建。
- **默认隐藏:** `claim_only`、`batch_save`、发布、无人值守入口。
- **失败文案:** 非草稿任务必须写成“当前任务已经执行过，请重新创建单商品只保存任务”。
- **验收:** 没选商品时主按钮禁用并说明“请先勾选 1 个商品”。

### 编辑页配置

- **用户目的:** 按店小秘编辑页分区补齐执行会使用的字段。
- **首屏必须出现:** 当前使用模板、保存状态、执行取值、当前最需要补的分区、三个动作按钮。
- **三个动作按钮:** `仅本次任务使用`、`保存为店铺模板`、`套用默认测试模板`。
- **默认收纳:** 模板命中解释、字段映射细节、低频分区。
- **验收:** 用户修改字段后能看到保存状态变化，并能明确知道执行会使用当前表单值。

### Agent 执行

- **用户目的:** 运行真实只读检查，人工确认只保存，然后启动 Agent 操控真实浏览器。
- **首屏必须出现:** 登录状态、真实只读检查状态、人工确认状态、当前任务、当前阻断原因、一个主按钮。
- **默认收纳:** 完整日志、证据路径、run-id、门禁 JSON、网络计数。
- **主按钮规则:** 未过只读检查时显示 `运行真实只读检查`；只读通过但未确认时显示 `人工确认只保存`；全部通过后显示 `启动 Agent 执行浏览器`。
- **验收:** 首屏文案必须说明“控制台操控独立真实浏览器；截图仅用于报告证据”。

### 结果与报告

- **用户目的:** 看保存是否成功、是否仍未发布、证据在哪里。
- **首屏必须出现:** 保存成功/失败、`published=false`、保存接口响应摘要、报告入口、重新处理入口。
- **默认收纳:** HAR 明细、截图文件路径、完整错误堆栈。
- **失败文案:** 默认写“保存没有完成，系统没有拿到保存成功证明”，技术异常进入诊断区。
- **验收:** 失败报告卡片不直接展示 `Cannot switch to a different thread` 这类原始异常。

### 问题处理

- **用户目的:** 根据问题卡恢复流程。
- **首屏必须出现:** 登录失败、只读检查失败、浏览器占用、任务状态不正确、保存未完成等问题卡。
- **每张卡必须包含:** 发生了什么、为什么阻断、下一步点哪里。
- **默认收纳:** 原始日志、backend traceback、证据 JSON。
- **验收:** 用户不需要理解 L2/probe/run-id，也能知道下一步操作。

### 系统设置

- **用户目的:** 查看运行环境和高级诊断。
- **首屏必须出现:** 后端状态、桌面页面状态、真实浏览器状态、日志路径、portable 版本。
- **允许出现:** `L2/L3`、run-id、路径、门禁状态、技术诊断。
- **验收:** 技术概念只能默认出现在这里或诊断抽屉，不在普通页面抢占首屏。

---

## Subagent Work Split

主代理负责方向、审查、验收和合并；子代理只处理边界清晰的模块，完成后关闭。

| Agent Lane | Responsibility | Inputs | Output |
| --- | --- | --- | --- |
| Backend gate lane | L2/L3 状态可信、登录状态、错误映射、真实浏览器 HUD 数据 | `delivery_workspace.py`, `main.py`, `agent_console.py`, `v1_runner.py` | 通过 pytest 的状态与门禁契约 |
| Frontend shell lane | 侧边栏、首页、顶部状态条、系统设置 | `App.tsx`, `AppShell.tsx`, `SafetyStatusBar.tsx`, `styles.css` | 首屏清晰的业务导航 |
| Config lane | 编辑页配置、模板管理、执行取值说明 | `WorkbenchModules.tsx`, `config_preview.py`, `config_defaults.py` | 用户可选模板、可保存、可理解执行值 |
| Execution lane | Agent 执行页、问题处理、报告与证据 | `WorkbenchModules.tsx`, `agent_console.py`, tests | 可恢复的真实浏览器执行流程 |
| Delivery lane | portable exe、文档、final gate | `app/desktop`, `scripts`, `README.md`, `docs/product` | 可交付免安装包和验收记录 |

---

## File Structure

### Backend

- Modify `app/backend/src/models.py`: `AgentConsoleStep`/HUD 字段定义。
- Modify `app/backend/src/services/agent_console.py`: HUD 状态持久化、最近动作、左上角黑色 HUD 注入、浏览器会话生命周期。
- Modify `app/backend/src/execution/v1_runner.py`: 每个真实执行步骤上报中文业务动作。
- Modify `app/backend/src/services/delivery_workspace.py`: L2/L3 门禁状态、桌面数据目录读取、误报发布风险处理。
- Modify `app/backend/src/main.py`: runtime status、Electron `file://` 状态、真实只读检查启动/占用提示、登录态检测提示。
- Test `app/backend/tests/test_agent_console.py`
- Test `app/backend/tests/test_v1_runner.py`
- Test `app/backend/tests/test_delivery_workspace.py`
- Test `app/backend/tests/test_frontend_demo_workflow_contract.py`

### Frontend

- Modify `app/frontend/src/types.ts`: 新菜单路由、HUD 类型、运行态类型。
- Modify `app/frontend/src/App.tsx`: 路由归一、主按钮状态、登录/只读/人工确认/执行流程状态。
- Modify `app/frontend/src/components/AppShell.tsx`: 侧边栏菜单、分组、折叠态可读性。
- Modify `app/frontend/src/components/WorkbenchModules.tsx`: 当前大模块继续承载页面逻辑，后续按任务拆分。
- Modify `app/frontend/src/components/SafetyStatusBar.tsx`: 顶部决策条文案与详细诊断折叠。
- Modify `app/frontend/src/styles.css`: 字号、密度、抽屉、HUD 状态、页面布局。
- Create during Task 8: `app/frontend/src/components/workbench/HomePage.tsx`
- Create during Task 8: `app/frontend/src/components/workbench/DxmAccessPage.tsx`
- Create during Task 8: `app/frontend/src/components/workbench/ProductTasksPage.tsx`
- Create during Task 8: `app/frontend/src/components/workbench/EditConfigPage.tsx`
- Create during Task 8: `app/frontend/src/components/workbench/AgentExecutionPage.tsx`
- Create during Task 8: `app/frontend/src/components/workbench/ResultsPage.tsx`
- Create during Task 8: `app/frontend/src/components/workbench/IssuesPage.tsx`
- Create during Task 8: `app/frontend/src/components/workbench/SystemSettingsPage.tsx`

### Desktop And Delivery

- Modify `app/desktop/src/main.js`: 免安装版启动、后台服务、日志、可见真实浏览器策略。
- Modify `app/desktop/src/preload.js`: 账号密码本机加密存储、runtime info。
- Modify `scripts/verify-desktop-package.ps1`: portable exe smoke、日志、真实浏览器窗口 smoke。
- Modify `scripts/final-delivery-check.ps1`: clean worktree、portable、READY 范围验收。
- Modify `README.md`: 新菜单、新使用流程、新 exe 路径。
- Modify `docs/product/用户交付使用说明-20260526.md`: 普通用户操作说明。

---

## Task 1: P0 Status Trust And Gate Accuracy

**Files:**
- Modify: `app/backend/src/services/delivery_workspace.py`
- Modify: `app/backend/src/main.py`
- Test: `app/backend/tests/test_delivery_workspace.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Write L2 desktop data-dir test**

Add a test that creates valid L2 readonly results under desktop runtime `DATA_DIR/l2_readonly_probe` and asserts `/api/delivery/workspace` reports L2 passed.

- [x] **Step 2: Implement desktop-first L2 evidence lookup**

Read L2 evidence from runtime `DATA_DIR/l2_readonly_probe` first, then fall back to repository `data/l2_readonly_probe` for legacy evidence.

- [x] **Step 3: Fix Electron file frontend status**

When frontend runs as `file://`, runtime status should say `桌面内置页面` or equivalent healthy desktop state, not `前端异常`.

- [ ] **Step 4: Verify stale and unsafe cases still block**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py -q
```

Expected:

```text
passed
```

- [ ] **Step 5: User-facing acceptance**

After a successful real readonly check, the UI must show:

```text
真实只读检查通过
```

It must not show:

```text
真实只读检查：未运行
前端：异常
```

---

## Task 2: Sidebar And Main Window Routing

**Files:**
- Modify: `app/frontend/src/types.ts`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/frontend/src/components/AppShell.tsx`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Define new route ids**

Use these route ids:

```ts
export type WorkbenchSection =
  | 'home'
  | 'dxm_access'
  | 'product_tasks'
  | 'edit_config'
  | 'agent_execution'
  | 'results'
  | 'issues'
  | 'settings'
```

Keep old route aliases only for compatibility.

- [x] **Step 2: Normalize old routes**

In `App.tsx`, map old ids to new pages:

```ts
dashboard -> home
guide -> dxm_access
tasks -> product_tasks
config -> edit_config
console -> agent_execution
reports -> results
exceptions -> issues
```

- [x] **Step 3: Render grouped sidebar**

`AppShell.tsx` should show full business labels, not one-character technical labels:

```text
首页
店小秘接入
商品任务
编辑页配置
Agent 执行
结果与报告
问题处理
系统设置
```

- [x] **Step 4: Tighten sidebar density**

Set sidebar item height, font size, and group spacing so a normal 1080p screen shows all menu items without scrolling.

- [x] **Step 5: Verify**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py::test_workbench_sidebar_uses_business_navigation -q
```

Expected:

```text
1 passed
```

---

## Task 3: Main Window Rebuild By Menu

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/components/SafetyStatusBar.tsx`
- Modify: `app/frontend/src/styles.css`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Home page becomes one-screen command center**

`首页` first viewport should show:

```text
当前能做什么
下一步
当前任务
店小秘登录状态
真实只读检查状态
```

Do not show full logs, run-id, HAR, hash, or evidence paths in the first viewport.

- [x] **Step 2: Dxm access page only handles login**

`店小秘接入` first viewport should show:

```text
登录真实店小秘
账号
密码
记住账号密码
打开真实登录页
验证码已完成，检测登录状态
```

Account/password storage details stay in a compact status row or folded help.

- [x] **Step 3: Product tasks page only handles task selection**

`商品任务` first viewport should show:

```text
选择商品
创建单商品只保存任务
当前任务
任务为什么不能启动
```

Batch, claim, publish remain hidden or disabled with clear explanation.

Verified on 2026-06-17:
- `tests/test_frontend_demo_workflow_contract.py` passed with `159 passed`.
- `npm run build` passed.
- In-app browser check at `http://127.0.0.1:5175/` confirmed the `商品任务` first viewport shows `选择商品`, store selection, `创建单商品只保存任务`, and actionable disabled reason; extra task/product drawers remain collapsed. Backend was disconnected during the visual check, so product count was `0`, but the first-screen structure and no-batch-copy contract were verified.

- [x] **Step 4: Edit config page only handles configuration**

`编辑页配置` first viewport should show:

```text
当前使用模板
是否已保存
执行会使用哪些值
当前最需要补的分区
```

Template matching trace and advanced mappings are folded.

- [x] **Step 5: Agent execution page only handles real browser execution**

`Agent 执行` first viewport should show:

```text
登录状态
真实只读检查
人工确认只保存
启动 Agent 执行浏览器
```

Logs and diagnostics move to right drawer / folding panels.

Verified on 2026-06-17:
- Root cause for the `Agent 执行` blank page was found with `npm exec tsc -- --noEmit`: `ConsoleFocusPanel` rendered `l2Gate` / `l3Gate` without destructuring them from props, causing a runtime `ReferenceError` and React root unmount when the page was opened.
- Fixed the missing destructuring and added a safe login-state fallback on the DXM access status card.
- `app/frontend/package.json` now runs `tsc --noEmit` before `vite build`, so this class of TypeScript runtime error fails the delivery build.
- `tests/test_frontend_demo_workflow_contract.py` passed with `159 passed`.
- `npm run build` passed with the new typecheck gate.
- In-app browser production preview at `http://127.0.0.1:4185/` confirmed clicking `Agent 执行` no longer blanks `#root`; `.console-focus-panel` and `.console-focus-panel__status-strip` render.

- [x] **Step 6: Results and issues split**

`结果与报告` shows success/failure summary and evidence entry. `问题处理` shows recoverable problems and next action. Do not mix raw Python exception text into the main card.

- [x] **Step 7: Verify first-viewport density**

Use browser verification at `http://127.0.0.1:5175/` or the current dev URL. The first viewport should not require scrolling to find the page’s primary action.

Verified on 2026-06-17 against production preview `http://127.0.0.1:4185/` at 1280x720:
- Primary blocker action button bottom: `534px`.
- Status strip bottom: `634px`.
- Secondary check-plan button bottom: `702px`.
- All diagnostic `<details>` in the first viewport were collapsed.
- Backend was intentionally disconnected during this UI-only verification, so the visible blocker was `后端未连接`; the Agent page layout itself remained usable and nonblank.

---

## Task 4: Real Browser Chinese Progress HUD

**Files:**
- Modify: `app/backend/src/models.py`
- Modify: `app/backend/src/services/agent_console.py`
- Modify: `app/backend/src/execution/v1_runner.py`
- Test: `app/backend/tests/test_agent_console.py`
- Test: `app/backend/tests/test_v1_runner.py`

- [x] **Step 1: Extend HUD data model**

`AgentConsoleHud` should include:

```ts
phase?: string
progress_index?: number
progress_total?: number
severity?: string
human_title?: string
human_action?: string
human_next?: string
recent_actions?: string[]
requires_user_action?: boolean
```

- [x] **Step 2: Map runner states to Chinese business actions**

Example state copy:

```text
PRECHECK_CONFIG -> 检查任务配置
PRECHECK_SESSION -> 检查店小秘登录
FILL_BASE_INFO -> 填写标题和基础信息
FILL_VARIANTS -> 填写 SKU / 价格 / 库存
FILL_COMPLIANCE -> 填写合规 / 海关
FILL_SEMI_GOODS -> 填写半托管信息
SAVE_ONLY -> 点击保存
RELEASE_LOCK -> 完成任务
```

- [x] **Step 3: Inject black top-left HUD**

The HUD must render in the real 店小秘 browser page, not only inside the console. It should be black, compact, top-left, and not cover the main edit form more than necessary.

- [x] **Step 4: Add user action states**

When the flow requires user action, HUD should show:

```text
需要你处理验证码
需要你人工确认只保存
需要你接管真实浏览器
```

Verified on 2026-06-17:
- Added backend HUD normalization for `WAITING_CAPTCHA`, `MANUAL_APPROVAL_REQUIRED`, and `MANUAL_TAKEOVER`.
- `request_manual_takeover()` now updates HUD to `需要你接管真实浏览器` and marks `requires_user_action=true`; `release_manual_takeover()` clears the user-action state.
- `tests/test_agent_console.py` passed with `28 passed`.

- [ ] **Step 5: Verify with real browser**

Start a visible real DXM browser and confirm the overlay appears on `dianxiaomi.com/web/home` or the edit page. Use actual browser verification, not static code inspection.

---

## Task 5: Configuration Center Production UX

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/styles.css`
- Modify: `app/backend/src/services/config_preview.py`
- Modify: `app/backend/src/services/config_defaults.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Show default test template as explicit template**

The UI must expose the old test data as:

```text
默认测试模板
```

It must be selectable and visibly marked as example/test data.

- [x] **Step 2: Show current template and save state**

Top of `编辑页配置` must show:

```text
当前模板：默认测试模板 / 店铺模板 / 本次任务覆盖
保存状态：已保存 / 有未保存修改
执行取值：将使用当前表单值
```

- [x] **Step 3: Split by 店小秘编辑页分区**

Use these visible sections:

```text
店铺与任务基础
类目与标题
SKU / 价格 / 库存
价格策略
图片与素材
包装物流
合规 / 海关
半托管
店小秘引用模板
```

- [x] **Step 4: Only expand the current needed section**

If required fields are missing, expand the first missing section. Collapse low-frequency sections under `更多编辑页分区`.

- [x] **Step 5: Add three clear actions per section**

Each section should have:

```text
仅本次任务使用
保存为店铺模板
套用默认测试模板
```

- [x] **Step 6: Keep execution source visible but not noisy**

Field-level source should read:

```text
执行取值来自：本次任务 / 店铺模板 / 默认测试模板 / 商品原始数据
```

Advanced matching explanation goes into a folded area.

- [x] **Step 7: Verify preview equals execution**

Confirm `config_preview.py` and `V1TaskRunner._execution_defaults()` both use the same resolver path so the UI preview values equal actual execution values.

Verified on 2026-06-17:
- `ConfigPreviewService` and `V1TaskRunner._execution_defaults()` both use `ConfigDefaultsResolver`.
- `tests/test_task_start_guard.py::test_config_preview_and_runner_use_same_resolved_defaults` passed.

---

## Task 6: Agent Execution Flow

**Files:**
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/styles.css`
- Modify: `app/backend/src/main.py`
- Modify: `app/backend/src/services/agent_console.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`
- Test: `app/backend/tests/test_agent_console.py`

- [x] **Step 1: Define user-visible execution states**

Use these states in the UI:

```text
需要登录店小秘
需要选择任务
需要补配置
需要运行真实只读检查
需要人工确认只保存
可以启动 Agent 执行浏览器
Agent 正在执行
保存成功
保存失败，需处理
```

Verified on 2026-06-17:
- `buildConsolePrimaryPath` now uses the user-visible state labels above.
- Selected real tasks that are not logged into DXM route to `需要登录店小秘` with primary action `打开真实登录页`.
- Added `tests/test_frontend_demo_workflow_contract.py::test_agent_execution_primary_path_uses_user_visible_state_labels`.
- `tests/test_frontend_demo_workflow_contract.py` passed with `160 passed`.
- `npm run build` passed with the new frontend typecheck gate.

- [x] **Step 2: Replace technical errors with action copy**

Map raw errors:

```text
Cannot switch to a different thread -> 浏览器会话冲突，请关闭旧浏览器窗口后重试
Playwright Sync API inside the asyncio loop -> 登录检测冲突，请保持真实浏览器打开后重新检测
L2 readonly probe runner is missing -> 只读检查组件缺失，请重新打开完整免安装目录版
Internal Server Error -> 后端执行失败，请打开问题处理查看日志
```

- [x] **Step 3: Split login browser and execution browser**

UI copy must explain:

```text
登录浏览器用于人工登录和验证码。
执行浏览器在配置、只读检查、人工确认通过后由 Agent 操作。
```

Verified on 2026-06-17:
- Agent execution page copy now says `登录浏览器用于人工登录和验证码。执行浏览器在配置、真实只读检查和人工确认通过后由 Agent 操作。`
- Existing contract tests assert the login panel appears before execution-browser controls.

- [x] **Step 4: Real logs become secondary**

Show only latest 5-10 key log lines in first viewport. Full logs go to `更多诊断与维护`.

Verified on 2026-06-17:
- `visibleRuntimeLogItems = filteredRuntimeLogItems.slice(0, 10)`.
- `RuntimeLogPreview` remains in the first viewport; full `RuntimeLogPanel` is under `更多诊断与维护`.
- `tests/test_frontend_demo_workflow_contract.py` covers this layout.

- [x] **Step 5: Verify no screenshot-as-control language**

Main execution page must not imply the embedded screenshot is the real-time operation surface. Use copy:

```text
控制台操控独立真实浏览器；截图仅用于报告证据。
```

Verified on 2026-06-17:
- Agent execution page now uses `控制台操控独立真实浏览器；截图仅用于报告证据。`
- Historical screenshot fallback says `截图仅用于报告证据，实时操作请启动真实浏览器`.
- `tests/test_frontend_demo_workflow_contract.py` passed with `160 passed`.

---

## Task 7: Failure Recovery And Issue Handling

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/backend/src/main.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Build user-facing problem cards**

Every blocker card should answer:

```text
发生了什么
为什么阻断
下一步点哪里
```

Verified on 2026-06-17:
- `问题处理` now renders exception cards and default recovery cards with `发生了什么 / 为什么阻断 / 下一步点哪里`.
- Default recovery cards cover 店小秘未登录、真实只读检查未通过、任务已执行/失败、保存未完成、浏览器连接异常.
- Raw exception detail is only shown under `技术诊断`.

- [x] **Step 2: Hide raw Python exceptions from default report cards**

Raw exception text remains under:

```text
技术诊断
```

Main report should say:

```text
保存没有完成，系统没有拿到保存成功证明。
```

- [x] **Step 3: Add stale task recovery**

If current task is not draft or last execution failed, primary action should be:

```text
重新创建单商品只保存任务
```

Do not ask the user to interpret task status codes.

Verified on 2026-06-17:
- Failed tasks now show `保存失败，需处理`.
- Primary CTA and task page start label use `重新创建单商品只保存任务`.

- [x] **Step 4: Add browser occupied recovery**

If readonly check or execution browser is already running, show:

```text
真实只读检查正在运行，请等待完成。
关闭旧窗口或后台旧进程后，再重新打开免安装版。
```

Verified on 2026-06-17:
- Active L2 readonly runner state now shows the above user-facing wait/reopen guidance while preserving run-id in context.
- `tests/test_frontend_demo_workflow_contract.py` passed with `161 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.

---

## Task 8: Code Structure Split

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Create: `app/frontend/src/components/workbench/HomePage.tsx`
- Create: `app/frontend/src/components/workbench/DxmAccessPage.tsx`
- Create: `app/frontend/src/components/workbench/ProductTasksPage.tsx`
- Create: `app/frontend/src/components/workbench/EditConfigPage.tsx`
- Create: `app/frontend/src/components/workbench/AgentExecutionPage.tsx`
- Create: `app/frontend/src/components/workbench/ResultsPage.tsx`
- Create: `app/frontend/src/components/workbench/IssuesPage.tsx`
- Create: `app/frontend/src/components/workbench/SystemSettingsPage.tsx`
- Create: `app/frontend/src/components/workbench/workbenchCopy.ts`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Extract copy helpers first**

Move repeated user-facing labels and error mappings into `workbenchCopy.ts`.

Verified on 2026-06-17:
- Created `app/frontend/src/components/workbench/workbenchCopy.ts`.
- Moved `humanOperatorMessage`, `humanOperatorTitle`, and technical-error detection out of `WorkbenchModules.tsx`.
- `tests/test_frontend_demo_workflow_contract.py` passed with `161 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.

- [ ] **Step 2: Extract one page at a time**

Extract in this order:

```text
SystemSettingsPage [done 2026-06-17]
ResultsPage [done 2026-06-17]
IssuesPage [done 2026-06-17]
DxmAccessPage [done 2026-06-17]
ProductTasksPage [entry split 2026-06-17; move TaskCenterView internals next]
EditConfigPage [entry split 2026-06-17; move ConfigCenterView internals next]
AgentExecutionPage [entry split 2026-06-17; move ExecutionConsoleView internals next]
HomePage [entry split 2026-06-17; move DashboardView internals next]
```

Run tests after each extraction.

Verified on 2026-06-17:
- Created `app/frontend/src/components/workbench/SystemSettingsPage.tsx`.
- `WorkbenchModules.tsx` now re-exports `SystemSettingsPage as SystemSettings` for compatibility with current `App.tsx` imports.
- `tests/test_frontend_demo_workflow_contract.py` passed with `162 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Created `app/frontend/src/components/workbench/ResultsPage.tsx`.
- `WorkbenchModules.tsx` now re-exports `ResultsPage as ReportCenter` for compatibility with current `App.tsx` imports.
- Report-center contract tests now read the extracted `ResultsPage.tsx` instead of slicing the legacy monolithic file.
- `tests/test_frontend_demo_workflow_contract.py` passed with `163 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Created `app/frontend/src/components/workbench/IssuesPage.tsx`.
- `WorkbenchModules.tsx` now re-exports `IssuesPage as ExceptionQueue` for compatibility with current `App.tsx` imports.
- Problem-handling contract tests now read the extracted `IssuesPage.tsx` instead of slicing the legacy monolithic file.
- `tests/test_frontend_demo_workflow_contract.py` passed with `164 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Created `app/frontend/src/components/workbench/DxmAccessPage.tsx`.
- `WorkbenchModules.tsx` now re-exports `DxmAccessPage` for compatibility with current `App.tsx` imports.
- Login/access contract tests now read the extracted `DxmAccessPage.tsx` instead of slicing the legacy monolithic file.
- `tests/test_frontend_demo_workflow_contract.py` passed with `165 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Created `app/frontend/src/components/workbench/ProductTasksPage.tsx`.
- `App.tsx` now imports `ProductTasksPage as TaskCenter` directly from the new page file.
- `WorkbenchModules.tsx` renamed the old task page export to `TaskCenterView`; `ProductTasksPage` wraps this view as a safe intermediate boundary before moving task-page internals.
- Task-center contract tests now slice `TaskCenterView` while the user-facing route goes through `ProductTasksPage`.
- `tests/test_frontend_demo_workflow_contract.py` passed with `166 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Created `app/frontend/src/components/workbench/ProductTaskPanels.tsx`.
- Moved `RealModeReleasePlanPanel`, `humanReadinessCheckLabel`, and `humanReleaseBlocker` out of `WorkbenchModules.tsx` while preserving the task page behavior.
- Product task panel contract tests now assert the release-plan panel lives in `ProductTaskPanels.tsx`, and the old monolithic file only imports it.
- `tests/test_frontend_demo_workflow_contract.py` passed with `167 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Moved `SingleSaveRecoveryGuide` into `ProductTaskPanels.tsx` with local typed props and private task-display helpers to avoid a reverse dependency on `WorkbenchModules.tsx`.
- Recovery-guide tests now read the extracted panel file, while `TaskCenterView` only keeps orchestration and props wiring.
- `tests/test_frontend_demo_workflow_contract.py` passed with `168 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Moved `TaskCurrentActionPanel` and its `taskStartDecision` helper into `ProductTaskPanels.tsx`; `TaskCenterView` now wires the panel through props only.
- Updated task-center contract tests so first-screen task panel assertions read the extracted panel module instead of the monolithic `WorkbenchModules.tsx`.
- `tests/test_frontend_demo_workflow_contract.py` passed with `169 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Moved `ReadonlyRecheckHelpCard` and `L2ProbeResourceRepairPanel` into `ProductTaskPanels.tsx`, keeping readonly-precheck recovery copy and repair steps colocated with the task panels.
- Updated readonly-precheck and L2 repair contract tests to read the extracted panel module while preserving existing UI copy and behavior.
- `tests/test_frontend_demo_workflow_contract.py` passed with `170 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Created `app/frontend/src/components/workbench/EditConfigPage.tsx` as the page entry wrapper for the existing config-center view.
- `App.tsx` now imports `EditConfigPage as ConfigCenter` directly from the workbench page module; `WorkbenchModules.tsx` exports `ConfigCenter as ConfigCenterView` for this intermediate boundary.
- `tests/test_frontend_demo_workflow_contract.py` passed with `171 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Created `app/frontend/src/components/workbench/AgentExecutionPage.tsx` as the page entry wrapper for the existing execution-console view.
- `App.tsx` now imports `AgentExecutionPage as ExecutionConsole` directly from the workbench page module; `WorkbenchModules.tsx` exports `ExecutionConsole as ExecutionConsoleView` for this intermediate boundary.
- `tests/test_frontend_demo_workflow_contract.py` passed with `172 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- Created `app/frontend/src/components/workbench/HomePage.tsx` as the page entry wrapper for the existing dashboard view.
- `App.tsx` now imports `HomePage as Dashboard` directly from the workbench page module.
- Moved the homepage command-center body and `OperationGuide` into `HomePage.tsx`; `WorkbenchModules.tsx` now only exports shared status helpers used by the homepage and other existing pages.
- `tests/test_frontend_demo_workflow_contract.py` passed with `173 passed`.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- `git diff --check` passed with only existing CRLF normalization warnings.
- Removed the unused legacy `GuideCenter` page and stale `App.tsx` import after the `guide` route had already been normalized to `dxm_access`.
- Updated frontend contract tests to validate `HomePage.tsx`, `DxmAccessPage.tsx`, and the current `ExecutionConsole` copy instead of the deleted legacy guide page.
- `tests/test_frontend_demo_workflow_contract.py` passed with `171 passed` after removing two obsolete `GuideCenter`-specific tests.
- `npm run build` passed with `tsc --noEmit` and Vite production build.
- `git diff --check` passed with only existing CRLF normalization warnings.
- `WorkbenchModules.tsx` is down to about 6196 lines; the file is improved but still above the `< 2500 lines` Task 8 target.

- [ ] **Step 3: Keep behavior unchanged during extraction**

Do not redesign and extract in the same commit. The extraction commit should only move code and preserve exported props.

- [ ] **Step 4: Stop when the largest file is manageable**

Target:

```text
WorkbenchModules.tsx < 2500 lines
styles.css split or reduced so page-specific styles are findable
```

---

## Task 9: Desktop Portable Delivery

**Files:**
- Modify: `app/desktop/src/main.js`
- Modify: `app/desktop/src/preload.js`
- Modify: `scripts/verify-desktop-package.ps1`
- Modify: `scripts/final-delivery-check.ps1`
- Modify: `README.md`
- Modify: `docs/product/用户交付使用说明-20260526.md`

- [x] **Step 1: Keep launcher silent**

The portable exe should start backend/frontend internally. It should not require the user to manage two console windows.

- [x] **Step 2: Persist credentials locally**

When the user checks `记住账号密码`, credentials should be available next launch through the existing desktop bridge. UI must show:

```text
账号密码已保存到本机加密存储
```

- [x] **Step 3: Rebuild portable exe**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
cd D:\Desktop\py\dxm-auto-uikit\app\desktop
npm run build:portable
```

Expected portable output:

```text
D:\Desktop\py\dxm-auto-uikit\outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

- [x] **Step 4: Verify portable smoke**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable
```

Expected:

```text
portable smoke passed
```

---

## Task 10: Browser And Real Flow Acceptance

**Files:**
- Test only unless failures require fixes.

- [ ] **Step 1: Verify in-app browser UI**

Open local UI and check:

```text
Sidebar shows 8 business entries.
首页 first viewport shows the primary next step.
Agent 执行 first viewport shows login, readonly check, manual confirmation, execution browser.
Diagnostics are folded.
```

- [ ] **Step 2: Verify visible DXM browser**

Use a visible real 店小秘 browser:

```text
Open real login page.
Complete captcha manually.
Detect login success.
Run true readonly check.
Confirm UI refreshes to true readonly passed.
```

- [ ] **Step 3: Verify controlled single-save path**

Only after readonly check and manual approval:

```text
Create one single-product save-only task.
Start Agent execution browser.
Confirm black HUD shows Chinese progress.
Confirm report shows save success and published=false.
Confirm no publish entry exists.
```

- [ ] **Step 4: Verify failure recovery**

Force or inspect one failed task and confirm the UI says:

```text
保存没有完成，系统没有拿到保存成功证明。
下一步：重新创建单商品只保存任务。
```

Raw exception text must be behind technical diagnostics.

---

## Task 11: Final Delivery Gate And Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/product/用户交付使用说明-20260526.md`
- Modify: `docs/product/交付状态报告-20260525.md` if stale wording remains.

- [x] **Step 1: Run focused regression**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_agent_console.py tests\test_v1_runner.py tests\test_frontend_demo_workflow_contract.py -q
```

Expected:

```text
passed
```

- [x] **Step 2: Run frontend build**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

Expected:

```text
✓ built
```

- [x] **Step 3: Run desktop portable verify**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable
```

Expected:

```text
passed
```

- [ ] **Step 4: Commit before clean worktree gate**

Commit only after tests and build pass:

```powershell
git add README.md docs/product/用户交付使用说明-20260526.md app/backend/src app/backend/tests app/frontend/src
git commit -m "feat: polish dxm agent deliverable ux"
```

- [ ] **Step 5: Run final source-package gate**

Run after commit:

```powershell
cd D:\Desktop\py\dxm-auto-uikit
scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY
```

Expected report must be read with all four values:

```text
ok=true
okScope=controlled_single_save_only
realDxmMutationScope=controlled_single_save_only
realDxmWriteReadiness=READY
sourcePackageReadiness=READY
```

---

## Module-Level Functional Breakdown

### 首页

- 当前步骤判断。
- 主按钮跳转到对应菜单。
- 当前任务摘要。
- 登录 / 配置 / 只读检查 / 人工确认 / 保存结果五个状态卡。
- 普通用户文案，不展示技术门禁名。

### 店小秘接入

- 输入店小秘账号密码。
- 记住账号密码。
- 打开真实登录页。
- 验证码完成后检测登录状态。
- 登录失败恢复：保留真实浏览器窗口、修正验证码或账号密码、重新检测。

### 商品任务

- 商品选择。
- 创建单商品只保存任务。
- 历史任务选择。
- 当前任务是否草稿态。
- 任务失败后重新创建。

### 编辑页配置

- 当前模板选择。
- 默认测试模板套用。
- 店铺模板保存。
- 本次任务覆盖保存。
- 分区字段填写。
- 执行取值预览。
- 高级模板匹配折叠。

### Agent 执行

- 登录状态。
- 真实只读检查。
- 人工确认只保存。
- 启动 Agent 执行浏览器。
- 真实浏览器 HUD。
- 人工接管 / 交还。
- 关键日志。
- 完整诊断抽屉。

### 结果与报告

- 保存成功 / 失败。
- `published=false` 证明。
- 保存接口响应。
- 截图和 HAR 证据入口。
- 重新处理入口。

### 问题处理

- 登录失败。
- 只读检查失败。
- 浏览器占用。
- 后端不可用。
- 保存未完成。
- 任务状态不正确。
- 每个问题给出下一步按钮。

### 系统设置

- 后端状态。
- 前端 / 桌面页面状态。
- 真实浏览器状态。
- 日志路径。
- 交付门禁。
- 高级诊断。

---

## Detailed Execution Breakdown

下面是合并后的实际开发拆分。执行时按阶段推进；每个阶段完成后都要能独立验证，不能只靠最终大验收兜底。

### Phase 0: 状态可信与交付边界

**目标:** 先保证控制台显示的状态是真实可信的，否则后续 UI 再漂亮也会误导用户。

**子功能:**
- L2 真实只读证据读取：优先读取桌面运行期 `DATA_DIR/l2_readonly_probe`，兼容旧仓库 `data/l2_readonly_probe`。
- Electron `file://` 模式识别：桌面内置页面显示为正常桌面模式，不再误报 `前端异常`。
- DXM 登录态检测：优先复用可见真实浏览器会话；失败时给用户恢复动作，不暴露 greenlet / Playwright 原始异常。
- 保存后证据识别：`popChoiceProduct/add.json` 且 `code=0`、保存成功文案才能作为 save-only 证据。
- 发布风险误报收敛：页面普通按钮文案不应误判为用户真的执行了发布动作。

**验收证据:**
- `tests/test_delivery_workspace.py` 覆盖桌面数据目录 L2 通过、旧目录兼容、过期/写请求/双目标不一致仍阻断。
- `/api/runtime/status` 在免安装桌面版下不显示 `前端异常`。
- UI 状态能从 `未运行` 正确刷新为 `真实只读检查通过`。

### Phase 1: 信息架构与主窗口骨架

**目标:** 把“技术功能堆叠”改成“普通用户按步骤完成一件事”。

**菜单结构:**
- `首页`: 看当前能不能继续，点主按钮去下一步。
- `店小秘接入`: 只处理真实店小秘登录、验证码、登录检测。
- `商品任务`: 只处理商品选择、单商品只保存任务创建、历史任务恢复。
- `编辑页配置`: 只处理模板、分区字段、执行取值。
- `Agent 执行`: 只处理真实只读检查、人工确认、启动真实执行浏览器。
- `结果与报告`: 只处理保存结果、未发布证明、报告入口。
- `问题处理`: 只处理失败恢复。
- `系统设置`: 只承载技术诊断、日志路径、门禁细节。

**子功能:**
- 侧边栏分组与完整业务词，不再用过短菜单词。
- 顶部状态条压缩为一行：当前步骤、主按钮、只保存不发布标识、一个阻断原因。
- 诊断抽屉统一承载 L2/L3、run-id、日志路径、HAR、hash、Python 异常。
- 字号和首屏密度统一收敛，普通 1280x720 首屏能看到主动作。

**验收证据:**
- `test_frontend_demo_workflow_contract.py` 检查新菜单、旧路由兼容、普通页面默认不暴露技术字段。
- 浏览器验证：首页、商品任务、编辑页配置、Agent 执行首屏无需滚动即可找到主按钮。

### Phase 2: 店小秘接入页

**目标:** 用户清楚知道“这里就是登录真实店小秘”，并且账号密码可记住。

**子功能:**
- 账号输入。
- 密码输入。
- `记住账号密码` 本机加密保存。
- `打开真实登录页` 启动可见真实浏览器。
- `验证码已完成，检测登录状态` 复用可见浏览器检查。
- 登录失败恢复说明：保持浏览器打开、完成验证码、再检测。
- 登录成功后入口：`进入采集箱`、`进入采集页`。

**禁止内容:**
- 不讲 L2、probe、run-id。
- 不在主卡片显示 Playwright / greenlet / stack trace。
- 不混入配置、任务创建、保存执行。

**验收证据:**
- 页面首屏只围绕登录。
- 登录成功显示 `DXM 已登录`。
- 失败文案能指导用户下一步，不需要用户理解技术错误。

### Phase 3: 商品任务页

**目标:** 用户先选 1 个商品，再创建单商品只保存任务；不让用户接触批量、发布或无人值守入口。

**子功能:**
- 商品列表首屏可见，至少展示商品名、店铺、类目、来源状态。
- 单选商品逻辑：当前交付只允许 1 个商品。
- `创建单商品只保存任务` 主按钮。
- 没选商品时禁用并说明 `请先选择 1 个商品`。
- 当前任务摘要：任务名、店铺、类目、状态、能否启动。
- 非草稿或失败任务恢复：`重新创建单商品只保存任务`。
- 历史任务折叠，避免首屏干扰。

**禁止内容:**
- 不显示 claim_only / batch_save / 发布 / 无人值守可启动入口。
- 不让用户理解 draft/running/failed 等内部状态码。

**验收证据:**
- 选择商品后能创建 `single_save` 任务。
- 当前任务非草稿时，主路径提示重新创建任务。
- 页面首屏能完成“选商品 -> 创建任务”的主动作。

### Phase 4: 编辑页配置页

**目标:** 配置中心从“字段大杂烩”改为“店小秘编辑页分区表单”，并让用户知道保存是否生效、执行会用哪个值。

**分区:**
- 店铺与任务基础。
- 类目与标题。
- SKU / 价格 / 库存。
- 价格策略。
- 图片与素材。
- 包装物流。
- 合规 / 海关。
- 半托管。
- 店小秘引用模板。

**子功能:**
- 当前模板显示：默认测试模板 / 店铺模板 / 本次任务覆盖。
- 保存状态显示：已保存 / 有未保存修改 / 保存失败。
- 执行取值提示：将使用当前表单值。
- 当前缺失分区优先展开。
- 每个分区三个动作：`仅本次任务使用`、`保存为店铺模板`、`套用默认测试模板`。
- 字段旁显示执行取值来源：本次任务、店铺模板、默认测试模板、商品原始数据。
- 模板匹配解释、高级映射、低频字段默认折叠。

**验收证据:**
- 用户改完字段后看到保存状态变化。
- 预览值与 `V1TaskRunner._execution_defaults()` 实际执行值一致。
- 首屏能看到当前模板、保存状态、当前最需要补的分区。

### Phase 5: Agent 执行页

**目标:** 执行台只负责真实浏览器自动化，不再像诊断台。

**状态顺序:**
- 需要登录店小秘。
- 需要选择任务。
- 需要补配置。
- 需要运行真实只读检查。
- 需要人工确认只保存。
- 可以启动 Agent 执行浏览器。
- Agent 正在执行。
- 保存成功。
- 保存失败，需处理。

**子功能:**
- 登录状态卡。
- 真实只读检查卡。
- 人工确认只保存卡。
- 当前任务卡。
- 当前阻断原因卡。
- 一个主按钮：运行只读检查 / 人工确认只保存 / 启动 Agent 执行浏览器。
- 关键日志只显示 5-10 条。
- 完整日志、证据路径、run-id、网络计数进入诊断抽屉。
- 明确说明：控制台操控独立真实浏览器；截图仅用于报告证据。

**验收证据:**
- L2 未通过时不能启动执行浏览器。
- 人工确认未完成时不能保存。
- 全部通过后才显示 `启动 Agent 执行浏览器`。
- 首屏不需要滚动即可看到主按钮和阻断原因。

### Phase 6: 真实浏览器左上角中文 HUD

**目标:** 用户看着真实店小秘浏览器时，能知道 Agent 正在做什么、做到哪一步、下一步是什么。

**HUD 内容:**
- 标题：`DXM Agent 正在执行`。
- 安全标识：`只保存，不发布`。
- 进度：`4 / 12`。
- 当前动作：`填写标题`、`选择分类`、`填写 SKU / 价格 / 库存`、`点击保存`。
- 最近动作：最多 3 条。
- 下一步：`继续填写半托管信息` 等。
- 需要用户动作：验证码、人工确认、接管浏览器。

**实现边界:**
- HUD 注入真实 `dianxiaomi.com` 可见浏览器页面。
- HUD 不代替真实浏览器操作；它只是进度解释层。
- HUD 不遮挡核心编辑区域，默认左上角小窗，可收起。
- HUD 文案来自后端执行状态，不由前端猜测。

**验收证据:**
- 打开真实店小秘首页或编辑页能看到黑色 HUD。
- 执行到不同状态时 HUD 中文动作变化。
- 保存阶段显示 `点击保存`，不会显示发布相关动作。

### Phase 7: 结果与报告

**目标:** 用户能判断保存是否成功、是否未发布、失败后该怎么办。

**子功能:**
- 保存成功摘要。
- 保存失败摘要。
- `published=false` 明确展示。
- 保存接口响应摘要。
- 保存前/保存后截图入口。
- 未发布证明入口。
- 重新处理入口。
- 技术证据折叠：HAR、截图路径、原始 JSON。

**失败文案规则:**
- 主卡片写：`保存没有完成，系统没有拿到保存成功证明。`
- 技术异常只在 `技术诊断` 中展示。
- `Cannot switch to a different thread` 映射为：`浏览器会话冲突，请关闭旧浏览器窗口后重试。`

**验收证据:**
- 失败报告默认不露 Python/greenlet/Playwright 原文。
- 成功报告必须同时有保存成功和 `published=false`。

### Phase 8: 问题处理

**目标:** 把错误变成可恢复操作，不让用户读日志猜原因。

**问题卡类型:**
- 店小秘未登录。
- 验证码未完成。
- 真实只读检查失败。
- 真实只读检查正在运行。
- 任务不是草稿。
- 当前任务失败。
- 保存没有完成。
- 后端不可用。
- 免安装目录不完整。
- 浏览器会话冲突。

**每张卡结构:**
- 发生了什么。
- 为什么阻断。
- 下一步点哪里。
- 主操作按钮。
- 技术诊断折叠。

**验收证据:**
- 用户看到问题页后能直接执行下一步操作。
- 默认视图不要求理解 L2/probe/run-id。

### Phase 9: 系统设置与诊断下沉

**目标:** 技术信息保留给维护人员，但不干扰普通主流程。

**子功能:**
- 后端服务状态。
- 桌面内置页面状态。
- 后端端口。
- 真实浏览器状态。
- 日志路径。
- 数据目录。
- portable 版本。
- L2/L3 门禁状态。
- 完整诊断导出。

**验收证据:**
- 普通页面不抢占显示技术状态。
- 系统设置能找到必要维护信息。

### Phase 10: 代码结构整理

**目标:** 当前 `WorkbenchModules.tsx` 和 `styles.css` 太大，继续堆会拖慢后续交付。

**拆分顺序:**
- `workbenchCopy.ts`: 文案、错误映射、状态标签。
- `SystemSettingsPage.tsx`
- `ResultsPage.tsx`
- `IssuesPage.tsx`
- `DxmAccessPage.tsx`
- `ProductTasksPage.tsx`
- `EditConfigPage.tsx`
- `AgentExecutionPage.tsx`
- `HomePage.tsx`

**拆分规则:**
- 每次只拆一个页面。
- 拆分 commit 不改行为。
- 每拆一个页面就跑对应契约测试。
- 保持 props 显式，不引入全局状态库。

**验收证据:**
- `WorkbenchModules.tsx` 降到可维护范围。
- 页面级样式能按模块定位。
- 原有功能契约测试通过。

### Phase 11: 免安装版与真实流程验收

**目标:** 给用户的是可直接打开的生产级免安装包，而不是开发态项目。

**子功能:**
- `DXM-Agent-Console-Portable-0.1.0.exe` 启动桌面主窗口。
- 后端和前端服务后台托管，不弹两个控制台窗口。
- 账号密码可记住。
- 可见真实浏览器可打开、登录、检测。
- 真实只读检查可运行并刷新门禁。
- 单商品只保存流程可启动。
- 保存成功后报告显示未发布。
- 发布、批量、无人值守无入口。

**验收命令:**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_agent_console.py tests\test_v1_runner.py tests\test_frontend_demo_workflow_contract.py -q

cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build

cd D:\Desktop\py\dxm-auto-uikit\app\desktop
npm run build:portable

cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable
```

**最终交付门禁:**

```powershell
scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY
```

必须读取并确认：

```text
ok=true
okScope=controlled_single_save_only
realDxmMutationScope=controlled_single_save_only
realDxmWriteReadiness=READY
sourcePackageReadiness=READY
```

---

## Delivery Milestones

| Milestone | User-Visible Result | Required Proof |
| --- | --- | --- |
| M1 状态可信 | 登录、只读检查、桌面页面状态不再误报 | pytest + runtime status 验证 |
| M2 菜单与首页 | 用户知道下一步点哪里 | 浏览器首屏验证 |
| M3 店小秘接入/商品任务 | 用户能登录并创建单商品只保存任务 | 前端契约测试 + 浏览器验证 |
| M4 配置中心 | 用户知道模板、保存状态和执行取值 | 配置预览测试 + 浏览器验证 |
| M5 Agent 执行与 HUD | 用户能看到真实浏览器正在做什么 | 真实浏览器验证 |
| M6 报告与问题处理 | 用户能看懂失败并恢复 | 失败样例验证 |
| M7 免安装交付 | exe 可直接启动完整流程 | portable smoke + final delivery gate |

---

## Self-Review

- Spec coverage: 合并了“可交付体验改造计划”和“主窗口按菜单栏重构 + 真实浏览器左上角 HUD 计划”，覆盖状态可信、菜单、主窗口、配置中心、Agent 执行、真实浏览器 HUD、错误恢复、桌面包和最终验收。
- Placeholder scan: 没有 `TBD`、`TODO`、`implement later`；每个任务都有具体文件、步骤、命令或验收文本。
- Type consistency: `WorkbenchSection`、`AgentConsoleHud`、`controlled_single_save_only`、`Agent 执行浏览器` 等命名与当前仓库已出现的类型和文案保持一致。
- Scope check: 本计划是单一交付目标下的多模块拆分，不拆成多个互相独立计划；每个任务仍能独立测试和提交。
