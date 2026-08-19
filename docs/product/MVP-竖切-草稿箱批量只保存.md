> 由 OpenAI GPT（Codex）AI 生成/维护。

# DXM MVP 竖切合同：草稿箱批量只保存

**合同状态：E0 冻结基线（未宣称 `MVP_READY`，未宣称 `PROD_READY`）**

**适用仓库：`D:\Desktop\py\dxm-auto-uikit`**

**上游只读：`D:\Desktop\py\DXM-TX`**

本文件是 DXM「草稿箱批量只保存」E1–E4 的唯一产品主合同。配套入口为
[Gold 工作指令](CODEX-GOLD-工作指令-MVP批量只保存.md)、
[AGENTS.md](../../AGENTS.md)、[CLAUDE.md](../../CLAUDE.md) 与
[docs 索引](../README.md)。这些文件用于指向本合同或补充工程安全要求，不得建立第二套产品主叙事。

---

## 0. 合同裁决与用词

### 0.1 冲突顺序

发生冲突时必须按以下顺序让步：

1. **零发布与真实证据**；
2. **当前代码、测试和运行事实**；
3. **本 MVP 合同一致性**；
4. **指定根原型的体验一致性**；
5. **功能完整**；
6. **速度**。

安全要求只能收紧，不能被产品体验或交付速度放宽。拿不准是否会形成真实写入、重复写入或发布时，必须 fail-closed：拒绝执行、保留现场、进入人工核对。

### 0.2 规范词

| 词 | 约束 |
|---|---|
| **必须 / 只允许 / 不得 / 禁止** | 硬合同；违反即失败 |
| **建议** | 可替换为更优实现，但交付记录必须写理由与等价证据 |
| **真实** | 来自当次真实可见店小秘会话、当前任务、当前页面与可核对证据 |
| **批次** | 一次任务中由人工确认的 `draft` 商品 id 队列，MVP 人工验收数量至少 1 |
| **只保存** | 只触发店小秘文案精确为「保存」的 UI 动作；不发布、不移入待发布 |

### 0.3 当前冻结范围

- 当前只冻结 E0–E4；一次只实施一个 Epic。
- MVP 执行路径仅为 **Path A**：不参与半托管，草稿商品编辑后只保存。
- Path B / `editFromSmt` 仅标记为**后续阶段 / 运行拒绝**，不得成为 E1–E4 的可执行任务、默认选项或成功分支。
- `claim_only` 是历史受控能力，**claim_only 非前置**；本 MVP 的输入直接来自店小秘采集箱 `dxmState=draft`。
- 现有 `single_save` 可被复用为实现原语，但其历史证据、授权和 READY 结论不得扩大为批次证据或批次授权。

---

## 1. 产品定义、用户与边界

### 1.1 一句话定义

运营人员在 DXM 控制台连接一个**真实可见浏览器**会话，通过只读接口取得店铺与采集箱草稿，人工多选 **draft ≥1**，选择并确认方案快照，然后由同一受控 runner 串行执行 `batch_draft_save`：逐品在真实店小秘编辑页用 UI 填写并点击精确「保存」，通过 HVD 查看同源进度，并可开始、暂停、继续或停止；任何发布动作永久禁止。

### 1.2 核心用户结果

1. 用户看到的店铺、草稿、模板和执行状态都来自后端或真实会话，而非前端自造成功态。
2. 用户在开始前能审阅商品范围、方案、差异字段、风险和不可变快照。
3. 用户在执行中能看到当前商品、当前步骤、证据状态和剩余队列。
4. 每个商品的成功或异常独立记录；批次汇总不能掩盖单品事实。
5. 用户可以在 UNKNOWN 或其它异常后人工对账，而系统不会自动重复点击。

### 1.3 本 MVP 不做

- 不采集、不认领新商品；只处理已经出现在 `pageList(draft)` 的商品。
- 不执行 Path B、`editFromSmt`、半托管页保存或任何「继续发布」动作。
- 不执行发布、立即发布、保存并发布、保存并移入待发布、上线、release/online 等动作。
- 不以 headless 或后台 HTTP 写接口替代可见浏览器 UI 写入。
- 不做无人值守真实写入，不新建第三套 runner，不在 DXM-TX 建生产后端。
- 不把 HTML 原型、mock、历史 `single_save`、离线测试或接口观察目录当作真实批量成功证据。

---

## 2. 权威来源与真相分层

### 2.1 产品与工程来源

| 来源 | 角色 | 可否直接授权执行 |
|---|---|---|
| 本文件 | E1–E4 唯一产品主合同 | 否；仅定义范围与 DoD |
| Gold 工作指令 | Epic 顺序、报告格式与硬禁止 | 否 |
| `AGENTS.md` / `CLAUDE.md` | 仓库结构、安全门禁、runner 与命令 | 否 |
| `DXM-TX/docs/01-产品与混合架构.md` | 读接口 / 写 UI 的架构真相 | 否 |
| `DXM-TX/docs/02-编辑页执行与填写手册.md` | 编辑页 UI 写入与三铁证 | 否 |
| `DXM-TX/docs/03-半托管全流程操作手册.md` | 字段和 Path A/B 观察参考 | 否；Path B 被本合同覆盖 |
| `DXM-TX/docs/api/店小秘-*.md` | 当前只读接口、模板、草稿列表与缺口 | 否 |
| DXM-TX 根原型 | 信息架构、布局、文案、组件和交互状态 | 否；其 mock/Path B 不进入运行 |

### 2.2 PASSIVE_ONLY 边界

DXM-TX 的四份 `DXM-*.md` 大文档是被动观察审计产物。即使其中目录为 `ready=true`、字段为 `VERIFIED` 或结构已经收敛，所有端点仍按 `PASSIVE_ONLY` 处理：

- `PASSIVE_ONLY` **不得自动升级为生产重放**；
- `STRUCTURAL_CANDIDATE` 不等于已验证 UI 语义；
- 被动观察到请求不等于获得主动调用、真实写入或批次授权；
- E1 如需使用只读接口，仍须建立本仓显式白名单、请求键校验、响应漂移与失败降级合同。

### 2.3 事实优先

- 文档描述与当前代码/测试冲突时，记录冲突，不伪称已实现。
- 历史 READY 仅对其 commit、包、证据范围和时间窗口有效。
- 当前 P0 红基线（TS18048、批次测试循环导入）是 E1 前门禁，不在 E0 内修复。

---

## 3. MVP 端到端竖切

### 3.1 主链路

```text
真实可见浏览器登录
  → 【只读接口】读取真实店铺
  → 【只读接口】pageList(dxmState=draft) 分页/按店过滤
  → 控制台人工多选 draft（MVP 验收 ≥1）
  → 选择 local_plan_template + dxm_template_ref
  → 预览并确认不可变 plan snapshot
  → 创建 mode=batch_draft_save 的单一批次任务
  → runner 串行逐品执行 Path A
      打开真实编辑页
      → 模板优先，按规则补差
      → 按中文字段映射写入英文自然语言内容并完成保存前校验
      → PublishGuard 前置/保存前/动作时复核
      → UI 点击精确「保存」
      → 回包 + 页面成功态 + 独立未发布证明
  → 结果页逐品显示事实与证据
```

### 3.2 读写分治

- **读路径：只读接口优先。** 店铺、draft 列表、编辑页当前值、模板索引和类目 schema 应来自已登录会话内的受审阅只读接口；漂移或鉴权失败必须显式失败或标注降级置信度。
- **写路径：UI 写。** 字段填写、模板引用和保存只通过真实可见页面的 UI 仿真完成。
- **写接口仅作证据。** 可以观察保存回包判定结果，但不得把直调 `add.json` 作为主保存实现。
- **模板优先补差。** 先引用店小秘已有模板，再对标题、SKU、货值、包装等差异字段按快照规则补齐；不得在运行中临时改变类目、品牌、是否发布或方案。
- **语言边界。** 中文只用于操作界面、字段映射和人工说明；自动写入的自然语言内容只允许英文，且必须在点击「保存」前完成读回校验。

### 3.3 批次粒度

- 任务输入必须绑定当前用户确认的店铺范围、`productIds[]`、方案快照、会话和审批上下文。
- `productIds[]` 必须来自当次 `pageList(draft)` 读回；不得由 mock、历史样例或手写真实业务 id 注入。
- MVP 人工验收要求多选至少 1 个商品；实现与测试不得硬编码为恰好 1。
- 批次默认逐品串行，单品完成并落证据后才推进下一品。
- 单品失败的继续策略必须由错误分类预先定义；`UNKNOWN` 一律停批。

### 3.4 中文界面、中文字段映射与英文写入

**产品自身使用中文界面与中文字段映射；自动写入的自然语言内容必须为英文，并在保存前校验，未通过时不得点击「保存」。**

- 产品导航、按钮、状态、错误、风险提示和人工验收说明使用中文；店小秘第三方页面的原始文案不由本产品改写。
- 中文字段映射以可审阅表表达 `ui_label_zh → field_key → category_schema_path → UI binding`。中文标签只供操作者识别，不得单独充当执行主键或脆弱文本选择器。
- 类目 Schema 必须标记哪些字段属于 `natural_language`。本产品自动写入这些字段时，快照固定 `expected_language=en`；标题、描述、卖点、自由文本属性等均适用，数字、枚举、标识符和不可翻译专名按 Schema 的非自然语言规则处理。
- 保存前校验必须针对本次自动写入值做 UI 读回，至少验证必填非空、Schema 约束、`detected_language=en` 且不含 Unicode Han 字符；检测为 `UNKNOWN`、中英文混杂、读回不一致或约束失败时，按已知前置失败停止该商品，且不得派发保存动作。
- 语言检测结果、字段映射版本/hash 和逐字段校验结果进入单品证据；运行时不得因页面标签、语言检测器或映射的新版本而静默改写已冻结任务。

---

## 4. 数据模型与不可变快照

### 4.1 模板模型必须分离

禁止把本地方案模板和店小秘模板引用揉成一个含糊对象。

#### `local_plan_template`

产品侧可编辑、可版本化的规则模板，至少包含：

- 本地模板 id、版本、名称与适用店铺/类目约束；
- Path A 固定值；
- 包装重量/尺寸、货值规则、英文内容策略等补差规则；
- 对各 `dxm_template_ref` 的引用；
- 缺失字段、校验策略和异常策略；
- 创建/更新时间与来源说明。

#### `dxm_template_ref`

对店小秘现有模板的只读引用，至少包含：

- 稳定类型（产品、属性、变种、运费、服务、尺码等）；
- 店小秘模板 id；
- `shopId`、`categoryId` 等适用作用域；
- 观察到的显示名仅用于人类确认，不作为执行主键；
- 最近同步时间、来源接口、可用性/漂移状态。

`dxm_template_ref` 不复制模板写接口，不等于允许程序修改店小秘模板。

### 4.2 `plan_snapshot`

开始批次前必须从当前 `local_plan_template` 和已解析的 `dxm_template_ref` 生成不可变 `plan_snapshot`。最低字段：

```yaml
schema: dxm_batch_draft_save_plan.v1
mode: batch_draft_save
path: A
shop_scope: "当前确认范围"
product_ids: ["来自当次 draft 读回"]
local_plan_template:
  id: "..."
  version: "..."
dxm_template_refs:
  - type: "freight|service|product|attribute|variation|size"
    id: "..."
    shop_id: "..."
    category_id: "..."
fill_rules: {}
item_snapshots:
  - product_id: "..."
    shop_id: "..."
    categoryId: "..."
    category_schema:
      normalized_schema: {}
      schema_hash: "sha256"
    field_mapping:
      mapping_version: "..."
      mapping_hash: "sha256"
      entries:
        - ui_label_zh: "中文字段名"
          field_key: "stable_field_key"
          category_schema_path: "$.properties..."
          ui_binding: "reviewed_binding_id"
    required_fields:
      - field_key: "stable_field_key"
        required_when: "normalized condition"
        constraints: {}
    resolution_result:
      resolved_fields:
        - field_key: "stable_field_key"
          source: "current|local_plan_template|dxm_template_ref|derived"
          source_ref: "id@version"
          resolved_value: "..."
          natural_language: true
          expected_language: "en"
      unresolved_fields: []
      resolution_hash: "sha256"
evidence_policy: three_proofs
failure_policy:
  unknown: stop_batch
publish_allowed: false
snapshot_hash: "sha256"
```

**`plan_snapshot` 必须为每件商品冻结 `categoryId`、类目 Schema/hash、必填字段及解析结果；多类目配置不得在执行时临时变化。**

- `item_snapshots[]` 与 `product_ids[]` 必须一一对应；每件商品独立绑定 `product_id`、`shop_id`、`categoryId`，不得从同批另一类目借用配置。
- `category_schema.normalized_schema` 保存创建任务时已规范化的完整类目 Schema；`schema_hash` 是对其确定性序列化结果计算的 SHA256。必填字段集合、条件必填规则、约束及依赖必须从这份 Schema 解析并冻结。
- `field_mapping` 冻结该商品的中文字段映射版本、hash 和映射条目；`resolution_result` 冻结每个目标字段的最终解析值、来源及版本、语言策略、未解析字段和解析 hash。存在未解析必填字段时不得创建可执行任务。
- 顶层 `snapshot_hash` 必须覆盖全部 `item_snapshots` 及其嵌套 Schema、映射、必填字段和解析结果，不得仅覆盖模板 id 或商品 id。
- `plan_snapshot` 创建后不可原地修改；方案变更必须创建新版本和新批次。
- runner、HVD、日志、结果与证据必须引用同一个任务 id、快照 hash、商品 id 和队列位置。
- runner 开始每件商品前只允许读回当前 `product_id`、`shop_id`、`categoryId` 与类目 Schema 并同冻结值/hash 做一致性核验；不一致时必须在任何字段写入前 fail-closed，不得用当前“最新”配置修补快照。
- 执行、暂停/继续和恢复均不得重新解析“最新方案”、最新模板、最新类目 Schema、最新必填字段或最新字段映射；只能继续使用任务创建时的逐商品解析结果。

### 4.3 批次与单品状态

建议状态必须至少表达：

```text
batch: DRAFT → APPROVED → RUNNING ↔ PAUSED → COMPLETED
                              ├→ STOPPING → STOPPED
                              ├→ FAILED
                              └→ UNKNOWN_RECONCILIATION

item: QUEUED → RUNNING → SAVED
                    ├→ FAILED_KNOWN
                    └→ UNKNOWN
```

状态转换必须后端持久化并与 worker ack 对齐；前端按钮状态不是执行事实。

---

## 5. 安全、控制与证据合同

### 5.1 PublishGuard

`PublishGuard` 是不可移除、不可绕过的硬门禁，至少在任务开始前、每品保存前和实际点击时复核：

- 目标域、会话、精确页面与商品绑定；
- 当前动作文本必须精确为「保存」；
- 可见按钮、弹窗、URL、请求意图不得命中发布类信号；
- `publish_allowed` 恒为 `false`；
- 命中「发布 / 立即发布 / 继续发布 / 保存并移入待发布 / save_and_publish / release / online」等信号必须拒绝。

禁止通过放宽断言、改阈值、跳过门禁、mock 被测对象或仅靠前端禁用来满足 DoD。

### 5.2 三铁证

每个商品只有同时具备以下事实才可标记 `SAVED`：

1. **保存回包成功**：与当次 UI 点击相关联的保存请求为允许的保存端点、方法正确、HTTP 成功、业务码成功；
2. **页面成功态**：真实页面出现可核对的编辑保存成功态；
3. **独立未发布证明**：通过独立读回/状态证明商品仍未发布；“没有观察到发布请求”不能替代本证据。

固定口径：**回包 + 页面成功态 + 独立未发布证明，三缺一不可。**

证据必须绑定任务 id、item id、plan snapshot hash、运行时/会话、时间、动作 id 和当前 Git 身份。HTML 模拟日志、原型结果表或历史单品报告均不满足。

### 5.3 UNKNOWN 停批

- 发送保存动作后，如果无法确认是否成功，不得归类为普通失败，不得自动重试。
- mutation ledger 中未闭合的派发、超时、断线、页面丢失或回包/页面/读回冲突必须进入 `UNKNOWN`。
- 固定策略：**UNKNOWN 停批**，隔离当前商品，保留证据和页面现场，剩余队列不再派发，转人工对账。
- 人工对账前禁止通过重启、换 runtime、继续按钮或重新创建相同动作来再次点击。

### 5.4 开始 / 暂停 / 继续 / 停止

四键必须作用于真实 batch runner，并由后端状态与 worker ack 证明：

| 控制 | 合同 |
|---|---|
| 开始 | 完成审批、快照冻结和门禁后才创建/派发队列 |
| 暂停 | 停止派发下一安全动作；等待 worker ack 后才显示已暂停 |
| 继续 | 从已持久化安全点和原快照继续；不得重复已完成写动作 |
| 停止 | 进入 STOPPING，安全收敛当前动作；不再派发新商品，最终 STOPPED 或 UNKNOWN |

暂停/停止不能粗暴中断一个已派发但结果未知的保存；这种情况必须按 UNKNOWN 处理。

### 5.5 HVD 同源

HVD 与 runner 同源，至少投影以下后端事实：

- 任务/批次 id、当前商品序号和总数；
- 当前商品稳定标识（脱敏展示）；
- 当前 runner step、状态和 worker ack；
- plan snapshot hash；
- 三铁证各自状态；
- 暂停/继续/停止状态；
- UNKNOWN / 人工接管提示。

禁止用前端计时器、预制步骤或本地数组独立推进 HVD。

---

## 6. 双就绪与发布口径

### 6.1 `MVP_READY`

`MVP_READY` 只表示本合同的最小竖切已经由人使用真实店小秘会话验收：

- **最终人工验收必须从当次 `pageList(draft)` 读回并多选 `draft ≥3`；**开发切片可以先支持 ≥1，但不得用单品或 mock 结果替代三商品验收。
- [ ] 真实可见浏览器登录成功，且身份/会话/当前 Git 可核对；
- [ ] 只读接口拉取真实店铺与 `pageList(draft)`，人工多选 ≥1；
- [ ] Path A 的 `local_plan_template` 与 `dxm_template_ref` 可审阅；
- [ ] 任务携带不可变 plan snapshot 与 hash；
- [ ] `batch_draft_save` 在同一受控 runner 中逐品串行；
- [ ] HVD 与 runner/日志/证据同源；
- [ ] 开始、暂停 ≥10 秒、继续、停止在真实任务上有 worker ack；
- [ ] 至少 1 品各自具备三铁证，结果页可逐品核对；
- [ ] UNKNOWN 样例或可执行合同证明会停批且不自动重试；
- [ ] PublishGuard 全程有效，零发布动作，独立未发布证明齐全。

只有人工完成 §11 并签字后，才可在对应验收记录中标注 `MVP_READY`。E0 文档完成、单测通过、mock 演示、单品成功或本清单存在，都不等于 `MVP_READY`。

### 6.2 `PROD_READY`

`PROD_READY` 是后置生产硬化口径，可能包括 portable 与当前 HEAD 同一构建、fresh L2/L3、审批租约、mutation ledger、状态一致性、包级 smoke、恢复/对账和更完整场景。

固定关系：**`MVP_READY ≠ PROD_READY`**。

- 未达到 `PROD_READY` 不应否定一个已经按本合同验收的 MVP 竖切；
- 达到 `MVP_READY` 也不得宣称 production、全局 READY、无人值守、Path B 或发布可用；
- 历史 `READY` / `controlled_single_save_only` 不得替代二者。

---

## 7. E0–E4 Definition of Done

### 7.1 E0 · 合同、指针与防回退校验

**交付**

- 本主合同存在并覆盖 §6.1、§7、§8、§11；
- Gold、`AGENTS.md`、`CLAUDE.md`、`docs/README.md` 四个指针可解析到本文件；
- 校验器检查文件存在、必需章节/术语、悬空链接、AI 标注与旧叙事冲突；
- `-SelfTest` 在内存删除 `PublishGuard` 后必须先判红并输出 `RED_EXPECTED`，再校验真实文件输出 `MVP_DOCS_OK`。

**DoD**

- 校验器真实红→绿且返回 0；
- `git diff --check` 返回 0；
- Gold/原型哈希不变，DXM-TX 与 `app/**` 零改动；
- 只宣称 E0 完成，不宣称 `MVP_READY` / `PROD_READY`。

### 7.2 E1 · 只读 Reader 与 draft 多选

**范围**

- 在已登录真实会话内读取 `userInfo.shopMap`；
- 分页读取 `pageList(dxmState=draft)`，支持全部店/按店过滤、刷新、加载与错误态；
- 前端多选真实 draft id，至少能支持 ≥1，生成可审阅任务输入；
- 明确 `claim_only` 不参与本链路。

**DoD**

- API 与 UI 显示真实来源，fallback/mock 不得显示为真实；
- 无会话、schema 漂移、分页不闭合、店铺/商品绑定冲突时 fail-closed；
- 测试覆盖分页、过滤、去重、空列表、错误态、真实/降级来源标签；
- 当前 P0 的 TS18048 与批次测试循环导入先修复并回归不劣化。

### 7.3 E2 · 模板、方案与不可变快照

**范围**

- `local_plan_template` CRUD/versioning；
- `dxm_template_ref` 只读同步与作用域校验；
- 模板优先补差；
- 启动前预览并冻结 `plan_snapshot`。

**DoD**

- 两模型在 schema、API 和 UI 上分离；
- 创建 `batch_draft_save` 任务时 payload 含完整快照与 hash，并为每件商品冻结 `categoryId`、类目 Schema/hash、必填字段、字段映射和解析结果；
- 方案修改不改变已创建任务；
- 多类目批次逐品使用自己的 `item_snapshots[]`；执行时不借用其它类目配置，不临时重算；
- 中文界面展示的字段名可追溯到冻结的中文字段映射；所有自动写入的自然语言字段在保存前通过英文校验；
- 不复制根原型的真实样例、mock 数组或 localStorage 数据源；
- 测试覆盖版本不可变、引用/Schema/hash 漂移、多类目隔离、作用域冲突、未解析或缺失必填字段 fail-closed。

### 7.4 E3 · `batch_draft_save` Path A runner

**范围**

- 在现有 runner / Browser Agent / `batch_edit` 基础上增加明确 mode `batch_draft_save`；
- 逐 id 串行打开真实编辑页，模板优先补差，只点精确「保存」；
- 每品三铁证、mutation ledger、PublishGuard 和 UNKNOWN 停批；
- 不新建第三套 runner，不把旧 `batch_save` 含糊语义直接当放行。

**DoD**

- 合约与测试覆盖 mode 门禁、队列、幂等、证据绑定、零发布、已知失败与 UNKNOWN；
- 真实账号人工批准后，至少 1 个 draft Path A 各自三铁证；
- 任何单品缺证据不得计入成功；
- Path B 请求在任务创建和运行时均被拒绝。

### 7.5 E4 · HVD 与四键

**范围**

- HVD 投影真实 runner/worker/ledger 状态；
- 开始、暂停、继续、停止具备后端控制、持久化状态与 worker ack；
- 结果页逐品展示证据与人工对账入口。

**DoD**

- 真实批次暂停 ≥10 秒后继续，不重复已完成保存，不丢队列；
- 停止后不再派发新商品；在途不确定动作归 UNKNOWN；
- HVD、日志、结果、API 与持久化状态在同一任务/快照/item 粒度一致；
- 完成后仅提交 §11 给人验收，不由实现者自行勾选 `MVP_READY`。

---

## 8. 指定根原型一致性

指定原型：`D:\Desktop\py\DXM-TX\DXM-半托管工作台-可交互原型.html`。

本合同要求严格对齐其**信息架构、布局、文案、组件和交互状态**，但产品数据与运行事实必须来自正式后端/真实会话。

### 8.1 固定视觉与布局

- 左 rail：桌面宽度 **240px**；
- topbar：高度 **56px**；
- 主色：**`#4f46e5`**；
- 卡片主圆角：**16px**；
- 支持**明暗主题**；
- 断点：**1100px** 时复杂多列/浏览器舞台收为单列，**860px** 时隐藏 rail 并切移动布局；
- 真实浏览器可见窗内保留 HVD 信任面板；
- HVD/浏览器控制固定四键：**开始 / 暂停 / 继续 / 停止**。

### 8.2 固定 7 项导航

导航名称与顺序固定为：

1. 工作台；
2. 连接店小秘；
3. 采集箱选品；
4. 铺货方案；
5. 开始批量保存；
6. 保存结果；
7. 设置。

允许为无障碍、响应式或错误态增加局部组件，但不得另造第二条主导航或把历史「认领 → 单品保存」放回主链路。

### 8.3 必须替换的原型假数据

实现时禁止复制或保留以下原型运行数据源：

- `SHOPS`；
- `PRODUCTS`；
- `DXM_TPL`；
- 原型中的真实店铺、商品、模板 id/名称与业务样例；
- `localStorage` 作为正式店铺、商品、模板、方案、任务、HVD 或结果真相源。

前端可使用明确标注的测试 fixture 做离线测试，但运行 UI 必须区分 `api` / `fallback` / `mock`，且 mock 永不产生真实成功态或 READY 结论。

### 8.4 Path B 与模拟引擎裁决

- 原型中的 Path B 选择、`editFromSmt` 演示与模拟 `popChoiceProduct/add` 成功不进入 E1–E4；
- 正式 UI 对 Path B 只显示“后续阶段”或不可选择状态；若请求绕过 UI，后端运行时拒绝；
- 原型 JavaScript 的队列、计时、预制日志、`dxm-fake` 与模拟结果页不得成为 runner、HVD 或证据实现；
- 真实可见浏览器不是用 HTML 画出的假店小秘页面。

---

## 9. 只读接口与 UI 写合同

### 9.1 E1 必需只读能力

| 能力 | 当前参考 | 运行要求 |
|---|---|---|
| 店铺 | `GET /api/userInfo.json` | 显式只读白名单；店铺 id/name 仅在授权 UI 展示 |
| 草稿列表 | `POST /api/smtProduct/pageList.json` + `dxmState=draft` | 分页闭合、按店过滤、来源标注 |
| 草稿数量 | `POST /api/smtProduct/getOfflineCounts.json` | 只作显示/交叉核对，不替代列表 |
| 编辑快照 | `GET /api/smtProduct/edit.json` | 每品打开时刷新并核对 product/shop/category |
| 模板/类目 | 受审阅的 list / category 只读接口 | 作用域与 schema 漂移 fail-closed |

私有接口会变化；本表不是把 PASSIVE_ONLY 观察自动提升为重放授权。E1 必须在本仓明确实现允许的只读请求合同。

### 9.2 写入动作

- 字段值通过 UI 控件写入；
- 模板通过 UI 引用或点选；
- 中文字段映射必须解析到稳定 `field_key`、当前类目 Schema 路径和受审阅 UI binding；不得把中文显示文本直接当作跨类目执行配置；
- 自动写入的自然语言内容必须为英文；每一目标字段都要在保存前完成非空/Schema/语言/精确读回校验，任一失败均不得点击「保存」；
- 保存按钮规范化文本必须精确等于「保存」；
- 保存回包只作为三铁证之一；
- 发现发布类按钮/弹窗/URL/意图时 `PublishGuard` 拒绝。

---

## 10. 错误、恢复与对账

| 类别 | 示例 | 批次策略 |
|---|---|---|
| 前置已知失败 | 未登录、模板缺失、作用域冲突、表单校验失败且确认未派发保存 | 记录失败；是否继续须按快照预设 |
| 保存明确失败 | 业务回包明确失败且可证明未写成功 | 记录失败；默认停现场，不自动重试 |
| 证据不完整 | 缺页面成功态或独立未发布证明 | 不计成功；停批核对 |
| UNKNOWN | 派发后断线、超时、结果冲突、ledger 未闭合 | 立即停批，人工对账，禁止自动重试 |
| 发布信号 | 发布按钮/弹窗/URL/请求意图 | `PublishGuard` 拒绝并终止 |

恢复必须从持久化状态、ledger、证据和真实页面共同判断，不得仅凭前端内存或 runtime 文本恢复。

---

## 11. 人工验收

本节由具备真实店小秘权限的人执行和签字。Codex 在没有真实会话、授权或三铁证时只能提供步骤，不能代签。

### 11.1 验收前门禁

- [ ] 当前分支、HEAD、工作树、运行时与构建身份已记录；
- [ ] 真实可见浏览器已登录，目标店铺/会话/页面绑定正确；
- [ ] PublishGuard、审批租约、mutation ledger 与证据目录处于可用状态；
- [ ] 选品、方案和批次测试已通过，P0 红基线已清零且未降低测试/断言；
- [ ] 本次明确只验 Path A，Path B 运行请求会拒绝；
- [ ] 已确认不会读取或提交 Cookie、密钥、raw 抓包或真实业务样例。

### 11.2 主流程

1. 打开「连接店小秘」，核对真实会话状态与店铺读取来源。
2. 进入「采集箱选品」，选择一个店铺或明确的全部店范围，刷新 `pageList(draft)`。
3. 人工勾选至少 1 个真实 draft；核对每个 id 均来自本次读回。
4. 进入「铺货方案」，审阅 `local_plan_template`、`dxm_template_ref`、模板优先补差规则、中文字段映射、自然语言英文策略和 Path A。
5. 创建任务前审阅 `plan_snapshot`，逐品核对 `categoryId`、类目 Schema/hash、必填字段、中文字段映射和解析结果并记录 snapshot hash；至少包含两个不同类目时，确认两份配置互不借用。
6. 任务创建后修改方案、模板、类目 Schema 或字段映射，确认已创建任务保持冻结；若真实页面的 `categoryId`/Schema hash 漂移，确认任何写入前 fail-closed，而不是临时重算。
7. 点击「开始」，确认真实可见浏览器操作当前商品，HVD 与后端日志显示同一任务/商品/step。
8. 在安全点点击「暂停」，等待至少 10 秒，确认 worker ack、没有推进下一写动作。
9. 点击「继续」，确认从合理安全点恢复、没有重复保存或丢队列。
10. 在独立验证任务或非破坏性验收场景中核对「停止」：停止后不派发新商品；若在途结果不确定则进入 UNKNOWN。
11. 对至少 1 个成功商品逐一核对保存回包、页面成功态、独立未发布证明。
12. 核对「保存结果」页、HVD、日志、ledger 与证据引用一致。
13. 搜查本次动作与网络事实，确认没有发布、立即发布、继续发布、保存并移入待发布或其它发布写入。

### 11.3 反向验收

- [ ] 伪造/删除三铁证任一项时，商品不得显示成功；
- [ ] 提交 Path B / `editFromSmt` 请求时，UI 不可选且后端运行拒绝；
- [ ] 人为制造保存结果不确定时，进入 UNKNOWN、停止剩余队列且不自动重试；
- [ ] 篡改任一商品的 `categoryId`、类目 Schema/hash、必填字段或解析结果时，快照/执行前一致性校验判红；不得从同批其它类目借值或临时重算；
- [ ] 前端 HVD 断线或刷新时，不得凭本地计时器继续推进；
- [ ] 发布类文本或 URL 命中时，PublishGuard 拒绝；
- [ ] 给任一自动写入的自然语言字段注入中文、混合语言、空值或 `detected_language=UNKNOWN` 时，保存前校验判红且不点击「保存」；
- [ ] mock/HTML 原型只能显示演示来源，不得生成真实任务证据。

### 11.4 签字结论

```text
验收日期：
验收人：
Git HEAD / build identity：
任务 id：
plan snapshot hash：
draft 数量：
三铁证完整成功数：
UNKNOWN / 已知失败：
零发布复核：
结论：MVP_READY / BLOCKED
备注：
```

只有本节全部适用项通过且人工结论为 `MVP_READY` 时，才可作该范围声明；`PROD_READY` 必须另行验收。

---

## 12. 后续阶段

- E5 可另立合同研究 Path B，但必须重新定义包含「继续发布」字样的危险交互如何被永久零发布策略处理；在此之前一律运行拒绝。
- E6 可扩展异常池、人工对账与恢复体验。
- E7 可执行 `PROD_READY` 硬化、portable 同 HEAD、包级 smoke 与生产交付门禁。
- 任何后续阶段不得倒写或弱化 E0–E4 的零发布、三铁证、UNKNOWN 停批和真实可见浏览器要求。

---

## 13. E0 冻结记录

- 本文件建立的是合同与 DoD，不是功能完成证据。
- E0 完成后下一建议入口是 E1：先修复当前 P0 门禁，再实现只读 Reader 与真实 draft 多选。
- E1–E4 未在本文件建立时完成；禁止据此宣称 `MVP_READY` 或 `PROD_READY`。
