> 由 OpenAI GPT（Codex）AI 生成/维护。

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本仓库为中文项目,后续交流与提交说明默认用中文。术语、命令、标识符保留原文。

## 这是什么

**DXM 半托管自动化工作台**:用真实可见浏览器驱动真实「店小秘」(dianxiaomi.com)账号,对采集箱/商品箱内商品按方案编辑并**「只保存、不发布」**。它不是本地演示页,也不是安全诊断工具。

### 当前产品主迭代（2026-08-28）

- **契约**: `docs/product/MVP-竖切-草稿箱批量只保存.md`
- **Gold 指令**: `docs/product/CODEX-GOLD-工作指令-MVP批量只保存.md`
- **主路径**: 一个具体店铺的草稿箱 `pageList(draft)` 多选 ≥3 → 方案 preview/freeze → **`batch_draft_save` 完整 Path B** → 主编辑 11 分区 → 主保存意图 Modal → `OPEN_SEMI_MANAGED_EDITOR` 触发店小秘原生门 → 按真实事件闭合实际 SAVE1 → 必要的 `SEMI_MANAGED_CONTINUE_TRANSITION` → `editFromSmt` 与第二次 SAVE → 独立最终未发布证明
- **每件商品无条件执行**: 视频、翻译、批发、半托管和 rollback preparation，缺一项即首写前拒绝；不得降级 Path A
- **类目**: `CategoryCatalog` 是本仓版本化参考，当前可见页面 category/Schema 才是写前执行权威
- **上游只读**: `D:\Desktop\py\DXM-TX`；只允许按当前合同提炼脱敏事实和同步已授权的纯类目结构，禁止当第二生产代码仓
- **当前裁定**: `E3_OPEN / BLOCKED`；不是 `MVP_READY`，不是 `PROD_READY`

### 安全与历史路径

整个系统的安全复杂度在:**在能操作真实卖家账号的前提下，用当前会话、不可变 snapshot、审批租约、JIT、队列 CAS、mutation ledger、读回和三铁证锁住每一次真实写入**。`claim_only` 与 `single_save` 只保留为历史受控路径和只读证据，**不是**完整商品批量主路径的前置必经；不得用历史 READY、旧 snapshot 或旧 portable 宣称当前批量已放行。

完整产品成功路径固定为 Path B。系统不得主动调用 `verifyPopChoiceShop` 或推断半托管资格；点击“编辑半托管信息”后只观察店小秘原生门。提示 Modal 不等于 SAVE1 完成，SAVE1 与门 outcome 的先后以同源 network/page/ledger 为准；半托管页首写前必须同时满足 SAVE1 verified、门 admitted 和正式页面 identity。中间精确“继续发布”只允许映射为 `SEMI_MANAGED_CONTINUE_TRANSITION`，用于进入冻结的 `editFromSmt`；最终发布、立即发布、保存并发布和移入待发布永久禁止。任何外部 mutation 派发后结果不确定都必须 `UNKNOWN` 停批且不得自动重试。

## 仓库布局(顶层)

- `app/backend/` — FastAPI + SQLite + WebSocket + Playwright 执行引擎(后端是绝大多数逻辑所在,~24K 行)
- `app/frontend/` — React 18 + Vite + TS 单页操作台(无 router/无状态库/无 WebSocket,靠轮询)
- `app/desktop/` — Electron 壳(`src/main.js` + `preload.js`,加载前端 URL,可选)
- `scripts/` — Windows 单窗口启动器 + 交付自检流水线(PowerShell 为主,`.bat` 是 shim)
- `tools/probes/` — L1 离线 selector replay、L2 真实只读 probe(其余 `draft-box/editor/navigation` 下是选择器探查的临时脚本,不属于交付链路)
- `docs/` — PRD、技术选型、全量字段矩阵、L1/L2 门禁规范、各次验收记录(产品意图与门禁规范的权威来源)
- `config/l2_readonly_allowlist.json` — L2 探针的人工评审白名单(必须显式传入才生效)
- `data/`、`outputs/` — 运行期产物(SQLite、证据、截图、日志、交付自检报告);均被 `.gitignore` 忽略

## 常用命令

后端有专用 venv:`app/backend/.venv/Scripts/python.exe`(下文记作 `PY`)。无独立 lint 工具——质量门禁就是 pytest + 前端 typecheck/build + L1 replay + 浏览器 QA。

```bat
:: 启动(Windows 单窗口,生产路径)。先检查环境,再启动后端8000+前端5173,健康检查过后自动开页
scripts\start-mvp.bat --check
scripts\start-mvp.bat

:: 后端全量测试(= L0 门禁)。在 app/backend 下运行,pyproject 已配置 pythonpath=src / testpaths=tests
cd app\backend && .venv\Scripts\python.exe -m pytest -q

:: 单个测试文件 / 单个用例(增量验证首选)
cd app\backend && .venv\Scripts\python.exe -m pytest tests\test_publish_guard.py -q
cd app\backend && .venv\Scripts\python.exe -m pytest tests\test_task_start_guard.py::<TestName> -q

:: 前端类型检查 / 生产构建(build 已串行执行 typecheck + vite build)
cd app\frontend && npm install && npm run typecheck
cd app\frontend && npm install && npm run build

:: Electron 桌面壳(可选;先构建前端,再打包到 outputs/desktop-build 等产物目录)
cd app\desktop && npm install && npm run build
cd app\desktop && npm run build:portable

:: L1 离线 selector replay 门禁(不访问店小秘;exit 0 通过 / 2 失败)
python tools\probes\l1_selector_replay.py --output-dir data\l1_selector_replay

:: 一键交付自检(串行跑:启动前检查→后端pytest全量→前端build→L1→git diff check→隔离浏览器QA→报告中心QA)
scripts\final-delivery-check.bat
scripts\final-delivery-check.bat -RequireCleanWorktree   :: 源码发布包验收:额外要求 git 工作区干净
```

非 Windows 开发备用(无健康门禁、无 job object):`bash scripts/start-backend.sh` / `start-frontend.sh` / `start-mvp.sh`。

未发现 `.cursor/rules/`、`.cursorrules` 或 `.github/copilot-instructions.md`;后续若新增这些规则,需把与本仓库安全门禁/命令相关的内容同步进本文件。

L2 真实只读 probe 需要**真实登录 cookie + 人工审批**,不由 `final-delivery-check` 自动运行;两个目标(`data_acquisition` / `draft_box`)必须用**同一个 `--run-id`** 各跑一次,流水线只消费其已产出的证据。

## 架构大图(需读多文件才能拼出)

### 后端进程结构
`app/backend/src/main.py` 在 import 时把一切装配成单例:一个共享 `Repository`(SQLite)、一个 `ConnectionManager`(WS 广播)、`PlaywrightEngine`(仅静态能力描述,**不执行任何自动化**)、以及 `DxmLiveClient → DxmLoginFlow → DxmWorkflowAdapter` 这条真实浏览器链、若干 services,和把它们串起来的 `V1TaskRunner`。CORS 锁死在 loopback 正则;`/artifacts/{screenshots,evidences}` 静态暴露 `DATA_DIR` 子目录(敏感的 `sessions/sqlite/ai` 不暴露)。

### 执行 = 状态机 + 模式/路径双门禁
- `state_machine/contracts.py` 定义 `ExecutionMode`(probe/dry_run/claim_only/single_save/batch_save/batch_draft_save)、`FORBIDDEN_EXECUTION_MODES`(publish/continue_publish/save_and_publish,被 `normalize_execution_mode` 直接拒绝)、`StateName` 枚举与节点不变量。
- `execution/v1_runner.py` 的 `V1_STEPS` 是基础保存流水线,另有独立 `CLAIM_ONLY_STEPS` 与冻结批次路径。`batch_draft_save` 只能从 plan snapshot 创建；Path A 可进入现有执行合同，Path B 虽可配置/preview/freeze，但批准、启动和 Runner 仍由 `PLAN_PATH_EXECUTION_NOT_RELEASED` 阻断。这是「爆炸半径」的结构性边界。
- **真假分流的唯一开关仍是 `workflow_adapter`**,但真实路径已经由持久化 `BrowserAgentRuntime` 承载。`V1TaskRunner` 构造带 command ID、幂等/变更标识、deadline、runtime/session/page/target 绑定和取消纪元的命令,worker 再调用 `DxmWorkflowAdapter → DxmLoginFlow`。若 `workflow_adapter is None`,真实写入模式直接失败;probe/dry_run 仍保持非真实写入。
- **真实浏览器不是每步重开。** `DxmLoginFlow` 持有可见 browser/context/page,`BrowserAgentRuntime` 在 Stage A/Stage B 动作间维持同一受控会话并做生命周期接管。磁盘 runtime state 只作为恢复/诊断资料,不能替代实时 session、精确页面、目标绑定和动作前复核。
- **save 判定以真实保存证据为准且文字精确**:`_save_only_on_page` 只点规范化文本**恰为「保存」**的按钮,若发现任何发布类按钮则中止;保存成功接受 DOM 出现「保存成功/编辑保存成功/编辑成功」或保存接口回包成功。真实接口包括 `.../api/smtProduct/add.json` / `.../api/popChoiceProduct/add.json`,必须是 POST、2xx、`code==0` 且成功文案命中;显式排除 publish/release/online/history URL。report/log 全程 `published=false`。

### 安全门禁——这是本仓库最该读懂的部分
两套正交机制叠加,详见 `services/delivery_workspace.py`(定义/计算 L0–L3 与严格 L2 闸门)、`main.py`(执行强制点)、`services/publish_guard.py`(内容扫描)。

1. **L 阶梯**(promotion ladder):
   - L0 = 离线单测 + 假 adapter(从不接触 DXM);L1 = 离线 DOM/selector fixture replay;**L2 = 真实登录态、只读、双目标网络探针**(产出 JSON 证据);L3 = 真正执行的单商品 save-only 金丝雀。
   - **只有 L2 状态会直接卡 API**。`_l2_probe_gate()` / `l2_real_probe_gate()` 极严:两个目标都必须 `ok` 且 `safety.ok`、最终 URL 落在 dianxiaomi.com、截图/DOM 文件的 SHA-256 与记录一致、五个网络计数器(write/non-read/blocked/forbidden-keyword/websocket)全为 0、两目标共享同一 run 绑定(`run_id`+`script_sha256`+`git_head`+session 指纹)且在 30 分钟偏差 / 2 小时新鲜度窗口内。任何不达标降级为 `failed`/`mock_passed`/`not_run`,真实写入保持关闭。mock/离线证据最高只能 `mock_passed`,**永不**解锁真实 L3。

2. **Publish guard**(`publish_guard.py`,无状态内容扫描):对 action/目标文本/URL/可见文本/弹窗文本/网络 URL 规范化后,命中任何发布信号(立即发布/继续发布/保存并发布/移入待发布/精确「发布」/`submitpublish` 等)即 `allowed=False`、`risk_level=critical`、`E999`。它放行仅提及「待发布」状态的良性文案,只拦发布**动作**。Runner 在 `PRECHECK_PUBLISH_GUARD`、`PRE_SAVE_GUARD_CHECK`、`SAVE_ONLY` 三处调用它。

3. **任务启动闸**(`main.py`):`REAL_DXM_MUTATION_MODES = {claim_only, single_save, batch_save, batch_draft_save}`；受控 mode surface 包含 `batch_draft_save`，但它还必须经过 frozen snapshot 与 execution path 子门禁，当前只释放 Path A，Path B 返回 `403 BATCH_PATH_B_FORBIDDEN`。两阶段 legacy 模式与冻结批次各自要求 publish scene、确认文本和服务端审批租约；令牌只存 hash，读 API 不回显。`try_start_task` 用原子 SQL 做单飞 draft→running；启动后每个真实 mutation 前仍要重新校验已消费租约和动作上下文。

4. **直连变更端点是「陷阱闸」**:`/api/dxm/draft-box/action`、`/workflow/claim-product`、`/workflow/open-editor` 走 `_assert_direct_real_dxm_mutation_allowed`——它跑完整启动闸校验后**无条件 raise 403**。即便一个完全合法、已审批、L2 已过的请求也返回 403:真实变更在产证据的 runner 之外**结构上不可能发生**。

5. **双重阻断(backend + frontend)**:前端 `App.tsx`/`WorkbenchModules.tsx`/`SafetyStatusBar.tsx` 镜像同样的常量并禁用按钮,但这**纯属 UX**;后端对每个条件独立重算,绕过 UI(curl/回放/自动化)照样撞 403。`test_task_start_guard.py` / `test_publish_guard.py` 是这套契约的可执行测试。

### 配置如何流入一次任务绑定
`config_defaults.py` 的 `ConfigDefaultsResolver` 是 legacy/非冻结任务的合并引擎,优先级:**store 模板(反序遍历,靠前的赢)< product payload < task payload < task `template_overrides`(最高)**。流程:前端 `GET /api/config/preview?task_id`(`config_preview.py` 的 9 个 `FIELD_GROUPS`,带 value/source/missing)→ `PATCH /api/tasks/{id}/config-overrides`(`task_basic` 写顶层 payload 键,其余写 `payload['template_overrides'][section]`)→ 运行时 `v1_runner._execution_defaults()` 调同一个 Resolver。**冻结的 `batch_draft_save` 是明确例外**：创建后不得再改 override，PATCH 返回 `409 BATCH_PLAN_SNAPSHOT_IMMUTABLE`，必须重新 preview/freeze 新快照。`config_validation.py` 按模式校验:`E999`=发布模式/意图,`E302`=配置不全。

任务列表默认 `GET /api/tasks` 返回公开 payload；工作台批次摘要必须使用 `GET /api/tasks?mode=batch_draft_save&view=summary`，该查询不读取或解码冻结 `payload_json`，不能用摘要接口还原 execution payload。

### 前端数据流
无后端推送:`App.tsx` 是唯一有状态容器,用多个 `setInterval` **轮询**(runtime 日志 1.5s、agent-console 3.5s、runtime status 5s),刷新时 `Promise.all` ~11 个并发 fetch,每个用 `loadOrFallback` 优雅降级。`workspace.ts/composeWorkspace` 合并统一 workspace 接口 + 各 REST 列表 + 内置 fallback,并把数据源标为 `api/fallback/mock`。所谓「页内真实 DXM 浏览器」**不是 iframe**,而是服务端无头浏览器截图的 `<img>`(`AgentBrowserFrame`),点击坐标映射后 POST `/api/agent-console/control`。`vite.config.ts` 把 `/api`、`/ws` 代理到 `127.0.0.1:8000`(`/ws` 代理存在但客户端从不连)。

## 不可破坏的不变量(改这些前先停下来)

- **生产结论必须 fail-closed**:`dxm_two_stage_acceptance.v1`、`dxm_state_consistency.v1`、L2/L3、runtime/build/package identity 任一缺失或冲突,都只能是 `BLOCKED`。
- **Mutation 不确定性不能自动重试**:持久化 mutation ledger 必须以稳定审批/任务 scope 生成动作 ID;进程崩溃时仍处于 `DISPATCHING` 的动作恢复为 `UNKNOWN`,只允许人工对账,不得因为换 runtime 或重启而再次点击。
- **动作前实时身份复核**:真实点击前必须重查 browser session、精确页面、目标绑定、审批租约和生命周期 owner。授权检查通过不代表稍后点击仍然安全。

- **当前生产放行范围是 `none` (`BLOCKED`)**。解释 `final-delivery-check.json` 时不能只看 `ok`:必须连同 `okScope`、`realDxmMutationScope`、`realDxmWriteReadiness`、`twoStageAcceptance`、`stateConsistency`、Git/runtime/build/package identity 和证据路径一起读。该 JSON 写入时带 **UTF-8 BOM**,Python 解析须 `encoding='utf-8-sig'`。
- **发布四层独立封锁**:`config_validation` 的 E999、`repo.create_task` 强制 `publish_allowed=False`、`agent_console` 的 `BLOCKED_SELECTOR_CONTROL_KEYWORDS` + 仅允许 dianxiaomi.com 的 goto、`selector_profile` 的 `forbidden_buttons`(经 L1 replay 暴露)。删任何一层都不会开放发布,但每层都假设其他层存在。
- **两段式不是范围复用**:`claim_only` 与 `single_save` 各自建立审批和动作证据,Stage B 必须绑定 Stage A 的同商品事实。`batch_draft_save` 使用独立 snapshot/审批/队列/JIT/ledger 合同；Path A 代码不能授权 Path B，`batch_save` 也继续未释放。
- **真实写入硬约束**:店铺来自任务与真实页面的权威绑定,不得硬编码或跨店复用证据;只操作 Stage A 来源、Stage B 快照与当前页面一致的同一商品。store/title/SKU/product_id/来源/商品箱证明任一冲突即停止(商品归属锁 `ownership_lock.py`)。
- **AI 不进执行闭环**:`title_ai.py`(DeepSeek 标题改写)等 AI 只做配置建议/标题/异常分析,绝不临场决定类目/品牌/是否发布、绝不绕验证码。
- **Browser-Use 是预留增强引擎,不是底座**:执行层走统一 ExecutionEngine 抽象,默认 `PlaywrightEngine`,`BrowserUseEngine` 仅扩展位。业务中台(模板中心/状态机/异常池/证据)必须自建。

## 已知陷阱

- `execution/simulator.py`(旧 `TaskRunner`)与 `execution/dxm_probe.py` **未被 src 引用**:生产恒用 `V1TaskRunner`;app 的真实 L2 探针是 `DxmLiveClient.probe_session` + `tools/probes/l2_readonly_probe.py`。
- `config_preview.py` 内有一大批 `_` 前缀的**死方法**(复刻 `ConfigDefaultsResolver`),`build()` 从不调用——重构陷阱。
- `batch_draft_save` 已有开始、暂停、继续、停止的持久状态/API/UI 合同；只有状态迁移不合法时返回 409。它们尚未在完整 Path B 三商品任务上完成真机同源 DoD，不能由路由存在推断 E4 已验收。legacy 真实写入任务仍有更严格限制。
- SQLite **无 FK 约束**,引用完整性只在应用层;每请求独立开关连接(无连接池),`check_same_thread=False`;迁移仅 `_ensure_columns` 增量 `ALTER ADD COLUMN`,无降级。
- 登录(验证码)需**可见**浏览器窗口(`continue_login` 依赖人工解码后提交);`DxmWorkflowAdapter.check_login_state()` 必须先复用这个可见登录浏览器的已登录状态，再降级到 `DxmLiveClient.probe_session()`。不要在可见 Playwright 会话仍活着时另起同步 probe，否则容易触发 `Playwright Sync API inside the asyncio loop` / greenlet 线程错误并误报“登录未通过”。
- `start-mvp` 后端端口 **8000 硬占用,被占即失败**(前端 5173 会自动顺延);`delivery_workspace.py` 为 L2 探针命令硬编码了 Windows 反斜杠路径,**隐含面向 Windows**。
- 正式验收**不要**用 `final-delivery-check.bat -SkipBrowserQA`(开发专用,跳过 403 阻断断言)。`-RequireCleanWorktree` 下有未提交改动会把 `Source package check` 标 FAIL。

## 关键文件索引

- 装配 + 启动闸 + 路由 + artifact URL:`app/backend/src/main.py`
- L0–L3 门禁定义/计算 + L2 严格闸 + 发布放行计划:`app/backend/src/services/delivery_workspace.py`
- 两段式验收与状态一致性:`app/backend/src/state_machine/two_stage.py`、`app/backend/src/services/state_consistency.py`
- Browser Agent 协议/生命周期/动作契约:`app/backend/src/execution/browser_agent_protocol.py`、`browser_agent_worker.py`、`action_result_contract.py`;持久化 mutation 派发账本:`mutation_dispatch_ledger.py`
- 发布拦截:`app/backend/src/services/publish_guard.py`;商品归属锁:`services/ownership_lock.py`
- 24 状态机执行引擎:`app/backend/src/execution/v1_runner.py`
- 真实浏览器驱动:`app/backend/src/execution/dxm_login_flow.py`(facade:`dxm_adapter.py`,只读探针:`dxm_live.py`)
- 模式/状态/禁用模式枚举:`app/backend/src/state_machine/contracts.py`
- 配置合并/校验/预览:`services/config_defaults.py`、`config_validation.py`、`config_preview.py`
- 前端控制流从这读起:`app/frontend/src/App.tsx`;全部面板:`components/WorkbenchModules.tsx`;客户端派生:`workspace.ts`
- 交付自检流水线:`scripts/final-delivery-check.ps1`;浏览器 QA:`scripts/qa-browser-check.ps1`;启动器:`scripts/start-mvp.ps1`
- 当前文档入口:[docs/README.md](docs/README.md);MVP 产品与安全主合同:[docs/product/MVP-竖切-草稿箱批量只保存.md](docs/product/MVP-竖切-草稿箱批量只保存.md);当前代码事实:[docs/architecture/当前运行时架构.md](docs/architecture/当前运行时架构.md);目标开发路线:[docs/architecture/DXM-工作台与分区自动化统一开发方案.md](docs/architecture/DXM-工作台与分区自动化统一开发方案.md);逐分区真实操作:[docs/runbook/运营操作详细文档.md](docs/runbook/运营操作详细文档.md);操作与验收:[docs/runbook/操作与验收手册.md](docs/runbook/操作与验收手册.md)。已删除旧文档不是现行指针,不得据此宣称 READY。
- 批量保存配置模型：`app/backend/src/batch_edit/path_a_section_templates.py`（VideoGenerationConfig、AutoTranslateConfig、WholesaleConfig、SemiManagedConfig、BatchDraftSaveConfig）
- 批量保存执行器：`app/backend/src/batch_edit/video_generator.py`（产品视频生成器）
- 批量保存执行器：`app/backend/src/batch_edit/translator.py`（一键翻译执行器）
- 批量保存执行器：`app/backend/src/batch_edit/wholesale_filler.py`（批发配置器）
- 批量保存执行器：`app/backend/src/batch_edit/semi_managed_executor.py`（半托管执行器）
- 批量保存执行器：`app/backend/src/batch_edit/rollback_manager.py`（回滚管理器）
- 铁证收集：`app/backend/src/services/evidence_collector.py`（批量保存专属铁证类型）

## 测试与协作约定(本仓库)

- **增量优先**:开发中只跑与改动相关的目标测试(`pytest tests\test_xxx.py -q`),不要反复跑全量。**任务收尾时**再跑一次后端全量 `pytest -q`;需要交付级别确认时跑一次 `scripts\final-delivery-check.bat`。
- 修改触及门禁/状态机/保存路径时,对应的契约测试(`test_task_start_guard.py`、`test_publish_guard.py`、`test_v1_runner.py`、`test_delivery_workspace.py`、`test_login_flow.py`)是首选回归。
- 涉及真实 DXM 写入语义的改动,必须保持 L0–L3 fail-closed 与「四层发布封锁」不被削弱;有疑问时按「更安全」一侧选择。
