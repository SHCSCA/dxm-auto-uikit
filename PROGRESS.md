> 由 OpenAI GPT（Codex）AI 生成/维护。

# 当前进度

## 2026-10-16 隔离验收与证据来源接线

- 继续在 `G:\AI\dxm-auto-uikit` 本地工作分支开发，不推送。上一轮 clean 固定点 `1f48ba2` 的完整 backend 回归为 `2123 passed / 0 failed / 0 skipped`；本轮修改后的数字、Git/包身份与检查结果另记在 `outputs/project-continuation-20261016/`，不能沿用旧包代替本轮验收。
- 用户已允许显示隔离测试窗口。验包脚本新增 `-AllowVisibleWindow`：默认先完成隐藏检查，再以 `PENDING_PERMISSION / exit 3` 保留未完成状态；明确传参才启动可见窗口，并核对 Electron 实际 `isVisible()`。这项授权不构成真实商品写入或保存授权。
- 登录检查也已改为仅请求当前 Playwright Page 置顶；删除按窗口标题猜测目标、全局枚举并抢焦的旧方法。更正上轮描述：该旧方法的生产调用方是登录检查，不能将其描述为仅手动显示入口。其它历史原生点击路径及超大文件仍须分阶段治理。
- 新增独立最终内容观察命令，沿现有 `V1TaskRunner → BrowserAgent → Adapter/Flow` 执行；仅允许精确只读 action/state，预约命令后核对 Worker 原请求/结果、截图及翻译前序，再追加来源。观察不从翻译回执复制最终值，也不生成必需能力回执。真实 FILL 模板完整性、视频来源和 11 分区完整覆盖仍未证明，不能据局部来源检查放开保存。
- 原生门新增独立被动采集窗口和摘要，但尚未接入获得独立授权的 `OPEN_SEMI_MANAGED_EDITOR`。采集结果仍为 `unbound / unreviewed / unknown`；生产响应语义注册表为空，不能产生 admitted、保存回执或执行授权。原 SAVE1/OPEN 时序和通用请求审计边界没有被合成证据替换。
- 用户已明确视频共同规则：保留弹窗默认选中的全部图片，转场和音乐采用弹窗当次实际默认值。必须观察完整选中集合、稳定标识与当前值并冻结，缺来源就拒绝，不能改为首张、前 N 张或以代码预设 `0 / none` 代填。视频业务规则不再待确认；尚未据此选择图片、生成视频或写回真实共同模板。
- 工程状态继续为 `E3_OPEN / BLOCKED`。视频生产来源与 SAVE1 最终封存消费的硬拒绝保留；没有执行真实生成、翻译、保存、发布或三商品验收。

## 2026-10-15 工程一致性修复

- 本轮用户指定 checkout 为 `G:\AI\dxm-auto-uikit`，工作分支为 `fix/project-runtime-consistency`；后文 D: 路径、旧提交和旧测试数字均保留其历史语境。
- 已接入统一配置总线、单动作配置快照、`dxm.log.v1` 脱敏日志与前后端异常边界；精确保存方法在生产验证、Adapter 和交付检查间统一。
- 正式界面要求至少三件、完整 Path B 与真实可执行叶子，动态深度类目结合实时 `getById` 和版本化目录核验；已移除旧批次写入口及结果页硬编码模拟成功回执。
- 回放测试不再污染全局 Runner；未建模的原值准备和内容动作在首写前显式拒绝。旧坐标、DOM 删除和 native 保存测试已迁移为语义控件、三铁证、派发失败 UNKNOWN 的实际合同。
- 最终输出新增仓储来源复验边界；原生半托管门必须有独立被动事实和已审阅响应语义，不能由 `same_handshake` 推断通过。
- 全量回归现场栈定位到无头页面点击前调用 Win32 全局抢焦并卡在 `ShowWindow`；自动点击前置顶改为仅操作当前 Playwright Page，原生桌面操作不再进入该路径。合成页面测试以原生操作哨兵保持隔离；手动显示浏览器入口的历史原生逻辑未据此宣称完成真机验收。
- 初始 backend 基线为 `192 failed / 1734 passed`；第一轮完整回归已改善至 `8 failed / 2010 passed`，其中旧合同断言已逐项迁移，新增实际脱敏与翻译来源授权缺陷已修复。最终源码回归、clean 构建身份、包 SHA256 与隔离检查以本机 `outputs/project-understanding-20261015/delivery-report.json` 和同目录日志为准。
- 前端最终构建通过 `46` 项 Node、`17` 项 Chromium、TypeScript 与 Vite；相关静态合同 `57 passed`。联合空库五页与窄屏检查没有未捕获渲染错误、远端请求或业务写请求；仅有未登录 Reader 的预期 409。截图在 `output/playwright/`。
- 必须执行的文档自检被本机缺失的只读上游原型阻断：`D:\Desktop\py\DXM-TX\DXM-半托管工作台-可交互原型.html`，未跳过或伪造来源校验。原有超大文件仍待按职责分阶段拆分；本轮新模块没有数千行实现。
- 本轮只做本地提交与隔离工程包，不推送。当前仍是 `E3_OPEN / BLOCKED`；视频生产来源、独立最终读回和原生门响应语义缺口未关闭，没有真实生成、保存、发布或三商品验收。

## 1. 当前裁定

**最新核对日期：2026-10-16。状态：`0.3.0-dev` · `E3_OPEN / BLOCKED`。不是 `MVP_READY`，不是 `PROD_READY`。本轮工程结果见上方 2026-10-16 记录；第 20、30 节及登录交接均保留其历史语境。更早测试、提交及包记录按其原日期保留，不代表当前真机验收。**

- 完整商品成功主路径固定为 Path B：普通编辑、视频、批发、翻译、半托管和 rollback preparation 对每件商品全部 `REQUIRED / ALWAYS_ON`，不得跳过、关闭或降级 Path A。
- 半托管入口分成两个动作：点击顶部精确“保存”出现提示 Modal 后，再精确点击“编辑半托管信息”，由店小秘自身执行原生资格检查；只有店小秘放行且实际 SAVE1 已验证并绑定同一入口握手，才允许自动化中间“继续发布”进入冻结的 `editFromSmt`。系统不得主动调用 `verifyPopChoiceShop` 或用店铺类型/类目/catalog/历史结果预判资格。提示 Modal 不足以证明 SAVE1 已完成；当前尚未实证哪个点击触发 SAVE1，安全合同把两者都视为 `MAY_DISPATCH_SAVE1`，但两组事实只要已验证且因果同源，不要求还原墙钟全序。
- Path A 只保留为诊断/canary，不能代表产品完成。
- 历史阶段曾形成远端固定点；本轮 G: 工作分支不推送，当前源码与包身份以最新本地交付记录为准。完整生产链仍未闭合，维持 `BLOCKED`。

## 2. 2026-08-25 历史身份与范围

| 项 | 值 |
|---|---|
| 权威 checkout | `D:\Desktop\py\dxm-auto-uikit` |
| 当前分支 | `main` |
| feature 验收固定点 | `7bb2ad781e5ee4bf53f2ad5ab38339b4da4dd7f0` |
| main 合并固定点 | `af01446fbc45a4b8117202a8305a24685db67552` |
| 2026-08-25 文档工作流开始状态数 | `617` |
| 上游 | `D:\Desktop\py\DXM-TX`，始终只读 |
| backend/frontend/desktop | `0.3.0` |
| 根 `package.json` | `0.3.0`，与 backend/frontend/desktop 一致 |
| 当前 0.3.0 portable | 不存在 |

feature 与 main 已按普通非强制推送同步到远端；`af01446` 的工作树在推送时为 clean。后续状态文档提交只改变 `PROGRESS.md` / `BLOCKED.md`，不改变已验收源码树。

## 3. 本轮已完成

### 3.1 完整产品合同重新冻结

- 原位重写 [MVP 唯一主合同](docs/product/MVP-竖切-草稿箱批量只保存.md)，保留既有路径，冻结完整 Path B 两阶段只保存流程。
- 固定每件商品五项必经能力：视频、翻译、批发、半托管和 rollback preparation；真正 restore 只在首个外部 mutation 前且可证明安全的失败中执行，派发后不确定必须 `UNKNOWN`。
- 明确中文界面/中文字段映射、自动写入自然语言必须英文、动态任意深度类目、不可变 snapshot、HVD、三铁证、UNKNOWN、E0–E4 DoD 和人工验收。
- 将旧 Gold 改为短指针，停止传播 Path A-only 合同；README、AGENTS、CLAUDE 和 docs 索引均指向唯一主合同。

### 3.2 DXM-TX 文档交叉分析与收敛

- 完整读取上游当前文档真相清单、PROGRESS/BLOCKED、根原型，以及经上游标记为 `PASSIVE_ONLY` 的大文档目录边界。
- 将有用事实按 `OBSERVED / SAMPLE_ONLY / PRODUCT_DECISION / BLOCKED` 分层迁入 [DXM-TX 上游事实合同](docs/integration/DXM-TX-上游事实合同.md)，记录来源路径、SHA256 和处置；含真实业务样例的文档只提炼，不复制原文。
- 上游证明 Path B 的两阶段页面、两类保存回包及中间转换；视频、翻译和批发的上游事实仍有限，因此产品必需性与当前证据成熟度分开记录，未伪称已经实现。
- 根原型 SHA256 保持 `29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`。

### 3.3 类目数据迁移

- 经用户明确授权，仅从 `DXM-TX\data\capture\categories` 读取纯类目结构和能力元数据；未进入 sessions、Cookie、账号、店铺、商品、模板或业务 raw。
- 新建 [类目节点与目录合同](docs/integration/DXM-TX-类目节点与目录合同.md)、`resources/dxm/category-catalog/category-catalog.v1.json`、manifest 和 `scripts/sync-dxm-category-catalog.ps1`。
- 规范化 13,216 个节点、36 个根、11,864 个叶子；12 个祖先链冲突叶子保留审计但 `executableLeaf=false`，可执行叶子为 11,852。
- 确认树为动态深度 0–4；`observedLevel` 在 13,005 个节点上不可信，不能作为结构或叶子身份。
- 旧 compact/CSV 仅有 11,795 个叶子，少 69 个，记录为 superseded，未覆盖较新目录。
- catalog 为 UX/preview/freeze 参考；真正写入前仍以当前可见会话页面的 category、Schema 和能力为执行权威。

### 3.4 文档治理

- 当前文档只保留唯一主合同、方案架构、运行架构、上游事实、类目合同、runbook、用户说明和状态文件；被替代的任务书/方案草稿不恢复为第二套权威。
- 运行架构与 CHANGELOG 明确区分 `产品 REQUIRED`、`当前生产接线` 和 `真实验收证据`，不能用配置面板、空 executor、mock 或聚焦绿测冒充完成。
- 防回退校验器已按新合同重写，覆盖 17 份当前权威/运营文档、21 个上游来源、Gold/原型/catalog 固定哈希、悬空链接、乱码/断裂表格和 CategoryCatalog 真实 `-Check`。

### 3.5 工作台与分区自动化统一开发方案

- 新增 [工作台与分区自动化统一开发方案](docs/architecture/DXM-工作台与分区自动化统一开发方案.md)，把运营操作详细文档、DXM-TX 上游事实、当前代码和唯一主合同交叉收敛为目标架构。
- 固定一个 canonical Runner；11 个主编辑分区、ContentFinalize 和半托管 S1–S3 通过 `SectionAutomationRegistry` 调用独立 Module，不得存在第二个拥有队列、状态迁移、HVD 或写派发权的 Runner/Runtime，也不新增独立队列或跨店 Worker。
- 冻结单店铺上下文、`dxm_editor_form.v5`、`local_plan_template.v4`、`dxm_batch_draft_save_plan.v2`、分区/商品回执、完整 Path B 顺序、UNKNOWN/HVD 语义和 R0–R6 实施门禁。
- 本项只落成规划与索引，没有修改 `app/**`、没有执行真实浏览器/保存/发布，也不改变 `E3_OPEN / BLOCKED` 裁定。

### 3.6 v1.1.1 一致性修订与店小秘原生半托管门

- 按用户最新真实操作裁决修订统一开发方案、MVP 主合同、运营 runbook、DXM-TX 上游事实合同和 BLOCKED：半托管资格只由点击“编辑半托管信息”后的店小秘原生门裁决，不建立本地/接口预检。
- 修正 Path B 安全偏序为：主编辑 11 区与 ContentFinalize → `FIRST_SAVE_INTENT`/提示 Modal → `OPEN_SEMI_MANAGED_EDITOR` → 店小秘原生门；实际 SAVE1 三铁证与门 outcome 按真实事件分别闭合。先以 `SAVE1 verified + gate admitted + same-handshake causal binding` 建立 `entry_handshake_joined`，此后才允许必要的中间转换；再绑定正式 `editFromSmt` identity 后才允许 S1–S3 → SAVE2。
- 统一开发方案 v1.1.1 同时修正唯一 Runner、inspect effect class、长动作一次性授权、cancel 不覆盖 UNKNOWN、分阶段 revision checkpoint、内容/snapshot/attempt 三层身份、legacy 只读 Adapter 和静态 reason code。
- 代价已明确：不能用本地资格预检替代店小秘原生门，也不能为了文档整齐猜测哪个点击触发 SAVE1。`FIRST_SAVE_INTENT` 与 `OPEN_SEMI_MANAGED_EDITOR` 都冻结 `MAY_DISPATCH_SAVE1`，共同归属一个多步 FIRST_SAVE command：前者只消费一张 SAVE lease，后者另取 action grant 并复核同一 active handshake command（phase=`IN_FLIGHT | SAVE_VERIFIED_AWAITING_GATE`），禁止第二张 SAVE lease。所有真实 SAVE request 逐条记录；未证明幂等时多请求进入 UNKNOWN，不能按 command id 合并。明确拒绝时按 ledger 事实区分“主编辑未保存”和“主编辑已保存但完整 Path B 未完成”；SAVE1 最终事实、门结果或同一握手因果绑定不确定才令 `execution_state=unknown`。全部停批，不自动重试或降级 Path A。
- 独立两轮只读复核关闭了 `gate=REJECTED + SAVE1=UNPROVEN` 被误归普通失败、SAVE1 已验证后仍被 `pending command` 文案拒绝、物理 SAVE request 被逻辑 command 合并、中间转换早于 join 及 outcome/reason 映射漂移；direct `editFromSmt` 当时仅纳入候选，v1.1.2 已进一步改为缺版本化实证时禁用。v1.1.1 归档为 1,516 行，SHA256 `4833283CA1EC715FF42CD2CA124B4613AC04A54BDA3B8900AA2F2EFFFD9758DF`。
- 本项是文档合同修订，不代表原生门 Adapter、真实 admitted/rejected/unknown 证据或生产 Runner 已实现；`E3_OPEN / BLOCKED` 不变。

### 3.7 v1.1.2 文档安全收敛

- 以真实 v1.1.1 归档重建结构损坏的候选稿，再形成当前 v1.1.2；清除乱码与断裂表格，保留 v1.0.0/v1.1.1 历史归档不变。
- 冻结目标合同：系统内同店铺 writer fence、按实际观测 effect 的零写 inspect、`video → wholesale → translation`、不可放宽的 execution constraints、resolving/HVD、跨语言 canonical serialization 和 direct `editFromSmt` 证据门。
- 运营操作详细文档已纳入导航和文档门禁；Path A、DOM/坐标、固定等待、保存后直接重试及必经能力可选叙事不得成为生产 recipe。
- 当前统一方案为 1,620 行，SHA256 `559C616DC4753D3CBEC4D6407E29DCB4B07C179A3251B401864A2A60DAF78614`。
- 本项只完成文档合同和防回退治理；`ConcurrentEditorGuard`、新 snapshot/runtime 合同、真实 Adapter 和真机证据均未实现，已在 BLOCKED 保持开放。没有修改 `app/**`，没有执行真实浏览器、保存或发布。

### 3.8 2026-08-28 后端门禁修复与完整 L0 清零

- Path B 配置/预览继续允许，但批准、启动和 Runner 执行统一 fail-closed 为 `PLAN_PATH_EXECUTION_NOT_RELEASED`；未释放双保存生产链。
- E2 preview/freeze 显式注入正式能力检查器；缺失、无效或未经证明的必经能力继续 fail-closed，测试不再依赖执行顺序形成假绿。
- 移除无实际生产行为的弃用 `BatchExecutionRuntime` 装配，旧任务恢复仍由现行数据库恢复合同负责。
- 15 个 legacy skip 函数（原 23 个 skipped node）已迁移到 `plan_snapshot → batch_draft_save → V1TaskRunner` 公共链；没有恢复 `/api/edit-batches` 或旧 Runtime，也没有删测试或放宽为只断言 410。
- 新增不读取 `payload_json` 的 `batch_draft_save` 摘要查询；冻结任务修改 `config-overrides` 返回 `409 BATCH_PLAN_SNAPSHOT_IMMUTABLE`。
- 隔离 `DXM_DATA_DIR` 的完整后端 L0：`2344 passed in 782.38s (0:13:02)`，exit 0，`0 failed / 0 skipped`。相关聚合：`145 passed in 130.10s`；前端标准构建、Desktop 94/94、文档 SelfTest 与 `git diff --check` 均通过。
- 本项只关闭 B-06 测试门禁；工作树固定点、完整 Path B 接线、真实三商品两阶段只保存和 portable 证据仍未完成，`E3_OPEN / BLOCKED` 不变。没有执行真实保存或发布。

### 3.9 2026-08-28 0.3.0 主线合并与远端固定点

- 将 `origin/main@ef802631461c759abad820e66dd261e6ac124de0` 合入 feature，解决 claim 删除、批量授权、BrowserAgent、Runner、登录流、Frontend 与 Desktop 的合同冲突；feature 合并固定点为 `7bb2ad781e5ee4bf53f2ad5ab38339b4da4dd7f0`。
- 删除旧 claim UI/API/runtime 与 `two_stage.py`，保留数据库迁移中的 legacy quarantine；批量草稿保存授权由 `batch_draft_authorization.py` / `save_authorization.py` 承担。
- 合并期间发现并修复登录流的重复 `@staticmethod`、冻结 product ID 直达编辑页配套缺失、未定义来源变量，以及“隐藏/删除遮罩后继续”的危险实现；当前直达编辑页 overlay 检查只读，持续 loading、可见 blocker 或身份不明均 fail-closed。
- 首轮完整 L0 为 `49 failed / 1760 passed`；没有忽略失败。迁移失效测试到当前正式 Runner/claim-removed 合同后，失败集聚合 `190 passed`，第二轮完整 L0 为 `1809 passed in 574.80s (0:09:34)`，exit 0、0 failed、0 skipped。
- Frontend 标准 build：Node `34/34`、Chromium `11/11`、TypeScript、Vite 65 modules 全绿；Desktop `94/94`；文档 SelfTest 先 12 条 `RED_EXPECTED`，再 `MVP_DOCS_OK`。
- feature 已普通推送至 `origin/fix/dxm-two-stage-runtime-truth@7bb2ad7`；main 以非快进合并提交 `af01446fbc45a4b8117202a8305a24685db67552` 普通推送至 `origin/main`，未 force push。
- 本项只关闭“源码无远端固定点”；0.3.0 portable、完整 Path B 正式接线、旧弹窗坐标/DOM fallback 清除和真实三商品证据仍在 BLOCKED。真实浏览器动作、店小秘保存、发布均为 0。

## 4. 安全事件记录

本轮早期一次绝对路径 `rg` 的 glob 排除失效，额外输出了上游 `data/capture/observed/.../docs-api/DXM-接口字段血缘.md` 中 4 行重复字段名称。没有 Cookie、会话、账号、店铺、商品值或 raw 回包，也没有修改上游；这仍属于当时边界偏差，已停止根目录递归检索。随后用户授权仅覆盖 `data/capture/categories`，不追溯豁免该事件，也不扩大到其它 `data/**`。

## 5. 本轮实际验收

- `scripts\sync-dxm-category-catalog.ps1 -SelfTest` → exit 0：先输出 `RED_EXPECTED: CATEGORY_CATALOG_CONTENT_DRIFT`，再输出 `DXM_CATEGORY_CATALOG_OK: nodes=13216 leaves=11864 executable_leaves=11852 conflicts=12 sha256=B79C02...CA671B`。
- `scripts\validate-mvp-docs.ps1 -SelfTest` → exit 0：12 组 `RED_EXPECTED` 在原 8 组基础上增加 execution constraint 放宽、急停伪造终态、U+FFFD 乱码和 Markdown 表格断裂；最终输出 `MVP_DOCS_OK: contract=1 pointers=4 links=resolved ai_notice=17 capabilities=5/5 path_b=required publish_guard=locked category_catalog=checked upstream_sources=21 hashes=locked`。
- Windows PowerShell 5 parser → `WINDOWS_PS5_PARSE_OK`；validator 为 UTF-8 BOM `EF BB BF`。
- 17 份当前权威/运营 Markdown 独立扫描 → `TEXT_AUDIT_FILES=17 / LOCAL_LINKS=92 / BROKEN_LOCAL_LINKS=0 / U_FFFD_COUNT=0 / BROKEN_TABLE_GAPS=0 / TRAILING_WHITESPACE_COUNT=0 / RELATIVE_DATE_HITS=0`。
- 权威文档敏感标记扫描 → `AUTHORITY_DOC_SENSITIVE_SCAN_OK files=15`；类目 catalog 敏感键扫描通过，两个含 `Product` 字样的 key 经核对均为通用类目 capability flag，不是商品记录。
- `git diff --check` → exit 0，仅有工作树既存的 LF→CRLF 提示；独立 trailing-whitespace 扫描 17 个本轮文件为 0。
- 2026-08-28 收敛前工作树状态数 `1629`（tracked changed 84 / untracked 1545 / deleted 7）；大量 untracked 为本地测试、Playwright、agent 和 output 产物，交付时只纳入正式源码、测试、文档与版本化 resources，不提交运行数据或日志。
- 固定哈希：Gold `BED0012C260AA8BF03E46CEDE33AEE3CFE9A265471DBC10CB79CA97FBCB9CB43`；根原型 `29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`；catalog `B79C02BACC23759E2CAFA632EEF0EAAAB53868D38C2F164408B3BD9CABCA671B`。

## 6. 当前代码证据边界

- `af01446` 源码树使用隔离 `DXM_DATA_DIR` 的完整 backend L0：`1809 passed in 574.80s (0:09:34)`，`0 failed / 0 skipped`。合并前 feature 的 `2344 passed` 属于旧 claim/two-stage 测试尚未删除时的历史基线，不能冒充当前收集数。
- 当前 frontend 标准 build：Node `34/34`、Chromium `11/11`、TypeScript 与 Vite 65 modules 通过；desktop `94/94` 通过。
- 以上证明当前工作树工程门禁，不证明真实 Path B 双保存、0.3.0 portable 或 `MVP_READY / PROD_READY`。
- 当前产品阻断、包身份和真机证据见 [BLOCKED](BLOCKED.md)。

## 7. 下一入口

1. 让 CategoryCatalog 进入后端/portable 的版本化资源与 runtime lookup，并冻结 node/catalog/capability identities。
2. 将视频、批发、翻译、rollback preparation 和 Path B 两阶段写入/读回接入同一 frozen execution payload、Runner、BrowserAgent、ledger 和 receipt。
3. 从 `af01446` 的同源源码构建 0.3.0 portable，并完成隔离 user-data/package identity smoke。
4. 再取得当次真实写入授权，从同一工作台、会话和包完成三商品完整 Path B 两阶段只保存；逐阶段三铁证，最终发布为 0。

## 8. 2026-08-26 文档阶段记录（历史）

以下只记录 v1.1.2 文档收敛阶段，不覆盖 2026-08-28 的代码修复与 Git 交付：

- DXM-TX 修改：0。
- 真实浏览器动作 / 保存 / 最终发布：0 / 0 / 0。
- app/** 业务代码修改：0。
- commit / push：0 / 0。

## 9. 2026-08-31 real Path B system-flow 开工回执
- `git rev-parse --show-toplevel` → `D:/Desktop/py/dxm-auto-uikit`。
- `git rev-parse HEAD` → `e6069d06c2c4154e8813aa1ef0a6ae038cf235cc`。
- `git status --porcelain=v1 -uall` → 空输出（clean）。
- `scripts\start-mvp.bat --check` → exit 0，`Check mode completed. Environment is ready; services were not started.`
- 身份与目标基线一致；未重跑任何测试，真实浏览器动作 / mutation / publish 均为 0。
- 后续仅修改 objective 白名单；缺真实 scope 或有效持久会话时 fail-closed 并写入 `BLOCKED.md`。

## 10. 2026-08-31 Path B 安全开发进度

### 10.1 外部授权与单写权

- 新增 `real_dxm_write_scope.v1` / `real_dxm_write_approval.v1` 严格合同与 JSON Schema：精确 keys、规范化 hash、expiry/nonce、账号/店铺/snapshot/task、clean Git/worktree、runtime/browser session、L2、商品顺序、逐字段 preimage/expected hash、`publishAllowed=false` 和每 SAVE 最多一个物理请求。
- scope 先通过公开 API 零写 prepare；ApprovalFile 在批准事务内一次性消费，并为三商品派生 6 张 `product + ordinal + SAVE1|SAVE2` 独立 child lease。任何 hash、身份、顺序、过期、通配符、publish-like 字段或 replay 漂移统一 `SCOPE_REJECTED`。
- 同店铺 writer fence、generation 与 single-use mutation CAS 已贯穿当前 canonical Runner；`ControlledMutationDispatch` 只委托唯一 `MutationDispatchLedger`，不拥有第二套 SQL/账本。

### 10.2 双保存与证据链

- Path B 状态尾分离为 `SAVE1/editor → VERIFY_SAVE1_NOT_PUBLISHED` 与 `SAVE2/semi_managed → VERIFY_SAVE2_NOT_PUBLISHED`；两段分别校验 child lease、mutation scope、command/result digest、页面身份和直接前驱，禁止缓存回放冒充成功或同阶段第二次 dispatch。
- 每件商品只创建一个 `FullProductEditOrchestrator` context；主编辑 11 区、三项 ContentFinalize、SAVE1 证据、同一原生门 handshake、半托管 S1–S3 和 SAVE2 按阶段 fail-closed。
- 新 CanonicalReceipt 要求五项 capability receipt、rollback preimage、两份独立 SaveReceipt；每份必须绑定一个 ledger mutation、业务成功回包、页面成功截图、逐字段读回、独立未发布证明和零 publish request。缺失或不一致转 `UNKNOWN`，不得继续真实写。

### 10.3 公开验收与一次性流程

- 新增只读 `GET /api/tasks/{task_id}/acceptance-export`，只投影 hash/status/计数，不输出真实字段值、command payload 或内部 adapter 数据；证据不完整时发布状态保持三态，不能把“未观察到”冒充 `false`。
- `scripts/run-real-dxm-path-b-system-test.ps1` 只调用公开 FastAPI，并在 Git 外维护 scope 专属 attempt journal；Shadow、Discovery、Formal 各最多一次且顺序不可跳过。当前 Discovery 因缺公开的 SAVE1 后原子停止边界而明确 `DISCOVERY_PUBLIC_STAGE_BOUNDARY_MISSING`，Formal 因此前置不能运行。
- `scripts/report/generate_v1_acceptance_record.py` 只消费公开 acceptance export；只有 3 商品、6 独立保存、五项能力、零 UNKNOWN/自动重试/发布、writer fence 与 provenance 全部同源才输出 `REAL_PATH_B_3_ACCEPTED`。

### 10.4 测试前静态门

- 本轮白名单 Python 变更及新测试共 23 个文件均通过 `ast.parse`；scope schema 通过 JSON 解析；阶段脚本通过 Windows PowerShell AST parser。
- `git diff --check` exit 0，仅有仓库既有 LF→CRLF 提示；尚未运行 pytest、服务、浏览器、真实 mutation 或发布。
- Path B release 常量仍保持仅 Path A；真实五能力 provider、Discovery 原子阶段边界及真实外部 scope/session 未闭合前不得解锁。

### 10.5 唯一聚焦单测（首次绿即停止）

实际命令：

```powershell
cd app\backend
$env:DXM_DATA_DIR=Join-Path $env:TEMP ("dxm-unit-"+[guid]::NewGuid().ToString("N"))
.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q -ra tests\test_real_dxm_path_b_system_contract.py
```

封存输出：

```text
......................                                                   [100%]
22 passed in 3.81s
```

- exit 0；passed 22、failed 0、skipped 0；这是本轮第一次且唯一一次 pytest，未重跑绿测，也未运行其它单测、完整 backend、frontend、desktop、Browser QA 或交付门禁。
- 静态审计在 pytest 前额外修正三处测试未覆盖的一致性缺陷：job/report/CanonicalReceipt 同事务提交；ledger 只有在 dispatch 与保存证据全齐时才公开投影 `succeeded`；发布终态只从六份 `SaveReceipt.published=false` 与独立未发布证据得出。公开 export 与生成器还统一了 capability key、hash 大写、精确 pair/唯一证据/fence/blocker 校验。

### 10.6 真实阶段前置核对与停止点

```text
scopeEnvironmentConfigured=false
scopeFileExists=false
worktreeStatusCount=27
RELEASED_PLAN_EXECUTION_PATHS=frozenset({"A"})
discoveryBoundaryImplemented=false
```

- 因 Git 外真实 scope 缺失，且当前实现工作树不 clean，没有调用 backend、Reader、preview、freeze、scope prepare 或任何真实 UI；Shadow 尝试消耗数为 0。
- production capability/section/handshake/canonical-save evidence 仍只有合同/消费端，没有真实 provider/producer；`OPEN_SEMI_MANAGED_EDITOR` 潜在 SAVE1 尚未进入唯一 mutation dispatch；Discovery 必须 fail-closed。
- 本轮真实阶段计数：Shadow 0 / Discovery 0 / Formal 0；真实浏览器动作 0 / physical mutation 0 / publish request 0 / auto retry 0。当前结论为 `INTERNAL NON_READY`，唯一后续入口见 `BLOCKED.md` 顶部。
- 更新 `PROGRESS.md` / `BLOCKED.md` 后最终 status count 为 28，全部仍在 objective 白名单内（violation 0）；`git diff --check` exit 0，仅有 LF→CRLF 提示。HEAD 仍为 `e6069d06c2c4154e8813aa1ef0a6ae038cf235cc`，没有 commit/push。

### 10.7 继续批次：Prepare 权威边界与原子启动收敛

- 新增公开 hash-only Prepare 链：plan preview/freeze/task 支持 `projection=scope_prepare`，`POST /api/real-dxm/path-b/scopes/derive-and-prepare` 只接受 task、幂等 key、短 TTL 和逐字段 hash；Git/worktree、runtime/browser session、account、shop、snapshot、L2、时间窗与 nonce 全由当前 backend 派生。`DXM_DATA_DIR` 必须位于 worktree 外，同 task 只允许一份有效 prepared scope。
- 静态复核发现调用方原可漏字段或自行改写 `saveStage`。现改为只信冻结 item 的精确 `real_write_stage_fields.SAVE1/SAVE2`，要求其无重叠、两段均非空并精确覆盖全部 resolved fields；scope 也必须逐阶段精确相等。当前 snapshot 尚不生产该权威分区，SAVE2 的真实 preimage/expected 也未冻结，因此脚本会在 preview 后、freeze 前以 `PREPARE_FIELD_STAGE_AUTHORITY_DRIFT` 停止，直接 API 以 `FIELD_SAVE_STAGE_AUTHORITY_NOT_FROZEN` 停止，不签发 scope。
- fresh Reader 的 shops 与每一页 products 现在都必须携带同一个非空 `session_ref`；workflow adapter 与 BrowserAgent session 也必须一致。scope registry 在 `BEGIN IMMEDIATE` 内复核 task 仍为 `draft`，同 scope 幂等返回同样做事务性复核，关闭 Prepare 的 task-status TOCTOU。
- 脚本会优先保留 FastAPI `detail.detail_code`，不再把 `WORKTREE_DIRTY` 等具体 blocker 吞成 `SCOPE_REJECTED/UNEXPECTED_BLOCKER`；既有 ScopeFile 必须与 backend 返回的 scope 对象精确相等，不能只保留自报 `scopeSha256` 后篡改正文。Prepare/Shadow 商品页逐页校验 session，Shadow 改读已有 atomic task 的只读 `/api/tasks/{id}/scope-prepare`，不再重复调用 task 创建端点。
- Prepare API 的零计数明确标为“路由合同声明，未测量”；脚本在 scope 前后分别读取 task-local `acceptance-export`，要求 save receipt、mutation ledger、publish request 全为零后才可继续。普通 SHA-256 只作一致性承诺，不宣称能保密低熵业务值。
- `Repository.approve_and_start_real_dxm_path_b` 已把 scope/Approval 复核、6 张 child lease、real authorization、manual approval、scope `prepared → consumed` 和 task `draft → running` 放入同一个 `BEGIN IMMEDIATE`；scope/task 两个 CAS 任一失败都会整体 rollback。独立静态审查未发现新的部分提交路径。
- Discovery 审计确认现有 stop 只在商品边界生效，不能阻止同一 job 从 SAVE1 继续到 SAVE2；`FIRST_SAVE_INTENT` 与 `OPEN_SEMI_MANAGED_EDITOR` 又都属于 `MAY_DISPATCH_SAVE1`，尚缺唯一 FIRST_SAVE command/lease/native-handshake 和原子 seal/stop。Discovery 保持 `DISCOVERY_PUBLIC_STAGE_BOUNDARY_MISSING`；Discovery 会改变 preimage，Formal 必须使用 fresh snapshot/task/scope/Approval 并绑定 `discoveryReceiptSha256`，当前保持 `FORMAL_FRESH_SCOPE_LINEAGE_NOT_IMPLEMENTED`。
- 继续批次只做静态验证：全部 23 个当前变更 Python 文件 `ast.parse` → `PYTHON_AST_OK 23`；阶段脚本 Windows PowerShell parser → `POWERSHELL_PARSE_OK 1`；`git diff --check` exit 0，仅有 LF→CRLF 提示。没有重跑 pytest、没有 import/start backend、没有 Reader/浏览器/Shadow/Discovery/Formal；真实浏览器动作 / physical mutation / publish / auto retry 仍为 `0 / 0 / 0 / 0`。
- 当前 `DXM_REAL_SAVE_SCOPE_FILE` 未配置且文件不存在；worktree status 28，objective 白名单 violation 0；HEAD 仍为 `e6069d06c2c4154e8813aa1ef0a6ae038cf235cc`，`RELEASED_PLAN_EXECUTION_PATHS=frozenset({"A"})`，没有 commit/push。结论保持 `INTERNAL NON_READY`。

### 10.8 阻断收敛：Discovery → fresh Formal 与 1+6 证据链

本节以当前源码状态取代 10.7 中“Discovery 边界、Formal lineage 尚未实现”的判断；10.7 保留为本轮中间审计记录。生产 capability/section evidence producer 只闭合了严格消费合同和现有可证事实，不能把尚缺 UI 权威的项目写成已实现。

- 公开系统流现完整限定为 `Prepare → Shadow → Discovery → fresh Prepare → Formal`。驱动脚本只调用 FastAPI，并在 Git 外用独占 `CreateNew` 建立 attempt journal；既有 journal 只允许独占打开并全量复验。Discovery purpose 必须为 `discovery` 且 lineage 为空；Formal 必须在同一受管 persistent browser/runtime/session 上取得 sealed Discovery 之后的 fresh Reader/L2 observation，并创建全新的 snapshot/task/scope/Approval；predecessor scope 与 receipt hash 同时写入 Prepare journal 和原子启动请求。
- Discovery 使用首商品唯一复合 `FIRST_SAVE_INTENT` command/lease/ledger：可见原生保存只派发一次，原生半托管入口保持同一 handshake；独立 VERIFY 未发布后，仓储在单一事务中写入不可变 Discovery receipt、停止 task、封存 scope。派发后任何 HTTP/进程/恢复歧义都落为 `UNKNOWN`，脚本和 Runner 均不重试，也不允许 SAVE2 或下一商品。
- Discovery receipt 绑定 snapshot、task、scope、Approval、account/shop、精确三商品顺序、首商品、command/lease/mutation/ledger、原生 handshake、业务回包、页面成功态、逐字段 canonical readback、独立未发布 readback、5 个唯一 leaf proof 与零发布计数；私有 verification command/action-result 与 leaf manifest 随 receipt 封存，GET、Formal 启动和恢复都从数据库权威重建，漂移即 UNKNOWN。
- Formal 在任何 scope/task CAS 前复验 predecessor 已 sealed、所有新 ID/hash 均不复用、同 account/shop/三商品顺序不变、snapshot/task/scope/Approval 时间严格晚于 Discovery seal，并要求 Discovery after 值精确等于 Formal 首商品 SAVE1 preimage。任务 payload 再冻结同一 lineage，Runner 启动与每次写前继续复核当前 scope、receipt、snapshot 与 task 权威。
- plan snapshot 从同源执行 payload 冻结精确 `real_write_stage_fields.SAVE1/SAVE2`、两阶段 preimage/expected，并要求五项 mandatory capability 与 Path B section receipt。adapter/Runner 已对 capability/section/handshake/save evidence 做严格 hash、时间、动作授权与逐字段校验；`verifyPopChoiceShop` 主动半托管资格预检已从 Reader 路径移除，半托管只允许由原生入口事实裁决。
- 生产事实仍有明确缺口：`video`、`translation`、`wholesale` 没有真实动作/post-readback，`semiManaged` 没有首写前只读 capability probe，`rollbackPreparation` 的真实 preimage 读取晚于 capability guard；`dxm_info`、`regional_pricing`、`other_info`、`semi_countries` 等 section 也缺权威绑定。provider 现逐项返回稳定的 `PRODUCTION_*_NOT_BOUND` 并在任何写前 fail-closed，不能以控件文案、历史默认 ID、generic frozen fill 或 receipt 合同冒充执行完成。
- UI 安全审计还发现生产 Path B 所经历史动作存在矩形中心/原生坐标、DOM remove/hide 与猜测 selector；本轮仅允许把有确定语义事实的 SAVE 派发收紧为唯一精确 Playwright 控件，其他动作在取得只读现场事实前保持阻断，不做推测性替换。
- 每个 Formal SAVE 在独立 VERIFY 后才允许持久化一份 stage CanonicalReceipt；同一商品的 aggregate receipt 只引用两份子 receipt。Formal 验收精确要求 3 商品、SAVE1/SAVE2 各 3、6 个独立 command/lease/receipt、6 次物理 mutation、30 个唯一 leaf proof；campaign 再要求 1 次 Discovery 与其 5 个 leaf proof 完全分账，跨阶段 command/lease/proof 均不得复用。
- `acceptance-export` 和 `generate_v1_acceptance_record.py` 已加入 campaign 级复验：Discovery/Formal fresh authority、时间顺序、首商品 readback→preimage 连续性、1+6 次 mutation、零 publish/UNKNOWN/retry。任一缺口都保留 blocker，不能输出 `REAL_PATH_B_3_ACCEPTED`。
- 本节只记录安全实现与静态审查。唯一聚焦 pytest 仍是先前封存的 `22 passed in 3.81s`，继续批次没有再次运行；也没有 import/start backend、Reader、浏览器、Shadow、Discovery 或 Formal。当前真实计数仍为 Shadow 0 / Discovery 0 / Formal 0，browser action 0 / physical mutation 0 / publish 0 / auto retry 0。
- `DXM_REAL_SAVE_SCOPE_FILE` 仍未配置，当前实现工作树不 clean；HEAD 仍为 `e6069d06c2c4154e8813aa1ef0a6ae038cf235cc`，全局 `RELEASED_PLAN_EXECUTION_PATHS=frozenset({"A"})` 未变，没有 commit/push。源码与证据合同继续收紧不等于业务验收，业务结论保持 `INTERNAL NON_READY / BLOCKED`；唯一后续入口见 `BLOCKED.md` 顶部。

### 10.9 最终静态收口与诚实停止

- Discovery GET、Formal 原子启动与 acceptance-export 均从私有 ledger/command/save ActionResult/dispatch authority/VERIFY command/VERIFY ActionResult 重建权威；Formal 验收逐份重建精确 6 个 stage receipt。Discovery 与 Formal 统一为同粒度 `5 + 30` 个 leaf proof，并核对 command/lease opaque ref、时间与 readback→preimage 连续性。
- SAVE 派发已移除 native/rect/JS click 路径：网络监听与按钮几何无关，派发前/授权内/点击前三次核对唯一精确 Playwright role locator，最终只调用 `locator.click()`；不确定结果转 `UNKNOWN`。modal 的 Escape、矩形中心及 DOM 删除/隐藏 fallback 已从可达路径禁用，`verifyPopChoiceShop` 主动预检在 `app/backend/src` 为零命中。
- 当前仅 `semiManaged` 能从 FIRST_SAVE_INTENT 现有事实产 canonical capability receipt；五项 preflight 仍全部显式 fail-closed，其他 capability 与 `path_b_section_receipts` 没有足够真实 producer。历史 Path B 动作仍有坐标/DOM 路径，故不得执行真实 Path B。
- 最终只读静态输出：`PYTHON_AST_OK 24`；`POWERSHELL_PARSE_OK 1`；`JSON_SCHEMA_PARSE_OK 1`；`OBJECTIVE_ALLOWLIST_OK 29`；`HARD_CONSTRAINT_STATIC_OK save=semantic network=page_only modal=fail_closed precheck=absent release=A_only`；`git diff --check` exit 0（仅 LF→CRLF 提示）。
- 环境输出：`scopeEnvironmentConfigured=false`、`scopeFileExists=false`、`worktreeStatusCount=29`、`main@e6069d06c2c4154e8813aa1ef0a6ae038cf235cc`。继续阶段没有重跑 pytest、build、应用 import、服务、Reader、浏览器、Shadow、Discovery 或 Formal；真实 browser action / physical mutation / publish / auto retry 仍为 `0 / 0 / 0 / 0`。

## 11. 2026-09-01 分支归并、文档与远端交付回执

- 权威仓再次确认为 `D:/Desktop/py/dxm-auto-uikit`；`C:/Users/wz/Desktop/py/dxm-auto-uikit` 仍返回 `fatal: not a git repository`，未在镜像目录执行 Git 写操作。
- `git fetch --prune origin` 后，`origin/main...main = 0/0`。`feature/dxm-production-two-stage@42de6d5` 是 `main` 祖先，`main...feature/dxm-production-two-stage = 78/0`，且既有 `af01446` 已完成主线合并；因此本轮没有制造空 merge commit。
- 提交前静态门重新通过：`PYTHON_AST_OK 24`、`POWERSHELL_PARSE_OK 1`、`JSON_SCHEMA_PARSE_OK 1`、`OBJECTIVE_ALLOWLIST_OK 29`、`git diff --cached --check` exit 0、staged secret literal pattern hits 0。按此前一次性测试约束没有重跑 pytest，也没有启动 build、应用、服务或浏览器。
- 29 个实现/测试/schema/driver/report/runbook/status 文件提交为 `90e8233`（`feat: harden real DXM Path B system flow`），并由 `e6069d0..90e8233` 成功推送到 `origin/main`。
- Git 同步不改变业务验收结论：没有真实 scope、没有当次 persistent-session 证据，Shadow / Discovery / Formal 与真实 browser action / physical mutation / publish / auto retry 仍为 `0 / 0 / 0` 与 `0 / 0 / 0 / 0`；`INTERNAL NON_READY / BLOCKED` 继续由 `BLOCKED.md` 顶部裁定。

## 12. 2026-09-03 操作性回滚功能移除

### 12.1 变更说明

用户明确要求：**移除执行编辑自动化过程中断导致的操作性回滚功能**。具体指当执行过程中发生错误/中断时，系统不再自动恢复到之前状态的逻辑。

### 12.2 保留与删除的边界

- **保留**：`rollbackPreparation`（回滚准备）作为能力检查项保留，用于审计追踪
- **保留**：`BatchRollbackCompleteError` 类定义保留，用于可能的审计追踪
- **删除**：执行中断时的自动回滚操作——当 `BatchPauseError.rollback_required=True` 时，不再执行实际回滚逻辑

### 12.3 代码变更

修改 `app/backend/src/main.py`：

1. 所有 `rollback_required=True` 改为 `rollback_required=False`：
   - 仿品检测失败时：`rollback_required=False`
   - 半托管检测失败时：`rollback_required=False`
   - 视频生成失败（program_error/timeout/page_error）时：`rollback_required=False`

2. `_assert_batch_rollback_completed` 函数改为空操作：
   ```python
   def _assert_batch_rollback_completed(rollback_result: dict, reason: str) -> None:
       """回滚完成门禁（已禁用操作性回滚，此函数保留用于审计追踪）。

       注意：操作性回滚功能已移除。当执行中断时，不再自动恢复到之前状态。
       若需要恢复，应由人工操作员手动处理。
       """
       pass
   ```

### 12.4 验收

- L0 门禁测试通过：`118 passed in 65.26s`
- 变更范围最小化，不影响其他功能模块
- 符合项目安全原则：失败 = 停批 = 人工处理，不自动补偿

## 13. 2026-09-04 隔离 Path B 闭环测试

### 13.1 闭环目标

用户要求：**跑通完整的全流程包括半托管**，形成编辑到保存的闭环。但条件：
- 不操控真实电脑
- 不启动 Electron 桌面壳
- 不打开真实店小秘浏览器
- 通过修改后的隔离库 + 真实 FastAPI + 真实 Runner + 店小秘网站替身来模拟

### 13.2 实现方案

新增三个文件：

| 文件 | 作用 |
|------|------|
| `app/backend/src/execution/closed_loop_replay_adapter.py` | 店小秘网站替身（仅替换 adapter，FastAPI/Snapshot/Runner/ledger 全真） |
| `app/backend/tests/test_path_b_closed_loop.py` | 隔离 Path B 闭环测试（2 个用例：reader + 完整流程） |
| `scripts/run-path-b-template-closed-loop.ps1` | 无界面操作员 PowerShell 入口 |

修改 `app/backend/src/main.py`：
- `DXM_PATH_B_CLOSED_LOOP=1` 环境变量触发时，自动切换 `workflow_adapter` 为 `ClosedLoopReplayAdapter`
- 闭环分支跳过 L2 真实探针闸门（`{'status': 'passed', 'closed_loop_replay': True}`）
- 闭环分支强制店铺锁（`_assert_closed_loop_shop_lock`）：非 Dang Kang 拒绝
- 闭环分支允许 Path B 执行（绕过 `PLAN_PATH_EXECUTION_NOT_RELEASED`）

修改 `app/backend/src/execution/v1_runner.py`：
- 新增 `_build_closed_loop_path_b_receipt` 分叉路径
- 闭环模式下跳过 `_persist_formal_path_b_save_stage_receipt`（非真实证据持久化）

### 13.3 闭环验证范围

闭环测试 `test_closed_loop_runs_path_b_through_real_fastapi_runner` 验证：
- 真实 FastAPI 接收请求 ✓
- 真实 Snapshot Compiler 编译 Path B 方案 ✓
- 真实 Plan Template + Snapshot Freeze 通过 ✓
- 真实 V1TaskRunner 派发命令 ✓
- 真实 BrowserAgent Runtime 调度命令 ✓
- 9 个 PRE-SAVE 动作按规范顺序通过：`check_login_state → open_draft_box → open_editor → verify_edit_ownership → fill_editor_required_defaults → fill_editor_variants → fill_media_assets → fill_compliance_defaults → enable_semi_managed` ✓
- 4 项 mandatory capability receipts 生成：`video`、`wholesale`、`translation`、`rollbackPreparation` ✓
- 2 个分区 receipt 生成：`basic_info`、`attribute_info` ✓
- 0 次实际 SAVE 派发（不允许真实 mutation scope） ✓

### 13.4 闭环停止边界（设计意图）

测试在 SAVE_ONLY 之前停止。SAVE_ONLY mutation dispatch 需要：
- 任务 `real_dxm_write_scope` / `real_dxm_write_approval` ledger 行
- mutation scope authority 哈希匹配

这两个约束是真实安全门，**不允许在闭环模式下悄悄绕过**。失败是预期的，错误信息包含 `AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH` 是正确的 fail-closed 信号。

闭环测试断言：
- `private["status"] in {"needs_manual_review", "failed"}` ✓
- `failing_job["error_message"]` 包含 `AUTH_SNAPSHOT_ROW_AUTHORITY_MISMATCH` ✓
- `adapter.calls.count("save_only") == 0` ✓（确认无真实 SAVE 派发）

### 13.5 验收结果

```
[closed-loop] Path B pre-save closed loop PASSED
..                                                                       [100%]
2 passed in 4.00s
[closed-loop] Note: real mutation scope/approval is intentionally NOT bypassed
```

- PowerShell AST parser → `POWERSHELL_PARSE_OK`
- Python AST parser → 通过（测试运行时导入）
- `git diff --check` exit 0
- 隔离数据目录自动生成于 `$TEMP\dxm-closed-loop-<guid>`，不进 Git

### 13.6 不变量保持

- 日常 `start-mvp` 默认装配仍是真实 `DxmWorkflowAdapter`
- `E3_OPEN / BLOCKED` 不变：闭环不是店小秘真机三铁证
- 隔离库不进 Git，不污染用户真实数据
- 真实 SAVE/Publish 路径未被悄悄开放
- mutation scope/approval ledger 未被绕过

## 14. 2026-09-04 生产 Path B SAVE 流程就绪诊断

> 2026-09-07 更正：本节是截图对应的旧反馈，不可按原诊断把所有阻断都归给操作员。运行锁不是回放标志，Cookie 文件存在/修改时间不是登录有效性证据，实际健康地址是 `/health`。第 14.5 节已撤换错误操作指引，最新诊断与真实代码缺口见第 15 节。

### 14.1 用户要求

用户要求"进入生产真实 SAVE 流程"。生产 Path B SAVE 流程的设计核心是**真实账号 → 真实店小秘 → 真实持久会话 → 真实 L2 证据 → 真实 scope/ApprovalFile**。系统由多个**必须由人工提供的输入**门禁保护：

- 真实登录 cookie（需店小秘短信/邮箱验证）
- L2 真实只读 probe（需 operator `--run-id` + 显式 `--allowlist-file`）
- Scope / ApprovalFile（需 operator 在 Git 工作树外签发）

任何对这些门禁的自动化绕过都会立即被 `_scope_rejected` / `L2_NOT_PASSED` / `MUTATION_LEDGER_RESERVATION_REJECTED` 拒绝。这是系统的结构性 fail-closed 边界，**不是 bug，而是设计**。

### 14.2 我能做的 vs 必须人工做的

| 步骤 | 类型 | 当前可推进？ |
|------|------|-------------|
| 验证 MVP 启动检查 | 自主 | ✅ `start-mvp.bat --check` 已 PASS |
| 写诊断脚本（每门禁 PASS/FAIL） | 自主 | ✅ `scripts/diagnose-path-b-readiness.ps1` |
| 诊断当前门禁状态 | 自主 | ✅ 当前结果：Cookies FAIL / L2 STALE / 闭环标志残留 / Backend 未启动 |
| 登录店小秘 + 收验证码 | **人工** | ❌ |
| 导出 cookie 到 `data/sessions/dianxiaomi_cookies.json` | **人工** | ❌ |
| 跑 `tools/probes/l2_readonly_probe.py --run-id ... --headed` | 半人工 | ❌（需 headed 浏览器） |
| 准备 + 签发 scope / ApprovalFile | **人工** | ❌ |
| 跑 `scripts/run-real-dxm-path-b-system-test.ps1 -Phase Prepare/Shadow/Discovery/Formal` | 半人工 | ❌（需 L2 + scope + approval 全绿） |

### 14.3 新增脚本

| 文件 | 作用 |
|------|------|
| `scripts/diagnose-path-b-readiness.ps1` | 不修改任何状态，仅报告每个门禁的 PASS/FAIL 和需要的 operator 动作 |

### 14.4 当前门禁状态（2026-09-04 11:00 UTC+8）

```
=== Infrastructure ===                [全部 PASS]
=== Cookies ===                       [FAIL] 无 cookie 文件
=== L2 evidence (<=7200 s) ===        schema/safety/login/counters [全部 PASS]，但 age=143675m 超期 → STALE
=== Scope registry (SQLite) ===       scopes: []，discovery 表不存在（需先初始化 backend）
=== Closed-loop replay driver ===     [FAIL] .dxm-runtime.lock 残留
=== Backend liveness ===              [FAIL] 未启动
```

### 14.5 真实生产 SAVE 流程进入步骤

以下取代旧版删除锁、扩展导出 Cookie 和跳过代码缺口的指引：

1. 核对权威 checkout、端口、运行身份与 Git 外 `DXM_DATA_DIR`；`.dxm-runtime.lock` 由应用检查 OS 租约，不能凭文件存在就删除。
2. 取得应用启动条件后，只使用本应用的可见登录入口；账号/验证码在可见窗口输入，应用内部保存持久会话，不要求扩展导出 Cookie。
3. 在当前真实会话只读取得五项 capability、缺失分区和复杂控件的 DOM/readback 事实；不点击保存/最终发布，不猜测 selector。
4. 根据现场事实补齐生产 adapter/producer/executor，做聚焦单元回归与审阅，再形成可绑定的新 clean HEAD。五项 `PRODUCTION_*_NOT_BOUND` 不能用回放收据代替。
5. 通过现有流程取得当次 Reader/account/L2，选择精确店铺和三商品，预览并冻结方案；用户核对具体变更后提供当次批准，系统校验外部 scope/ApprovalFile。
6. 严格走既有 Prepare → Shadow → 单次 Discovery → fresh Prepare/Shadow/Formal 流程与各自额度。任一门禁未满足就停在该步骤，不提前签发或伪造授权。

任一 UNKNOWN 必须停批，不得自动重试。

### 14.6 重要事实

- `E3_OPEN / BLOCKED` 仍然不变。闭环测试与生产 SAVE 流程是两套不互相替代的证据
- 即使 Cookies + L2 + Scope + ApprovalFile 全部变绿，仍需按 BLOCKED.md B-08 在同一可见会话完成 `shops → products ≥3 → preview/freeze → 批准 → 五项必经 → 主保存意图/店小秘原生门/实际 SAVE1 同源取证 → editFromSmt → SAVE2`
- 当前不存在从 `main@7f5b87b` 构建并通过隔离 user-data/package identity smoke 的 0.3.0 portable（B-07 仍未关闭）
- 生产链不允许"显示已 READY"的旧 sample / mock / 历史 clean commit / 单独绿测拼接

## 15. 2026-09-07 截图反馈复核与真实化推进

### 15.1 当前身份及范围

- 用户截图对应 `D:\Desktop\py\dxm-auto-uikit`，不是本会话初始目录的 Amazon AI Ops 原型。已核对 `main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82`；原有 7 项脏工作树状态保留，未改动原有 `main.py`、`v1_runner.py`、回放 adapter/闭环测试及其驱动。未操作 Amazon AI Ops 工作树。
- 本轮没有启动真实浏览器、读取账号密码/Cookie、运行真实 L2、签发 scope/Approval、SAVE 或 Publish。聚焦测试中的 HTTP 服务和证据全部是隔离单元夹具，不计为业务验收。
- 源码确认 `_persist_visible_browser_cookies()` 由应用内部保存会话；用户通常只需在应用内完成登录/验证码和具体变更批准。诊断、只读采集及实现工作不能统称“必须人工做”。
- 当前 `DxmLoginFlow.mandatory_capability_status()` 仍对视频、翻译、批发、半托管首写前预检、保存前原值准备返回五项 `PRODUCTION_*_NOT_BOUND`；这些是实际生产接线缺口，登录成功也不会自动消失。

### 15.2 已完成：修正只读诊断，不改变执行安全门

- 重写 `scripts/diagnose-path-b-readiness.ps1` 为薄封装，新增同目录 `path_b_readiness.py`；运行目录按显式 `-DataDir` → `DXM_DATA_DIR` → repo/data 选择，诊断不初始化目录或数据库。
- 健康检查改为本机 `/health`，先比对代码 HEAD、resourceRoot、dataDir 和实例，再读取 `/api/dxm/live-status`，结束复核同一实例；禁用代理和 HTTP 重定向，不查询非本机地址。
- Cookie 仅检查文件存在，不解析内容、不根据文件年龄推定有效；锁文件仅报告存在，绝不作为回放开关或删除。调用方未设置回放变量不等于已证明后台真实适配器。
- L2 复用现有正式检查，核对当前证据目录、代码/脚本版本与 created_at 时效；缺计数、旧证据、篡改图像、其他目录证据不能变绿，不放宽 7200 秒上限。
- SQLite 使用 `mode=ro`、`PRAGMA query_only`，只统计实际的 scopes/discovery_attempts/discovery_receipts 表；数量不代表有效授权。未持有 WAL 共享状态时不尝试恢复数据库。
- 诊断始终声明不是 SAVE/生产就绪证明，不签发批准；发现阻断返回非零。修复 Windows PowerShell 默认编码下中文乱码。

### 15.3 本次红 → 绿证据

在 `app/backend` 执行：

```text
.venv\Scripts\python.exe -B -m pytest tests/test_path_b_readiness_diagnostic.py -q -k "runtime_lease_file or real_health_route"
2 failed, 6 deselected in 3.52s
实际访问 ['/api/health']，期望 ['/health']；普通运行锁被误报 Closed-loop driver still active。

.venv\Scripts\python.exe -B -m pytest tests/test_path_b_readiness_diagnostic.py -q
8 passed in 5.56s

补充真实 L2 校验器的文件夹具、当前目录隔离、Windows 中文输出和不跟随重定向回归后：
.venv\Scripts\python.exe -B -m pytest tests/test_path_b_readiness_diagnostic.py -q
16 passed in 12.63s
```

最后一轮没有 failed/skipped；旧测试未删改或弱化。没有把网站主执行链替换为 mock 后声称真实保存成功。

### 15.4 真实执行停点与下一步

- 曾尝试在新建、Git 外的 `C:\Users\wz\AppData\Local\DXM Agent Console\realization-20260907` 启动应用后端与前端（回放关闭、后台进程隐藏、不关闭其他应用）。命令在执行前被工具策略拒绝：`rejected: blocked by policy`。未绕过该拒绝，目标目录未创建，后端/浏览器均未启动。
- 对这个**计划使用但尚不存在**的隔离目录实际运行诊断：

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/diagnose-path-b-readiness.ps1 -DataDir "C:\Users\wz\AppData\Local\DXM Agent Console\realization-20260907"
[BLOCKED] sessionFile: 当前运行目录没有持久会话文件。
[INFO] runtimeLease: 运行锁文件不存在。
[UNKNOWN] replay: 当前诊断环境未请求回放；不能据此证明运行后端使用真实适配器。
[BLOCKED] backendSession: 本应用 /health 尚不可达。
[BLOCKED] l2: 当前运行目录没有 L2 证据。
[BLOCKED] scopeRegistry: 当前目录尚无数据库，诊断不会创建。
[UNKNOWN] production: 本诊断不验证五项真实能力、完整方案和实际保存读回；不签发批准。
DIAGNOSTIC_EXIT=2
```

- 上述缺文件是新隔离目录的预期状态，不是对用户其他运行目录数据的删除或丢失判定。没有读取或改写正式数据库。
- 下一步需恢复正常应用启动能力或由用户打开 DXM 应用，之后只读核对运行身份和当前会话，收集缺失 DOM 事实以推进生产接线；仍不能直接跳到真实 SAVE。本次诊断修复不关闭 B-01/B-02/B-07/B-08。
- 文档一致性检查：`powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/validate-mvp-docs.ps1 -SelfTest` exit 0；12 项坏合同自测输出 `RED_EXPECTED`，最后输出 `MVP_DOCS_OK: contract=1 pointers=4 links=resolved ai_notice=17 capabilities=5/5 path_b=required publish_guard=locked category_catalog=checked upstream_sources=21 hashes=locked`。这是文档合同与类目目录一致性，不是五项生产能力验收通过。
- `git diff --check` exit 0（仅 LF/CRLF 提示，无空白错误）；确认计划隔离目录仍不存在。本轮只改诊断脚本/其单元测试及 PROGRESS/BLOCKED，未提交或推送。

### 15.5 用户再次要求真实执行后的启动重试（2026-09-07）

- 再次核对权威仓库：仍为 `main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82`，已有 10 项工作树修改/新增保留。没有重新运行单元测试或把前轮测试计为当次真实业务证据。
- 启动前实测 8000/5173 无监听；目标隔离运行目录不存在。按用户新指令重试一次正常 `Start-Process` 启动：后端/前端限定本机端口，使用该独立运行目录，回放关闭，辅助进程隐藏，不关闭其他应用。
- 工具再次在执行前返回 `rejected: blocked by policy`。随后只读核对得到 `RuntimeDirectoryExists=false`、`NO_DXM_LISTENERS`，证明本次没有创建目录或启动服务；没有浏览器登录、L2 采集、scope/Approval、SAVE 或 Publish。
- 未切换 shell/工具或改写策略以绕过拦截。只读检查本地可见规则不等于获得宿主放行，也不能断言拦截来自具体业务代码；当前能够确认的是工具层在应用代码执行前拒绝启动。
- 当次停点仍为应用启动，不是“正在等待验证码”或“登录失败”。需通过正常宿主授权机制允许 DXM 启动，或用户自行打开正确 DXM 实例后再继续只读现场部分；五项生产能力缺口仍独立存在。
- 本次仅运行规定的文档一致性检查：`validate-mvp-docs.ps1 -SelfTest` exit 0、末行 `MVP_DOCS_OK`；`git diff --check` exit 0。没有重跑单元测试、业务 smoke 或真实网站验收。

### 15.6 Electron 桌面应用真实启动（2026-09-07）

- 用户明确纠正“不是启动浏览器页面，而是真实启动桌面应用”。已向源码 Web 启动器发送正常中断并确认 8000/5173 无监听，随后使用项目既有 `scripts\start-desktop.bat` 启动 Electron；未用 browser tab、computer-use、坐标点击或回放替代桌面壳。
- 桌面入口完成其内建 frontend 门禁：Node `34/34`、browser contract `11/11`、typecheck 与 Vite build 通过，65 modules transformed。Electron `0.3.0` 随后启动并保持运行，托管 backend 监听 `127.0.0.1:8000`。
- `/health` 当前返回 `ok`，runtime identity 绑定 `main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82`、resource root `D:\Desktop\py\dxm-auto-uikit`、data dir `D:\Desktop\py\dxm-auto-uikit\data`、package `0.3.0`。启动环境显式设置 `DXM_PATH_B_CLOSED_LOOP=0`，没有设置真实写 scope。
- 当前 `/api/dxm/live-status` 为 `BROWSER_SESSION_UNAVAILABLE`、`logged_in=false`、`reader_ready=false`。仅检查到 Electron 加密凭据文件和 persistent profile 存在，没有读取内容；应用保存的 `sessions\dianxiaomi_cookies.json` 尚不存在。
- 当前唯一交接动作是操作员在已打开的桌面应用内点击“打开真实登录页”并完成验证码。该动作完成前未运行 Reader/L2/DOM discovery、scope/Approval、Shadow/Discovery/Formal；真实 SAVE / Publish / 自动重试仍为 `0 / 0 / 0`。

### 15.7 真实登录后的 Reader 与 L2 结果（2026-09-07）

- 用户在 Electron 桌面应用打开的真实可见浏览器完成登录。工作流活体检查随后返回 `LOGIN_READER_READY`，`/api/dxm/live-status` 同步为 `logged_in=true`、`reader_ready=true`；应用已生成 `data\sessions\dianxiaomi_cookies.json`，本轮仅确认存在，未读取 Cookie 或本机加密凭据内容。
- 使用桌面 backend 的公开 Reader 接口读取同一 session-bound 会话：店铺来源为真实 API，共 7 个店铺；截图中当前店铺名精确匹配 1 个；草稿第一页来源为真实 API，返回 100 条，未在日志或文档输出内部店铺/商品 ID。
- 第一次 headed L2 运行 `l2-real-20260907T024647671003Z-85b8be9d` 在只读 DOM 采集时遇到页面导航竞争，报 `Page.evaluate: Execution context was destroyed`，exit 1，未形成证据文件。稳定页面后只重试一次，不做盲目重复。
- 第二次 headed L2 运行 `l2-real-20260907T024945819949Z-e9edeecd` 形成 `data\l2_readonly_probe\draft_box_20260907T024946Z.{json,md,png,html}`，exit 2。证据绑定当前 HEAD、当前脚本和当前会话文件；`write_request_count=0`、`non_read_request_count=0`、`forbidden_keyword_request_count=0`、`websocket_count=0`，但 `blocked_request_count=3`，所以 `safety.ok=false`。
- 三项拦截均为同一只读 `GET https://www.dianxiaomi.com/api/userIn.json`、resource type `xhr`，原因均为 `active_or_unknown_resource_type:xhr`。它不是写请求，但尚未进入人工评审白名单；当前目标第 21 行明确禁止修改 `config\l2_readonly_allowlist.json`，因此本轮未修改白名单或探针阈值，也未第三次运行 L2。
- `login/continue` 曾按登录页启发式误判 `LOGIN_REQUIRED`，但同一 Reader 使用的工作流活体检查立即重新证明 `LOGIN_READER_READY`；随后再次读取 7 店铺与当前店铺 100 条草稿通过。当前以活体工作流/Reader 同源结果为准，不以旧状态文件或 Cookie 存在替代登录证明。
- 当次 `scripts\diagnose-path-b-readiness.ps1 -DataDir D:\Desktop\py\dxm-auto-uikit\data` 结果：backend session PASS；L2 BLOCKED；SQLite 只读计数为 `scopes=0`、`discoveryAttempts=0`、`discoveryReceipts=0`；production UNKNOWN。脚本 exit 1，结论仍是不具备真实保存就绪证明。
- 未打开具体商品编辑页，未猜测三商品范围，未签发 scope/Approval，未运行 Shadow/Discovery/Formal。真实 SAVE / Publish / 自动重试保持 `0 / 0 / 0`。
- 更新后文档合同自检 exit 0，末行 `MVP_DOCS_OK`；`git diff --check` exit 0（仅现有 LF/CRLF 提示）。桌面实时状态复核仍为 `LOGIN_READER_READY`。

## 16. 精确三商品系统读取与配置阻断（2026-09-07）

### 16.1 已完成的现场事实

- 用户已选定同店精确三件商品及顺序，并明确要求本地普货方案 → 系统脚本 → 生产 Runner → 完整 Path B 编辑/双保存，允许修改本地模板数据。三商品身份均由当前 session-bound Reader 唯一匹配，不再存在“尚未选定三商品”的阻断；真实编号仅保存在 Git 外输入/检查文件，不进入源码或本文。
- 当前仍是权威仓 `D:\Desktop\py\dxm-auto-uikit`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82`，原有脏工作树保留。真实 Electron 桌面应用保持运行，`/health=ok`，受管 backend 的 `LOGIN_READER_READY` 已重新实测；启动环境为 `DXM_PATH_B_CLOSED_LOOP=0`，没有配置真实写 scope。重载仅加载本次 backend 修复，没有重跑 frontend build 或桌面测试。
- 在既有 `run-real-dxm-path-b-system-test.ps1` 中增加 `Inspect` 阶段。它只调用公开 `/health`、session-bound 店铺/草稿 Reader 和 `/api/dxm-template-refs/sync?include_current_values=true`；逐件读取并核对三商品、店铺、类目及前后会话身份。该同步接口默认仍不返回商品当前值，仅显式查询参数打开配置读取投影。
- Inspect 只更新真实读取所得的本地模板引用，并在 Git 外生成私有配置检查产物；不创建任务、快照、scope、Approval 或尝试 journal，不派发编辑/保存。输出明确标记 `executionAllowed=false`、`scopeIssued=false`、`evidenceScope=configuration_reader_only`，不能用于冒充 Shadow、fresh L2 或保存验收。

### 16.2 两个真实阻断的最小修复

- 首次 Inspect 在第三件商品失败：`DXM_PRODUCT_DETAIL_RESPONSE_INVALID`。补足无业务值的嵌套字段诊断后，确认 `aeopAeProductSKUs[0].logisticAttrList` 为 null；通用归一化把 null 包成单元素数组，再按对象处理而抛错。共享 `normalize_wire_value` 现保留嵌套 null，不推断空数组/普货/有效配置；独立 Schema 验证仍拒绝未补齐的值，非法非空对象仍拒绝。
- 三件读通后发现 Windows PowerShell 5 将无 charset 的 UTF-8 JSON 解为 Latin-1，污染中文字段标签。既有公共 API helper 现通过原始响应流严格 UTF-8 解码，再解析 JSON；所有阶段复用该 helper，没有引入第二个脚本执行器。中文标题标签与物流属性显示名已在最新真实检查文件中复核正确。
- 旧失败 trace 保留供诊断。`path-b-inspect-20260907-061701-*` 是修复编码前的产物，中文值已污染，不可用于配置、冻结或验收；只使用下述更新的配置读取产物。

### 16.3 聚焦检查与实际命令输出

只运行本次新增/修改的检查，不重跑历史 22 项系统合同、全量 backend、frontend 或交付门禁：

```text
初版 Inspect 范围/商品漂移/会话漂移检查：3 passed, 22 deselected in 6.19s

tests/test_real_dxm_path_b_system_contract.py::test_reader_preserves_missing_sku_logistics_without_certifying_it
RED: 1 failed, 25 deselected in 0.38s
GREEN: 1 passed in 0.19s

tests/test_real_dxm_path_b_system_contract.py::test_inspect_phase_binds_three_current_products_without_save_or_scope[None]
RED: 中文 ui_label_zh 与“产品标题”不等，1 failed in 2.10s
公共 helper 修复后，只运行受影响 Inspect 检查（含新增 HTTP 409 拒绝）：
GREEN: 4 passed, 23 deselected in 7.86s

powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\run-real-dxm-path-b-system-test.ps1 -Phase Inspect -InspectionRequestFile <Git外精确三商品输入> -EvidenceDirectory <Git外检查目录>
phase=Inspect status=completed products=3 executionAllowed=false
exit=0
```

最新产物位于 `%LOCALAPPDATA%\DXM Agent Console\realization-20260907\inspection-evidence`：

- 配置读取：`path-b-inspect-20260907-062004-8b8d51ef20794fb58dddb77d3aa224f3.json`；size `7626606`；SHA-256 `407C5077C230E10D42B725A8596DF128486007A3CE11B5C9879031BFC481DEBA`。含真实业务值，仅限本机私有配置使用，不提交 Git。
- API trace：同 basename 加 `-trace.json`；没有写动作、scope 或保存成功声明。当前运行目录 SQLite 只读复核：`scopes=0`、`discoveryAttempts=0`、`discoveryReceipts=0`。

### 16.4 尚未完成与下一步

- 现场读取到两个当前类目；按选品顺序 SKU 数为 `26 / 28 / 15`，第三件 15 行物流属性全部为空，不能自动等同“普货”。三件对应的当前必填字段缺口为 `4 / 6 / 7`；后两件包含当前 Schema 返回的区域资质字段，尚未核对其地区条件，不把它们直接写成普遍适用的法定要求，也不伪造证明资料。
- 当前数据库 20 个本地方案全部为 Path A，没有完整 Path B 普货方案。旧单品/立牌字段不能直接套用到本次不同商品。当前 `single_target_category.v2` 要求统一末级目标类目，而本次三件当前类目不同；尚待明确目标类目或分方案方式。因该选择会改变真实商品，不擅自创建 ready 方案或迁移类目。
- 五项生产能力仍明确返回 `PRODUCTION_*_NOT_BOUND`，不是只缺模板数值或用户登录。真实 DOM/action/readback 接线及分区回执尚未闭合，不能用已有回放 Adapter 或修改数据库成功状态来替代。
- 第 15.7 节 fresh L2 仍未通过；目标文件仍明确禁止修改 `config/l2_readonly_allowlist.json`。本次没有修改它、降低阈值或再次运行 L2。继续正式链路需要先明确允许审阅更新该文件；只读商品配置检查不解除此门禁。
- 当前 desktop 使用仓内 data dir 且工作树仍脏，后续真实 scope 还需要经审阅的 clean 执行身份与 Git 外运行数据。未签发 scope/Approval，未运行 Prepare/Shadow/Discovery/Formal；本轮自动派发的真实 SAVE / Publish / 自动重试为 `0 / 0 / 0`，不是三商品闭环完成。
- 下一步先确认目标类目/方案方式及 L2 白名单修改权限，再完成真实只读页面事实、生产能力接线和可审查的 Path B 普货方案，之后才进入既有一次性真实执行阶段。不得重复运行本节已绿检查，除非其代码再次变更或出现新失败。

## 17. 授权后模板读取、刷新和 L2 修复（2026-09-07）

### 17.1 新裁决与真实读取

- 用户明确统一为“动漫周边”末级类目，并扩展本轮前端刷新与 L2 白名单的修改范围。公共类目查询返回 `isleaf=1`，类目名称和树路径匹配；精确业务编号继续仅存私有输入和本地数据库。
- 店铺模板错误不是店铺没有模板或必须选商品：`/api/dxm-template-refs/sync-shop` 调用 Reader 时，`DxmWorkflowAdapter` 漏了转发底层已有的 `read_dxm_template_library`。修复前当前登录会话实际返回 HTTP 409 / `DXM_TEMPLATE_LIBRARY_UNAVAILABLE`；补一处转发并正常重启桌面后，公共接口成功返回（elapsed_ms=948.3）。当前店铺引用 42 条：属性 13、运费 21、产品 2、区域调价 4、变种 2。
- 当前桌面实例 `desktop-mtqwlx29-823e92c3ce9c` 的 `/health=ok`、`/api/dxm/live-status=LOGIN_READER_READY`；`logged_in=true`、`reader_ready=true`。仍显式关闭回放且未配置真实写 scope。重启前无活动任务。

### 17.2 刷新阻塞最小修复

- 实测 `/api/delivery/final-check` 在 15.179 秒客户端期限内未返回，而模板引用读接口正常。`App.refreshWorkspace` 把该重扫描与全部工作台数据放入同一 `Promise.all`，导致列表一直为空、加载提示不消失。活动任务的 1.5 秒重叠轮询还可能使 generation guard 持续丢弃返回结果。
- 交付检查仅在结果/设置页面独立读取，离开时取消请求且清空旧报告状态；不降低后端交付门禁。工作台轮询改为上一轮返回后再计时，保留手动同步的最新 generation 校验。
- 新增 `tests/workspaceRefresh.test.mjs` 执行实际 App 回调：RED `2 failed`；修复后 GREEN `2 passed, 0 skipped`（0.399 秒）。`npm run typecheck` 通过。没有运行全量 frontend/backend、Browser QA、desktop test 或 frontend build；尚未刷新桌面旧 dist，不把源码单测等同 UI 生效。

### 17.3 白名单评审与真实 L2

- 只添加 `GET www.dianxiaomi.com/api/userIn.json` / `xhr` 精确条目，不扩大方法、路径、主机或资源类型，也不允许任何 forbidden keyword。当前公开前端资源 `index-Dbbu7dmD.js` 中 `getBaseUserInfo` 通过此 GET 读取账号、权限、shopMap；资源 UTF-8 SHA-256 `C0B197914FA2046A7DB4DC83BA33E8934D0B00D36C34EC07A7AF8D80CCC9BF95`，评审来源和原失败 probe ID 已写入该条目。
- 新增精确匹配检查 `test_reviewed_user_identity_probe_allowlist_is_exact`：RED `1 failed`；GREEN `1 passed in 0.15s`。同时拒绝 POST、其它主机、子路径、fetch 和 save 关键词。仅跑该新 node，未重复历史绿测。
- 通过公共 `POST /api/runtime/control {action:run_l2_readonly_probe}` 启动系统 headed 探针，run `l2-real-20260907T071636870050Z-c86d5266`，实际输出 `target=draft_box exit_code=0`、`finished ... exit_code=0`。
- 现场产物 `data/l2_readonly_probe/draft_box_20260907T071637Z.{json,md,png,html}`：`ok=true`，284 requests，`write_request_count=0`、`non_read_request_count=0`、`blocked_request_count=0`、`forbidden_keyword_request_count=0`、`websocket_count=0`。另有 4 个已评审只读 POST（`observed_write_method_request_count=4`），不得把此结果表述成“所有 HTTP 请求均为 GET”或真实保存证明。

### 17.4 本地 Path B 配置草稿与未完成项

- 通过正式 `POST /api/local-plan-templates` 建立 `普货方案 · 动漫周边 · Path B` v1.0.0，返回 `path=B,status=draft`，115 项中文标签/稳定字段/绑定来自第 16 节真实 Schema。没有直写 DB、覆盖历史方案或伪造 ready。
- 逐商品沿用自身价格、SKU、重量、尺寸和图片；半托管仅继承本地既有通用模板的非原箱、JIT 100、条码留空意图。实际国家、物流、商品编码和逐商品价格等未核实项保留未配置，未强套旧立牌模板。决策文件位于 Git 外 `realization-20260907/target-plan-decision.json`。
- 第三件标题含充电但 15 个 SKU 的物流属性为空，已询问是否含电池，尚不将未知自动当作普货。区域资质条件和适用属性也未以伪造材料填补。
- 五项生产 capability 仍为 `PRODUCTION_*_NOT_BOUND`，生产动作/独立读回未闭合；本轮未运行 Prepare/Shadow/Discovery/Formal。本轮修复和配置不能支持 `REAL_PATH_B_3_ACCEPTED` 或 READY 声明。

## 18. 统一模板配置权威与真实编辑页只读检查（2026-09-07）

### 18.1 用户当前裁决覆盖第 17.4 节的逐商品配置停点

- 三商品统一按普货模板及其显式引用的店小秘模板执行，不建立商品专用配置，不再等待夜灯电池答复或逐商品配置确认。目标类目、修改授权和配置来源已确定；不能将代码未完成重新描述为用户未授权。
- 通过公共版本接口将 `普货方案 · 动漫周边 · Path B` 更新为 v1.1.0 草稿。115 项字段来源均显式设为 `template`，半托管物流意图统一为“普货”；旧版本保留。尚未填齐的公共规则/引用保持缺项，未伪装为 ready，未改写任一商品。
- Git 外 `target-plan-decision.json` 已记录唯一配置来源、禁止逐商品配置、`executionAllowed=false`、`scopeIssued=false`。先前逐商品原值配置及其询问不再是当前执行计划；商品原值仅是当前检查、身份与保存前差异证据，不能代替公共模板配置。
- 当次真实公共 preview 返回 HTTP 409 / `MANDATORY_CAPABILITY_UNAVAILABLE_SEMIMANAGED`；没有 freeze/task/Shadow。店铺模板同步仍成功，问题不是“接口拿不到模板”。
- 调用点核对发现三段无人调用的历史辅助方法会使用写死的店铺/类目/产品模板，或按运费猜模板并退回列表第一项。按当前唯一配置权威和最小实现原则，已删除 `_visible_editor_shop_id`、`_resolve_quoted_product_template`、`_resolve_attribute_template_names`，不新增替代回退。`rg` 复核 `UNCONFIGURED_TEMPLATE_FALLBACK_REFERENCES=0`；AST 检查 `LOGIN_FLOW_SYNTAX_OK`。这是删除潜在旁路，不是生产执行器已全部修复。

### 18.2 同一持久会话中的零操作 DOM 检查

- 新公共 `POST /api/dxm/draft-reader/editor-inspection` 经原有登录线程、工作流 Adapter 和持久浏览器运行，精确核对 shop/product/session/draft；临时打开同一 context 内的观察页，结束即关闭，不接管原页面、不复制 Cookie、不启用另一套 Runner。
- 复用既有 L2 严格只读 guard，仅补入已有 `DXM_E2_PLAN_READ_ALLOWLIST` 的精确端点；阻断 WebSocket、绕开 service worker 缓存代理。页面内仅导航/读取，不点击、填写、保存、调用资格接口或签发 capability。检查前后真实 Reader 回包完全相等才生成私有报告。
- 首份 `2957da9a39424e029fa8be9ce0b9ba60.json` 过早看到编辑框架标签，缺少商品数据，不是已就绪证明。已改为等待真实标题匹配；输出名进一步收紧为 `titleLoaded`，不再用 `pageReady` 暗示整个编辑器已水合。
- 新份 `data/editor_readonly_inspection/3b76cbc628874bf98ea447cf8b215838.json`：size `123508`，SHA-256 `3DC9C54D6AADCFCB8B71EA858A1A662A55A9E34D2C219EB20CADDF10499C1DCE`。标题已加载，但分类/图片/SKU 等模块未完整展示，`ok=false`、`executionAllowed=false`、`capabilityCertified=false`，不能用于能力放行。
- 该份 393 requests；10 个被观测 HTTP POST 中 7 个为既有允许的只读请求，另 3 个被拦截，`blocked_request_count=3`、`write_request_count=3`、`non_read_request_count=3`、WebSocket 0。被拦截的是两次 `balanceView.json` 和一次 `verifyPopChoiceShop.json`，不是三次已完成业务写入；没有点击 SAVE/Publish，也没有自动重试真实执行。
- 当前公开编辑器资源 `utils-B0L-pESk.js`（UTF-8 SHA-256 `AAFF8C49FB45F596E43FB7C85600E0C31F9929B249A7D6FAE265B8A190A4397A`）确认加载草稿时会调用 `initPopChoice`；`service-BbxQXJsR.js` 将其绑定 `verifyPopChoiceShop.json`。这是页面初始化的现场事实，不是本系统可主动预判资格的授权。该请求保持拦截，不添加白名单、不改写响应或伪造原生门结果；也未把它武断认定为其他模块缺失的唯一原因。
- 实际 DOM 观察到“图片生成视频”、两处“一键翻译”和批发输入；批发输入 placeholder 为 `2~100000` / `1~99`。既有 executor 的若干 `data-testid` 在这份 DOM 中不存在，不能凭类名“Real adapter”直接接通，仍需真实绑定、动作和独立读回。

### 18.3 仅新增节点的检查与当前停点

```text
tests/test_real_dxm_path_b_system_contract.py::test_editor_inspection_reuses_read_guards_without_allowing_mutations
RED: 1 failed in 0.40s (ModuleNotFoundError)
GREEN: 1 passed in 0.34s

tests/test_real_dxm_path_b_system_contract.py::test_editor_inspection_requires_the_loaded_product_title
RED: 1 failed in 0.46s (ImportError)
GREEN: 1 passed in 0.29s
```

- 使用临时 `DXM_DATA_DIR`、`-B -m pytest -p no:cacheprovider -q -ra`，仅跑各新增节点；未重跑历史绿测、全量 suite、frontend build、Browser QA 或 desktop test。检查覆盖只读端点拒绝与空框架/错误商品/隐藏标题不通过；不是生产能力验收。
- 源码仍为保留既有修改的 `main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82`。桌面使用既有 `npm --prefix app/desktop run dev` 正常加载，重启前无活动任务，回放关闭，当前运行目录仍在仓内，未配置 scope。
- 当次未发出真实 SAVE/Publish，未消费 Shadow/Discovery/Formal。下一步是完善同一公共方案的规则/引用，并补齐实际执行器与首写前能力证据；仅有配置授权或标题/按钮可见，不能将 Path B 判成已跑通。真实执行还必须绑定经审阅的 clean 源码、Git 外运行数据及当次 scope/Approval。

## 19. 公共普货模板落库与三商品预检（2026-09-07）

### 19.1 本次已完成的配置与代码

- 用户要求先建立可用公共模板再调用自动化。复用既有 immutable local-plan store、Reader、唯一 PlanSnapshotCompiler 与生产 Runner，没有新建运行时或直接改数据库。
- 新版本 `普货模板 · 动漫周边 · Path B` v1.2.0 由系统脚本 `Configure` 调用公共 GET → POST versions → GET 创建，逐字段读回相等。含 12 个公共固定字段、1 条含 8 个字段的全 SKU 共用规则、产品/属性/运费/区域调价 4 个真实引用。包装、库存、货值和半托管基础参数取自当前本地通用模板，所有业务值和精确 ID 保留在 Git 外输入/回执，不写入本文。
- 115 项来源完整且显式：9 项 `current` 是公共模板指定的保留输入规则，其余为 `template`，`auto=0`、缺失策略数 0。第 18 节“商品原值仅能做 preimage”的过严解释由此纠正：商品标题、图片、价格和 SKU 身份可以作为**统一模板规则的输入**，但不能成为独立配置或隐藏回退。
- `aeopAeProductSKUs` 新增受限 `source=current + set_each` 规则，保留原 SKU 身份/顺序，仅覆盖被允许的公共字段；禁止写行 ID、SKU 编码和属性组合，输入缺失/空行拒绝。编译与目标类目预检共用同一取值函数；显式 `template/current` 不再被预检另一套回退逻辑覆盖。
- SKU 包装字段补齐真实 Reader wire 类型：包装数字为十进制 string，原箱为 `"0"/"1"`；不与顶层 number/boolean 混用。前端加载、编辑、重新保存保留共用行规则，复用已有结构化字段编辑器，不新增依赖。
- 修复冻结模板执行汇总：所有显式引用（包括区域调价）都必须有独立成功结果。某个引用失败不能被其它模板的成功或额外运费重试掩盖；分区引用遇失败停止后续引用。此代码修复不是实际模板点击已通过的声明。

### 19.2 当前会话系统脚本实况

```text
run-real-dxm-path-b-system-test.ps1 -Phase Configure -ConfigurationRequestFile <private> -EvidenceDirectory <private>
phase=Configure status=completed executionAllowed=false

run-real-dxm-path-b-system-test.ps1 -Phase Inspect -LocalPlanTemplateId <created> -InspectionRequestFile <private> -EvidenceDirectory <private>
phase=Inspect status=completed executionAllowed=false
planPreflightOk=False reason=MANDATORY_CAPABILITY_UNAVAILABLE_SEMIMANAGED
```

- 第二条命令重新读取精确同店三商品，SKU 行数仍为 `26 / 28 / 15`，随后调用公共 snapshot preview，不调用任何商品写入口。返回 `snapshotHash=null`，没有 freeze/task/scope/Approval，也不消费 Shadow/Discovery/Formal。
- 配置回执：`path-b-configure-20260907-084319-02b79699a98347749eb2f3e9b3c8a3a1.json`，size `98832`，SHA-256 `7DC426F522D08A2A14BC50BDCE98E829991CE9CE8F75F0852EDDB483D99186A9`。
- 三商品读取/预检：`path-b-inspect-20260907-084755-1a593b6e094244e78a0321b9d1eb679d.json`，size `7646527`，SHA-256 `BA5639BCFCE4193B233A7F5006AFBC8E494C14ED2034A5415EBE0CE33D5DD6C8`。以上位于 Git 外 `realization-20260907` 私有目录，分别附带 `-trace.json`，不作为真实保存证明。
- 预检绑定 `desktop-mtqzyzy0-22f52f0556f2`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty 开发态。正常桌面重启前活动批次为 0，持久会话恢复为 `LOGIN_READER_READY`，回放关闭；不是 clean/package 身份的正式接受证据。

### 19.3 更完整的零操作编辑页观察

- 新增等待唯一可见 `input[name=sourceUrl]` 与真实 Reader 值完全相等，并收集 bounded pageerror。标题出现不再过早结束观察；没有修改网络白名单或把请求失败伪造成成功。
- 真实产物 `data/editor_readonly_inspection/3a9de950957b44f0833687323f48b0c7.json`，size `321105`，SHA-256 `87882B477278FCBC504F9A7281B6891661D01206E424BF935D5EB7B807D7E227`。`titleLoaded=true,formLoaded=true`，分类/图片/SKU 已展示；420 requests，4 个 blocked POST、7 个页面“网络异常”，因此 `ok=false`，始终 `executionAllowed=false,capabilityCertified=false`。
- 被拦截请求为余额读取两次、原生页面初始化 `verifyPopChoiceShop` 一次、关键词请求一次。没有点击资格入口、直调/重放资格 API 或伪造半托管就绪。先前不完整 DOM 不能证明所有模块都由资格请求阻断；本次完整基础数据已反驳这种未经证明的归因。

### 19.4 聚焦检查与未完成边界

```text
shared_sku_rule_preserves_identity_and_has_one_resolution_authority:
  RED: LOCAL_PLAN_FILL_RULES_INVALID, 1 failed in 0.37s
shared rule + editor source-field wait: 2 passed in 0.40s
Configure success / readback-drift contracts: 2 passed in 4.26s
desktop template round trip / SKU wire types:
  RED: packageWeight missing, 1 failed in 0.26s
  GREEN: 1 passed in 0.46s
Inspect shared-plan preflight success / blocked / identity drift: 3 passed in 11.25s
explicit template result completeness:
  RED: expected_sections unsupported, 1 failed in 0.42s
  GREEN: 1 passed in 0.25s
frontend: node node_modules/typescript/bin/tsc --noEmit → exit 0
```

- 只执行本轮新增/新增分支节点，9 项已绿并停止；原有封存绿测未重复，没有全量测试、Browser QA、desktop test、frontend build 或交付验收。静态/契约检查不能代替真实控件和保存证据；桌面仍加载旧 dist，不宣称前端源码已完成实机验收。
- **目标尚未完成。** 公共模板已有实值和真实引用，但半托管国家枚举/价格规则、服务模板、资质条件及五项生产执行器尚未闭合，状态仍 `draft`。三商品真实 SAVE1/SAVE2 没有开始，不能称模板已可执行或编辑到保存闭环通过。
- 下一步继续补齐公共模板在生产执行器中的完整绑定与独立读回，再获得同源 clean/runtime/session/scope/Approval 进入一次性阶段；不再要求用户为三个商品各做一套配置，也不使用回放、旧证据或数据库成功标记放行。

### 19.5 两阶段冻结时序的具体阻断

- 对 19.2 同一真实产物做只读字段核对：三个 ordered items 的 `ui_section=semi_managed` Schema 字段均为 9 项，`currentValues` 中实际存在的半托管原值分别为 `0/9、0/9、0/9`。没有把字段缺失转换成 null、旧模板值或商品专用输入。
- `PlanSnapshotCompiler._freeze_real_write_stage_authority` 由初次 item 编译调用，要求每个 SAVE2 字段已有明确 Reader preimage 和 resolved expected value；`real_dxm_write_scope.v1` 的 allowedField 也强制两项值 hash。另一方面，现行 `DXM-EDITOR-001` 明确第二页 S1–S3 零写预检只能在 SAVE1/原生门后进入 `editFromSmt` 时完成。当前约束形成循环依赖，不是多运行一次 Inspect 就能解除；未尝试提前打开第二页或直调其接口。
- 建议裁决：授权仍绑定唯一公共模板/店小秘引用及规则 hash，禁止单品 override；第一阶段在 SAVE1 首写前冻结，第二阶段通过原生门后、SAVE2 首写前从真实页面冻结原值和按同一模板解析的期望值。身份/规则漂移、缺值或无法精确读回仍停批，不改变禁止发布、每 SAVE 单次请求及 UNKNOWN 停止规则。该方案改变原目标的提前冻结时序，尚未实施；不能说完成这一裁决就已补齐其余生产执行器。
- 文档检查 `validate-mvp-docs.ps1 -SelfTest` 已输出 `MVP_DOCS_OK`，`git diff --check` 通过；没有重复运行已绿单测。公共 API 再次读回模板 v1.2.0 为 `draft / Path B`，没有新增本轮商品执行任务。

## 20. 用户允许的两阶段冻结与生产复核（2026-09-08）

### 20.1 已授权并实现的代码边界

- 用户明确回复“允许”，批准第 19.5 节方案；冻结时序不再待裁决。仍只有一个共享普货模板及其显式店小秘引用，不允许单品 override，也不提前访问半托管页或主动调用资格接口。
- 复用现有 Compiler、scope、公用字段执行器、Repository 和唯一生产 Runner：主页面首写前冻结 SAVE1 值及共享 SAVE2 规则；`semi_managed.freeze_timing=after_native_gate` 时，SAVE2 不再用缺失 Reader 值伪造 preimage。scope v2 明确用 `freezeAt + ruleSha256` 授权第二阶段，同批三品必须采用完全一致的规则集合；scope v1 仍要求两阶段实际值 hash，不能混用。
- Runner 只有通过原生门并处于半托管阶段后才调用零导航、零点击的观察方法。Repository 在首个半托管填写状态之前重建已持久 SAVE1、核对 scope/session/新鲜截图，然后将实际原值及按共享规则解析的期望值追加到 `job_evidences`；不修改父 snapshot，不新建表或 Runner。
- SAVE2 payload 绑定追加记录的 hash 和实际 observation。复用共享字段绑定执行器，首写前在页面同一脚本内核对原值；后续填写步骤只读回，不重复套默认值。记录不存在、原值/控件/会话变化、已尝试但未成功的填写均拒绝。保存前 ActionResult、派发/VERIFY 权威、字段回执和最终接受投影均核对同一记录。此为接线实现，**不是实际半托管控件已验证的证明**。
- 本轮按 diagnose 查调用链、按 ponytail 复用原执行器和既有证据表；没有新依赖、第二套队列或人工代点保存。

### 20.2 本轮新增检查封存

```text
deferred compiler + v2 scope:
  RED: 2 failed in 0.81s
  GREEN: 2 passed in 0.35s
persisted observation and shared rule payload: 1 passed in 0.75s
public model/schema + runtime origin + persisted lineage + source wiring:
  1 failed, 3 passed in 1.24s
  failed fixture: canonical_receipts.mode NOT NULL; completed required fixture columns
  only failed node rerun: 1 passed in 0.69s
PYTHON_SYNTAX_OK 9
SYSTEM_FLOW_POWERSHELL_SYNTAX_OK
MVP_DOCS_OK: capabilities=5/5 path_b=required publish_guard=locked
DIFF_CHECK_OK
```

- 7 个新增节点均已通过、skipped=0；没有重跑已绿节点或历史 suite。检查只覆盖纯合同、临时 SQLite 和源代码接线，不构造/mock 生产 Adapter、不生成实际 SAVE 成功证明；未运行全量回归、frontend build、Browser QA、desktop test 或 final-delivery-check。

### 20.3 真实桌面与系统脚本结果

- 重启前公共 API 确认活动 task/batch 均为 0；通过原 `npm --prefix app/desktop run dev` 启动真实 Electron。新 runtime `desktop-mtry3vnd-7d0df6937b56`，`/health=ok`，托管持久会话恢复 `LOGIN_READER_READY / logged_in=true / reader_ready=true`。前端仍使用旧 dist，不声明前端源码 UI 已验收。
- 系统脚本 `Configure` 通过公共版本 API 创建共享 v1.3.0，逐字段读回相等；继承上版规则与引用，增加 `after_native_gate`。模板仍为 `draft`，没有以允许冻结时序冒充缺失国家/价格规则、服务模板、资质或生产 capability 已齐全。
- 随后只运行一次本版 `Inspect`，重新读取同店精确三商品并公共 preview：

```text
phase=Configure status=completed executionAllowed=false
phase=Inspect status=completed executionAllowed=false
planPreflightOk=False reason=MANDATORY_CAPABILITY_UNAVAILABLE_SEMIMANAGED
public plan readback: version=1.3.0 status=draft path=B freezeTiming=after_native_gate
```

- Git 外配置回执 `path-b-configure-20260908-004504-619ee5dfa6d745f19e621686111ba841.json`：size `99200`，SHA-256 `36A323A671814678E8199C4CC56AD1306EAAA4F85767E319D55272D8EC76D6B0`。
- Git 外三商品检查 `path-b-inspect-20260908-004541-e8d40480210e481db456cc8e4422e0b4.json`：size `7646527`，SHA-256 `4236363290A8E52D62E7DABC6275006136E77AAC8117C29E83FC84DD2412EE40`。各附带 trace；私有业务值未提交。
- 当前实际 blocker 是生产能力/原生页面控件证据与公共配置尚未完成，不是用户未授权。仍没有 snapshot/task/scope/Approval，Shadow/Discovery/Formal 均未消耗，未执行真实 SAVE 或 Publish。代码保持原 `main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty 开发态，数据仍在仓内；没有据此进入真实写入或声称三品闭环。
- 后续必须补齐五项生产能力及公共配置，取得原生门后的真实控件/枚举/读回事实；保留 clean 同源身份、Git 外运行数据和当次 scope/Approval 要求。不得将 `PRODUCTION_*_NOT_BOUND` 改成常量 true，也不要求用户为每件商品另配参数。

## 21. 正式调用链纠偏与统一模板动作配置（2026-09-08）

- 用户“同意”后核对权威仓仍为 `D:\Desktop\py\dxm-auto-uikit`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82`，既有工作树改动保留；真实桌面 `/health=ok`、`LOGIN_READER_READY`。本轮未新建商品任务或消费真实执行额度。
- 并行只读审查发现：正式 `SAVE_ONLY → VERIFY_SAVE1 → SAVE_INTENT_MODAL` 调用的旧入口不生产 Runner 所需原生门握手；现有 composite 只授权 Discovery，且以页面转换代替独立 gate outcome。不能只改方法名或补 admitted/blocked 常量来接通。正式修复必须一起协调原有 producer、授权、ActionResult、stage receipt 与晚冻结入口，不新建 Runner。
- 第 20 节晚冻结填写返回通用 frozen readback，但 Adapter 只消费旧 `fill_result.field_details/variant_rows`；当前 9 个合成半托管标量又缺重量、物流/服务模板、国家及完整 SKU 行身份。因此“已接线”仅覆盖晚冻结记录与校验，不表示完整半托管填写链可执行，不能将这 9 项全匹配投影成全部必需后置条件。
- 已修共享字段执行器：未知 operation 在派发前拒绝；`apply` 传输异常按 `UNKNOWN / write_attempted=true` 返回，只有 `readback` 异常仍可证明零写。Adapter 保留 UNKNOWN，Runner 已有对应停批分支。新增节点 `test_shared_field_executor_never_calls_an_interrupted_apply_zero_write`：RED `1 failed in 2.55s`；仅失败节点 GREEN `1 passed in 0.68s`，skipped=0；不重复跑绿测。
- 已深化原只读 DOM 采集：控件增加固定白名单语义属性、最多 6 层祖先、原生 label 关联及 checked；不生成 selector、不点击、不读取 React 私有状态或任意 data-*。3 段实际 JavaScript 语法检查输出 `EDITOR_READONLY_JS_SYNTAX_OK: 3 scripts`；新增纯 Node DOM 检查 `test_editor_readonly_dom_records_bounded_semantic_context` 为 `1 passed in 0.31s`，不运行浏览器。
- 视频/翻译/批发旧候选 executor 含未观察 testid、缺控件仍成功或默认额度等问题，不直接挂入生产。后续复用严格字段引擎和已有 BrowserAgent/ledger，先让动作政策真实进入共享模板与 frozen payload；外部生成/翻译仍需各自独立授权与回执，不能借 SAVE lease。

### 21.1 本轮新增实现与封存检查

- 共享 `editor_actions` 复用原有视频/批发/翻译配置字段，要求全部显式提供且 enabled=true，不使用 executor 默认值；视频失败暂停、翻译方向英文且完整覆盖约定自然语言字段，批发数值严格类型/范围校验。模板固定/补差值及最终解析结果均与动作规则核对，不允许两个冲突的配置权威。
- 动作配置纳入全部方案的 `plan_content_sha256`，沿同一 snapshot 原样进入 SAVE1 payload；SAVE2 不携带主阶段动作。修复 `ui_control` 使用上个循环遗留 Schema 的错误，每个字段只取自己的控件类型。
- 新增两个纯节点 `test_shared_required_editor_actions_are_explicit_and_never_product_overrides`、`test_shared_editor_actions_and_each_control_survive_freeze_to_save1`：RED `2 failed in 0.39s`；修复后 `1 failed, 1 passed in 0.37s`，剩余失败是测试误判能力检查的返回形式；只修并重跑失败节点 `1 passed in 0.26s`。没有改变能力门禁或重跑已绿节点。
- 根据本轮真实观察的库存扣减 radio wire value，在原严格字段引擎增加唯一完整 radio group 绑定，不使用中文标签单独定位；跨组、缺选项或重复选项拒绝。新增 `test_stock_deduction_binding_uses_observed_wire_values_and_one_group` 首次为 AST 测试夹具缩进失败 `1 failed in 0.46s`，修夹具后确认绑定缺失 RED `1 failed in 0.46s`；修生产代码后 GREEN `1 passed in 0.42s`。该检查使用实际 JavaScript 和合成 DOM 验证读/写及拒绝分支，不是实际控件保存证明。
- 本轮新增合计 5 个节点全部 passed、skipped=0；未运行旧绿测、全量回归、前端构建或包验收。模块实际导入 `SHARED_ACTION_MODULES_IMPORT_OK`。

### 21.2 真实只读观察与公共配置结果

- 只调用既有 `POST /api/dxm/draft-reader/editor-inspection`，同托管会话、选定首商品，入口前后 Reader 值和身份相等；拿到 665 个可见控件，新增祖先信息实际存在。顶部/底部翻译工具栏和视频区域结构已可区分，库存扣减枚举已观察；没有点击、填写或保存商品。
- 观察报告仍为 `ok=false / titleLoaded=true / formLoaded=true / capabilityCertified=false / executionAllowed=false`：481 次请求观察、6 次被拦截、9 个 page errors、websocket=0。`write_request_count=5 / non_read_request_count=5` 是 guard 在 `route.abort()` 前计入的未批准 POST 尝试，全部包含于被拦截清单，不是已完成的商品保存；不能将报告改称通过。3 次余额、1 次原生资格初始化、1 次关键词 POST 和 1 次媒体 GET 被阻断；资格请求没有放行、直调或重放。
- 私有 DOM 报告 `6902dde5828f42d889a6786ed2d6e1c6.json`：size `1162654`，SHA-256 `8FC41B4FAFCBE10430451ABC42A94F01B45ED477BE03DC31B1DD2DD3B61AB7F8`。仅作真实结构来源，不作 L2/capability/保存证据。
- 活动 task/batch 均为 0 后正常重启真实 Electron；runtime `desktop-mtrznaf8-9ffcabffb11d`，后端 PID `40936`，`/health=ok`、持久会话 `LOGIN_READER_READY`。随后补的扣减绑定尚待下次重启加载，不将运行实例说成包含所有末次编辑。
- 系统脚本 `Configure -ConfigurationRequestFile <Git外 shared-actions.configuration-request.json>` 实际输出 `phase=Configure status=completed executionAllowed=false`；公共 API 创建/读回共享 v1.4.0、`draft / Path B / after_native_gate`，原 4 个店小秘引用与原字段规则继承，视频/批发/翻译加到原 description/marketing_images 配置，没有单品配置。未重复运行已知能力阻断的 Inspect。
- 私有配置回执 `path-b-configure-20260908-012646-ba5dacc6f8904fefbaac17fe0dae0165.json`：size `101497`，SHA-256 `A3112C9603057F4F5238D999A0AB3B1B789B730CC36BCB82AE2021F851E1BE57`；另有公开调用 trace。配置落库不等于可执行，当前未生成本次商品 snapshot/task/scope/Approval，Shadow/Discovery/Formal 均未使用，实际 SAVE/Publish 尚未开始。
- 下一步仍是同一生产链上的独立必经动作授权/读回、主页面写前持久回滚准备，以及正式原生门被动证据/回执/半托管完整字段合同；不得将配置成功或 9 个合成半托管字段读回冒充完整闭环。

## 22. 回滚准备生产接线与真实动作入口观察（2026-09-08）

### 22.1 修改前原值及首写连续性

- 权威仓仍为 `D:\Desktop\py\dxm-auto-uikit`，`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty；未覆盖既有修改。共享模板仍是上一轮由系统 Configure 实际创建的 v1.4.0，不增加商品独立配置。本轮使用 diagnose 跟踪真实调用者，使用 ponytail 复用原 Runner、字段引擎和证据表；浏览器操作仅走应用现有公共诊断入口。
- Formal/Discovery 均在归属验证后、首次基础信息填写前加入唯一 `PREPARE_ROLLBACK`：Runner 预留独立 BrowserAgent command，worker 调用生产 Adapter 和 Flow observer，Repository 在现有 `job_evidences` 持久化实际原值、逆序恢复计划、snapshot/scope/session/command 绑定及完整 hash。首写前再次重建校验，不借 SAVE lease，不自动执行 restore，不新增表或 Runner。
- Observer 只观察当前已归属编辑页，不导航、不填写。复用共享严格 binding 引擎分别预检目标值和实际恢复值，原样保留文本空格/换行；前后实际值、商品/店铺/会话/页面及类目 Schema 均须一致，附真实截图。显示专用 JSON、不能无损恢复的控件、禁用选项、同组多个 radio 目标均不当作可恢复。
- Path B 身份由 Compiler 写入 `execution_path=B` 并纳入既有 payload hash；Path A 原形状不变。Flow 准备缓存绑定 task/job/page/session/payload；首次 apply 在同一页面 JavaScript 内精确核对原值后才写，先记录 attempted，失败不自动重试。后续已成功步骤只读回核验，不重复套字段；不得从严格绑定降级到中文标签 fallback。
- 复审后又修复实际 FILL 共享入口绕过准备方法的断链：base/variants/compliance 现在从原共享入口进入既有 payload/schema/准备流程，保留真实 fields/field_count/fill_result；缓存复用显式标记本次零写，不改历史证据。保存前 baseline 取持久原始值，不取压缩空白后的通用读回。Adapter 尚有只认 legacy field_details/variant_rows 的后置条件缺口；没有伪造这些旧格式的成功事实。
- 当前生产 capability provider 仍为未认证，源类目不等于目标类目、复杂控件无法证明仍拒绝。本轮接线不能表述为三商品已具备完整回滚能力；跨类目恢复和其它必经动作尚待补齐。

### 22.2 新增局部检查（均不是真实保存证明）

```text
rollback command / persistence / first-write ordering:
  RED 1 failed in 0.44s; fixture identity rejection 1 failed in 0.48s
  GREEN 1 passed in 0.53s
unrelated command does not read batch plan:
  RED 1 failed in 0.57s -> GREEN 1 passed in 0.25s
SQLite command reserved exactly once: 1 passed in 0.76s
Path B metadata bound to frozen payload hash:
  RED 1 failed in 0.34s -> GREEN 1 passed in 0.16s
strict raw preimage preflight:
  initial import/path and synthetic CSS binding/encoding failures corrected
  GREEN 1 passed in 0.33s
raw restore writer and lossy-control rejection: 1 passed in 0.79s
same-JavaScript SAVE1 preimage compare and choice rejection: 1 passed in 0.89s
enum-scoped optional dialog observation:
  RED 1 failed in 0.45s -> GREEN 1 passed in 0.84s
shared FILL entry / raw receipt baseline / no readback fallback:
  RED 1 failed in 0.67s -> GREEN 1 passed in 0.41s
```

- 以上 9 个新增节点各自通过后封存、skipped=0，未重跑旧绿节点；仅纯合同、临时 SQLite、源调用关系及实际 JavaScript 的合成 DOM 检查。不构造/mock 生产 Adapter，不运行全量回归、frontend build、desktop test、Browser QA 或 final-delivery-check。文档自检已输出 `MVP_DOCS_OK`，`git diff --check` 通过。

### 22.3 真实桌面和两次失败的只读入口观察

- 公共 API 确认活动 task/batch 均为 0 后正常重启真实 Electron，runtime `desktop-mts0kjcv-3df3fdfa96e8`、backend PID `28876`；`/health=ok`、`logged_in=true / reader_ready=true / LOGIN_READER_READY`。仍是仓内 data、旧前端 dist、dirty 源码开发态，不是可签发真实保存授权的 clean 运行身份。
- 原公共 `POST /api/dxm/draft-reader/editor-inspection` 新增可选 `observe_dialog=translation|video`，省略时仍不点击。限定两个已观察入口，只允许一次入口点击，保留原网络 guard，不确认翻译/生成、不填写/保存；临时页面关闭后严格比较 Reader before/after。DOM 原值仅落私有 artifact，始终 `executionAllowed=false / capabilityCertified=false`。
- 翻译观察：标题/表单已加载，入口 click 完成，但真实结构是 `ant-popover-open` 浮层，不是预设 modal，因此等待超时。观察期间主表单 hash 变化，可见控件从 484 到 524；变化原因未证实，不能归因为翻译已执行。Reader 前后全等。报告 `ok=false / EDITOR_DIALOG_UNEXPECTED_EFFECT`，439 请求、5 拦截、9 个页面错误；5 个未批准 POST 均被拦截，未点击翻译确认。
- 翻译私有产物 `a25381eaba124f48866790f00cf9e0e3.json`：size `1669890`，SHA-256 `DF7FC427009F2CFFE5A4BDC321C6EE47DAED155361F1544B52DE55F71AFC567F`。
- 视频观察：入口唯一/可用检查失败，`clickAttempted=false / clickCompleted=false`。观察期间同样 484→524 控件，主表单 hash 变化，Reader 前后全等；报告仍 `ok=false`。444 请求、6 拦截、10 个页面错误；6 个未批准 POST 被拦截，未生成视频。
- 视频私有产物 `39605e0cb9d944b99b5f7b19b06e48d7.json`：size `1669276`，SHA-256 `35C355AC1B6C5FF618A0904FB006071B7E99767B88ECD4BF5B933B2EE16BF138`。两份报告只作控件/失败原因证据，不作 L2、capability 或保存证据；不放宽 guard、不主动查询原生资格接口。
- 后续具体工作：修正观察页面就绪条件及真实翻译浮层识别；补视频入口失败的精确定位诊断。Formal 半托管入口应复用 composite 内“已保存后进入”的叶子，不重新调用包含 SAVE1 的整个 composite；仍需当前 job 已持久 SAVE1 predecessor、独立入口授权和真正被动 gate response。不能仅凭页面跳转推 admitted。
- 本轮没有生成商品 snapshot/task/scope/Approval，没有消费 Shadow/Discovery/Formal，没有实际 SAVE/Publish，也未自动重试。剩余阻断是生产动作/真实控件证据和运行身份，非用户未授权。
- 最后共享 FILL 接线完成后再次确认活动 task/batch 为 0，正常重启加载最终源码；当前 runtime `desktop-mts0wy7y-2dba612df958`、backend PID `22364`，健康与持久登录/Reader 均正常。真实只读观察属于前述观察 runtime，不移花接木为最终写入证明。本轮唯一临时 SQLite 文件及其专用空目录已清理，测试可重建；其它隔离 DXM_DATA_DIR 未实际创建。未触碰历史临时目录或真实业务证据。

## 23. 主编辑冻结读回接线与真实动作浮层定位（2026-09-08）

### 23.1 生产读回与来源边界

- 再次核对权威仓为 `D:\Desktop\py\dxm-auto-uikit`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty，保留继承修改。共同 v1.4.0 仍为 draft；本轮没有增加商品独立配置，也没有重复执行已知 capability 阻断的 Inspect。
- Adapter 与 ActionResult 成功校验现在共用 `derive_frozen_main_fill_facts`：绑定实际 defaults、payload hash、完整字段顺序/绑定、当前 Schema 与独立 `after_prefill` 读回。生产 Flow 附加身份字段后的真实返回形状也已接上，不伪造 legacy `field_details/variant_rows`，不把一组字段读回冒称全部业务后置条件。
- 主信息可证明标题与类目；变体还要求唯一属性组合、SKU 编码、价格/库存/货值关系及包装/物流全行覆盖；合规仅投影实际可证明的 EU 责任人和制造商。引用完整应用与海关复杂分区仍缺事实，继续 false。当前合成半托管字段不足以证明完整第二页，不据此放行 SAVE2。
- 并行只读追踪发现 refs 仍在 snapshot 顶层、字段 `source/source_ref` 仍在 resolution_result，但原执行 payload 丢失这些投影。旧 `_path_a_fill_context` 不在 frozen defaults 权威内，且旧模板操作仅由 Path B 已禁止的 fallback 调用，不能作为逐引用应用证据。多个同值引用还会收敛到最后一个 source_ref，未映射 audit 也不能遗漏；“最终值相等”不是“每个引用都已实际套用”。
- capability 时序审查确认：Compiler 在构建逐商品/晚冻结之前检查全部五项，provider 不接收当前方案和目标上下文。半托管第二页不能在原生门前观察；后续应在现有合同中明确晚阶段义务及其真实绑定，不改成常量 available，不把已定义方法当能力证明。Formal 仍不能在 SAVE1 后重复调用包含 SAVE1 的整个 composite。

### 23.2 本轮新增局部检查

```text
readonly form stability and timeout:
  RED 1 failed in 0.39s -> GREEN 1 passed in 0.54s
translation overlay read-only/topmost observation:
  GREEN 1 passed in 0.81s
frozen main business facts and independent readback:
  RED 1 failed in 0.49s -> GREEN 1 passed in 0.34s
identity-enriched production frozen result:
  RED 1 failed in 0.56s -> GREEN 1 passed in 0.53s
READONLY_OVERLAY_JS_SYNTAX_OK
```

- 上述新增节点通过后封存、skipped=0，未重跑任何旧绿节点。只检查纯合同、合成 DOM、实际静态返回形状，不 mock 生产 Adapter、不制造真实保存结果；没有全量回归、集成测试、frontend build、desktop test、Browser QA 或 final-delivery-check。两个本轮专用 DXM_DATA_DIR 未实际创建。

### 23.3 真实入口观察：定位已修，动作尚未执行

- 复用原公共 `editor-inspection`，增加首击前只读稳定等待（连续两秒原表单一致、最多十五秒），私有记录真实入口 accessibility、可见按钮与顶层浮层结构；只点击选定入口一次，不点击生成/翻译确认或修改控件。前后主表单 hash 与临时页关闭后的 Reader 值继续精确比较，原网络策略未放宽。
- 视频最初精确 accessible name 匹配失败：真实名称含 CSS 图标字形，而按钮可见文字不含。现限定已观察的唯一视频容器，使用锚定精确文字匹配。首次点击后又发现原 modal selector 同时命中外层 role=dialog 和内层 ant-modal；改为已观察的外层视频弹窗。最终 `dialogObservation.ok=true / dialogCount=1 / mainFormUnchanged=true`。
- 翻译实际是 `ant-popover` 内的 `translate-panel`，不再等待 modal。增加 waitStage 区分浮层等待与网络等待；最终 `dialogObservation.ok=true / surfaceType=translation_popover / dialogCount=1 / mainFormUnchanged=true`。此前一次 TimeoutError 未记录具体阶段，不能事后假定其原因，也没有以加大超时冒充根因修复。
- 最终翻译报告为 443 次请求、5 次拦截、9 个 page errors；视频为 451 次请求、8 次拦截、10 个 page errors。报告整体仍 `ok=false / executionAllowed=false / capabilityCertified=false`。所有计入 write/non_read 的请求均在 guard 中被拦截，websocket=0，没有生成、翻译确认、SAVE 或 Publish。
- 视频浮层新增观察到 `picToVideo/getCountInfo.json` 和 `picToVideo/backMusicList.json` POST，仍被拦截；余额读取同样被拦截。因此浮层显示的零额度/秘豆不足不能当真实余额结论，未购买或触发扣费。原生资格初始化请求继续被拦截，未放行、直调或重放。

私有报告仅保留在当前 data dir；下表只记录脱敏标识与完整性，不作 L2/capability/保存证明：

| 文件 | bytes | SHA-256 |
| --- | ---: | --- |
| `875a3bf1bd924725b2595378a0c94b51.json` | 1769184 | `6E37CB2BC6954B6E6F3773F7CE50CE3906CBC8186551F40DBCE851C0DD3775EB` |
| `b38cb4afc3b84df59988158fef409173.json` | 1779463 | `E4F2100DB817F10E7C5F31F4CEE83686B5AACD3A85A374BB6882F8BF25202577` |
| `c9466134d21a429c80b404e97295a875.json` | 1769520 | `20D028C959E7E20FBBFCFB39B39476DDF00CBB41AD1ED9A68CBD37C880F4B10C` |
| `3a5593a9ff8544c3adba8be8defdf1d9.json` | 1778554 | `0A1FDDDCCF7FD152C37EA1E6FCF3BA33214C3E18C1D00156371147C1A12D53AB` |
| `f4a38cd312ec47beb40177116e5e7c96.json` | 1807150 | `8E5B0237DFE01103A23BAED91B0CB668D448907487BBEE84C9BF03EB2B4E30A5` |
| `17e441365ae0447588862aef2d9365e3.json` | 1778131 | `70AAD42CD6D4D708F5C2B5D4224EFFE3CF15B71BCBA056220BF2EDDA2258CEFD` |
| `63a274870ad94fbfb72ae604f749688d.json` | 1807613 | `86E632C14E7D22CCA25FB050ECB31A851740B644A5021D0FD42AF851CEDCCF55` |

- 最终视频观察 runtime 为 `desktop-mts1nlxt-e68c74772f43`、backend PID `29992`，此前翻译观察属于 `desktop-mts1kftk-0cc3f79078a7`。各次正常重启前公共 API 均确认活动 task/batch=0。仍是 dirty 开发态、仓内 data、旧前端 dist，不伪称 clean 真实写入身份。
- Shadow/Discovery/Formal 均未使用，未生成本次商品 snapshot/task/scope/Approval；未实际保存、发布或自动重试。后续继续完善共同来源冻结、独立动作回执、正式原生门及完整半托管字段，不能将入口定位通过称为三商品闭环。

### 23.4 引用身份、审计明细及两阶段来源投影

- 已补齐上一节发现的最小数据链：仅 Path B 的 snapshot 保留全部显式引用身份、ref_id、digest、解析值摘要和现有审计数量/明细，原样克隆 `executable=false / DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED` 等事实。缺失的历史明细保持 absent，不补空数组；Path A 原调用和形状不变。
- SAVE1 字段的既有 `source/source_ref` 与全部引用列表进入原 `payload_hash`。SAVE2 复用原解析器 tuple，来源从共享晚冻结 policy 进入 stage seal、再进入执行 payload，并受既有三层 hash 约束；不增加解析器、覆盖规则或商品独立设置。未解析 current 规则仍为 `rule.source=current`，不伪造 source_ref。
- 生产 Runner 与 dispatch loader 始终保留完整 task snapshot，不用旧纯测试省略 path/refs 的 stub 当作真实生产输入。新元数据只由新编译快照产生，历史冻结快照不会就地改写。模板逐引用贡献、被共同 fixed/set_each 覆盖的候选字段及实际 UI 套用仍未获得完整证据；没有生成 `template_apply` 或 applied=true。

```text
test_path_b_freeze_preserves_all_reference_identities_and_final_provenance:
  RED 1 failed in 0.45s -> GREEN 1 passed in 0.37s
test_path_b_audit_details_and_deferred_sources_survive_both_save_stages:
  RED 1 failed in 0.54s -> GREEN 1 passed in 0.18s
```

- 本节两个节点加 23.2 四个节点，本轮合计 6 个新增节点分别通过、skipped=0，首次通过后均封存；未重跑旧绿节点。新增来源测试的两个隔离目录也未实际创建，没有删除历史目录、真实数据或证据。
- 最终源码稳定后，公共 API 再次确认活动 task/batch=0，正常重启 Electron 加载后端：runtime `desktop-mts25hkx-7419efef37e0`、backend PID `42848`，`/health=ok`、`logged_in=true / reader_ready=true / LOGIN_READER_READY`。没有因重载而重复入口诊断或重新运行已知失败的 Inspect；仍未进入真实保存。

## 24. 批发独立验证接线与生成结果冻结冲突（2026-09-08）

### 24.1 已观察批发控件与只读职责

- 权威仓仍为 `D:\Desktop\py\dxm-auto-uikit`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty，保留继承修改。本轮没有新调用只读入口、生成、翻译、Shadow/Discovery/Formal 或真实保存。
- 统一方案 6.4.3 明确批发填写归主分区，ContentFinalize 在主分区和视频之后独立重新验证。复用既有严格字段引擎的只读操作，不调用旧 `WholesaleFiller` 中未验证 testid 或缺控件仍成功的路径，不把旧 FILL 结果改名为新批发回执。
- 从 23.3 私有报告核对到同一表单项中的成对数字控件及原生批发复选框；现以该结构和唯一性绑定起订量/折扣，中文标签仅作附加辨别。读回原始值；禁用控件仍不可写，未自动勾选或替缺失控件补值。报告中的批发未启用/数字控件禁用仍是实际执行缺口。
- Flow 增加独立只读观察：同一任务/商品/页面/会话、两次实际批发与完整 SKU 读值、启用状态、百分比单位、当前目标类目 Schema 和真实截图。原主 FILL 首次执行时才保留其实际 command 和字段结果摘要；缓存复用不改来源，也不从后续验证 command 补造原 writer。

```text
test_wholesale_observed_pair_readback_is_readonly_and_ambiguous_groups_fail:
  RED 1 failed in 0.64s (Windows command-line length limit)
  harness uses stdin instead of a long argv
  GREEN 1 passed in 0.40s, skipped=0
```

- 此节点运行实际严格引擎/观察 JavaScript 的合成 DOM，确认唯一成对控件可读、禁用时拒绝填写、重复组/错误标签拒绝、写事件为 0。不是生产 Adapter 模拟或真实商品验证；第一次绿后封存，未重跑旧节点。
- 已确认另一个跨层冲突：视频/翻译的合法结果尚无追加封存通道，原 FILL 缓存、payload 重编、scope expected hash 和最终保存回执都仍绑定动作前值。后续必须共同消费共享动作政策授权的追加结果，同时保留原 snapshot/preimage；不能只刷新缓存掩盖漂移，也不能改成单品配置。

### 24.2 独立命令、实际首写来源与业务回执

- 复用原 Runner/BrowserAgent/Adapter，增加 `BATCH_WHOLESALE_FILL → validate_editor_wholesale` 映射。命令构建时从真实任务重编冻结 defaults；只读 command 的顶层 `execution_payload_hash` 仍为 None，遵守现有协议，冻结值及 hash 保留在受绑定 params 中。
- 同一纯 validator 被 Flow、Adapter 和 ActionResult 消费：两次当前读回完全相等、批发已启用、单位为百分比、起订量/折扣/库存扣减与共同政策相等；完整 SKU 的行身份、编码、价格、库存与货值关系有效。保留实际数字控件字符串，不把缺字段、布尔值或模糊文本变成期望数值。回执只含这次四类实际字段，不冒称其它分区已经验证。
- 原主 FILL 的完整字段结果及 command 在首次真实 apply 后保存。Worker 核对批发观察与当前独立 command 的 7 项身份，Runner 再对比 `prior_results` 中唯一实际 `FILL_BASE_INFO` command、原字段结果及摘要；来源只自报哈希不够。允许真实调用后的等值 no-op，不伪造每字段都已写入。
- 同一批发回执不得由其它 FILL 捎带、覆盖已有回执或复用其它能力 grant。新动作未加入 active steps，避免视频尚未接线时以残缺顺序运行；production capability provider 与保存锁未放宽。只读验证不会产生 mutation lease/ledger，不宣称它已有写入凭据。

```text
test_wholesale_fresh_contract_rejects_missing_changed_and_reused_evidence:
  GREEN 1 passed in 0.37s, skipped=0
test_wholesale_runner_requires_actual_first_fill_and_unique_command_receipt:
  GREEN 1 passed in 0.37s, skipped=0
WHOLESALE_WIRING_AST_OK 4
```

- 本节是纯观测合同/ActionResult 与 Runner 内存收集器检查，没有构造或 mock 生产 Adapter、没有持久成功数据、真实 browser command 或商品保存。加上 24.1 共 3 个新增节点，均首次绿后封存，未重跑旧绿测；4 次命令使用的本轮隔离目录均未实际创建，没有待删临时文件。
- 运行中的 Electron/backend 保持 23.4 原实例，本轮没有重启或重新读取真实商品，不将磁盘新源码说成已加载或真实执行通过。后续先补共享动作结果的追加冻结与真实视频/翻译绑定，再完成半托管链及一次性正式流程；无需用户重复确认既有范围。

## 25. 共享动作输出归属、结果候选与 scope 规则（2026-09-08）

### 25.1 保留原输入的结果合同

- 权威仓仍是 `D:\Desktop\py\dxm-auto-uikit`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty；保留全部继承修改，没有在 C: 镜像改动或验收。本轮未调用真实业务接口、浏览器动作或重启运行时。
- 复用共享模板现有 field mapping，增加可选 `delegated_to=content_finalize.video|content_finalize.translation`；只允许 Path B 已启用的对应共同动作，不增加顶层商品配置。元数据进入原 mapping/content/snapshot/execution hash；旧四键 mapping 形状保持不变。公共模板先验证动作结构，避免非法配置在读取 enabled 时变成未处理异常。
- 输出 policy 从共同动作、明确字段归属和冻结 Schema 构建。视频只能拥有产品视频 media 字段；翻译只能修改明确标记的自然语言叶子，不能改 SKU 身份、行数/顺序、价格、库存或未知字段。两种必需输出归属必须同时存在，SAVE2 字段不能混入。
- 新增纯结果候选构造：按视频→批发→翻译核对独立 grant、时间顺序、完整字段读回和最终截图描述符；未委派字段与输入值逐项相等，视频实际 URL 与回执媒体身份一致。生成结果进入新候选，原 snapshot、preimage、resolved input 均不就地修改。批发仍是原主填写后的独立零写验证，不把其 SKU 读回当成翻译输出。
- **候选不是持久成功或保存授权**：Repository 尚未把三项实际命令/ActionResult/截图来源与候选追加绑定，主 FILL 缓存也未改成消费新结果。不能把候选摘要、自报 receipt 或临时任务附加字段当作真实动作证据。

### 25.2 共享输出的预先授权与保存阻断

- `real_dxm_write_scope.v3` 在原 v2 晚冻结 SAVE2 基础上增加 SAVE1 生成字段：保留 `preimageSha256`，另锁定 `inputSha256 / ruleSha256 / delegatedTo / freezeAt=after_content_finalize`；不提前伪造最终 `expectedSha256`，也不在生成后修改已批准 scope。普通字段仍用原 preimage/expected 双摘要。
- 同一 scope 的所有商品必须使用完全相同的输出字段、归属、顺序及共同 policy 摘要；允许真实商品原值/输入摘要不同，不允许单品替换规则。公共 Prepare 模型、服务投影和唯一 PowerShell 系统脚本均保留该精确形状；缺键、附加 expected、错误阶段、旧 schema 混用、跨商品规则漂移被拒绝。
- 这只是授权输入接线，尚未签发实际 v3 scope/Approval。生成字段的 SAVE1 结果消费尚未完成：Runner 命令创建、公共授权检查和统一 dispatch 都使用保存编译校验，遇到未持久验证的生成结果即拒绝；没有为了先保存而删除 expected 检查或刷新原值缓存。
- 共同 v1.4.0 仍是原 draft，本轮没有 Configure 新模板版本、preview/freeze/task 或重复已知失败的 Inspect。现有生产 capability 锁、完整五项要求和永久禁发布均未放宽；原运行实例未加载本轮磁盘改动。

### 25.3 新增局部检查与尚未完成的链路

```text
test_shared_field_delegation_is_explicit_and_hash_bound:
  RED 1 failed in 0.44s -> GREEN 1 passed in 0.31s
test_common_output_policy_survives_compile_without_overwriting_input_values:
  RED 1 failed in 0.45s (synthetic public payload included server-owned id)
  GREEN 1 passed in 0.32s
test_content_finalize_candidate_preserves_preimages_and_rejects_unowned_or_identity_changes:
  GREEN 1 passed in 0.38s
test_shared_generated_scope_preserves_inputs_and_rejects_per_product_rules
test_content_scope_projection_keeps_preimages_and_closes_unpersisted_save:
  GREEN 2 passed in 2.43s
```

- 五个新增节点均 skipped=0，首次绿后封存；未重跑任何旧绿节点。检查只覆盖纯合同、Pydantic 模型、源调用关系和从原脚本 AST 提取的三个纯 Prepare 校验函数；没有执行系统脚本顶层流程、数据库成功插入、生产 Adapter mock 或任何真实保存。未运行全量回归、集成测试、frontend build、desktop test、Browser QA 或交付验收。
- 下一步复用现有 `job_evidences`，绑定真实命令来源并追加结果，再贯通 SAVE1 payload/scope expected/独立读回；视频/翻译实际执行、共同引用实际应用、批发启用原值及完整半托管原生门仍需完成。不能因元数据和候选校验通过就声明生产能力已可用。
- Shadow/Discovery/Formal 均未使用，SAVE/Publish/自动重试均未发生；此轮是目标进展，不是业务验收完成，也不是等待用户重复授权。文档自检输出 `MVP_DOCS_OK: contract=1 pointers=4 links=resolved ai_notice=17 capabilities=5/5 path_b=required publish_guard=locked category_catalog=checked upstream_sources=21 hashes=locked`，`git diff --check` 通过。
- 本轮 `dxm-unit-content-*` 隔离目录未实际创建，没有待删临时文件。工作树新增行扫描的精确商品/店铺/类目数字命中为 0；同时发现 3 处继承的回放/历史店铺名文本（历史第 13 节、Runner 回放回执、回放 shop lock 提示），未冒充本轮新增或生产证据。尚未提交/推送；这些继承文本仍需在交付前脱敏审查，不宣称整个 dirty diff 已通过隐私验收。

## 26. Worker 原始来源持久化与首写血缘接线（2026-09-08）

- 权威仓仍为 `D:\Desktop\py\dxm-auto-uikit`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty，保留继承修改。复用原 Worker 产物和 `job_evidences`，没有增加第二套日志、表或 Runner；本轮没有真实业务接口/浏览器调用或重启。
- Worker 新只读加载器从当前 DATA_DIR 推导原 request/result 路径，核对命令完整载荷、传输身份、当前 session 和 ActionResult，再返回文件 size/SHA-256。调用者不可提供另一条证据路径；原文件不改写、不重新签发，内层业务失败不会因外层传输完成而变成成功。
- 生产 Runner 在实际 Worker 返回后、兼容结果消费前调用 Repository。主 FILL 与独立批发追加完整命令、实际 ActionResult、文件来源、快照/scope/payload/行权威摘要；同事务核对当前 running 状态、消费 scope、原冻结字段和 target。重复命令/状态拒绝；实际失败可追加且保持失败，不插入 CanonicalReceipt、mutation ledger 或修改任务成功状态。
- 成功来源额外检查当前截图真实文件；批发成功必须重新读回同 job 的唯一成功首 FILL 文件。Runner 内存与 Repository 共用最小首写绑定校验，比较 command、session、原填写值及其摘要，不用后续观察替代原 writer。

```text
test_browser_action_source_reads_actual_worker_files_without_resigning_them:
  RED 1 failed in 0.50s -> GREEN 1 passed in 0.39s
test_editor_attempt_is_persisted_once_with_worker_and_snapshot_sources:
  RED 1 failed in 0.98s -> GREEN 1 passed in 0.99s
test_wholesale_memory_and_persistence_use_the_same_first_writer_binding:
  GREEN 1 passed in 0.40s
```

- 三个新增节点均 skipped=0，首次绿后封存，未重跑旧绿节点。它们覆盖原产物只读及漂移拒绝、隔离 SQLite 中失败来源只追加一次、共享首写校验；不使用生产 Adapter mock，不写成功记录，不构成真实 FILL/批发成功或三商品保存证明。
- 仅删除本轮精确定位的 3 个可重建 pytest 子目录，其中是合成 request/result 与隔离数据库；没有删除历史目录、真实业务数据或现场证据。命令设置的 `dxm-unit-worker-source-* / dxm-unit-editor-journal-* / dxm-unit-wholesale-source-*` 根目录未实际创建。
- 后续仍需绑定视频/翻译真实命令来源、持久封存最终生成输出，并让 SAVE1 payload、授权字段期望、实际独立读回共同消费；共同引用应用、批发启用和完整半托管链尚未现场通过。保存锁未放宽，旧运行实例未加载本轮源码，Shadow/Discovery/Formal 与实际 SAVE/Publish/自动重试仍为 0。

### 26.1 当前公开组件核对与精确控件观察

- 无 Cookie 只读获取店小秘公开前端入口及其实际引用的静态 JS；未执行下载的代码、未请求其中业务接口。第一笔请求被本机网络沙箱拒绝，明确提升为公开静态读取后成功；这不是店小秘业务失败，也未消耗真实流程额度。
- 路由 `smtProductEdit` 指向当前编辑组件，真实 `TranslateBtnNew` 在 `.panel-language-list > .panel-language-item` 点击时派发翻译；`普通翻译 / 中文 → 英文 / 五项内容` 由该面板声明。不存在旧候选 executor 假设的确认按钮。主编辑调用注册字段的翻译处理器；底层普通翻译有服务失败后切换/重试分支，正式接线必须观察并阻断不确定后的继续派发，不能只看“翻译完成”提示或忽略未变字段。
- 当前视频弹层先取前 8 张图片，原生默认自然转场/无背景音乐，提交 `transToVideo` 得到任务编号，再由原生 `checkProcess` 轮询；点击“投放到产品视频”才把结果写回页面。默认值只是上游行为事实，尚未被本地共享模板显式授权，不能据此增加单品配置或直接调用接口。进度组件在结束且 `data` 非空时可能显示投放按钮，故按钮可见本身不证明生成成功；还需独立核对当次任务业务结果和实际媒体身份。
- 复用现有 `inspect_editor_readonly`，新增只读结构化观察，覆盖此前通用 input/button 采集遗漏的语言行、类型原生 radio、范围说明、生成按钮、额度文本、图片实际加载值、转场和音乐选中态。重复浮层不选择第一项；缺失、禁用、未加载和未知值原样返回。新数据仅留私有报告 `contentSurface`，不扩大公共摘要，不改总报告 `ok`、guard、`executionAllowed=false / capabilityCertified=false`。
- 该观察接线尚未通过当前运行实例执行：本轮没有新浏览器动作、登录会话检查、重启、Configure 或 Inspect；旧报告也没有被改写成含新字段。旧生成/翻译候选 executor 未被接入生产，完整实际动作仍待实现。

```text
test_content_surface_reads_real_control_shapes_without_clicks_or_certification:
  GREEN 1 passed in 0.65s, skipped=0
```

- 本节点执行实际观察 JavaScript 的合成 DOM，验证只读字段提取与拒绝选择重复浮层；不运行浏览器、不构造生产 Adapter、不证明现场 selector 已通过。与本节此前 3 节点合计 4 个新增节点，各自首次绿后封存，未重复旧绿测。此前本轮文档自检已输出 `MVP_DOCS_OK`，此补充在收尾重新执行规定文档检查。
- 临时公开资源缓存只用于此轮源码核对，不进入 Git。入口资源基址为 `https://s13.dianxiaomi.com/dxm-web/2026-09/assets/`；以下为实际下载元数据，**不是业务成功证据**：

| 公开组件文件 | size | SHA-256 |
| --- | ---: | --- |
| `index-DZIZdaK7.js` | 1478089 | `2438F643E9E3C919E97395BA01514E39CD6269823A83978EEB76907F78383831` |
| `index-CPttqsQH.js` | 252764 | `6468D84F59DE51D2B8074C167C74E2CA7EC61D1941D0139FCE2FF60DDB45391F` |
| `TranslateBtnNew-DuD57twf.js` | 6960 | `510DC66490D41ACD7C8806FF493123929473A5EB8F509977F6FBC428756383A2` |
| `advancedTranslate-CrBFB0bv.js` | 16184 | `8B7108BFEC548028935714774B06A1A1F6436156764D156DAD6C73DBD233D333` |
| `ImgToVideoModal-Cn4d-6zD.js` | 9426 | `25D36FFACB573B45F3D94EB031335BABDF5DF7FA1D870F657C2DC1956ACB5FED` |
| `index-DxrHWTJK.js` | 19043 | `F94C2FAC920C0A542960F419C9BF1BFC4ADEDD8C8FFA96218A2F5D23EE3B1637` |
| `index-BA-XYm54.js` | 5801 | `D0D279941260EACE1E2852E157E84784560350674C5B174B23BBA1B6773031C4` |

- 收尾已核实并删除本轮唯一临时公开资源目录中的 11 个 JS 缓存文件（共 1821317 bytes，可由公开地址重新获取）；目录解析路径、文件白名单及非重解析属性均检查通过，没有删除真实运行数据/截图/报告。新观察单测使用的隔离根目录也未实际创建。
- 提交扫描覆盖 tracked 新增行及 untracked 文本：原 tracked 3 处店铺名仍在；另有继承的 `app/backend/src/execution/closed_loop_replay_adapter.py` 2 处、`app/backend/tests/test_path_b_closed_loop.py` 3 处、`scripts/run-path-b-template-closed-loop.ps1` 2 处店铺名。该七处不属于本轮新增，精确数字身份均未命中；旧测试/脚本不在当前修改白名单，不擅自删改。未提交/推送，不能把只扫 tracked diff 的旧结论当作全工作树隐私通过。
- 此补充前的完整文档检查已再次返回 `MVP_DOCS_OK: contract=1 pointers=4 links=resolved ai_notice=17 capabilities=5/5 path_b=required publish_guard=locked category_catalog=checked upstream_sources=21 hashes=locked`，`git diff --check` 通过。本次最后的清理/扫描事实补充后，仍按仓规运行文档自检；不重复已绿业务单测。

## 27. 内容动作派发接线与运营规则核对（2026-09-08）

- 补记前一开发轮：视频提交、视频投放和翻译三个精确命令已接入既有 BrowserAgent 命令、公共批准复核、Runner 命令构造和统一 mutation ledger；各动作标识与六个 SAVE lease 分离，重复派发拒绝，派发后中断保留 UNKNOWN。首商品 discovery 只允许该商品当前步骤的精确内容动作，未放行其它商品或 SAVE2。
- 修复实际编译器快照与派发复算不一致：共同 `plan_snapshot_sha256` 沿用编译器原有派生元数据排除规则，替换三个不一致的权威复算点；完整存储快照/命令一致性检查继续保留。
- 前轮新增节点 `test_content_commands_share_scope_authority_and_keep_save_leases_separate` 经失败定位后首次通过：`1 passed in 1.28s, skipped=0`。隔离 SQLite 检查实际命令构造、权限/队列/身份复核、分离标识、重复拒绝和中断 UNKNOWN；没有生产 Adapter mock、真实浏览器动作或 SAVE 成功记录。本轮没有重跑该绿测。
- 仍缺生产 Flow/Adapter 的实际视频/翻译方法、成功 ActionResult 与实际结果追加封存、主阶段完整步序及半托管闭环；命令和 ledger 接线不能算业务动作已实现。未放宽生产 capability 或生成字段保存门，未运行 Shadow/Discovery/Formal。
- 本轮公共 GET 实测 `/health` 在线，原桌面 runtime、dirty HEAD 与仓内 DATA_DIR 未变，没有重启。公共模板列表及单模板读回确认共同 v1.4.0 为最新 Path B 草稿；原四项引用列表仍为 available，但列表只有摘要，没有返回具体字段值，不能用它证明半托管价格或视频规则已配置。
- 对照运营文档 §4/§6–§9、统一方案 §6.4 和当前公共模板：已确定逐商品视频→批发验证→翻译→双保存顺序；模板明确普通中译英及完整五项范围。视频尚缺源图/转场/音乐规则，不能借用“产品图片前六张”或上游默认值。半托管已有全选实际可用国家意图，不要求用户重复裁决；价格规则仍须追溯引用/配置。只向用户确认真正未规定的共同业务规则，不增加单品配置。

## 28. 原生翻译控件准备（2026-09-08）

- 视频共同源图/转场/音乐规则仍待用户回复，没有擅自填写模板默认值；继续处理不依赖该选择的普通中译英入口。只读核对当前公开 `TranslateBtnNew-DuD57twf.js`、其配置与主编辑实际 import，确认类型 radio 原生值为 1、语言行点击直接执行，五项范围为标题/自定义属性/自定义名称/PC端描述/无线端描述。
- 当前主编辑实际使用 `advancedTranslate-CrBFB0bv.js` 执行翻译，`advancedTranslate-i7-t4onH.js` 是面板/余额/注册字段依赖；两者职责不同，不能把后者没有请求代码当作接口消失。普通中译英优先原生 freeBatchTranslate，失败存在其它服务与重试分支；明确业务成功和结果覆盖仍待生产观察/约束，未直调这些接口。
- 在既有 `translator.py` 增加原生准备函数，复用已有精确入口和只读 surface 采集；先校验共同配置，打开面板、必要时明确选择普通翻译，再核对唯一语言行和完整范围。只准备控件，不点击语言行、不生成翻译回执、不读取私有 Vue 状态、不调用旧假 testid/自动关闭即成功路径。
- 函数尚未接入生产 Flow/Adapter/active steps；后续必须与动作时页面身份及字段连续性检查、统一派发、实际网络业务结果、逐字段读回一起接入，不能以此函数可用代替完整翻译。未运行真实浏览器准备动作，未重启或更改共享模板。
- 新增节点 `test_native_translation_preparation_uses_shared_scope_and_never_dispatches`：`RED 1 failed in 0.70s`（实现缺失）→ `GREEN 1 passed in 0.62s, skipped=0`。只使用 Python 控件替身验证准备步骤及不派发语言行，无生产 Adapter mock、无浏览器、无保存成功记录；首次绿后封存，未重跑旧绿节点。
- 本轮公开源码仅驻留命令内存，无下载文件；新节点不使用临时数据库夹具。Shadow/Discovery/Formal、实际生成/翻译/SAVE/Publish 均未执行。前轮三个已核实的隔离测试数据库及其空子目录已清理，可重建；运行数据与真实证据未删除。

## 29. 原生翻译执行与结果合同接线（2026-09-08）

- 权威仓复核为 `D:\Desktop\py\dxm-auto-uikit`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty，保留继承修改。继续使用现有 Flow、Adapter、Worker 与 ActionResult；未创建第二个 Runner，未重启桌面运行实例，未修改共享模板或访问真实业务接口。
- `NativeTranslationNetwork` 只观察浏览器原生请求，不主动调用翻译接口。语言点击在原统一授权派发内执行一次；请求须属于当前页面、普通中译英、当前被授权自然语言输入。逐个实际请求绑定原请求/回包摘要及业务结果；重复内容的不同原生请求分别记录。服务失败、未证明结果、跨范围输入、原生服务切换和封存后的延迟翻译均拒绝，后续写派发也检查已记录失败。
- 翻译字段结果必须能由当次实际服务输出解释，未委派字段、SKU 身份、数量、顺序、价格等不得改变；前后字段覆盖、页面/会话/店铺、原冻结输入与实际批发前序必须连续。生产方法读取页面字段、准备并复核原生控件、授权点击语言行、等待业务结果并再次读回、采集截图；不是英文即成功，也不是关闭面板或完成提示即成功。
- Worker 与 Adapter 的 `BATCH_TRANSLATE_EXECUTE → translate_editor_content` 接线及 ActionResult 新合同已落代码；翻译结果回执使用本次实际 mutation id，不复用六个 SAVE lease。观察与回执还需由 Repository 对原 Worker 文件、ledger 和实际前序逐项持久绑定：当前 `persist_path_b_editor_source` 及 Runner 调用范围仍只有首 FILL/批发，未将翻译列为已持久成功。
- **仍不可执行完整流程**：视频真实生成/投放、翻译来源持久化、最终输出冻结与 SAVE1 消费、完整半托管尚未闭合，active steps/capability 未释放。全部英文输入导致原生零请求、描述 HTML 原生序列化与当前严格读回的兼容性、原生异步处理完成边界均未现场证明；不得靠放宽成功条件解决。视频源图/转场/音乐共同规则仍待用户明确，半托管国家策略已明确，不重复询问。

```text
test_native_translation_network_binds_responses_and_blocks_late_fallbacks:
  RED 1 failed in 0.81s -> GREEN 1 passed in 0.58s
test_native_translation_readback_requires_provider_values_and_preserves_structure:
  GREEN 1 passed in 1.00s
test_native_translation_observation_and_action_contract_bind_the_actual_dispatch:
  GREEN 1 passed in 0.76s
```

- 三个新增局部节点均 skipped=0，首次绿后封存，没有重跑旧绿节点。检查采用合成网络/字段数据和源调用关系，不实例化或 mock 生产 Adapter，不调用浏览器，不写成功数据库记录；源接线检查不等于生产方法已在真页面跑通。没有运行全量回归、集成测试、前端构建或交付验收。
- Shadow/Discovery/Formal 均未使用，实际生成/翻译/SAVE/Publish/自动重试均未执行。本节是源码进展与明确缺口，不是业务验收完成；原运行实例没有加载这些新改动。

## 30. 翻译实际来源持久接线与点击返回修复（2026-09-08）

- 开工复核权威仓与 HEAD 未变：`D:\Desktop\py\dxm-auto-uikit`、`main@7f5b87b9779274f25dac773e201dfdb9d9a8dc82` dirty，保留继承修改。上一轮新增接线及检查属于实际进展，不是等待真实进程或无进展；本轮继续安全实现，未重启旧桌面实例或访问真实业务接口。
- 实际调用链审查发现新翻译 callback 在原生 click 正常返回后没有返回 Worker 要求的派发确认，会被统一 Worker 判为 UNKNOWN。已修为仅在 click 正常返回后返回 `dispatched=true`，click 异常继续抛出；该标记只证明派发操作已返回，不证明翻译业务成功，业务回包与字段读回要求不变。
- 复用现有 `job_evidences`，将实际翻译 Worker 原始 request/result 来源纳入 `persist_path_b_editor_source`。成功结果必须匹配同 job 唯一批发前序、原文件摘要、原输入与目标，以及唯一实际 `DISPATCHED` ledger 行、完整 command、snapshot 行权威、现场身份、时间顺序、冻结 dispatch authority 和真实截图。失败结果仍按失败追加；不修改原 snapshot，不新增表，不写 CanonicalReceipt 或伪造成功 ledger。
- Runner 原回执收集器进一步核对翻译 command、实际批发前序及持久来源摘要，拒绝捎带、覆盖或复用其它能力 grant。翻译来源持久验证失败会尝试将其原派发行标为 UNKNOWN，抛出 UNKNOWN 停止，不因持久化失败再次执行翻译。

```text
test_translation_native_click_returns_worker_dispatch_confirmation_only_after_click:
  RED 1 failed in 0.59s (callback returned None)
  GREEN 1 passed in 0.28s
test_translation_persistence_sources_and_runner_reject_reuse_and_drift:
  RED 1 failed in 0.63s (new check missing ProductEditContext import)
  GREEN 1 passed in 0.37s
```

- 两个新增节点均 skipped=0，首次绿后封存，未运行任何旧绿节点。首节点从实际生产源码提取内部点击 callback 检查原生 None 返回和异常；第二节点使用合成对象检查前序/账本绑定与真实 Runner 的纯收集器，并检查 Repository 调用接线。无生产 Adapter mock、无真实浏览器、无成功数据库记录；这些不是数据库成功分支或真页面的端到端验收。
- **仍未闭合**：视频真实生成/投放与来源、最终完整字段结果封存和 SAVE1 编译/授权/读回消费、完整半托管流程。翻译的全英文零请求、原生异步完成与 HTML 序列化语义仍待解决，不因来源已接线就宣称翻译已现场通过。视频共同源图/转场/音乐仍待用户回复，未代填默认值或要求重复范围授权。
- active steps/capability 不释放；Shadow/Discovery/Formal 均未使用，实际生成/翻译/SAVE/Publish/自动重试均为 0。没有创建临时数据库、下载资源或修改真实数据；本轮仅完成上述源码接线与局部验证。
