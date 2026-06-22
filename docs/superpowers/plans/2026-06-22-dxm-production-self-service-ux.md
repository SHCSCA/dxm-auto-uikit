# DXM Production Self-Service UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DXM Agent Console 从“已能验证的只保存工具”推进到普通运营用户可长期自助使用的生产级单商品只保存产品。

**Architecture:** 保持当前 React/Vite/Electron/FastAPI/Playwright 架构，不重写技术栈。主窗口只呈现业务路径、下一步和恢复动作；技术门禁、日志、run-id、证据链下沉到诊断抽屉和系统维护页。真实执行继续发生在独立可见店小秘浏览器，浏览器内通过中文 HUD 实时显示 Agent 当前动作。

**Tech Stack:** React 18 + TypeScript + Vite, Electron portable desktop, FastAPI backend, Playwright visible browser automation, pytest contract tests, PowerShell browser/package QA scripts.

---

## Delivery Definition

任务算完成，必须同时满足以下条件：

1. 用户从免安装 EXE 启动，不需要打开两个 bat 控制台窗口。
2. 主窗口默认路径清楚：登录店小秘 -> 选择商品 -> 填写配置 -> 运行检查 -> 启动真实浏览器只保存 -> 查看结果。
3. 店小秘浏览器是可见独立窗口，用户能看到 Agent 正在操作什么。
4. 浏览器左上角 HUD 用中文显示实时进度，例如 `开始任务`、`查找草稿`、`输入标题`、`选择分类`、`点击保存`、`确认未发布`。
5. 账号密码可在本机加密保存，下次打开能自动填入。
6. 配置中心能明确显示：当前使用哪套模板、是否已保存、执行会取哪个值。
7. 默认页面不暴露 `L2`、`L3`、`probe`、`run-id`、`HAR`、线程异常等工程概念。
8. 失败时用户看到的是：发生了什么、为什么不能继续、下一步点哪里。
9. 发布、批量、无人值守、批量保存仍无入口且后端继续硬阻断。
10. 免安装版通过后台测试、前端构建、浏览器 QA、桌面包验证和一次真实可见路径验收。

## Non-Goals

- 不开放发布。
- 不开放批量保存。
- 不开放无人值守。
- 不把截图预览伪装成真实操控画面。
- 不做新的 UI 框架迁移。
- 不在主界面堆工程诊断信息。

## File Structure

### Frontend

- Modify: `app/frontend/src/types.ts`
  路由 section、模板状态、浏览器 HUD、用户可见状态类型。

- Modify: `app/frontend/src/components/AppShell.tsx`
  左侧菜单、分组、折叠态 tooltip、当前路径高亮。

- Modify: `app/frontend/src/App.tsx`
  数据加载、动作分发、页面路由、登录凭据、只读检查、Agent 启停。

- Modify: `app/frontend/src/components/SafetyStatusBar.tsx`
  顶部状态条。只保留当前步骤、安全边界、主按钮、一个阻断原因。

- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
  现有大组件继续拆瘦：配置中心、真实浏览器、日志、模板、证据逐步下沉。

- Modify: `app/frontend/src/components/workbench/HomePage.tsx`
  今日工作台，显示唯一下一步和当前控制权。

- Modify: `app/frontend/src/components/workbench/DxmAccessPage.tsx`
  店小秘账号、打开真实登录页、检测登录状态、记住账号密码。

- Modify: `app/frontend/src/components/workbench/ProductTasksPage.tsx`
  商品选择、当前任务、历史任务入口。

- Modify: `app/frontend/src/components/workbench/EditConfigPage.tsx`
  编辑页配置入口，连接配置分区和模板管理。

- Modify: `app/frontend/src/components/workbench/AgentExecutionPage.tsx`
  运行前检查、人工确认、启动执行浏览器。

- Modify: `app/frontend/src/components/workbench/ResultsPage.tsx`
  保存结果，优先展示保存成功、未发布、商品、时间、下一步。

- Modify: `app/frontend/src/components/workbench/IssuesPage.tsx`
  问题处理，默认使用用户语言，技术细节折叠。

- Modify: `app/frontend/src/components/workbench/HelpPage.tsx`
  操作引导，面向第一次使用和日常使用。

- Modify: `app/frontend/src/components/workbench/SystemSettingsPage.tsx`
  系统设置、日志、诊断、维护验收。

- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`
  技术错误翻译为用户可执行文案。

- Modify: `app/frontend/src/styles.css`
  菜单、主窗口密度、状态条、抽屉、配置分区、浏览器控制台、结果页样式。

### Backend

- Modify: `app/backend/src/services/agent_console.py`
  真实浏览器会话、HUD 注入、人工接管、可见窗口状态。

- Modify: `app/backend/src/execution/v1_runner.py`
  single_save 步骤向 Agent Console 同步用户可读进度。

- Modify: `app/backend/src/execution/dxm_login_flow.py`
  店小秘真实页面操作、保存、未发布确认、错误恢复证据。

- Modify: `app/backend/src/services/delivery_workspace.py`
  交付状态、门禁摘要、用户可读 readiness。

- Modify: `app/backend/src/services/config_defaults.py`
  默认测试模板、模板种子、执行默认值。

- Modify: `app/backend/src/services/config_preview.py`
  执行取值预览。

- Modify: `app/backend/src/services/config_validation.py`
  配置完整性、缺失字段、保存状态。

### Desktop And Scripts

- Modify: `app/desktop/src/main.cjs`
  免安装 EXE 启动、端口选择、账号加密保存、桌面日志、可见窗口 smoke。

- Modify: `scripts/qa-browser-check.ps1`
  浏览器 QA，验证用户默认界面和本地 API 安全边界。

- Modify: `scripts/verify-desktop-package.ps1`
  免安装包验证、凭据验证、可见窗口验证、portable smoke。

- Modify: `scripts/final-delivery-check.ps1`
  最终交付门禁，保持 controlled single_save only。

### Tests

- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`
- Modify: `app/backend/tests/test_frontend_api_error_contract.py`
- Modify: `app/backend/tests/test_agent_console.py`
- Modify: `app/backend/tests/test_v1_runner.py`
- Modify: `app/backend/tests/test_delivery_workspace.py`
- Modify: `app/backend/tests/test_desktop_package_contract.py`
- Modify: `app/backend/tests/test_config_defaults.py`
- Modify: `app/backend/tests/test_config_validation.py`

---

## Task 1: Freeze Safety And Baseline

**Purpose:** 先锁住当前已验证的安全边界，避免后续 UX 改造误放行发布、批量或无人值守。

**Files:**
- Test: `app/backend/tests/test_delivery_workspace.py`
- Test: `app/backend/tests/test_task_start_guard.py`
- Test: `app/backend/tests/test_publish_guard.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add explicit delivery-scope contract**

Add tests that assert the user-facing workspace still reports controlled single-save only:

```python
def test_workspace_delivery_scope_remains_single_save_only(repository):
    workspace = build_delivery_workspace(repository)
    readiness = workspace["delivery_readiness"]
    assert readiness["realDxmMutationScope"] == "controlled_single_save_only"
    assert readiness["batchUnattendedPublishAllowed"] is False
    assert "single_save" in readiness["allowedModes"]
    assert "claim_only" in readiness["blockedModes"]
    assert "batch_save" in readiness["blockedModes"]
```

- [x] **Step 2: Run guard tests**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_task_start_guard.py tests\test_publish_guard.py -q
```

Expected: all pass. If not, stop UX work and repair the safety gate first.

- [x] **Step 3: Record baseline evidence**

```powershell
cd D:\Desktop\py\dxm-auto-uikit
git status --short
```

Expected: only known working-branch changes. Do not reset unrelated user changes.

Evidence recorded on 2026-06-22:

- Added `test_delivery_workspace_delivery_scope_remains_controlled_single_save_only` to lock the release plan to `controlled_single_save_only`.
- Guard suite passed with project-local temp directory on D drive: `132 passed in 26.03s`.
- C drive user temp had about 11MB free, so pytest must use `D:\Desktop\py\dxm-auto-uikit\.tmp\pytest` until C drive space is recovered.

---

## Task 2: Mature Sidebar And Page Boundaries

**Purpose:** 菜单要像成熟产品，而不是技术模块清单。侧边栏负责“去哪里”，页面内负责“具体做什么”。

**Files:**
- Modify: `app/frontend/src/types.ts`
- Modify: `app/frontend/src/components/AppShell.tsx`
- Modify: `app/frontend/src/App.tsx`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Write sidebar contract**

Require these top-level groups and leaf entries:

```python
expected_sidebar_labels = [
    "今日工作台",
    "店小秘账号",
    "商品任务",
    "选择商品",
    "当前任务",
    "历史任务",
    "编辑页配置",
    "基础信息",
    "类目与标题",
    "价格库存",
    "图片素材",
    "包装物流",
    "合规海关",
    "模板管理",
    "自动执行",
    "运行前检查",
    "真实浏览器",
    "人工接管",
    "结果复盘",
    "保存结果",
    "问题处理",
    "证据归档",
    "帮助与系统",
    "使用帮助",
    "系统设置",
]
```

Also assert these strings are not default sidebar labels:

```python
forbidden_default_labels = ["Agent Console", "L2", "L3", "probe", "HAR", "run-id"]
```

- [x] **Step 2: Update workbench section types**

Target route model:

```ts
export type WorkbenchSection =
  | 'home'
  | 'dxm_access'
  | 'product_tasks'
  | 'current_task'
  | 'task_history'
  | 'edit_config'
  | 'config_basic'
  | 'config_category_title'
  | 'config_price_stock'
  | 'config_images'
  | 'config_logistics'
  | 'config_compliance'
  | 'template_management'
  | 'preflight'
  | 'real_browser'
  | 'manual_takeover'
  | 'results'
  | 'issues'
  | 'evidence'
  | 'help'
  | 'settings'
```

Use aliases so existing links still work:

```ts
const sectionAliases: Partial<Record<string, WorkbenchSection>> = {
  agent_execution: 'preflight',
  guide: 'help',
  browser: 'real_browser',
}
```

- [x] **Step 3: Replace sidebar model**

Use user-facing groups:

```tsx
const primaryAreas = [
  { label: '准备', items: [
    { id: 'home', label: '今日工作台', hint: '看当前该做哪一步' },
    { id: 'dxm_access', label: '店小秘账号', hint: '登录真实店小秘并保存本机账号' },
  ] },
  { label: '商品任务', items: [
    { id: 'product_tasks', label: '选择商品', hint: '选择一个商品创建只保存任务' },
    { id: 'current_task', label: '当前任务', hint: '查看本次只保存任务状态' },
    { id: 'task_history', label: '历史任务', hint: '恢复或复制历史任务' },
  ] },
  { label: '编辑页配置', items: [
    { id: 'edit_config', label: '配置总览', hint: '查看还缺哪些编辑页信息' },
    { id: 'config_basic', label: '基础信息', hint: '店铺、类目、认领标记' },
    { id: 'config_category_title', label: '类目与标题', hint: '分类、标题、属性模板' },
    { id: 'config_price_stock', label: '价格库存', hint: '价格、库存、SKU' },
    { id: 'config_images', label: '图片素材', hint: '主图、营销图、外包装图' },
    { id: 'config_logistics', label: '包装物流', hint: '重量、尺寸、物流模板' },
    { id: 'config_compliance', label: '合规海关', hint: '欧代、海关、半托管' },
    { id: 'template_management', label: '模板管理', hint: '选择、保存、复制店铺模板' },
  ] },
  { label: '自动执行', items: [
    { id: 'preflight', label: '运行前检查', hint: '只读检查和保存前确认' },
    { id: 'real_browser', label: '真实浏览器', hint: '查看 Agent 控制的店小秘窗口' },
    { id: 'manual_takeover', label: '人工接管', hint: '遇到验证码或异常时接管' },
  ] },
  { label: '结果复盘', items: [
    { id: 'results', label: '保存结果', hint: '确认保存成功且未发布' },
    { id: 'issues', label: '问题处理', hint: '按失败原因恢复' },
    { id: 'evidence', label: '证据归档', hint: '维护人员查看证据链' },
  ] },
  { label: '帮助与系统', items: [
    { id: 'help', label: '使用帮助', hint: '普通用户操作说明' },
    { id: 'settings', label: '系统设置', hint: '日志、服务、维护诊断' },
  ] },
]
```

- [x] **Step 4: Run contract**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
```

Expected: sidebar labels and aliases pass.

Evidence recorded on 2026-06-22:

- `WorkbenchSection` now has user-facing routes for current task, task history, edit-page subsections, preflight, real browser, manual takeover, evidence archive, help, and settings.
- Legacy route aliases keep older entries compatible: `agent_execution -> preflight`, `guide -> help`, `browser -> real_browser`.
- Sidebar now exposes the planned 25 ordinary-user labels and keeps engineering terms out of the default navigation.
- Frontend contract suite passed independently: `180 passed in 0.56s`.

---

## Task 3: Main Window Information Architecture

**Purpose:** 主窗口根据菜单拆页面，不再把配置、日志、状态、证据、说明堆在一个屏幕里。

**Files:**
- Modify: `app/frontend/src/components/SafetyStatusBar.tsx`
- Modify: `app/frontend/src/components/workbench/HomePage.tsx`
- Modify: `app/frontend/src/components/workbench/DxmAccessPage.tsx`
- Modify: `app/frontend/src/components/workbench/ProductTasksPage.tsx`
- Modify: `app/frontend/src/components/workbench/AgentExecutionPage.tsx`
- Modify: `app/frontend/src/components/workbench/ResultsPage.tsx`
- Modify: `app/frontend/src/components/workbench/IssuesPage.tsx`
- Modify: `app/frontend/src/styles.css`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add first-viewport contract**

Assert first-screen default content follows these rules:

```python
assert "现在只做这一步" in home_source
assert "下一步" in home_source
assert "状态详情" in status_source
assert "技术诊断" in settings_source

default_forbidden = ["run-id", "HAR", "probe", "greenlet", "Cannot switch to a different thread"]
for token in default_forbidden:
    assert token not in default_first_screen_source
```

- [x] **Step 2: Rebuild top status bar**

Target visible structure:

```tsx
<section className="safety-status-bar">
  <div className="safety-status-bar__step">继续下一步：{nextStepLabel}</div>
  <span className="safety-status-bar__scope">只保存，不发布</span>
  <button>{primaryActionLabel}</button>
  {blocker && <span className="safety-status-bar__blocker">{blocker.userSummary}</span>}
  <details>
    <summary>状态详情</summary>
    <TechnicalGateDetails />
  </details>
</section>
```

- [x] **Step 3: Reduce page density**

Apply these UI rules in `styles.css`:

```css
:root {
  --font-size-body: 14px;
  --font-size-title: 22px;
  --font-size-panel-title: 16px;
}

.workbench-page {
  display: grid;
  gap: 16px;
}

.primary-panel {
  min-height: 0;
  padding: 16px;
}

.diagnostic-drawer,
.technical-details {
  max-height: 52vh;
  overflow: auto;
}
```

- [x] **Step 4: Verify desktop and mobile layout**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1 -Url http://127.0.0.1:15195
```

Expected: no horizontal overflow, no blank page, no console errors.

Evidence recorded on 2026-06-22:

- Top status bar default disclosure changed to `状态详情`; technical diagnostics remain inside the disclosure and system settings.
- Kept compact type-scale variables compatible with existing CSS while adding `--font-size-*` aliases for the next density pass.
- Frontend contract suite passed: `180 passed in 0.55s`.
- Frontend production build passed: `npm run build`.
- Browser QA passed against current source backend/frontend: `outputs/browser-checks/production-self-service-ux-task3/qa-browser-check.json` with `ok=true`, no console errors, no failed network requests, and no desktop/mobile horizontal overflow.

---

## Task 4: Account Login And Credential UX

**Purpose:** 用户能理解登录状态，账号密码能本机记住，登录成功后状态必须可信。

**Files:**
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/frontend/src/components/workbench/DxmAccessPage.tsx`
- Modify: `app/desktop/src/main.cjs`
- Modify: `app/backend/src/execution/dxm_login_flow.py`
- Test: `app/backend/tests/test_desktop_package_contract.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add login UX contract**

Require visible user states:

```python
required_login_copy = [
    "打开真实登录页",
    "验证码完成后检测登录状态",
    "记住账号密码",
    "本机加密保存",
    "DXM 已登录",
    "登录未通过",
]
```

- [x] **Step 2: Make login status source clear**

Page should show:

```text
当前状态：已登录 / 未登录 / 等待验证码 / 登录失败
真实浏览器停留位置：www.dianxiaomi.com/...
下一步：点击检测登录状态 / 继续选择商品
```

- [x] **Step 3: Keep credential storage local**

Maintain Electron safeStorage behavior:

```js
ipcMain.handle('desktop:dxm-credential:save', (_, credential) => saveDxmCredential(credential))
ipcMain.handle('desktop:dxm-credential:load', () => loadDxmCredential())
ipcMain.handle('desktop:dxm-credential:clear', () => clearDxmCredential())
```

No credential should be written to repo files.

- [x] **Step 4: Run credential smoke**

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

Expected: credential smoke and visible window smoke pass.

Evidence recorded on 2026-06-22:

- Login copy now uses user-facing actions: `打开真实登录页`, `验证码完成后检测登录状态`, `记住账号密码`, `本机加密保存`, `DXM 已登录`, and `登录未通过`.
- The account page now shows a compact login status summary: `当前状态`, `真实浏览器停留位置`, and `下一步`, with user states `已登录`, `未登录`, `等待验证码`, and `登录失败`.
- Electron credential storage remains local via `safeStorage` and the existing `desktop:dxm-credential:load/save/clear` IPC handlers; user-facing copy no longer describes it as a technical storage mechanism.
- Focused desktop/frontend contract tests passed with project-local temp directory on D drive: `200 passed in 0.54s`.
- Frontend production build passed after the login UX changes: `npm run build`.
- Packaged credential smoke completed during Task 9 via `scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180`.

---

## Task 5: Configuration Center As Execution Brief

**Purpose:** 配置中心要回答“Agent 到店小秘编辑页会怎么填”，而不是展示一堆模板和字段路径。

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/components/workbench/EditConfigPage.tsx`
- Modify: `app/frontend/src/workspace.ts`
- Modify: `app/backend/src/services/config_defaults.py`
- Modify: `app/backend/src/services/config_preview.py`
- Modify: `app/backend/src/services/config_validation.py`
- Test: `app/backend/tests/test_config_defaults.py`
- Test: `app/backend/tests/test_config_validation.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add config UX contract**

Require these user-facing concepts:

```python
required_config_copy = [
    "当前使用模板",
    "保存状态",
    "执行会使用这些值",
    "仅本次任务使用",
    "保存为店铺模板",
    "套用默认测试模板",
    "未保存的修改",
    "已保存",
]
```

Default view must not expose:

```python
forbidden_default_config_copy = ["template_trace", "payload_json", "field.path", "dxm_reference_templates_resolved"]
```

- [x] **Step 2: Split config pages by DXM edit-page sections**

Use these page responsibilities:

```text
基础信息：店铺、平台、类目、认领标记
类目与标题：类目、标题、属性模板、详情模板
价格库存：SKU、价格、库存、条码策略
图片素材：主图、营销图、外包装图
包装物流：重量、尺寸、运费模板、服务模板
合规海关：欧代、制造商、海关名、半托管
模板管理：默认测试模板、店铺模板、复制模板、启停模板
```

- [x] **Step 3: Add save-state model**

Frontend state should distinguish:

```ts
type ConfigSaveState = 'clean' | 'dirty' | 'saving' | 'saved' | 'failed'
```

Show one of:

```text
已保存，本次执行会使用这些值
有未保存修改，执行前请保存或选择仅本次任务使用
保存失败，请重试或查看问题处理
```

- [x] **Step 4: Keep advanced explanation collapsed**

Default field row:

```tsx
<div className="config-field">
  <label>{field.label}</label>
  <input value={field.value} />
  <small>{sourceBadgeText(field.source)}</small>
  <details>
    <summary>字段来源详情</summary>
    <code>{field.path}</code>
  </details>
</div>
```

- [x] **Step 5: Run focused tests**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_config_defaults.py tests\test_config_validation.py tests\test_frontend_demo_workflow_contract.py -q
```

Expected: config contracts pass.

Evidence recorded on 2026-06-22:

- Configuration center default status now uses ordinary-user wording: `当前使用模板`, `保存状态`, `执行会使用这些值`, and `未保存的修改`.
- Section save state now distinguishes `clean`, `dirty`, `saving`, `saved`, and `failed`; save failures render as user-facing failed state instead of an internal error state.
- Default configuration controls keep technical fields such as `template_trace`, `payload_json`, `field.path`, and `dxm_reference_templates_resolved` out of the visible path; field path details remain available only under `字段来源详情`.
- Focused config and frontend contract tests passed with project-local temp directory on D drive: `196 passed in 1.32s`.

---

## Task 6: Real Browser Execution And Chinese HUD

**Purpose:** 用户必须能在真实浏览器里看见 Agent 当前在做什么，错在哪里，何时需要人工接管。

**Files:**
- Modify: `app/backend/src/services/agent_console.py`
- Modify: `app/backend/src/execution/v1_runner.py`
- Modify: `app/backend/src/execution/dxm_login_flow.py`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/frontend/src/components/workbench/AgentExecutionPage.tsx`
- Test: `app/backend/tests/test_agent_console.py`
- Test: `app/backend/tests/test_v1_runner.py`

- [x] **Step 1: Standardize business progress steps**

Use one canonical step list:

```python
SINGLE_SAVE_PROGRESS_STEPS = [
    ("start_task", "开始任务", "准备打开店小秘草稿箱"),
    ("open_draft_box", "打开草稿箱", "进入店小秘商品草稿箱"),
    ("find_product", "查找商品", "按商品来源和标题定位草稿"),
    ("open_editor", "打开编辑页", "进入当前商品编辑页"),
    ("fill_title", "输入标题", "填写商品标题和卖点"),
    ("choose_category", "选择分类", "确认商品类目和属性"),
    ("fill_price_stock", "填写价格库存", "填写价格、库存和 SKU 信息"),
    ("handle_images", "处理图片", "检查主图、营销图和外包装图"),
    ("set_logistics", "设置包装物流", "填写重量尺寸和物流模板"),
    ("click_save", "点击保存", "只点击保存，不点击发布"),
    ("verify_unpublished", "确认未发布", "检查商品仍未发布"),
    ("done", "任务完成", "保存成功并确认未发布"),
]
```

- [x] **Step 2: HUD must be non-blocking**

HUD target behavior:

```text
位置：真实浏览器页面左上角，避开店小秘顶部导航
宽度：约 280px
样式：黑色半透明窗口
内容：当前步骤、进度、下一步、安全边界
交互：pointer-events: none，不挡用户点击
```

- [x] **Step 3: Sync every real action**

Before each major browser operation, call Agent Console HUD update:

```python
agent_console.update_hud({
    "state": "RUNNING",
    "phase": "自动执行中",
    "human_title": "选择分类",
    "human_action": "正在确认店小秘类目和属性",
    "human_next": "填写价格库存",
    "progress_index": 6,
    "progress_total": 12,
    "guard": "只保存不发布",
})
```

- [x] **Step 4: Add manual takeover states**

Visible states:

```text
Agent 操作中
等待人工处理
人工接管中
已交还 Agent
任务完成
任务失败
```

- [x] **Step 5: Test HUD contract**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_agent_console.py tests\test_v1_runner.py::test_single_save_syncs_agent_console_hud_without_changing_workflow_order -q
```

Expected: progress order stable and HUD copy user-readable.

Evidence recorded on 2026-06-22:

- `SINGLE_SAVE_PROGRESS_STEPS` now defines the user-visible 12-step save-only flow: start task, draft box, product lookup, editor open, title, category, price/stock, images, logistics, save, unpublished verification, done.
- `V1TaskRunner` now maps real workflow states to the 12-step HUD without changing the underlying workflow order.
- Browser HUD remains injected as a black, top-left, non-blocking overlay with `pointer-events:none`; it shows progress, next step, recent actions, and `只保存不发布`.
- Manual takeover states remain user-facing: waiting captcha, manual approval, manual takeover, and release back to Agent.
- Focused HUD tests passed with project-local temp directory on D drive: `31 passed in 5.38s`.

---

## Task 7: Error Recovery That A Normal User Can Follow

**Purpose:** 失败不是把异常抛给用户，而是给用户一个可恢复路径。

**Files:**
- Modify: `app/frontend/src/api.ts`
- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`
- Modify: `app/frontend/src/components/workbench/IssuesPage.tsx`
- Modify: `app/frontend/src/components/workbench/ResultsPage.tsx`
- Modify: `app/backend/src/services/agent_console.py`
- Test: `app/backend/tests/test_frontend_api_error_contract.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add technical-error translations**

Map examples:

```ts
const userErrorMappings = [
  {
    match: /Cannot switch to a different thread|greenlet/i,
    title: '浏览器会话异常',
    why: '当前浏览器自动化会话已经失效，系统没有继续保存。',
    next: '关闭当前执行浏览器，重新打开真实浏览器后再运行任务。',
  },
  {
    match: /L2 readonly probe|readonly/i,
    title: '运行前检查未通过',
    why: '系统还没有确认店小秘页面可以安全读取。',
    next: '点击“运行前检查”，通过后再启动只保存。',
  },
  {
    match: /save_result|published=false proof|network\/HAR/i,
    title: '保存结果证据不完整',
    why: '系统没有拿到足够证据证明保存成功且未发布。',
    next: '查看保存结果；如店小秘页面已保存，请重新创建任务补齐证据。',
  },
]
```

- [x] **Step 2: Enforce issue-card shape**

Every issue card defaults to:

```text
发生了什么
为什么不能继续
下一步
```

Raw exception goes into:

```tsx
<details>
  <summary>维护人员查看技术细节</summary>
  <pre>{rawError}</pre>
</details>
```

- [x] **Step 3: Test error copy**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_api_error_contract.py tests\test_frontend_demo_workflow_contract.py -q
```

Expected: default UI has no raw stack traces.

Evidence recorded on 2026-06-22:

- Technical failures now map to user recovery copy: `浏览器会话异常`, `运行前检查未通过`, and `保存结果证据不完整`.
- Issue cards keep the default shape `发生了什么 / 为什么不能继续 / 下一步`; raw detail is moved under `维护人员查看技术细节`.
- Frontend API error handling still hides raw 500/greenlet/Traceback messages from user-facing operation errors.
- Focused error and frontend contract tests passed with project-local temp directory on D drive: `181 passed in 1.29s`.
- Frontend production build passed after the error-recovery changes: `npm run build`.

---

## Task 8: Logs And Diagnostics As Drawer, Not Main Content

**Purpose:** 实时日志要有，但不能占主窗口；默认只显示最近关键 5-10 条。

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/components/workbench/SystemSettingsPage.tsx`
- Modify: `app/frontend/src/styles.css`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add log visibility contract**

Default pages may show:

```text
最近日志
正在实时刷新
查看完整日志
```

Default pages must not show:

```text
400 条
run-id
完整 JSON
日志路径
```

except in system diagnostics.

- [x] **Step 2: Implement log summary**

Target summary:

```tsx
<section className="log-summary">
  <header>
    <strong>最近日志</strong>
    <span>自动刷新</span>
  </header>
  {recentImportantLogs.slice(0, 8).map(renderLogLine)}
  <details className="diagnostic-drawer">
    <summary>查看完整日志与维护诊断</summary>
    <FullRuntimeLog />
  </details>
</section>
```

- [ ] **Step 3: Verify first viewport**

Use browser QA screenshot and DOM text assertions. The main action must be visible without scrolling on 1365x768.

Evidence recorded on 2026-06-22:

- Execution console now exposes `最近日志` as the compact default log entry and moves full log counts, sources, and maintenance context under `完整日志与维护诊断`.
- Default log preview shows recent summarized lines and `正在实时刷新`; full raw lines are only available under `查看完整日志与维护诊断`.
- Frontend contract tests passed after the log-visibility update: `180 passed in 1.19s`.
- Frontend production build passed after the log UI change: `npm run build`.
- Pending: browser QA screenshot pass for the full first viewport; this belongs to Task 10 after Task 9 package rebuild.

---

## Task 9: Desktop EXE Productization

**Purpose:** 普通用户只打开一个 EXE；旧进程、端口占用、资源缺失要能自恢复或给出明确处理方式。

**Files:**
- Modify: `app/desktop/src/main.cjs`
- Modify: `scripts/verify-desktop-package.ps1`
- Modify: `scripts/start-desktop.bat`
- Modify: `scripts/final-delivery-check.ps1`
- Test: `app/backend/tests/test_desktop_package_contract.py`

- [x] **Step 1: Add startup contract**

Verify:

```python
def test_desktop_package_uses_single_visible_console_window():
    source = Path("app/desktop/src/main.cjs").read_text(encoding="utf-8")
    assert "DXM Agent Console" in source
    assert "safeStorage" in source
    assert "backend.log" in source
    assert "frontend.log" not in user_default_visible_copy
```

- [x] **Step 2: Make stale process handling user-readable**

User-facing text:

```text
检测到旧服务正在运行
处理：关闭旧的 DXM Agent Console 窗口后重试
不会执行保存或发布
```

- [x] **Step 3: Rebuild portable**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\desktop
npm run build:portable
```

Expected output:

```text
D:\Desktop\py\dxm-auto-uikit\outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

- [x] **Step 4: Copy user-facing no-install EXE**

```powershell
Copy-Item -Force `
  D:\Desktop\py\dxm-auto-uikit\outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe `
  D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
```

- [x] **Step 5: Verify package**

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

Expected: packaged smoke, credential smoke, visible window smoke, portable smoke all pass.

Evidence recorded on 2026-06-22:

- Rebuilt portable desktop package with `app\desktop\npm run build:portable`; output: `D:\Desktop\py\dxm-auto-uikit\outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe`.
- Package verification passed with D-drive TEMP: packaged backend resource status, packaged smoke, credential smoke, visible window smoke, and portable smoke all passed.
- Verification artifacts were written under `D:\Desktop\py\dxm-auto-uikit\.tmp\desktop-verify\`.
- Copied the user-facing no-install EXE to `D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe` with size `102054447` bytes and timestamp `2026/6/22 17:09:28`.

---

## Task 10: Browser-Backed Acceptance

**Purpose:** 不能靠猜测和静态代码判断体验是否成立；必须用真实渲染和真实浏览器路径验收。

**Files:**
- Modify if needed: `scripts/qa-browser-check.ps1`
- Output: `outputs/browser-checks/<run-id>/qa-browser-check.json`
- Output: `outputs/browser-checks/<run-id>/qa-browser-check.md`

- [ ] **Step 1: Run backend tests**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_frontend_demo_workflow_contract.py tests\test_frontend_api_error_contract.py tests\test_agent_console.py tests\test_v1_runner.py tests\test_desktop_package_contract.py -q
```

Expected: pass.

- [ ] **Step 2: Build frontend**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

Expected: Vite build pass.

- [ ] **Step 3: Run browser QA**

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1 -OutDir outputs\browser-checks\production-self-service-ux
```

Expected JSON:

```json
{
  "ok": true,
  "failedRequests": [],
  "consoleErrors": [],
  "desktopHorizontalOverflow": false,
  "mobileHorizontalOverflow": false
}
```

- [ ] **Step 4: Manual acceptance through EXE**

Use the updated no-install EXE:

```text
D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
```

Acceptance path:

```text
1. 打开 EXE
2. 店小秘账号自动填入或手动输入
3. 打开真实登录页
4. 完成验证码并点击检测登录状态
5. 选择一个商品任务
6. 检查编辑页配置和执行取值
7. 运行真实只读检查
8. 人工确认只保存
9. 启动真实浏览器执行
10. 浏览器 HUD 显示中文进度
11. 任务结束后结果页显示保存成功、未发布
12. 发布、批量、无人值守无入口
```

- [ ] **Step 5: Final delivery gate**

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\final-delivery-check.ps1 -ExpectedRealDxmWriteReadiness READY
```

Expected:

```text
realDxmWriteReadiness=READY
realDxmMutationScope=controlled_single_save_only
batchUnattendedPublishAllowed=false
```

---

## Task 11: Documentation And User Handoff

**Purpose:** 交付物要告诉用户如何用，而不是只告诉开发者测试通过。

**Files:**
- Modify: `README.md`
- Modify: `docs/product/用户交付使用说明-20260526.md`
- Modify: `docs/product/交付状态报告-20260525.md`
- Modify: `docs/superpowers/plans/2026-06-22-dxm-production-self-service-ux.md`

- [ ] **Step 1: Update user guide**

Guide structure:

```markdown
# DXM 单商品只保存 Agent 使用说明

## 这是什么
真实打开店小秘浏览器，按配置只保存一个商品，不发布。

## 第一次怎么用
1. 打开免安装 EXE
2. 登录店小秘
3. 选择商品
4. 填写编辑页配置
5. 运行检查
6. 人工确认后启动只保存
7. 查看结果

## 它不会做什么
- 不发布
- 不批量保存
- 不无人值守
- 不绕过验证码

## 失败怎么处理
按“问题处理”页给出的下一步恢复。
```

- [ ] **Step 2: Update delivery report**

Must include:

```text
交付范围：controlled single_save only
用户入口：免安装 EXE 路径
验收证据：测试、构建、浏览器 QA、desktop package smoke
未开放范围：发布、批量、无人值守
```

- [ ] **Step 3: Verify docs do not overclaim**

Search:

```powershell
rg -n "无人值守|批量|发布|READY|single_save|claim_only|batch_save" README.md docs\product
```

Expected: no sentence claims batch/unattended/publish is deliverable.

---

## Subagent Execution Model

Use fresh subagents per independent task group, then close them after completion:

1. **Frontend IA agent**
   Owns Task 2 and Task 3. Reviews sidebar, first viewport, default copy.

2. **Config UX agent**
   Owns Task 5. Reviews template selection, save state, execution values.

3. **Browser/HUD agent**
   Owns Task 6 and browser-specific parts of Task 10. Reviews real visible browser behavior and HUD.

4. **Backend gates agent**
   Owns Task 1, Task 4 backend checks, and Task 7 error contracts.

5. **Packaging QA agent**
   Owns Task 9 and Task 10 package/browser QA.

Main agent responsibilities:

- Keep publish/batch/unattended blocked.
- Review subagent diffs before merging.
- Run final tests and browser verification.
- Rebuild and copy the no-install EXE.
- Report exact artifact path and remaining risks.

---

## Execution Order

Recommended order:

1. Task 1: safety baseline.
2. Task 2: menu and routing.
3. Task 3: main-window density and status bar.
4. Task 5: configuration center.
5. Task 4: login and credential UX.
6. Task 6: real browser HUD.
7. Task 7: error recovery.
8. Task 8: logs and diagnostics drawers.
9. Task 9: desktop EXE.
10. Task 10: browser-backed acceptance.
11. Task 11: docs and handoff.

Do not start Task 9 until Task 2-8 pass focused tests and `npm run build`.

---

## Final Acceptance Command Set

Run these before claiming completion:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py tests\test_frontend_demo_workflow_contract.py tests\test_frontend_api_error_contract.py tests\test_agent_console.py tests\test_v1_runner.py tests\test_desktop_package_contract.py tests\test_config_defaults.py tests\test_config_validation.py -q
```

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1 -OutDir outputs\browser-checks\production-self-service-ux
```

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\desktop
npm run build:portable
```

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\final-delivery-check.ps1 -ExpectedRealDxmWriteReadiness READY
```

Completion evidence must name:

- Backend test result.
- Frontend build result.
- Browser QA artifact path.
- Desktop package verification result.
- User-facing EXE path.
- Whether real single-save was executed in this round or reused from accepted L3 evidence.
- Explicit statement that publish/batch/unattended remain blocked.
