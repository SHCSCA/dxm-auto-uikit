# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本仓库为中文项目,后续交流与提交说明默认用中文。术语、命令、标识符保留原文。

## 这是什么

**DXM 半托管自动化工作台**:用真实浏览器驱动真实「店小秘」(dianxiaomi.com)账号,把速卖通(SMT)采集箱商品按模板补齐字段并**「只保存到待发布、永不发布」**。它不是本地演示页,也不是安全诊断工具。

整个系统的核心价值与全部复杂度都在一件事上:**在能操作真实卖家账号的前提下,用分层证据门禁(L0→L1→L2→L3)把「真实写入」死死锁住,使得唯一被放行的真实变更只有「单店(Dang Kang)、单商品、save-only、带服务端一次性审批令牌、且有新鲜只读探针证据」的受控金丝雀**。改动本仓库时,默认假设你正在靠近这套门禁——任何让真实写入/发布更容易发生的改动都是高危改动。

最新归档交付记录为 `docs/product/最终交付验收记录-20260622.md`，当次 `realDxmWriteReadiness = READY`，但范围严格为 `controlled_single_save_only`。L2 真实只读证据有新鲜度窗口；实时状态必须以当前工作台或最新 `final-delivery-check` 为准。`claim_only` / `batch_save` / 批量 / 无人值守 / 任何发布动作**均未放行**。

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

后端有专用 venv:`app/backend/.venv/Scripts/python.exe`(下文记作 `PY`)。无独立 lint 工具——质量门禁就是 pytest + 前端 build + L1 replay + 浏览器 QA。

```bat
:: 启动(Windows 单窗口,生产路径)。先检查环境,再启动后端8000+前端5173,健康检查过后自动开页
scripts\start-mvp.bat --check
scripts\start-mvp.bat

:: 后端全量测试(= L0 门禁)。在 app/backend 下运行,pyproject 已配置 pythonpath=src / testpaths=tests
cd app\backend && .venv\Scripts\python.exe -m pytest -q

:: 单个测试文件 / 单个用例(增量验证首选)
cd app\backend && .venv\Scripts\python.exe -m pytest tests\test_publish_guard.py -q
cd app\backend && .venv\Scripts\python.exe -m pytest tests\test_task_start_guard.py::<TestName> -q

:: 前端生产构建(注意:build 脚本只有 vite build,没有独立 tsc 类型检查,类型错误不一定让 build 失败)
cd app\frontend && npm install && npm run build

:: L1 离线 selector replay 门禁(不访问店小秘;exit 0 通过 / 2 失败)
python tools\probes\l1_selector_replay.py --output-dir data\l1_selector_replay

:: 一键交付自检(串行跑:启动前检查→后端pytest全量→前端build→L1→git diff check→隔离浏览器QA→报告中心QA)
scripts\final-delivery-check.bat
scripts\final-delivery-check.bat -RequireCleanWorktree   :: 源码发布包验收:额外要求 git 工作区干净
```

非 Windows 开发备用(无健康门禁、无 job object):`bash scripts/start-backend.sh` / `start-frontend.sh` / `start-mvp.sh`。

L2 真实只读 probe 需要**真实登录 cookie + 人工审批**,不由 `final-delivery-check` 自动运行;两个目标(`data_acquisition` / `draft_box`)必须用**同一个 `--run-id`** 各跑一次,流水线只消费其已产出的证据。

## 架构大图(需读多文件才能拼出)

### 后端进程结构
`app/backend/src/main.py` 在 import 时把一切装配成单例:一个共享 `Repository`(SQLite)、一个 `ConnectionManager`(WS 广播)、`PlaywrightEngine`(仅静态能力描述,**不执行任何自动化**)、以及 `DxmLiveClient → DxmLoginFlow → DxmWorkflowAdapter` 这条真实浏览器链、若干 services,和把它们串起来的 `V1TaskRunner`。CORS 锁死在 loopback 正则;`/artifacts/{screenshots,evidences}` 静态暴露 `DATA_DIR` 子目录(敏感的 `sessions/sqlite/ai` 不暴露)。

### 执行 = 24 状态机 + 模式截断
- `state_machine/contracts.py` 定义 `ExecutionMode`(probe/dry_run/claim_only/single_save/batch_save)、`FORBIDDEN_EXECUTION_MODES`(publish/continue_publish/save_and_publish,被 `normalize_execution_mode` 直接拒绝)、`StateName` 枚举与节点不变量。
- `execution/v1_runner.py` 的 `V1_STEPS` 是 24 步流水线;`MODE_LAST_STATE` 决定每种模式跑到哪一步就停:`dry_run` 只跑 `PRECHECK_CONFIG`;`probe` 停在 `PRECHECK_PUBLISH_GUARD`;`claim_only` 停在 `VERIFY_LIST_OWNERSHIP`(物理上永不开编辑器、永不发 `add.json`);`single_save`/`batch_save` 跑到 `RELEASE_LOCK`。这是「爆炸半径」的结构性边界。
- **真假分流的唯一开关是 `workflow_adapter`**。Runner 把特定状态映射成 `DxmWorkflowAdapter` 的真实浏览器动作,放在 **1 线程 ThreadPoolExecutor** 上跑(Playwright 同步 API 不能在 asyncio loop 上跑)。adapter 转发进 `dxm_login_flow.py`(5400 行,唯一真正驱动浏览器的地方)。若 `workflow_adapter is None`,真实写入模式直接 E901,而 probe/dry_run 仍作为纯骨架「成功」——生产 `main.py` 始终传真实 adapter。
- **步间状态只通过磁盘文件 `dianxiaomi_runtime_state.json` 传递**(page_url / source_editor_url / target_source_urls / save_result)。`DxmLoginFlow` 每个动作都**新开并关闭一整个浏览器**、重新注入 cookie、导航到上一步保存的 URL。没有跨步长存的 page,所以 state 文件缺失/过期会直接打断编辑/半托管步骤。
- **save 判定以真实保存证据为准且文字精确**:`_save_only_on_page` 只点规范化文本**恰为「保存」**的按钮,若发现任何发布类按钮则中止;保存成功接受 DOM 出现「保存成功/编辑保存成功/编辑成功」或保存接口回包成功。真实接口包括 `.../api/smtProduct/add.json` / `.../api/popChoiceProduct/add.json`,必须是 POST、2xx、`code==0` 且成功文案命中;显式排除 publish/release/online/history URL。report/log 全程 `published=false`。

### 安全门禁——这是本仓库最该读懂的部分
两套正交机制叠加,详见 `services/delivery_workspace.py`(定义/计算 L0–L3 与严格 L2 闸门)、`main.py`(执行强制点)、`services/publish_guard.py`(内容扫描)。

1. **L 阶梯**(promotion ladder):
   - L0 = 离线单测 + 假 adapter(从不接触 DXM);L1 = 离线 DOM/selector fixture replay;**L2 = 真实登录态、只读、双目标网络探针**(产出 JSON 证据);L3 = 真正执行的单商品 save-only 金丝雀。
   - **只有 L2 状态会直接卡 API**。`_l2_probe_gate()` / `l2_real_probe_gate()` 极严:两个目标都必须 `ok` 且 `safety.ok`、最终 URL 落在 dianxiaomi.com、截图/DOM 文件的 SHA-256 与记录一致、五个网络计数器(write/non-read/blocked/forbidden-keyword/websocket)全为 0、两目标共享同一 run 绑定(`run_id`+`script_sha256`+`git_head`+session 指纹)且在 30 分钟偏差 / 2 小时新鲜度窗口内。任何不达标降级为 `failed`/`mock_passed`/`not_run`,真实写入保持关闭。mock/离线证据最高只能 `mock_passed`,**永不**解锁真实 L3。

2. **Publish guard**(`publish_guard.py`,无状态内容扫描):对 action/目标文本/URL/可见文本/弹窗文本/网络 URL 规范化后,命中任何发布信号(立即发布/继续发布/保存并发布/移入待发布/精确「发布」/`submitpublish` 等)即 `allowed=False`、`risk_level=critical`、`E999`。它放行仅提及「待发布」状态的良性文案,只拦发布**动作**。Runner 在 `PRECHECK_PUBLISH_GUARD`、`PRE_SAVE_GUARD_CHECK`、`SAVE_ONLY` 三处调用它。

3. **任务启动闸**(`main.py`):`REAL_DXM_MUTATION_MODES = {claim_only, single_save, batch_save}`,但 `RELEASED_REAL_DXM_MUTATION_MODES = {single_save}` 才真正放行。`_assert_task_can_start` 与 `_assert_task_can_receive_manual_approval` 都要求:模式已放行、`publish_scene == SMT_SEMI_MANAGED_SAVE_ONLY`、`store == 'Dang Kang'`、审批 `source=='server'` 且 `approved`、请求 `approval_token` 与存储的 `token_hash` **HMAC 比对**(`hmac.compare_digest`)、`confirmation == 'CONFIRM_DXM_SAVE_ONLY'`、非空 `approved_by`、且 `l2_real_probe_gate().status == 'passed'`。审批令牌由 `/manual-approval` 用 `secrets.token_urlsafe(24)` 服务端生成、**只存 SHA-256 hash**;读 API(`_public_task_payload`)抹掉 token/token_hash,所以无法从 GET 回放。`try_start_task` 用一条原子 SQL(`UPDATE ... WHERE status='draft'`,rowcount==1)做单飞 draft→running。

4. **直连变更端点是「陷阱闸」**:`/api/dxm/draft-box/action`、`/workflow/claim-product`、`/workflow/open-editor` 走 `_assert_direct_real_dxm_mutation_allowed`——它跑完整启动闸校验后**无条件 raise 403**。即便一个完全合法、已审批、L2 已过的请求也返回 403:真实变更在产证据的 runner 之外**结构上不可能发生**。

5. **双重阻断(backend + frontend)**:前端 `App.tsx`/`WorkbenchModules.tsx`/`SafetyStatusBar.tsx` 镜像同样的常量并禁用按钮,但这**纯属 UX**;后端对每个条件独立重算,绕过 UI(curl/回放/自动化)照样撞 403。`test_task_start_guard.py` / `test_publish_guard.py` 是这套契约的可执行测试。

### 配置如何流入一次任务绑定
`config_defaults.py` 的 `ConfigDefaultsResolver` 是合并引擎,优先级:**store 模板(反序遍历,靠前的赢)< product payload < task payload < task `template_overrides`(最高)**。流程:前端 `GET /api/config/preview?task_id`(`config_preview.py` 的 9 个 `FIELD_GROUPS`,带 value/source/missing)→ `PATCH /api/tasks/{id}/config-overrides`(`task_basic` 写顶层 payload 键,其余写 `payload['template_overrides'][section]`)→ 运行时 `v1_runner._execution_defaults()` 调**同一个** Resolver,所以**预览值 == 执行值**。绑定就是任务 payload 里的 `template_overrides`,没有单独的表。`config_validation.py` 按模式校验:`E999`=发布模式/意图,`E302`=配置不全。

### 前端数据流
无后端推送:`App.tsx` 是唯一有状态容器,用多个 `setInterval` **轮询**(runtime 日志 1.5s、agent-console 3.5s、runtime status 5s),刷新时 `Promise.all` ~11 个并发 fetch,每个用 `loadOrFallback` 优雅降级。`workspace.ts/composeWorkspace` 合并统一 workspace 接口 + 各 REST 列表 + 内置 fallback,并把数据源标为 `api/fallback/mock`。所谓「页内真实 DXM 浏览器」**不是 iframe**,而是服务端无头浏览器截图的 `<img>`(`AgentBrowserFrame`),点击坐标映射后 POST `/api/agent-console/control`。`vite.config.ts` 把 `/api`、`/ws` 代理到 `127.0.0.1:8000`(`/ws` 代理存在但客户端从不连)。

## 不可破坏的不变量(改这些前先停下来)

- **放行范围只有 `controlled_single_save_only`**。解释 `final-delivery-check.json` 时不能只看 `ok`——必须连同 `okScope` / `realDxmMutationScope` / `realDxmWriteReadiness` 一起读;`ok:true` 仅代表 `okScope` 声明的范围。该 JSON 写入时带 **UTF-8 BOM**,Python 解析须 `encoding='utf-8-sig'`。
- **发布四层独立封锁**:`config_validation` 的 E999、`repo.create_task` 强制 `publish_allowed=False`、`agent_console` 的 `BLOCKED_SELECTOR_CONTROL_KEYWORDS` + 仅允许 dianxiaomi.com 的 goto、`selector_profile` 的 `forbidden_buttons`(经 L1 replay 暴露)。删任何一层都不会开放发布,但每层都假设其他层存在。
- **要扩到 `claim_only` 或 `batch_save`**:必须为对应范围**重新建立** L2/L3 证据链 + 人工审批 + 回滚策略,**不能复用** `single_save` 的结论。`real_mode_release_plan` 里 `single_save=released_controlled`,其余 `blocked_unreleased`,且在任何 L2/审批检查**之前**就被拒。
- **真实写入硬约束**:店铺只允许 `Dang Kang`;只操作带 `AI认领-{task_id}-{job_id}` 唯一备注且 store/title/SKU/product_id 与任务 payload 一致的商品(商品归属锁 `ownership_lock.py`)。
- **AI 不进执行闭环**:`title_ai.py`(DeepSeek 标题改写)等 AI 只做配置建议/标题/异常分析,绝不临场决定类目/品牌/是否发布、绝不绕验证码。
- **Browser-Use 是预留增强引擎,不是底座**:执行层走统一 ExecutionEngine 抽象,默认 `PlaywrightEngine`,`BrowserUseEngine` 仅扩展位。业务中台(模板中心/状态机/异常池/证据)必须自建。

## 已知陷阱

- `execution/simulator.py`(旧 `TaskRunner`)与 `execution/dxm_probe.py` **未被 src 引用**:生产恒用 `V1TaskRunner`;app 的真实 L2 探针是 `DxmLiveClient.probe_session` + `tools/probes/l2_readonly_probe.py`。
- `config_preview.py` 内有一大批 `_` 前缀的**死方法**(复刻 `ConfigDefaultsResolver`),`build()` 从不调用——重构陷阱。
- `pause/resume/stop` 对真实写入模式基本禁用(409);`resume` 永远 409;`clear_stuck_tasks` 跳过真实写入任务(`real_write_protected`)——operator 无法中途取消重置一个真实保存。
- SQLite **无 FK 约束**,引用完整性只在应用层;每请求独立开关连接(无连接池),`check_same_thread=False`;迁移仅 `_ensure_columns` 增量 `ALTER ADD COLUMN`,无降级。
- 登录(验证码)需**可见**浏览器窗口(`continue_login` 依赖人工解码后提交);`DxmWorkflowAdapter.check_login_state()` 必须先复用这个可见登录浏览器的已登录状态，再降级到 `DxmLiveClient.probe_session()`。不要在可见 Playwright 会话仍活着时另起同步 probe，否则容易触发 `Playwright Sync API inside the asyncio loop` / greenlet 线程错误并误报“登录未通过”。
- `start-mvp` 后端端口 **8000 硬占用,被占即失败**(前端 5173 会自动顺延);`delivery_workspace.py` 为 L2 探针命令硬编码了 Windows 反斜杠路径,**隐含面向 Windows**。
- 正式验收**不要**用 `final-delivery-check.bat -SkipBrowserQA`(开发专用,跳过 403 阻断断言)。`-RequireCleanWorktree` 下有未提交改动会把 `Source package check` 标 FAIL。

## 关键文件索引

- 装配 + 启动闸 + 路由 + artifact URL:`app/backend/src/main.py`
- L0–L3 门禁定义/计算 + L2 严格闸 + 发布放行计划:`app/backend/src/services/delivery_workspace.py`
- 发布拦截:`app/backend/src/services/publish_guard.py`;商品归属锁:`services/ownership_lock.py`
- 24 状态机执行引擎:`app/backend/src/execution/v1_runner.py`
- 真实浏览器驱动(5400 行):`app/backend/src/execution/dxm_login_flow.py`(facade:`dxm_adapter.py`,只读探针:`dxm_live.py`)
- 模式/状态/禁用模式枚举:`app/backend/src/state_machine/contracts.py`
- 配置合并/校验/预览:`services/config_defaults.py`、`config_validation.py`、`config_preview.py`
- 前端控制流从这读起:`app/frontend/src/App.tsx`;全部面板:`components/WorkbenchModules.tsx`;客户端派生:`workspace.ts`
- 交付自检流水线:`scripts/final-delivery-check.ps1`;浏览器 QA:`scripts/qa-browser-check.ps1`;启动器:`scripts/start-mvp.ps1`
- 门禁/产品规范权威文档:`docs/product/店小秘半托管执行器可交付化回归矩阵.md`、`docs/product/L2只读Probe门禁.md`、`docs/product/店小秘速卖通半托管自动化执行器_PRD_V1.0.md`

## 测试与协作约定(本仓库)

- **增量优先**:开发中只跑与改动相关的目标测试(`pytest tests\test_xxx.py -q`),不要反复跑全量。**任务收尾时**再跑一次后端全量 `pytest -q`;需要交付级别确认时跑一次 `scripts\final-delivery-check.bat`。
- 修改触及门禁/状态机/保存路径时,对应的契约测试(`test_task_start_guard.py`、`test_publish_guard.py`、`test_v1_runner.py`、`test_delivery_workspace.py`、`test_login_flow.py`)是首选回归。
- 涉及真实 DXM 写入语义的改动,必须保持 L0–L3 fail-closed 与「四层发布封锁」不被削弱;有疑问时按「更安全」一侧选择。
