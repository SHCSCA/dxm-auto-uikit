> 由 OpenAI GPT（Codex）AI 生成/维护。

# DXM-TX 上游事实合同

**复核日期：2026-08-26。**
**上游目录：`D:\Desktop\py\DXM-TX`（只读）。**
**产品状态：完整商品编辑主流程是目标合同；当前实现仍为 `E3_OPEN / BLOCKED`，不是 `MVP_READY`，不是 `PROD_READY`。**

本文把 DXM-TX 中可复用的文档、类目目录和页面观察，转换为本仓可审计的上游事实合同。它同时记录截至 2026-08-26 的产品裁决，但严格区分：

- **上游观察事实**回答“店小秘页面、接口或 wire 曾观察到什么”；
- **产品裁决**回答“本系统必须怎样工作”；
- **当前实现事实**回答“代码截至 2026-08-26 实际接通到哪里”。

三者不能互相冒充。上游出现某字段不等于本仓已实现；产品要求某能力必需也不等于当前已经 READY。

关联：[MVP 主合同](../product/MVP-竖切-草稿箱批量只保存.md) · [普货方案配置与执行架构](../product/普货方案配置与执行架构.md) · [当前运行时架构](../architecture/当前运行时架构.md) · [当前进度](../../PROGRESS.md) · [待关闭门禁](../../BLOCKED.md)。

## 1. 事实状态与使用规则

| 状态 | 含义 | 允许用途 |
|---|---|---|
| `VERIFIED_UPSTREAM` | 上游文档和当前代码共同支持的稳定原则 | 产品合同、实现约束、回归测试 |
| `SAMPLE_ONLY` | 只在有限账号、页面、类目或时间样本中观察到 | 形成脱敏 fixture、建立漂移门禁 |
| `PASSIVE_ONLY` | 被动观察到接口、字段或请求，但没有主动重放授权 | 索引、诊断、只读白名单候选 |
| `PRODUCT_DECISION` | 用户为本产品明确裁定的强合同 | 方案、快照、Runner、证据和验收 |
| `IMPLEMENTATION_BLOCKED` | 产品必须具备，但当前生产链尚未闭合 | `BLOCKED.md`、开发顺序、负向测试 |

硬边界：

1. `PASSIVE_ONLY` 不得自动升级为生产重放、真实写入或 READY 证据。
2. 私有接口可能漂移；业务码、响应结构、账号、店铺、商品、类目和分页作用域必须严格验证。
3. DXM-TX 永久只读。本仓不得迁入 Cookie、storage state、账号密码、真实店铺/商品/模板/联系人样例、原始业务抓包或未脱敏日志。
4. 用户已明确授权读取并同步 `DXM-TX/data/capture/categories/**` 中的通用类目目录产物；授权仅覆盖规范化类目节点和来源 manifest，不覆盖其它 `data/**`。
5. 写路径仍只通过真实可见 UI；观察到保存请求不等于允许程序直调写接口。
6. 最终发布、立即发布、保存并发布、保存并移入待发布和任何使商品在线的动作永久禁止。

## 2. 上游 Source manifest

以下 SHA256 是本次审计快照。16 个入口（根 3 份、`docs/**` 13 份）均已逐一登记，其可复用事实已经合并到本文、唯一主合同、方案架构、运行架构和 runbook；没有遗漏未登记的当前上游文档。同步采用“提炼后进入唯一当前文档”而不是原样复制整棵文档树，避免把含业务样例、过程日志和 `PASSIVE_ONLY` 大目录带入本仓，也避免形成第二套滞后权威。源 hash 变化时必须输出 `STALE_REVIEW_REQUIRED`，先做脱敏差分审阅，不能自动覆盖本合同。

### 2.1 根状态与 13 份文档

| 上游相对路径 | SHA256 | 处置 |
|---|---|---|
| `README.md` | `D91145EFD018EB663473B55A712FB89D75CF758A09F899F0A999C8FE76A0AE6C` | 入口与总体边界已合并到本仓 README 和本文 |
| `PROGRESS.md` | `D5D992CC8061C979A12212ED695811F0A08EE77CE85966131D3A9FEC043C4CBE` | 仅保留 hash 与脱敏摘要；历史状态不覆盖本仓当前状态 |
| `BLOCKED.md` | `4CA42044AC1477D32FCE712426FEECED715CD1AF04E06FD750BDBB2B1BF9758E` | 仅保留 hash 与脱敏摘要；样例和现场路径不复制 |
| `docs/README.md` | `981F25B0C8C0B6919D30357D0F782F801740C32A4872DB3CAAF701E2C2D91C09` | 有效导航与真相分层已合并到本仓 docs 索引和本文 |
| `docs/01-产品与混合架构.md` | `4DB90765C161CB4F9534CFB9873752F5E958975E8F4567630C4AAB77824FA403` | 读接口、写 UI、零最终发布原则已合并到主合同 |
| `docs/02-编辑页执行与填写手册.md` | `88D7A8E5E0757BD4F116CE881C843DCCBC170424D2DDCF9109EE95CCB1D4D182` | 编辑结构、定位、预检和三铁证已合并到运行架构/runbook |
| `docs/03-半托管全流程操作手册.md` | `7B351D36E005348EFFEB68CE0CDCEDAEB18E8E4E15AD6346B3FFA4B864B248C1` | Path A/B 页面事实；正文含业务样例，只能脱敏归档 |
| `docs/api/店小秘-半托管双保存路径.md` | `684F345AB62E85B2BB3941EF95C226881B77414C4040A4BFD133B1F36A8225C5` | 两阶段页面/请求事实；含商品/店铺样例，只能脱敏提炼 |
| `docs/api/店小秘-采集箱草稿列表与选品接口.md` | `601FFF2F0105032E82393BF26B25FF69BD2B03A620CBAC221BBFE300B330AC85` | Reader 请求/响应壳；含店铺和数量样例，只能脱敏提炼 |
| `docs/api/店小秘-常用模板与编辑页-接口文档.md` | `B491AB60ED3E0189EB81B6DC67B842049A994C74545C3CFC62CBA1BBC9215C15` | 模板、编辑快照、类目和 Schema；含业务样例，只能脱敏提炼 |
| `docs/api/店小秘-接口抓包缺口与场景矩阵.md` | `78CA753BE3FED5F7AA37F7F493ADBA641F7F33ADDF6DAE15BC08BDD3403C181F` | 缺口与验收维度；含样例，只能脱敏提炼 |
| `docs/api/店小秘-类目路径与叶子ID映射.md` | `2E53B5394F1E3B843A06892F67E2316F18FD27A55E22344FFE1EE64B13BDF761` | 通用平台类目合同已迁为独立类目合同并驱动规范 catalog |
| `docs/api/DXM-编辑页接口.md` | `531467886266C3603584C0CA0BC960C7F565E3E24122B9B75B8963A56C5B920C` | `PASSIVE_ONLY` 大目录；只保留 hash 与定向提炼，不整本复制 |
| `docs/api/DXM-常用模板接口.md` | `1ECD87C0CAD6F089F1886232CD5817C2CF332C0A76962370AD99645A20027351` | `PASSIVE_ONLY` 大目录；只保留 hash 与定向提炼，不整本复制 |
| `docs/api/DXM-接口字段血缘.md` | `D4085E3D1E57A0977B223E9E93B3EBE3DE322D215208E2AD844012C428153776` | `PASSIVE_ONLY` 结构候选；只保留 hash 与定向提炼，不整本复制 |
| `docs/api/DXM-已观察私有接口总目录.md` | `6BE7347A7EEA3FE297978BADAAAE15429159437932FD752FCF7BFF2F0AD2F3AC` | `PASSIVE_ONLY` 索引；只保留 hash，不作为调用白名单 |

根原型 `DXM-半托管工作台-可交互原型.html` 的 SHA256 为 `29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`。原型只提供信息架构与体验约束；其 mock、localStorage、预制日志和业务值不得成为运行数据或 READY 证据。

### 2.2 类目数据 manifest

用户授权范围内的类目数据已规范化为：

- [category-catalog.v1.json](../../resources/dxm/category-catalog/category-catalog.v1.json)；
- [category-catalog.manifest.json](../../resources/dxm/category-catalog/category-catalog.manifest.json)；
- 同步/漂移校验器：[sync-dxm-category-catalog.ps1](../../scripts/sync-dxm-category-catalog.ps1)。

权威校验命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-dxm-category-catalog.ps1 -Check
```

manifest 自身保存源文件 SHA256、大小、处置、catalog hash、观测时间和计数。叙事文档不硬编码派生 catalog hash；消费方必须读取 manifest 当前值并验证文件。当前观测快照为 `SAMPLE_ONLY@2026-07-28`：13,216 节点、11,864 叶子，其中 11,852 个叶子通过完整祖先链校验可作目录候选，12 个冲突叶子被隔离。计数不是永久阈值。

当前 `resources/**` 尚未被证明进入 Electron portable；因此 catalog 目前是源码态版本化参考，不能据此宣称 0.3.0 包已携带。

## 3. 事实目录

### DXM-BOUNDARY-001 · 读接口、写 UI

- 状态：`VERIFIED_UPSTREAM`。
- 店铺、草稿、模板、类目 Schema 和编辑快照优先从已登录可见会话的受审阅只读接口取得。
- 字段、模板选择、视频、翻译、批发、半托管和保存必须通过真实可见 UI 完成。
- 保存接口只可作为证据观察；禁止把 `add.json` 或其它写接口直调变成主实现。

### DXM-READER-001 · 店铺与草稿列表

- 状态：端点和基础字段为 `SAMPLE_ONLY`；本仓规范化行为为 `PRODUCT_DECISION`。
- `GET /api/userInfo.json` 提供账号与 `data.shopMap`；`POST /api/smtProduct/pageList.json` 使用 `dxmState=draft` 读取分页草稿；`getOfflineCounts` 只作数量交叉核对。
- 商品身份至少绑定 `id/idStr`、`shopId`、`categoryId`、draft 状态、账号 generation、会话、页码闭合和读取时间。
- 业务码不是严格整数 `0`、分页不闭合、重复身份冲突、账号/会话变化或商品不再是 draft 时，旧输入立即失效。

### DXM-CATEGORY-CATALOG-001 · 动态类目节点与执行叶子

- 状态：端点/字段形状为 `SAMPLE_ONLY`；本仓规范化 catalog 与执行约束为 `PRODUCT_DECISION`。
- 上游读取族为：`list.json` 根列表、携带 `pcid` 的递归子列表、`getByCategoryId.json` 单节点详情。树深度是动态的，禁止写死三级或把 `level===2` 当作叶子。
- catalog schema 为 `dxm.category_catalog.v1`。节点至少保留：`categoryId`、`parentCategoryId`、`observedLevel`、`pathDepth`、`derivedDepth`、`isLeaf`、`executableLeaf`、中英文名称、`nodePath`、`nodePathIds[]`、能力标志、来源标志、完整性问题和 `nodeIdentitySha256`。
- 上游 `level` 仅作 observed 值，不能单独授权执行。执行目标必须同时满足 `isLeaf=true`、完整祖先链一致、直接父节点一致且没有隔离问题。
- `categoryId` 必须与 `nodePathIds[]` 最后一段一致；`parentCategoryId`、祖先链和派生深度必须一致。重复 ID、路径歧义、缺祖先或冲突节点 fail-closed。
- 搜索结果不能直接成为执行目标；必须按 ID 重新水合节点与祖先链。路径到叶子、叶子到完整路径都要支持；歧义路径不得猜选。
- 方案和逐商品 snapshot 必须分开冻结 `source_category` 与 `target_category`，并绑定 `catalog_hash`、源/目标 `nodeIdentitySha256`、目标 Schema hash 和 capability hash。
- catalog 只服务选择、展示、preview 和漂移比较。真正写入前仍必须从**当前可见会话页面**重读当前 `categoryId` 和 Schema；它们才是动作时执行权威。

### DXM-TEMPLATE-001 · 模板、编辑快照与作用域

- 状态：端点存在为 `SAMPLE_ONLY/PASSIVE_ONLY`；跨账号、店铺和类目通用性未证明。
- 管理中心模板索引与编辑页当前可引用子集必须分开；名称相同不代表同一模板。
- 编辑快照、店铺级模板、类目级 `attributeList`、值级 `childAttributeList`、资质、尺码表等都必须按账号、会话、店铺、商品、类目和采集时间分区。
- 模板记录必须保留稳定 id、作用域、来源时间和 source hash；中文名称只用于展示。

### DXM-WIRE-001 · wire 与规范化类型分离

- 状态：`PRODUCT_DECISION`。
- 同一字段可能是数组、JSON 字符串、严格数字字符串、`0` 哨兵或空 id 自定义属性。
- Reader 必须记录 `observed_wire_type` 和 `normalized_type`，只允许显式、可逆、Schema-aware 的转换。
- 未知形状、冲突重复、不可逆转换或哨兵语义不明时 fail-closed；不得为通过测试静默丢字段。

### DXM-EDITOR-001 · 可见编辑页与稳定定位

- 状态：稳定原则为 `VERIFIED_UPSTREAM`，具体 selector 为 `SAMPLE_ONLY`。
- `rc_select_N` 是运行期序号，不能持久化。执行身份必须使用冻结 `field_key`、Schema path、稳定 binding、控件类型和当次 DOM 唯一性。
- 中文标签只用于展示和辅助诊断，不能单独成为执行主键。
- 写入与读回必须共用 binding registry；隐藏控件、额外匹配、未知组件或无法预检的字段一律拒绝。
- 在每个当前可见页面首次字段写入前，必须完成该页面全部后置控件、值和动作的零写预检。主编辑页完成 11 区预检；半托管页只能在店小秘原生门放行并进入 `editFromSmt` 后完成 S1–S3 预检，不得在第一次 SAVE 前猜测第二页资格或控件。

### DXM-EDITOR-002 · 原生 11 form 与产品 11 区投影

- 状态：上游 11 form 为 `SAMPLE_ONLY`；产品 v5 固定 11 区是 `PRODUCT_DECISION`；当前代码 v4 的 10 区模型是待迁移事实。
- 上游观察的 11 form 为基本、店小秘、属性、产品、区域调价、描述、包装、模板主、模板税率、合规和其它。
- 产品层不得再把模板主与模板税率合并；两者在工作台和冻结合同中保持独立 11 区身份。
- 半托管页是第二阶段页面，不是主编辑页的额外 form。

### DXM-CAPABILITIES-001 · 五项能力是逐商品必经主流程

- 状态：**`PRODUCT_DECISION`；当前均存在不同程度 `IMPLEMENTATION_BLOCKED`。**
- 每件商品都必须无条件经过：视频、翻译、批发、半托管以及 rollback preparation。方案只能配置真实模式和值，不能关闭、跳过或降级这些阶段。
- 主编辑页可观察能力在当前店铺、目标类目、商品或页面上不受支持，或者缺少稳定控件、Schema、值、readback 或证据合同时，必须在主页面首写前 fail-closed；不得回退 Path A、继承原值、空操作或伪造成功。
- 半托管资格是唯一的阶段性例外：它不是本系统可提前判定的输入。点击顶部精确“保存”出现半托管提示后，再点击“编辑半托管信息”时由店小秘自身原生裁决；系统只冻结门控动作和拒绝/不确定处置，不得主动调用 `verifyPopChoiceShop`，也不得用 `shopSmtTypeMap`、类目、catalog、模板或历史记录推断资格。现有上游文字不足以证明真实 SAVE1 请求一定先于该原生门完成，精确时序必须从同一可见会话的 network/page/ledger 证据得出。
- rollback preparation 的必经含义是：持久化逐字段 preimage、建立恢复点、验证恢复边界并绑定 task/job/item/session/schema/hash。成功商品不应为了“执行回滚”而反向改回；只有首个保存派发前的已知失败才执行逆序恢复。
- 保存、视频生成或其它外部 mutation 一旦派发且结果不确定，令 `execution_state=unknown`、`manual_review_required=true`，禁止自动重试或自动补偿保存。

上游对具体能力的事实边界：

| 能力 | 上游已观察 | 尚不能从上游推断 |
|---|---|---|
| 视频 | 产品视频字段、`videoUrl/dxmVideoId` 等形状候选 | 当前代码假设的配额、生成 Modal、轮询和成功条件 |
| 翻译 | 编辑页存在一键翻译入口和目标语言检查 | 普通/AI 模式、方向、作用字段和完成判定的通用语义 |
| 批发 | `bulkDiscount*` 等结构候选及价格/库存相关字段 | 起订量、折扣、扣减方式的真实控件和跨类目规则 |
| 半托管 | 主编辑页提示、“编辑半托管信息”、`editFromSmt`、第二页字段、双保存路径 | `shopSmtTypeMap` 或 `verifyPopChoiceShop` 可升级为本系统的资格权威；任意店铺/类目都适用；国家/物流可猜测或硬编码 |
| 回滚 | 编辑前后页面状态可观察 | 保存后存在安全、幂等的自动补偿写语义 |

### DXM-PATHB-001 · 半托管双阶段保存是完整产品主路径

- 状态：页面/请求形状为 `SAMPLE_ONLY/PASSIVE_ONLY`；每件商品必须执行 Path B 是 `PRODUCT_DECISION`。
- 目标偏序：主编辑页完整填写与读回 → 启用半托管 → 派发主保存意图并精确绑定提示 Modal → 点击“编辑半托管信息” (`OPEN_SEMI_MANAGED_EDITOR`) → 店小秘原生资格检查；实际第一次 SAVE 请求及三铁证与门 outcome 均按真实事件闭合，不预设固定先后。只有 FIRST_SAVE verified、门 admitted 且两者因果绑定同一握手后，才可处理已实证的特定中间 Modal (`SEMI_MANAGED_CONTINUE_TRANSITION`)；再精确绑定正式 `/web/smt/editFromSmt` 页面，才允许 S1–S3 零写预检、填写与读回 → 第二次受控保存 → 两阶段证据闭合。
- `FIRST_SAVE_INTENT` 与 `OPEN_SEMI_MANAGED_EDITOR` 在未取得相反真实证据前都属于 `MAY_DISPATCH_SAVE1`。前者消费唯一 FIRST_SAVE lease 并开启同一 ledger command；后者消费 action grant，同时复核同一 `entry_handshake_id/FIRST_SAVE command`，其 phase 只能为 `IN_FLIGHT` 或 `SAVE_VERIFIED_AWAITING_GATE`。任一可能写 action 点击前必须持久化 `MAY_HAVE_DISPATCHED`，崩溃后不得恢复为 pre-write。两个动作若观察到多条真实 SAVE mutation request，必须逐条绑定 request hash/causal action/ledger；没有平台幂等同一保存的证据时一律 UNKNOWN，不得合并。
- `OPEN_SEMI_MANAGED_EDITOR` 与含“继续发布”的 `SEMI_MANAGED_CONTINUE_TRANSITION` 是两个独立 action kind。每个都绑定当前 task/job/item、Path B、精确 Modal 身份、预期请求、目标 URL、动作时一次性 grant 和 mutation ledger；“继续发布”只能证明进入半托管编辑页，不是最终发布白名单。
- 原生门明确拒绝时，若已证明 SAVE1 未派发则记录 `semi_entry_rejected_main_not_saved`；若 SAVE1 三铁证已闭合则保留回执并记录 `semi_entry_rejected_main_saved`、要求人工复核；SAVE1 最终事实、门结果或同一握手因果绑定不确定时进入 `unknown`。三者都停批，不自动重试、不执行第二次 SAVE、不降级 Path A。
- 不能因为文案相同就建立全局白名单。身份、URL、请求或页面结果任一不符，立即拒绝并停批。
- 最终发布、立即发布、保存并发布、保存并移入待发布以及任何 online/release 意图永久禁止。
- 两次保存各自需要与其 action 精确绑定的业务回包、页面成功态、独立未发布证明和 ledger 闭合；第一阶段证据不能替代第二阶段证据。

### DXM-SNAPSHOT-001 · 模板优先补差与不可变执行输入

- 状态：模板优先是上游工作流事实；不可变逐商品快照是更强的 `PRODUCT_DECISION`。
- 冻结解析优先级为：人工固定值/补差规则 → 已批准店小秘模板引用 → 当前商品值 → unresolved。
- 每件商品必须冻结账号/会话、店铺、商品、源/目标类目、catalog/schema/capability hash、模板引用、字段 mapping、最终 resolution、稳定 binding、五项必经能力配置、两阶段动作合同、rollback preimage policy、审批和证据策略。半托管只冻结 `RUNTIME_NATIVE_GATE_REQUIRED` 及处置策略，不冻结伪造资格结果。
- Runner 只能消费冻结 resolution 和 ordered item payload；不能在执行时重新读取最新模板后改变目标值。

### DXM-SAVE-001 · 两次只保存、三铁证与 UNKNOWN

- 状态：安全原则为 `VERIFIED_UPSTREAM + PRODUCT_DECISION`。
- 主编辑页和半托管页只允许各自精确的“保存”动作；保存接口只作证据观察。
- 每次保存只有同时具备业务成功回包、页面成功态和独立未发布证明才可闭合，三缺一不可。
- 派发后断线、超时、重启、回包/页面/读回冲突或 ledger 未闭合必须进入 `UNKNOWN`，停批且不自动重试。

### DXM-PROTOTYPE-001 · 原型体验边界

- 状态：`PRODUCT_DECISION`。
- 可迁移信息架构、布局、文案、组件、交互状态和 HVD 四键。
- 禁止迁移 `SHOPS`、`PRODUCTS`、`DXM_TPL`、localStorage 数据源、假浏览器、预制日志和预制成功。

## 4. 当前实现阻断

下列事实说明产品合同尚未实现，不能据此降低产品要求：

1. `BatchVideoGenerator`、`BatchTranslator`、`WholesaleFiller`、`SemiManagedExecutor` 和 `RollbackManager` 尚未形成同一生产 Runner/BrowserAgent/ActionResult/ledger 链，多处页面动作仍为空实现或输入回显。
2. 当前 `BATCH_DRAFT_SAVE_STEPS` 仍以 Path A 为主并排除半托管；正式执行器尚未完成逐商品双保存。
3. 视频 quota/request/poll/readback、翻译真实作用域、批发真实控件/关系规则、半托管国家/货品/变种/物流和 rollback 持久恢复均缺生产闭环。
4. 类目目录已版本化，但前端/后端仍需证明任意深度选择、冲突节点隔离、source/target category 冻结和写前实时 Schema 复核；portable 也尚未证明打包 catalog。
5. 当前工作树完整 backend L0 已于 2026-08-28 达到 `2344 passed / 0 skipped`；同源 0.3.0 portable、正式 DxmWorkflowAdapter 集成、真实逐商品双保存三铁证和最终零发布证据仍未闭合。

因此当前只能标 `E3_OPEN / BLOCKED`。不得把类存在、状态枚举、配置面板、聚焦测试、历史 Path A 保存或 catalog 文件存在描述为完整产品可用。

## 5. 下游消费边界

| 下游 | 必须消费 | 不得消费 |
|---|---|---|
| Reader | 白名单请求、scope、wire/normalized 类型、账号会话证明 | Cookie、raw 值、固定业务 id |
| CategoryCatalog | manifest、动态祖先链、executable leaf、node/catalog hash | 固定三级、只信 observed level、冲突节点 |
| 方案/快照 | 模板、完整能力配置、源/目标类目、最终 resolution、rollback policy | 运行时临时重算、允许跳过必经阶段 |
| Visible Editor Adapter | 稳定 binding、当前页面分阶段全量预检、共享写入/读回定位 | 中文标签单键、隐藏控件、`rc_select_N`、第一次 SAVE 前伪造第二页预检 |
| Runner/BrowserAgent | ordered item、五项必经阶段、Path B 双保存、两个独立半托管入口动作、原生门三类结果、UNKNOWN | Path A 降级、主动资格预检、直调写 API、调用方自签事实 |
| UI | 中文结构化配置、真实来源、阻断与证据 | mock 成功、可关闭必经能力、敏感样例 |

任何上游源、catalog manifest 或本合同发生漂移时，默认动作是 `STALE_REVIEW_REQUIRED`：停止依赖该事实的放行声明，重新做脱敏差分审阅；不是自动覆盖快照或自动执行。
