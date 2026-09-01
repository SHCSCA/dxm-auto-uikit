> 由 OpenAI GPT（Codex）AI 生成/维护。

# 当前进度

## 1. 当前裁定

**日期：2026-08-28。状态：`0.3.0-dev` · `E3_OPEN / BLOCKED`。不是 `MVP_READY`，不是 `PROD_READY`。**

- 完整商品成功主路径固定为 Path B：普通编辑、视频、批发、翻译、半托管和 rollback preparation 对每件商品全部 `REQUIRED / ALWAYS_ON`，不得跳过、关闭或降级 Path A。
- 半托管入口分成两个动作：点击顶部精确“保存”出现提示 Modal 后，再精确点击“编辑半托管信息”，由店小秘自身执行原生资格检查；只有店小秘放行且实际 SAVE1 已验证并绑定同一入口握手，才允许自动化中间“继续发布”进入冻结的 `editFromSmt`。系统不得主动调用 `verifyPopChoiceShop` 或用店铺类型/类目/catalog/历史结果预判资格。提示 Modal 不足以证明 SAVE1 已完成；当前尚未实证哪个点击触发 SAVE1，安全合同把两者都视为 `MAY_DISPATCH_SAVE1`，但两组事实只要已验证且因果同源，不要求还原墙钟全序。
- Path A 只保留为诊断/canary，不能代表产品完成。
- 当前代码已形成远端源码固定点并通过完整工程门禁，但仍未闭合上述完整生产链，因此维持 `BLOCKED`；本轮合并与验收没有操作真实浏览器、保存或发布。

## 2. 当前身份与范围

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
