> 由 OpenAI GPT（Codex）AI 生成/维护。

# 待裁决清单（BLOCKED）

用户已裁决产品范围和类目迁移权限，当前没有待问的产品选择；以下均是实现、证据或交付门禁。任何一项存在时均不得宣称 `MVP_READY / PROD_READY`。

## 2026-09-01 real Path B system-flow 当前裁定

**结论：`INTERNAL NON_READY / BLOCKED`。公开系统流、Discovery 原子边界、Discovery→Formal fresh lineage、逐 SAVE 权威账本与验收重建已提交并推送到 `main@90e8233`；但生产 Path B 的五项 capability 与 14 个 section producer/executor 尚未全部有可复核的真实 UI 事实。当前也没有可用的当次真实 scope/经实时复核的持久会话，因此没有运行 Shadow、Discovery、Formal，没有打开真实商品编辑页；真实 mutation / publish / auto retry 均为 0。**

当前阻断证据：

- `DXM_REAL_SAVE_SCOPE_FILE` 未配置且没有可用的当次真实 scope。实现提交 `90e8233` 已由 `e6069d0..90e8233` 推送到 `origin/main`；任何后续真实 scope 仍必须绑定执行时再次确认的 clean HEAD/worktree、Git 外 `DXM_DATA_DIR`、有效持久 browser session、fresh Reader/account/L2 与当次批准，不能用旧 scope 或历史会话冒充。
- 分支审计确认 `feature/dxm-production-two-stage@42de6d5` 是 `main` 的祖先，`main...feature/dxm-production-two-stage = 78/0`，其内容已由既有合并提交 `af01446` 纳入主线；本轮没有制造无内容 merge commit。
- 公开 FastAPI 已具备 hash-only Prepare、同 task 单 active scope、原子 consume-and-start、Shadow、一次性 Discovery、按 key 恢复、fresh Formal 与 acceptance export。冻结 snapshot 现按同源 `real_write_stage_fields.SAVE1/SAVE2` 精确分区全部字段，并冻结两阶段 preimage/expected；调用方自报、漏字段、多字段或漂移仍会在任何 CAS/写入前拒绝。
- Discovery 现只为首商品创建一个复合 `FIRST_SAVE_INTENT` command/lease/ledger/native-handshake，执行一次 SAVE1，独立 VERIFY 未发布后在同一事务封存 receipt、停止 task 并令 scope 进入 `discovery_sealed`；任何派发后不确定性进入 `UNKNOWN`，不得重试、不得进入 SAVE2 或下一商品。
- Formal 必须在 sealed Discovery 之后重新完成 fresh Reader → preview/freeze → 新 snapshot/task → 新 formal scope → 新 Approval，并绑定 predecessor scope 与 `discoveryReceiptSha256`。仓储层在任何 CAS 前复验新 ID/hash、同 account/shop/三商品顺序、时间顺序，以及 Discovery after 值与 Formal 首商品 SAVE1 preimage 精确一致。
- 生产 adapter/Runner 已具备 capability/section receipt 的严格校验与增量消费链，FIRST_SAVE_INTENT/SAVE 的 network、页面成功态、逐字段读回、截图和独立未发布证据也有 fail-closed 合同；每次 Formal SAVE 只有在独立 VERIFY 后才允许持久化 stage CanonicalReceipt。Formal 精确要求 3 个商品 × SAVE1/SAVE2 = 6 份独立 command/lease/receipt、6 次物理 mutation、30 个唯一 leaf proof；Discovery 固定为 5 个 leaf proof，且必须与 Formal 完全分账、不得复用。
- 仍未闭合的生产事实不能由合同或文案存在替代：`video`、`translation`、`wholesale` 没有真实动作与 post-readback；`semiManaged` 没有首写前只读 capability probe；`rollbackPreparation` 的真实 preimage 读取时序晚于首写前 capability guard。`dxm_info`、`regional_pricing`、`other_info`、`semi_countries` 等 section 也缺精确 field-to-section 或复杂控件 post-readback；正式 frozen payload 仍会绕开部分 action-specific proof envelope。当前 capability provider 因此对五项逐项返回稳定的 `PRODUCTION_*_NOT_BOUND`，在任何真实写前停止。
- 现有 UI 流程还有多处历史矩形中心/原生坐标点击。真实 SAVE 已收紧为派发前/授权内/实际点击前三次核对唯一精确语义 Playwright 控件并只走 `locator.click()`，网络监听也不再依赖矩形；弹窗 Escape、矩形中心和 DOM remove/hide fallback 已从可达路径禁用。但其余 Path B 所经动作没有足够现场 DOM 事实可安全批量替换；禁止用猜测 selector 或坐标 fallback 补齐，这些事实未完成 discovery 前正式 Path B 必须保持不可达。
- acceptance export 与报告生成器按完整 campaign 复验 1 次 Discovery + 6 次 Formal、fresh authority、跨阶段 command/lease/proof 不复用、时间顺序、零发布/UNKNOWN/自动重试。任何缺证仍 fail-closed，不能靠旧 aggregate receipt、mock、HTML、手工截图或 hash 投影补齐。
- 全局 `RELEASED_PLAN_EXECUTION_PATHS = frozenset({"A"})` 保持不变；本轮实现只是受一次性真实 scope 驱动的窄系统验收通道，不把 Path B 解锁为普通生产运行能力。

唯一聚焦测试仍只有已封存的 `22 passed in 3.81s`，exit 0、skipped 0；继续阶段没有重跑 pytest。它只证明被测合同，不证明当前真实店铺、真实页面、持久会话或 1+6 次业务验收已经发生。

**唯一下一步：以 `90e8233` 为当前静态基线，先在不写入的 headed Playwright Reader/discovery 中逐项取得并审阅上述五项 capability、缺失 section、复杂控件及非坐标语义控件的真实 DOM/readback 事实；据此补齐 producer/executor、重新审阅并形成新的 clean HEAD。之后才可在 Git 工作树外准备 data dir、有效持久会话和 fresh Reader/account/L2，由操作员签发当次 scope/ApprovalFile，严格按 Prepare → Shadow → Discovery → fresh Prepare → Formal 各自的一次性额度运行。任一证据缺失或 UNKNOWN 立即停止，不得自动重试。**

## P1 · 完整商品主链尚未接入生产

### B-01 · 五项 ALWAYS_ON 未贯穿同一执行链

- 视频、翻译、批发、半托管和 rollback preparation 已固定为每件商品必经，但现有实现仍以类、配置、状态或局部测试为主，多处真实页面动作和持久证据未闭合。
- 主编辑页可观察能力不支持、缺控件、缺稳定 binding 或缺读回时，必须在主页面首写前 fail-closed；半托管资格不得由本系统预判，主保存意图 Modal 中点击“编辑半托管信息”时只接受店小秘原生门裁决。明确拒绝或结果不确定均停批，不能跳过、空操作或降级 Path A。
- 合并时已将冻结 product ID 直达编辑页的 loading/overlay 路径改为只读检查，持续 loading、可见 blocker 与身份不明均 fail-closed；但 `DxmLoginFlow._dismiss_blocking_modals` 的 legacy fallback 仍包含矩形中心点击、泛化 Escape 与 `_remove_stuck_notice_modal` DOM/遮罩删除。它不能进入生产 Path B，必须改成精确可见 close binding；无法安全关闭时保持 `blocked_pre_write`。
- 关闭条件：每项贯穿 UI → API → snapshot → frozen execution payload → Runner → 正式 BrowserAgent/DxmWorkflowAdapter → 精确 readback → receipt，并覆盖失败与 UNKNOWN 反例。

### B-02 · Path B 两阶段保存、原生门时序与中间转换未闭环（真实写前 P0）

- 产品完整成功必须执行主保存意图、精确 `OPEN_SEMI_MANAGED_EDITOR`、店小秘原生资格门、实际主编辑 SAVE、必要时的 `SEMI_MANAGED_CONTINUE_TRANSITION`、`editFromSmt` 填写与第二次 SAVE。
- 当前运营证据写明“点保存后出现半托管提示，取消可中止本次保存”，因此不能证明 SAVE1 三铁证一定先于 `OPEN_SEMI_MANAGED_EDITOR`。在取得同一可见会话的真实 network/page/mutation-ledger 时间线前，任何实现都不得硬编码该先后；提示 Modal 本身不算 SAVE1 证据。
- 原生门后是否可能不经过已实证中间 Modal 而直接落到正式 `editFromSmt` 仍缺版本化真实证据；当前状态必须是 `DISABLED_UNTIL_OBSERVED_EVIDENCE_VERSION`。首次观察只收集脱敏 Evidence Pack 并停批，不得现场启用候选分支。
- 目标授权边界已保守冻结：顶部“保存”是最早可能触发 SAVE 的动作，必须在其前消费唯一 FIRST_SAVE lease 并开启一个多步 ledger command；后续 `OPEN_SEMI_MANAGED_EDITOR` 另取 action grant，同时复核同一 active handshake/FIRST_SAVE command，phase 只允许 `IN_FLIGHT | SAVE_VERIFIED_AWAITING_GATE`，禁止第二张 SAVE lease。真实请求究竟由哪个 UI 步骤触发仍属于本项待取证事实。
- 系统不得主动调用 `verifyPopChoiceShop`，不得用 shop type/类目/catalog/历史结果推断资格。中间“继续发布”只能在原生门明确放行、主保存意图因果链、特定 Modal 身份、目标页、task/job/snapshot/action grant/ledger 精确绑定时自动化；不能成为泛化 publish 白名单。
- 中间转换前的 join 固定为 `first_save_verified AND semi_entry_gate_admitted AND same_entry_handshake_causally_bound`；第二页首写再要求 `semi_page_bound`。明确拒绝时，SAVE1 未派发与 SAVE1 已验证必须形成不同 outcome；SAVE1 最终事实、门结果或因果绑定不确定只能 UNKNOWN。两组事实均已同源验证时，不因无法还原墙钟全序而误判 UNKNOWN。
- 两次 SAVE 分别需要业务成功回包、页面成功态、独立未发布证明；最终发布动作永久禁止。
- 关闭条件：先取得主保存意图、Modal、`OPEN_SEMI_MANAGED_EDITOR`、全部真实 SAVE1 request 和原生门 outcome 的脱敏同源事件与因果绑定证据；正式 Adapter 再覆盖 admitted/rejected/unknown、拒绝时主编辑是否已保存、两个独立入口 action kind、单一多步 FIRST_SAVE command/lease、逐 request identity/hash/causal action/幂等判定、入口 action ledger、可选转换、SAVE2、两段 ActionResult/receipt、崩溃 UNKNOWN 和真实三商品证据。

### B-03 · 回滚安全还不是生产合同

- 每件商品必须在首写前持久化字段 preimage、页面/类目/Schema 身份、恢复顺序和可恢复性检查。
- 真正 restore 只允许在当前 page stage 尚未派发会提交该阶段页面变化的外部 mutation、恢复身份仍一致且 preimage 完整的失败中逆序执行；已验证 SAVE1 不阻止恢复尚未派发 SAVE2 的半托管页本地变化。
- 视频生成、保存或中间转换已经派发后，不得自动再保存作补偿；未知结果必须令 `execution_state=unknown` 且 `manual_review_required=true`。

## P1 · 类目目录与真实页面尚未贯通

### B-04 · CategoryCatalog 尚未进入 runtime/package

- 13,216 节点的规范 catalog 已同步到根 `resources/dxm/category-catalog`，但当前 Electron 打包规则未证明包含该资源，后端也未形成唯一 lookup/漂移 API。
- 关闭条件：定义 package 资源路径、加载失败 reason code、catalog hash/版本 API、portable smoke，并从方案到 snapshot 冻结 `nodeIdentitySha256` 与 `capabilitiesSha256`。

### B-05 · 动态类目与切类目序列仍缺真实闭环

- 当前前端仍可能固定三层；上游 `level` 不可信，只有 `isleaf=1 && executableLeaf=true` 可冻结。
- 12 个祖先链冲突叶子必须隔离；4 个无观测子节点的非叶不能推测升级；显示路径存在一对多，最终身份必须为 categoryId。
- DXM-TX 尚未证明 switch-category 完整请求时序、旧字段失效和非空 child 正向链。
- 关闭条件：动态任意深度 UI、当前会话 `getById`/祖先链/Schema 水合、切换后首写前复核及脱敏真实夹具。

## P1 · 当前代码与交付证据

### B-06 · 完整 L0 已全绿（2026-08-28 关闭）

- 使用隔离 `DXM_DATA_DIR` 对 feature/main 合并源码树运行完整后端门禁：首轮如实为 `49 failed / 1760 passed`；修复全部失败后第二轮为 `1809 passed in 574.80s (0:09:34)`，exit 0，`0 failed / 0 skipped`。
- 合并前 feature 的历史基线为 `2344 passed`；当前收集数减少来自旧 claim/two-stage 运行面和对应测试按 main 合同删除，不是 skip、阈值放宽或隐藏失败。
- 本项不再是当前 blocker；该证据绑定 `7bb2ad7` / `af01446` 源码树，不能替代 B-01/B-02 生产接线、portable 或 B-08 真实三商品验收。

### B-07 · 远端源码固定点已关闭；0.3.0 portable 仍不可复验

- feature 固定点 `7bb2ad781e5ee4bf53f2ad5ab38339b4da4dd7f0` 已推送至 `origin/fix/dxm-two-stage-runtime-truth`，main 非快进合并固定点 `af01446fbc45a4b8117202a8305a24685db67552` 已进入并推送至 `origin/main` 历史；核心源码、测试、合同与资源已有远端可复验固定点。
- backend/frontend/desktop 与根 package 已统一为 0.3.0，但仍不存在从 `af01446` 构建并通过隔离 user-data/package identity smoke 的同源 0.3.0 portable。
- 关闭条件：仅剩 portable 构建、manifest/hash、隔离 user-data 和 package smoke；不得把远端源码固定点等同于可交付安装包。

### B-08 · 真实三商品完整 Path B 未验收

- 当前没有同一 UI、同一可见会话、同一包完成 `shops → products ≥3 → preview/freeze → 批准 → 五项必经 → 主保存意图/店小秘原生门/实际 SAVE1 同源取证 → editFromSmt → SAVE2` 的证据。
- 关闭条件：B-01 至 B-07 关闭后，另取当次真实写入授权；逐商品、逐保存阶段收集三铁证和独立最终未发布证明。任一 UNKNOWN 立即停批且不自动重试。

### B-09 · E4 四键缺完整真机 DoD

- 开始、暂停、继续、停止已有工程实现，但未在完整 Path B 三商品任务上证明暂停不推进、继续不重做、停止不再派发、在途不确定归 UNKNOWN，以及 UI/API/SQLite/报告同源。

## P2 · 上游事实仍有限

### B-10 · 视频、翻译、批发真实语义不足

- 上游仅证明视频字段/页面位置、“一键翻译”按钮和少量批发字段血缘；没有足够证据证明生成配额/轮询、翻译模式/方向、批发阶梯控件和完整保存读回。半托管原生门也缺 admitted/rejected/unknown 三类脱敏固定证据。
- 产品必需性已裁决，不等于实现细节可猜。未实证部分必须明确标 `PRODUCT_DECISION` 或 `BLOCKED`，用真实可见页面和脱敏差分补齐。

### B-11 · wire shape 与级联持续漂移

- array、JSON string、数字字符串、`0` 哨兵、空 ID 自定义属性及 child 结构都可能漂移。
- Reader 必须记录 observed/normalized type，只做显式、可逆、Schema-aware 归一化；新形状先判红并形成脱敏回归。

## P2 · 架构深化

### B-12 · 安全与证据合同分散

JIT、队列、lease、ledger、SAVE/VERIFY、payload/readback 和两阶段 receipt 分散在 main、Runner、worker 与多个合同模块。应收敛 `RuntimeTruth`、`ControlledMutationDispatch`、`CanonicalReceipt`、`ContentPreparation`、`RollbackSafety` 和 `SemiManagedBranch`，避免新的平行 runner。

统一方案 v1.1.2 新冻结的同店铺 writer fence 仍是目标态：事务 CAS、generation/fencing token、动作时 ledger 复核、孤儿围栏崩溃隔离和反例尚未实现。系统围栏不能观察外部浏览器或人工编辑，生产链仍必须用实时 revision、类目、Schema、catalog 和页面 checkpoint 阻断漂移；不得因有内部锁就宣称不存在并发编辑。

### B-13 · 大模块职责过重

`DxmLoginFlow` 同时承担会话、Reader、Schema、页面写入、读回、网络审计和身份；前端 `App.tsx` / `WorkbenchModules.tsx` 也继续膨胀。应保留 `DxmWorkflowAdapter` Seam，向深模块拆分而不复制合同。

### B-14 · 统一开发方案 v1.1.0 缺完整归档

- v1.1.1 修订前的 v1.1.0 只保留 SHA256 `1CDC30ED5E7B0AFB9F5E3927FD052D22137E9710E2B1EEDFD58FE764CAEA905B`，仓内没有完整 v1.1.0 归档；不得根据当前文档反推并伪造旧版。
- 关闭条件：若外部来源能提供同 hash 原稿，则只读核对后补入 `_archive`；若无法取得，永久保留该来源缺口。从 v1.1.1 起，任何 `v_next` 修改前必须先归档完整前一版本并记录 hash。

## 记录但不再待裁决

- 早期一次绝对路径 `rg` 排除失效，额外输出上游 `data/capture/observed` 下文档中的 4 行字段名；未含秘密、未改上游。事件已记录于 PROGRESS，后续只使用列明路径。
- 用户明确授权的唯一上游数据范围为 `data/capture/categories`；该授权不扩展到 sessions、Cookie、账号、店铺、商品、模板或业务 raw。
- 用户已经裁定五项能力全部必经、允许自动化精确中间转换并授权同步有用文档/类目数据；这些不再作为待裁决问题。
