# DXM Production Two-Stage Workflow Implementation Plan

> **2026-07-02 状态:** 本计划为历史归档，已被 `2026-06-25-dxm-production-two-stage-version-plan.md` 取代。旧文中的 `采集认领`、`采集箱/草稿箱`、`开始采集认领` 不是当前用户界面或交付口径；当前主路径是 `待认领商品 -> 商品箱商品 -> 商品箱编辑保存`，系统不采集商品、不填写产品网址、不点击“开始采集”。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Historical version of the two-stage plan. The current product goal is: first move existing Dianxiaomi pending-claim products into the product box, then edit the product-box item and save only.

**Architecture:** Keep the current React/Vite/Electron/FastAPI/Playwright stack. Add an explicit acquisition stage before the existing draft-box edit/save stage, move QA/demo data behind development diagnostics, and rebuild configuration as multi-template Chinese section forms. The user-facing app must expose business steps, while technical gates, selectors, run ids, and QA fixtures stay in maintenance-only diagnostics.

**Tech Stack:** React 18 + TypeScript + Vite, Electron portable desktop, FastAPI, SQLite repository, Playwright headed browser automation, pytest contract tests, PowerShell packaging scripts.

---

## Product Boundary

### Production User Path

The production path has exactly two major stages:

1. **Stage A: 采集认领**
   - Open real Dianxiaomi browser.
   - Enter `数据采集`.
   - Search or filter the real product source.
   - Claim the product into `采集箱/草稿箱`.
   - Verify the claimed product appears in Draft Box.

2. **Stage B: 编辑保存**
   - Start from the verified Draft Box product.
   - Open the real edit page.
   - Resolve the selected template.
   - Fill sectioned edit forms.
   - Human confirms.
   - Click `保存` only.
   - Verify saved and not published.

### Product Rules

- Production mode must not show `QA guarded product`, `QA_CATEGORY`, `demo`, `dry_run`, `probe`, `L2`, `L3`, `run-id`, `source_url`, or `fixture` to normal users.
- The old local `选择商品 -> 创建单商品只保存任务` path becomes an internal fallback only.
- The user must see where the real browser is, what step the Agent is performing, and what the next action is.
- Every write action is explicit:
  - Claim into Draft Box requires a user-facing confirmation.
  - Save only requires a second user-facing confirmation.
  - Publish, batch, and unattended execution remain unavailable.
- Templates are production data, not hidden code defaults. Users can create and select multiple templates.

---

## Version Roadmap

### V1.1 - Correct Product Shell And Remove Test Leakage

**Objective:** Make the app describe the real production workflow even before new automation is complete.

**User Outcome:**
- The sidebar has `采集认领` and `编辑保存`.
- The current `选择商品` route no longer appears as the primary user path.
- QA/test products cannot appear in production lists.
- Any missing automation is explained as "先完成采集认领", not as QA/test blockers.

**Acceptance:**
- App first screen says the workflow is `采集认领 -> 编辑保存 -> 只保存结果`.
- Normal mode shows no `QA`, `测试`, `示例`, `probe`, `L2`, `L3`, `run-id`.
- If no real claimed product exists, the app tells the user to run `采集认领`.

### V1.2 - Real Data Acquisition Claim Stage

**Objective:** Implement real browser automation from `数据采集` to `采集箱/草稿箱`.

**User Outcome:**
- User clicks `开始采集认领`.
- Visible browser opens the Dianxiaomi Data Acquisition page.
- Agent finds the target source product.
- Agent claims it into Draft Box.
- Agent verifies the Draft Box row and records a stable product identity.

**Acceptance:**
- A real product can be claimed into Draft Box from the visible browser.
- The system records: store, platform, product title, source URL if available, Draft Box title, claim mark, timestamp, screenshot evidence, and network safety summary.
- No save or publish action occurs in this stage.

### V1.3 - Draft Box Edit And Save-Only Stage

**Objective:** Make edit/save start from a verified claimed Draft Box product.

**User Outcome:**
- User selects a claimed Draft Box product, not a local QA product.
- Agent opens edit page, fills fields by selected template, and saves only.
- Browser HUD stays visible through all steps.
- Result page explains success/failure in business language.

**Acceptance:**
- Save-only run starts only when a claimed product exists.
- The app refuses to save if the product was not claimed by Stage A or manually verified in Draft Box.
- Save result includes `保存成功` evidence and `未发布` proof.

### V1.4 - Template Center And Chinese Section Forms

**Objective:** Replace the crowded edit configuration page with production template management.

**User Outcome:**
- User can create multiple templates.
- User can assign template defaults by store and category.
- User can choose a template per task.
- Edit fields are shown in Chinese, grouped like Dianxiaomi edit page sections.
- User sees whether the current values are saved and which template will be used.

**Acceptance:**
- The template resolution priority is visible:
  `本次任务覆盖 > 手动选择模板 > 类目默认模板 > 店铺默认模板 > 系统默认模板`.
- Every field shows Chinese label, value, source, saved state, and missing state.
- English internal keys are hidden unless the diagnostics drawer is opened.

### V1.5 - Production Package And Customer Acceptance

**Objective:** Deliver a portable EXE that can be used by a real customer without development knowledge.

**User Outcome:**
- User opens one EXE.
- User logs into Dianxiaomi once and can remember credentials locally.
- User follows two large business stages.
- Browser stays visible.
- Logs are readable and do not occupy the main screen.
- Reports show what happened and what to do next.

**Acceptance:**
- Packaged smoke passes.
- Portable smoke passes.
- Frontend contract tests pass.
- Backend full test suite passes.
- At least one controlled real canary passes:
  `数据采集认领成功 -> 采集箱确认成功 -> 编辑保存成功 -> 未发布证明成功`.

---

## File Structure

### Backend

- Modify: `app/backend/src/state_machine/contracts.py`
  - Add acquisition states before Draft Box edit states.
- Modify: `app/backend/src/execution/dxm_login_flow.py`
  - Add real Data Acquisition actions and claim-to-draft verification.
- Modify: `app/backend/src/execution/dxm_adapter.py`
  - Expose claim-from-acquisition workflow adapter methods.
- Modify: `app/backend/src/execution/v1_runner.py`
  - Split workflow into acquisition stage and edit-save stage.
- Modify: `app/backend/src/models.py`
  - Add request/response models for acquisition claim and template selection.
- Modify: `app/backend/src/repository.py`
  - Persist acquisition records, claimed Draft Box identity, and template metadata.
- Modify: `app/backend/src/main.py`
  - Add production APIs for acquisition claim, claimed products, template management, and save-stage creation.
- Modify: `app/backend/src/services/dxm_reference_templates.py`
  - Normalize sectioned Chinese template configuration and source tracing.

### Frontend

- Modify: `app/frontend/src/types.ts`
  - Add production workflow, acquisition, claimed product, and template types.
- Modify: `app/frontend/src/components/AppShell.tsx`
  - Replace local task menu with production two-stage menu.
- Modify: `app/frontend/src/App.tsx`
  - Route new pages and remove product-task primary flow from normal mode.
- Create: `app/frontend/src/components/workbench/AcquisitionClaimPage.tsx`
  - UI for Stage A.
- Create: `app/frontend/src/components/workbench/EditSavePage.tsx`
  - UI for Stage B.
- Create: `app/frontend/src/components/workbench/TemplateCenterPage.tsx`
  - Multi-template management.
- Modify: `app/frontend/src/components/workbench/EditConfigPage.tsx`
  - Either replace with `TemplateCenterPage` or keep as compatibility wrapper.
- Modify: `app/frontend/src/components/workbench/ProductTasksPage.tsx`
  - Hide from production shell or convert to internal diagnostics.
- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`
  - Rewrite blockers in business language.

### Tests

- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`
  - Assert new sidebar and no QA leakage.
- Add: `app/backend/tests/test_acquisition_claim_workflow.py`
  - Backend contract tests for claim-from-acquisition.
- Modify: `app/backend/tests/test_v1_runner.py`
  - Assert Stage A precedes Stage B.
- Modify: `app/backend/tests/test_task_start_guard.py`
  - Assert save stage requires claimed Draft Box product.
- Modify: `app/backend/tests/test_delivery_workspace.py`
  - Update gates to distinguish acquisition evidence and save evidence.
- Add: `app/backend/tests/test_template_center_contract.py`
  - Template priority, Chinese labels, multi-template selection.
- Modify: `app/backend/tests/test_desktop_package_contract.py`
  - Ensure package docs describe two-stage production path.

### Docs And Packaging

- Modify: `README.md`
- Modify: `docs/product/免安装版快速使用说明-20260615.md`
- Modify: `docs/product/用户交付使用说明-20260526.md`
- Modify: `scripts/verify-desktop-package.ps1`
- Modify: `scripts/final-delivery-check.ps1`

---

## Implementation Tasks

### Task 1: Rename User-Facing Navigation To Production Stages

**Files:**
- Modify: `app/frontend/src/types.ts`
- Modify: `app/frontend/src/components/AppShell.tsx`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: Write the failing sidebar contract test**

Add this test to `app/backend/tests/test_frontend_demo_workflow_contract.py`:

```python
def test_sidebar_uses_two_stage_production_workflow():
    source = FRONTEND_SRC / "components" / "AppShell.tsx"
    shell = source.read_text(encoding="utf-8")

    assert "采集认领" in shell
    assert "编辑保存" in shell
    assert "模板中心" in shell
    assert "保存结果" in shell
    assert "选择商品" not in shell
    assert "QA" not in shell
    assert "L2" not in shell
    assert "run-id" not in shell
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py::test_sidebar_uses_two_stage_production_workflow -q
```

Expected: fail because the sidebar still contains `选择商品`.

- [ ] **Step 3: Update `WorkbenchSection`**

Modify `app/frontend/src/types.ts` so production sections include:

```ts
export type WorkbenchSection =
  | 'home'
  | 'dxm_access'
  | 'acquisition_claim'
  | 'draft_edit_save'
  | 'template_center'
  | 'start_save'
  | 'results'
  | 'issues'
  | 'help'
  | 'settings'
```

Keep legacy section ids only if the compiler still needs them, but do not put them in the production sidebar.

- [ ] **Step 4: Update `AppShell` menu**

Modify `app/frontend/src/components/AppShell.tsx` `primaryAreas` to:

```ts
const primaryAreas: WorkbenchPrimaryArea[] = [
  {
    id: 'daily_flow',
    label: '日常流程',
    short: '1',
    items: [
      { id: 'home', label: '今日任务', short: '今', hint: '看今天该处理哪一步' },
      { id: 'dxm_access', label: '登录店小秘', short: '登', hint: '打开真实店小秘并确认登录' },
      { id: 'acquisition_claim', label: '采集认领', short: '采', hint: '从数据采集认领到采集箱' },
      { id: 'draft_edit_save', label: '编辑保存', short: '编', hint: '从采集箱打开编辑页并只保存' },
      { id: 'template_center', label: '模板中心', short: '模', hint: '管理店铺和类目模板' },
    ],
  },
  {
    id: 'review',
    label: '结果复盘',
    short: '2',
    items: [
      { id: 'results', label: '保存结果', short: '果', hint: '查看保存成功和未发布证明' },
      { id: 'issues', label: '问题处理', short: '问', hint: '按失败原因恢复' },
    ],
  },
  {
    id: 'system',
    label: '帮助与系统',
    short: '3',
    items: [
      { id: 'help', label: '使用帮助', short: '帮', hint: '普通用户操作说明' },
      { id: 'settings', label: '系统设置', short: '设', hint: '账号、浏览器、日志和维护诊断' },
    ],
  },
]
```

- [ ] **Step 5: Run contract test**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py::test_sidebar_uses_two_stage_production_workflow -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add app/frontend/src/types.ts app/frontend/src/components/AppShell.tsx app/frontend/src/App.tsx app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "feat: expose production two-stage sidebar"
```

### Task 2: Hide QA And Demo Products From Production Mode

**Files:**
- Modify: `app/backend/src/repository.py`
- Modify: `app/backend/src/main.py`
- Modify: `app/frontend/src/components/workbench/ProductTasksPage.tsx`
- Modify: `app/backend/tests/test_task_start_guard.py`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: Write backend test**

Add this to `app/backend/tests/test_task_start_guard.py`:

```python
def test_products_api_hides_fixture_products_in_production(client, repo):
    repo.create_product({
        "title": "QA guarded product",
        "category_name": "QA_CATEGORY",
        "price": 1,
        "currency": "USD",
        "sku_count": 1,
        "image_count": 1,
        "status": "draft",
        "payload": {"fixture": True},
    })
    repo.create_product({
        "title": "真实采集商品 A",
        "category_name": "立牌类谷子",
        "price": 9.9,
        "currency": "USD",
        "sku_count": 1,
        "image_count": 1,
        "status": "claimed_to_draft",
        "payload": {"source": "dxm_data_acquisition"},
    })

    response = client.get("/api/products")
    assert response.status_code == 200
    titles = [item["title"] for item in response.json()]
    assert "真实采集商品 A" in titles
    assert "QA guarded product" not in titles
```

- [ ] **Step 2: Run failing test**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_task_start_guard.py::test_products_api_hides_fixture_products_in_production -q
```

Expected: fail until `/api/products` filters fixture products.

- [ ] **Step 3: Implement fixture filter**

In `app/backend/src/repository.py`, add:

```python
def _is_fixture_product(row: dict[str, Any]) -> bool:
    payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            row.get("title"),
            row.get("category_name"),
            payload.get("fixture"),
            payload.get("source"),
        )
    ).lower()
    return any(marker in text for marker in ("qa guarded", "qa_category", "测试", "示例", "fixture"))
```

Then make `list_products()` return only non-fixture rows for the normal API path. If development diagnostics need fixtures, add a separate explicit method:

```python
def list_products(self, *, include_fixtures: bool = False):
    rows = self._query_products()
    if include_fixtures:
        return rows
    return [row for row in rows if not _is_fixture_product(row)]
```

- [ ] **Step 4: Run tests**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_task_start_guard.py::test_products_api_hides_fixture_products_in_production -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add app/backend/src/repository.py app/backend/src/main.py app/backend/tests/test_task_start_guard.py
git commit -m "fix: hide fixture products from production APIs"
```

### Task 3: Add Acquisition Data Model And APIs

**Files:**
- Modify: `app/backend/src/models.py`
- Modify: `app/backend/src/repository.py`
- Modify: `app/backend/src/main.py`
- Create: `app/backend/tests/test_acquisition_claim_workflow.py`

- [ ] **Step 1: Write API contract tests**

Create `app/backend/tests/test_acquisition_claim_workflow.py`:

```python
from __future__ import annotations


def test_acquisition_claim_request_creates_claim_record(client, repo):
    store = repo.create_store({"name": "Dang Kang", "platform": "AliExpress", "status": "connected"})

    response = client.post("/api/acquisition/claim-requests", json={
        "store_id": store["id"],
        "keyword": "Hazbin Hotel",
        "category_name": "立牌类谷子",
        "claim_mark": "AI-OPS",
        "template_id": None,
    })

    assert response.status_code == 200
    payload = response.json()
    assert payload["stage"] == "pending_acquisition_claim"
    assert payload["store_id"] == store["id"]
    assert payload["keyword"] == "Hazbin Hotel"
    assert payload["claim_mark"] == "AI-OPS"
    assert payload["status"] == "pending"


def test_save_task_requires_claimed_draft_product(client, repo):
    store = repo.create_store({"name": "Dang Kang", "platform": "AliExpress", "status": "connected"})
    product = repo.create_product({
        "title": "真实采集商品 A",
        "category_name": "立牌类谷子",
        "price": 9.9,
        "currency": "USD",
        "sku_count": 1,
        "image_count": 1,
        "status": "draft",
        "payload": {"source": "manual_import"},
    })

    response = client.post("/api/tasks", json={
        "name": "单商品只保存 - Dang Kang - 1 件商品",
        "mode": "single_save",
        "publish_scene": "controlled_single_save_only",
        "store_id": store["id"],
        "product_ids": [product["id"]],
        "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
    })

    assert response.status_code == 409
    assert "采集箱" in response.json()["detail"]
    assert "采集认领" in response.json()["detail"]
```

- [ ] **Step 2: Run failing tests**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py -q
```

Expected: fail because endpoints and claimed-product guard do not exist.

- [ ] **Step 3: Add models**

In `app/backend/src/models.py`, add:

```python
class AcquisitionClaimRequest(BaseModel):
    store_id: int
    keyword: str | None = None
    category_name: str | None = None
    claim_mark: str
    template_id: int | None = None


class ClaimedDraftProductCreate(BaseModel):
    store_id: int
    title: str
    category_name: str
    source_url: str | None = None
    draft_box_url: str | None = None
    claim_mark: str
    template_id: int | None = None
```

- [ ] **Step 4: Add repository persistence**

In `app/backend/src/repository.py`, add methods:

```python
def create_acquisition_claim_request(self, data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "stage": "pending_acquisition_claim",
        "status": "pending",
        "store_id": data["store_id"],
        "keyword": data.get("keyword"),
        "category_name": data.get("category_name"),
        "claim_mark": data["claim_mark"],
        "template_id": data.get("template_id"),
    }
    return self.create_task({
        "name": f"采集认领 - {payload['keyword'] or payload['category_name'] or '待选择商品'}",
        "mode": "claim_only",
        "publish_scene": "controlled_claim_to_draft_only",
        "store_id": payload["store_id"],
        "product_ids": [],
        "payload": payload,
    })
```

- [ ] **Step 5: Add API endpoint**

In `app/backend/src/main.py`, add:

```python
@app.post("/api/acquisition/claim-requests")
def create_acquisition_claim_request(payload: AcquisitionClaimRequest):
    repo = Repository()
    task = repo.create_acquisition_claim_request(payload.model_dump())
    return task
```

- [ ] **Step 6: Guard save task creation**

Update `_assert_task_create_scope(payload: TaskCreate)` in `app/backend/src/main.py`:

```python
if payload.mode == "single_save":
    products = Repository().products_by_ids(payload.product_ids)
    unclaimed = [
        product.get("title")
        for product in products
        if product.get("status") not in {"claimed_to_draft", "ready_for_edit"}
    ]
    if unclaimed:
        raise HTTPException(
            status_code=409,
            detail="请先完成采集认领：商品必须从店小秘数据采集认领到采集箱，并完成采集箱确认后，才能创建编辑保存任务。",
        )
```

If `products_by_ids` does not exist, add it to `Repository`.

- [ ] **Step 7: Run tests**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_task_start_guard.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add app/backend/src/models.py app/backend/src/repository.py app/backend/src/main.py app/backend/tests/test_acquisition_claim_workflow.py app/backend/tests/test_task_start_guard.py
git commit -m "feat: add acquisition claim task model"
```

### Task 4: Add Real Data Acquisition Browser Actions

**Files:**
- Modify: `app/backend/src/state_machine/contracts.py`
- Modify: `app/backend/src/execution/dxm_login_flow.py`
- Modify: `app/backend/src/execution/dxm_adapter.py`
- Modify: `app/backend/src/execution/v1_runner.py`
- Create: `app/backend/tests/test_acquisition_claim_workflow.py`

- [ ] **Step 1: Write state contract test**

Add to `app/backend/tests/test_acquisition_claim_workflow.py`:

```python
def test_state_machine_has_acquisition_before_draft_edit():
    from src.state_machine.contracts import StateName, build_v1_state_specs

    specs = build_v1_state_specs()
    assert StateName.OPEN_DATA_ACQUISITION in specs
    assert StateName.FIND_ACQUISITION_PRODUCT in specs
    assert StateName.CLAIM_TO_DRAFT_BOX in specs
    assert StateName.VERIFY_DRAFT_BOX_CLAIM in specs
```

- [ ] **Step 2: Run failing test**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py::test_state_machine_has_acquisition_before_draft_edit -q
```

Expected: fail because states are missing.

- [ ] **Step 3: Add state names**

In `app/backend/src/state_machine/contracts.py`, add to `StateName` before `OPEN_DRAFT_LIST`:

```python
OPEN_DATA_ACQUISITION = "OPEN_DATA_ACQUISITION"
FIND_ACQUISITION_PRODUCT = "FIND_ACQUISITION_PRODUCT"
CLAIM_TO_DRAFT_BOX = "CLAIM_TO_DRAFT_BOX"
VERIFY_DRAFT_BOX_CLAIM = "VERIFY_DRAFT_BOX_CLAIM"
```

Add corresponding `StateNodeSpec` entries:

```python
StateName.OPEN_DATA_ACQUISITION: StateNodeSpec(
    state_name=StateName.OPEN_DATA_ACQUISITION,
    preconditions=("session is usable", "claim request exists"),
    actions=("open Dianxiaomi data acquisition page",),
    expected_url=("/web/productCrawl/dataAcquisition",),
    failure_code="E210",
    ownership_required=False,
),
StateName.FIND_ACQUISITION_PRODUCT: StateNodeSpec(
    state_name=StateName.FIND_ACQUISITION_PRODUCT,
    preconditions=("data acquisition page is open",),
    actions=("search and locate one acquisition product row",),
    expected_dom=("unique acquisition product row",),
    failure_code="E211",
    ownership_required=False,
),
StateName.CLAIM_TO_DRAFT_BOX: StateNodeSpec(
    state_name=StateName.CLAIM_TO_DRAFT_BOX,
    preconditions=("unique acquisition product row is located",),
    actions=("click claim to draft box only",),
    expected_text=("claim success", "采集箱"),
    failure_code="E212",
),
StateName.VERIFY_DRAFT_BOX_CLAIM: StateNodeSpec(
    state_name=StateName.VERIFY_DRAFT_BOX_CLAIM,
    preconditions=("claim action completed",),
    actions=("open draft box and verify claimed product row",),
    expected_dom=("claimed draft product row",),
    failure_code="E213",
),
```

- [ ] **Step 4: Add adapter method contract test**

```python
def test_adapter_exposes_claim_from_data_acquisition():
    from src.execution.dxm_adapter import DxmWorkflowAdapter

    class Flow:
        def __init__(self):
            self.calls = []
        def claim_from_data_acquisition(self, keyword=None, category_name=None, claim_mark=None):
            self.calls.append((keyword, category_name, claim_mark))
            return {"stage": "claimed_to_draft", "ok": True}

    flow = Flow()
    result = DxmWorkflowAdapter(flow).claim_from_data_acquisition(
        keyword="Hazbin Hotel",
        category_name="立牌类谷子",
        claim_mark="AI-OPS",
    )

    assert result["action"] == "claim_from_data_acquisition"
    assert result["stage"] == "claimed_to_draft"
    assert flow.calls == [("Hazbin Hotel", "立牌类谷子", "AI-OPS")]
```

- [ ] **Step 5: Implement adapter method**

In `app/backend/src/execution/dxm_adapter.py`, add:

```python
def claim_from_data_acquisition(
    self,
    *,
    keyword: str | None = None,
    category_name: str | None = None,
    claim_mark: str | None = None,
) -> dict[str, Any]:
    return self._result(
        "claim_from_data_acquisition",
        self.login_flow.claim_from_data_acquisition(
            keyword=keyword,
            category_name=category_name,
            claim_mark=claim_mark,
        ),
    )
```

- [ ] **Step 6: Implement Playwright flow**

In `app/backend/src/execution/dxm_login_flow.py`, add method skeleton with real visible browser operations:

```python
def claim_from_data_acquisition(
    self,
    *,
    keyword: str | None = None,
    category_name: str | None = None,
    claim_mark: str | None = None,
) -> dict[str, Any]:
    page = self._ensure_page()
    self.navigate_post_login("data_acquisition")
    self._search_data_acquisition(page, keyword=keyword, category_name=category_name)
    row_info = self._find_data_acquisition_row(page, keyword=keyword, category_name=category_name)
    claim_result = self._claim_data_acquisition_row(page, row_info=row_info)
    draft_result = self._verify_claimed_product_in_draft_box(
        keyword=keyword,
        category_name=category_name,
        claim_mark=claim_mark,
        source_url=claim_result.get("source_url"),
    )
    return {
        "stage": "claimed_to_draft",
        "ok": True,
        "keyword": keyword,
        "category_name": category_name,
        "claim_mark": claim_mark,
        "source_url": claim_result.get("source_url"),
        "draft_box": draft_result,
    }
```

Implementation details:
- `_search_data_acquisition` must only type/search/filter.
- `_find_data_acquisition_row` must return exactly one row or raise with a Chinese message.
- `_claim_data_acquisition_row` may click only the claim/认领 control, not edit/save/publish.
- `_verify_claimed_product_in_draft_box` must navigate to Draft Box and match by source URL first, title second.

- [ ] **Step 7: Run focused tests**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_dxm_adapter.py tests\test_login_flow.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add app/backend/src/state_machine/contracts.py app/backend/src/execution/dxm_login_flow.py app/backend/src/execution/dxm_adapter.py app/backend/src/execution/v1_runner.py app/backend/tests/test_acquisition_claim_workflow.py app/backend/tests/test_dxm_adapter.py app/backend/tests/test_login_flow.py
git commit -m "feat: automate acquisition claim to draft box"
```

### Task 5: Build Acquisition Claim Page

**Files:**
- Create: `app/frontend/src/components/workbench/AcquisitionClaimPage.tsx`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/frontend/src/types.ts`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: Write frontend contract test**

Add:

```python
def test_acquisition_claim_page_is_business_first():
    page = FRONTEND_SRC / "components" / "workbench" / "AcquisitionClaimPage.tsx"
    source = page.read_text(encoding="utf-8")

    assert "采集认领" in source
    assert "打开数据采集页" in source
    assert "认领到采集箱" in source
    assert "确认采集箱商品" in source
    for forbidden in ("QA", "L2", "probe", "run-id", "source_url"):
        assert forbidden not in source
```

- [ ] **Step 2: Run failing test**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py::test_acquisition_claim_page_is_business_first -q
```

Expected: fail because the page does not exist.

- [ ] **Step 3: Create page**

Create `app/frontend/src/components/workbench/AcquisitionClaimPage.tsx`:

```tsx
import type { Store } from '../../types'

type AcquisitionClaimPageProps = {
  stores: Store[]
  busy: boolean
  onOpenDataAcquisition: () => void
  onStartClaim: (request: { storeId: number; keyword: string; categoryName: string; claimMark: string }) => void
}

export function AcquisitionClaimPage({ stores, busy, onOpenDataAcquisition, onStartClaim }: AcquisitionClaimPageProps) {
  const defaultStore = stores[0]

  return (
    <section className="module-layout" aria-label="采集认领">
      <div className="module-card span-2">
        <div className="module-head">
          <div>
            <span className="eyebrow">第一段</span>
            <h2>采集认领</h2>
            <p>从店小秘数据采集页认领商品到采集箱。这里只认领，不编辑、不保存、不发布。</p>
          </div>
        </div>
        <div className="step-grid">
          <div className="step-card">
            <strong>1 打开数据采集页</strong>
            <span>确认真实浏览器已登录店小秘。</span>
          </div>
          <div className="step-card">
            <strong>2 选择要认领的商品</strong>
            <span>按关键词、类目或当前页面筛选。</span>
          </div>
          <div className="step-card">
            <strong>3 认领到采集箱</strong>
            <span>认领后会进入采集箱确认。</span>
          </div>
        </div>
        <div className="action-row">
          <button className="button button--secondary" type="button" onClick={onOpenDataAcquisition} disabled={busy}>
            打开数据采集页
          </button>
          <button
            className="button button--primary"
            type="button"
            onClick={() => onStartClaim({
              storeId: defaultStore?.id ?? 0,
              keyword: '',
              categoryName: '',
              claimMark: 'AI-OPS',
            })}
            disabled={busy || !defaultStore}
          >
            开始认领到采集箱
          </button>
        </div>
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Wire route in `App.tsx`**

Import and render:

```tsx
import { AcquisitionClaimPage } from './components/workbench/AcquisitionClaimPage'
```

Add in the section switch:

```tsx
case 'acquisition_claim':
  return (
    <AcquisitionClaimPage
      stores={workspace.stores}
      busy={busy}
      onOpenDataAcquisition={() => navigateDxmTarget('data_acquisition')}
      onStartClaim={startAcquisitionClaim}
    />
  )
```

Add `startAcquisitionClaim`:

```tsx
async function startAcquisitionClaim(request: { storeId: number; keyword: string; categoryName: string; claimMark: string }) {
  setBusy(true)
  try {
    await postJson('/api/acquisition/claim-requests', {
      store_id: request.storeId,
      keyword: request.keyword || null,
      category_name: request.categoryName || null,
      claim_mark: request.claimMark,
      template_id: null,
    })
    await refreshWorkspace()
    setActiveSection('draft_edit_save')
  } catch (error) {
    setOperationError(error instanceof Error ? error.message : '采集认领启动失败')
  } finally {
    setBusy(false)
  }
}
```

- [ ] **Step 5: Run tests and build**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py::test_acquisition_claim_page_is_business_first -q

cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

Expected: both pass.

- [ ] **Step 6: Commit**

```powershell
git add app/frontend/src/components/workbench/AcquisitionClaimPage.tsx app/frontend/src/App.tsx app/frontend/src/types.ts app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "feat: add acquisition claim page"
```

### Task 6: Rebuild Edit Save Page Around Claimed Draft Products

**Files:**
- Create: `app/frontend/src/components/workbench/EditSavePage.tsx`
- Modify: `app/frontend/src/App.tsx`
- Modify: `app/frontend/src/components/workbench/ProductTasksPage.tsx`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: Write contract test**

```python
def test_edit_save_page_starts_from_claimed_draft_product():
    page = FRONTEND_SRC / "components" / "workbench" / "EditSavePage.tsx"
    source = page.read_text(encoding="utf-8")

    assert "第二段" in source
    assert "从采集箱开始编辑" in source
    assert "选择已认领商品" in source
    assert "只保存，不发布" in source
    assert "本地测试商品" not in source
    assert "QA" not in source
```

- [ ] **Step 2: Create page**

Create `app/frontend/src/components/workbench/EditSavePage.tsx`:

```tsx
import type { Product, Task } from '../../types'

type EditSavePageProps = {
  claimedProducts: Product[]
  selectedTask: Task | null
  busy: boolean
  onCreateSaveTask: (productId: number) => void
  onShowTemplates: () => void
  onStartSave: () => void
}

export function EditSavePage({
  claimedProducts,
  selectedTask,
  busy,
  onCreateSaveTask,
  onShowTemplates,
  onStartSave,
}: EditSavePageProps) {
  return (
    <section className="module-layout" aria-label="编辑保存">
      <div className="module-card span-2">
        <div className="module-head">
          <div>
            <span className="eyebrow">第二段</span>
            <h2>从采集箱开始编辑</h2>
            <p>选择已认领商品，按模板填写编辑页。这里只保存，不发布。</p>
          </div>
        </div>
        <div className="claimed-product-list" aria-label="选择已认领商品">
          {claimedProducts.length === 0 ? (
            <div className="empty-state">
              <strong>还没有可编辑商品</strong>
              <span>请先完成采集认领，确认商品已经进入采集箱。</span>
            </div>
          ) : claimedProducts.map((product) => (
            <button
              key={product.id}
              className="product-pick-card"
              type="button"
              onClick={() => onCreateSaveTask(product.id)}
              disabled={busy}
            >
              <strong>{product.title}</strong>
              <span>{product.category_name} / {product.status}</span>
            </button>
          ))}
        </div>
        <div className="action-row">
          <button className="button button--secondary" type="button" onClick={onShowTemplates}>
            选择填写模板
          </button>
          <button className="button button--primary" type="button" onClick={onStartSave} disabled={busy || !selectedTask}>
            人工确认后开始只保存
          </button>
        </div>
      </div>
    </section>
  )
}
```

- [ ] **Step 3: Route page**

In `App.tsx`, derive claimed products:

```tsx
const claimedProducts = workspace.products.filter((product) =>
  ['claimed_to_draft', 'ready_for_edit'].includes(product.status),
)
```

Render:

```tsx
case 'draft_edit_save':
  return (
    <EditSavePage
      claimedProducts={claimedProducts}
      selectedTask={selectedTask}
      busy={busy}
      onCreateSaveTask={(productId) => createRealTask({ storeId: workspace.stores[0]?.id ?? 0, mode: 'single_save', productIds: [productId] })}
      onShowTemplates={() => setActiveSection('template_center')}
      onStartSave={() => void startRealTaskWithManualApproval()}
    />
  )
```

- [ ] **Step 4: Run tests and build**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py::test_edit_save_page_starts_from_claimed_draft_product -q

cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add app/frontend/src/components/workbench/EditSavePage.tsx app/frontend/src/App.tsx app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "feat: add claimed-product edit save page"
```

### Task 7: Build Multi-Template Center With Chinese Section Forms

**Files:**
- Create: `app/frontend/src/components/workbench/TemplateCenterPage.tsx`
- Modify: `app/frontend/src/components/workbench/EditConfigPage.tsx`
- Modify: `app/frontend/src/types.ts`
- Modify: `app/backend/src/models.py`
- Modify: `app/backend/src/repository.py`
- Modify: `app/backend/src/main.py`
- Create: `app/backend/tests/test_template_center_contract.py`

- [ ] **Step 1: Write backend template priority test**

Create `app/backend/tests/test_template_center_contract.py`:

```python
def test_template_resolution_priority_is_task_then_selected_then_category_then_store(client, repo):
    store = repo.create_store({"name": "Dang Kang", "platform": "AliExpress", "status": "connected"})
    store_template = repo.create_template({
        "template_type": "edit_page",
        "template_name": "店铺默认模板",
        "binding_scope": "store",
        "is_enabled": True,
        "payload": {"store_id": store["id"], "sections": {"base": {"商品标题": "店铺标题"}}},
    })
    category_template = repo.create_template({
        "template_type": "edit_page",
        "template_name": "立牌类谷子模板",
        "binding_scope": "category",
        "is_enabled": True,
        "payload": {"category_name": "立牌类谷子", "sections": {"base": {"商品标题": "类目标题"}}},
    })
    selected_template = repo.create_template({
        "template_type": "edit_page",
        "template_name": "本次选择模板",
        "binding_scope": "manual",
        "is_enabled": True,
        "payload": {"sections": {"base": {"商品标题": "选择模板标题"}}},
    })
    product = repo.create_product({
        "title": "真实采集商品 A",
        "category_name": "立牌类谷子",
        "price": 9.9,
        "currency": "USD",
        "sku_count": 1,
        "image_count": 1,
        "status": "claimed_to_draft",
        "payload": {"template_id": selected_template["id"]},
    })
    task = repo.create_task({
        "name": "单商品只保存 - Dang Kang - 1 件商品",
        "mode": "single_save",
        "publish_scene": "controlled_single_save_only",
        "store_id": store["id"],
        "product_ids": [product["id"]],
        "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子", "template_id": selected_template["id"]},
    })

    response = client.get(f"/api/config/preview?task_id={task['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["templatePriority"] == ["本次任务覆盖", "手动选择模板", "类目默认模板", "店铺默认模板", "系统默认模板"]
    assert data["resolvedDefaults"]["商品标题"] == "选择模板标题"
    assert "template_trace" in data
```

- [ ] **Step 2: Run failing test**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_template_center_contract.py -q
```

Expected: fail because `templatePriority` and Chinese field resolution are not implemented.

- [ ] **Step 3: Extend config preview response**

In `app/backend/src/main.py` config preview output, add:

```python
"templatePriority": ["本次任务覆盖", "手动选择模板", "类目默认模板", "店铺默认模板", "系统默认模板"],
"sections": _sectioned_chinese_config_preview(resolved_defaults),
```

Add helper:

```python
def _sectioned_chinese_config_preview(values: dict[str, Any]) -> list[dict[str, Any]]:
    sections = [
        ("store_task", "店铺与任务基础", ["店铺", "绑定类目", "认领标记"]),
        ("category_title", "类目与标题", ["商品标题", "商品卖点", "关键词"]),
        ("sku_price_stock", "SKU / 价格 / 库存", ["SKU", "价格", "库存"]),
        ("images_media", "图片与素材", ["主图", "营销图", "详情图"]),
        ("package_logistics", "包装物流", ["重量", "尺寸", "物流方式"]),
        ("compliance_customs", "合规 / 海关", ["材质", "用途", "海关编码"]),
        ("semi_managed", "半托管", ["服务模板", "仓库", "发货配置"]),
        ("dxm_reference", "店小秘引用模板", ["运费模板", "服务模板", "尺码模板"]),
    ]
    return [
        {
            "section": code,
            "label": label,
            "fields": [
                {
                    "label": field,
                    "value": values.get(field),
                    "source": "待解析",
                    "saved": values.get(field) not in (None, ""),
                    "missing": values.get(field) in (None, ""),
                }
                for field in fields
            ],
        }
        for code, label, fields in sections
    ]
```

- [ ] **Step 4: Write frontend contract**

```python
def test_template_center_uses_chinese_section_forms():
    page = FRONTEND_SRC / "components" / "workbench" / "TemplateCenterPage.tsx"
    source = page.read_text(encoding="utf-8")

    for label in ("店铺模板", "类目模板", "本次任务覆盖", "保存为模板", "套用模板"):
        assert label in source
    for section in ("店铺与任务基础", "类目与标题", "SKU / 价格 / 库存", "图片与素材", "包装物流", "合规 / 海关", "半托管"):
        assert section in source
    assert "source_url" not in source
    assert "template_type" not in source
```

- [ ] **Step 5: Create Template Center page**

Create `app/frontend/src/components/workbench/TemplateCenterPage.tsx`:

```tsx
import type { ConfigPreview, Template } from '../../types'

type TemplateCenterPageProps = {
  templates: Template[]
  configPreview: ConfigPreview | null
  onSaveTemplate: (template: { name: string; scope: 'store' | 'category' | 'manual' }) => void
}

const sectionLabels = [
  '店铺与任务基础',
  '类目与标题',
  'SKU / 价格 / 库存',
  '图片与素材',
  '包装物流',
  '合规 / 海关',
  '半托管',
  '店小秘引用模板',
]

export function TemplateCenterPage({ templates, configPreview, onSaveTemplate }: TemplateCenterPageProps) {
  return (
    <section className="module-layout" aria-label="模板中心">
      <div className="module-card span-2">
        <div className="module-head">
          <div>
            <span className="eyebrow">模板中心</span>
            <h2>多套模板管理</h2>
            <p>按店铺、类目和本次任务选择模板。执行前会显示最终采用的值。</p>
          </div>
        </div>
        <div className="template-toolbar">
          <button className="button button--secondary" type="button" onClick={() => onSaveTemplate({ name: '新店铺模板', scope: 'store' })}>保存为店铺模板</button>
          <button className="button button--secondary" type="button" onClick={() => onSaveTemplate({ name: '新类目模板', scope: 'category' })}>保存为类目模板</button>
          <button className="button button--primary" type="button" onClick={() => onSaveTemplate({ name: '本次任务覆盖', scope: 'manual' })}>保存本次任务覆盖</button>
        </div>
        <div className="template-list">
          {templates.map((template) => (
            <button className="template-card" key={template.id} type="button">
              <strong>{template.template_name}</strong>
              <span>{template.binding_scope}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="module-card span-2">
        <div className="module-head">
          <h2>填写分区</h2>
          <span>{configPreview?.ok ? '配置已就绪' : '需要补齐字段'}</span>
        </div>
        <div className="section-form-list">
          {sectionLabels.map((label) => (
            <details className="section-form" key={label} open={label === '店铺与任务基础'}>
              <summary>{label}</summary>
              <p>字段会显示中文名称、当前值、来源和保存状态。</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  )
}
```

- [ ] **Step 6: Run tests and build**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_template_center_contract.py tests\test_frontend_demo_workflow_contract.py::test_template_center_uses_chinese_section_forms -q

cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add app/frontend/src/components/workbench/TemplateCenterPage.tsx app/frontend/src/types.ts app/frontend/src/App.tsx app/backend/src/models.py app/backend/src/repository.py app/backend/src/main.py app/backend/tests/test_template_center_contract.py app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "feat: add production template center"
```

### Task 8: Update Runner To Enforce Two Separate Stages

**Files:**
- Modify: `app/backend/src/execution/v1_runner.py`
- Modify: `app/backend/src/main.py`
- Modify: `app/backend/tests/test_v1_runner.py`
- Modify: `app/backend/tests/test_task_start_guard.py`

- [ ] **Step 1: Write runner order test**

Add to `app/backend/tests/test_v1_runner.py`:

```python
def test_single_save_runner_requires_claimed_product_before_edit(v1_db):
    repo = Repository(v1_db)
    product = repo.create_product({
        "title": "真实采集商品 A",
        "category_name": "立牌类谷子",
        "price": 9.9,
        "currency": "USD",
        "sku_count": 1,
        "image_count": 1,
        "status": "draft",
        "payload": {"source": "manual_import"},
    })
    task = repo.create_task({
        "name": "单商品只保存 - Dang Kang - 1 件商品",
        "mode": "single_save",
        "publish_scene": "controlled_single_save_only",
        "store_id": 1,
        "product_ids": [product["id"]],
        "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
    })

    runner = V1TaskRunner(repo, workflow_adapter=FakeWorkflowAdapter())
    result = runner.run_task(task["id"])

    assert result["status"] == "failed"
    assert "采集认领" in result["error_message"]
```

- [ ] **Step 2: Implement guard in runner**

In `app/backend/src/execution/v1_runner.py`, before opening Draft Box for `single_save`, check product status:

```python
if mode == "single_save":
    product = self.repository.get_product(job.get("product_id"))
    if product.get("status") not in {"claimed_to_draft", "ready_for_edit"}:
        raise V1ExecutionError(
            "E214",
            "商品尚未完成采集认领",
            "请先从店小秘数据采集认领到采集箱，再启动编辑保存。",
        )
```

- [ ] **Step 3: Run focused tests**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_v1_runner.py tests\test_task_start_guard.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```powershell
git add app/backend/src/execution/v1_runner.py app/backend/src/main.py app/backend/tests/test_v1_runner.py app/backend/tests/test_task_start_guard.py
git commit -m "fix: require acquisition claim before edit save"
```

### Task 9: Rewrite Help, Errors, And Results For Customer Language

**Files:**
- Modify: `app/frontend/src/components/workbench/HelpPage.tsx`
- Modify: `app/frontend/src/components/workbench/IssuesPage.tsx`
- Modify: `app/frontend/src/components/workbench/ResultsPage.tsx`
- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: Write wording contract**

```python
def test_customer_pages_do_not_expose_engineering_terms():
    files = [
        FRONTEND_SRC / "components" / "workbench" / "HelpPage.tsx",
        FRONTEND_SRC / "components" / "workbench" / "IssuesPage.tsx",
        FRONTEND_SRC / "components" / "workbench" / "ResultsPage.tsx",
        FRONTEND_SRC / "components" / "workbench" / "workbenchCopy.ts",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    for forbidden in ("L2", "L3", "probe", "run-id", "source_url", "QA", "fixture", "dry_run"):
        assert forbidden not in combined
    for required in ("采集认领", "编辑保存", "只保存，不发布", "下一步", "为什么不能继续"):
        assert required in combined
```

- [ ] **Step 2: Replace wording**

Use these business terms:

```ts
export function customerBlockerCopy(code: string) {
  if (code === 'missing_claimed_product') {
    return {
      what: '还没有完成采集认领。',
      why: '编辑保存必须从采集箱里的真实商品开始，不能直接使用本地记录。',
      next: '先进入“采集认领”，把商品认领到采集箱。',
    }
  }
  if (code === 'missing_template') {
    return {
      what: '编辑页模板还没有选好。',
      why: '系统需要知道标题、SKU、图片、包装物流等字段怎么填写。',
      next: '进入“模板中心”，选择或保存一套模板。',
    }
  }
  return {
    what: '当前步骤被保护性阻断。',
    why: '系统没有拿到足够证据，不能启动真实保存。',
    next: '按页面提示处理后重试。',
  }
}
```

- [ ] **Step 3: Run test**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py::test_customer_pages_do_not_expose_engineering_terms -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```powershell
git add app/frontend/src/components/workbench/HelpPage.tsx app/frontend/src/components/workbench/IssuesPage.tsx app/frontend/src/components/workbench/ResultsPage.tsx app/frontend/src/components/workbench/workbenchCopy.ts app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "fix: use customer language for blockers and help"
```

### Task 10: Production Packaging And Real Canary Acceptance

**Files:**
- Modify: `README.md`
- Modify: `docs/product/免安装版快速使用说明-20260615.md`
- Modify: `docs/product/用户交付使用说明-20260526.md`
- Modify: `scripts/final-delivery-check.ps1`
- Modify: `scripts/verify-desktop-package.ps1`

- [ ] **Step 1: Run backend full test**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\backend
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run frontend build**

```powershell
cd D:\Desktop\py\dxm-auto-uikit\app\frontend
npm run build
```

Expected: typecheck and Vite build pass.

- [ ] **Step 3: Build portable**

```powershell
cd D:\Desktop\py\dxm-auto-uikit
npm --prefix app\desktop run build:portable
```

Expected:

```text
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

- [ ] **Step 4: Verify package**

```powershell
cd D:\Desktop\py\dxm-auto-uikit
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

Expected:

```text
Packaged smoke passed
Credential smoke passed
Visible window smoke passed
Portable smoke passed
```

- [ ] **Step 5: Copy delivery EXE**

```powershell
Copy-Item `
  D:\Desktop\py\dxm-auto-uikit\outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe `
  D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe `
  -Force
```

- [ ] **Step 6: Real canary**

Using the visible browser from the packaged EXE:

```text
1. 登录店小秘
2. 打开采集认领
3. 从数据采集认领 1 个真实商品到采集箱
4. 确认采集箱出现该商品
5. 进入编辑保存
6. 选择模板
7. 人工确认
8. 执行只保存
9. 保存成功
10. 未发布证明成功
```

Expected result:

```text
采集认领：通过
采集箱确认：通过
编辑保存：通过
保存成功：通过
未发布证明：通过
发布/批量/无人值守入口：无
```

- [ ] **Step 7: Commit and push**

```powershell
git status --short
git add README.md docs/product/免安装版快速使用说明-20260615.md docs/product/用户交付使用说明-20260526.md scripts/final-delivery-check.ps1 scripts/verify-desktop-package.ps1
git commit -m "docs: document production two-stage delivery"
git push origin main
```

---

## Delivery Definition

The task is complete only when all of these are true:

- Sidebar and pages follow the two-stage production workflow.
- Normal users cannot see or choose QA/demo/test products.
- Stage A can claim a real Dianxiaomi Data Acquisition product into Draft Box.
- Stage B can edit a claimed Draft Box product and save only.
- Template Center supports multiple templates and Chinese section forms.
- Template priority is visible before execution.
- Browser HUD stays resident through acquisition and save stages.
- Logs remain readable and do not cover the main UI.
- EXE launches without command windows.
- Packaged and portable smoke pass.
- Backend full test suite passes.
- Frontend build passes.
- One real canary proves claim-to-draft and save-only.
- Git is clean and pushed.

---

## Known Risks And Mitigations

- **Dianxiaomi UI changes:** Keep selector profiles per page and fail with Chinese recovery steps.
- **Claim button ambiguity:** Data Acquisition claim must match a unique row; multiple matches require user selection.
- **Duplicate Draft Box rows:** Verify by source URL first, claim mark second, title third.
- **Template value mistakes:** Preview final resolved values before execution; do not start save with missing required fields.
- **Accidental publish:** Keep publish, batch, and unattended routes unavailable; scan buttons and network before save.
- **User confusion:** Hide technical diagnostics by default; show only business blockers.

---

## Execution Choice

Plan complete and saved to `docs/superpowers/plans/2026-06-23-dxm-production-two-stage-workflow-plan.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

