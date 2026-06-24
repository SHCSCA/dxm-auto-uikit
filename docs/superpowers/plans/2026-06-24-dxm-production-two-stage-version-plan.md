# DXM Production Two Stage Version Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DXM Agent Console 做成生产级两段式真实店小秘自动化产品：第一段从数据采集认领到采集箱，第二段从采集箱编辑商品并只保存。

**Architecture:** 继续使用现有 React/Vite/Electron/FastAPI/Playwright 架构，不重写技术栈。产品层按业务阶段拆分，普通用户只看到“登录、认领、配置、保存、结果”，技术门禁、日志、路径、run-id 和证据细节统一下沉到维护诊断。

**Tech Stack:** React 18 + TypeScript + Vite, Electron portable desktop, FastAPI, SQLite repository, Playwright headed browser automation, pytest contract tests, PowerShell desktop package verification.

---

## 0. Current Execution Index

**Authoritative product plan:** `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\DXM-Agent-Console-生产级版本计划-20260624.md`

**Current branch:** `feature/dxm-production-two-stage`

**Current product completion estimate:** 68%

**Already completed in this branch:**

- Production sidebar is moving toward user-facing two-stage workflow language.
- The template center has been changed from a dense configuration screen into sectioned Chinese forms.
- Default test/template values are exposed as a selectable starting template, not as proof of real production readiness.
- Template metadata is aligned with config preview fields.
- Frontend build and focused backend template/frontend contract tests passed after the template-center slice.

**Next implementation task:** continue with V1.4 real browser Agent stability:

1. Confirm whether the task browser and Agent Console browser use the same persistent session.
2. Keep the main window polling task state while a task is running.
3. Preserve browser state on Agent failure instead of allowing a silent close.
4. Keep the in-browser Chinese HUD resident through navigation and page changes.
5. Hide raw technical errors from the normal user path and move them into maintenance diagnostics.

---

## 1. 版本总目标

### V0.9 交付壳收口版

**目的:** 让当前免安装版不再像测试台，能稳定启动、能解释状态、能避免用户走错入口。

**用户可感知结果:**
- 双击 EXE 进入主控制台，不再需要用户理解后端/前端两个服务窗口。
- 首页明确显示当前只支持“两段式单商品只保存”：先认领到采集箱，再从采集箱编辑保存。
- 页面不再出现默认测试商品作为真实执行入口。
- 报错统一翻译成“发生了什么 / 为什么停止 / 下一步怎么做”。

**验收标准:**
- `D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe` 可启动。
- `scripts\verify-desktop-package.ps1 -CheckPortable` 通过。
- README、快速使用说明、用户交付说明、验收报告里的 Git HEAD、SHA、版本边界一致。

### V1.0 两段式生产主路径版

**目的:** 用真实店小秘浏览器完成可验收的主路径。

**用户可感知结果:**
- 菜单固定为：`首页`、`店小秘登录`、`数据采集认领`、`采集箱编辑保存`、`模板中心`、`执行浏览器`、`结果与问题`、`系统设置`。
- 第一段只负责从数据采集页把商品认领到采集箱。
- 第二段只负责从采集箱打开商品编辑页并只点击保存。
- 任何发布、批量、无人值守入口都不可见且后端继续阻断。

**验收标准:**
- 真实浏览器完成一次：数据采集认领 -> 采集箱确认。
- 真实浏览器完成一次：采集箱商品打开编辑页 -> 按模板填写 -> 只保存 -> 未发布证明。
- 报告能关联同一个商品的第一段和第二段证据。

### V1.1 模板中心生产版

**目的:** 配置不再是写死的测试数据，而是可被运营维护的多套中文模板。

**用户可感知结果:**
- 支持多套模板：店铺默认、类目默认、本次任务、手动选择模板。
- 表单按店小秘编辑页分区：店铺与任务基础、类目与标题、SKU/价格/库存、图片素材、包装物流、合规海关、半托管、店小秘引用模板、执行策略。
- 所有字段中文化，英文 key 只在维护诊断里显示。
- 页面始终显示当前模板是否已保存、执行实际会取哪个值、值来自哪里。

**验收标准:**
- 新建、复制、重命名、停用模板可用。
- 执行保存前能预览最终填充值。
- 空字段、缺失模板、冲突模板都有中文提示和修复动作。

### V1.2 浏览器 Agent 生产版

**目的:** 让用户能看见真实浏览器正在做什么，Agent 不再像黑盒。

**用户可感知结果:**
- 浏览器显式常开。
- 浏览器左上角常驻黑色中文进度窗，显示“正在打开数据采集 / 正在认领 / 正在填写标题 / 正在只保存”等业务步骤。
- 页面跳转后 HUD 自动恢复。
- 浏览器或 Agent 异常退出时，主窗口能看到明确原因和恢复按钮。

**验收标准:**
- HUD 经历至少 5 次页面跳转仍常驻。
- Agent 崩溃、浏览器关闭、登录失效、验证码等待都能进入可恢复状态。
- 日志默认显示业务摘要，完整原始日志只在维护诊断中显示。

### V1.3 客户自助版

**目的:** 普通运营用户无需开发者协助也能完成日常单商品只保存。

**用户可感知结果:**
- 首次打开有简短向导，不需要读长文档。
- 账号密码本机加密记住。
- 任务失败后能按页面提示恢复，不需要看日志。
- 系统能判断“现在卡在登录、采集认领、模板缺失、只保存确认、浏览器异常”哪一步。

**验收标准:**
- 新用户按 UI 引导可在 15 分钟内完成一次受控单商品只保存。
- 失败场景至少覆盖：未登录、验证码未处理、未选择商品、模板缺失、浏览器关闭、保存未成功、出现发布风险。

### V2.0 扩展能力版

**目的:** 在 V1.x 稳定后再开放更高风险能力。

**开放顺序:**
1. 批量只保存小批量灰度。
2. 多店铺模板继承。
3. 半自动异常重试。
4. 团队权限和操作记录。
5. 无人值守。

**硬边界:** V2.0 之前不开放发布、不开放无人值守、不开放批量生产写入。

---

## 2. 当前代码边界

### 前端核心文件

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\AppShell.tsx`
  - 侧边栏、分组、菜单文案。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\SafetyStatusBar.tsx`
  - 顶部状态条和下一步按钮。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\App.tsx`
  - 页面路由、任务创建、任务启动动作。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\HomePage.tsx`
  - 首页当前步骤和下一步。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\DxmAccessPage.tsx`
  - 店小秘登录和账号记住。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AcquisitionClaimPage.tsx`
  - 数据采集认领。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\DraftEditSavePage.tsx`
  - 采集箱编辑保存。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\TemplateCenterPage.tsx`
  - 多模板管理和中文分区表单。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AgentExecutionPage.tsx`
  - 执行浏览器、实时日志、Agent 状态。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\ResultsPage.tsx`
  - 保存结果、未发布证明、问题处理入口。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\types.ts`
  - 两段式流程、模板、任务、Agent 状态类型。

### 后端核心文件

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
  - API、启动门禁、错误结构。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\repository.py`
  - 任务、商品、模板、认领记录。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\v1_runner.py`
  - `claim_only` 和 `single_save` 执行流程。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
  - 真实店小秘页面操作。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\agent_console.py`
  - 浏览器会话、HUD 注入、Agent 生命周期。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\browser_agent_status.py`
  - 中文 HUD 状态映射。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\template_center.py`
  - 模板优先级、字段元数据、执行取值。
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\desktop\src\main.cjs`
  - 桌面启动、后端进程、资源路径、账号本机加密。

### 测试文件

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_frontend_demo_workflow_contract.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_acquisition_claim_workflow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_task_start_guard.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_template_center_contract.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_desktop_package_contract.py`

---

## 3. 实施任务

### Task 1: V0.9 交付壳收口

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\README.md`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\免安装版快速使用说明-20260615.md`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\用户交付使用说明-20260526.md`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\最终交付验收记录-20260623-桌面包.md`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_desktop_package_contract.py`

- [ ] **Step 1: 写桌面包文档契约测试**

Add this test to `app/backend/tests/test_desktop_package_contract.py`:

```python
def test_delivery_docs_describe_two_stage_real_browser_scope():
    root = Path(__file__).resolve().parents[2].parents[0]
    docs = [
        root / "README.md",
        root / "docs" / "product" / "免安装版快速使用说明-20260615.md",
        root / "docs" / "product" / "用户交付使用说明-20260526.md",
    ]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "数据采集认领" in text
        assert "采集箱编辑保存" in text
        assert "只保存" in text
        assert "不发布" in text
        assert "真实浏览器" in text
        assert "本地测试商品" not in text
```

- [ ] **Step 2: 运行测试确认当前文档缺口**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_desktop_package_contract.py::test_delivery_docs_describe_two_stage_real_browser_scope -q
```

Expected: FAIL if any old delivery doc still uses single-save-only or test fixture wording.

- [ ] **Step 3: 更新文档版本边界**

Replace old scope with:

```text
当前交付范围：真实店小秘两段式受控单商品只保存。
第一段：从数据采集页认领真实商品到采集箱。
第二段：从采集箱打开编辑页，按模板填写后只点击保存。
禁止范围：发布、保存并发布、移入待发布、批量无人值守。
```

- [ ] **Step 4: 复测桌面包**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

Expected: all package smoke checks pass.

- [ ] **Step 5: 提交**

Run:

```powershell
git add README.md docs/product app/backend/tests/test_desktop_package_contract.py
git commit -m "docs: align portable delivery docs with two-stage DXM workflow"
```

### Task 2: V1.0 导航和首屏决策重构

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\AppShell.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\SafetyStatusBar.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\HomePage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: 写导航契约测试**

Add:

```python
def test_sidebar_uses_customer_two_stage_navigation():
    source = (FRONTEND_SRC / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    expected = ["首页", "店小秘登录", "数据采集认领", "采集箱编辑保存", "模板中心", "执行浏览器", "结果与问题", "系统设置"]
    for label in expected:
        assert label in source
    forbidden = ["Agent 控制台", "证据中心", "异常池", "任务中心", "配置中心"]
    for label in forbidden:
        assert label not in source
```

- [ ] **Step 2: 写首屏术语契约测试**

Add:

```python
def test_home_default_path_hides_technical_gate_terms():
    source = (FRONTEND_SRC / "components" / "workbench" / "HomePage.tsx").read_text(encoding="utf-8")
    for required in ["现在该做什么", "为什么不能继续", "下一步"]:
        assert required in source
    for forbidden in ["L2", "L3", "probe", "run-id", "HAR", "greenlet"]:
        assert forbidden not in source
```

- [ ] **Step 3: 实现首页决策卡片**

Use this default structure in `HomePage.tsx`:

```tsx
const decisionCards = [
  { label: '现在该做什么', value: currentAction },
  { label: '为什么不能继续', value: blockerReason || '没有阻断' },
  { label: '下一步', value: nextAction },
]
```

- [ ] **Step 4: 技术细节下沉**

Move diagnostics under:

```tsx
<details className="maintenance-details">
  <summary>维护人员查看技术状态</summary>
  <TechnicalStatusPanel />
</details>
```

- [ ] **Step 5: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
cd ..\frontend
npm run build
```

Expected: tests and frontend build pass.

- [ ] **Step 6: 提交**

```powershell
git add app/frontend/src app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "feat: simplify production navigation and first screen"
```

### Task 3: V1.0 第一段数据采集认领闭环

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AcquisitionClaimPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\repository.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_acquisition_claim_workflow.py`

- [ ] **Step 1: 写任务创建测试**

Add:

```python
def test_acquisition_claim_request_is_not_local_product_task(client):
    response = client.post("/api/acquisition-claims", json={
        "storeId": 1,
        "keyword": "真实采集商品关键词",
        "categoryName": "立牌类谷子",
        "claimMark": "AI-OPS",
    })
    assert response.status_code in (200, 201)
    payload = response.json()
    assert payload["task_id"]
    assert payload["stage"] in ("pending", "data_acquisition")
```

- [ ] **Step 2: 写认领完成测试**

Add:

```python
def test_claim_only_completion_records_claimed_draft_identity(repo, fake_claim_adapter):
    task = repo.create_task({
        "name": "数据采集认领",
        "mode": "claim_only",
        "publish_scene": "CONTROLLED_CLAIM_TO_DRAFT_ONLY",
        "payload": {"keyword": "真实商品", "claim_mark": "AI-OPS"},
    })
    result = run_task_with_adapter(repo, task["id"], fake_claim_adapter)
    updated = repo.get_task(task["id"])
    assert result["status"] == "completed"
    assert updated["payload"]["claimed_product_id"]
    assert updated["payload"]["next_step"] == "draft_edit_save"
```

- [ ] **Step 3: 页面只展示采集认领**

`AcquisitionClaimPage.tsx` primary copy:

```text
第一段：从数据采集认领到采集箱
这里只会打开真实店小秘数据采集页并认领商品，不保存、不发布。
```

- [ ] **Step 4: 禁止测试商品入口**

Remove customer-visible wording:

```text
QA guarded product
测试商品
本地商品
```

- [ ] **Step 5: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_v1_runner.py -q
cd ..\frontend
npm run build
```

Expected: claim-only tests and frontend build pass.

- [ ] **Step 6: 提交**

```powershell
git add app/frontend/src app/backend/src app/backend/tests
git commit -m "feat: close acquisition claim stage"
```

### Task 4: V1.0 第二段采集箱编辑保存闭环

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\DraftEditSavePage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_task_start_guard.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_v1_runner.py`

- [ ] **Step 1: 写保存启动门禁测试**

Add:

```python
def test_single_save_requires_claimed_draft_product(client, repo):
    task = repo.create_task({
        "name": "采集箱编辑保存",
        "mode": "single_save",
        "publish_scene": "CONTROLLED_SINGLE_SAVE_ONLY",
        "payload": {"product_ids": [1]},
    })
    response = client.post(f"/api/tasks/{task['id']}/start", json={})
    assert response.status_code == 409
    assert "请先完成数据采集认领" in response.text
```

- [ ] **Step 2: 写人工确认测试**

Add:

```python
def test_single_save_requires_manual_approval_after_template_ready(client, repo):
    task = repo.create_task({
        "name": "采集箱编辑保存",
        "mode": "single_save",
        "publish_scene": "CONTROLLED_SINGLE_SAVE_ONLY",
        "payload": {"claimed_product_id": 10, "stage": "claimed_to_draft"},
    })
    response = client.post(f"/api/tasks/{task['id']}/start", json={})
    assert response.status_code == 409
    assert "人工确认" in response.text
```

- [ ] **Step 3: 页面展示五步**

Use:

```ts
const saveSteps = [
  '选择采集箱商品',
  '确认本次模板',
  '人工确认只保存',
  '启动 Agent 保存',
  '查看保存结果',
]
```

- [ ] **Step 4: 保存边界说明**

Use customer copy:

```text
系统只点击“保存”。如果页面出现“发布”“保存并发布”“移入待发布”，Agent 会停止并要求人工处理。
```

- [ ] **Step 5: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_task_start_guard.py tests\test_v1_runner.py -q
cd ..\frontend
npm run build
```

- [ ] **Step 6: 提交**

```powershell
git add app/frontend/src app/backend/src app/backend/tests
git commit -m "feat: guard draft edit save stage"
```

### Task 5: V1.1 模板中心生产化

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\template_center.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_template_center_contract.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\TemplateCenterPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\types.ts`

- [ ] **Step 1: 写多模板优先级测试**

Add:

```python
def test_template_priority_uses_task_selected_category_store_system():
    from src.services.template_center import resolve_template

    result = resolve_template(
        task_template={"id": "task", "template_name": "本次任务模板"},
        selected_template={"id": "selected", "template_name": "手动选择模板"},
        category_template={"id": "category", "template_name": "类目模板"},
        store_template={"id": "store", "template_name": "店铺模板"},
        system_template={"id": "system", "template_name": "系统默认模板"},
    )
    assert result["id"] == "task"
    assert result["source_label"] == "本次任务覆盖"
```

- [ ] **Step 2: 写中文字段测试**

Add:

```python
def test_template_center_fields_are_chinese_for_customer_ui():
    from src.services.template_center import editable_sections

    sections = editable_sections()
    section_labels = [section["label"] for section in sections]
    for label in ["店铺与任务基础", "类目与标题", "SKU / 价格 / 库存", "图片与素材", "包装物流", "合规 / 海关", "半托管", "店小秘引用模板"]:
        assert label in section_labels
    for section in sections:
        for field in section["fields"]:
            assert "_" not in field["label"]
```

- [ ] **Step 3: 实现模板页面状态条**

`TemplateCenterPage.tsx` top summary:

```tsx
<div className="template-status-strip">
  <span>当前模板：{currentTemplateName}</span>
  <span>保存状态：{dirty ? '有未保存修改' : '已保存'}</span>
  <span>执行取值：{previewReady ? '可预览' : '待补齐'}</span>
</div>
```

- [ ] **Step 4: 分区表单只展开一个分区**

```tsx
{sections.map((section) => (
  <button
    type="button"
    aria-current={section.id === activeSectionId ? 'step' : undefined}
    onClick={() => setActiveSectionId(section.id)}
  >
    {section.label}
  </button>
))}
<SectionForm section={activeSection} />
```

- [ ] **Step 5: 模板动作固定**

```tsx
<button>仅本次任务使用</button>
<button>保存为店铺模板</button>
<button>另存为新模板</button>
<button>套用默认测试模板</button>
```

- [ ] **Step 6: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_template_center_contract.py tests\test_config_validation.py -q
cd ..\frontend
npm run build
```

- [ ] **Step 7: 提交**

```powershell
git add app/backend/src/services/template_center.py app/backend/tests/test_template_center_contract.py app/frontend/src
git commit -m "feat: productionize template center"
```

### Task 6: V1.2 浏览器 HUD 和 Agent 常驻

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\browser_agent_status.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AgentExecutionPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_browser_agent_status.py`

- [ ] **Step 1: 写中文 HUD 映射测试**

Add:

```python
def test_hud_step_copy_uses_business_chinese():
    from src.services.browser_agent_status import build_browser_hud

    hud = build_browser_hud({"step": "CLAIM_TO_DRAFT_BOX", "status": "running"})
    assert hud["title"] == "正在认领商品"
    assert hud["line1"] == "把当前商品认领到采集箱"
    assert hud["severity"] == "running"
```

- [ ] **Step 2: 写 HUD 重注入测试**

Add:

```python
def test_agent_console_hud_script_contains_persistent_mount_id():
    from src.services.agent_console import build_hud_injection_script

    script = build_hud_injection_script({"title": "正在认领商品"})
    assert "dxm-agent-hud-root" in script
    assert "position: fixed" in script
    assert "z-index" in script
```

- [ ] **Step 3: 状态映射**

`browser_agent_status.py` mapping:

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

- [ ] **Step 4: 页面跳转后重注入**

In `dxm_login_flow.py`, after every navigation or page switch:

```python
self._ensure_browser_hud(page, self._current_hud_payload())
```

- [ ] **Step 5: AgentExecutionPage 默认显示业务状态**

Default visible log categories:

```ts
const visibleLogTags = ['任务', '浏览器 Agent']
const maxVisibleLogs = 8
```

- [ ] **Step 6: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_agent_console.py tests\test_browser_agent_status.py -q
cd ..\frontend
npm run build
```

- [ ] **Step 7: 提交**

```powershell
git add app/backend/src app/backend/tests app/frontend/src
git commit -m "feat: keep real browser agent visible and explainable"
```

### Task 7: V1.3 用户化错误和恢复动作

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\workbenchCopy.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\IssuesPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\ResultsPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: 写错误文案契约测试**

Add:

```python
def test_customer_error_copy_uses_recovery_structure():
    source = (FRONTEND_SRC / "components" / "workbench" / "workbenchCopy.ts").read_text(encoding="utf-8")
    for required in ["发生了什么", "为什么停止", "下一步怎么做"]:
        assert required in source
    for forbidden in ["Internal Server Error", "greenlet", "Cannot switch to a different thread"]:
        assert forbidden not in source
```

- [ ] **Step 2: 定义错误结构**

`types.ts`:

```ts
export type UserFacingProblem = {
  title: string
  what: string
  why: string
  next: string
  maintenanceDetail?: string
}
```

- [ ] **Step 3: 后端错误返回**

`main.py`:

```python
def user_problem(title: str, what: str, why: str, next_step: str, maintenance_detail: str | None = None) -> dict:
    return {
        "title": title,
        "what": what,
        "why": why,
        "next": next_step,
        "maintenanceDetail": maintenance_detail,
    }
```

- [ ] **Step 4: 结果页默认展示用户问题**

```tsx
<ProblemCard
  title={problem.title}
  what={problem.what}
  why={problem.why}
  next={problem.next}
/>
```

- [ ] **Step 5: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py tests\test_frontend_api_error_contract.py -q
cd ..\frontend
npm run build
```

- [ ] **Step 6: 提交**

```powershell
git add app/frontend/src app/backend/src app/backend/tests
git commit -m "feat: translate runtime failures into user recovery steps"
```

### Task 8: V1.0 到 V1.3 真实验收

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\scripts\final-delivery-check.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\scripts\verify-desktop-package.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\最终交付验收记录-20260623-桌面包.md`

- [ ] **Step 1: 全量自动测试**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
cd ..\desktop
npm run build:portable
```

Expected: pytest, frontend build, portable build all pass.

- [ ] **Step 2: 桌面包验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

Expected: packaged backend resource, packaged smoke, credential smoke, visible window smoke, portable smoke all pass.

- [ ] **Step 3: 真实 DXM 验收**

Manual acceptance:

```text
1. 打开免安装 EXE。
2. 确认店小秘账号自动填充或可手动登录。
3. 在“数据采集认领”创建真实采集认领任务。
4. 真实浏览器完成认领到采集箱。
5. 在“采集箱编辑保存”选择已认领商品。
6. 在“模板中心”确认本次模板和执行取值。
7. 人工批准只保存。
8. Agent 在真实浏览器执行只保存。
9. “结果与问题”显示保存成功和未发布证明。
```

- [ ] **Step 4: 更新验收报告**

Report must include:

```json
{
  "scope": "controlled_two_stage_single_product_save_only",
  "claim_to_draft": "passed",
  "draft_edit_save": "passed",
  "published": false,
  "batch_unattended_publish_allowed": false
}
```

- [ ] **Step 5: 提交并推送**

Run:

```powershell
git add scripts docs/product
git commit -m "docs: record two-stage DXM desktop acceptance"
git push
```

---

## 4. 完成判定

任务只有在下面全部满足时才算完成：

1. 用户路径正确：第一段是数据采集认领，第二段是采集箱编辑保存。
2. 真实浏览器可见：用户能看到浏览器操作和中文 HUD。
3. 真实链路跑通：完成一次真实 DXM 认领到采集箱，再完成一次真实只保存。
4. 模板可生产使用：支持多套模板、中文分区、保存状态、执行取值预览。
5. 错误可恢复：失败页不显示原始异常作为主信息，显示中文恢复动作。
6. 安全边界保持：发布、保存并发布、移入待发布、批量、无人值守仍阻断。
7. EXE 可交付：免安装包、resources、说明、故障处理、验收报告齐全。
8. 证据一致：Git HEAD、EXE hash、测试结果、真实验收记录一致。

---

## 5. 推荐执行顺序

1. 先完成 V0.9：文档和免安装包证据收口。
2. 再完成 V1.0：两段式真实流程闭环。
3. 再完成 V1.1：模板中心生产化。
4. 再完成 V1.2：浏览器 HUD 和 Agent 生命周期。
5. 最后做 V1.3：自助使用体验和错误恢复。

每个 Task 独立提交一次。每个 Task 完成后至少运行对应 pytest 和 `npm run build`，涉及桌面包时额外运行 `verify-desktop-package.ps1`。
