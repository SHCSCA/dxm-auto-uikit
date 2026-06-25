# DXM Production Two Stage Version Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DXM Agent Console 交付为生产级真实店小秘两段式自动化产品：第一段从数据采集认领到采集箱，第二段从采集箱编辑商品并只保存。

**Architecture:** 保持现有 React/Vite/Electron/FastAPI/SQLite/Playwright 架构，不重写技术栈。产品主路径按业务阶段拆分，普通用户只看到“登录、数据采集认领、采集箱商品、模板、只保存、结果”，`claim_only`、`single_save`、L2、probe、run-id、HAR、原始异常等工程概念只进入维护诊断。

**Tech Stack:** React 18 + TypeScript + Vite, Electron portable desktop, FastAPI, SQLite repository, Playwright headed browser automation, pytest contract tests, PowerShell desktop package verification.

---

## 0. 当前状态

**当前有效工作树:** `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage`

**当前分支:** `feature/dxm-production-two-stage`

**最近已完成提交:**

- `bd24b1e test: align browser QA with two-stage workflow`
- `1de8a88 feat: simplify two-stage production navigation`

**当前完成度:** 约 74%。这不是可交付结论，只表示方向、导航、QA 脚本和部分两段式底座已转向生产路径。

**现在最重要的事实:**

1. 正确业务逻辑不是“本地选测试商品然后保存”，而是“店小秘数据采集认领到采集箱，再从采集箱编辑保存”。
2. 第一段页面不能出现第二段保存入口；认领完成后只能提示“去采集箱商品页选择已认领商品”。
3. 第二段只能从真实采集箱确认商品创建保存任务，不能从 fixture、手工导入、旧失败任务、伪造 payload 启动。
4. 认领完成必须有 `source_url`、店铺、认领标记、采集箱验证证据；缺任一关键证据不能生成可保存商品。
5. 浏览器必须显式常开，HUD 必须常驻显示中文业务进度，失败时保留现场并允许人工接管。
6. 模板中心必须是可维护的多套中文模板系统，不是写死配置或英文 key 表单。

## 1. 最终交付边界

### 1.1 允许交付

1. 免安装 EXE 启动 DXM Agent Console。
2. 打开真实店小秘浏览器。
3. 本机加密记住店小秘账号密码。
4. 用户人工处理验证码、登录异常和必要确认。
5. 第一段：在真实店小秘数据采集页定位商品并认领到采集箱。
6. 第一段完成后：记录真实 claimed product、来源链接、店铺、认领标记、采集箱确认。
7. 第二段：从已确认的采集箱商品创建单商品只保存任务。
8. 模板中心：按店小秘编辑页分区填写，支持多套模板和执行取值预览。
9. 真实浏览器 Agent 填写编辑页字段，只点击“保存”。
10. 结果页展示保存成功和未发布证明。

### 1.2 禁止交付

1. 发布。
2. 保存并发布。
3. 移入待发布。
4. 批量保存。
5. 无人值守写入。
6. 测试商品冒充真实商品。
7. 手工导入商品直接启动真实保存。
8. 未完成采集箱确认就进入第二段。
9. 失败任务复用为成功证据。

### 1.3 完成判定

只有全部满足以下条件，才算达到“可交付客户正常使用”：

1. 双击免安装 EXE 可启动，不需要两个命令行窗口。
2. 主窗口首屏只显示当前步骤、能不能继续、为什么阻断、下一步按钮。
3. 店小秘真实浏览器显式打开，并且 Agent 失败时不闪退。
4. 浏览器左上角 HUD 常驻，中文显示实时动作。
5. 第一段真实跑通：数据采集认领到采集箱。
6. 第二段真实跑通：采集箱编辑商品并只保存。
7. 保存成功证据存在。
8. 未发布证明存在。
9. 模板中心支持多套模板、中文分区、保存状态、执行取值预览。
10. 普通用户主路径不暴露 `L2`、`probe`、`run-id`、`HAR`、`greenlet`、`Internal Server Error`。
11. 发布、批量、无人值守在 UI 和 API 双层阻断。
12. 后端 focused tests 通过。
13. 前端 build 通过。
14. 桌面 portable package 验证通过。
15. 最终验收报告、Git HEAD、EXE SHA-256、真实验收证据一致。

## 2. 产品信息架构

### 2.1 主菜单

| 分组 | 菜单 | 用户理解 | 子功能 |
| --- | --- | --- | --- |
| 准备 | 首页 | 今天先做什么 | 当前步骤、阻断原因、下一步按钮、最近结果 |
| 准备 | 店小秘登录 | 连接真实店小秘 | 账号密码、记住账号、打开登录页、检测登录状态 |
| 第一段：采集认领 | 数据采集认领 | 把数据采集商品放进采集箱 | 店铺平台、来源链接、关键词、类目、认领标记、启动认领 |
| 第一段：采集认领 | 采集箱商品 | 管理已认领商品 | 已认领列表、来源链接、采集箱标题、可保存状态 |
| 第二段：编辑保存 | 模板中心 | 管理填写规则 | 多模板、中文分区表单、默认模板、执行取值预览 |
| 第二段：编辑保存 | 只保存任务 | 启动编辑保存 | 选择已认领商品、人工确认、启动保存、安全边界 |
| 现场执行 | 真实浏览器 | 看 Agent 操作现场 | 浏览器状态、HUD、人工接管、重试 |
| 结果复盘 | 结果与问题 | 看结果和处理失败 | 保存结果、未发布证明、恢复动作、维护诊断 |
| 系统维护 | 系统设置 | 管理本机运行环境 | 数据目录、日志、资源自检、版本信息 |

### 2.2 需要下沉的技术概念

这些内容不能作为普通用户一级菜单或首屏主文案：

- Agent 控制台
- 证据中心
- 异常池
- 任务中心
- 配置中心
- L2 / L3
- probe
- run-id
- HAR
- greenlet
- Playwright
- Internal Server Error

保留位置：`结果与问题 -> 维护人员查看技术状态` 或 `系统设置 -> 诊断信息`。

## 3. 版本路线图

### V0.9.2 已完成：QA 与导航转向两段式

**状态:** 已提交。

**已交付:**

- QA/browser 脚本不再把测试 single_save 当作生产路径。
- 侧边栏和首屏开始转向两段式业务语言。
- 当前分支已有“数据采集认领”和“采集箱编辑保存”的用户路径雏形。

**剩余风险:**

- 前端旧模块中仍有工程词和跨阶段跳转残留。
- 第一段页面仍能直接跳到第二段保存页面。
- 部分状态判断仍可能被旧任务、旧报告或缺证据数据污染。

### V0.9.3 当前优先版：第一段证据可信修复

**目标:** 第一段“数据采集认领”成为可信生产入口，不再产生弱证据或跨阶段误导。

**必须完成:**

1. `AcquisitionClaimRequest` 增加 `source_url`。
2. 来源链接、关键词、类目三者至少一个可作为商品线索。
3. 创建认领请求时不创建本地商品。
4. `claim_only` 执行完成时必须记录 `source_url`。
5. 缺 `source_url`、缺 claimed product、缺 draft box verification 时，认领任务失败且不能生成可保存商品。
6. 第一段 UI 删除“进入采集箱编辑保存”按钮。
7. 第一段完成后只显示“去采集箱商品页选择已认领商品”。

**验收标准:**

- `pytest tests\test_acquisition_claim_workflow.py tests\test_v1_runner.py -q` 通过。
- `pytest tests\test_frontend_demo_workflow_contract.py -q` 通过。
- `npm run build` 通过。
- UI 源码中 `AcquisitionClaimPage.tsx` 不再包含 `onShowDraftEdit`。

**完成度目标:** 74% -> 81%。

### V1.0 真实两段式可跑通版

**目标:** 单店单商品完成真实 DXM 生产主路径。

**用户路径:**

1. 打开免安装 EXE。
2. 店小秘登录成功。
3. 在“数据采集认领”输入来源链接、关键词或类目。
4. Agent 打开真实数据采集页。
5. Agent 定位商品并认领到采集箱。
6. 系统打开采集箱确认同一个商品。
7. 用户进入“采集箱商品”选择已认领商品。
8. 用户进入“只保存任务”确认模板。
9. 用户人工批准“只保存，不发布”。
10. Agent 打开真实编辑页并填写字段。
11. Agent 只点击保存。
12. 结果页显示保存成功和未发布证明。

**验收标准:**

- 真实店小秘完成一次 `数据采集认领 -> 采集箱确认`。
- 真实店小秘完成一次 `采集箱编辑 -> 只保存 -> 未发布证明`。
- 报告能关联同一商品的 `source_url`、claim result、draft box row、save result。
- 任何发布按钮、发布接口、保存并发布入口都会停止。

**完成度目标:** 81% -> 88%。

### V1.1 模板中心生产版

**目标:** 配置中心升级为运营可维护的多模板中心。

**模板类型:**

1. 系统默认模板。
2. 默认测试模板。
3. 店铺默认模板。
4. 类目默认模板。
5. 手动选择模板。
6. 本次任务覆盖。

**取值优先级:**

1. 本次任务覆盖。
2. 手动选择模板。
3. 类目默认模板。
4. 店铺默认模板。
5. 默认测试模板。
6. 系统默认模板。
7. 商品原始数据。

**分区表单:**

1. 店铺与任务基础。
2. 类目与标题。
3. SKU / 价格 / 库存。
4. 图片与素材。
5. 包装物流。
6. 合规 / 海关。
7. 半托管。
8. 店小秘引用模板。
9. 执行策略。

**每个分区动作:**

- 仅本次任务使用。
- 保存为店铺模板。
- 保存为类目模板。
- 另存为新模板。
- 套用默认测试模板。

**验收标准:**

- 用户能保存多套模板。
- 用户能看懂当前正在使用哪套模板。
- 修改字段后有明确“未保存/已保存”状态。
- 启动保存前能预览最终执行值和来源。
- 普通界面不显示英文 key。

**完成度目标:** 88% -> 93%。

### V1.2 浏览器 Agent 和 HUD 稳定版

**目标:** 用户能看到 Agent 正在真实店小秘浏览器里做什么，失败后可接管。

**浏览器要求:**

- 显式打开。
- 常开。
- 失败保留现场。
- 用户可人工接管。
- 不因任务失败直接关闭浏览器。

**HUD 要求:**

- 位于浏览器左上角。
- 黑色小窗。
- 中文实时刷新。
- 页面跳转、刷新、新标签页后自动重注入。

**HUD 业务步骤:**

- 准备打开店小秘。
- 检查登录状态。
- 打开数据采集。
- 搜索商品。
- 定位目标商品。
- 认领到采集箱。
- 确认采集箱商品。
- 打开编辑页。
- 填写标题。
- 选择分类。
- 设置 SKU / 价格 / 库存。
- 处理图片。
- 选择包装物流。
- 只点击保存。
- 检查未发布。
- 完成。

**验收标准:**

- HUD 经历至少 5 次页面跳转仍常驻。
- 浏览器关闭、验证码等待、页面加载失败、Agent 异常都有中文恢复提示。
- 主窗口状态、HUD 状态、后台任务状态一致。

**完成度目标:** 93% -> 96%。

### V1.3 客户自助与问题恢复版

**目标:** 普通运营用户不看技术日志也能继续处理。

**统一失败结构:**

1. 发生了什么。
2. 为什么停止。
3. 下一步怎么做。
4. 维护人员查看技术状态。

**覆盖失败场景:**

- 未登录。
- 验证码未处理。
- 未选择真实商品。
- 来源链接无法匹配。
- 找不到商品。
- 多个商品匹配。
- 认领失败。
- 采集箱未确认。
- 模板缺失。
- 浏览器被关闭。
- 保存失败。
- 检测到发布风险。

**验收标准:**

- 主路径不出现 `Internal Server Error`、`greenlet`、`Cannot switch to a different thread`。
- 每个失败都有明确按钮或下一步。
- 实时日志默认只显示业务事件 5 到 10 条。
- 完整日志进入维护诊断。

**完成度目标:** 96% -> 98%。

### V1.4 免安装客户交付版

**目标:** 输出客户可直接使用的 Windows 免安装目录。

**交付目录必须包含:**

- `DXM-Agent-Console-Portable-0.1.0.exe`
- `resources`
- 快速使用说明。
- 常见问题与恢复说明。
- 真实验收报告。
- 版本说明。
- EXE SHA-256。
- Git HEAD。

**验收标准:**

- `scripts\verify-desktop-package.ps1` 通过。
- `scripts\final-delivery-check.ps1` 通过。
- 真实两段式 DXM canary 通过。
- EXE 路径、Git HEAD、SHA-256、验收报告一致。

**完成度目标:** 98% -> 100%。

## 4. 实施任务

### Task 1: V0.9.3 第一段来源链接和证据硬化

**Files:**

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\models.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\repository.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_adapter.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_acquisition_claim_workflow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_v1_runner.py`

- [ ] **Step 1: 写来源链接输入测试**

Add to `app/backend/tests/test_acquisition_claim_workflow.py`:

```python
def test_acquisition_claim_request_accepts_source_url_hint(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")

    response = client.post(
        "/api/acquisition/claim-requests",
        json={
            "store_id": store["id"],
            "keyword": "",
            "category_name": "",
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "claim_mark": "AI-OPS",
            "template_id": None,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["source_url"] == "https://detail.1688.com/offer/1013604102950.html"
    assert data["task_id"] > 0
    assert repo.list_products(include_fixtures=True) == []
```

- [ ] **Step 2: 写缺来源链接失败测试**

Add to `app/backend/tests/test_v1_runner.py`:

```python
def test_claim_only_does_not_record_claimed_product_without_source_url(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    task = repo.create_acquisition_claim_request({
        "store_id": store["id"],
        "keyword": "Hazbin Hotel",
        "category_name": "立牌类谷子",
        "claim_mark": "AI-OPS",
        "template_id": None,
    })

    class MissingSourceUrlAdapter(FakeWorkflowAdapter):
        def _record(self, action, *args):
            result = super()._record(action, *args)
            if action == "verify_draft_box_claim":
                result["evidence"]["claimed_product"].pop("source_url", None)
            return result

    asyncio.run(V1TaskRunner(repo, DummyManager(), workflow_adapter=MissingSourceUrlAdapter()).run_task(task["id"]))

    assert repo.get_task(task["id"])["status"] == "failed"
    assert repo.list_claimed_draft_products() == []
```

- [ ] **Step 3: 实现 `source_url` 模型字段**

In `app/backend/src/models.py`:

```python
class AcquisitionClaimRequest(BaseModel):
    store_id: int
    keyword: str | None = None
    category_name: str | None = None
    source_url: str | None = None
    claim_mark: str
    template_id: int | None = None
```

- [ ] **Step 4: 规范化认领请求**

In `app/backend/src/main.py`, normalize source URL:

```python
source_url = str(payload.source_url or "").strip()
if not keyword and not category_name and not source_url:
    raise HTTPException(status_code=400, detail="请填写来源链接、搜索关键词或认领类目，用于定位真实采集商品")
data["source_url"] = source_url or None
```

- [ ] **Step 5: 仓储保存来源链接**

In `app/backend/src/repository.py`, include:

```python
"source_url": data.get("source_url"),
```

in the acquisition claim task payload and response.

- [ ] **Step 6: runner 传递来源链接**

In `app/backend/src/execution/v1_runner.py`, add:

```python
def _acquisition_source_urls(self, task: Mapping[str, Any]) -> list[str]:
    payload = task.get("payload") if isinstance(task.get("payload"), Mapping) else {}
    values = [payload.get("source_url"), payload.get("url")]
    source_urls = payload.get("source_urls")
    if isinstance(source_urls, (list, tuple)):
        values.extend(source_urls)
    return [str(value).strip() for value in values if isinstance(value, str) and value.strip()]
```

Then pass `target_source_urls=self._acquisition_source_urls(task)` to both `claim_from_data_acquisition` and `verify_draft_box_claim`.

- [ ] **Step 7: 认领完成记录必须强制证据完整**

Before `repo.create_product(...)` in `_record_claimed_product_from_acquisition`:

```python
if not isinstance(claimed, Mapping) or not claimed:
    raise V1ExecutionError("E202", "采集箱确认失败", "缺少采集箱商品证据，未记录可保存商品")
source_url = claimed.get("source_url") or evidence.get("source_url") or payload.get("source_url")
if not isinstance(source_url, str) or not source_url.strip():
    raise V1ExecutionError("E202", "采集箱确认失败", "缺少来源链接，不能证明采集箱商品来自本次数据采集认领")
```

- [ ] **Step 8: DXM 浏览器动作支持来源链接匹配**

In `dxm_adapter.py` and `dxm_login_flow.py`, add `target_source_urls` to `claim_from_data_acquisition` and `verify_draft_box_claim`; in `_find_data_acquisition_claim_target`, match row source links first when URL hint exists.

- [ ] **Step 9: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_v1_runner.py -q
```

Expected: all selected tests pass.

- [ ] **Step 10: 提交**

```powershell
git add app/backend/src app/backend/tests
git commit -m "feat: harden acquisition claim evidence"
```

### Task 2: V0.9.3 第一段 UI 去除保存入口

**Files:**

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AcquisitionClaimPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\App.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\types.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: 写 UI 合同测试**

Add to `app/backend/tests/test_frontend_demo_workflow_contract.py`:

```python
def test_acquisition_claim_page_does_not_offer_save_stage_entry():
    source = ACQUISITION_CLAIM_PAGE_TSX.read_text(encoding="utf-8")
    assert "从店小秘数据采集认领到采集箱" in source
    assert "不会进入编辑页" in source
    assert "不会保存" in source
    assert "不会发布" in source
    assert "onShowDraftEdit" not in source
    assert "进入采集箱编辑保存" not in source
```

- [ ] **Step 2: 增加来源链接输入**

In `AcquisitionClaimPage.tsx`:

```tsx
const [sourceUrl, setSourceUrl] = useState('')
const hasProductHint = Boolean(keyword.trim() || categoryName.trim() || sourceUrl.trim())
```

Add field:

```tsx
<label>
  <span>来源链接</span>
  <input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="1688、Temu 或其他采集来源链接" disabled={busy} />
</label>
```

- [ ] **Step 3: submit 传递来源链接**

```tsx
onCreateClaimRequest({
  storeId: selectedStore.id,
  keyword: keyword.trim() || undefined,
  categoryName: categoryName.trim() || undefined,
  sourceUrl: sourceUrl.trim() || undefined,
  claimMark: claimMark.trim(),
  templateId: templateId ? Number(templateId) : null,
})
```

- [ ] **Step 4: 删除跨阶段跳转 prop**

Remove `onShowDraftEdit` from:

- `AcquisitionClaimPageProps`
- component arguments
- `App.tsx` invocation
- all buttons inside `AcquisitionClaimPage.tsx`

Replace completion next step with:

```tsx
<span><strong>下一步</strong><b>去“采集箱商品”选择该商品</b></span>
```

- [ ] **Step 5: 更新前端类型**

In `types.ts`:

```ts
export type AcquisitionClaimCreateRequest = {
  storeId: number
  keyword?: string
  categoryName?: string
  sourceUrl?: string
  claimMark: string
  templateId?: number | null
}
```

- [ ] **Step 6: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
cd ..\frontend
npm run build
```

Expected: contract tests and build pass.

- [ ] **Step 7: 提交**

```powershell
git add app/frontend/src app/backend/tests/test_frontend_demo_workflow_contract.py
git commit -m "feat: keep acquisition claim UI in first stage"
```

### Task 3: V1.0 采集箱商品页和第二段入口

**Files:**

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\DraftEditSavePage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\App.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\repository.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_acquisition_claim_workflow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_task_start_guard.py`

- [ ] **Step 1: 写可保存商品过滤测试**

Add to `test_acquisition_claim_workflow.py`:

```python
def test_claimed_products_requires_source_url_and_draft_box_verification(tmp_path, monkeypatch):
    client, repo = _client_with_temp_repo(tmp_path, monkeypatch)
    store = repo.create_store("Dang Kang", "AliExpress")
    valid = repo.create_product({
        "title": "真实采集商品 A",
        "source": "dxm_data_acquisition",
        "status": "claimed_to_draft",
        "category_name": "立牌类谷子",
        "price": 9.9,
        "currency": "USD",
        "sku_count": 1,
        "image_count": 1,
        "payload": {
            "source": "dxm_data_acquisition",
            "store_id": store["id"],
            "store_name": "Dang Kang",
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "claim_task_id": 42,
            "draft_box_verified": True,
        },
    })
    repo.create_product({
        "title": "缺来源链接商品",
        "source": "dxm_data_acquisition",
        "status": "claimed_to_draft",
        "category_name": "立牌类谷子",
        "price": 9.9,
        "currency": "USD",
        "sku_count": 1,
        "image_count": 1,
        "payload": {"source": "dxm_data_acquisition", "draft_box_verified": True},
    })

    response = client.get("/api/acquisition/claimed-products")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [valid["id"]]
```

- [ ] **Step 2: 后端过滤必须要求 source_url**

In `Repository.list_claimed_draft_products()`:

```python
source_url = self._first_source_url(payload)
if not source_url:
    continue
```

- [ ] **Step 3: 第二段页面展示采集箱商品**

In `DraftEditSavePage.tsx`, first screen must show:

```tsx
<h2>从采集箱选择要编辑保存的商品</h2>
<p>这里只显示第一段已认领并通过采集箱确认的真实商品。</p>
```

Each item must show:

- 店铺。
- 商品标题。
- 来源链接。
- 认领标记。
- 采集箱验证状态。
- 创建只保存任务按钮。

- [ ] **Step 4: 创建保存任务时带 claimed proof**

When creating `single_save`, request payload must include the selected claimed product id only; backend attaches claim proof from product payload.

- [ ] **Step 5: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_task_start_guard.py -q
cd ..\frontend
npm run build
```

- [ ] **Step 6: 提交**

```powershell
git add app/frontend/src app/backend/src app/backend/tests
git commit -m "feat: gate save stage on verified claimed products"
```

### Task 4: V1.0 真实只保存执行闭环

**Files:**

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\delivery_workspace.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\ResultsPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_delivery_workspace.py`

- [ ] **Step 1: 写保存结果证据测试**

Add to `test_v1_runner.py`:

```python
def test_single_save_report_keeps_claim_source_and_unpublished_proof(v1_db):
    repo = Repository()
    store = repo.create_store("Dang Kang", "AliExpress")
    claimed = repo.create_product({
        "title": "真实采集商品 A",
        "source": "dxm_data_acquisition",
        "status": "claimed_to_draft",
        "category_name": "立牌类谷子",
        "price": 9.9,
        "currency": "USD",
        "sku_count": 1,
        "image_count": 1,
        "payload": {
            "source": "dxm_data_acquisition",
            "source_url": "https://detail.1688.com/offer/1013604102950.html",
            "draft_box_verified": True,
            "claim_mark": "AI-OPS",
        },
    })
    task = repo.create_task({
        "name": "单商品只保存 - Dang Kang - 1 件商品",
        "store_id": store["id"],
        "mode": "single_save",
        "publish_scene": "SMT_SEMI_MANAGED_SAVE_ONLY",
        "claim_mark": "AI-OPS",
        "product_ids": [claimed["id"]],
        "payload": {"store_name": "Dang Kang", "category_name": "立牌类谷子"},
    })

    asyncio.run(V1TaskRunner(repo, DummyManager(), workflow_adapter=FakeWorkflowAdapter()).run_task(task["id"]))

    assert repo.get_task(task["id"])["status"] == "completed"
    report = repo.list_reports(task["id"])[0]
    assert report["published"] is False
    assert report["summary"]["claimed_product_source_url"] == "https://detail.1688.com/offer/1013604102950.html"
```

- [ ] **Step 2: 保存入口继续要求人工批准**

Ensure `_assert_task_can_start` rejects `single_save` without `manual_approval`.

- [ ] **Step 3: publish guard 保持硬阻断**

If DXM page contains publish actions or network publish URLs, fail with customer-facing message:

```text
页面出现发布风险，系统已停止。请人工确认当前页面只保留“保存”操作后再重试。
```

- [ ] **Step 4: 结果页必须按业务展示**

`ResultsPage.tsx` visible summary:

- 保存状态。
- 是否发布。
- 商品。
- 来源链接。
- 使用模板。
- 保存时间。
- 下一步建议。

- [ ] **Step 5: 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_v1_runner.py tests\test_delivery_workspace.py -q
cd ..\frontend
npm run build
```

- [ ] **Step 6: 提交**

```powershell
git add app/backend/src app/backend/tests app/frontend/src
git commit -m "feat: complete controlled draft edit save flow"
```

### Task 5: V1.1 模板中心多模板和中文分区

**Files:**

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\template_center.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\config_preview.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\TemplateCenterPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\types.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_template_center_contract.py`

- [ ] **Step 1: 写模板优先级测试**

Add:

```python
def test_template_priority_prefers_task_selected_category_store_system():
    from src.services.template_center import resolve_template_priority

    result = resolve_template_priority({
        "task_override": {"template_name": "本次任务覆盖"},
        "selected": {"template_name": "手动选择模板"},
        "category_default": {"template_name": "类目默认模板"},
        "store_default": {"template_name": "店铺默认模板"},
        "sample_default": {"template_name": "默认测试模板"},
        "system_default": {"template_name": "系统默认模板"},
    })

    assert result["template_name"] == "本次任务覆盖"
    assert result["source_label"] == "本次任务覆盖"
```

- [ ] **Step 2: 写中文字段测试**

Add:

```python
def test_template_sections_use_customer_chinese_labels():
    from src.services.template_center import editable_template_sections

    sections = editable_template_sections()
    labels = [section["label"] for section in sections]

    for label in ["店铺与任务基础", "类目与标题", "SKU / 价格 / 库存", "图片与素材", "包装物流", "合规 / 海关", "半托管", "店小秘引用模板", "执行策略"]:
        assert label in labels
    for section in sections:
        for field in section["fields"]:
            assert field["label"]
            assert "_" not in field["label"]
```

- [ ] **Step 3: UI 顶部固定模板状态**

In `TemplateCenterPage.tsx`:

```tsx
<div className="template-status-strip">
  <span>当前模板：{currentTemplateName}</span>
  <span>保存状态：{dirty ? '有未保存修改' : '已保存'}</span>
  <span>执行取值：{previewReady ? '已生成预览' : '等待填写'}</span>
</div>
```

- [ ] **Step 4: 默认只展开一个分区**

```tsx
const [activeSectionId, setActiveSectionId] = useState(sections[0]?.id ?? 'task_basic')
const activeSection = sections.find((section) => section.id === activeSectionId) ?? sections[0]
```

- [ ] **Step 5: 每个分区固定动作**

```tsx
<button>仅本次任务使用</button>
<button>保存为店铺模板</button>
<button>保存为类目模板</button>
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
git add app/backend/src app/backend/tests app/frontend/src
git commit -m "feat: productionize Chinese template center"
```

### Task 6: V1.2 浏览器 Agent 常开和 HUD 常驻

**Files:**

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\browser_agent_status.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AgentExecutionPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_browser_agent_status.py`

- [ ] **Step 1: 写 HUD 中文映射测试**

Add:

```python
def test_hud_step_copy_uses_business_chinese():
    from src.services.browser_agent_status import build_browser_hud

    hud = build_browser_hud({"step": "CLAIM_TO_DRAFT_BOX", "status": "running"})

    assert hud["title"] == "正在认领商品"
    assert hud["line1"] == "把当前商品认领到采集箱"
    assert hud["severity"] == "running"
```

- [ ] **Step 2: 写 HUD 注入脚本测试**

Add:

```python
def test_hud_injection_uses_persistent_mount():
    from src.services.agent_console import build_hud_injection_script

    script = build_hud_injection_script({"title": "正在认领商品", "line1": "把当前商品认领到采集箱"})

    assert "dxm-agent-hud-root" in script
    assert "position: fixed" in script
    assert "z-index" in script
```

- [ ] **Step 3: 实现业务步骤映射**

In `browser_agent_status.py`:

```python
STEP_COPY = {
    "OPEN_DATA_ACQUISITION": ("正在打开数据采集", "进入店小秘数据采集页"),
    "CLAIM_TO_DRAFT_BOX": ("正在认领商品", "把当前商品认领到采集箱"),
    "VERIFY_DRAFT_BOX_CLAIM": ("正在确认采集箱", "检查商品是否已进入采集箱"),
    "OPEN_EDITOR": ("正在打开编辑页", "进入采集箱商品编辑页"),
    "FILL_TITLE": ("正在填写标题", "按当前模板填写商品标题"),
    "FILL_SKU_PRICE_STOCK": ("正在填写 SKU、价格和库存", "按当前模板写入销售信息"),
    "FILL_IMAGES": ("正在处理图片", "检查并补齐商品图片"),
    "SAVE_ONLY": ("正在只保存", "只点击保存，不发布"),
    "VERIFY_NOT_PUBLISHED": ("正在检查未发布", "确认商品没有发布"),
}
```

- [ ] **Step 4: 页面跳转后重注入**

After navigation or page switch in `dxm_login_flow.py`:

```python
self._ensure_browser_hud(page, self._current_hud_payload())
```

- [ ] **Step 5: Agent 异常不关闭浏览器**

On task failure, keep browser session open and set state:

```python
"browser_state": "open_needs_user_attention"
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
git commit -m "feat: keep browser agent visible and recoverable"
```

### Task 7: V1.3 用户化错误、日志和恢复

**Files:**

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\api.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\IssuesPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\ResultsPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AgentExecutionPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] **Step 1: 写错误结构测试**

Add:

```python
def test_customer_error_copy_uses_recovery_structure():
    source = (FRONTEND_SRC / "components" / "workbench" / "IssuesPage.tsx").read_text(encoding="utf-8")
    for required in ["发生了什么", "为什么停止", "下一步怎么做", "维护人员查看技术状态"]:
        assert required in source
    for forbidden in ["Internal Server Error", "Cannot switch to a different thread", "greenlet"]:
        assert forbidden not in source
```

- [ ] **Step 2: 后端统一用户问题结构**

In `main.py`:

```python
def user_problem(title: str, what: str, why: str, next_step: str, maintenance_detail: str | None = None) -> dict[str, str | None]:
    return {
        "title": title,
        "what": what,
        "why": why,
        "next": next_step,
        "maintenanceDetail": maintenance_detail,
    }
```

- [ ] **Step 3: 前端默认只显示业务日志**

In `AgentExecutionPage.tsx`:

```tsx
const visibleLogTags = new Set(['任务', '浏览器 Agent'])
const visibleLogs = logs.filter((item) => visibleLogTags.has(item.tag)).slice(0, 8)
```

- [ ] **Step 4: 完整日志进入诊断折叠**

```tsx
<details className="maintenance-details">
  <summary>维护人员查看技术状态</summary>
  <FullRuntimeLog logs={logs} />
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

- [ ] **Step 6: 提交**

```powershell
git add app/backend/src app/backend/tests app/frontend/src
git commit -m "feat: make runtime failures recoverable for users"
```

### Task 8: V1.4 免安装包和真实验收

**Files:**

- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\scripts\verify-desktop-package.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\scripts\final-delivery-check.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\最终交付验收记录-20260625-两段式生产版.md`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\免安装版快速使用说明-20260625.md`

- [ ] **Step 1: 后端 focused tests**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_v1_runner.py tests\test_task_start_guard.py tests\test_delivery_workspace.py tests\test_template_center_contract.py tests\test_agent_console.py tests\test_browser_agent_status.py -q
```

- [ ] **Step 2: 前端构建**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend
npm run build
```

- [ ] **Step 3: 桌面打包**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\desktop
npm run build:portable
```

- [ ] **Step 4: 覆盖免安装目录**

Copy the generated portable package to:

```text
D:\Desktop\DXM-Agent-Console-免安装版
```

The directory must include the EXE and the `resources` directory.

- [ ] **Step 5: package 验证**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

- [ ] **Step 6: 真实 DXM 验收**

Manual acceptance:

```text
1. 打开免安装 EXE。
2. 确认店小秘账号自动填充或可手动登录。
3. 在“数据采集认领”输入真实来源链接、关键词或类目。
4. 真实浏览器完成认领到采集箱。
5. 在“采集箱商品”选择已认领商品。
6. 在“模板中心”确认模板和最终执行取值。
7. 在“只保存任务”人工批准。
8. Agent 在真实浏览器执行只保存。
9. “结果与问题”显示保存成功和未发布证明。
10. 发布、批量、无人值守入口仍不可用。
```

- [ ] **Step 7: 生成验收报告字段**

Run:

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage
$gitHead = git rev-parse HEAD
$exePath = "D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe"
$sha = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
Write-Output "git_head=$gitHead"
Write-Output "portable_exe_sha256=$sha"
Write-Output "portable_exe_path=$exePath"
```

Create `docs/product/最终交付验收记录-20260625-两段式生产版.md` and record the exact command output plus:

```json
{
  "scope": "controlled_two_stage_single_product_save_only",
  "claim_to_draft": "passed",
  "draft_edit_save": "passed",
  "published": false,
  "batch_unattended_publish_allowed": false
}
```

- [ ] **Step 8: 提交并推送**

Run:

```powershell
git add scripts docs/product
git commit -m "docs: record two-stage DXM portable acceptance"
git push
```

## 5. 测试矩阵

### 每个后端任务后

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_v1_runner.py tests\test_task_start_guard.py -q
```

### 每个前端任务后

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend
npm run build
```

### 免安装包任务后

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

### 最终验收前

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
cd ..\desktop
npm run build:portable
```

## 6. 执行顺序

1. V0.9.3 Task 1：第一段来源链接和证据硬化。
2. V0.9.3 Task 2：第一段 UI 去除保存入口。
3. V1.0 Task 3：采集箱商品页和第二段入口。
4. V1.0 Task 4：真实只保存执行闭环。
5. V1.1 Task 5：模板中心多模板和中文分区。
6. V1.2 Task 6：浏览器 Agent 常开和 HUD 常驻。
7. V1.3 Task 7：用户化错误、日志和恢复。
8. V1.4 Task 8：免安装包和真实验收。

每个 Task 独立提交一次。涉及 UI 的 Task 必须用运行项目或浏览器验证可见效果；不能只凭代码猜测。涉及真实店小秘流程的 Task 必须保留真实浏览器、日志和证据路径。
