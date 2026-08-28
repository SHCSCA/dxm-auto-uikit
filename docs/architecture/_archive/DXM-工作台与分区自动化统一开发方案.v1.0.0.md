> 由 OpenAI GPT（Codex）AI 生成/维护。

# DXM 工作台与分区自动化统一开发方案

## 0. 文档定位

| 项 | 结论 |
|---|---|
| 文档性质 | 目标架构与实施路线，不是当前运行事实 |
| 当前状态 | `0.3.0-dev` · `E3_OPEN / BLOCKED` |
| 产品主合同 | [完整商品编辑：草稿箱批量只保存](../product/MVP-竖切-草稿箱批量只保存.md) |
| 当前代码事实 | [当前运行时架构](当前运行时架构.md) |
| 方案与快照事实 | [普货方案配置与执行架构](../product/普货方案配置与执行架构.md) |
| 运营操作来源 | [运营操作详细文档](../runbook/运营操作详细文档.md) |
| 上游事实 | [DXM-TX 上游事实合同](../integration/DXM-TX-上游事实合同.md) 与 [类目节点与目录合同](../integration/DXM-TX-类目节点与目录合同.md) |
| 状态裁决 | [PROGRESS](../../PROGRESS.md) / [BLOCKED](../../BLOCKED.md) |

本文把运营人员在店小秘中的真实完整编辑过程，转换成工作台信息架构、冻结合同、单 Runner 编排、分区自动化 Module、证据和验收路线。本文不允许覆盖产品主合同；如有冲突，按“零发布与真实证据 → 当前代码/测试/运行事实 → MVP 合同 → 指定原型体验 → 功能完整 → 速度”裁决。

本文中的“已存在”“当前”“未接”描述现有代码事实；“目标”“应”“R0–R6”描述后续 Implementation。仅创建本文不能关闭任何 BLOCKED 项，也不能宣称 `MVP_READY` 或 `PROD_READY`。

## 1. 结论先行

系统不是“把若干字段批量改掉”的工具，而是“先把一个店铺内多件草稿的完整编辑决策冻结，再由同一个可见会话按商品、页面和分区串行执行，最终只保存、不发布”的运营工作台。

后续开发固定为以下主线：

1. 登录后必须先选择一个具体店铺；选品、模板、方案、快照、审批和任务全部绑定该店铺与当前账号会话。
2. 工作台的方案编辑器按店小秘主编辑页的 11 个分区组织，不再以当前 10 区模型或旧 Path A 步骤作为产品结构。
3. 自动化只有一个 canonical Runner。所谓“按分区做多个自动化”，是把每个分区做成独立、可测试、可维护的 Module，由 Runner 到达对应分区时调用；不是新增进程、队列、Worker 或第三套 runner。
4. 每件商品无条件经过普通编辑、视频、批发、翻译、半托管和 rollback preparation。任一能力不具备稳定 binding、写前读回或安全回执时，必须在首写前拒绝。
5. 完整成功路径固定为 Path B：主编辑页 11 分区 → 第一次 SAVE → 精确中间转换 → `editFromSmt` 三分区 → 第二次 SAVE → 独立最终未发布证明。
6. 精确识别的中间“继续发布”允许作为 `SEMI_MANAGED_CONTINUE_TRANSITION` 自动化；最终发布、立即发布、保存并发布、移入待发布永久禁止。
7. 每个分区都实行 `inspect → capture_preimage → apply → readback → receipt`。外部 mutation 一旦派发而结果不确定，状态只能是 `UNKNOWN`，停批且不得自动重试。

## 2. 真相来源与证据等级

### 2.1 来源优先级

1. 产品和安全不变量：唯一 MVP 主合同。
2. 当前 Implementation：权威 checkout 中的代码、当前测试和运行证据。
3. 店小秘真实操作：运营操作详细文档及 DXM-TX 已脱敏事实合同。
4. 交互体验：指定根原型的信息架构与视觉约束。
5. 建议和推演：运营文档 §12、人工构造夹具和历史原型，只能形成待验证设计，不能直接放行写入。

### 2.2 本方案的事实标签

| 标签 | 含义 | 可否直接进入写入合同 |
|---|---|---|
| `OBSERVED` | 已由上游页面、接口或当前代码直接观察 | 仍须通过当前会话写前复核 |
| `PRODUCT_DECISION` | 用户已拍板的产品或安全要求 | 可以冻结为目标合同，但不代表已实现 |
| `NEEDS_LIVE_EVIDENCE` | 细节尚缺真实正向回包或控件证据 | 不可猜测；写前 fail-closed |
| `HISTORICAL_ONLY` | 旧 Path A、旧 snapshot、旧批次或 mock 叙事 | 只读审计，不得升级为生产写入 |

### 2.3 已确认事实

- `OBSERVED`：主编辑页存在 11 个运营分区；Path B 存在主编辑页保存、中间转换、`editFromSmt` 的 S1–S3 和第二次保存。
- `OBSERVED`：当前代码的 `dxm_editor_form.v4` 仍是 10 区模型，模板主区与税率区尚未按运营流程分开。
- `OBSERVED`：当前 `BATCH_DRAFT_SAVE_STEPS` 和相关 guard 仍带有 Path A 历史结构；另一条旧批次编排也没有成为统一生产主线。
- `OBSERVED`：视频、翻译、批发、半托管和回滚已有若干类、配置或测试 seam，但尚未共同贯穿正式 Runner、BrowserAgent、ledger 和回执。
- `PRODUCT_DECISION`：一个任务只处理一个具体店铺；五项能力对每件商品无条件执行；中间精确转换允许自动化；最终发布永久禁止。
- `NEEDS_LIVE_EVIDENCE`：视频额度和轮询、翻译模式与完成态、批发阶梯控件、资质图片稳定身份、切类目差分、非空级联回包，以及运营文档 §12 中的扩展建议。

## 3. 当前系统与真实运营流程的交叉审计

| 真实运营阶段 | 当前系统事实 | 主要缺口 | 本方案处置 |
|---|---|---|---|
| 登录并选择店铺 | 已有可见会话、Reader、店铺与草稿读取 | 店铺切换后的全部下游状态失效规则仍需统一 | 建立 `ShopExecutionContext`，所有对象冻结 `account/session/shop` 身份 |
| 多选草稿 | 已有草稿列表、≥3 多选与任务输入 | 需要与具体店铺、当次 Reader epoch 精确绑定 | 店铺或会话变化即撤销 selection、preview、snapshot 和 approval |
| 11 分区配置 | 当前动态编辑模型为 10 区 | 模板主/税率未分开，运营规则和执行 binding 未逐区闭合 | 升级 `dxm_editor_form.v5`，固定 0–10 分区代码 |
| 模板优先补差 | 已有本地方案、DXM 只读模板和 snapshot | 必经能力、两页执行值和分区回执未进入同一 hash | `local_plan_template.v4` 与 `dxm_batch_draft_save_plan.v2` 同时冻结 |
| 写前预检 | 已有部分 schema、identity、JIT 和 readback 校验 | 仍分散在多处，不能证明 11 区全部可执行后才首写 | 每区 `inspect`，并在商品级先完成全量 zero-write preflight |
| 主编辑页填写 | 现有写入器偏向 legacy 固定字段与 Path A | 未由通用稳定 binding 驱动 11 区 | 一个 `BindingRegistry`，分区 Module 只消费冻结 binding |
| 视频/批发/翻译 | 有局部 Implementation 或配置 | 未形成每件商品 ALWAYS_ON 主链 | 做成跨分区必经 Module，纳入 preimage、readback 和 receipt |
| 第一次 SAVE | 已有 mutation guard、JIT、lease、ledger 和证据合同 | 需要绑定新的完整 item payload 与 11 区回执 | 由 `ControlledSaveDispatch` 消费冻结执行 payload，禁止调用方自签事实 |
| 中间转换 | 上游已观察 Path B 弹窗与目标页 | 旧代码仍可能把 Path A 语义混入 | 独立 action kind，只允许精确 modal/URL/task/job/lease 组合 |
| 半托管 S1–S3 | 有历史 Path B-like 流程 | 尚未成为 canonical Runner 的必经页 | 第二页三个分区 Module + 第二次独立 SAVE 回执 |
| 最终未发布 | 有 PublishGuard 和部分未发布校验 | 两次 SAVE 与最终状态尚未形成完整同源回执 | `CanonicalReceipt` 汇总两段三铁证与独立最终未发布证明 |
| 暂停/继续/停止 | 已有工程实现和 HVD 方向 | 未在完整 Path B 三商品任务证明 | 仅在安全分区 seam 检查 HVD；在途 mutation 不伪装成已停止 |

审计结论：现有代码不是推倒重写对象。它已经具备 Reader、方案、snapshot、Runner、BrowserAgent、JIT、lease、ledger、PublishGuard 和部分读回能力；正确方向是深化这些 Module，把分散的完整编辑能力收敛进同一冻结合同和同一串行 Runner，而不是再建一套执行系统。

## 4. 产品主流程

### 4.1 店铺与会话

- 登录成功只表示账号会话可用，不代表任务已具备执行作用域。
- 操作员必须在工作台选择一个具体店铺；禁止跨店铺批次，禁止用“全部店铺”或 `shopId=-1` 创建、冻结或批准任务。
- `account_identity_sha256`、`session_ref`、`session_epoch`、`shop_id`、`shop_identity_sha256` 是 selection、方案草稿、preview、snapshot、approval 和 task 的共同上下文。
- 更换账号、浏览器 context、登录 epoch 或店铺时，前端和后端必须共同撤销旧 selection、模板引用、未冻结方案、preview、snapshot alias、approval 和未开始任务输入；不得只清 UI。

### 4.2 方案准备

1. 读取当前店铺草稿，只允许当前 Reader 回包中的稳定商品身份。
2. 多选至少 3 件商品；同一任务只允许一个源店铺，可以覆盖多个目标类目。
3. 读取每件商品当前值、当前类目、当前 Schema、类目能力、DXM 只读模板和本地方案。
4. 工作台按 11 分区展示中文字段、来源、目标值、稳定 binding、必填/条件依赖、转换规则和风险。
5. 解析优先级保持“明确固定值 → 补差规则 → DXM 只读模板 → 当前商品值”；自然语言目标值保存前必须通过真实英文门禁。
6. preview 必须显示每件商品 × 每个分区的来源、归一化、目标值、差异、缺口和可执行性。
7. freeze 将商品顺序、全部分区解析结果、五项能力、两页动作和批准上下文写入不可变 snapshot/hash；Runner 不得执行时重新读取模板改变目标值。

### 4.3 每件商品的完整执行

每件商品严格串行，前一件未形成可判定终态时不得开始下一件：

1. 复核 task、job、queue version、approval、lease、account/session/shop 和冻结商品身份。
2. 打开主编辑页并精确绑定 HTTPS 正式域名、默认端口、URL、商品、店铺、类目和页面 epoch。
3. 读取当前类目与 Schema，与冻结 `categoryId/schemaSha256` 比对。
4. 对 0–10 全部分区和跨分区必经能力执行 zero-write `inspect`；任一失败即 `blocked_pre_write`。
5. 持久化全部可恢复字段的 `preimage`、恢复顺序和不可恢复动作清单。
6. 按 0–10 分区顺序执行 `apply → readback → receipt`；每区结束检查 HVD。
7. 执行视频、批发和翻译的冻结动作；翻译可在字段准备完成后统一触发，但回执归属原字段和 `ContentFinalize`。
8. 对 11 区目标值做最终全量读回，确认不存在额外异常匹配、隐藏字段写入或未批准差异。
9. 对第一次 SAVE 执行动作时 JIT、lease/expiry、队列 CAS 和 ledger reserve/begin；点击后收集业务回包、页面成功态、独立未发布证明。
10. 精确识别 Path B 中间弹窗并执行 `SEMI_MANAGED_CONTINUE_TRANSITION`；该动作不能复用普通发布白名单。
11. 到达 `editFromSmt` 后复核页面、商品、店铺、task/job/snapshot、前序 SAVE command 和回执。
12. 对 `semi_countries`、`semi_goods`、`semi_variants` 执行全量 zero-write inspect、preimage、apply、readback 和 receipt。
13. 对第二次 SAVE 独立执行 JIT、lease、队列 CAS 和 ledger；收集第二组三铁证。
14. 读取最终状态，证明商品仍未发布；形成 item receipt 后才允许推进下一件。

### 4.4 永久禁止

- 最终发布、立即发布、保存并发布、移入待发布及任何等价动作。
- 通过网络请求、脚本、隐藏控件、坐标点击或模糊中文文案绕过可见 UI 与稳定 binding。
- 把 mock、HTML、旧任务、旧 Path A snapshot、历史 `single_save` 或 `claim_only` 当成完整产品证据。
- 在 UNKNOWN 后自动重试 SAVE、中间转换或第二次 SAVE。

## 5. 目标 Module 架构

### 5.1 总体结构

```text
Workbench
  -> PlanPreviewFreeze
  -> FullProductEditOrchestrator
       -> canonical V1TaskRunner
            -> SectionAutomationRegistry
                 -> 11 main-page SectionAutomation Modules
                 -> ContentFinalize Modules
                 -> 3 semi-page SectionAutomation Modules
            -> BindingRegistry
            -> RollbackSafety
            -> ControlledSaveDispatch
            -> CanonicalReceipt
                 -> BrowserAgent / DxmWorkflowAdapter
                 -> JIT + lease + queue CAS + mutation ledger
                 -> PublishGuard
```

`FullProductEditOrchestrator` 是对现有 Runner 的深化，不是新 runner。Runner 仍然是唯一任务队列、状态机和 HVD 权威；Orchestrator 隐藏页面阶段、分区顺序、回执聚合和恢复决策，使调用方只需理解一个深 Interface。

`SectionAutomationRegistry` 是分区代码到 Adapter 的唯一注册 seam。每个分区 Implementation 可以独立维护和测试，但不得拥有独立任务状态、进程、浏览器会话、审批或 mutation ledger。

### 5.2 SectionAutomation Interface

```python
class SectionAutomation(Protocol):
    def inspect(
        self,
        context: ExecutionContext,
        section_plan: FrozenSectionPlan,
    ) -> SectionPreflight: ...

    def capture_preimage(
        self,
        context: ExecutionContext,
        section_plan: FrozenSectionPlan,
    ) -> SectionPreimage: ...

    def apply(
        self,
        context: ExecutionContext,
        section_plan: FrozenSectionPlan,
    ) -> SectionActionResult: ...

    def readback(
        self,
        context: ExecutionContext,
        section_plan: FrozenSectionPlan,
    ) -> SectionReceipt: ...

    def restore(
        self,
        context: ExecutionContext,
        preimage: SectionPreimage,
    ) -> RollbackReceipt: ...
```

Interface 不只包含类型，还包含以下不变量：

- `inspect` 和 `capture_preimage` 禁止产生外部 mutation。
- 商品级所有 `inspect` 全绿之后，任何 `apply` 才能开始。
- `apply` 只消费 frozen section plan；禁止重新读取当前模板后改变目标值。
- `readback` 必须逐字段绑定 command payload 中的 stable field key、binding、expected value/hash 和实际可见控件。
- `restore` 只在未派发任何外部 mutation、页面/商品/类目/Schema 身份仍一致且恢复计划完整时运行。
- 每个 Adapter 必须返回结构化 reason code；不得把 timeout、缺控件或未知回包转成成功。

这个 Interface 的 Depth 来自：所有分区共享同一调用顺序、安全不变量、错误语义、回执与恢复协议；Runner 不再理解每个页面控件的细节。它给调用方提供 Leverage，也把定位、写前校验、读回和故障修复集中到对应 Module，提升 Locality。

### 5.3 共享 Module

| Module | 深 Interface | 主要责任 |
|---|---|---|
| `ShopExecutionContext` | `bind/validate/invalidate` | 统一账号、会话、店铺与 Reader epoch；阻止跨店旧输入 |
| `FullProductEditOrchestrator` | `prepare_item/execute_item/recover_item` | 编排主页面、两次 SAVE、转换、半托管页和终态 |
| `SectionAutomationRegistry` | `resolve(page_kind, section_code)` | 唯一分区 Adapter 注册表；禁止分支散落在 Runner |
| `BindingRegistry` | `resolve/inspect/readback` | 稳定字段身份、控件类型、可见性、唯一匹配和读写共用定位 |
| `RollbackSafety` | `capture/decide/restore` | preimage、严格逆序、外部 mutation 点和 UNKNOWN 分流 |
| `ControlledSaveDispatch` | `authorize/reserve/dispatch/verify` | 动作时 JIT、lease、queue CAS、ledger 与保存三铁证 |
| `CanonicalReceipt` | `append/finalize/verify` | 分区、页面、SAVE、未发布、HVD、运行身份的同源回执 |

两个 Adapter 才建立真实 seam。生产 `BrowserAgent/DxmWorkflowAdapter` 与 deterministic fixture Adapter 都必须跨同一 Interface；测试 Adapter 不得绕过正式授权、协议、ledger 或 action-result 验证。

## 6. 主编辑页 11 分区

分区代码、顺序和中文名称冻结如下。代码可在分区内部继续深化 Module，但外部 Interface 和顺序不能各自漂移。

| 序号 | section code | 中文分区 | 核心配置/动作 | 必需读回与证据 |
|---:|---|---|---|---|
| 0 | `basic_info` | 基本信息 | 标题、语言、类目基础字段 | 英文自然语言、长度、类目和稳定 binding |
| 1 | `dxm_info` | 店小秘信息 | 店小秘内部管理字段 | 目标值、来源和唯一可见控件 |
| 2 | `attribute_info` | 属性信息 | 普通属性、checkbox、多值、条件/子属性 | ID/自定义审计项、Schema 类型、条件依赖闭合 |
| 3 | `product_info` | 产品信息 | 主图、变体、SKU、发货地、插头、大小、批发、有效期 | 图片顺序、SKU 行身份、价格/库存/货值关系、批发配置 |
| 4 | `regional_pricing` | 区域调价信息 | 区域价格与例外 | 区域集合、目标价格、相互约束 |
| 5 | `description_info` | 描述信息 | PC/移动描述、结构化内容、翻译输入 | 英文内容、媒体引用、编辑器可见值 |
| 6 | `packaging_info` | 包装信息 | 重量、尺寸、包装数量 | 单位归一化、数值范围和读回 |
| 7 | `template_main` | 模板信息（主） | 运费、服务、承诺等主模板 | DXM 引用身份、`0` 哨兵处理和最终选择 |
| 8 | `template_tax` | 模板信息（税率） | 税率及相关模板 | 独立模板身份、选择与读回，不与主模板合并 |
| 9 | `compliance_info` | 合规信息 | 合规文本、资质、图片银行 | 资格类型、稳定图片身份、必填状态和回执 |
| 10 | `other_info` | 其他信息 | 其它上架和平台字段 | 明确 Schema、binding、目标值；禁止“兜底随便填” |

### 6.1 分区实现规则

- 写入与读回共用一个 `BindingRegistry`；禁止各维护一套选择器算法。
- 中文名称只用于工作台展示，不能单独作为执行主键。
- 只有可见、唯一、类型相符、页面身份已绑定的控件可写；`input[type=hidden]` 永不作为可见执行控件。
- checkbox 单值、JSON string、数字字符串、分号图片串、`0` 哨兵和无 ID 自定义属性只按显式 Schema-aware 规则归一化，并保留 wire/normalized 审计。
- 多值属性必须聚合，不能把同一属性的合法多个值判成身份冲突。
- 同一分区出现额外匹配、重复 binding 或未冻结字段变化时，整件商品首写前拒绝。

### 6.2 跨分区 ContentFinalize

视频、批发和翻译可能在页面上属于某个分区，但在执行语义上需要跨字段完成，因此建立 `ContentFinalize` 阶段：

- 视频：生成/选择结果回写到冻结的视频字段，记录配额、请求、轮询、可见完成态和最终媒体身份。细节未实证前 fail-closed。
- 批发：配置属于 `product_info`，但 SKU/价格变化后必须重新验证阶梯、最小数量和价格关系。
- 翻译：所有原始目标字段填写完成后统一触发或逐字段翻译，必须证明模式、方向、完成态和最终英文读回；不能因“按钮点击成功”即判成功。
- `ContentFinalize` 结束后必须再次完成 11 区全量读回，再进入第一次 SAVE。

## 7. 半托管页分区

| 顺序 | section code | 中文分区 | 核心不变量 |
|---:|---|---|---|
| S1 | `semi_countries` | 参加国家 | 国家集合与冻结值精确一致，不继承未审核旧值 |
| S2 | `semi_goods` | 货品信息 | SKU 行稳定身份、价格/库存/货值和必填字段闭合 |
| S3 | `semi_variants` | 变种信息 | 变体轴、值、图片、映射与主编辑页 SKU 身份一致 |

第二页不是独立任务。它必须继续使用同一 task/job/item、snapshot、account/session/shop、queue version、approval lease、Git/worktree identity 和前序 SAVE receipt。第二次 SAVE 有独立 command/hash、ledger 记录和三铁证。

## 8. 冻结合同与版本迁移

### 8.1 新合同版本

| 合同 | 目标版本 | 用途 |
|---|---|---|
| 编辑表单 | `dxm_editor_form.v5` | 11 主分区、S1–S3、稳定 binding、能力和中文元数据 |
| 本地方案 | `local_plan_template.v4` | 单店铺作用域、11 分区规则、五项 ALWAYS_ON 和 Path B 决策 |
| 执行快照 | `dxm_batch_draft_save_plan.v2` | 商品顺序、逐区 resolution、两页动作、回滚准备和批准上下文 |
| 分区回执 | `dxm_section_receipt.v1` | inspect/preimage/apply/readback/restore 的结构化事实 |
| 商品回执 | `dxm_full_product_item_receipt.v1` | 11 区、ContentFinalize、双 SAVE、HVD 和最终未发布汇总 |

### 8.2 Snapshot 最小内容

```yaml
schema: dxm_batch_draft_save_plan.v2
execution_mode: batch_draft_save
path: B
shop_context:
  account_identity_sha256: ...
  session_ref: ...
  session_epoch: ...
  shop_id: ...
  shop_identity_sha256: ...
mandatory_capabilities:
  video: true
  translation: true
  wholesale: true
  semi_managed: true
  rollback_preparation: true
items:
  - queue_index: 0
    product_identity: ...
    category_id: ...
    catalog_sha256: ...
    node_identity_sha256: ...
    schema_sha256: ...
    capabilities_sha256: ...
    main_sections: []
    content_finalize: {}
    first_save: {}
    semi_sections: []
    second_save: {}
    expected_final_state: NOT_PUBLISHED
approval_context: {}
publish_allowed: false
```

真实合同还必须包含逐字段来源、wire/normalized 类型、stable binding、当前值、目标值、规则版本、preimage requirement、readback expectation、页面身份、队列版本、幂等键和 canonical hash。

### 8.3 迁移规则

- `local_plan_template.v3`、`dxm_batch_draft_save_plan.v1`、Path A snapshot 和 `/api/edit-batches` 旧批次只保留为 `HISTORICAL_ONLY / READ_ONLY`。
- 禁止静默把旧合同升级为 v4/v2 后进入写入；必须由用户在当前工作台重新打开、重新解析、重新 preview、重新 freeze 和重新批准。
- 新 Runner 只接受明确版本、完整 required fields、同源 hash 和 `publish_allowed=false` 的新快照。
- 迁移期不得并行维护两套可写主线；旧入口必须在开始动作前返回明确 reason code。

## 9. 工作台后续设计

### 9.1 七项主导航保持不变

`工作台、连接店小秘、采集箱选品、铺货方案、开始批量保存、保存结果、设置` 仍是产品一级信息架构。11 分区属于“铺货方案”和任务复核内部结构，不新增 11 个一级导航。

### 9.2 连接店小秘

- 显示账号身份、会话 reason code、可见浏览器状态、Reader readiness 和当前店铺。
- 登录后读取店铺并要求选择一个具体店铺。
- 店铺切换前显示将失效的对象数量；确认后同时调用后端 invalidate，不允许只清前端。

### 9.3 采集箱选品

- 只显示当前店铺草稿；顶部持续显示账号/店铺/Reader epoch。
- 至少选择 3 件；跨页选择保留稳定身份，但任一商品身份漂移立即撤销确认。
- 进入方案前显示类目分布、Schema 可用性、五项能力可探测性和阻断数量。

### 9.4 铺货方案

- 左侧 11 分区 rail，与店小秘真实编辑顺序一致。
- 每个字段显示中文标签、来源、执行策略（继承/补差/固定）、当前值、目标值、约束、binding 状态和影响商品数。
- 视频、批发、翻译、半托管、rollback preparation 显示为锁定的“每件必经”，不得提供关闭开关。
- 模板主区与税率区独立；本地方案与 DXM 只读模板分层展示。
- JSON 只允许进入开发者诊断，不作为运营人员主配置入口。

### 9.5 Preview 与 Freeze

preview 使用“商品 × 分区”矩阵：

- 行：商品及队列顺序；列：0–10、ContentFinalize、第一次 SAVE、S1–S3、第二次 SAVE、最终未发布。
- 单元格状态：`READY / BLOCKED / DRIFT / UNKNOWN / NEEDS_LIVE_EVIDENCE`。
- 展开单元格查看逐字段来源、归一化、目标、binding、规则、风险和预期读回。
- 只有所有商品所有必经列为 READY，才能 freeze；freeze 后任何配置或上下文变化都产生新版本和新 hash。

### 9.6 开始批量保存

- 启动前复核具体店铺、商品数、队列、snapshot hash、批准范围、Git/worktree/package identity 和永久零发布。
- 实时层级：task → item → page → section → `inspect/apply/readback/receipt`。
- HVD 四键显示安全生效点：暂停不打断在途 mutation；停止不把不确定结果伪装成失败或成功。
- 当前 item 未形成终态时，不允许手动跳到下一件。

### 9.7 保存结果

每件商品展示：

- 11 个主分区 receipt；
- 视频、批发、翻译和 rollback preparation receipt；
- 第一次 SAVE 三铁证；
- 中间转换 receipt；
- S1–S3 receipt；
- 第二次 SAVE 三铁证；
- 独立最终未发布证明；
- task/job/queue/snapshot、account/session/shop、Git/worktree/package identity；
- UNKNOWN/人工复核原因及禁止重试说明。

## 10. 状态机、失败与恢复

### 10.1 商品状态

```text
pending
  -> preflighting
  -> ready_to_apply
  -> applying_main_sections
  -> main_readback_verified
  -> first_save_dispatched
  -> first_save_verified
  -> transitioning_to_semi
  -> applying_semi_sections
  -> semi_readback_verified
  -> second_save_dispatched
  -> second_save_verified
  -> not_published_verified
  -> succeeded
```

任何已派发外部 mutation、但无法证明结果的状态只能转为 `unknown / needs_manual_review`，不能落为普通 `failed` 后提示重试。

### 10.2 失败分类

| 场景 | 状态 | 后续动作 |
|---|---|---|
| 全量 preflight 未通过 | `blocked_pre_write` | 零写，记录 reason code，允许修配置后重新 preview/freeze |
| 页面字段已改变，但尚无外部 mutation | `restore_required` | 身份一致且 preimage 完整时严格逆序 restore；否则人工复核 |
| 第一次 SAVE 派发结果不确定 | `unknown` | 停批、禁止自动重试、人工核对真实草稿 |
| 第一次 SAVE 成功，转换或半托管失败 | `needs_manual_review` | 停批，不用再次 SAVE 补偿 |
| 第二次 SAVE 派发或证据不确定 | `unknown` | 停批、禁止自动重试 |
| 最终未发布无法证明 | `needs_manual_review` | 不宣称成功，不继续下一件 |

只允许在外部 dispatch 前，对同值、确定性的可见表单动作进行一次受控纠正；这不是网络 mutation 重试，也不能跨商品复用。

### 10.3 HVD 安全点

- `暂停`：在当前 section receipt 或明确 dispatch 终态后生效。
- `继续`：从持久化的下一个安全 section 开始，不重做已证实 SAVE。
- `停止`：不再派发新动作；在途动作先判定成功/失败/UNKNOWN。
- `急停`：终止新的 BrowserAgent command；已派发动作按 UNKNOWN 处理，不伪造回滚成功。

## 11. 实施里程碑

### R0 · 真相收敛与旧主线冻结

目标：让所有开发入口只指向本方案、唯一主合同和当前运行架构。

- 标记 `local_plan_template.v3`、Path A snapshot、旧 batch bundle 和 `/api/edit-batches` 为只读历史。
- 建立当前 10 区 → 11 区、旧步骤 → Path B 完整步骤的显式差异测试。
- 固定单店铺上下文与切换失效 Interface。
- 建立当前完整 L0 基线，不用聚焦绿测替代。

DoD：旧入口无法创建新写任务；文档、类型、接口和 reason code 对旧合同处置一致；无第三 runner。

### R1 · 11 分区工作台与 Snapshot Compiler

目标：运营人员可在中文结构化界面完成 11 分区配置、preview 和 freeze。

- 发布 `dxm_editor_form.v5`、`local_plan_template.v4`、`dxm_batch_draft_save_plan.v2`。
- 模板主/税率拆分；动态任意深度类目与 CategoryCatalog 进入 runtime/package。
- 商品 × 分区矩阵覆盖五项必经、Path B 两页和双 SAVE。
- 店铺/账号/会话变化使所有下游对象失效。

DoD：≥3 商品、多类目 snapshot 可重复生成相同 canonical hash；遗漏任一必经分区、能力、binding 或当前 Schema 即 fail-closed。

### R2 · SectionAutomation 框架与全量零写预检

目标：建立一个深 Interface 和共享定位/回执/回滚 seam。

- 实现 `SectionAutomationRegistry`、`BindingRegistry`、`SectionReceipt` 和商品级 preflight aggregator。
- 写入与读回使用同一定位 Implementation。
- 在首个 `apply` 前完成主页面全部分区和能力预检。
- 建立生产 Adapter 与 deterministic fixture Adapter；二者通过同一授权和回执验证。

DoD：任一后置字段非法、隐藏、重复或漂移时，页面写入计数为 0；真实 producer→consumer 回执无形状漂移。

### R3 · 11 分区 Implementation

目标：按 0–10 顺序逐区完成真实可见 UI 填写和精确读回。

- 优先级：基本/属性/产品 → 描述/包装 → 区域价格 → 模板主/税率 → 合规/其它 → 店小秘信息。
- 每完成一个 Module，同时提交控件夹具、失败 reason code、preimage、readback 和 receipt 测试。
- 不用固定坐标、中文标签兜底、选择第一项、静默截断或固定 sleep 作为生产策略。

DoD：每区有稳定 Interface 级测试、正式 Adapter 集成测试和至少一个脱敏真实 wire/DOM 形状；跨区全量预检仍保证零写。

### R4 · 五项必经与完整 Path B

目标：每件商品完成视频、批发、翻译、rollback preparation 和半托管双阶段只保存。

- 视频、批发和翻译进入 ContentFinalize 与全量读回。
- 第一次 SAVE、精确 `SEMI_MANAGED_CONTINUE_TRANSITION`、S1–S3、第二次 SAVE 接入同一 Orchestrator。
- 两段 command 分别绑定 snapshot/item/job/queue/lease/runtime/package/前序事实。
- PublishGuard 对最终发布保持绝对拒绝。

DoD：正式 BrowserAgent Adapter 覆盖 SAVE→VERIFY→transition→SEMI_SAVE→VERIFY；任一发布等价动作反例稳定判红。

### R5 · 回执、恢复、HVD 与主线清理

目标：让崩溃、暂停、继续、停止和 UNKNOWN 在 SQLite、Runner、UI 和报告中同义。

- 启动恢复在单事务中更新 task/job/ledger，保留已派发动作的 UNKNOWN 语义。
- `CanonicalReceipt` 逐项从实际 command、ledger 和持久任务重建事实，不接受调用方自签 metadata。
- 删除被新主线替代的重复校验与 shallow pass-through；保留必要历史读适配。
- 模块拆分以 Depth、Leverage 和 Locality 为目标，不按文件行数机械拆分。

DoD：崩溃窗口、lease 过期、队列跳项、VERIFY 篡改、字段证据替换和 Schema 漂移反例全部判红。

### R6 · 门禁、同源包与真实三商品验收

目标：从固定可复验源码，证明真实 UI 完整 Path B 三商品只保存且最终零发布。

- 完整 backend L0 `0 failed / 0 skipped`；不得放宽断言、删测试或 mock 被测对象。
- frontend Node、Chromium、typecheck、Vite；desktop；文档 SelfTest 全绿。
- 统一版本并从固定 Git/worktree 构建同源 portable；隔离 user-data smoke。
- 另取当次真实写入授权，从同一工作台、同一可见会话、同一具体店铺选择 ≥3 个真实 draft。
- 每件商品完成五项必经、11 区、双 SAVE 三铁证、HVD 负向和最终未发布证明。

DoD：证据同时绑定 Git、worktree、package、DB、task、snapshot、account/session/shop 和真实页面；任何 UNKNOWN 都使任务不通过且不自动重试。

## 12. 测试策略

### 12.1 合同层

- 11 分区代码、顺序、必经字段和版本反序列化。
- 旧合同只读、禁止静默升级和禁止创建写任务。
- 单店铺上下文、切换失效、商品顺序、snapshot/hash 与批准精确绑定。
- 五项能力任一缺失、关闭、跳过或改为 false 的反例。

### 12.2 Module 层

- 每个 SectionAutomation 的 inspect/preimage/apply/readback/restore。
- BindingRegistry 的唯一匹配、可见性、类型、重复、额外匹配和页面漂移。
- wire normalization 的真实脱敏形状：数组/JSON string/数字字符串/图片串/哨兵/自定义属性。
- 生产回执 producer 到集中 consumer 的端到端结构测试。

### 12.3 Runner 与安全层

- 只授权当前 running job，前序成功、后序 pending、queue version 未漂移。
- 动作时事务复核 lease ID、批准状态、消费状态和 expiry。
- command payload、逐字段 readback、snapshot、page/category/schema、Git/worktree/package 全量绑定。
- SAVE 与 VERIFY、第一次 SAVE 与中间转换、第二次 SAVE 与最终未发布成对验证。
- crash before dispatch、after dispatch、after response、before receipt 的恢复矩阵。

### 12.4 UI 与包

- 店铺切换后的前后端状态共同撤销。
- 11 分区 rail、中文字段、模板/方案分层、必经能力锁定和商品 × 分区 preview。
- 1100px/860px 断点、七项导航、明暗主题和 HVD 四键真实浏览器 computed-state。
- 源码与 portable 使用相同 schema、资源、版本和后端；启动冲突不能静默复用错误 runtime。

## 13. DXM-TX 文档与数据的持续使用

- `D:\Desktop\py\DXM-TX` 始终只读；本仓只保存脱敏、可追溯、与当前产品有关的事实合同。
- 类目节点映射已经通过 `resources/dxm/category-catalog/category-catalog.v1.json` 与 manifest 迁入，包含 13,216 节点、11,864 叶子和 12 个不可执行冲突叶；它是版本化参考，不替代当前页面 category/Schema 写前权威。
- 后续上游变化只通过显式同步脚本、hash 漂移和人工审阅进入本仓；禁止复制 sessions、Cookie、账号、店铺、商品、模板或 raw 业务样例。
- 视频、翻译、批发、资质图片、切类目和级联的新证据，应先形成脱敏 fixture 与事实条目，再进入 SectionAutomation Implementation。
- 上游文档中的坐标、固定等待、选择第一项、模糊遮罩删除、可关闭能力或 Path A/Path B 二选一，只能标记为历史操作提示，不能成为生产合同。

## 14. 代码落点

以下是目标落点，不表示当前已实现：

| 目标 | 优先深化位置 |
|---|---|
| 单店铺/会话上下文 | `app/backend/src/main.py`、会话门面与前端 workbench state |
| 编辑模型 v5 | `app/backend/src/services/dxm_editor_model.py`、`app/frontend/src/types.ts` |
| 方案 v4 / snapshot v2 | `app/backend/src/batch_edit/plan_template_contract.py`、`plan_snapshot_compiler.py`、`LocalPlanWorkspace.tsx` |
| 统一 Orchestrator | `app/backend/src/execution/v1_runner.py`，复用现有 task/HVD 状态机 |
| 分区 Registry 与 Interface | `app/backend/src/batch_edit/` 中新增深 Module，正式 Adapter 进入 `DxmLoginFlow` seam |
| 共享 binding/readback | 收敛 `DxmLoginFlow` 中重复定位与读回算法，不再各分区复制 |
| 双 SAVE 与安全事实 | 现有 BrowserAgent protocol/worker、JIT、lease、queue CAS、mutation ledger、ActionResult |
| UI 过程与结果 | `app/frontend/src/components/workbench/`，保持七项主导航 |

实现时遵循删除测试：如果删掉一个新 Module，只会让同样复杂度散回多个调用方，说明它提供了 Depth；如果删掉后复杂度也消失，它只是 shallow pass-through，不应保留。

## 15. 非目标与停止条件

本方案不授权：

- 当前轮直接改业务代码、执行真实保存或最终发布；
- 新增第三套 runner、并行多 Worker 或跨店铺任务；
- 恢复旧文档为第二主合同；
- 根据未实证运营建议猜控件、请求、等待时间或默认值；
- 用聚焦测试、mock 浏览器、历史包或旧数据库宣称完成。

任一里程碑遇到缺少真实页面身份、稳定 binding、当前 Schema、回包语义或安全裁决时，将具体事项写入 BLOCKED；跳过后继续不受影响的 Module。只有 R0–R6 的当前同源证据全部满足，才可以申请关闭 `E3_OPEN / BLOCKED`。
