> 由 OpenAI GPT（Codex）AI 生成/维护。

# DXM 工作台与分区自动化统一开发方案

## 版本历史


| 版本     | 日期         | 更新人                  | 概述                                                                                                                                                                                              | 归档                                                                              |
| ------ | ---------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| v1.0.0 | 2026-08-25 | OpenAI GPT（Codex）    | 初版：建立目标架构骨架，冻结结论先行、真相等级、当前系统交叉审计、产品主流程、11 分区、共享 Module、Path B、冻结合同、工作台七导航、状态机与恢复、R0–R6 里程碑、测试策略、DXM-TX 使用、代码落点、非目标与停止条件                                                                         | [archive/DXM-工作台与分区自动化统一开发方案.v1.0.0.md](_archive/DXM-工作台与分区自动化统一开发方案.v1.0.0.md) |
| v1.1.0 | 2026-08-26 | CURSOR（grok）+ 用户深度脑暴 | 见下方 §0A「v1.1.0 修订概述大纲」共 17 项实质更新（N1–N10、M1–M7），覆盖：草稿身份读回、Module 职责切分、per-category capability、ContentFinalize 与 11 区 readback 协调、批发 readback 双层、迁移工具、长动作 HVD、用户主动 cancel、reason code 表、反向 DoD、Path A 清理、版本冻结纪律 | 未归档；修订前 SHA256 `1CDC30ED5E7B0AFB9F5E3927FD052D22137E9710E2B1EEDFD58FE764CAEA905B` |
| v1.1.1 | 2026-08-26 | OpenAI GPT（Codex）+ 用户裁决 | 一致性修订：固定店小秘原生半托管资格门、修正 Path B 时序、唯一 Runner、inspect effect class、长动作授权、cancel/UNKNOWN、草稿 revision checkpoint、三层幂等身份、legacy 只读 Adapter、静态 reason code 与反向 DoD；清除乱码 | 当前 |


> 版本冻结纪律：`section_code`、Module 接口、reason code 命名、snapshot schema 名称一经发布即冻结。后续变更必须走 `v_next`，并在修改前归档完整前一版本。v1.1.0 未留下完整归档，只保留修订前 SHA256，此来源缺口列入 BLOCKED，禁止伪造补档。文档内“已存在 / 当前 / 未接”描述代码事实；“目标 / 应 / R0–R6”描述后续 Implementation。**仅创建本文不能关闭任何 BLOCKED 项，也不能宣称** `MVP_READY` **或** `PROD_READY`**。**



## 0A. v1.1.0 修订概述大纲（变更点索引）

本节为 v1.1.0 的变更导航，便于读者定位新增/修改段落。详细正文见对应章节。

### 0A.1 新增节


| 序号  | 新增节                                     | 主题                                                                   | 落地位置    |
| --- | --------------------------------------- | -------------------------------------------------------------------- | ------- |
| N1  | §4.5 草稿身份与状态读回                          | 每件商品 `apply` 之前先验证草稿身份/状态，漂移即停批                                      | §4 之后   |
| N2  | §5.4 Module 职责切分                        | 明确 Orchestrator 管页面阶段切换，SectionAutomation 只管字段填写；增加 Module 状态标注列     | §5 之后   |
| N3  | §6.3 per-category capability            | 11 分区表增加"per-category capability"列；不可用分区必须 fail-closed 而非 skip       | §6 之后   |
| N4  | §6.4 ContentFinalize 与 11 区 readback 协调 | 明确 ContentFinalize 的回执覆盖范围与 11 区 readback 的跳过条件                      | §6 之后   |
| N5  | §7.2 第二页三区的读回双层                         | `semi_goods` 的批发/价格读回双层契约                                            | §7 之后   |
| N6  | §8.4 旧版本迁移工具与查询路径                       | v3/v1 历史 snapshot 的查询/审计/迁移路径                                        | §8 之后   |
| N7  | §10.4 用户主动 cancel 路径                    | 与 UNKNOWN 自动停批区分                                                     | §10 之后  |
| N8  | §10.5 长动作 HVD 语义                        | 视频生成、翻译这类不可中断动作的暂停/停止/配额追溯                                           | §10 之后  |
| N9  | §12.6 反向 DoD 专章                         | 与 MVP 合同 §11.3 反向流程对齐的 DoD 清单                                        | §12 之内  |
| N10 | §16 Reason Code 体系                      | `E_INSPECT_* / E_BINDING_* / E_DISPATCH_* / E_VERIFY_* / E_SAVE_* / E_POLICY_*` 等静态命名空间与总表 | §16（新增） |




### 0A.2 修改节


| 序号  | 修改节                      | 主要变更                                              |
| --- | ------------------------ | ------------------------------------------------- |
| M1  | §5.1 总体结构图               | 每个 Module 加状态列：✅ 已存在 / 🔄 改造中 / 🆕 新增 / ⛔ 暂缓      |
| M2  | §6.1 分区实现规则              | 明文"分区 Module 不进行页面跳转/Modal 触发/URL 切换"             |
| M3  | §6.2 跨分区 ContentFinalize | 明确 inspect 副作用边界（折叠区打开允许，setValue/click 选择器/上传禁止） |
| M4  | §8.3 迁移规则                | 增加 reason code `E_LEGACY_VERSION_LOCKED` 命名约定        |
| M5  | §10.2 失败分类               | 增加"草稿身份漂移"和"页面身份漂移"独立分类                           |
| M6  | §11 实施里程碑 R5             | DoD 列表增加"删除 Path A 代码 + 独立清理 PR"                  |
| M7  | §12.4 UI 与包测试            | 增加"重复运行/幂等性"测试维度                                  |




### 0A.3 未变更节（仅交叉引用增强）

§0、§1（结论先行）、§2（真相等级）、§3（交叉审计）、§4.1–4.4（产品主流程主体）、§5.1–5.3（Module 架构主体）、§6 表（11 分区基本属性）、§7 表（半托管三区基本属性）、§8.1–8.3（冻结合同主体）、§9（工作台后续设计）、§10.1–10.3、§11（R0–R6 主里程碑）、§13（DXM-TX 使用）、§14（代码落点）、§15（非目标与停止条件）保持 v1.0.0 主体内容不变，仅在交叉引用时指向新增节。

## 0B. v1.1.1 一致性修订摘要

v1.1.1 不扩大功能范围，只修正 v1.1.0 内部无法同时成立的合同，并纳入用户对真实半托管流程的最新裁决：

1. 半托管仍是每件商品必经阶段，但“能否进入 `editFromSmt`”只由店小秘在点击可见“编辑半托管信息”后原生检查；系统不得自建、主动调用或推断另一套资格预检。
2. Path B 固定为主编辑页 11 区与 ContentFinalize → 主保存意图 Modal → 点击“编辑半托管信息”触发店小秘原生门 → 闭合实际第一次 SAVE 三铁证与原生门结果 → 建立同一握手因果 join → 必要时精确中间转换 → `editFromSmt` S1–S3 → 第二次 SAVE。当前不能断言哪个点击触发 SAVE1，因此两者都按 `MAY_DISPATCH_SAVE1` 防护；两组事实已验证且因果同源时，不要求还原墙钟全序。
3. 只有 `V1TaskRunner` 拥有任务调度、商品顺序、状态迁移和 HVD；`FullProductEditOrchestrator` 是其内部深 Module。
4. `inspect` 改用显式 effect class，区分允许的 DOM 展开/只读网络与禁止的字段写入/外部 mutation。
5. 保存 lease 不跨长动作、不冻结、不复活；每个外部动作使用一次性 action grant，并在 dispatch 前实时复核。
6. cancel 只表达用户意图，不能覆盖 `UNKNOWN`、部分保存或已派发动作的真实结果。
7. 草稿身份、服务器 revision checkpoint 和页面 epoch 分离；实际第一次 SAVE 完成后必须建立新的已验证 revision 基线，且第二页首写前必须同时满足 SAVE1 已验证、原生门放行和 `editFromSmt` 页面已绑定。
8. 确定性方案内容 hash、唯一 snapshot instance 和唯一 execution attempt 分离。
9. 旧写 Interface 返回稳定 410；历史 task/job/receipt 继续通过只读 Legacy Adapter 查询。
10. reason code 只允许静态枚举，动态字段进入结构化 `details`；反向 DoD 同步覆盖上述裁决。

---



## 0. 文档定位


| 项       | 结论                                                                                                 |
| ------- | -------------------------------------------------------------------------------------------------- |
| 文档性质    | 目标架构与实施路线，不是当前运行事实                                                                                 |
| 当前状态    | `0.3.0-dev` · `E3_OPEN / BLOCKED`                                                                  |
| 产品主合同   | [完整商品编辑：草稿箱批量只保存](../product/MVP-竖切-草稿箱批量只保存.md)                                                   |
| 当前代码事实  | [当前运行时架构](当前运行时架构.md)                                                                              |
| 方案与快照事实 | [普货方案配置与执行架构](../product/普货方案配置与执行架构.md)                                                           |
| 运营操作来源  | [运营操作详细文档](../runbook/运营操作详细文档.md)                                                                 |
| 上游事实    | [DXM-TX 上游事实合同](../integration/DXM-TX-上游事实合同.md) 与 [类目节点与目录合同](../integration/DXM-TX-类目节点与目录合同.md) |
| 状态裁决    | [PROGRESS](../../PROGRESS.md) / [BLOCKED](../../BLOCKED.md)                                        |


本文把运营人员在店小秘中的真实完整编辑过程，转换成工作台信息架构、冻结合同、单 Runner 编排、分区自动化 Module、证据和验收路线。本文不允许覆盖产品主合同；如有冲突，按“零发布与真实证据 → 当前代码/测试/运行事实 → MVP 合同 → 指定原型体验 → 功能完整 → 速度”裁决。

本文中的“已存在”“当前”“未接”描述现有代码事实；“目标”“应”“R0–R6”描述后续 Implementation。仅创建本文不能关闭任何 BLOCKED 项，也不能宣称 `MVP_READY` 或 `PROD_READY`。

## 1. 结论先行

系统不是“把若干字段批量改掉”的工具，而是“先把一个店铺内多件草稿的完整编辑决策冻结，再由同一个可见会话按商品、页面和分区串行执行，最终只保存、不发布”的运营工作台。

后续开发固定为以下主线：

1. 登录后必须先选择一个具体店铺；选品、模板、方案、快照、审批和任务全部绑定该店铺与当前账号会话。
2. 工作台的方案编辑器按店小秘主编辑页的 11 个分区组织，不再以当前 10 区模型或旧 Path A 步骤作为产品结构。
3. 自动化只有一个 canonical Runner。所谓“按分区做多个自动化”，是把每个分区做成独立、可测试、可维护的 Module，由 Runner 到达对应分区时调用；禁止存在任何第二个拥有队列、任务状态迁移、HVD 或写派发权的 Runner/Runtime。
4. 每件商品无条件经过普通编辑、视频、批发、翻译、半托管和 rollback preparation。主编辑页可观察能力必须在主页面首写前闭合；半托管能否进入只能由店小秘在主保存意图 Modal 中点击“编辑半托管信息”后原生裁决，不得自建资格预检。
5. 完整成功路径固定为 Path B：主编辑页 11 分区 → 主保存意图 Modal → 点击“编辑半托管信息”并接受店小秘原生检查 → 闭合实际第一次 SAVE 三铁证与原生门结果 → 必要时执行精确中间转换 → 精确绑定 `editFromSmt` 三分区 → 第二次 SAVE → 独立最终未发布证明。SAVE1 请求与原生门裁决的实际先后由运行证据决定；两者未同时闭合前禁止第二页首写。
6. “编辑半托管信息”是独立的 `OPEN_SEMI_MANAGED_EDITOR`；特定后续 Modal 中的“继续发布”才是 `SEMI_MANAGED_CONTINUE_TRANSITION`。两者都必须精确绑定上下文；最终发布、立即发布、保存并发布、移入待发布永久禁止。
7. 每个分区都实行 `inspect → capture_preimage → apply → readback → receipt`。外部 mutation 一旦派发而结果不确定，状态只能是 `UNKNOWN`，停批且不得自动重试。



## 2. 真相来源与证据等级



### 2.1 来源优先级

1. 产品和安全不变量：唯一 MVP 主合同。
2. 当前 Implementation：权威 checkout 中的代码、当前测试和运行证据。
3. 店小秘真实操作：运营操作详细文档及 DXM-TX 已脱敏事实合同。
4. 交互体验：指定根原型的信息架构与视觉约束。
5. 建议和推演：运营文档 §12、人工构造夹具和历史原型，只能形成待验证设计，不能直接放行写入。



### 2.2 本方案的事实标签


| 标签                    | 含义                               | 可否直接进入写入合同          |
| --------------------- | -------------------------------- | ------------------- |
| `OBSERVED`            | 已由上游页面、接口或当前代码直接观察               | 仍须通过当前会话写前复核        |
| `PRODUCT_DECISION`    | 用户已拍板的产品或安全要求                    | 可以冻结为目标合同，但不代表已实现   |
| `NEEDS_LIVE_EVIDENCE` | 细节尚缺真实正向回包或控件证据                  | 不可猜测；写前 fail-closed |
| `HISTORICAL_ONLY`     | 旧 Path A、旧 snapshot、旧批次或 mock 叙事 | 只读审计，不得升级为生产写入      |




### 2.3 已确认事实

- `OBSERVED`：主编辑页存在 11 个运营分区；Path B 存在主编辑页保存、中间转换、`editFromSmt` 的 S1–S3 和第二次保存。
- `OBSERVED`：当前代码的 `dxm_editor_form.v4` 仍是 10 区模型，模板主区与税率区尚未按运营流程分开。
- `OBSERVED`：当前 `BATCH_DRAFT_SAVE_STEPS` 和相关 guard 仍带有 Path A 历史结构；另一条旧批次编排也没有成为统一生产主线。
- `OBSERVED`：视频、翻译、批发、半托管和回滚已有若干类、配置或测试 seam，但尚未共同贯穿正式 Runner、BrowserAgent、ledger 和回执。
- `PRODUCT_DECISION`：一个任务只处理一个具体店铺；五项能力对每件商品无条件执行；点击“编辑半托管信息”后由店小秘自身执行原生资格检查，本系统不得建立平行预检；中间精确转换允许自动化；最终发布永久禁止。
- `NEEDS_LIVE_EVIDENCE`：视频额度和轮询、翻译模式与完成态、批发阶梯控件、资质图片稳定身份、切类目差分、非空级联回包，以及运营文档 §12 中的扩展建议。
- `NEEDS_LIVE_EVIDENCE`：半托管原生门的明确通过、明确拒绝和结果不确定三类真实页面/回包形状；在获得证据前不得猜测店铺、类目或账号资格规则。



## 3. 当前系统与真实运营流程的交叉审计


| 真实运营阶段    | 当前系统事实                                   | 主要缺口                            | 本方案处置                                                          |
| --------- | ---------------------------------------- | ------------------------------- | -------------------------------------------------------------- |
| 登录并选择店铺   | 已有可见会话、Reader、店铺与草稿读取                    | 店铺切换后的全部下游状态失效规则仍需统一            | 建立 `ShopExecutionContext`，所有对象冻结 `account/session/shop` 身份     |
| 多选草稿      | 已有草稿列表、≥3 多选与任务输入                        | 需要与具体店铺、当次 Reader epoch 精确绑定    | 店铺或会话变化即撤销 selection、preview、snapshot 和 approval               |
| 11 分区配置   | 当前动态编辑模型为 10 区                           | 模板主/税率未分开，运营规则和执行 binding 未逐区闭合 | 升级 `dxm_editor_form.v5`，固定 0–10 分区代码                           |
| 模板优先补差    | 已有本地方案、DXM 只读模板和 snapshot                | 必经能力、两页执行值和分区回执未进入同一 hash       | `local_plan_template.v4` 与 `dxm_batch_draft_save_plan.v2` 同时冻结 |
| 写前预检      | 已有部分 schema、identity、JIT 和 readback 校验   | 仍分散在多处，不能证明同一页面全部后置字段可执行后才首写       | 主编辑页首写前完成 11 区全量 zero-write preflight；半托管页只在店小秘原生门放行后、其首写前完成 S1–S3 全量 preflight |
| 主编辑页填写    | 现有写入器偏向 legacy 固定字段与 Path A              | 未由通用稳定 binding 驱动 11 区          | 一个 `BindingRegistry`，分区 Module 只消费冻结 binding                   |
| 视频/批发/翻译  | 有局部 Implementation 或配置                   | 未形成每件商品 ALWAYS_ON 主链            | 做成跨分区必经 Module，纳入 preimage、readback 和 receipt                  |
| 第一次 SAVE  | 已有 mutation guard、JIT、lease、ledger 和证据合同 | 需要绑定新的完整 item payload 与 11 区回执  | 由 `ControlledMutationDispatch` 的 SAVE Adapter 消费冻结执行 payload，禁止调用方自签事实            |
| 半托管原生门   | 店小秘在点击“编辑半托管信息”后自行检查能否进入半托管页 | 旧文档把诊断接口或店铺类型误当成可由系统提前裁决的资格 | `OPEN_SEMI_MANAGED_EDITOR` 只点击真实可见按钮并观察平台裁决；禁止自建、主动调用或推断资格预检 |
| 中间转换      | 上游已观察 Path B 弹窗与目标页                      | 旧代码仍可能把 Path A 语义或泛化“继续发布”混入             | 独立 action kind，只允许精确 modal/URL/task/job/action grant 组合               |
| 半托管 S1–S3 | 有历史 Path B-like 流程                       | 尚未成为 canonical Runner 的必经页      | 原生门放行后才解析第二页三个分区 Module，并建立第二次独立 SAVE 回执                                 |
| 最终未发布     | 有 PublishGuard 和部分未发布校验                  | 两次 SAVE 与最终状态尚未形成完整同源回执         | `CanonicalReceipt` 汇总两段三铁证与独立最终未发布证明                           |
| 暂停/继续/停止  | 已有工程实现和 HVD 方向                           | 未在完整 Path B 三商品任务证明             | 仅在安全分区 seam 检查 HVD；在途 mutation 不伪装成已停止                         |


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
7. freeze 将商品顺序、全部分区解析结果、五项必经阶段、两页动作、所需批准策略与作用域写入不可变 snapshot/hash；实际 approval record、action grant 和 save lease 只能在 freeze 后进入 task/attempt 授权事实，不得回写 snapshot。Runner 不得执行时重新读取模板改变目标值。



### 4.3 每件商品的完整执行

每件商品严格串行，前一件未形成可判定终态时不得开始下一件：

1. 复核 task、job、queue version、approval、account/session/shop 和冻结商品身份；视频/翻译/入口转换即时签发并复核一次性 `action_grant_id`，SAVE 即时签发并复核一次性 `save_lease_id`。
2. 打开主编辑页并精确绑定 HTTPS 正式域名、默认端口、URL、商品、店铺、类目和页面 epoch。
3. 读取当前类目与 Schema，与冻结 `categoryId/schemaSha256` 比对。
4. 对 0–10 全部分区和跨分区必经能力执行 zero-write `inspect`；任一失败即 `blocked_pre_write`。
5. 持久化全部可恢复字段的 `preimage`、恢复顺序和不可恢复动作清单。
6. 按 0–10 分区顺序执行 `apply → readback → receipt`；每区结束检查 HVD。
7. 执行视频、批发和翻译的冻结动作；翻译可在字段准备完成后统一触发，但回执归属原字段和 `ContentFinalize`。
8. 对 11 区目标值做最终全量读回，确认不存在额外异常匹配、隐藏字段写入或未批准差异。
9. `FIRST_SAVE` 是一个多步 UI command；`FIRST_SAVE_INTENT` 是其中最早可能触发真实 SAVE 的动作。必须在点击顶部精确“保存”前完成 JIT、队列 CAS、SAVE ledger reserve/begin 并一次性消费 `save_lease_id`，先持久化 `dispatch_state=MAY_HAVE_DISPATCHED`，再把 UI 子状态写为 `awaiting_native_gate`。Modal 出现只证明保存意图进入平台握手，不能单独证明真实 SAVE 请求已经派发或完成；不得为同一 FIRST_SAVE 再签第二张 lease。
10. 精确绑定该 Modal 和可见“编辑半托管信息”按钮，以独立一次性 `action_grant_id` 派发 `OPEN_SEMI_MANAGED_EDITOR`；同一 ledger 事务还必须复核同一 `entry_handshake_id/FIRST_SAVE command`、approval、queue version、expiry policy 和“尚无第二个 SAVE command”。该 command phase 只能是 `IN_FLIGHT` 或 `SAVE_VERIFIED_AWAITING_GATE`；已终止、已拒绝、UNKNOWN 或另一 command 一律拒绝。该 action grant 只授权入口动作，实际 SAVE 若作为平台下游效应出现，仍归属已消费 lease 的同一 FIRST_SAVE command。点击后由店小秘自身执行原生资格检查。本系统不得预先调用 `verifyPopChoiceShop`、根据店铺类型/类目/历史结果推断资格或在点击前宣称资格 READY。
11. 从同一可见会话的网络、页面与 mutation ledger 分别闭合两组事实：店小秘原生门 outcome，以及实际 FIRST_SAVE 的派发和三铁证。当前没有证据可把两者冻结成固定先后顺序；实现必须记录实际事件序列。所有观察到的 SAVE mutation request 必须逐条保存 request identity/hash、causal action、响应与 ledger 关联；未经真实幂等证据证明为同一次平台保存时，`observed_save_request_count > 1` 必须进入 UNKNOWN，禁止因共用 command id 就合并。
12. 店小秘明确拒绝且能证明 SAVE1 未派发时，记录 `outcome_code=semi_entry_rejected_main_not_saved`；若 SAVE1 三铁证已闭合，记录 `outcome_code=semi_entry_rejected_main_saved` 并保留部分保存事实；无法证明 SAVE 最终事实、门结果或同一握手因果绑定时，`execution_state=unknown`。三者均停批且不得降级 Path A。
13. 只有 `first_save_verified AND semi_entry_gate_admitted AND same_entry_handshake_causally_bound` 同时为真，才建立 `entry_handshake_joined`。平台继续显示已实证且上下文精确的特定 Modal 时，也必须在该 join 后才允许执行 `SEMI_MANAGED_CONTINUE_TRANSITION`；该动作不能复用普通发布白名单。
14. 到达 `editFromSmt` 后复核页面、商品、店铺、task/job/snapshot、实际 FIRST_SAVE command/receipt、原生门 receipt 和页面 epoch。只有 `entry_handshake_joined AND semi_page_bound` 同时为真，才建立 `semi_ready_to_apply` 并进入第二页首写。
15. 对 `semi_countries`、`semi_goods`、`semi_variants` 先完成该页面的全量 zero-write inspect 与 preimage，再执行 apply、readback 和 receipt；不得用主保存意图前的推测代替第二页真实检查。
16. 对第二次 SAVE 独立执行 JIT、一次性 lease、队列 CAS 和 ledger；收集第二组三铁证。
17. 读取最终状态，证明商品仍未发布；形成 item receipt 后才允许推进下一件。



### 4.4 永久禁止

- 最终发布、立即发布、保存并发布、移入待发布及任何等价动作。
- 通过网络请求、脚本、隐藏控件、坐标点击或模糊中文文案绕过可见 UI 与稳定 binding。
- 把 mock、HTML、旧任务、旧 Path A snapshot、历史 `single_save` 或 `claim_only` 当成完整产品证据。
- 在 UNKNOWN 后自动重试 SAVE、中间转换或第二次 SAVE。



### 4.5 商品身份、草稿 revision 与页面 epoch（v1.1.1 修订）

商品在编辑期间可能被店小秘自动保存、运营同时操作、平台打回或会话过期。身份、服务器 revision 和浏览器页面实例是三个不同生命周期，禁止压成一个自造 token。

**4.5.1 三层身份事实**

```yaml
item_runtime_identity:
  product_identity_sha256: ...   # 只由当前 account/shop/product/source URL 等已观察稳定身份构成
  draft_revision:
    source: pageList_or_editor    # 必须注明真实来源
    value: ...                    # 真实 revision/lastModified；无稳定事实时不得补造
    captured_at: ...
  page_identity:
    page_kind: main_editor
    canonical_https_url: ...
    page_epoch: ...               # 每次装载页面分配的新 epoch
```

- `product_identity_sha256` 证明“还是同一件商品”，不能只用裸 `product_id`，也不能加入未观察的“一个或两个不可见稳定字段”。
- `draft_revision` 证明“服务器草稿是否被更新”。Reader/编辑页若没有可稳定复核的 revision 事实，必须标 `NEEDS_LIVE_EVIDENCE` 并阻断真实执行。
- `page_epoch` 只证明“还是同一浏览器页面实例”，不能替代商品或服务器 revision。

**4.5.2 阶段 checkpoint**

每件商品至少持久化以下 checkpoint：`selected`、`pre_main_apply`、`pre_main_save`、`main_save_intent_dispatched`、`semi_entry_modal_bound`、`pre_semi_entry`、`post_main_save`、`post_semi_entry`、`entry_handshake_joined`、条件性的 `post_semi_transition`、`semi_page_bound`、`semi_ready_to_apply`、`pre_semi_apply`、`pre_semi_save`、`post_semi_save`。每个 checkpoint 绑定商品身份、服务器 revision、page kind/page epoch、task/job/snapshot 和前序 action receipt。

- `selected → pre_main_apply → pre_main_save`：服务器 revision 应与当次 Reader 基线一致；出现外部漂移即停批。
- `pre_main_save → main_save_intent_dispatched → semi_entry_modal_bound → pre_semi_entry` 是已观察的 UI 顺序；真实 FIRST_SAVE 写请求由哪个点击触发尚无 network/ledger 定论，`post_main_save` 与 `post_semi_entry` 必须按实际事实分别记录并因果绑定同一 handshake，禁止伪造线性顺序，也不得仅因墙钟全序不可还原而判 UNKNOWN。
- 实际第一次 SAVE 成功后，必须用当前会话只读 Reader 返回的显式服务器 revision 建立新的 `post_main_save` 基线；业务回包若也带 revision 必须与其一致，页面成功态和 page epoch 只能作旁证，不能替代服务器 revision。
- 原生门放行后写入 `post_semi_entry`。`post_main_save` 与 `post_semi_entry` 均已验证且能证明因果绑定同一握手时，先建立 `entry_handshake_joined`；不要求还原二者的墙钟全序。实际发生特定中间转换时再写 `post_semi_transition`。精确到达正式 HTTPS `editFromSmt` 后，以新的 URL、page epoch、商品身份和可观察服务器 revision 建立 `semi_page_bound`。只有 `entry_handshake_joined` 与 `semi_page_bound` 均存在且互相一致，才建立 `semi_ready_to_apply`，`pre_semi_apply` 必须从它派生；任一最终事实、身份一致性或同一握手因果绑定无法证明时，令 `execution_state=unknown` 并停批。
- 第二次 SAVE 前只能与 `semi_page_bound` 后建立的半托管阶段基线比较，**不得再与最初冻结 revision 机械比较**，否则系统会把自己的第一次 SAVE 或平台原生转换误判为外部漂移。
- 第二次 SAVE 后建立 `post_semi_save` revision，并与最终未发布证明共同进入商品回执。

漂移检测由 `ShopExecutionContext` 的唯一 Interface 负责；Orchestrator 只提交 checkpoint 请求，不自行拼 hash。明确漂移记录 `outcome_code=drift_detected_pre_save` 并按事实设置 `manual_review_required`；外部动作已经派发但结果无法证明时仍必须令 `execution_state=unknown`。

**4.5.3 草稿消失**

如果当前同源 Reader 中该商品已被删除或移出草稿箱，落 `draft_missing`。已验证的 SAVE receipt 永久保留；不得用“再保存一次覆盖”恢复，不得跳过 revision 检查，也不得在 apply 中途发现漂移后伪装成功。



## 5. 目标 Module 架构



### 5.1 总体结构

```text
Workbench
  -> PlanPreviewFreeze
       -> immutable snapshot + approval + task

canonical V1TaskRunner
  -> FullProductEditOrchestrator
       -> SectionAutomationRegistry
            -> 11 main-page SectionAutomation Modules
            -> ContentFinalize Modules
            -> 3 semi-page SectionAutomation Modules
        -> BindingRegistry
        -> RollbackSafety
        -> ControlledMutationDispatch
             -> BrowserAgent / DxmWorkflowAdapter
             -> action-time JIT + one-shot grant + queue CAS + mutation ledger
             -> PublishGuard
        -> CanonicalReceipt（只消费 Dispatcher/Section/Rollback 的持久事实）
```

只有 `V1TaskRunner` 拥有任务调度、商品顺序、状态迁移和 HVD 控制权。`FullProductEditOrchestrator` 是由它调用的内部深 Module，不是新 runner；它隐藏页面阶段、分区顺序、回执聚合和恢复决策，使 Runner 只需理解一个高 Leverage Interface。

`SectionAutomationRegistry` 是分区代码到 Adapter 的唯一注册 seam。每个分区 Implementation 可以独立维护和测试，但不得拥有独立任务状态、进程、浏览器会话、审批或 mutation ledger。

R0 必须删除 `BatchExecutionRuntime` 的执行装配及其调度、批准、任务推进和写派发 Interface；不要把 Runtime 本身伪装成 Adapter。历史数据由独立 `LegacyReadAdapter` 查询，旧写请求由 410 tombstone 拒绝。删除第二调度器后，复杂度应进入 `V1TaskRunner` 与其内部 Orchestrator，而不是散回路由或 Worker。

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
- `restore` 只在**当前 page stage** 的 preimage 已建立、尚未派发会提交该阶段页面变化的外部 mutation、页面/商品/类目/Schema 身份仍一致且恢复计划完整时运行。此前已闭合并验证的 SAVE1 不阻止恢复尚未派发 SAVE2 的半托管页面变化；任何已派发但结果未知的当前阶段 mutation 仍禁止 restore。
- 每个 Adapter 必须返回结构化 reason code；不得把 timeout、缺控件或未知回包转成成功。

这个 Interface 的 Depth 来自：所有分区共享同一调用顺序、安全不变量、错误语义、回执与恢复协议；Runner 不再理解每个页面控件的细节。它给调用方提供 Leverage，也把定位、写前校验、读回和故障修复集中到对应 Module，提升 Locality。

### 5.3 共享 Module


| Module                        | 深 Interface                              | 主要责任                                    |
| ----------------------------- | ---------------------------------------- | --------------------------------------- |
| `ShopExecutionContext`        | `bind/validate/invalidate`               | 统一账号、会话、店铺与 Reader epoch；阻止跨店旧输入        |
| `FullProductEditOrchestrator` | `prepare_item/execute_item/recover_item` | 编排主页面、两次 SAVE、转换、半托管页和终态                |
| `SectionAutomationRegistry`   | `resolve(page_kind, section_code)`       | 唯一分区 Adapter 注册表；禁止分支散落在 Runner         |
| `BindingRegistry`             | `resolve/inspect/readback`               | 稳定字段身份、控件类型、可见性、唯一匹配和读写共用定位             |
| `RollbackSafety`              | `capture/decide/restore`                 | preimage、严格逆序、外部 mutation 点和 UNKNOWN 分流 |
| `ControlledMutationDispatch`  | `dispatch(frozen_action)`                | 视频/翻译/半托管转换使用一次性 action grant；两次 SAVE 使用一次性 save lease；共同执行动作时 JIT、queue CAS 和 ledger，SAVE Adapter 另收三铁证 |
| `CanonicalReceipt`            | `append/finalize/verify`                 | 分区、页面、SAVE、未发布、HVD、运行身份的同源回执            |

授权事实按动作种类冻结，禁止混称或互用：

| 动作 | 唯一授权事实 | 消费点 |
| --- | --- | --- |
| 视频/翻译远端动作、`OPEN_SEMI_MANAGED_EDITOR`、`SEMI_MANAGED_CONTINUE_TRANSITION` | 一次性 `action_grant_id` | 对应 action ledger `BEGIN` 的同一事务；`OPEN_SEMI_MANAGED_EDITOR` 还复核同一 `entry_handshake_id/FIRST_SAVE command`，其 phase 只能为 `IN_FLIGHT` 或 `SAVE_VERIFIED_AWAITING_GATE`，但 action grant 本身不授权 SAVE |
| `FIRST_SAVE` | 一次性 `save_lease_id` | 在最早可能触发 SAVE 的 `FIRST_SAVE_INTENT` 前，于 SAVE ledger `BEGIN` 同一事务消费；多步握手只允许一个 command/lease |
| `SECOND_SAVE` | 一次性 `save_lease_id` | 在半托管页精确 SAVE 点击前，于 SAVE ledger `BEGIN` 同一事务消费 |

两类事实都绑定精确 payload、execution attempt、task/job/item、queue version、approval record、expiry 和 runtime identity。`action_grant_id` 不能授权 SAVE，`save_lease_id` 也不能授权视频、翻译或转换。

入口握手的 command effect set 必须冻结，不能把按钮假定成单一副作用：

| command | `possible_effects` | 点击前原子要求 |
| --- | --- | --- |
| `FIRST_SAVE_INTENT` | `OPEN_MODAL`, `MAY_DISPATCH_SAVE1` | `BEGIN IMMEDIATE` 内复核 SAVE approval/queue/runtime，消费唯一 `save_lease_id`，建立 FIRST_SAVE ledger，并先写本 action attempt=`MAY_HAVE_DISPATCHED` |
| `OPEN_SEMI_MANAGED_EDITOR` | `NATIVE_GATE`, `MAY_DISPATCH_SAVE1` | 同一事务消费独立 `action_grant_id`，复核同一握手/FIRST_SAVE command（phase=`IN_FLIGHT | SAVE_VERIFIED_AWAITING_GATE`）及 approval/queue，并先写本 action attempt=`MAY_HAVE_DISPATCHED`；不得签发第二张 SAVE lease |

真实 Evidence Pack 若以后证明某一 action 绝不可能触发 SAVE1，才允许通过版本化合同把 `MAY_DISPATCH_SAVE1` 从该 effect set 删除。在此之前，任一 action 点击后崩溃或失去证据都按“可能已派发 SAVE”恢复为 `execution_state=unknown`，不能退回 reserve/pre-write。

逻辑 command 的唯一性不等于物理请求唯一。FIRST_SAVE receipt 必须枚举 `observed_save_request_count`、每条 `save_request_identity_sha256`、`request_payload_sha256`、`causal_action_kind/action_attempt_id`、response identity 和 ledger sequence。真实证据未证明多条请求是平台对同一次保存的幂等重放前，观察到两条或以上不同 mutation request 必须使用 `E_SAVE_DUPLICATE_REQUEST_UNPROVEN` 进入 UNKNOWN；不得按相同 command id、URL 或 payload hash 静默去重。


两个 Adapter 才建立真实 seam。生产 `BrowserAgent/DxmWorkflowAdapter` 与 deterministic fixture Adapter 都必须跨同一 Interface；测试 Adapter 不得绕过正式授权、协议、ledger 或 action-result 验证。

### 5.4 Module 职责切分（v1.1.0 新增）

§5.1 的总体结构图描述了“哪些 Module 存在”，但还要固定任务权威。**Runner 调度任务、商品顺序与 HVD；Orchestrator 只编排当前单件商品内部页面阶段；Section Module 履行冻结字段动作。** 这三层不得互相取得对方的状态迁移权。

#### 5.4.1 职责矩阵


| 职责                               | Orchestrator | SectionAutomation | ContentFinalize | SectionAutomationRegistry | BindingRegistry | RollbackSafety | ControlledMutationDispatch | CanonicalReceipt |
| -------------------------------- | ------------ | ----------------- | --------------- | ------------------------- | --------------- | -------------- | ---------------------- | ---------------- |
| 页面阶段切换（主编辑/转换 modal/editFromSmt） | ✅            | ❌                 | ❌               | ❌                         | ❌               | ❌              | ❌                      | ❌                |
| Tab 切换（同一页面内切换 11 区 Tab）         | ✅            | ❌                 | ❌               | ❌                         | ❌               | ❌              | ❌                      | ❌                |
| 找到并填写本分区字段                       | ❌            | ✅                 | ✅（跨字段）          | ❌                         | ❌               | ❌              | ❌                      | ❌                |
| 解析 `section_code` → Module 实例    | ❌            | ❌                 | ❌               | ✅                         | ❌               | ❌              | ❌                      | ❌                |
| 解析 binding → 控件                  | ❌            | ✅（调用）             | ✅（调用）           | ❌                         | ✅（唯一权威）         | ❌              | ❌                      | ❌                |
| preimage 捕获与严格逆序恢复               | ❌            | ✅（本分区）            | ✅（跨字段）          | ❌                         | ❌               | ✅（统一编排）        | ❌                      | ❌                |
| 外部动作派发时 JIT/action grant 或 save lease/CAS/ledger | ❌（只决定下一阶段） | ❌ | ✅（提出冻结动作） | ❌ | ❌ | ❌ | ✅（唯一权威） | ❌ |
| Receipt 收集、汇总、verify             | ❌            | ✅（产出）             | ✅（产出）           | ❌                         | ❌               | ✅（产出）          | ✅（产出）                  | ✅（唯一权威）          |
| 业务成功态/页面成功态/未发布证明 三铁证            | ❌            | ❌                 | ❌               | ❌                         | ❌               | ❌              | ✅（收集）                  | ✅（汇总 verify）     |


**铁律**：

1. **页面阶段切换由 Orchestrator 唯一负责**。SectionAutomation 不得调用跳转、URL 切换、Modal 触发；它必须假设"我已经在正确的页面、正确的 Tab"。
2. **Binding 解析由 BindingRegistry 唯一负责**。SectionAutomation 不得自己写 XPath、不得维护自己的选择器缓存；它必须通过 `binding_registry.resolve(field_key, context)` 拿到唯一匹配。
3. **外部 mutation 派发由 ControlledMutationDispatch 唯一负责**。SectionAutomation/Orchestrator 都不得直接派发视频/翻译远端请求、半托管转换或 SAVE；调用方只能提交 frozen action，由 Dispatcher 按动作种类签发/消费 `action_grant_id` 或 `save_lease_id`，并完成动作时 JIT、queue CAS、ledger 和精确 command 绑定。
4. **Receipt 由 CanonicalReceipt 唯一汇总**。各 Module 产出"事实"（SectionReceipt / Preimage / SaveResult），但最终的 `dxm_full_product_item_receipt.v1` 必须由 CanonicalReceipt 重组，不接受调用方自签 metadata。



#### 5.4.2 §5.1 结构图 Module 状态标注（v1.1.0 新增）


| Module                          | 状态  | 里程碑     | 备注                                                          |
| ------------------------------- | --- | ------- | ----------------------------------------------------------- |
| `ShopExecutionContext`          | 🔄  | R0 → R2 | R0 冻结接口；R2 与草稿身份读回联动                                        |
| `FullProductEditOrchestrator`   | 🆕  | R2      | 对现有 Runner 的深化，新增单件商品内部 11 区与页面阶段编排职责；不拥有任务调度权             |
| `SectionAutomationRegistry`     | 🆕  | R2      | 唯一注册 seam                                                   |
| `SectionAutomation` × 11        | 🆕  | R3      | R3 逐区实现，建议 R2 末先做 1 个（`packaging_info`）                     |
| `BindingRegistry`               | 🔄  | R2      | 现有选择器算法收敛                                                   |
| `ContentFinalize` × 3（视频/批发/翻译） | 🆕  | R4      | 与 SectionAutomation 接口一致，但跨字段                               |
| `RollbackSafety`                | 🔄  | R2 → R5 | R0 已有 `RollbackManager` 骨架，R2 深化持久 preimage，R5 接 UNKNOWN 语义 |
| `ControlledMutationDispatch`    | 🔄  | R2      | 现有 JIT/授权/CAS/ledger 逻辑分散，尚未收敛为单一深 Module；先落 save lease Adapter，再接 action grant 动作 |
| `CanonicalReceipt`              | 🆕  | R5      | 删除浅层 `EvidenceCollector` 平行实现                               |


图例：✅ 已存在（DXM-TX 之前的）/ 🔄 改造中 / 🆕 新增 / ⛔ 暂缓

## 6. 主编辑页 11 分区

分区代码、顺序和中文名称冻结如下。代码可在分区内部继续深化 Module，但外部 Interface 和顺序不能各自漂移。


| 序号  | section code       | 中文分区     | 核心配置/动作                    | 必需读回与证据                         |
| --- | ------------------ | -------- | -------------------------- | ------------------------------- |
| 0   | `basic_info`       | 基本信息     | 标题、语言、类目基础字段               | 英文自然语言、长度、类目和稳定 binding         |
| 1   | `dxm_info`         | 店小秘信息    | 店小秘内部管理字段                  | 目标值、来源和唯一可见控件                   |
| 2   | `attribute_info`   | 属性信息     | 普通属性、checkbox、多值、条件/子属性    | ID/自定义审计项、Schema 类型、条件依赖闭合      |
| 3   | `product_info`     | 产品信息     | 主图、变体、SKU、发货地、插头、大小、批发、有效期 | 图片顺序、SKU 行身份、价格/库存/货值关系、批发配置    |
| 4   | `regional_pricing` | 区域调价信息   | 区域价格与例外                    | 区域集合、目标价格、相互约束                  |
| 5   | `description_info` | 描述信息     | PC/移动描述、结构化内容、翻译输入         | 英文内容、媒体引用、编辑器可见值                |
| 6   | `packaging_info`   | 包装信息     | 重量、尺寸、包装数量                 | 单位归一化、数值范围和读回                   |
| 7   | `template_main`    | 模板信息（主）  | 运费、服务、承诺等主模板               | DXM 引用身份、`0` 哨兵处理和最终选择          |
| 8   | `template_tax`     | 模板信息（税率） | 税率及相关模板                    | 独立模板身份、选择与读回，不与主模板合并            |
| 9   | `compliance_info`  | 合规信息     | 合规文本、资质、图片银行               | 资格类型、稳定图片身份、必填状态和回执             |
| 10  | `other_info`       | 其他信息     | 其它上架和平台字段                  | 明确 Schema、binding、目标值；禁止“兜底随便填” |


> v1.1.0 补充：表格的"必需读回与证据"列适用于全类目统一可执行情况；具体到每个类目时，必须参考 §6.3 per-category capability 表。



### 6.1 分区实现规则

- 写入与读回共用一个 `BindingRegistry`；禁止各维护一套选择器算法。
- 中文名称只用于工作台展示，不能单独作为执行主键。
- 只有可见、唯一、类型相符、页面身份已绑定的控件可写；`input[type=hidden]` 永不作为可见执行控件。
- checkbox 单值、JSON string、数字字符串、分号图片串、`0` 哨兵和无 ID 自定义属性只按显式 Schema-aware 规则归一化，并保留 wire/normalized 审计。
- 多值属性必须聚合，不能把同一属性的合法多个值判成身份冲突。
- 同一分区出现额外匹配、重复 binding 或未冻结字段变化时，整件商品首写前拒绝。
- **（v1.1.0 新增）分区 Module 不进行页面跳转、Modal 触发、URL 切换**。该责任归 Orchestrator；Module 仅在已就位的页面/Tab 内完成字段查找、填写与读回。



### 6.2 跨分区 ContentFinalize

视频、批发和翻译可能在页面上属于某个分区，但在执行语义上需要跨字段完成，因此建立 `ContentFinalize` 阶段：

- 视频：生成/选择结果回写到冻结的视频字段，记录配额、请求、轮询、可见完成态和最终媒体身份。细节未实证前 fail-closed。
- 批发：配置属于 `product_info`，但 SKU/价格变化后必须重新验证阶梯、最小数量和价格关系。
- 翻译：所有原始目标字段填写完成后统一触发或逐字段翻译，必须证明模式、方向、完成态和最终英文读回；不能因“按钮点击成功”即判成功。
- `ContentFinalize` 结束后必须再次完成 11 区全量读回，再进入第一次 SAVE。

> **（v1.1.1 修订）inspect effect class**：`inspect` 与 `capture_preimage` 的每个实际 effect 必须归类并写入 receipt。允许 `PURE_READ`、`UI_REVEAL`（仅 expand/scroll/hover，不改变字段值）和 `READ_ONLY_DXM_REQUEST`（仅显式只读 allowlist，mutation request 数为 0）。禁止 `FORM_VALUE_WRITE`、`FILE_UPLOAD`、`LONG_ACTION_DISPATCH`、`SAVE_OR_PUBLISH` 及任何未声明 effect。DOM 因展开/滚动产生的展示状态变化不等于字段 mutation；不得用“任何 DOM mutation”这种笼统规则把合法 inspect 判红。



### 6.3 类目字段适用性与产品必经阶段（v1.1.1 修订）

必须把“某类目有没有某个字段”与“产品阶段能否跳过”分开。11 个 Section Module 对每件商品都必须运行并产出 receipt；当前 Schema 明确不存在某类字段时，可以得到可审计的空字段结果，但这不是 `skip`。视频、翻译、批发、半托管和 rollback preparation 是产品级 `ALWAYS_ON` 阶段，不能被类目适用性关闭。

#### 6.3.1 Section 字段决策

| 状态 | 含义 | 处置 |
| --- | --- | --- |
| `FIELDS_REQUIRED_BY_SCHEMA` | 当前实时 Schema/页面明确存在本分区字段 | 全部 required/condition/dependency 闭合，任一缺口 fail-closed |
| `NO_FIELDS_BY_SCHEMA` | 当前实时 Schema 明确证明本分区字段集合为空 | Module 仍运行 inspect/readback 并产出零字段 receipt；不得写成 skip/optional |
| `UNRESOLVED_BLOCKED` | Schema、页面或 capability hash 无法证明前两种之一 | `blocked_pre_write`；不得猜字段、猜控件或默认空集合 |

`OPTIONAL_PLAN`、`REQUIRED_IF_APPLICABLE` 不再作为执行状态。方案可以为字段选择继承/补差/固定策略，但不能关闭 Section Module 或五项必经阶段。

#### 6.3.2 五项必经阶段

| 阶段 | 首次可判定时机 | 不可用时 |
| --- | --- | --- |
| 视频 | 主编辑页全量 preflight | 首个主页面字段写入前阻断；远端生成已派发而结果不确定则 UNKNOWN |
| 翻译 | 主编辑页全量 preflight | 首个主页面字段写入前阻断；远端动作已派发按外部 mutation 规则处理 |
| 批发 | 主编辑页全量 preflight | 首个主页面字段写入前阻断；不得以类目 optional 静默跳过 |
| rollback preparation | 每个页面首次 apply 前 | preimage/恢复计划不可证明即阻断该页面写入 |
| 半托管 | 主保存意图 Modal 中点击“编辑半托管信息” | 不做本地资格预检；真实 SAVE1 与门 outcome 分别观察，明确拒绝按是否已保存分类，不确定则 `execution_state=unknown`，均不得降级 Path A |

#### 6.3.3 多类目任务

§4.2 允许同一任务覆盖多个目标类目。snapshot 必须为每件商品独立冻结 `target_category_id`、`category_capability_hash` 和 11 个 Section 字段决策；同一任务中不同商品可以得到不同的字段集合，但每个 Section 都必须有明确、可重算的决策和 receipt。半托管原生门不属于 `category_capability_hash`，不得从类目 catalog 推断其结果。



### 6.4 ContentFinalize 与 11 区 readback 协调（v1.1.0 新增）

§6.2 要求"ContentFinalize 结束后必须再次完成 11 区全量读回"。但视频、批发、翻译可能向已 readback 过的分区字段回写（如视频结果写入 `product_info` 分区的视频字段）。本节规定协调规则。

#### 6.4.1 协调原则

1. **ContentFinalize 的回执是它写过字段的唯一 readback owner**，后续主页面聚合器按 `delegated_to` 验证覆盖，不重复执行另一套定位。
2. **委托必须显式且精确**。`SectionReceipt.readback` 标注 `delegated_to=content_finalize.video`，聚合器要求字段集合与 frozen payload 完全相等；少字段、多字段或重复 owner 都判红。
3. **未委托字段照常由所属 Section readback**。最终主页面回执必须证明所有冻结字段恰好被一个 owner 覆盖。
4. **失败按动作事实分类**。外部 mutation 尚未派发时，`outcome_code` 为 `blocked_pre_write` 或 `restore_required`；已派发且结果不确定时才令 `execution_state=unknown`；明确业务拒绝使用静态 `reason_code` 并按处置设置 `manual_review_required`。不得把所有失败一律写成 UNKNOWN，也不得把不确定降成普通失败。



#### 6.4.2 双层 readback 流程

```text
for each main section in 0..10:
  apply(section) → immediate readback(non-delegated fields) → section receipt
end for
ContentFinalize(video/wholesale/translation)
readback(delegated fields by their sole owner)
aggregate/final-verify(all 11 main sections)
FIRST_SAVE_INTENT(action-time JIT + consume one save lease + SAVE ledger begin)
  → bind semi-entry Modal; do not infer SAVE1 completion
OPEN_SEMI_MANAGED_EDITOR(independent action grant + revalidate same active FIRST_SAVE handshake command)
  → store-native eligibility gate
  → observe actual FIRST_SAVE dispatch/proofs and gate outcome in their real order
       ├─ admitted AND FIRST_SAVE verified
       │    → optional exact SEMI_MANAGED_CONTINUE_TRANSITION
       │    → bind editFromSmt
       │    → inspect/preimage(all S1–S3, zero write)
       │    → apply/readback(S1–S3) + semi relationship verification
       │    → SECOND_SAVE(independent JIT/save lease/ledger + three proofs)
       │    → independent NOT_PUBLISHED verification
       ├─ rejected AND SAVE1 not dispatched → execution_state=stopped; outcome_code=semi_entry_rejected_main_not_saved
       ├─ rejected AND SAVE1 verified → execution_state=stopped; outcome_code=semi_entry_rejected_main_saved; manual_review_required=true
       └─ SAVE1 fact, gate outcome, or same-handshake causal binding uncertain → UNKNOWN; stop batch
```



#### 6.4.3 与 §6 表中"批发"的归属关系

§6 表把"批发"放在 `product_info` 分区；§6.2 又说"SKU/价格变化后必须重新验证"。本节明确：

- `product_info` **分区的第一次 readback 只覆盖"非批发"字段**（主图、变体、SKU 列表、发货地等）
- **批发阶梯、最小数量、价格/库存/货值关系由 ContentFinalize 阶段验证**
- **批发验证必须在所有可能影响 SKU、价格、库存和货值的主分区 apply/readback 完成后才能跑**，作为 ContentFinalize 的一部分运行，并在主页面 aggregate/final-verify 与 FIRST_SAVE 之前完成。

这与 §5.4 职责矩阵并不冲突：批发规则的"填写责任"属于 `product_info` 分区，"价格/阶梯/货值关系验证"属于 ContentFinalize（批发 Module）。

## 7. 半托管页分区


| 顺序  | section code     | 中文分区 | 核心不变量                     |
| --- | ---------------- | ---- | ------------------------- |
| S1  | `semi_countries` | 参加国家 | 国家集合与冻结值精确一致，不继承未审核旧值     |
| S2  | `semi_goods`     | 货品信息 | SKU 行稳定身份、价格/库存/货值和必填字段闭合 |
| S3  | `semi_variants`  | 变种信息 | 变体轴、值、图片、映射与主编辑页 SKU 身份一致 |


第二页不是独立任务。它必须继续使用同一 task/job/item、snapshot、account/session/shop、queue version、approval context、Git/worktree identity 和已验证的实际 FIRST_SAVE receipt；入口动作和可选转换分别取得独立 `action_grant_id`，第二次 SAVE 取得独立 `save_lease_id`。第二次 SAVE 有独立 command/hash、ledger 记录和三铁证。

### 7.1 店小秘原生半托管入口门（v1.1.1 新增）

半托管是产品必经阶段，但资格裁决不属于本系统的 `CapabilityContract`：

1. 主编辑页填写、ContentFinalize 和最终读回全部完成后，Runner/Orchestrator 只能向 `ControlledMutationDispatch` 提交冻结的 `FIRST_SAVE_INTENT` 请求，由 Dispatcher 唯一派发；半托管提示 Modal 出现后才能请求 `OPEN_SEMI_MANAGED_EDITOR`。Modal 出现不等于第一次 SAVE 已完成。
2. `ControlledMutationDispatch` 精确绑定当前主保存意图、Modal、可见“编辑半托管信息”按钮、task/job/snapshot、商品、页面和一次性 action grant 后点击，并继续观察同一因果链上的实际 FIRST_SAVE 派发。
3. 点击后由店小秘自身检查是否能进入半托管界面。本系统**禁止**主动调用 `verifyPopChoiceShop` 作为执行预检，禁止用 `shopSmtTypeMap`、店铺类型、类目、模板或历史成功记录推断资格，也禁止在点击前写“资格 READY”。
4. 店小秘内部产生的只读/检查请求可以作为原生门证据被观察，但不得由本系统复刻为平行判断器。
5. 明确放行后还必须闭合实际 SAVE1 三铁证，并证明两组事实属于同一入口握手，建立 `entry_handshake_joined`；只有此后出现已实证的特定中间 Modal，才允许 `SEMI_MANAGED_CONTINUE_TRANSITION`。最终必须精确到达正式 HTTPS `editFromSmt` 页面。
6. 明确拒绝时必须按 ledger/网络最终事实区分：SAVE1 未派发则 `outcome_code=semi_entry_rejected_main_not_saved`；SAVE1 已完成三铁证则 `outcome_code=semi_entry_rejected_main_saved` 且 `manual_review_required=true`。SAVE1 最终事实、门结果或同一 handshake 因果绑定无法证明时 `execution_state=unknown`。三者都不得继续第二次 SAVE、自动重试或降级 Path A。
7. 平台明确放行也不等于可继续转换或开始填写；转换前必须 `entry_handshake_joined`，S1–S3 首写前还必须正式 `editFromSmt` 页面身份闭合。

工作台 preview/freeze 只冻结 `semi_entry.required=true`、两个 action kind、预期页面身份、拒绝/不确定处置和证据策略；资格状态显示 `RUNTIME_NATIVE_GATE_REQUIRED`，不冻结伪造的 `eligible=true`。

### 7.2 半托管读回双层（v1.1.1 修订）

`semi_goods` 分区涉及 SKU 变体行、价格、库存和货值关系。`semi_variants` 涉及变体轴、图片、映射与主编辑页 SKU 身份一致性。**这些字段的 readback 必须分两层**：


| 层次  | 内容                                                    | 归属                                                                                                   |
| --- | ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| 第一层 | `semi_goods` 和 `semi_variants` 的基础字段值（价格、库存、图片 URL 等） | `semi_goods`/`semi_variants` SectionAutomation.readback                                              |
| 第二层 | SKU 变体轴映射、货值关系、价格/库存一致性、变体与主编辑 SKU 行身份对应              | `ContentFinalize(semi_wholesale)` — 这是 `semi_goods` 分区内的"批发验证"，语义与主编辑页 ContentFinalize(wholesale) 对应 |


两层 readback 都必须成功才能派发第二次 SAVE。SAVE2 尚未派发、preimage 完整且页面身份稳定时，失败先记录 `outcome_code=restore_required` 并由 RollbackSafety 严格逆序恢复；无法安全恢复或恢复读回不一致时设置 `manual_review_required=true`。SAVE2 已派发但结果无法证明时仍令 `execution_state=unknown`。

## 8. 冻结合同与版本迁移



### 8.1 新合同版本


| 合同   | 目标版本                               | 用途                                             |
| ---- | ---------------------------------- | ---------------------------------------------- |
| 编辑表单 | `dxm_editor_form.v5`               | 11 主分区、S1–S3、稳定 binding、能力和中文元数据               |
| 本地方案 | `local_plan_template.v4`           | 单店铺作用域、11 分区规则、五项 ALWAYS_ON 和 Path B 决策        |
| 执行快照 | `dxm_batch_draft_save_plan.v2`     | 商品顺序、逐区 resolution、两页动作、回滚准备和所需 approval policy/scope |
| 分区回执 | `dxm_section_receipt.v1`           | inspect/preimage/apply/readback/restore 的结构化事实 |
| 商品回执 | `dxm_full_product_item_receipt.v1` | 11 区、ContentFinalize、双 SAVE、HVD 和最终未发布汇总       |




### 8.2 Snapshot 最小内容

```yaml
schema: dxm_batch_draft_save_plan.v2
execution_mode: batch_draft_save
path: B
plan_content_sha256: ...          # 确定性内容身份，不含实例/时间/批准/attempt
snapshot_instance_id: ...         # 每次正式 freeze 唯一
snapshot_instance_sha256: ...     # 完整不可变实例 hash
shop_context:
  account_identity_sha256: ...
  session_ref: ...
  session_epoch: ...
  shop_id: ...
  shop_identity_sha256: ...
required_workflow_stages:
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
    product_identity_sha256: ...
    initial_draft_revision: ...
    revision_checkpoint_policy: ...
    main_sections: []
    content_finalize: {}
    entry_handshake:
      first_save_command_kind: FIRST_SAVE
      first_save_intent_action_kind: FIRST_SAVE_INTENT
      possible_save1_trigger_actions:
        - FIRST_SAVE_INTENT
        - OPEN_SEMI_MANAGED_EDITOR
      possible_effects_by_action:
        FIRST_SAVE_INTENT: [OPEN_MODAL, MAY_DISPATCH_SAVE1]
        OPEN_SEMI_MANAGED_EDITOR: [NATIVE_GATE, MAY_DISPATCH_SAVE1]
      open_action_allowed_first_save_phases:
        - IN_FLIGHT
        - SAVE_VERIFIED_AWAITING_GATE
      save_request_evidence_policy:
        enumerate_all_mutation_requests: true
        required_identity_fields:
          - save_request_identity_sha256
          - request_payload_sha256
          - causal_action_kind
          - action_attempt_id
          - ledger_sequence
        multiple_requests_without_idempotency_proof: UNKNOWN
      semi_entry:
        required: true
        eligibility_source: STORE_NATIVE_AFTER_OPEN_CLICK
        open_action_kind: OPEN_SEMI_MANAGED_EDITOR
        conditional_transition_kind: SEMI_MANAGED_CONTINUE_TRANSITION
        expected_page: editFromSmt
      required_join:
        - FIRST_SAVE_VERIFIED
        - SEMI_ENTRY_GATE_ADMITTED
        - SAME_ENTRY_HANDSHAKE_CAUSALLY_BOUND
      join_before:
        - SEMI_MANAGED_CONTINUE_TRANSITION
        - SEMI_PAGE_FIRST_WRITE
    semi_sections: []
    second_save: {}
    expected_final_state: NOT_PUBLISHED
approval_policy: {}
required_approval_scope: {}
publish_allowed: false
```

真实合同还必须包含逐字段来源、wire/normalized 类型、stable binding、当前值、目标值、规则版本、preimage requirement、readback expectation、页面身份、队列版本、每个 action 的 `possible_effects`、SAVE request 枚举/幂等证据策略和 canonical serialization 版本。`execution_attempt_id` 不属于 snapshot 内容；它在每次启动时唯一创建，并绑定 task、command、ledger 和 receipt。

三层身份不可混用：

- `plan_content_sha256`：对账号/店铺作用域、有序商品、冻结 resolution、Schema/capability/binding 和动作计划做确定性 hash；明确排除 `session_ref/session_epoch`、created/captured time、实际 approval record、实例 ID、attempt ID 和任何授权 TTL。相同业务事实必须得到相同值。
- `snapshot_instance_id/snapshot_instance_sha256`：每次 freeze 的唯一不可变实例及其完整 hash。实例 hash 包含 `snapshot_instance_id`、完整不可变 snapshot payload 与 canonical serialization version，明确排除 hash 字段自身、`freeze_idempotency_key` 和 freeze 请求传输元数据。
- `freeze_idempotency_key` 属于 freeze 请求/alias store，不写入 snapshot；同一 key 重试返回同一实例，新 key 可以产生新实例，即使内容 hash 相同。
- `execution_attempt_id`：每次执行唯一。一个 snapshot instance 只能被一个正式 execution attempt 消费；重试必须重新读取、preview、freeze、批准并创建新 attempt。

实际 `approval_record` 在 snapshot freeze 后创建，绑定 `snapshot_instance_sha256`、required scope、操作员、批准时间与 expiry，并存入 task/attempt 授权事实。snapshot 只描述“需要批准什么”，不描述“谁已经批准”。

### 8.3 迁移规则

- `local_plan_template.v3`、`dxm_batch_draft_save_plan.v1`、Path A snapshot 和 `/api/edit-batches` 旧批次只保留为 `HISTORICAL_ONLY / READ_ONLY`。
- 禁止静默把旧合同升级为 v4/v2 后进入写入；必须由用户在当前工作台重新打开、重新解析、重新 preview、重新 freeze 和重新批准。
- 新 Runner 只接受明确版本、完整 required fields、同源 hash 和 `publish_allowed=false` 的新快照。
- 迁移期不得并行维护两套可写主线；旧入口必须在开始动作前返回明确 reason code `E_LEGACY_VERSION_LOCKED`，并指向“请到工作台重新打开方案”。



### 8.4 旧版本迁移工具与查询路径（v1.1.0 新增）

v3/v1 snapshot、Path A 任务在 R0 之后仍可查询/审计，但不得作为写入口。本节规定查询路径和迁移工具。

#### 8.4.1 旧 snapshot/task 的查询


| 对象                             | 查询条件                                                          | 返回内容                    | 写路径                                       |
| ------------------------------ | ------------------------------------------------------------- | ----------------------- | ----------------------------------------- |
| `local_plan_template.v3`       | GET `/api/local-plan-templates?v=3`                           | 方案配置（只读）                | `E_LEGACY_VERSION_LOCKED` → 引导用户重新创建 v4      |
| `dxm_batch_draft_save_plan.v1` | GET `/api/plan-snapshots?schema=dxm_batch_draft_save_plan.v1` | 快照详情（只读）                | `E_LEGACY_VERSION_LOCKED` → 引导用户重新 freeze v2 |
| Path A task（已 approve 未 start） | GET `/api/tasks/{id}?path=A`                                  | 任务状态（只读）                | 写路径全部 `E_LEGACY_VERSION_LOCKED`              |
| Path A task（已 start 已完成）       | GET `/api/tasks/{id}`                                         | 任务详情和 receipt（可读）       | 不允许重跑；引导新 snapshot                        |
| `/api/edit-batches` 历史读取      | 显式 GET 只读 Legacy Adapter                                    | 历史 batch/task/job/receipt | 不得产生状态迁移或写入                              |
| `/api/edit-batches` 写请求        | POST/approve/start/pause/resume/stop/retry                     | HTTP 410 + `E_LEGACY_API_DISABLED` | 全部拒绝                                      |




#### 8.4.2 v3 → v4 字段映射迁移（建议工具）

v3 和 v4 的字段结构有差异（如 10 区 → 11 区、模板主/税率合并 → 拆分）。**不建议自动迁移 v3 → v4**，因为字段语义可能改变。但应提供：

1. **v3 → v4 对照报告**：给定一个 v3 template，返回"哪些字段可以直接映射，哪些需要人工复核，哪些完全丢失"
2. **v3 方案的只读展示**：让用户在 UI 上看到 v3 方案的内容，再手动创建对应的 v4
3. **v3 snapshot 的迁移不可行声明**：snapshot 是不可变事实；v3 snapshot 永远只能以 v1 的语义读取，不允许"升级后重新 freeze"



#### 8.4.3 迁移安全规则

- 旧 snapshot 的 task/job/receipt 历史**永久保留可查询**，但 task id 不得复用
- 新创建的 task 永远从最新的 `plan_snapshot.vN` 出发
- 不提供"自动升级历史 task"功能；用户必须主动创建新任务
- 在禁用 legacy control Interface 前，必须在一个恢复事务中枚举所有非终态 legacy task/job/ledger：未派发者转为 `execution_state=stopped`、`outcome_code=legacy_locked_pre_dispatch`；已派发但结果未闭合者转为 `execution_state=unknown`、`manual_review_required=true` 并永久保留 command/ledger/evidence。只有该迁移完成后，旧 approve/start/pause/resume/stop/retry 才统一返回 HTTP 410。
- 旧 URL 上的 mutating request 返回 `E_LEGACY_API_DISABLED`；新 Interface 收到旧版本对象返回 `E_LEGACY_VERSION_LOCKED`，两者不得混用。



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
- 进入方案前显示类目分布、Schema 可用性、主编辑页可观察阶段的可执行性、rollback preparation 状态、半托管 `RUNTIME_NATIVE_GATE_REQUIRED` 和阻断数量；不得探测或预判半托管资格。



### 9.4 铺货方案

- 左侧 11 分区 rail，与店小秘真实编辑顺序一致。
- 每个字段显示中文标签、来源、执行策略（继承/补差/固定）、当前值、目标值、约束、binding 状态和影响商品数。
- 视频、批发、翻译、半托管、rollback preparation 显示为锁定的“每件必经”，不得提供关闭开关。
- 模板主区与税率区独立；本地方案与 DXM 只读模板分层展示。
- JSON 只允许进入开发者诊断，不作为运营人员主配置入口。



### 9.5 Preview 与 Freeze

preview 使用“商品 × 分区”矩阵：

- 行：商品及队列顺序；列：0–10、ContentFinalize、入口握手（实际 SAVE1 与半托管原生门的有序事件）、S1–S3、第二次 SAVE、最终未发布。
- 单元格状态：`READY / BLOCKED / DRIFT / UNKNOWN / NEEDS_LIVE_EVIDENCE / RUNTIME_NATIVE_GATE_REQUIRED`。最后一项只用于半托管原生入口门，表示动作计划与证据策略已冻结、资格必须等店小秘运行时裁决，不等于资格 READY。
- 展开单元格查看逐字段来源、归一化、目标、binding、规则、风险和预期读回。
- 只有所有可在 freeze 时判定的必经列为 READY，且半托管列恰好为 `RUNTIME_NATIVE_GATE_REQUIRED`，才能 freeze。freeze 后配置或上下文变化创建新的 snapshot instance；若业务内容未变，`plan_content_sha256` 可以相同，但实例身份和实例 hash 必须不同。



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
- `OPEN_SEMI_MANAGED_EDITOR`、店小秘原生门裁决及必要的中间转换 receipt；
- S1–S3 receipt；
- 第二次 SAVE 三铁证；
- 独立最终未发布证明；
- task/job/queue/snapshot、account/session/shop、Git/worktree/package identity；
- UNKNOWN/人工复核原因及禁止重试说明。



## 10. 状态机、失败与恢复



### 10.1 商品状态

```text
execution_state:
  pending
    -> preflighting
    -> ready_to_apply
    -> applying_main_sections
    -> main_readback_verified
    -> entry_handshake_observing

entry_handshake_observing 期间只追加事实，不伪造新的 execution_state：
  first_save_intent = MAY_HAVE_DISPATCHED
  semi_entry_modal = BOUND
  open_semi_action = MAY_HAVE_DISPATCHED
  first_save_fact = NOT_DISPATCHED_PROVEN | DISPATCHED | VERIFIED | BUSINESS_REJECTED | UNPROVEN
  native_gate_fact = ADMITTED | REJECTED | UNPROVEN

  VERIFIED + ADMITTED + SAME_HANDSHAKE_CAUSALLY_BOUND
    -> execution_state=entry_handshake_joined
       ├─ 已实证特定中间 Modal 存在
       │    -> transitioning_to_semi
       │    -> semi_page_bound
       └─ 平台已直接到达正式 editFromSmt
            -> semi_page_bound
    -> semi_ready_to_apply    # entry_handshake_joined AND semi_page_bound
    -> applying_semi_sections
    -> semi_readback_verified
    -> second_save_dispatched
    -> second_save_verified
    -> not_published_verified
    -> succeeded

  # 以下交叉积先处理 request duplication 和任一 UNPROVEN；它们覆盖所有 known 分支
  observed_save_request_count > 1 AND idempotency_not_proven
    -> unknown / result_unproven / E_SAVE_DUPLICATE_REQUEST_UNPROVEN / manual_review_required=true
  native_gate=UNPROVEN
    -> unknown / result_unproven / E_SEMI_ENTRY_RESULT_UNKNOWN / manual_review_required=true
  first_save 与 native_gate 最终事实均已知 AND same_handshake_causal_binding=UNPROVEN
    -> unknown / result_unproven / E_SEMI_ENTRY_CAUSAL_BINDING_UNKNOWN / manual_review_required=true
  native_gate IN {ADMITTED, REJECTED} AND first_save IN {DISPATCHED, UNPROVEN}
    -> unknown / result_unproven / E_SAVE_DISPATCH_TIMEOUT / manual_review_required=true
  native_gate=REJECTED AND first_save=NOT_DISPATCHED_PROVEN
    -> stopped / semi_entry_rejected_main_not_saved / completed_save_stage=NONE
  native_gate=REJECTED AND first_save=VERIFIED
    -> stopped / semi_entry_rejected_main_saved / completed_save_stage=MAIN_SAVED
  native_gate IN {ADMITTED, REJECTED} AND first_save=BUSINESS_REJECTED
    -> stopped / save_business_rejected / completed_save_stage=NONE
  native_gate=ADMITTED AND first_save=NOT_DISPATCHED_PROVEN
    -> stopped / blocked_pre_write / E_SAVE_NOT_DISPATCHED_AFTER_ENTRY
```

真实 FIRST_SAVE 派发与原生门 outcome 是入口握手中的两个事实分支，不在缺证据时硬编码墙钟先后。若两组事实都已验证且精确绑定同一 handshake，无法还原毫秒级先后不构成失败；**因果绑定、SAVE1 最终事实或门 outcome 任一无法证明**时，才令 `execution_state=unknown`。任何已派发外部 mutation 但无法证明结果的状态都必须 `manual_review_required=true`，不能落为普通 `failed` 后提示重试。

机器结果必须拆成六个正交字段，不得再用斜杠或 `+` 把状态、结果和人工处置串成一个值：

- `execution_state_version=dxm_execution_state.v2`；`execution_state` 为闭集：`pending | preflighting | ready_to_apply | applying_main_sections | main_readback_verified | entry_handshake_observing | entry_handshake_joined | transitioning_to_semi | semi_page_bound | semi_ready_to_apply | applying_semi_sections | semi_readback_verified | second_save_dispatched | second_save_verified | not_published_verified | resolving | stopped | unknown | succeeded`；
- `outcome_code_version=dxm_outcome_code.v1`；`outcome_code` 为闭集：`none | blocked_pre_write | restore_required | restored_pre_dispatch | drift_detected_pre_save | draft_drift_during_long_action | page_identity_drift_pre_save | draft_missing_pre_save | legacy_locked_pre_dispatch | save_business_rejected | long_action_rejected | semi_entry_rejected_main_not_saved | semi_entry_rejected_main_saved | result_unproven | not_published_unproven | cancelled_safe | cancelled_restored | cancelled_during_external_action | cancelled_main_saved | cancelled_during_second_save | succeeded_not_published`；
- `reason_code`：§16 注册表中的静态原因码；没有错误的正常取消/成功可为 `null`；
- `manual_review_required`：是否必须人工核对的布尔事实；
- `completed_save_stage`：`NONE | MAIN_SAVED | SEMI_SAVED`，只表达已经闭合的保存阶段，不与终止原因争用 `outcome_code`；
- `retry_allowed`：是否允许**同一 attempt** 重试。当前闭集所有外部动作、失败、取消与 UNKNOWN 终态均为 `false`；写前阻断经重新 Reader/preview/freeze/批准创建新 attempt，不属于重试。

原生门明确拒绝时，若 SAVE1 未派发则 `execution_state=stopped`、`outcome_code=semi_entry_rejected_main_not_saved`、`completed_save_stage=NONE`；若 SAVE1 已验证则 `execution_state=stopped`、`outcome_code=semi_entry_rejected_main_saved`、`completed_save_stage=MAIN_SAVED`、`manual_review_required=true`。SAVE1 最终事实、门结果或同一 handshake 因果绑定无法证明时只能 `execution_state=unknown`、`outcome_code=result_unproven`、`manual_review_required=true`。以上终止路径均 `retry_allowed=false`，不进入 `transitioning_to_semi`。

### 10.2 失败分类


| 场景 | `execution_state` | `outcome_code` | `reason_code` | 人工复核 | 已完成 SAVE | 同 attempt 重试 | 后续动作 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 全量 preflight 未通过 | `stopped` | `blocked_pre_write` | 对应静态 `E_INSPECT_*` | `false` | `NONE` | `false` | 零写；修配置后重新 Reader/preview/freeze/批准，创建新 attempt |
| 页面字段已改变，但当前 page stage 尚无提交 mutation | `resolving` | `restore_required` | `E_VERIFY_VALUE_MISMATCH` | 初始 `false` | 按已闭合事实 | `false` | 身份一致且 preimage 完整时严格逆序 restore；失败则转人工复核 |
| 草稿身份漂移（§4.5） | `stopped` | `drift_detected_pre_save` | `E_DRAFT_REVISION_DRIFT` | `true` | 按已闭合事实 | `false` | 停批，人工核对真实草稿 |
| 页面身份漂移（URL/page epoch） | `stopped` | `page_identity_drift_pre_save` | `E_DRAFT_PAGE_IDENTITY_DRIFT` | `true` | 按已闭合事实 | `false` | 不派发新的 mutation |
| 草稿消失 | `stopped` | `draft_missing_pre_save` | `E_DRAFT_MISSING` | `true` | 按已闭合事实 | `false` | 停批；已验证 receipt 永久保留 |
| FIRST_SAVE 结果无法证明 | `unknown` | `result_unproven` | `E_SAVE_DISPATCH_TIMEOUT` | `true` | 仅已验证阶段 | `false` | 停批、人工核对，不得再次保存 |
| SAVE 明确业务拒绝 | `stopped` | `save_business_rejected` | `E_SAVE_BUSINESS_REJECTED` | `true` | 仅已验证阶段 | `false` | 保留回包并停批；不得伪装 UNKNOWN 或自动再次保存 |
| 原生门已放行，但入口握手结束时已证明 SAVE1 未派发 | `stopped` | `blocked_pre_write` | `E_SAVE_NOT_DISPATCHED_AFTER_ENTRY` | `false` | `NONE` | `false` | 不进入中间转换或半托管首写；创建新 attempt 前先补真实证据/实现 |
| 视频/翻译 provider 明确拒绝 | `stopped` | `long_action_rejected` | `E_LONG_ACTION_PROVIDER_REJECTED` | `true` | 仅已验证阶段 | `false` | 保留 provider receipt；新配置必须创建新 attempt |
| 视频/翻译额度在派发前明确耗尽 | `stopped` | `blocked_pre_write` | `E_LONG_ACTION_QUOTA_EXHAUSTED` | `false` | 仅已验证阶段 | `false` | 未派发该长动作；处理额度后重新 preview/freeze/批准 |
| 原生门明确拒绝且 SAVE1 零派发已证明 | `stopped` | `semi_entry_rejected_main_not_saved` | `E_SEMI_ENTRY_PLATFORM_REJECTED_MAIN_NOT_SAVED` | `false` | `NONE` | `false` | 零保存停批，不降级 Path A |
| 原生门明确拒绝且 SAVE1 已验证 | `stopped` | `semi_entry_rejected_main_saved` | `E_SEMI_ENTRY_PLATFORM_REJECTED_MAIN_SAVED` | `true` | `MAIN_SAVED` | `false` | 保留 SAVE1 receipt，停批，不做第二次 SAVE |
| 门结果已知、SAVE1 最终事实无法证明 | `unknown` | `result_unproven` | `E_SAVE_DISPATCH_TIMEOUT` 或对应 SAVE reason | `true` | 仅已验证阶段 | `false` | 停批；不得用再次点击覆盖事实 |
| SAVE1 已知、门结果无法证明 | `unknown` | `result_unproven` | `E_SEMI_ENTRY_RESULT_UNKNOWN` | `true` | 仅已验证阶段 | `false` | 停批；不得重放原生门 |
| SAVE1 与门结果均已知，但同一 handshake 因果绑定无法证明 | `unknown` | `result_unproven` | `E_SEMI_ENTRY_CAUSAL_BINDING_UNKNOWN` | `true` | 仅已验证阶段 | `false` | 停批；不得拼接跨会话证据 |
| 已完成 SAVE1，S1–S3 零写预检失败 | `stopped` | `blocked_pre_write` | 对应静态 `E_INSPECT_*` | `true` | `MAIN_SAVED` | `false` | 半托管页写入为 0；保留 SAVE1 receipt，不做 SAVE2 |
| SECOND_SAVE 结果无法证明 | `unknown` | `result_unproven` | `E_SAVE_DISPATCH_TIMEOUT` | `true` | `MAIN_SAVED` | `false` | 停批、人工核对，不得再次保存 |
| 最终未发布无法证明 | `unknown` | `not_published_unproven` | `E_SAVE_NOT_PUBLISHED_VERIFY_FAILED` | `true` | `SEMI_SAVED` | `false` | 不宣称成功，不继续下一件 |


只允许在外部 dispatch 前，对同值、确定性的可见表单动作进行一次受控纠正；这不是网络 mutation 重试，也不能跨商品复用。

### 10.3 HVD 安全点

- `暂停`：在当前 section receipt 或明确 dispatch 终态后生效。
- `继续`：从持久化的下一个安全 section 开始，不重做已证实 SAVE。
- `停止`：不再派发新动作；在途动作先判定成功/失败/UNKNOWN。
- `急停`：只终止新的 BrowserAgent command；已派发动作进入 `resolving`，能证明成功/明确拒绝则记录真实终态，最终无法证明时才是 `UNKNOWN`，且不伪造回滚成功。



### 10.4 用户主动 Cancel 与系统结果的边界（v1.1.1 修订）

`cancel_requested` 只记录用户停止意图；商品最终状态仍由动作事实决定。cancel 永远不能把 `UNKNOWN`、已派发动作或部分保存改写成安全取消。

#### 10.4.1 Cancel 状态路径

| 场景 | `execution_state` | `outcome_code` | `reason_code` | 人工复核 | 已完成 SAVE | 同 attempt 重试 | 最终处置 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| inspect/preimage 中，页面字段未变化且无外部 dispatch | `stopped` | `cancelled_safe` | `null` | `false` | `NONE` | `false` | 停止当前商品和后续派发；无需 restore |
| apply 已改变页面，但当前 page stage 无提交 mutation | `resolving` | `restore_required` | `null` | 初始 `false` | 按已闭合事实 | `false` | 身份稳定且 preimage 完整时严格逆序 restore/reload-discard；成功转 `cancelled_restored`，否则人工复核 |
| 视频/翻译/转换/SAVE 已派发 | `resolving` | `cancelled_during_external_action` | 按在途动作事实 | `true` | 仅已验证阶段 | `false` | 只记录 stop intent并等待确定结果；最终无法证明则转 `unknown/result_unproven` |
| FIRST_SAVE 已验证、SECOND_SAVE 尚未派发 | `stopped` | `cancelled_main_saved` | `null` | `true` | `MAIN_SAVED` | `false` | 保留 SAVE1 和原生门事实，不继续 SAVE2；明确标注 Path B 未完成 |
| SECOND_SAVE 已派发 | `resolving` | `cancelled_during_second_save` | 按 SAVE2 事实 | `true` | `MAIN_SAVED` | `false` | 等待并按 SAVE2 事实归类；不确定转 `unknown/result_unproven` |

#### 10.4.2 UI 与恢复规则

- `cancelled_safe` 可以显示蓝色；只有重新读取、preview、freeze、批准后才能创建新任务。
- `manual_review_required=true` 和 `execution_state=unknown` 显示红色并要求到店小秘核对；部分保存必须单独显示 SAVE1 证据。
- `blocked_pre_write/restore_required` 显示黄色；恢复是安全状态机动作，不由用户任意选择“保留未审阅页面变化”。
- cancel request、restore receipt 和最终 outcome 分字段保存，禁止一个 `cancelled=true` 覆盖真实执行状态。



### 10.5 长动作 HVD 语义（v1.1.1 修订）

视频生成和翻译可能是耗时、配额型或远端不可撤销动作。当前真实耗时、超时和可取消能力仍标 `NEEDS_LIVE_EVIDENCE`；不得用未经实测的分钟数决定授权 TTL。HVD 在这类动作期间的语义与普通字段填写不同。

#### 10.5.1 长动作分类


| 动作 | 当前证据 | 控制合同 |
| --- | --- | --- |
| 视频生成（平台/远端） | `NEEDS_LIVE_EVIDENCE` | dispatch 后只能按 provider request/可见结果收敛；不得假设可取消或固定超时 |
| 视频生成（本地渲染） | `NEEDS_LIVE_EVIDENCE` | 使用独立 operation attempt；停止新阶段，不伪造已终止 |
| 翻译（平台/远端） | `NEEDS_LIVE_EVIDENCE` | dispatch 前一次性授权，完成/失败/不确定进入结构化 receipt |
| 普通字段填写 | 当前页面动作 | 只在 section 安全点响应 HVD；不涉及远端配额不等于可丢弃 preimage |




#### 10.5.2 暂停语义

当 HVD 暂停键在长动作期间被按下：

1. 已派发长动作只记录 `pause_requested`，系统继续观察同一个 `operation_attempt_id/provider_request_id`，直到明确终态或 UNKNOWN。
2. 明确结果进入 receipt 后暂停才在下一个安全点生效；不得重复派发长动作。
3. 继续前重新验证 task/job/queue/approval、商品 revision 和页面身份；为下一个外部动作签发新的 action grant，不复活旧 grant。



#### 10.5.3 停止语义

当 HVD 停止键在长动作期间被按下：

1. 停止只禁止派发新的外部动作，并记录 `stop_requested`；已经派发的动作继续按真实 provider/page 结果收敛。
2. Receipt 必须记录 operation attempt、provider request、配额事实和最终结果；系统不得自行把已生成结果改写成 `discarded`。
3. 能否调用 provider cancel 必须有真实接口与幂等证据；未实证前不得强制断线或假定取消成功。超时后无法证明结果时进入 UNKNOWN。



#### 10.5.4 一次性 action grant 与 SAVE lease

- 每个远端长动作使用独立、一次性 `action_grant_id`，在 dispatch 前实时复核并在 ledger begin 时消费；它只授权该精确 action payload，不授予 SAVE 权限。
- 每个 SAVE command 的 lease 只在“最早可能触发该 SAVE 的 UI 动作”前即时签发并于 ledger begin 消费，不得跨越 inspect、apply、ContentFinalize、暂停或长动作，不得冻结、续期或复活。FIRST_SAVE 是 `FIRST_SAVE_INTENT → Modal → OPEN_SEMI_MANAGED_EDITOR` 的多步握手：lease 在首个“保存”点击前只消费一次，后续步骤不得取得第二张 SAVE lease。
- `action_grant_id` 或尚未消费的 `save_lease_id` 在各自 dispatch 前过期属于 `blocked_pre_write`；lease 已消费后不得靠续期推动握手。进入下一 UI 动作前若 approval/queue/同一握手 command phase 复核失败，且能证明 SAVE 零派发则安全停止；无法排除 SAVE 已发生时进入 UNKNOWN。
- 长动作完成后、下一个字段写入或转换前申请新的 `action_grant_id`；SAVE 前申请新的 `save_lease_id`，两者都先重新执行 live validation。



#### 10.5.5 长动作与草稿漂移

§4.5 的草稿身份漂移检测在长动作期间仍然生效。如果长动作进行中检测到草稿被外部修改：

- 视频/翻译结果已经回写或远端结果已生成 → 保留真实 receipt；页面/草稿发生漂移时记录 `outcome_code=draft_drift_during_long_action`、`manual_review_required=true`，不得自动重复生成。
- 远端是否完成无法证明 → `UNKNOWN`；明确未派发且页面无变化时才可安全取消。



## 11. 实施里程碑



### R0 · 真相收敛与旧主线冻结

目标：让所有开发入口只指向本方案、唯一主合同和当前运行架构。

- **R0A · 唯一执行权威**：只有 `V1TaskRunner` 可调度、推进状态和响应 HVD。先事务化收敛全部非终态 legacy task/job/ledger，再删除 `BatchExecutionRuntime` 执行装配并禁用 `/api/edit-batches` 的写启动/批准/推进 Interface；历史读取迁入显式 LegacyReadAdapter。
- 标记 `local_plan_template.v3`、Path A snapshot 和旧 batch bundle 为只读历史。
- 建立当前 10 区 → 11 区、旧步骤 → Path B 完整步骤的显式差异测试。
- 固定单店铺上下文与切换失效 Interface。
- **R0B · 真实只读 Evidence Pack**：取得视频、翻译、批发、资质图片、类目切换、非空级联、草稿 revision checkpoint，以及半托管原生门 admitted/rejected/unknown 的脱敏证据；未实证的超时、资格规则和控件不得冻结成实现常量。
- 建立当前完整 L0 基线，不用聚焦绿测替代。

DoD：旧入口无法创建或推进新写任务；历史查询仍可读；文档、类型、Interface 和 reason code 对旧合同处置一致；进程内不存在第二个拥有队列/状态迁移权的 Runner；Evidence Pack 缺项保持 BLOCKED，不靠猜测填平。

### R1 · 11 分区工作台与 Snapshot Compiler

目标：运营人员可在中文结构化界面完成 11 分区配置、preview 和 freeze。

- 发布 `dxm_editor_form.v5`、`local_plan_template.v4`、`dxm_batch_draft_save_plan.v2`。
- 模板主/税率拆分；动态任意深度类目与 CategoryCatalog 进入 runtime/package。
- 商品 × 分区矩阵覆盖五项必经、Path B 两页、店小秘原生半托管门和双 SAVE；半托管资格只能显示 `RUNTIME_NATIVE_GATE_REQUIRED`。
- 店铺/账号/会话变化使所有下游对象失效。

DoD：≥3 商品、多类目相同输入可重复生成相同 `plan_content_sha256`；每次 freeze 有唯一 snapshot instance；遗漏任一必经分区、主页面能力、binding 或当前 Schema 即 fail-closed，且不得把半托管运行时资格伪造成 freeze 时 READY。

### R2 · SectionAutomation 框架与全量零写预检

目标：建立一个深 Interface 和共享定位/回执/回滚 seam。

- 实现 `SectionAutomationRegistry`、`BindingRegistry`、`SectionReceipt` 和商品级 preflight aggregator。
- 写入与读回使用同一定位 Implementation。
- 在主页面首个 `apply` 前完成主页面全部分区和能力预检；半托管页只在店小秘原生门放行并精确绑定 `editFromSmt` 后、该页首个 `apply` 前完成 S1–S3 预检。
- 建立生产 Adapter 与 deterministic fixture Adapter；二者通过同一授权和回执验证。

DoD：同一页面任一后置字段非法、隐藏、重复或漂移时，该页面写入计数为 0；真实 producer→consumer 回执无形状漂移；inspect 只有声明过的允许 effect。

### R3 · 11 分区 Implementation

目标：按 0–10 顺序逐区完成真实可见 UI 填写和精确读回。

- 优先级：基本/属性/产品 → 描述/包装 → 区域价格 → 模板主/税率 → 合规/其它 → 店小秘信息。
- 每完成一个 Module，同时提交控件夹具、失败 reason code、preimage、readback 和 receipt 测试。
- 不用固定坐标、中文标签兜底、选择第一项、静默截断或固定 sleep 作为生产策略。

DoD：每区有稳定 Interface 级测试、正式 Adapter 集成测试和至少一个脱敏真实 wire/DOM 形状；跨区全量预检仍保证零写。

### R4 · 五项必经与完整 Path B

目标：每件商品完成视频、批发、翻译、rollback preparation 和半托管双阶段只保存。

- 视频、批发和翻译进入 ContentFinalize 与全量读回。
- `FIRST_SAVE_INTENT` → Modal → `OPEN_SEMI_MANAGED_EDITOR` → 店小秘原生门，并按真实事件分别闭合 SAVE1 与门 outcome；只有 `entry_handshake_joined` 后才允许必要的 `SEMI_MANAGED_CONTINUE_TRANSITION`，到达正式 `editFromSmt` 并建立 `semi_page_bound` 后才可 S1–S3 → SECOND_SAVE。全部接入同一 Orchestrator。
- `FIRST_SAVE_INTENT` 与 `OPEN_SEMI_MANAGED_EDITOR` 分别冻结 possible-effect set；前者消费唯一 FIRST_SAVE lease，后者消费独立 action grant并事务化复核同一 active handshake/FIRST_SAVE command（phase 仅 `IN_FLIGHT | SAVE_VERIFIED_AWAITING_GATE`）。可选 transition 消费自己的 action grant，SECOND_SAVE 消费自己的 save lease；四类 command 都绑定 snapshot/item/job/queue/runtime/package/前序事实，不能写成模糊“两段 command”。
- PublishGuard 对最终发布保持绝对拒绝。

DoD：正式 BrowserAgent Adapter 覆盖 `FIRST_SAVE_INTENT→Modal→OPEN_SEMI`，两个 possible-effect set 均进入正式授权/queue CAS/ledger/crash recovery；逐条枚举真实 SAVE request 并绑定 request hash/causal action/ledger，未证明幂等时多请求稳定判 UNKNOWN；以真实事件分别闭合 SAVE1 与 native gate 三分支，建立 `entry_handshake_joined` 后再进入可选 transition→S1–S3→SAVE2→VERIFY。测试必须覆盖“拒绝且主编辑未保存”“拒绝且主编辑已保存”“拒绝但 SAVE1 未知”“SAVE1/门因果绑定不确定”以及“两组事实同源但墙钟全序不可还原仍可 join”，不能把明确拒绝一律伪装成部分保存；任一发布等价动作反例稳定判红。

### R5 · 回执、恢复、HVD 与主线清理

目标：让崩溃、暂停、继续、停止和 UNKNOWN 在 SQLite、Runner、UI 和报告中同义。

- 启动恢复在单事务中更新 task/job/ledger，保留已派发动作的 UNKNOWN 语义。
- `CanonicalReceipt` 逐项从实际 command、ledger 和持久任务重建事实，不接受调用方自签 metadata。
- 删除被新主线替代的重复校验与 shallow pass-through；保留必要历史读适配。
- 模块拆分以 Depth、Leverage 和 Locality 为目标，不按文件行数机械拆分。

DoD：崩溃窗口、lease 过期、队列跳项、VERIFY 篡改、字段证据替换和 Schema 漂移反例全部判红。

> **（v1.1.0 R5 补充）** R5 的 DoD 必须包含以下清理条目，不允许遗留 Path A 代码进入 R6：
>
> 1. 删除 `BATCH_DRAFT_SAVE_STEPS` 中 Path A 相关步骤（如 `V1_STEPS` 中的 `STEP_PATH_A_*`）
> 2. 删除 `/api/edit-batches` 的 create/approve/start/pause/resume/stop/retry 等写 handler；保留独立只读 Legacy Adapter 与稳定 HTTP 410 tombstone
> 3. 删除 `dxm_editor_form.v4` 旧模型（保留归档路径）
> 4. 删除 `dxm_batch_draft_save_plan.v1` 的写入 factory
> 5. 删除 `local_plan_template.v3` 的新方案创建入口
> 6. 形成独立的 `refactor/remove-path-a-legacy` 变更集（提交/PR 仍须另行授权），包含上述删除、只读兼容与测试覆盖
> 7. 清理门禁必须：历史查询 Adapter 通过、旧写路径稳定 410、新路径无旧执行 import；不得以删除历史数据换绿



### R6 · 门禁、同源包与真实三商品验收

目标：从固定可复验源码，证明真实 UI 完整 Path B 三商品只保存且最终零发布。

- 完整 backend L0 `0 failed / 0 skipped`；不得放宽断言、删测试或 mock 被测对象。
- frontend Node、Chromium、typecheck、Vite；desktop；文档 SelfTest 全绿。
- 统一版本并从固定 Git/worktree 构建同源 portable；隔离 user-data smoke。
- 另取当次真实写入授权，从同一工作台、同一可见会话、同一具体店铺选择 ≥3 个真实 draft。
- 每件商品完成五项必经、11 区、店小秘原生门、双 SAVE 三铁证、HVD 负向和最终未发布证明。

DoD：证据同时绑定 Git、worktree、package、DB、task、snapshot、account/session/shop 和真实页面；任何 UNKNOWN 都使任务不通过且不自动重试。

## 12. 测试策略



### 12.1 合同层

- 11 分区代码、顺序、必经字段和版本反序列化。
- 旧合同只读、禁止静默升级和禁止创建写任务。
- 单店铺上下文、切换失效、商品顺序、`plan_content_sha256`、snapshot instance、execution attempt 与批准精确绑定。
- 五项能力任一缺失、关闭、跳过或改为 false 的反例。



### 12.2 Module 层

- 每个 SectionAutomation 的 inspect/preimage/apply/readback/restore。
- BindingRegistry 的唯一匹配、可见性、类型、重复、额外匹配和页面漂移。
- wire normalization 的真实脱敏形状：数组/JSON string/数字字符串/图片串/哨兵/自定义属性。
- 生产回执 producer 到集中 consumer 的端到端结构测试。



### 12.3 Runner 与安全层

- 只授权当前 running job，前序成功、后序 pending、queue version 未漂移。
- 动作时事务按种类复核一次性 `action_grant_id` 或 `save_lease_id`、批准状态、消费状态和 expiry；暂停/长动作后不得复活旧授权。
- command payload、逐字段 readback、snapshot、page/category/schema、Git/worktree/package 全量绑定。
- SAVE 与 VERIFY、主保存意图/`OPEN_SEMI_MANAGED_EDITOR`/实际 SAVE1/原生门的同源事件链、必要的中间转换、第二次 SAVE 与最终未发布成对验证。
- crash before dispatch、after dispatch、after response、before receipt 的恢复矩阵。



### 12.4 UI 与包

- 店铺切换后的前后端状态共同撤销。
- 11 分区 rail、中文字段、模板/方案分层、必经能力锁定和商品 × 分区 preview。
- 1100px/860px 断点、七项导航、明暗主题和 HVD 四键真实浏览器 computed-state。
- 源码与 portable 使用相同 schema、资源、版本和后端；启动冲突不能静默复用错误 runtime。



### 12.5 幂等性与重复运行（v1.1.1 修订）

- 相同有序商品、resolution、Schema/capability/binding 和动作计划必须产生相同 `plan_content_sha256`；时间、会话租约、批准和实例 ID 不得污染内容 hash。
- 同一 `freeze_idempotency_key` 的重试返回同一 snapshot instance；不同 key 创建不同 `snapshot_instance_id/snapshot_instance_sha256`，即使内容 hash 相同。
- 一个 snapshot instance 只能被一个正式 `execution_attempt_id` 消费；task id、attempt id、command id、action grant、save lease 和 ledger 不得复用。
- 失败或 UNKNOWN 后要重跑，必须重新读取、preview、freeze、批准并创建新 attempt；旧 receipt 永远只引用旧 attempt。新旧内容 hash 可以相同，但实例与执行身份必须不同。



### 12.6 反向 DoD 专章（v1.1.0 新增）

本节列出"一旦出现则必然违规"的反例，与 MVP 合同 §11.3 反向流程对齐。任何反例被 CI/lint/code review 捕获都必须在当天修复，不得以"WIP"或"后续再修"拖延。

#### 12.6.1 保存与发布安全


| 反例                                                                                    | 检测手段                     | 裁定          |
| ------------------------------------------------------------------------------------- | ------------------------ | ----------- |
| `BrowserAgent.click` 或 `page.click` 直接调用"发布"/"立即发布"/"上线"/"saveAndPublish" 按钮          | 代码扫描（禁止中文控件名作为 selector） | P0 · 立即回退   |
| `Dispatch.save()` 收到非 `batch_draft_save` mode 的 task                                  | 运行时断言                    | P0 · 立即回退   |
| `PublishGuard` 对"继续发布"文本点击返回 pass，但 action kind 不是 `SEMI_MANAGED_CONTINUE_TRANSITION` | protocol 验证              | P0 · 立即回退   |
| `ActionResult` 中 `success=true` 但缺少三铁证字段                                              | receipt schema 校验        | P0 · 立即回退   |
| 两次 SAVE（主编辑 + 半托管）共用同一 command id 或 lease id                                          | ledger 对账                | P0 · 立即回退   |




#### 12.6.2 草稿身份与漂移


| 反例                                           | 检测手段    | 裁定          |
| -------------------------------------------- | ------- | ----------- |
| `apply` 在没有同阶段商品身份/revision/page epoch checkpoint 的情况下执行 | 代码路径分析  | P0 · 立即回退   |
| 草稿漂移后系统返回 `success=true`                     | 运行时反例测试 | P0 · 立即回退   |
| 草稿消失后任务继续派发 SAVE                             | 运行时反例测试 | P0 · 立即回退   |
| 用 product_id 替代商品身份，或用最初 revision 机械比较 SAVE1 之后阶段 | 代码扫描 + checkpoint 测试 | P0 · 立即回退 |




#### 12.6.3 UNKNOWN 与自动重试


| 反例                                             | 检测手段                                                    | 裁定          |
| ---------------------------------------------- | ------------------------------------------------------- | ----------- |
| SAVE/视频生成/中间转换派发后收到不确定结果，系统自动再次派发 SAVE         | 运行时反例测试                                                 | P0 · 立即回退   |
| UNKNOWN 状态的 job 被 runner 自动推进到下一商品             | 状态机转移图验证                                                | P0 · 立即回退   |
| `failure_strategy=ignore` 让超时变成 `success=true` | 长动作超时反例：任何 ignore 策略都不得把未证实结果改成成功 | P1 · 立即修复测试 |




#### 12.6.4 Path A 与旧合同


| 反例                                                      | 检测手段                   | 裁定             |
| ------------------------------------------------------- | ---------------------- | -------------- |
| R6 之后仓库中仍存在 `batch_draft_save_steps` 中的 Path A 步骤定义     | `git grep` Path A 相关代码 | P0 · 不得合入 main |
| 旧合同 snapshot（v1/v3）被接受为可执行 task 的输入                     | API 集成测试               | P0 · 立即回退      |
| `/api/edit-batches` 的 mutating request 返回 2xx 而非 HTTP 410 + `E_LEGACY_API_DISABLED` | Interface 集成测试 | P0 · 立即回退 |
| 存在第二个拥有任务调度、商品顺序或状态迁移权的 Runner | 架构合同测试 + 启动装配测试 | P0 · 不得进入 R1 |




#### 12.6.5 店小秘原生半托管门

| 反例 | 检测手段 | 裁定 |
| --- | --- | --- |
| 系统主动调用 `verifyPopChoiceShop`、读取 shop type/类目/catalog 或历史结果来裁决半托管资格 | 代码扫描 + Adapter 反例 | P0 · 立即回退 |
| 店小秘原生门前把半托管资格写成 READY/eligible=true | snapshot/preview schema 反例 | P0 · 立即回退 |
| `OPEN_SEMI_MANAGED_EDITOR` 与 `SEMI_MANAGED_CONTINUE_TRANSITION` 合并为同一泛化“继续发布”动作 | protocol 反例 | P0 · 立即回退 |
| 任一含 `MAY_DISPATCH_SAVE1` 的 command 点击前未绑定当前 FIRST_SAVE approval/queue/lease/ledger | possible-effect protocol 反例 | P0 · 立即回退 |
| 顶部“保存”点击后、FIRST_SAVE ledger 尚未 `BEGIN/MAY_HAVE_DISPATCHED` 时进程崩溃，却恢复成 pre-write | crash recovery 反例 | P0 · 立即回退 |
| `OPEN_SEMI_MANAGED_EDITOR` 只消费 action grant，却未事务化复核同一 active handshake/FIRST_SAVE command 及合法 phase | grant/ledger 反例 | P0 · 立即回退 |
| 两个可能 SAVE1 动作观察到多条真实 mutation request，却因共用 command id/URL/payload 而合并，或缺少每条 request hash/causal action | request-ledger 反例 | P0 · 立即回退 |
| 原生门 admitted 且已证明 SAVE1 未派发，却仍建立 join、执行中间转换或开始 S1–S3 | 状态机交叉积反例 | P0 · 立即回退 |
| `entry_handshake_joined` 之前派发 `SEMI_MANAGED_CONTINUE_TRANSITION` | 状态机 + Dispatcher 反例 | P0 · 立即回退 |
| SAVE1 与门 outcome 均已验证且因果绑定同一 handshake，仅因墙钟全序不可还原就判 UNKNOWN | 偏序 join 反例 | P0 · 立即回退 |
| 原生门明确拒绝但 SAVE1 最终事实未知，却被归类为 `main_not_saved` 或 `main_saved` | outcome 分类反例 | P0 · 立即回退 |
| 店小秘原生门明确拒绝后仍进入 S1–S3、第二次 SAVE 或 Path A 成功 | 状态机与 Browser Adapter 反例 | P0 · 立即回退 |
| 原生门结果不确定却自动再次点击或继续下一商品 | crash/timeout 反例 | P0 · 立即回退 |

#### 12.6.6 SectionAutomation Protocol


| 反例                                        | 检测手段                | 裁定         |
| ----------------------------------------- | ------------------- | ---------- |
| `inspect()` 产生未声明 effect，或出现 FORM_VALUE_WRITE/FILE_UPLOAD/LONG_ACTION_DISPATCH/SAVE_OR_PUBLISH | effect receipt + 运行时断言 | P0 · 立即回退 |
| `apply()` 重新读取了模板并改变了目标值                  | 集成测试验证 payload hash | P0 · 立即回退  |
| BindingRegistry 之外存在第二套选择器实现              | 代码扫描                | P1 · R5 清理 |




#### 12.6.7 幂等性


| 反例                                 | 检测手段           | 裁定        |
| ---------------------------------- | -------------- | --------- |
| 同一 snapshot instance 或 execution attempt 被两个 task/command 消费 | API/ledger 集成测试 | P0 · 立即回退 |
| 相同业务输入因 created_at/批准/attempt 不同而产生不同 `plan_content_sha256` | canonical serialization 测试 | P1 · R1 阻断 |
| task 在 `succeeded` 状态后被允许再次 start  | 状态机转移图验证       | P0 · 立即回退 |
| task id 被复用                        | 数据库唯一约束 + 集成测试 | P0 · 立即回退 |
| SAVE lease 跨长动作或暂停被冻结、续期、复活 | action-time authorization 反例 | P0 · 立即回退 |
| cancel 把 UNKNOWN 或 `first_save_verified` 部分保存改写成安全 cancelled | 状态机反例 | P0 · 立即回退 |




#### 12.6.8 迁移工具


| 反例                                   | 检测手段     | 裁定        |
| ------------------------------------ | -------- | --------- |
| v3 snapshot 被"静默升级"为 v2 后进入写入        | API 集成测试 | P0 · 立即回退 |
| v3/v1 历史 receipt 被覆盖或删除              | 数据库唯一约束  | P0 · 立即回退 |
| `E_LEGACY_VERSION_LOCKED` 返回 2xx 而非 4xx | API 集成测试 | P0 · 立即回退 |
| 旧写 Interface 仍可执行，或清理旧写路径时误删历史只读查询 | API/迁移集成测试 | P0 · 立即回退 |




## 13. DXM-TX 文档与数据的持续使用

- `D:\Desktop\py\DXM-TX` 始终只读；本仓只保存脱敏、可追溯、与当前产品有关的事实合同。
- 类目节点映射已经通过 `resources/dxm/category-catalog/category-catalog.v1.json` 与 manifest 迁入，包含 13,216 节点、11,864 叶子和 12 个不可执行冲突叶；它是版本化参考，不替代当前页面 category/Schema 写前权威。
- 后续上游变化只通过显式同步脚本、hash 漂移和人工审阅进入本仓；禁止复制 sessions、Cookie、账号、店铺、商品、模板或 raw 业务样例。
- 视频、翻译、批发、资质图片、切类目和级联的新证据，应先形成脱敏 fixture 与事实条目，再进入 SectionAutomation Implementation。
- 上游文档中的坐标、固定等待、选择第一项、模糊遮罩删除、可关闭能力或 Path A/Path B 二选一，只能标记为历史操作提示，不能成为生产合同。



## 14. 代码落点

以下是目标落点，不表示当前已实现：


| 目标                      | 优先深化位置                                                                                                      |
| ----------------------- | ----------------------------------------------------------------------------------------------------------- |
| 单店铺/会话上下文               | `app/backend/src/main.py`、会话门面与前端 workbench state                                                           |
| 编辑模型 v5                 | `app/backend/src/services/dxm_editor_model.py`、`app/frontend/src/types.ts`                                  |
| 方案 v4 / snapshot v2     | `app/backend/src/batch_edit/plan_template_contract.py`、`plan_snapshot_compiler.py`、`LocalPlanWorkspace.tsx` |
| 统一 Orchestrator         | `app/backend/src/execution/v1_runner.py`，复用现有 task/HVD 状态机                                                  |
| 分区 Registry 与 Interface | `app/backend/src/batch_edit/` 中新增深 Module，正式 Adapter 进入 `DxmLoginFlow` seam                                 |
| 共享 binding/readback     | 收敛 `DxmLoginFlow` 中重复定位与读回算法，不再各分区复制                                                                        |
| 双 SAVE 与安全事实            | 现有 BrowserAgent protocol/worker、JIT、lease、queue CAS、mutation ledger、ActionResult                            |
| UI 过程与结果                | `app/frontend/src/components/workbench/`，保持七项主导航                                                            |


实现时遵循删除测试：如果删掉一个新 Module，只会让同样复杂度散回多个调用方，说明它提供了 Depth；如果删掉后复杂度也消失，它只是 shallow pass-through，不应保留。

## 15. 非目标与停止条件

本方案不授权：

- 当前轮直接改业务代码、执行真实保存或最终发布；
- 存在任何第二个拥有队列、任务状态迁移、HVD 或写派发权的 Runner/Runtime；并行多 Worker 或跨店铺任务；
- 恢复旧文档为第二主合同；
- 根据未实证运营建议猜控件、请求、等待时间或默认值；
- 用聚焦测试、mock 浏览器、历史包或旧数据库宣称完成。

任一里程碑遇到缺少真实页面身份、稳定 binding、当前 Schema、回包语义或安全裁决时，将具体事项写入 BLOCKED；跳过后继续不受影响的 Module。只有 R0–R6 的当前同源证据全部满足，才可以申请关闭 `E3_OPEN / BLOCKED`。

## 16. Reason Code 体系（v1.1.1 修订）

reason code 是系统向用户和工程师传递结构化失败信息的唯一通道。本节规定 reason code 的命名规则、命名空间总表和使用约束。

### 16.1 命名规则

```text
reason_code_version: dxm_reason_codes.v1
reason_code: E_{CATEGORY}_{STATIC_REASON}
details:
  section_code: ...
  field_key: ...
  job_id: ...
  upstream_code: ...
```

- reason code 是版本化静态枚举，全部使用大写 `UPPER_SNAKE_CASE`；发布后不得把 job、field、section、上游 code/msg/state 拼进 code。
- `CATEGORY` 是失败大类（见 §16.2），`STATIC_REASON` 是稳定语义；动态事实只进入结构化 `details`，并受脱敏规则约束。
- 禁止空格、camelCase、运行时模板、模糊缩写（如 `E_FAIL`）或以 HTTP 200 返回 `E_*`。
- 静态 registry 是唯一机器权威，由它生成后端枚举、前端中文映射、本文总表和合同测试，禁止多处手写漂移。
- 下表最后一列是推荐 `outcome_code`/处置摘要，不是 `execution_state` 的序列化值。出现 `needs_manual_review` 表示设置 `manual_review_required=true`；真正持久化仍必须使用 §10.1 的六字段机器模型。



### 16.2 命名空间总表



#### E_INSPECT_* — 零写预检失败


| code                                             | 含义                                      | HTTP 状态 | outcome/处置摘要                |
| ------------------------------------------------ | --------------------------------------- | ------- | ------------------- |
| `E_INSPECT_CONTROL_NOT_FOUND` | 指定分区字段控件未找到；section/field 进入 details | 422 | `blocked_pre_write` |
| `E_INSPECT_CONTROL_NOT_VISIBLE` | 控件存在但不可见 | 422 | `blocked_pre_write` |
| `E_INSPECT_CONTROL_AMBIGUOUS` | 合法控件匹配结果不等于 1 | 422 | `blocked_pre_write` |
| `E_INSPECT_CONTROL_TYPE_MISMATCH` | 控件类型与 Schema 类型不符 | 422 | `blocked_pre_write` |
| `E_INSPECT_EXTRA_MATCH` | 分区出现未冻结的额外匹配 | 422 | `blocked_pre_write` |
| `E_INSPECT_SCHEMA_FIELD_MISSING` | Schema 要求的字段在 DOM 中不存在 | 422 | `blocked_pre_write` |
| `E_INSPECT_CATEGORY_CAPABILITY_BLOCKED` | 类目字段决策无法解析为 REQUIRED 或 NO_FIELDS | 422 | `blocked_pre_write` |
| `E_INSPECT_EFFECT_FORBIDDEN` | inspect 出现未声明或禁止 effect | 500 | `needs_manual_review` |




#### E_BINDING_* — Binding 解析失败


| code                                    | 含义                              | HTTP 状态 | outcome/处置摘要                |
| --------------------------------------- | ------------------------------- | ------- | ------------------- |
| `E_BINDING_NOT_REGISTERED` | 字段未在 BindingRegistry 中注册 | 422 | `blocked_pre_write` |
| `E_BINDING_DUPLICATE` | 同一 field_key 有多个合法 binding | 422 | `blocked_pre_write` |
| `E_BINDING_PAGE_CONTEXT_MISMATCH` | binding 的 page_context 与当前页面不匹配 | 422 | `blocked_pre_write` |
| `E_BINDING_STALE` | binding 自冻结后已过期 | 422 | `blocked_pre_write` |




#### E_DISPATCH_* — 动作派发失败


| code                                      | 含义                   | HTTP 状态 | outcome/处置摘要                |
| ----------------------------------------- | -------------------- | ------- | ------------------- |
| `E_DISPATCH_ACTION_GRANT_EXPIRED` | action grant 在非 SAVE 动作 dispatch 前已过期 | 409 | `blocked_pre_write` |
| `E_DISPATCH_ACTION_GRANT_NOT_HELD` | 当前 job 不持有精确 action grant | 409 | `blocked_pre_write` |
| `E_DISPATCH_QUEUE_VERSION_MISMATCH` | 队列版本在派发前已变更 | 409 | `blocked_pre_write` |
| `E_DISPATCH_APPROVAL_REVOKED` | 人工批准在派发前已撤销 | 403 | `blocked_pre_write` |
| `E_DISPATCH_NO_RUNNING_TASK` | 当前没有 running task | 409 | N/A |
| `E_DISPATCH_SESSION_LOST_PRE_ACTION` | 动作尚未派发且可见会话已断开 | 503 | `blocked_pre_write` |
| `E_DISPATCH_RESULT_UNKNOWN` | 无法排除动作已派发，且网络/worker 结果不确定 | 503 | `unknown` |




#### E_VERIFY_* — 读回校验失败


| code                                          | 含义                 | HTTP 状态 | outcome/处置摘要                      |
| --------------------------------------------- | ------------------ | ------- | ------------------------- |
| `E_VERIFY_VALUE_MISMATCH` | 读回值与冻结预期不一致 | 422 | 按外部 dispatch fact 分流为 `restore_required` 或 `needs_manual_review` |
| `E_VERIFY_HASH_MISMATCH` | 字段/集合 hash 与预期不符 | 422 | 同上 |
| `E_VERIFY_PAGE_CONTEXT_CHANGED` | 读回时页面上下文已漂移 | 409 | `page_identity_drift_pre_save` |
| `E_VERIFY_SECTION_RECEIPT_MISSING` | 分区 receipt 缺失 | 500 | `needs_manual_review` |
| `E_VERIFY_CONTENT_FINALIZE_FAILED` | ContentFinalize 明确失败 | 422 | 按 dispatch fact 分流 |
| `E_VERIFY_FIELD_OWNERSHIP_MISMATCH` | readback 字段有缺失、额外项或多个 owner | 500 | `needs_manual_review` |




#### E_SAVE_* — SAVE 派发与回包失败


| code                                 | 含义                                                            | HTTP 状态 | outcome/处置摘要                  |
| ------------------------------------ | ------------------------------------------------------------- | ------- | --------------------- |
| `E_SAVE_DISPATCH_TIMEOUT` | SAVE 是否派发/生效无法证明 | 504 | `unknown` |
| `E_SAVE_UPSTREAM_RESPONSE_ERROR` | SAVE 上游响应非预期；code/msg 进入 details | 502 | 按是否已派发分流，无法证明则 `unknown` |
| `E_SAVE_BUSINESS_REJECTED` | SAVE 明确返回 business failure | 422 | `save_business_rejected`；`needs_manual_review` |
| `E_SAVE_PAGE_STATE_UNEXPECTED` | SAVE 后页面状态非预期 | 500 | `unknown` |
| `E_SAVE_NOT_PUBLISHED_VERIFY_FAILED` | 独立未发布校验失败 | 422 | `needs_manual_review` |
| `E_SAVE_LEASE_EXPIRED` | SAVE lease 在 SAVE dispatch 前已过期 | 409 | `blocked_pre_write` |
| `E_SAVE_LEASE_NOT_HELD` | 当前 job 不持有精确 SAVE lease | 409 | `blocked_pre_write` |
| `E_SAVE_AUTHORIZATION_NOT_CURRENT` | SAVE 前 JIT/save lease/CAS 任一不成立 | 409 | `blocked_pre_write` |
| `E_SAVE_POSSIBLE_EFFECT_UNCOVERED` | command 声明 `MAY_DISPATCH_SAVE1`，但点击前未覆盖当前 SAVE approval/ledger | 500 | 点击已发生则 `unknown`；否则 `blocked_pre_write` |
| `E_SAVE_LEDGER_BEGIN_MISSING` | 可能触发 SAVE 的点击已发生，但 FIRST_SAVE ledger 未先 BEGIN/MAY_HAVE_DISPATCHED | 500 | `unknown`；人工复核 |
| `E_SAVE_DUPLICATE_LEASE` | 同一 FIRST_SAVE 握手试图签发或消费第二张 save lease | 409 | `blocked_pre_write` |
| `E_SAVE_DUPLICATE_REQUEST_UNPROVEN` | 同一逻辑 FIRST_SAVE 观察到多条 mutation request，且无法证明为平台幂等同一次保存 | 503 | `unknown`；人工复核 |
| `E_SAVE_NOT_DISPATCHED_AFTER_ENTRY` | 原生门已放行且入口动作已闭合，但证据证明 SAVE1 未派发 | 409 | `blocked_pre_write`；当前 attempt 停止 |




#### E_POLICY_* — 安全策略拒绝


| code                                               | 含义                                | HTTP 状态 | outcome/处置摘要                  |
| -------------------------------------------------- | --------------------------------- | ------- | --------------------- |
| `E_POLICY_PUBLISH_GUARD_REJECTED` | PublishGuard 拒绝发布类动作；action kind 进入 details | 403 | `blocked_pre_write` |
| `E_POLICY_PUBLISH_GUARD_BYPASSED` | 检测到绕过 PublishGuard 的尝试 | 500 | `needs_manual_review` |
| `E_POLICY_SEMI_TRANSITION_CONTEXT_MISMATCH` | 半托管入口/“继续发布”上下文不是精确 Path B | 403 | `blocked_pre_write` |
| `E_POLICY_ENTRY_HANDSHAKE_JOIN_REQUIRED` | SAVE1、原生门或同一握手因果 join 未闭合即请求中间转换 | 409 | `blocked_pre_write`；已有不确定 mutation 时转 `unknown` |
| `E_POLICY_SEMI_ENTRY_PRECHECK_FORBIDDEN` | 系统试图自建/主动调用/推断半托管资格预检 | 500 | `needs_manual_review` |
| `E_POLICY_SNAPSHOT_VERSION_MISMATCH` | snapshot 版本与当前 Runner 不匹配 | 422 | `blocked_pre_write` |
| `E_POLICY_ALWAYS_ON_STAGE_DISABLED` | 必经工作流阶段被关闭或改写为 skip/optional | 422 | `blocked_pre_write` |

#### E_SEMI_ENTRY_* — 店小秘原生半托管门

| code | 含义 | HTTP 状态 | outcome/处置摘要 |
| --- | --- | --- | --- |
| `E_SEMI_ENTRY_PLATFORM_REJECTED_MAIN_NOT_SAVED` | 店小秘明确拒绝，且 ledger/网络证明 SAVE1 未派发 | 422 | `stopped`；`outcome_code=semi_entry_rejected_main_not_saved` |
| `E_SEMI_ENTRY_PLATFORM_REJECTED_MAIN_SAVED` | 店小秘明确拒绝，且 SAVE1 三铁证已闭合 | 422 | `stopped`；`outcome_code=semi_entry_rejected_main_saved`；人工复核 |
| `E_SEMI_ENTRY_CAUSAL_BINDING_UNKNOWN` | SAVE1 与原生门的最终事实可能已取得，但无法证明属于同一入口握手 | 503 | `unknown`；人工复核 |
| `E_SEMI_ENTRY_RESULT_UNKNOWN` | 原生门已派发但 admitted/rejected 无法证明（无论 SAVE1 是否已知） | 503 | `unknown`；人工复核 |
| `E_SEMI_ENTRY_PAGE_IDENTITY_MISMATCH` | 入口 join 后未到达精确正式 `editFromSmt` 页面 | 409 | `execution_state=stopped`；`outcome_code=page_identity_drift_pre_save`；`manual_review_required=true`；`completed_save_stage=MAIN_SAVED`；`retry_allowed=false` |




#### E_DRAFT_* — 草稿状态与身份漂移


| code                         | 含义                           | HTTP 状态 | outcome/处置摘要                           |
| ---------------------------- | ---------------------------- | ------- | ------------------------------ |
| `E_DRAFT_STATE_DRIFT` | 草稿状态与当前 checkpoint 不一致 | 409 | `drift_detected_pre_save` |
| `E_DRAFT_REVISION_DRIFT` | 服务器 revision 与当前阶段基线不一致 | 409 | `needs_manual_review` |
| `E_DRAFT_PRODUCT_IDENTITY_DRIFT` | 稳定商品身份不一致 | 409 | `drift_detected_pre_save` |
| `E_DRAFT_PAGE_IDENTITY_DRIFT` | 页面 URL/epoch 与 checkpoint 不匹配 | 409 | `page_identity_drift_pre_save` |
| `E_DRAFT_MISSING` | 当前 Reader 中商品已消失 | 404 | `draft_missing_pre_save` |
| `E_DRAFT_REVISION_UNAVAILABLE` | 无可稳定复核的服务器 revision 事实 | 422 | `blocked_pre_write` |
| `E_DRAFT_SESSION_EXPIRED` | 会话已过期，草稿不可访问 | 401 | `blocked_pre_write` |




#### E_LONG_ACTION_* — 长动作（视频/翻译）失败


| code                                      | 含义                | HTTP 状态 | outcome/处置摘要                                   |
| ----------------------------------------- | ----------------- | ------- | -------------------------------------- |
| `E_LONG_ACTION_QUOTA_EXHAUSTED` | 视频/翻译额度在派发前已耗尽 | 422 | `blocked_pre_write` |
| `E_LONG_ACTION_RESULT_UNKNOWN` | 已派发长动作的结果无法证明 | 504 | `unknown` |
| `E_LONG_ACTION_PROVIDER_REJECTED` | provider 明确拒绝；原始 reason 进入 details | 422 | `long_action_rejected`；`needs_manual_review` |
| `E_LONG_ACTION_DRAFT_DRIFT` | 长动作期间草稿 revision 被外部修改 | 409 | `needs_manual_review` |

用户暂停/停止/取消是 `control_code/outcome_code`，不是错误。成功处理控制意图不得返回 HTTP 200 + `E_*`。




#### E_LEGACY_* — 旧版本与迁移


| code                                  | 含义                                  | HTTP 状态 | outcome/处置摘要 |
| ------------------------------------- | ----------------------------------- | ------- | ---- |
| `E_LEGACY_API_DISABLED` | 调用了已禁用的旧写 Interface | 410 | N/A |
| `E_LEGACY_VERSION_LOCKED` | 旧版本 snapshot/template/task 被拒绝进入写路径 | 409 | N/A |
| `E_LEGACY_MIGRATION_NOT_SUPPORTED` | 尝试把 v1/v3 历史事实升级为可执行新版本 | 422 | N/A |




#### E_SYSTEM_* — 系统级错误


| code                               | 含义                         | HTTP 状态 | outcome/处置摘要                  |
| ---------------------------------- | -------------------------- | ------- | --------------------- |
| `E_SYSTEM_UNEXPECTED_ERROR` | 未预期的异常；已记录结构化日志 | 500 | `needs_manual_review` |
| `E_SYSTEM_WORKFLOW_STAGE_MISSING` | 任何入口动作前发现冻结工作流缺少必需后续阶段 | 500 | `execution_state=stopped`；`outcome_code=blocked_pre_write`；`manual_review_required=false`；`completed_save_stage=NONE`；`retry_allowed=false` |
| `E_SYSTEM_DB_WRITE_FAILURE` | 数据库写入失败 | 500 | `needs_manual_review` |
| `E_SYSTEM_WORKER_DIED` | BrowserAgent worker 进程意外终止 | 503 | 按 dispatch fact 分流，无法证明则 `unknown` |
| `E_SYSTEM_CRASH_RECOVERY_IN_PROGRESS` | 系统正在从崩溃恢复中，不接受新任务 | 503 | N/A |




### 16.3 使用约束

1. **每个非 2xx failure response 必须包含** `reason_code_version`、`reason_code` 和结构化 `details`，不得返回裸 `"error": "xxx"`
2. **reason code 必须对应具体的失败点**，不允许用单一 catch-all system error 覆盖所有异常
3. **reason code 一经发布即冻结**；新增 code 必须先进入唯一 registry 并走 `v_next` 文档变更，禁止运行时拼接
4. **reason code 的 HTTP 状态码必须与上表一致**，不得为 200 返回 error code
5. **前端 UI 必须将静态 reason code + 脱敏 details 翻译为用户可读的中文文案**，但保留 code/version 在 API response 和 receipt 中
6. **reason code 不得在日志中用正则匹配作为业务逻辑**，只能用结构化 API 响应
7. **reason code 的文档、前后端类型和测试必须由同一 registry 校验**；发现未登记 code 或动态模板即门禁失败
