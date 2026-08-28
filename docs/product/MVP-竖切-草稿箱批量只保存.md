> 由 OpenAI GPT（Codex）AI 生成/维护。

# DXM 完整商品编辑主合同：草稿箱批量只保存

E1–E4 的唯一产品主合同。

**合同状态：2026-08-26 产品真相冻结；当前实现仍 `E3_OPEN / BLOCKED`。**
**未宣称 `MVP_READY`，未宣称 `PROD_READY`。**
**适用仓库：`D:\Desktop\py\dxm-auto-uikit`。**
**上游只读：`D:\Desktop\py\DXM-TX`。**

本合同需要真实可见浏览器作为执行环境，draft ≥3 才能开始，只保存不发布。

本文件是产品、方案、Runner、安全和人工验收的唯一主合同。Gold、`AGENTS.md`、`CLAUDE.md`、docs 索引、架构和 runbook 只能指向或解释本合同，不得建立第二套 Path A-only、旧 `claim_only` 或 `single_save` 叙事。

---

## 0. 裁决与不可混淆的三层真相

### 0.1 冲突顺序

发生冲突时依次服从：最终零发布、数据正确和真实证据 → 当前代码/测试/运行事实 → 本合同 → 指定原型体验 → 功能完整 → 速度。

### 0.2 三层真相

| 层 | 回答的问题 | 当前裁定 |
|---|---|---|
| 产品范围 | 完整可交付产品必须做什么 | 视频、翻译、批发、半托管、回滚全部 `REQUIRED_CAPABILITY / ALWAYS_ON` |
| 运行时成熟度 | 当前代码实际接到哪里 | 未接线或证据不足的必需能力阻断产品放行，不得改称可选 |
| 当次授权 | 当前允许执行什么真实动作 | 由快照、人工批准、JIT、lease、queue 和 ledger 精确限定 |

“产品必须具备”不等于“当前已经实现”。聚焦测试、空 executor、配置面板或历史 Path A canary 都不能把未完成能力写成已交付。

### 0.3 最新产品裁决

- 每件商品必须无条件执行：产品视频、一键翻译、批发配置、半托管双阶段和 rollback preparation。
- 不允许由方案关闭，不允许 `SKIPPED_BY_FROZEN_PLAN`，不允许以继承原值、空操作或 Path A 降级冒充完整成功。
- rollback preparation 指每件商品都持久化 preimage、建立恢复计划并验证可恢复性；真正 restore 只在保存派发前的安全失败时触发。
- 完整产品成功路径固定为 **Path B**。Path A 只保留为底层诊断/canary，不得产生产品完成、`MVP_READY` 或 `PROD_READY`。
- Path B 中精确识别的中间“继续发布”允许受控自动化；它必须是进入 `editFromSmt` 的特定中间动作，不得解除最终发布禁令。
- 半托管资格不由本系统预判。点击顶部精确“保存”出现半托管提示后，再点击可见“编辑半托管信息”，由店小秘自身执行原生资格检查；系统不得主动调用 `verifyPopChoiceShop`，不得用店铺类型、类目、catalog、模板或历史结果推断资格。提示 Modal 不足以证明第一次 SAVE 已完成；当前不能断言哪个点击触发 SAVE1，因此两者均按可能写动作防护。实际 SAVE1 与门 outcome 必须各自验证并因果绑定同一握手，但不要求还原二者墙钟全序。

---

## 1. 产品定义与边界

### 1.1 一句话定义

运营人员在中文工作台连接同一个真实可见店小秘会话，从当前 `pageList(dxmState=draft)` 选择至少 3 件商品，按动态叶子类目、真实 Schema 和模板配置完整方案并冻结；同一受控 Runner 逐件完成普通编辑、视频、批发、翻译、半托管两阶段填写和两次精确保存，通过 HVD 控制并收集每阶段三铁证，最终始终保持未发布。

### 1.2 “只保存”与中间动作

本产品允许两次受控草稿保存：主编辑页的精确“保存”，以及 `editFromSmt` 半托管页的精确“保存”。最终“发布”“立即发布”“保存并发布”“保存并移入待发布”“上线”及任何 online/release 意图永久禁止。

主保存意图之后的半托管入口包含两个不同动作，不得合并：

1. `OPEN_SEMI_MANAGED_EDITOR`：精确点击当前主保存意图 Modal 中可见的“编辑半托管信息”。点击后由店小秘自身检查能否进入半托管界面；系统只观察平台裁决，不建立另一套资格判断器。该点击也可能位于实际 SAVE1 派发的因果链上，必须继续由 ledger/网络事实观察，不能按按钮文案猜测。
2. `SEMI_MANAGED_CONTINUE_TRANSITION`：只有原生门放行、实际 SAVE1 三铁证已闭合且两者因果绑定同一入口握手后，若出现已实证的特定后续 Modal，才允许点击其中的“继续发布”以进入 `editFromSmt`。

`FIRST_SAVE_INTENT` 与 `OPEN_SEMI_MANAGED_EDITOR` 都必须在 snapshot 中冻结 `MAY_DISPATCH_SAVE1` possible effect。前者在点击顶部“保存”前消费唯一 FIRST_SAVE lease 并开启 ledger；后者消费独立 action grant，同时事务化复核同一 `entry_handshake_id/FIRST_SAVE command`，其 phase 只允许 `IN_FLIGHT` 或 `SAVE_VERIFIED_AWAITING_GATE`。任一点击前未落 `MAY_HAVE_DISPATCHED`、任一点击后崩溃却恢复成写前失败、或为同一 FIRST_SAVE 再签第二张 lease，均属于安全违规。所有观察到的 SAVE mutation request 必须逐条绑定 request hash、causal action 与 ledger；未证明为平台幂等同一次保存时，物理请求数大于 1 必须 UNKNOWN，不得按相同 command id 静默合并。

中间“继续发布”不是泛化白名单。只有同时满足以下条件才允许自动化：

- 当前路径冻结为 Path B；
- 当前 Modal、主保存意图、商品、页面、任务、SAVE 授权因果链和 action grant 精确绑定；
- 店小秘原生半托管门已明确放行；
- 实际 SAVE1 三铁证已闭合，且与原生门 outcome 因果绑定同一入口握手；
- action kind 为独立 `SEMI_MANAGED_CONTINUE_TRANSITION`；
- 预期目标严格为正式 HTTPS `editFromSmt` 页面；
- 请求范围与上游观察的中间转换相符；
- 动作时重新经过 JIT 和 mutation ledger；
- 未命中任何最终发布/上线状态。

任一条件不成立时 PublishGuard 拒绝。

店小秘明确拒绝进入时必须按最终保存事实区分：已证明 SAVE1 未派发则 `outcome_code=semi_entry_rejected_main_not_saved`；SAVE1 三铁证已闭合则 `outcome_code=semi_entry_rejected_main_saved` 并保留部分保存事实、要求人工复核。SAVE1 最终事实、裁决结果或同一握手因果绑定不确定时 `execution_state=unknown`。三者都立即停批，不得自动再次点击、执行第二次 SAVE 或降级 Path A。

### 1.3 本产品不做

- 不采集、不认领新商品；`claim_only 非前置`。
- 不以 headless、HTML mock、后台写 API 或历史抓包替代真实可见 UI。
- 不直调店小秘写接口作为保存实现；写接口只可作为动作回包证据。
- 不使用中文标签、动态 DOM 序号、隐藏字段或模糊按钮作为单一执行身份。
- 不允许无人值守真实写入；不得存在第二个拥有队列、任务状态迁移、HVD 或写派发权的 Runner/Runtime。
- 不把本地 catalog、原型数据、旧 package、单测或历史 READY 当当前页面真相。

---

## 2. 权威来源与上游边界

| 来源 | 作用 |
|---|---|
| 本文件 | 唯一产品范围、顺序、安全和 DoD |
| [DXM-TX 上游事实合同](../integration/DXM-TX-上游事实合同.md) | 接口、页面和证据分层 |
| [类目节点与目录合同](../integration/DXM-TX-类目节点与目录合同.md) | 动态类目、叶子身份、catalog 和漂移 |
| [当前运行时架构](../architecture/当前运行时架构.md) | 当前代码事实与成熟度 |
| [操作与验收手册](../runbook/操作与验收手册.md) | 当前可执行命令和人工步骤 |
| DXM-TX 根原型 | IA、布局、文案和交互参考；mock 不是运行事实 |

上游私有接口、字段目录和抓包事实可能漂移。`PASSIVE_ONLY` 不得自动升级为生产重放；`SAMPLE_ONLY` 不得冒充通用 Schema。读接口必须有本仓白名单、请求合同、响应规范化、账号/会话作用域和漂移门禁。

经 2026-08-25 授权，本仓只迁入 `DXM-TX/data/capture/categories` 中的纯类目结构，并生成脱敏 catalog。Cookie、sessions、storage state、账号、店铺、商品、模板内容和业务 raw 仍禁止迁移。

---

## 3. 完整端到端主流程

### 3.1 批次流程

```text
统一 RuntimeTruth
  → 真实账号/店铺/Reader
  → 动态类目目录与目标叶子
  → pageList(draft) 当次多选 draft ≥3
  → Schema/模板/能力同步
  → 完整方案 preview
  → 不可变 plan_snapshot + ordered item_snapshots
  → 人工批准 batch_draft_save
  → Runner 串行逐商品
      页面/商品/源类目核验
      → 持久化 preimage + rollback plan
      → 必要时切换目标叶子并重读 Schema
      → 普通编辑分区填写
      → 产品视频（必经）
      → 批发/SKU 商业规则（必经）
      → 一键翻译（必经）
      → 全字段精确读回
      → 启用半托管
      → 主保存意图 + 精确绑定半托管提示 Modal
      → 精确点击“编辑半托管信息”
      → 店小秘原生资格检查；按真实事件闭合实际第一次 SAVE + 三铁证
      → 建立 SAVE1 verified + gate admitted + same-handshake causal join
      → 必要时受控中间“继续发布”
      → 精确进入 editFromSmt
      → 仅在 entry-handshake joined + page bound 同时成立后继续
      → 国家/货品/变种/物流填写与读回
      → 半托管第二次受控保存 + 三铁证
      → 独立未发布证明
  → HVD、结果、审计和人工对账
```

### 3.2 读写分治

- 店铺、draft、编辑快照、类目、Schema、模板和能力使用当前登录会话内的受审阅只读接口。
- 类目 catalog 只用于搜索、展示、预览参考和漂移检测；当前可见页面类目和实时 Schema 才是写前执行权威。
- 字段、模板、视频、翻译、批发、半托管和保存均通过真实可见 UI 写。
- 分页面、分阶段完成全量零写预检：主编辑页首写前完成 11 区、ContentFinalize 和半托管启用控件预检；店小秘原生门放行并进入 `editFromSmt` 后，在半托管页首写前完成 S1–S3 全量预检。后置字段不合法时不得先写同一页面的前置字段；不得用第一次 SAVE 前的推测代替第二页真实检查。
- 模板优先补差，运行时不得临时改变冻结目标值。

### 3.3 每件必经能力

| 能力 | 必经结果 | 不可用时 |
|---|---|---|
| 视频 | 真实生成/选择、投放、视频身份和字段读回 | 首个 SAVE 前 fail-closed；生成派发后未知则 UNKNOWN |
| 批发 | 真实控件、起订/折扣/扣减、价格货值库存关系和读回 | 首个 SAVE 前 fail-closed |
| 翻译 | 所有允许自然语言字段翻译、before/after、英文和越界校验 | 首个 SAVE 前 fail-closed |
| 半托管 | 主保存意图、`OPEN_SEMI_MANAGED_EDITOR`、店小秘原生门、实际主编辑 SAVE、必要的受控转换、`editFromSmt` 填写、第二次 SAVE | 不做本地资格预检；SAVE1 与门结果分别取证，平台拒绝按是否已保存分类，不确定均停批，不得降级 Path A |
| 回滚 | preimage、恢复计划、可恢复性预检；失败时逆序恢复 | 不可证明恢复则停止；派发后未知不自动补偿 |

---

## 4. 类目、模板与方案

### 4.1 动态类目

- 类目树任意深度，不得固定三级。
- 只有 `isleaf=1` 且 catalog `executableLeaf=true` 的节点可成为目标。
- `categoryId` 是执行身份；`nodePath` 和中文名只显示。
- 搜索结果必须通过 getById 和祖先链重建，并支持路径 ↔ 叶子 ID 双向映射。
- snapshot 同时冻结源类目、目标类目、node identity、catalog hash、Schema hash 和 capability hash。
- 切类目后、写任何字段前重新读取当前页面 `categoryId` 和 Schema；漂移立即停止。

### 4.2 模板模型

`local_plan_template` 与 `dxm_template_ref` 必须分离。本地模板持有运营规则、固定值、补差和必经能力配置；店小秘模板引用只持有稳定 id、店铺/类目作用域、来源时间和 hash。运行时不得重新读取“最新模板”后改变冻结目标值。

冻结解析优先级：明确 fixed → 明确 fill → 已批准 `dxm_template_ref` → 当前商品值 → unresolved（fail-closed）。“当前值已非空”不能吞掉人工补差。

### 4.3 中文界面与英文内容

产品自身使用中文界面与中文字段映射；自动写入的自然语言内容必须为英文，并在保存前校验，未通过时不得点击“保存”。

- `ui_label_zh → field_key → schema_path → stable binding` 必须可追溯。
- 中文标签不能单独作为执行主键。
- 翻译位于所有自然语言生成之后，只允许修改冻结白名单内的自然语言字段。
- 标题、描述、无线描述和自由文本属性逐字段读回，校验非空、Schema、英文和内容边界。
- ID、枚举、URL、SKU 结构和纯数字不得进入翻译目标。

---

## 5. 不可变 plan snapshot

每件商品的 `item_snapshot` 至少冻结：

```yaml
schema: dxm.full_product_edit_plan.v1
mode: batch_draft_save
executionPath: B
mandatoryCapabilities:
  video: true
  translation: true
  wholesale: true
  semiManaged: true
  rollbackPreparation: true
accountContextHash: sha256
sessionGeneration: "..."
shopId: "..."
productId: "..."
queuePosition: 1
sourceCategory:
  categoryId: "..."
  nodeIdentitySha256: sha256
targetCategory:
  categoryId: "..."
  nodeIdentitySha256: sha256
  catalogSha256: sha256
targetSchema:
  normalizedSchema: {}
  schemaSha256: sha256
targetCapabilities:
  capabilitiesSha256: sha256
requiredFields: []
fieldMapping: {}
resolutionResult: {}
videoPlan: {}
wholesalePlan: {}
translationPlan: {}
semiManagedPlan: {}
rollbackPolicy: {}
evidencePolicy: two_stage_three_proofs
publishAllowed: false
snapshotHash: sha256
```

`plan_snapshot` 必须为每件商品冻结 `categoryId`、类目 Schema/hash、必填字段及解析结果；多类目配置不得在执行时临时变化。

- 五项 mandatory capability 任一为 false、缺失或不可执行，不得创建可执行任务。
- `product_ids[]`、`item_snapshots[]` 和 job 顺序必须完全一致。
- snapshot 创建后不可修改；方案、目录、模板、Schema 或代码身份变化要创建新版本并重新批准。
- Runner 只能消费冻结 `resolutionResult` 和 execution payload，不能临时重算。

---

## 6. 安全、证据与就绪

### 6.1 MVP_READY

`MVP_READY` 只表示真实用户在同一可见店小秘会话完成完整产品主流程：

- 当次 `pageList(draft)` 多选 `draft ≥3`；
- 每件均完成目标叶子、完整配置和不可变 plan snapshot；
- 每件均真实完成视频、批发、翻译、rollback preparation 和 Path B；
- 每件均完成两次受控保存及对应证据；
- HVD 与 runner 同源，并与 worker、ledger、报告同源；
- 开始 / 暂停 / 继续 / 停止有真实 worker ack；
- 全批次没有最终发布动作；
- 任一 UNKNOWN 会停批且不得自动重试。

Path A 成功、单商品成功、任一能力跳过、mock、空 executor、单测或文档通过都不等于 `MVP_READY`。

### 6.2 PROD_READY

`PROD_READY` 还要求固定源码、同源 portable、完整 L0、包级 smoke、崩溃恢复、对账、长期证据、权限和生产运维门禁。固定关系：**`MVP_READY ≠ PROD_READY`**。

### 6.3 三铁证与两阶段保存

每一次 SAVE 都必须具备：预期请求的业务成功回包、同一商品/动作的页面成功态、独立读回证明没有进入最终发布状态。主页面提示 Modal 只证明保存意图，不属于三铁证；实际 FIRST_SAVE 请求无论发生在“保存”点击后还是原生入口握手中，都必须归入同一 SAVE1 command/ledger/receipt，并在半托管页首写前完成三铁证。

回包 + 页面成功态 + 独立未发布证明，三缺一不可。主编辑 SAVE 与半托管 SAVE 分别建立 command、JIT、lease、ledger、ActionResult 和 receipt，不得用第二次证据补第一次。

### 6.4 UNKNOWN 停批

保存、视频生成或受控中间转换派发后，若结果不确定、证据冲突、断线、超时、页面丢失或重启，必须令 `execution_state=unknown` 且 `manual_review_required=true`；UNKNOWN 停批且不得自动重试。

---

## 7. E0–E4 Definition of Done

### 7.1 E0 · 主合同、指针、上游同步和防回退

- 唯一主合同固定完整 Path B 和五项 ALWAYS_ON 能力；
- Gold、AGENTS、CLAUDE、docs index 指向本文件；
- DXM-TX 类目合同、catalog、manifest 和 hash 可复核；
- 校验器能把“能力可选/可跳过/降级 Path A”“固定三级”“泛化允许继续发布”真实判红；
- SelfTest 红→绿、链接、AI 标注、catalog check 和 `git diff --check` 通过。

### 7.2 E1 · RuntimeTruth、Reader、动态类目与多选

- 同一可见会话绑定账号、店铺、Reader 和 reason code；
- 分页读取 `pageList(draft)`，支持人工多选 ≥3；
- 动态任意深度类目 UI，只接受真实叶子；
- 搜索/getById/祖先链、catalog/session/account 漂移 fail-closed；
- 换会话、换账号、换店铺后旧选品、类目和确认输入全部失效。

### 7.3 E2 · 完整方案与不可变快照

- `local_plan_template` 与 `dxm_template_ref` 分离；
- 每件冻结 source/target category、catalog/node/schema/capability hashes；
- 每件冻结视频、批发、翻译、半托管和 rollback plan，全部 enabled；半托管只冻结 `RUNTIME_NATIVE_GATE_REQUIRED`、两个动作、目标页和拒绝/不确定处置，不冻结资格结果；
- 任一可在 freeze 时判定的必经能力缺控件、稳定 binding、值或证据规划时不能冻结；半托管资格只能在执行期由店小秘原生门裁决，不得提前伪造 READY；
- 多类目逐品隔离，运行时只消费冻结结果。

### 7.4 E3 · 完整可见编辑与 Path B Runner

- 使用现有唯一 Runner/BrowserAgent/DxmWorkflowAdapter，不得新增或保留第二个拥有队列、状态迁移、HVD 或写派发权的 Runner/Runtime；
- 每件先建立持久 preimage 和 rollback plan；
- 完成普通编辑、视频、批发、翻译与全字段读回；
- 完成主保存意图 Modal、`OPEN_SEMI_MANAGED_EDITOR`、店小秘原生门三类结果、实际主编辑 SAVE、必要的受控中间转换、`editFromSmt` 填写和第二次 SAVE；不得把 SAVE1 与门结果硬编码成未经实证的固定先后；
- 两次 SAVE 分别满足三铁证；
- 任一能力不可用不得降级 Path A；UNKNOWN 停批。

### 7.5 E4 · HVD、四键、结果与人工验收

- HVD 投影真实 task/job/step/worker/ledger/receipt；
- 开始、暂停、继续、停止使用持久状态和 worker ack；
- 暂停 ≥10 秒不推进，继续不重做，停止不再派发；
- 结果页逐件显示类目、五项能力、两阶段保存、三铁证、rollback/UNKNOWN；
- 完成 §11 后仅由人工签署 `MVP_READY`。

---

## 8. 指定根原型一致性

指定原型：`D:\Desktop\py\DXM-TX\DXM-半托管工作台-可交互原型.html`。

固定体验：240px rail、56px topbar、`#4f46e5`、16px 圆角、明暗主题、1100px/860px 断点和 HVD 开始/暂停/继续/停止四键。

当前七项主导航：工作台、连接店小秘、采集箱选品、铺货方案、开始批量保存、保存结果、设置。模板库可作为铺货方案内的子页，不得制造第二套主流程。

禁止复制原型中的 `SHOPS`、`PRODUCTS`、`DXM_TPL`、localStorage 数据源、预制成功、假浏览器和 mock 业务值。原型 Path B 交互只能提供 IA 参考，正式执行以本合同、实时页面和安全证据为准。

---

## 9. PublishGuard 与受控中间动作

PublishGuard 在任务开始、每阶段写入前、每次保存前和实际动作时独立复核。

永久拒绝：最终发布、立即发布、保存并发布、保存并移入待发布、上线、online/release 及相应请求/URL。

唯一含发布文字的允许动作是 `SEMI_MANAGED_CONTINUE_TRANSITION`。它只能在 §1.2 的精确 Path B 上下文中执行；不得通过文本白名单、正则排除或前端按钮放行。动作后必须到达预期 `editFromSmt` 页面，否则结果 UNKNOWN。

---

## 10. 回滚与异常

### 10.1 每件必经的 rollback preparation

- 打开并核验商品后、首个页面修改前，持久化受影响字段、源类目、页面和 Schema preimage；
- 生成严格逆序恢复计划和 preimage hash；
- 验证所有 binding 可读、可写、唯一且当前页面未漂移；
- 捕获期间不得保存、发布或触发外部 mutation。

### 10.2 真正 restore 的边界

- 首次 SAVE 和其它外部 mutation 派发前的已知失败：逆序恢复或 reload/discard，并逐字段读回；证明恢复后结束当前商品。
- 视频生成、主编辑 SAVE、中间转换或半托管 SAVE 已派发：不得自动用另一次 SAVE 补偿；结果不确定即 UNKNOWN。
- 恢复缺 preimage、字段不一致、页面漂移或进程重启丢状态时，不得报告 rollback 成功。

---

## 11. 人工验收

### 11.1 前置门禁

- [ ] Git、worktree、build、package、runtime 和 data identity 固定；
- [ ] 完整 L0、frontend build、desktop、文档和 catalog 门禁全绿；
- [ ] 同一真实可见会话的账号、店铺、Reader 就绪；
- [ ] 当前类目目录无未裁决漂移，目标均为可执行叶子；
- [ ] 视频、批发、翻译、半托管和 rollback 正式 Adapter/证据已接线；
- [ ] 最终发布保护与受控中间动作反例通过；
- [ ] 当次真实写入有明确人工授权。

### 11.2 正向流程

1. 从当前 `shopMap/pageList(draft)` 选择至少 3 件真实草稿。
2. 为每件选择动态目标叶子，审阅 source/target category 和 catalog/node/schema/capability hashes。
3. 配置普通编辑、视频、批发、翻译和半托管；确认五项均不可关闭，且半托管显示“店小秘运行时原生检查”，不显示预判资格 READY。
4. preview/freeze，审阅 ordered items、最终值、rollback plan、两阶段 evidence policy 和 snapshot hash。
5. 批准并开始；核对当前队列、JIT、lease 和 ledger。
6. 每件核对 preimage、类目切换、普通编辑、视频、批发、翻译和全字段读回。
7. 核对主保存意图 Modal 与“编辑半托管信息”入口，按真实 network/page/ledger 时间线分别核对店小秘原生门结果和实际第一次 SAVE 三铁证；不得预设两者先后。
8. 若出现特定后续 Modal，核对中间“继续发布”动作上下文；在任何半托管字段首写前，确认 SAVE1 verified、native gate admitted 和正式 `editFromSmt` 页面身份同时成立。
9. 核对半托管国家、货品、变种、物流填写和第二次 SAVE 三铁证。
10. 核对独立未发布状态，确认没有最终发布/上线。
11. 在真实任务验证暂停 ≥10 秒、继续不重做、停止不再派发。
12. HVD、API、SQLite、ledger、日志、报告与 receipt 同源。

### 11.3 反向流程

- [ ] 任一商品关闭/跳过视频、批发、翻译或半托管时，preview 或 freeze 判红；
- [ ] 非叶第三层、祖先链冲突或旧 catalog 节点不得冻结；
- [ ] 当前页面类目/Schema 漂移时，首个字段写入前拒绝；
- [ ] 系统主动调用 `verifyPopChoiceShop` 或用店铺类型/类目/catalog/历史结果预判半托管资格时拒绝；
- [ ] 原生门前将半托管资格写成 READY，或把 `OPEN_SEMI_MANAGED_EDITOR` 与 `SEMI_MANAGED_CONTINUE_TRANSITION` 合并时拒绝；
- [ ] 只凭半托管提示 Modal 宣称 SAVE1 完成，或硬编码“先 SAVE1 三铁证、后原生门”而没有真实 network/page/ledger 证据时拒绝；
- [ ] `FIRST_SAVE_INTENT` 或 `OPEN_SEMI_MANAGED_EDITOR` 未声明/处理 `MAY_DISPATCH_SAVE1`，点击前未持久化 `MAY_HAVE_DISPATCHED`，或同一 FIRST_SAVE 使用第二张 lease 时拒绝；
- [ ] `entry_handshake_joined` 前派发中间“继续发布”时拒绝；SAVE1 与门事实均已验证且因果同源时，仅因墙钟全序不可还原就判 UNKNOWN 也拒绝；
- [ ] 店小秘原生门明确拒绝后仍进入 S1–S3/第二次 SAVE，未按 SAVE1 是否真实派发区分结果，或结果不确定后自动重试时拒绝；
- [ ] 中间“继续发布”脱离精确 Modal/主保存意图与实际 SAVE 因果链/目标页上下文时拒绝；
- [ ] 最终发布类文本、URL 或请求始终拒绝；
- [ ] 删除任一次 SAVE 三铁证任一项，不得成功；
- [ ] 保存派发后制造断线，进入 UNKNOWN、停批且不得自动重试；
- [ ] preimage 不完整或恢复读回不一致时，不得宣称 rollback 成功。

### 11.4 签字

```text
验收日期：
验收人：
Git / worktree / package / runtime identity：
任务 id：
plan snapshot hash：
draft 数量：
完整 Path B 成功数：
两阶段三铁证完整数：
UNKNOWN / 已知失败：
rollback 复核：
最终零发布复核：
结论：MVP_READY / BLOCKED
备注：
```

只有全部适用项通过且人工签署，才可声明本范围 `MVP_READY`；`PROD_READY` 另行验收。

---

## 12. 当前实现裁定

截至 2026-08-28，当前工作树完整 backend L0 已达到 `2344 passed / 0 skipped`，但 0.3.0 仍主要只有 Path A 和基础 Runner 生产接线；视频、翻译、批发、Path B 完整生产接线、真实 rollback 和两阶段证据尚未闭环。Path B 配置/preview/freeze 可以存在，真实批准、启动和 Runner 派发仍以 `PLAN_PATH_EXECUTION_NOT_RELEASED` fail-closed。该事实意味着产品仍 `BLOCKED`，不意味着这些能力可从产品范围删除。

下一实施入口：动态 CategoryCatalog 消费和 source/target 类目修复 → 五项 mandatory snapshot → 正式可见页面 executor → Path B 双阶段安全合同 → 全量门禁与真实三商品验收。
