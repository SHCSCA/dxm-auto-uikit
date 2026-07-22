# CLAUDE.md

This file provides repository-level guidance for coding agents.

> 本仓库为中文项目，交流与提交说明默认用中文；命令、路径和标识符保留原文。

## 这是什么

DXM 半托管自动化工作台使用真实可见浏览器驱动店小秘账号，对商品箱中已经存在且身份可验证的商品按已确认模板编辑，并且只保存、不发布。

当前真实 mutation surface：

- `single_save`：单店、单商品、服务端批准、精确保存、独立未发布证明。
- `controlled_edit_batch`：冻结商品箱可见范围和顺序、一次批准、全局单并发、逐商品短 grant、严格串行。

认领环节和相关页面、API、任务模式、状态机、运行时动作与验收 schema 已删除。旧 `batch_save`、无人值守调度和任何发布动作仍未开放。

2026-07-22 当前源码发生了产品范围变更。在同一干净 Git HEAD 的全量回归、全新 portable、packaged/portable smoke、新鲜商品箱 L2 与真实保存证据完成前，生产交付保持 `BLOCKED`。旧包和历史 READY 只属于记录中的 commit 与范围。

## 仓库布局

- `app/backend/` — FastAPI、SQLite、任务/批次执行、Browser Agent 与证据门禁。
- `app/frontend/` — React + Vite 操作台。
- `app/desktop/` — Electron 桌面壳与 portable 打包。
- `scripts/` — Windows 启动、QA 和最终交付检查。
- `tools/probes/` — L1 离线 replay 与 L2 商品箱只读 probe。
- `config/l2_readonly_allowlist.json` — 显式、最小、人工审计的 L2 只读依赖。
- `docs/` — 当前规范与历史记录；入口是 `docs/README.md`。
- `data/`、`outputs/` — 本地 SQLite、日志、截图、证据和交付报告，均不得提交敏感内容。

## 常用命令

```bat
:: Windows 单窗口启动
scripts\start-mvp.bat --check
scripts\start-mvp.bat

:: 后端 L0
cd app\backend
.venv\Scripts\python.exe -m pytest -q

:: 聚焦测试
.venv\Scripts\python.exe -m pytest tests\test_delivery_workspace.py -q
.venv\Scripts\python.exe -m pytest tests\test_task_start_guard.py -q

:: 前端
cd app\frontend
npm install
npm run typecheck
npm run build

:: 桌面包
cd app\desktop
npm install
npm run build
npm run build:portable

:: L1
app\backend\.venv\Scripts\python.exe tools\probes\l1_selector_replay.py --output-dir data\l1_selector_replay

:: 最终自检
scripts\final-delivery-check.bat
scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness BLOCKED -ExpectedRealDxmSingleSaveEndToEnd pending_live_dxm_validation
```

L2 访问真实店小秘，必须获得用户明确批准。当前只允许 `--target draft_box`；`final-delivery-check` 只消费已产生的证据，不自动运行真实 L2。

## 后端结构

`src/main.py` 装配共享 `Repository`、WebSocket manager、配置/发布服务、真实浏览器链和 `V1TaskRunner`。真实动作通过持久化 `BrowserAgentRuntime` 调用 `DxmWorkflowAdapter -> DxmLoginFlow`；磁盘 runtime state 只能用于恢复/诊断，不能替代实时 browser/session/page/target 检查。

### 保存任务

`Repository.create_task(mode="single_save")` 要求恰好一个商品箱商品，并在创建时附加不可变 `product_box_snapshot`。快照包含 product/store/source/target/captured_at/evidence_ref 与 fingerprint。启动闸、runner 和交付工作台都必须重新验证它。

`src/state_machine/save_authorization.py` 是商品箱快照和保存授权事实的权威模块。不要恢复已删除的旧模块或兼容 alias。

### 受控整批

受控整批使用独立 batch/scope/item/ledger 表与 API，不等同于任务模式 `batch_save`。核心策略：

- 批准时冻结可见商品范围和顺序；
- 一次 approve-and-start；
- 全局并发 1；
- 每项 60 秒一次性 mutation grant；
- 保存前零写入失败可隔离；
- 派发后不确定性立即停批；
- `UNKNOWN` 人工对账，禁止自动重试。

### 保存成功判定

只点击规范化文本恰为“保存”的唯一按钮。保存成功必须有：

- 已消费批准与 ledger 派发事实；
- 保存前完整字段与冻结目标读回；
- DXM 精确保存 endpoint 的 POST 2xx、`code==0` 与成功消息；
- 页面新的或变化后的结构化成功状态；
- 零发布请求审计；
- 随后采集、同目标绑定且不复用保存文件的独立未发布读回。

顶层 `published=false`、文件名、按钮文案或模糊“ok”都不能替代这条证据链。

## 安全门禁

### L0–L3

- L0：离线单测与 fake adapter。
- L1：离线 DOM/selector replay。
- L2：真实商品箱只读 probe。必须验证登录态、目标/最终路径、截图和 DOM hash、零写网络计数、时效，以及精确 `evidence_binding.target_set=["draft_box"]`。
- L3：真实 `single_save` 金丝雀；需要批准、保存回包、保存证据与独立未发布证据。

mock L2 最高只能是 `mock_passed`，永不解锁真实写入。

### 发布封锁

`services/publish_guard.py` 对 action、按钮、弹窗、URL 和网络记录做内容扫描。发布、立即发布、继续发布、保存并发布、移入待发布等任何动作信号都必须 `E999`。任务 payload 强制 `publish_allowed=false`；直连 mutation endpoint 不能绕过 runner。

### 人工批准

服务端只存 token hash，读 API 不返回可重放 token。真实保存启动时原子消费批准；动作前继续核对批准上下文。`confirmation` 必须是 `CONFIRM_DXM_SAVE_ONLY`。

### Mutation ledger

稳定 mutation ID 进入持久化 ledger：

```text
PENDING -> DISPATCHING -> DISPATCHED
                  \-> UNKNOWN
```

进程重启、超时或结果不确定不能生成新 ID 再点击。`DISPATCHING` 恢复为 `UNKNOWN`；`UNKNOWN`/`DISPATCHED` 都不得自动重试。

## 不可破坏的不变量

- `dxm_single_save_acceptance.v1`、`dxm_state_consistency.v1`、L2/L3、runtime/build/package identity 任一缺失或冲突都只能 `BLOCKED`。
- 保存任务只能绑定商品箱现有商品；商品、店铺、来源、目标、证据或 fingerprint 漂移即停止。
- 动作前必须重查 lifecycle owner、browser session、精确页面、冻结目标、批准、deadline、cancel epoch 和 ledger。
- 保存证据与未发布证据必须独立；未发布证据必须晚于保存证据。
- `single_save` 的 READY 不扩大为受控整批；受控整批的 READY 不扩大为发布、旧批量任务或无人值守。
- AI 只做配置建议、标题或异常分析，不进入保存/发布决策闭环，不绕验证码。
- 当前运行代码、测试和同 HEAD 包证据优先于历史文档。

## 前端数据流

`App.tsx` 是主状态容器，轮询后端多个只读接口；`workspace.ts` 组合工作台数据并标记来源。前端禁用按钮只提供 UX，后端必须独立重算所有门禁。当前导航从商品箱编辑保存开始，不得恢复旧入口或旧字段兼容。

## 已知陷阱

- 正式执行恒用 `V1TaskRunner`；旧 simulator/probe 代码不能当生产路径。
- SQLite 无 FK 约束，引用完整性依赖应用层与状态一致性审计。
- 登录验证码需要可见浏览器；不要在活跃异步 Playwright 会话里另起同步 probe。
- `start-mvp` 后端端口 8000 被占用会失败；前端端口可顺延。
- 正式验收不要用 `-SkipBrowserQA`。
- `final-delivery-check.json` 必须联合读取 `okScope`、`realDxmMutationScope`、`singleSaveAcceptance`、`stateConsistency` 和 identity/证据路径，不能只看 `ok`。

## 关键文件

- 路由与启动闸：`app/backend/src/main.py`
- Repository 与 task/batch ledger：`app/backend/src/repository.py`
- 保存任务授权事实：`app/backend/src/state_machine/save_authorization.py`
- 保存状态机：`app/backend/src/state_machine/contracts.py`
- Runner：`app/backend/src/execution/v1_runner.py`
- Action result：`app/backend/src/execution/action_result_contract.py`
- Browser Agent：`browser_agent_protocol.py`、`browser_agent_worker.py`、`browser_agent_runtime.py`
- Mutation ledger：`app/backend/src/execution/mutation_dispatch_ledger.py`
- 真实浏览器：`dxm_login_flow.py`、`dxm_adapter.py`、`dxm_live.py`
- 交付聚合：`app/backend/src/services/delivery_workspace.py`
- 状态一致性：`app/backend/src/services/state_consistency.py`
- 发布封锁：`app/backend/src/services/publish_guard.py`
- L2：`tools/probes/l2_readonly_probe.py`、`tools/probes/l2_readonly_probe_runner.py`
- 最终自检：`scripts/final-delivery-check.ps1`
- 当前文档入口：`docs/README.md`

## 测试约定

- 开发中优先跑受影响的聚焦测试；任务收尾再跑一次后端全量和前端 production build。
- 保存/门禁变更优先覆盖 `test_delivery_workspace.py`、`test_task_start_guard.py`、`test_action_result_contract.py`、`test_mutation_dispatch_ledger.py`、`test_batch_execution_contract.py`、`test_publish_guard.py`。
- 删除功能时删除运行表面和旧契约测试，不保留静默兼容层；另加“旧路由/模式/字段不存在”的删除契约。
