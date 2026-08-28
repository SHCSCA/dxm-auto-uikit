> 由 OpenAI GPT（Codex）AI 生成/维护。

# 当前进度

## 1. 当前裁定

**日期：2026-08-28。状态：`0.3.0-dev` · `E3_OPEN / BLOCKED`。不是 `MVP_READY`，不是 `PROD_READY`。**

- 完整商品成功主路径固定为 Path B：普通编辑、视频、批发、翻译、半托管和 rollback preparation 对每件商品全部 `REQUIRED / ALWAYS_ON`，不得跳过、关闭或降级 Path A。
- 半托管入口分成两个动作：点击顶部精确“保存”出现提示 Modal 后，再精确点击“编辑半托管信息”，由店小秘自身执行原生资格检查；只有店小秘放行且实际 SAVE1 已验证并绑定同一入口握手，才允许自动化中间“继续发布”进入冻结的 `editFromSmt`。系统不得主动调用 `verifyPopChoiceShop` 或用店铺类型/类目/catalog/历史结果预判资格。提示 Modal 不足以证明 SAVE1 已完成；当前尚未实证哪个点击触发 SAVE1，安全合同把两者都视为 `MAY_DISPATCH_SAVE1`，但两组事实只要已验证且因果同源，不要求还原墙钟全序。
- Path A 只保留为诊断/canary，不能代表产品完成。
- 当前代码仍未闭合上述完整生产链，因此维持 `BLOCKED`；本轮只收敛合同、上游知识和类目数据，没有操作真实浏览器、保存或发布。

## 2. 当前身份与范围

| 项 | 值 |
|---|---|
| 权威 checkout | `D:\Desktop\py\dxm-auto-uikit` |
| 分支 | `fix/dxm-two-stage-runtime-truth` |
| HEAD | `cbb88c1eb22e5df58b05075f6aa3dde044856099` |
| 2026-08-25 文档工作流开始状态数 | `617` |
| 上游 | `D:\Desktop\py\DXM-TX`，始终只读 |
| backend/frontend/desktop | `0.3.0` |
| 根 `package.json` | `0.3.0`，与 backend/frontend/desktop 一致 |
| 当前 0.3.0 portable | 不存在 |

工作树原有大量 tracked/untracked/删除项，均属于既有工作；本轮不清理、不恢复、不 commit、不 push。

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

- 2026-08-28 使用隔离 `DXM_DATA_DIR` 的完整 backend L0：`2344 passed in 782.38s (0:13:02)`，`0 failed / 0 skipped`。
- 当前 frontend 标准 build：Node `34/34`、Chromium `11/11`、TypeScript 与 Vite 68 modules 通过；desktop `94/94` 通过。
- 以上证明当前工作树工程门禁，不证明真实 Path B 双保存、0.3.0 portable 或 `MVP_READY / PROD_READY`。
- 当前产品阻断、包身份和真机证据见 [BLOCKED](BLOCKED.md)。

## 7. 下一入口

1. 让 CategoryCatalog 进入后端/portable 的版本化资源与 runtime lookup，并冻结 node/catalog/capability identities。
2. 将视频、批发、翻译、rollback preparation 和 Path B 两阶段写入/读回接入同一 frozen execution payload、Runner、BrowserAgent、ledger 和 receipt。
3. 形成可复验 Git 固定点，从该点重跑门禁并构建同源 0.3.0 portable。
4. 再取得当次真实写入授权，从同一工作台、会话和包完成三商品完整 Path B 两阶段只保存；逐阶段三铁证，最终发布为 0。

## 8. 2026-08-26 文档阶段记录（历史）

以下只记录 v1.1.2 文档收敛阶段，不覆盖 2026-08-28 的代码修复与 Git 交付：

- DXM-TX 修改：0。
- 真实浏览器动作 / 保存 / 最终发布：0 / 0 / 0。
- app/** 业务代码修改：0。
- commit / push：0 / 0。
