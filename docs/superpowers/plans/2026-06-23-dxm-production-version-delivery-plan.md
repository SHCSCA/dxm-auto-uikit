# DXM Production Version Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DXM Agent Console 从“测试/诊断型工作台”推进为可交付客户使用的生产级两段式真实店小秘自动化产品：先从数据采集认领到采集箱，再从采集箱编辑商品并只保存。

**Architecture:** 保持现有 React/Vite/Electron/FastAPI/Playwright 架构，但按用户业务流程重构产品边界。后端把 `claim_only` 明确定义为“数据采集认领到采集箱”，把 `single_save` 明确定义为“采集箱商品编辑后只保存”；前端把技术门禁、run-id、L2/L3、日志路径下沉到维护诊断，普通用户只看到当前阶段、下一步、阻断原因和恢复动作。

**Tech Stack:** React 18 + TypeScript + Vite, Electron portable desktop, FastAPI, SQLite repository, Playwright headed browser automation, pytest contract tests, PowerShell package verification.

---

## 0. 当前版本基线

**当前分支:** `feature/dxm-production-two-stage`

**当前已完成:**
- 后端已把 `claim_only` 改为采集认领阶段，不再伪装为本地 QA 商品或编辑保存。
- 后端已有采集认领状态：`OPEN_DATA_ACQUISITION`、`CLAIM_TO_DRAFT_BOX`、`VERIFY_DRAFT_BOX_CLAIM`。
- `single_save` 已被约束为只允许从已认领/已验证的采集箱商品开始。
- 发布、批量、无人值守仍保持阻断。
- 关键后端契约测试已通过一次：`353 passed`。
- 前端 build 已通过一次。

**当前未完成:**
- 普通用户路径仍不够清晰，菜单和页面仍有技术概念泄漏。
- 模板中心还不像生产模板系统，用户无法清晰管理多套模板和执行取值。
- 真实浏览器 HUD 与 Agent 生命周期还需要做成常驻、可恢复、可解释。
- 免安装 EXE 还没有完成本轮版本级重新打包、桌面烟测和真实流程验收。
- 文档、脚本、最终交付报告仍有旧的 `controlled_single_save_only` 历史语义，需要按两段式生产路径统一。

---

## 1. 版本目标总览

### V1.0 产品壳收敛版

**目标:** 让用户一打开软件就理解这是“两段式真实店小秘只保存自动化”，不是测试台。

**完成标准:**
- 侧边栏按业务拆为：`首页`、`店小秘登录`、`数据采集认领`、`采集箱编辑保存`、`模板中心`、`执行浏览器`、`结果报告`、`问题处理`、`系统设置`。
- 首页只回答三件事：当前该做什么、为什么不能继续、点哪个按钮。
- 普通用户默认路径不显示：`QA`、`测试商品`、`L2`、`L3`、`probe`、`run-id`、`greenlet`、`HAR`。
- 技术信息只出现在 `系统设置` 或 `维护人员诊断` 折叠区。

### V1.1 数据采集认领版

**目标:** 第一段真实跑通：从店小秘数据采集页认领真实商品到采集箱，并生成可用于第二段的产品身份。

**完成标准:**
- 用户可创建“采集认领任务”，不是先选择本地商品。
- Agent 打开可见真实浏览器，进入店小秘数据采集页。
- Agent 搜索/定位目标采集商品。
- Agent 只执行认领到采集箱，不保存、不发布。
- 后端记录认领结果：店铺、平台、源标题、源链接、采集箱标题、认领时间、证据截图、只读/写入安全摘要。
- 认领成功后，第二段编辑保存才能选择该商品。

### V1.2 采集箱编辑保存版

**目标:** 第二段真实跑通：从采集箱打开商品编辑页，按模板填写并只点击保存。

**完成标准:**
- 只允许从 V1.1 认领成功的商品进入编辑保存。
- 运行前清楚展示：当前商品、店铺、模板、将填写哪些分区、只保存不发布。
- 保存前必须人工确认。
- Agent 只点击“保存”，不得点击“发布”“保存并发布”“移入待发布”。
- 结果报告必须包含：保存成功证据、未发布证据、失败时的中文恢复动作。

### V1.3 模板中心版

**目标:** 把配置中心升级为生产模板系统，支持多套模板、中文分区表单和执行取值预览。

**完成标准:**
- 用户能新建、复制、重命名、删除、选择模板。
- 用户能设置店铺默认模板、类目默认模板、单次任务模板。
- 模板分区按店小秘编辑页组织：基础信息、类目标题、SKU/价格/库存、图片素材、包装物流、合规海关、半托管、店小秘引用模板、执行策略。
- 字段全部中文展示，英文 key 只在维护诊断里出现。
- 页面始终显示：当前模板、是否已保存、执行会使用哪个值、值来自哪里。

### V1.4 真实浏览器 Agent 版

**目标:** 让真实浏览器变成生产级执行现场，而不是闪退、黑盒或截图展示。

**完成标准:**
- 浏览器显式常开，用户能看到 Agent 操作。
- 浏览器左上角常驻中文 HUD，显示：当前任务、当前步骤、正在做什么、失败原因、是否需要用户接管。
- HUD 不因页面跳转消失；消失后能自动注入恢复。
- Agent 进程异常退出时，主窗口能显示明确原因和恢复按钮。
- 执行过程日志按业务步骤输出，不再用重叠、难读的原始日志堆叠。

### V1.5 免安装交付版

**目标:** 输出客户可直接使用的免安装 EXE 和验收证据。

**完成标准:**
- 双击一个 EXE 启动主控制台，不弹两个服务窗口。
- 后端、前端、浏览器 Agent 生命周期由 Electron 管理。
- 账号密码可本机加密记住，重启后自动填入。
- `数据采集认领 -> 采集箱验证 -> 编辑保存 -> 未发布证明` 至少完成一次真实受控验收。
- 交付目录包含 EXE、resources、快速使用说明、故障处理说明、验收报告。

---

## 2. 文件结构与边界

### 前端页面边界

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\AppShell.tsx`
  - 负责主导航、分组、折叠态、aria 标签。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\App.tsx`
  - 负责页面路由、当前任务动作、启动任务动作。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\types.ts`
  - 负责两段式流程、模板、采集商品、保存任务类型。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\HomePage.tsx`
  - 负责首页当前步骤和下一步。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AcquisitionClaimPage.tsx`
  - 负责第一段数据采集认领。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\DraftEditSavePage.tsx`
  - 负责第二段采集箱编辑保存。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\EditConfigPage.tsx`
  - 逐步降级为模板中心兼容层。
- Create: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\TemplateCenterPage.tsx`
  - 负责模板列表、模板详情、分区表单、执行取值预览。
- Create: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\BrowserAgentPage.tsx`
  - 负责真实浏览器状态、HUD 状态、Agent 生命周期、接管恢复。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\ResultsPage.tsx`
  - 负责保存结果和未发布证明。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\styles.css`
  - 当前文件过大，按版本逐步抽离页面样式。

### 后端边界

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
  - 负责 API、任务启动门禁、桌面状态。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\repository.py`
  - 负责采集认领记录、模板记录、任务记录。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\v1_runner.py`
  - 负责两段式任务执行顺序。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
  - 负责真实店小秘页面操作。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_adapter.py`
  - 负责执行适配器方法。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\state_machine\contracts.py`
  - 负责状态契约。
- Create: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\template_center.py`
  - 负责模板解析、优先级、中文字段元数据、执行取值预览。
- Create: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\browser_agent_status.py`
  - 负责浏览器 Agent 状态、HUD 心跳、异常恢复建议。

### 测试边界

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_frontend_demo_workflow_contract.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_acquisition_claim_workflow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_task_start_guard.py`
- Add: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_template_center_contract.py`
- Add: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_browser_agent_status.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_desktop_package_contract.py`

---

## 3. 实施任务

### Task 1: 收敛导航与用户路径

**Files:**
- Modify: `app/frontend/src/components/AppShell.tsx`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/frontend/src/types.ts`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: 写失败测试**

在 `app/backend/tests/test_frontend_demo_workflow_contract.py` 增加：

```python
def test_sidebar_exposes_production_two_stage_workflow_only():
    source = (FRONTEND_SRC / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    for label in ["首页", "店小秘登录", "数据采集认领", "采集箱编辑保存", "模板中心", "执行浏览器", "结果报告", "问题处理", "系统设置"]:
        assert label in source
    forbidden = ["Agent 控制台", "证据中心", "异常池", "任务中心", "配置中心"]
    for label in forbidden:
        assert label not in source
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py::test_sidebar_exposes_production_two_stage_workflow_only -q
```

Expected: FAIL because old labels still exist or new labels are incomplete.

- [ ] **Step 3: 修改导航**

在 `AppShell.tsx` 把主导航改成：

```ts
const primaryAreas = [
  { id: 'home', label: '首页', group: '开始' },
  { id: 'dxm_access', label: '店小秘登录', group: '开始' },
  { id: 'acquisition_claim', label: '数据采集认领', group: '第一段' },
  { id: 'draft_edit_save', label: '采集箱编辑保存', group: '第二段' },
  { id: 'template_center', label: '模板中心', group: '配置' },
  { id: 'browser_agent', label: '执行浏览器', group: '执行' },
  { id: 'results', label: '结果报告', group: '复盘' },
  { id: 'issues', label: '问题处理', group: '复盘' },
  { id: 'system', label: '系统设置', group: '系统' },
]
```

- [ ] **Step 4: 路由兼容**

在 `App.tsx` 增加旧 section alias：

```ts
const normalizeSection = (section: string): AppSection => {
  const aliases: Record<string, AppSection> = {
    guide: 'home',
    config: 'template_center',
    edit_config: 'template_center',
    product_tasks: 'acquisition_claim',
    agent_console: 'browser_agent',
    real_browser: 'browser_agent',
    evidence: 'results',
    reports: 'results',
  }
  return aliases[section] ?? section as AppSection
}
```

- [ ] **Step 5: 复测并提交**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
cd ..\frontend
npm run build
git add app/frontend/src app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "feat: align sidebar with two-stage DXM workflow"
```

Expected: frontend contract and build pass.

### Task 2: 首页改成任务决策面板

**Files:**
- Modify: `app/frontend/src/components/workbench/HomePage.tsx`
- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: 写失败测试**

```python
def test_home_page_hides_technical_gate_language_from_default_path():
    source = (FRONTEND_SRC / "components" / "workbench" / "HomePage.tsx").read_text(encoding="utf-8")
    for forbidden in ["L2", "L3", "probe", "run-id", "HAR", "greenlet"]:
        assert forbidden not in source
    for required in ["现在该做什么", "为什么不能继续", "下一步"]:
        assert required in source
```

- [ ] **Step 2: 实现首页卡片**

首页只保留：

```ts
const decisionCards = [
  { title: '现在该做什么', value: currentAction },
  { title: '为什么不能继续', value: blockerReason || '没有阻断' },
  { title: '下一步', value: nextAction },
]
```

技术细节进入 `<details>`：

```tsx
<details className="maintenance-details">
  <summary>维护人员查看技术状态</summary>
  <TechnicalStatusPanel />
</details>
```

- [ ] **Step 3: 复测并提交**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
cd ..\frontend
npm run build
git add app/frontend/src/components/workbench/HomePage.tsx app/frontend/src/components/workbench/workbenchCopy.ts app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "feat: simplify DXM home decision flow"
```

### Task 3: 数据采集认领页面生产化

**Files:**
- Modify: `app/frontend/src/components/workbench/AcquisitionClaimPage.tsx`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/backend/src/main.py`
- Modify: `app/backend/src/repository.py`
- Modify: `app/backend/tests/test_acquisition_claim_workflow.py`
- Modify: `app/backend/tests/test_task_start_guard.py`

- [ ] **Step 1: 写后端契约测试**

```python
def test_acquisition_claim_creates_task_without_existing_product(repo):
    task = repo.create_acquisition_claim_request({
        "store_id": 1,
        "store_name": "Dang Kang",
        "platform": "AliExpress",
        "keyword": "real product keyword",
        "claim_mark": "AI-OPS",
    })
    assert task["mode"] == "claim_only"
    assert task["publish_scene"] == "CONTROLLED_CLAIM_TO_DRAFT_ONLY"
    jobs = repo.list_jobs(task["id"])
    assert len(jobs) == 1
    assert jobs[0]["product_id"] is None
```

- [ ] **Step 2: 写前端契约测试**

```python
def test_acquisition_page_describes_claim_to_draft_not_local_product_selection():
    source = (FRONTEND_SRC / "components" / "workbench" / "AcquisitionClaimPage.tsx").read_text(encoding="utf-8")
    for required in ["从数据采集认领到采集箱", "不会保存", "不会发布", "认领标记"]:
        assert required in source
    for forbidden in ["QA guarded product", "测试商品", "本地商品"]:
        assert forbidden not in source
```

- [ ] **Step 3: 页面主流程**

`AcquisitionClaimPage.tsx` 默认展示四步：

```ts
const steps = [
  '选择店铺与平台',
  '填写采集商品线索',
  '启动真实浏览器认领',
  '确认商品进入采集箱',
]
```

- [ ] **Step 4: API 返回用户可读错误**

`main.py` 中采集认领错误统一返回：

```python
raise HTTPException(
    status_code=409,
    detail={
        "title": "还不能开始采集认领",
        "what": "当前任务不是数据采集认领任务。",
        "why": "采集认领必须从数据采集页开始，不能使用已有本地商品。",
        "next": "请在“数据采集认领”页面重新创建任务。",
    },
)
```

- [ ] **Step 5: 复测并提交**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_task_start_guard.py tests\test_frontend_demo_workflow_contract.py -q
cd ..\frontend
npm run build
git add app/frontend/src app/backend/src app/backend/tests
git commit -m "feat: productionize acquisition claim workflow"
```

### Task 4: 采集箱编辑保存页面生产化

**Files:**
- Modify: `app/frontend/src/components/workbench/DraftEditSavePage.tsx`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/backend/src/main.py`
- Modify: `app/backend/src/execution/v1_runner.py`
- Modify: `app/backend/tests/test_v1_runner.py`
- Modify: `app/backend/tests/test_task_start_guard.py`

- [ ] **Step 1: 写保存阶段门禁测试**

```python
def test_single_save_requires_claimed_draft_product_before_browser_start(client, repo):
    product = repo.create_product({"title": "local product", "status": "draft"})
    task = repo.create_task({"mode": "single_save", "product_ids": [product["id"]]})
    response = client.post(f"/api/tasks/{task['id']}/start", json={})
    assert response.status_code == 409
    assert "请先完成采集认领" in response.json()["detail"]
```

- [ ] **Step 2: 页面主流程**

`DraftEditSavePage.tsx` 默认展示：

```ts
const saveSteps = [
  '选择已进入采集箱的商品',
  '确认本次使用的模板',
  '人工确认只保存',
  '启动 Agent 保存',
  '查看保存结果',
]
```

- [ ] **Step 3: 发布词硬阻断文案**

用户看到：

```text
本功能只点击“保存”。如果页面出现“发布”“保存并发布”“移入待发布”，系统会停止并要求人工处理。
```

- [ ] **Step 4: 复测并提交**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_v1_runner.py tests\test_task_start_guard.py -q
cd ..\frontend
npm run build
git add app/frontend/src app/backend/src app/backend/tests
git commit -m "feat: require claimed draft product for save-only workflow"
```

### Task 5: 模板中心多模板与中文分区表单

**Files:**
- Create: `app/backend/src/services/template_center.py`
- Add: `app/backend/tests/test_template_center_contract.py`
- Create: `app/frontend/src/components/workbench/TemplateCenterPage.tsx`
- Modify: `app/frontend/src/components/workbench/EditConfigPage.tsx`
- Modify: `app/frontend/src/types.ts`
- Modify: `app/frontend/src/App.tsx`

- [ ] **Step 1: 写模板优先级测试**

```python
def test_template_resolution_priority_uses_task_then_category_then_store_then_system():
    from src.services.template_center import resolve_template

    resolved = resolve_template(
        task_template={"id": "task", "name": "本次任务模板"},
        selected_template=None,
        category_template={"id": "cat", "name": "类目模板"},
        store_template={"id": "store", "name": "店铺模板"},
        system_template={"id": "system", "name": "系统默认模板"},
    )
    assert resolved["id"] == "task"
    assert resolved["source_label"] == "本次任务覆盖"
```

- [ ] **Step 2: 写中文字段测试**

```python
def test_template_fields_have_chinese_labels_and_sections():
    from src.services.template_center import editable_sections

    sections = editable_sections()
    labels = [field["label"] for section in sections for field in section["fields"]]
    assert "店铺" in labels
    assert "绑定类目" in labels
    assert "认领标记" in labels
    assert all("_" not in field["label"] for section in sections for field in section["fields"])
```

- [ ] **Step 3: 实现模板服务**

`template_center.py` 提供：

```python
def editable_sections() -> list[dict]:
    return [
        {"id": "basis", "label": "店铺与任务基础", "fields": [
            {"key": "store_name", "label": "店铺", "required": True},
            {"key": "category_name", "label": "绑定类目", "required": True},
            {"key": "claim_mark", "label": "认领标记", "required": True},
        ]},
        {"id": "title", "label": "类目与标题", "fields": [
            {"key": "title_prefix", "label": "标题前缀", "required": False},
            {"key": "title_suffix", "label": "标题后缀", "required": False},
        ]},
        {"id": "sku_price_stock", "label": "SKU / 价格 / 库存", "fields": [
            {"key": "stock", "label": "库存", "required": False},
            {"key": "price_strategy", "label": "价格策略", "required": False},
        ]},
        {"id": "media", "label": "图片与素材", "fields": [
            {"key": "main_image_policy", "label": "主图处理", "required": False},
            {"key": "eu_outer_package_image", "label": "欧盟外包装图", "required": True},
        ]},
        {"id": "logistics", "label": "包装物流", "fields": [
            {"key": "logistics_type", "label": "物流属性", "required": True},
        ]},
        {"id": "compliance", "label": "合规 / 海关", "fields": [
            {"key": "customs_cn_name", "label": "海关中文名", "required": False},
            {"key": "customs_en_name", "label": "海关英文名", "required": False},
        ]},
        {"id": "semi_managed", "label": "半托管", "fields": [
            {"key": "semi_managed_template", "label": "半托管模板", "required": True},
        ]},
        {"id": "dxm_reference", "label": "店小秘引用模板", "fields": [
            {"key": "dxm_product_template_name", "label": "产品引用模板", "required": False},
            {"key": "dxm_logistics_template_name", "label": "物流引用模板", "required": False},
        ]},
    ]
```

- [ ] **Step 4: 实现模板页面**

`TemplateCenterPage.tsx` 默认布局：

```tsx
<TemplateHeader currentTemplate={template} dirty={dirty} appliedSource={source} />
<TemplateSectionTabs sections={sections} activeSection={activeSection} />
<SectionForm section={activeSection} values={values} sources={sources} />
<ExecutionValuePreview collapsedByDefault />
```

页面动作固定为：

```text
仅本次任务使用
保存为店铺模板
另存为新模板
套用默认测试模板
```

- [ ] **Step 5: 复测并提交**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_template_center_contract.py tests\test_config_validation.py tests\test_task_start_guard.py -q
cd ..\frontend
npm run build
git add app/backend/src/services/template_center.py app/backend/tests/test_template_center_contract.py app/frontend/src
git commit -m "feat: add production template center"
```

### Task 6: 真实浏览器 HUD 常驻与 Agent 生命周期

**Files:**
- Create: `app/backend/src/services/browser_agent_status.py`
- Add: `app/backend/tests/test_browser_agent_status.py`
- Modify: `app/backend/src/execution/dxm_login_flow.py`
- Modify: `app/backend/src/execution/v1_runner.py`
- Create: `app/frontend/src/components/workbench/BrowserAgentPage.tsx`
- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`

- [ ] **Step 1: 写 HUD 状态测试**

```python
def test_browser_agent_status_maps_runner_step_to_chinese_hud():
    from src.services.browser_agent_status import build_browser_hud

    hud = build_browser_hud({
        "task_name": "采集箱编辑保存",
        "step": "FILL_TITLE",
        "status": "running",
    })
    assert hud["title"] == "正在编辑商品"
    assert hud["line1"] == "正在填写标题"
    assert hud["severity"] == "running"
```

- [ ] **Step 2: 实现状态映射**

`browser_agent_status.py` 提供固定映射：

```python
STEP_COPY = {
    "OPEN_DATA_ACQUISITION": ("正在打开数据采集", "进入店小秘数据采集页"),
    "CLAIM_TO_DRAFT_BOX": ("正在认领商品", "把当前商品认领到采集箱"),
    "VERIFY_DRAFT_BOX_CLAIM": ("正在确认采集箱", "检查商品是否已进入采集箱"),
    "OPEN_EDITOR": ("正在打开编辑页", "进入采集箱商品编辑页"),
    "FILL_TITLE": ("正在编辑商品", "正在填写标题"),
    "FILL_IMAGES": ("正在编辑商品", "正在处理图片"),
    "SAVE_ONLY": ("正在只保存", "只点击保存，不发布"),
    "VERIFY_NOT_PUBLISHED": ("正在检查结果", "确认商品没有发布"),
}
```

- [ ] **Step 3: HUD 心跳**

后端每个 runner step 写入：

```python
agent_console_service.update_hud({
    "task_id": task_id,
    "step": state,
    "status": "running",
    "updated_at": datetime.now(timezone.utc).isoformat(),
})
```

- [ ] **Step 4: 页面跳转后重注入**

`dxm_login_flow.py` 每次 `goto`、弹窗处理、编辑页切换后调用：

```python
self._ensure_browser_hud(page, current_hud_payload)
```

- [ ] **Step 5: 复测并提交**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_browser_agent_status.py tests\test_agent_console.py tests\test_v1_runner.py -q
cd ..\frontend
npm run build
git add app/backend/src app/backend/tests app/frontend/src
git commit -m "feat: keep browser agent HUD alive"
```

### Task 7: 日志与问题处理用户化

**Files:**
- Modify: `app/frontend/src/components/workbench/IssuesPage.tsx`
- Modify: `app/frontend/src/components/workbench/ResultsPage.tsx`
- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`
- Modify: `app/backend/src/main.py`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: 写错误文案测试**

```python
def test_default_error_copy_uses_user_recovery_structure():
    source = (FRONTEND_SRC / "components" / "workbench" / "workbenchCopy.ts").read_text(encoding="utf-8")
    for required in ["发生了什么", "为什么会停止", "下一步怎么做"]:
        assert required in source
    for forbidden in ["greenlet", "Cannot switch to a different thread", "Internal Server Error"]:
        assert forbidden not in source
```

- [ ] **Step 2: 标准错误结构**

前后端统一错误结构：

```ts
type UserFacingProblem = {
  title: string
  what: string
  why: string
  next: string
  maintenanceDetail?: string
}
```

- [ ] **Step 3: 日志卡片规则**

实时日志默认只显示 8 条业务日志：

```text
已打开真实浏览器
正在进入数据采集
已找到目标商品
正在认领到采集箱
已进入采集箱
正在打开编辑页
正在只保存
保存完成
```

完整原始日志进入：

```tsx
<details>
  <summary>维护人员查看完整原始日志</summary>
  <RawLogViewer />
</details>
```

- [ ] **Step 4: 复测并提交**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py tests\test_agent_console.py -q
cd ..\frontend
npm run build
git add app/frontend/src app/backend/src app/backend/tests
git commit -m "feat: present DXM failures as recoverable user problems"
```

### Task 8: 免安装 EXE 验收与文档

**Files:**
- Modify: `README.md`
- Modify: `docs/product/免安装版快速使用说明-20260615.md`
- Modify: `docs/product/用户交付使用说明-20260526.md`
- Modify: `scripts/verify-desktop-package.ps1`
- Modify: `scripts/final-delivery-check.ps1`
- Modify: `app/backend/tests/test_desktop_package_contract.py`

- [ ] **Step 1: 更新桌面包契约测试**

```python
def test_desktop_package_docs_describe_two_stage_real_browser_flow():
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    for required in ["数据采集认领", "采集箱编辑保存", "只保存，不发布", "真实浏览器"]:
        assert required in text
```

- [ ] **Step 2: 打包前验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
cd ..\desktop
npm run build:portable
```

Expected:
- Backend tests pass.
- Frontend build passes.
- Portable EXE exists under desktop release output.

- [ ] **Step 3: 桌面包验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

Expected:
- EXE can start.
- Backend is reachable.
- Frontend does not report Electron `file://` as abnormal.
- No second console window remains as main operation interface.

- [ ] **Step 4: 真实验收**

Manual/browser-backed acceptance:

```text
1. 打开免安装 EXE。
2. 登录店小秘，确认账号可记住。
3. 创建数据采集认领任务。
4. 真实浏览器进入数据采集页并完成认领。
5. 系统确认商品进入采集箱。
6. 选择该采集箱商品进入编辑保存。
7. 选择模板并人工确认只保存。
8. Agent 执行保存。
9. 报告显示保存成功且未发布。
```

- [ ] **Step 5: 输出交付目录**

交付目录固定为：

```text
D:\Desktop\DXM-Agent-Console-免安装版
```

目录必须包含：

```text
DXM-Agent-Console.exe
resources\
快速使用说明.md
故障处理说明.md
验收报告.json
```

- [ ] **Step 6: 最终提交**

Run:

```powershell
git status --short
git add README.md docs/product scripts app/backend/tests/test_desktop_package_contract.py
git commit -m "docs: update DXM portable delivery guide"
```

---

## 4. 版本验收门槛

### 代码验收

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
cd ..\desktop
npm run build:portable
```

### 产品验收

- 普通用户首屏不出现工程术语。
- 菜单能解释完整业务路径。
- 用户不需要理解 `claim_only`、`single_save`、`L2`、`L3` 才能操作。
- 两段式路径能真实走通。
- 浏览器可见、常开、HUD 常驻。
- 失败可恢复，且说明是中文业务语言。

### 安全验收

- 发布入口不可见。
- API 仍阻断发布、批量、无人值守。
- 保存动作只允许单商品、采集箱已验证商品、人工确认后执行。
- 报告必须包含未发布证明。

### 交付验收

- 一个免安装 EXE 可启动。
- 不依赖开发者打开两个命令行窗口。
- 本机加密保存账号密码。
- 交付目录完整。
- 验收报告路径明确。

---

## 5. 任务完成定义

这个项目不能只按“代码写完”算完成。最终完成必须同时满足：

1. **流程正确:** 真实路径是 `数据采集认领 -> 采集箱编辑保存`，没有绕回本地测试商品。
2. **真实可跑:** 使用免安装 EXE 能完成至少一次真实受控验收。
3. **用户能懂:** 普通运营用户不需要理解技术门禁就知道下一步怎么做。
4. **错误可恢复:** 失败页说明发生了什么、为什么停止、下一步点哪里。
5. **浏览器可信:** 真实浏览器可见、HUD 常驻、Agent 不黑盒闪退。
6. **配置可控:** 多模板、中文分区、保存状态、执行取值都清晰。
7. **边界安全:** 发布、批量、无人值守仍被 UI 和 API 双层阻断。
8. **交付完整:** EXE、resources、说明文档、验收报告和构建脚本都一致。

只有以上 8 项都通过，才可以称为“生产级可交付版本”。
