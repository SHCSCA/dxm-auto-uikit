> 由 OpenAI GPT（Codex）AI 生成/维护。

# 当前状态（置顶）

## G0/G1 授权与接手开发（2026-08-03）

- **G0 用户裁定：策略 B**（完整 L0 绿或可审计簇关闭证明为 E2 关闭硬门槛）。计划：`docs/product/L0-策略B-迁移计划.md`。
- **G1 用户授权：允许 commit 固定点**（不自动 push）；范围=E1/E2 核心源码/测试/相关文档与脚本，排除 `data/**`、Cookie、密钥、output/artifacts 垃圾。
- **接手开发**：本轮由独立执行者在策略 B 下推进 G1 → G2 → G3；仍 **禁止 E3 / 真保存发布 / 未授权 raw**。
- **`E2-CLOSE-CANDIDATE` SHA：`09fceb756cd56f6971893db3977a1d97671bc208`**（短 `09fceb7`；消息 `feat(e2): pin E1/E2 plan-snapshot stack as G1 close candidate`；69 files；**未 push**）。
- 仍 **不宣称** `E2_ACCEPTED` / `MVP_READY` / `PROD_READY`，直至 G2+G3(+G4) 按清单满足。

## `REOPEN E2`（2026-08-03 · 关闭清单执行中）

- **当前裁定不变：E2 继续打开，禁止进入 E3；不宣称 `E2_ACCEPTED`、`MVP_READY` 或 `PROD_READY`。**
- 已完整读取 `docs/product/E2-关闭剩余清单.md`、MVP 主合同、Gold 与 `CLAUDE.md`；权威仓为 `D:\Desktop\py\dxm-auto-uikit`，启动身份仍为 `fix/dxm-two-stage-runtime-truth` / `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`，工作树启动记录 `618`（tracked=`84`、deleted=`52`、untracked=`534`）。
- **（已更新）** G0=策略 B、G1 commit 已授权；G4 真实登录/raw 脱敏与 G5-1 Gold 哈希修改 **仍未授权**。历史「无授权」条目仅作过程记录。
- G5-4 现状核查发现 `source_digest` 已存在于前端提交、Pydantic 请求模型和后端 `BEGIN IMMEDIATE` 事务内重读校验，历史 `PROGRESS` 也曾记录关闭；因此不重做业务实现，先做当前事实复验。
- G5-4 首次复验为 `7 failed / 3 passed`：两个后端用例在 digest 校验前被当前正确的 `BATCH_CATEGORY_SCOPE_UNVERIFIABLE` 类目安全门拒绝；五个前端源码字符串用例与当前组件结构漂移。不得删除 digest 或放宽类目门换绿，先把 digest 漂移公共用例迁移到允许的店铺级合同再逐项处理。
- G5-4 当前事实已闭环：仅把 digest 漂移公共测试入口迁移到允许的店铺级 bundle（保留类目绑定 409），现同一事务重读源模板后稳定返回 `TEMPLATE_SOURCE_DIGEST_DRIFT` 且不生成 bundle；店铺级成功路径、前端 ready 候选提交完整 `source_digest`、类型合同组合 `4 passed in 3.63s`。未改生产实现，清单 G5-4 已按复验事实勾选；首次聚合暴露的其余前端字符串测试漂移继续作为 L0 迁移项，不能拿 G5-4 绿覆盖。
- L0 同簇基线：`test_edit_batch_bundle_composer.py` + 前端 composer 合同原样为 `29 failed / 7 passed in 28.71s`；其中 24 个后端失败共享“测试仍传已禁止的类目绑定”根因。首个成功路径已逐项迁移到店铺级源模板/请求，完整 8 分区冻结 bundle `1 passed in 2.53s`，类目绑定 409 用例保持原样。
- L0 同簇第 2 条：分组 `dxm_reference` 源模板改用店铺级绑定后，嵌套 `dxm_reference_templates` 仍经正式 composer 规范化并创建 bundle，`1 passed in 3.85s`；未放宽来源完整性或 digest 校验。
- L0 同簇第 3 条：不存在店铺用例先从有效店铺级候选取得完整 digest，再提交不存在的 store id，正式 API 保持 404 `STORE_NOT_FOUND`，`1 passed in 3.98s`。
- L0 同簇第 4 条：8 分区选择形状三个反例迁移到店铺级入口后，缺分区、额外 `publish` 分区和候选字段注入仍全部 422，`3 passed in 5.37s`；extra-forbid 未放宽。
- L0 同簇第 5 条：disabled、wrong type、store binding conflict 三个源模板反例均从有效店铺级候选后制造漂移，正式 API 分别保持 `TEMPLATE_SOURCE_DISABLED` / `TEMPLATE_SOURCE_TYPE_MISMATCH` / `TEMPLATE_SOURCE_BINDING_CONFLICT`，`3 passed in 7.14s`。
- L0 同簇第 6 条：店铺 binding 精确 token 反例迁移后，`notDXM Shop A` 仍不能冒充 `DXM Shop A`；options 标记 binding 缺口且 compose 返回 `TEMPLATE_SOURCE_BINDING_CONFLICT`，`1 passed in 4.40s`。
- L0 同簇第 7 条：店铺级物流模板删除重量后，options 保持 `ready_count=0`/`missing_fields=[logistics.weight]`，compose 返回 `TEMPLATE_BUNDLE_INCOMPLETE`，`1 passed in 5.49s`。
- L0 同簇第 8 条：普通 category 分区错误使用扁平字段而非嵌套对象时，店铺级 compose 仍返回 `TEMPLATE_SOURCE_INCOMPLETE`，`1 passed in 3.71s`。
- L0 同簇第 9 条：10 个递归发布指令反例迁移到店铺级后全部保持 `TEMPLATE_PUBLISH_FORBIDDEN`，`10 passed in 14.56s`；布尔/数字/字符串 `publish`、`published/should_publish/auto_publish` 及 `publish/continue_publish/save_and_publish` action 均未放行。
- L0 同簇第 10 条：店铺级 bundle 同请求保持幂等、禁用后可按同内容重新启用；同版本换有效源内容仍返回 `TEMPLATE_BUNDLE_VERSION_CONFLICT` 且记录数不增，`1 passed in 5.52s`。
- L0 同簇第 11 条：通用模板 API 仍不能直接创建、转换或篡改 `edit_batch_bundle`，只允许单独启停；未知字段仍 422，`1 passed in 2.38s`。
- L0 bundle composer 整文件收束：原样复跑 `test_edit_batch_bundle_composer.py` 得 `28 passed in 28.72s`、exit 0；类目作用域不可验证拒绝、发布指令、digest 漂移、必填、幂等和通用 API 防绕过均保留。该文件从第五轮完整 L0 中的一个明确失败簇转绿，但不推断全仓剩余失败数。
- 前端 composer L0 第 1 条：默认模式测试改为验证 `initialMode='sections'` 的公开默认值及“普货模板库 · 分区/整批”现行中文标签，`1 passed in 0.15s`；未改运行组件。
- 前端 composer L0 第 2 条：候选查询合同现明确只发送 `store_id`、禁止设置 category 参数，创建请求固定 `category_name:null` 且仍禁止 payload/localStorage/mock 注入，`1 passed in 0.24s`。
- 前端 composer L0 第 3 条：成功/错误消息断言迁移到当前显式分支 `message && !optionsError` + `message.text`，候选错误不会被成功消息覆盖；刷新与“回到批次草稿”行为保持，`1 passed in 0.13s`。
- 前端 composer L0 第 4 条：作用域测试冻结为只允许 `category_name:null` 的店铺级 bundle，并验证 UI 明示“整批模板固定按店铺绑定”且拒绝后端返回非空 category，`1 passed in 0.11s`。
- 前端 composer L0 第 5 条实际 UI 修复：`.batch-template-store-binding small` 从 11px 提升为 12px；可读性合同 `1 passed in 0.07s`，未改 1100/860 响应式主布局。
- 前端 composer 整文件复跑 `8 passed in 0.11s`、exit 0。与后端 composer 文件合计原基线 `29 failed / 7 passed` 的聚焦簇现已分别全绿；仍需组合复跑和更大门禁证明无交叉回归。
- L0 composer 聚焦簇组合复跑：`test_edit_batch_bundle_composer.py` + `test_frontend_batch_template_composer_contract.py` 原样得到 `36 passed in 26.80s`、exit 0，相比本轮 RED 基线关闭 `29` 个失败且未增加 skip、未放宽类目/发布/digest/必填门禁。
- 当前工作树 E2 扩展集中回归：value contract、生产 Reader、snapshot/API、前端 E2 合同、bundle composer 后端/前端六文件合计 `122 passed in 60.11s`、exit 0。该结果只证明未提交工作树，不能替代 G1 固定 SHA 上的 G2 独立复跑。
- 当前工作树标准前端 `npm run build` exit 0：Node `12/12`、Chromium `6 passed in 21.24s`、typecheck、Vite `56 modules` 全绿，产物 `index-CP8UVCUn.css` / `index-wIEuflzs.js`；仍须在未来关闭候选 SHA 上独立重跑。
- 当前工作树桌面版本门禁 `npm test` exit 0：`89/89 passed`、0 skipped/todo，package 版本保持 `0.1.1`。
- 当前工作树保护门禁：文档 SelfTest 两项 `RED_EXPECTED` 后 `MVP_DOCS_OK`、exit 0；`git diff --check` exit 0；凭据字面量、`runner_released=true`、`publish_allowed=true` 差异命中均为 0。分支/HEAD 未变，状态 `619`（tracked=`85`、deleted=`52`、untracked=`534`）；Gold/根原型 SHA256 仍为冻结值，8000/5173 监听数 0。
- 完整 L0 `-x` 首探针（独立临时 `DXM_DATA_DIR`）为 `1 failed / 4 passed`：旧 acquisition claim API 用例缺现行必填 `source_url`，实际 422。未放宽生产模型；测试补入明确来源 URL，并断言响应与任务 payload 同源，目标用例转为 `1 passed in 2.78s`。该迁移只维护历史 Stage A 安全能力，不把 claim_only 恢复为 MVP 前置。
- 完整 L0 `-x` 第 2 探针推进到 `1 failed / 10 passed`：旧“必须 keyword/category”测试与当前“`source_url` 必填、keyword/category 可空”的来源身份合同冲突。保留测试数并迁移为缺 `source_url` 必须 Pydantic 422/missing，目标用例 `1 passed in 5.70s`；生产代码未改。
- 完整 L0 `-x` 第 3 探针推进到 `1 failed / 16 passed`：伪造 `claimed_to_draft/draft_box_verified` 的未证明商品已正确 409，旧断言却要求把所有缺证明商品称为“测试/示例数据”。测试改为验证不可伪造的完成认领任务链与商品箱要求，目标用例 `1 passed in 3.52s`；拒绝条件未变。
- acquisition claim 整文件原样复跑 `24 passed in 21.87s`、exit 0；来源 URL 必填、目标身份、完成证明、跨店拒绝和伪造 flags 拒绝均保留。该历史能力仅作为 L0 债迁移，不进入 E2 产品主链。
- 完整 L0 `-x` 第 4 探针推进到 `1 failed / 42 passed`：action-result 注册表的 SAVE_ONLY 成功夹具缺现行 `save_result`。生产合同未放宽；测试工厂补齐唯一保存按钮、mutation 授权、写前零写/身份/字段完整性、DXM add.json 回包、闭合零发布审计和结构化页面成功态，注册表 + 独立 save descriptor 两用例 `2 passed in 0.16s`。未释放 Runner 或执行写入。
- action-result 整文件首跑 `8 failed / 71 passed`，八项均由旧未发布夹具缺 `fresh_probe` 引起；补齐目标绑定结构化未发布状态、唯一候选、同源身份读回和与 SAVE 相同 target digest 后，整文件 `79 passed in 0.43s`、exit 0。证据路径不复用、时间先后、target/runtime/session 反例均重新命中目标断言，三铁证未放宽。
- 完整 L0 `-x` 第 5 探针推进到 `1 failed / 110 passed`：Agent Console 预览共享夹具错误使用 `single_save` 且无认领证明。因三个调用方只测预览/接管/控制拒绝，按最小权限迁移为 `probe / READ_ONLY_PROBE`，三用例 `3 passed in 5.35s`；未伪造 claim proof、未开放保存模式。
- Agent Console 整文件原样复跑 `42 passed in 8.06s`、exit 0；预览、人工接管、selector/type 阻断、网络事件边界均保持。
- 完整 L0 `-x` 第 6 探针推进到 `1 failed / 153 passed`：scope snapshot 端点已按最小披露只返回公开视图，旧测试却从响应读取内部 `schema_version/digest/evidence`。未扩大 API 泄露面；测试改为先断言公开响应不含 digest/evidence，再经 Repository 读取持久化快照校验完整 schema、canonical digest、DOM evidence 与零写证明，目标用例 `1 passed in 6.86s`。
- 完整 L0 `-x` 第 7 探针推进到 `1 failed / 154 passed`：LoginFlow 真实 raw 合同测试同样误从公开响应读取 `evidence`。现保持端点不回显 digest/evidence，同时从持久化记录证明 `dom_sha256/refs_digest` 与生产 capture 完全一致，目标用例 `1 passed in 3.33s`；未削弱真实 wire 兼容或证据保存。
- 完整 L0 `-x` 第 8 探针推进到 `1 failed / 158 passed`：批次公共工厂仍直接创建会被现行安全门隔离的“类目绑定 + 不可执行 DXM 名称引用”bundle，并把 API 公开投影当内部冻结记录。工厂迁移到店铺级、已登记 AliExpress 店铺与可执行引用基线；API 保持最小披露，内部 digest/snapshot 改由私有仓储合同校验，主冻结用例 `1 passed in 2.41s`。
- `test_batch_edit_api.py` 整文件首次复跑为 `26 failed / 21 passed`：其中 4 项为同一公开/私有投影、店铺登记及重复 helper 漂移，已逐项迁移并组合 `4 passed in 6.33s`；其余 22 项全部在独立 manual-approval 入口被正确的 `BATCH_APPROVAL_REQUIRES_ATOMIC_START` 提前拒绝，暂不为旧 E3 测试重开令牌入口。
- G5 文档收束：现行 `CLAUDE/AGENTS/docs` 指针已由 SelfTest 证明可解析（冻结 Gold 悬空链接仍单列待授权）；根 README 已把当前主叙事改为草稿箱多选 + E2 不可变快照，并明确源码/package `0.1.1` 尚无对应 portable、既有 `0.1.0` 路径仅为历史证据。
- 英文/data lease/browser 边界已冻结：保守无依赖词表不是通用 NLP，证据不足一律 `UNKNOWN`；pytest 必须停 live 服务或使用唯一隔离 `DXM_DATA_DIR`，`-x` 不算完整 L0；标准 `npm run build` 的 Browser 文件实际包含 2 个 `LocalPlanWorkspace` E2 Chromium 用例，本轮当次 Browser `6/6`，无需新增第三套 runner。
- 旧批次 API 文件当前固定结果为 `22 failed / 25 passed in 34.05s`：相对本轮首跑 `26 failed / 21 passed` 已关闭 4 个公开投影/店铺工厂失败；22 个剩余均为待裁决的历史独立批准簇，未通过重开端点或改期望为假绿。
- 本轮最终集中回归使用唯一 `DXM_DATA_DIR=C:\Users\wz\AppData\Local\Temp\dxm-e2-final-46cf8f3a6fcc410898bf43df790ed2fc`，E2/Reader/composer/acquisition/action-result/Agent Console 九文件合计 `267 passed in 79.34s`、exit 0；该结果明确不替代完整 L0。
- 最终文档/保护门禁：SelfTest 输出两项 `RED_EXPECTED` 后 `MVP_DOCS_OK`、exit 0；`git diff --check` exit 0（仅 LF→CRLF warning）；凭据字面量、`runner_released=true`、`publish_allowed=true` 命中均为 0，8000/5173 监听数均 0。
- 最终身份与冻结哈希：分支/HEAD 仍为 `fix/dxm-two-stage-runtime-truth` / `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；状态 `624`（tracked=`90`、deleted=`52`、untracked=`534`），既有删除未恢复。Gold=`648E004FBF600AE4620435ADD3C8324D473710EC283ACDA139BCF337FE8EAE1C`、根原型=`29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`；未 commit/push，未登录、保存、发布或读取受禁 raw/Cookie。
- 续做批准簇审计：现有 `test_batch_execution_contract.py` 覆盖底层 start authorization 的绑定、过期和 replay，但仓内没有 `/approve-and-start` API 等价测试；把 22 个旧 `/manual-approval` 用例全部改为同一 409 会丢失 runtime/DOM/order/CAS/token-leak 安全性质，改调用原子启动又越过 E2。因此保持 22 红并细化 BLOCKED，不通过删断言或释放 E3 换绿。
- G5-5 已登记本地技术债 `DXM-E2-TECH-001`：`execution/dxm_login_flow.py` 实测 22,807 行，后续只拆四个 E2 只读入口与 wire normalization；本轮只登记范围/硬边界/DoD，不改生产代码或公开合同。
- §6.4 首次并行映射复跑错误共用默认 data lease，收集期 `RuntimeLeaseConflictError`，结果作废；改为四个唯一 `%TEMP%/dxm-e2-regression-*` 后，Reader wire=`9 passed / 33 deselected`、snapshot invariants=`7 passed / 32 deselected`、英文/价格=`19 passed / 20 deselected`、DOM/旧类目安全=`7 passed`，全部 exit 0。因 G1 尚无固定 SHA，最终复选框保持未勾。
- G1 无写入盘点已完成：10 个 E2 后端深模块、5 个专项/Reader/Browser 测试、`LocalPlanWorkspace.tsx`、MVP/PROGRESS/BLOCKED/本清单当前均为存在但 `??`；`main/db/models`、前端导航/API/types/composer/styles 和三端版本真源为 tracked modified。白名单已写入清单 §2.4，明确未来不得全仓通配 staging；本轮仍未 `git add`、commit 或 push。
- 续做收口复核：文档 SelfTest 再次输出两项 `RED_EXPECTED` 后 `MVP_DOCS_OK`，`git diff --check` exit 0；状态仍为 624/90/52/534，分支/HEAD 未变；Gold/根原型哈希仍为冻结值，8000/5173 无监听，凭据/runner released/publish allowed true 扫描均为 0。
- 第三次连续阻断审计：G0 A/B、G1 commit、G4 真实零写/raw、G5-1 Gold 与旧批准簇裁决五项均仍无新增授权；HEAD/状态仍为 `fd0da945…` / 624。所有不进入 E3、不读取受禁数据、不提交的安全工作已完成，继续执行只会重复门禁或越权，因此按 goal 规则正式进入 `blocked`，E2 仍保持 `REOPEN` 而非完成。

## `REOPEN E2`（2026-08-03 · 第五次独立验收不通过）

- **当前裁定：E2 继续打开，禁止进入 E3；不宣称 E2 完成、`MVP_READY` 或 `PROD_READY`。**
- 第五轮真实重放确认前四轮 raw 解析 P0 基本关闭：属性模板 `50/50`、产品模板 `5/5`；`2621` checkbox/图片/19 行 SKU 库存完成归一化，22 个当前字段 Schema 类型错误为 0。
- 新 P0：真实 `2621` 的 SKU 价格均在 min/max 内且 `cargoPrice<=skuPrice`，但独立 `productPrice` 不在 SKU min/max 区间；当前错误冻结 `productMinPrice<=productPrice<=productMaxPrice` 并返回 `PLAN_PRICE_RELATION_INVALID`，导致正式 preview/freeze 不成立。
- 新 P1：`Cosplay Costume Accessories for Halloween Party` 与 `Handmade Resin Statue Desktop Decoration Gift` 仍被英文门禁判为 `UNKNOWN`；完整 L0 仍为 `509 failed / 1392 passed`，另有 DOM 身份把 `id=abcde` 当稳定商品 ID 的具体红点。
- 新 P2/证据缺口：两个指定类目没有真实 edit/schema，13 个真实 child 回包均为空；仓内 50 条 raw-wire 仍是现场生成而非脱敏固定 fixture；E2 Reader 逻辑仍聚集在约 2.2 万行 `DxmLoginFlow`；核心源码仍处 533 个未跟踪文件中。
- 本轮顺序：真实价格语义公开红→绿 → 两个英文标题逐条红→绿 → 受影响集中回归 → 版本真源更新 → 前端/文档/哈希/范围门禁。原始 `DXM-TX/data/**`、真实登录/保存/发布、E3、Gold 写入仍禁止；无法取得的两个类目/非空 child/真实 fixture 继续写 BLOCKED。
- 价格语义 P0 已公开红→绿：脱敏 `2621` 形态满足全部 SKU 售价落在 min/max 且 `cargoPrice<=skuPrice`，仅独立 `productPrice` 位于区间外；旧实现稳定返回 409 `PLAN_PRICE_RELATION_INVALID`。现从生产 Schema、校验记录、前端类型和中文说明中删除错误的 `productPrice` 区间关系，仅冻结 `min<=max`、SKU 售价区间与货值≤售价；同一 preview 与 cargo 超价反例组合 `2 passed`。
- 英文标题 P1（1/2）已红→绿：`Cosplay Costume Accessories for Halloween Party` 先稳定返回 409 `NATURAL_LANGUAGE_ENGLISH_REQUIRED`；现补充目标类目常用词，并增加通用 `-ies→-y` 复数还原以复用既有 `accessory` 词证据，单条公开 preview `1 passed`，未降低未知词比例或脚本门禁。
- 英文标题 P1（2/2）已红→绿：`Handmade Resin Statue Desktop Decoration Gift` 同样先稳定返回 409；现仅补充 `handmade/resin/statue/desktop/decoration` 五个明确商品词，单条公开 preview `1 passed`。法/西语、混合脚本、`Product title malapa rebeka` 与无元音乱码反例仍须在集中回归保持拒绝。
- 第五轮修复集中回归：首次 `86 passed in 27.02s` 后外层 30 秒清理超时返回 124，未当作绿证据；原样把命令时限放宽至 60 秒复跑，实际 `86 passed in 26.15s`、exit 0。覆盖 value contract、生产 Reader、全部 E2 snapshot、英文正反例、价格规则和前端 E2 合同。
- 版本已按 bugfix 语义从 `0.1.0` 提升到 `0.1.1`：同步更新后端 `pyproject.toml`/运行 `APP_VERSION`、前端 package/lock 与桌面 package/lock 根版本。未修改 README 或验证脚本中既有 `0.1.0` portable 路径，因本轮未构建、验收或交付新桌面可执行包。
- 版本/前端门禁：桌面全套首次因生成器测试仍期待 `0.1.0` 得到 `88 passed / 1 failed`；只同步明确版本期望后原样复跑为 `89/89 passed`、exit 0。标准前端 `npm run build` 以 `0.1.1` exit 0：Node `12/12`、Chromium `6/6 in 22.30s`、typecheck、Vite `56 modules transformed` 全绿，产物 `index-DfpWeZYY.css` / `index-OvHCPYjB.js`。
- L0 具体身份红点已红→绿：既有 DOM 公共用例精确复现 `/web/smt/edit?id=abcde` 被错误接受，首轮 `1 failed / 4 passed`。现浏览器提取器与 Python 归一化双层要求商品 ID 为 5–128 位允许字符且至少含一位数字；`DXM-1001`、纯数字和受支持来源 URL 保持有效，原样复跑 `5 passed in 8.14s`。未对其余历史 L0 放宽断言。
- 第五轮最终后端集中回归：DOM 身份收紧后再次原样运行 value/Reader/E2 snapshot/frontend contract，`86 passed in 30.09s`、exit 0；专项绿仍不得覆盖完整 L0 红线。
- 第五轮保护收口：Python `py_compile` exit 0；后端、前端/桌面 package 与两个 lock 根/空包共 8 个版本字段均严格读取为 `0.1.1`（首次 lockfile 检查因 PowerShell 空键解析错误产生假 `VERSION_OK`，已废弃并改用 `-AsHashtable` 后重跑）；文档 SelfTest 两项 `RED_EXPECTED` 后 `MVP_DOCS_OK`；`git diff --check` exit 0（仅既有 LF→CRLF warning）。Gold/根原型哈希仍为冻结值，8000/5173 监听数为 0，差异中账号密码字面量与 `runner_released=true/publish_allowed=true` 均命中 0。
- 第五轮最终工作树：分支/HEAD 仍为 `fix/dxm-two-stage-runtime-truth` / `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；状态记录 `617`（tracked=`84`、既有 deleted=`52`、untracked=`533`）。未恢复删除、未清理未跟踪文件、未提交/推送；E2 继续 `REOPEN`，等待完整 L0、Git 固定点与真实三类目/child/fixture 授权证据。

## `REOPEN E2`（2026-07-30 · 第四次独立验收不通过）

- **当前裁定：E2 继续打开，禁止进入 E3；完整 L0、标准前端流水线和真实三类目零写证据未绿，不宣称任何 READY。**
- 本轮 P0：有内容但无 `attrNameId/attrValueId` 的模板自定义属性仍中断同步，且模板 checkbox 未按 Schema 数组化；真实 `2621` edit 的 `ipmSkuStock` 数字字符串和分号图片串未归一化，预览仍可报 `PLAN_FIELD_SCHEMA_INVALID`。
- 本轮 P1：常见动漫/耳机英文标题被误拒；SKU 售价/货值/商品价格缺关系规则；SKU 子字段缺完整 `ui_label_zh`。
- 本轮 Standards：完整 L0 仍为 `509 failed / 1386 passed`；外部当次标准 `npm run build` 为 Browser `1 failed / 5 passed`、整体 exit 1；Gold 第 43 行仍有悬空指针，但 Gold 属于只读哈希冻结文件，只能列入 BLOCKED。
- 本轮 P2：`stable_field_key/is_resolved_value/canonical clone` 仍重复；`plan_contract.py` 仍直接解释 `dxm_template_refs` 表，且 `E2PlanService` 职责仍偏多；真实 child 正向回包与三类目真实链仍缺。
- 返修顺序：模板无 ID 审计项 + template Schema-aware normalization → edit SKU/图片 normalization → 英文正反语料 → 价格关系 + SKU 中文 Schema → 去重与 reference-store 深化 → 标准 build 稳定复跑 → 完整 L0。
- 安全边界：继续禁止读取 `DXM-TX/data/**`、raw 抓包、Cookie 或真实业务样例；只按验收披露的真实 wire 形态制作脱敏回归。不得启动 Runner、保存、发布、修改 Gold 或进入 E3。
- 模板无 ID/checkbox P0 已红→绿：公开生产 Reader 用“有 `attrName/attrValue`、无 ID”的脱敏真实形态先稳定报 `DXM_PLAN_IDENTITY_INVALID`；现仅在名称和值均可审计时保存为 `executable=false` 的 `DXM_TEMPLATE_ATTRIBUTE_ID_UNMAPPED` 项，既不进入 `resolved_values` 也不冒充 Schema 字段。审计项随 `dxm_template_ref` 持久化并独立 hash/count；同一生产链再按该模板 `category_id` 的冻结 Schema 把 checkbox singleton 包为 array。Reader 与持久化 API 分别 `1 passed`。
- template/edit wire P0 已红→绿：正式预览先以 `ipmSkuStock="12"` 稳定复现 409 `PLAN_FIELD_SCHEMA_INVALID`；现模板值和商品当前值共用冻结 Schema 归一化，checkbox singleton→array、严格整数串→integer、仅声明 `wire_format=semicolon_delimited` 的图片串→URL array，并递归处理 SKU object。产品模板与 edit 预览均转绿；`12.5` 库存和图片空段两个反例保持 409，组合 `4 passed`。
- 英文可用性 P1 已红→绿：把验收给出的 Marvel/Anime/耳机三条正常标题原样加入公开预览，旧门禁先得到 `3 failed / 5 passed`；现仅扩充目标类目通用商品词和 PVC 等稳定代码，保留未知词比例、脚本与伪词规则。8 条正常标题全绿，`Product title malapa rebeka`、法/西语、混合脚本及无元音乱码 6 条继续拒绝，组合 `14 passed`。
- 价格关系/SKU 中文 P1 已红→绿：冻结 Schema 新增 `SKU货值≤SKU售价`、商品价与各 SKU 售价落在最低/最高价区间三条关系，并把当前值与最终解析值的校验结果写入 resolution hash；`cargoPrice=10.50 > skuPrice=9.99` 的正式预览返回 `PLAN_PRICE_RELATION_INVALID`。SKU 编码/售价/货值/库存及 SKU 属性子字段均有中文标签，UI 明示冻结规则；后端/前端合同 `4 passed`，TypeScript exit 0。
- 模块 P2 已完成不放宽安全合同的收束：`stable_field_key`、`is_resolved_value` 与 canonical clone 改为复用 `PlanValueContract`；本地方案创建与快照预览均通过 `plan_reference_store.resolve_bindings` 解析店小秘引用，不再由 `E2PlanService` 直接读取/解释该表。首轮集中回归捕获创建入口残留旧 `_assert_plan_refs`（`3 failed / 47 passed`），修正同一入口后原样重跑为 `81 passed in 34.53s`。
- 2026-08-03 续做 P2：用 deletion test 深化模板引用 Module；`resolve_bindings()` 现返回不可变的 `ResolvedTemplateReferences`，由其统一隐藏 `_resolved_values/_audit_items`、生成冻结摘要、按类目/Schema 允许字段解析值、拼接来源证明并执行冲突拒绝。`E2PlanService` 不再理解模板引用的存储私有形状。公开契约新增“同类目冲突 409 `DXM_TEMPLATE_VALUE_CONFLICT` / 异类目不串值”，修正测试绑定遗漏后为 `2 passed`；版本、冻结、配置优先级和漂移/范围/必填/语言主链 `4 passed`；最终 value/Reader/E2 snapshot/frontend contract 集中回归 `83 passed in 26.51s`。
- 2026-08-03 续做 P2（本地方案）：新增深 `LocalPlanTemplateStore` Module，集中方案规范化、只读模板绑定、lineage/supersedes、版本唯一性、CRUD/归档和活动版本快照输入装载；`E2PlanService` 对本地方案只保留委托 Interface，不再直接读写 `local_plan_templates`。编译与版本/冻结主链 `2 passed`，新增“归档版本不得生成快照”公开不变量为 `1 passed`；未抽象只有一个 SQLite Adapter 的假想 Seam。
- 2026-08-03 续做 P2（快照编译）：新增深 `PlanSnapshotCompiler` Module，把 session/shop/item scope、逐品 Schema/hash、字段映射、fixed→fill→模板→current 解析、英文/必填/价格规则和最终 hash 收进 `compile(request)` / `assert_hash(snapshot)` 两个 Interface。`E2PlanService` 降为 163 行 façade，仅编排模板、本地方案、编译、原子冻结与任务读取；核心版本/冻结/失败关闭/模板冲突隔离 `5 passed`，最终 value/Reader/E2 snapshot/frontend contract 集中回归 `83 passed in 24.59s`；JSON、错误码、Runner 边界均未改。
- 2026-08-03 续做保护门禁：四个受影响 Python 文件与公开测试 `py_compile` exit 0；文档 SelfTest 输出两项 `RED_EXPECTED` 后 `MVP_DOCS_OK`；`git diff --check` exit 0（仅既有 LF→CRLF warning）。分支/HEAD 仍为 `fix/dxm-two-stage-runtime-truth` / `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；Gold/根原型 SHA256 仍为冻结值。工作树 `612` 条（tracked=`79`、既有 deleted=`52`、untracked=`533`），新增 2 条仅为本轮两个 Python Module；未恢复、清理、提交或推送。
- 标准前端流水线已形成一次完整绿证据：原样 `npm run build` exit 0；内部 Node `12/12`、Chromium `6 passed in 79.12s`、TypeScript 以及 Vite production build 全部通过，Vite `56 modules transformed`，产物 `index-DfpWeZYY.css` / `index-BOgdmec0.js`。该结果关闭本次验收所述的 Vite harness 偶发聚合失败，但不覆盖完整后端 L0 红线。
- 第四次返修完整 L0 已原样跑完：`509 failed / 1392 passed / 0 skipped in 2742.15s`，exit 1。failed 与本轮开工基线 `509` 完全相同，新增 6 个 passed 对应新增公开回归；因此本轮未增加全仓失败，但“失败数没增加”仍不等于通过。代表性失败继续落在旧 acquisition claim、action evidence 和 v1 `single_save`/Runner 合同，不以不安全默认值、放宽三铁证或恢复旧叙事换绿；E2 继续 `REOPEN`。
- 最终保护验收：文档 SelfTest 原样输出两项 `RED_EXPECTED` 后 `MVP_DOCS_OK`，exit 0；`git diff --check` exit 0（仅既有 LF→CRLF warning）。分支/HEAD 仍为 `fix/dxm-two-stage-runtime-truth` / `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；Gold SHA256=`648E004FBF600AE4620435ADD3C8324D473710EC283ACDA139BCF337FE8EAE1C`，根原型 SHA256=`29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`，均保持冻结。
- 最终工作树事实：`610` 条状态记录（tracked=`79`、既有 deleted=`52`、untracked=`531`）；没有恢复 52 个删除、没有清理未跟踪文件、没有提交/推送。Gold 悬空第 43 行因只读哈希边界继续记录在 BLOCKED；受禁读边界限制，真实 50/50、`2621` raw 零冲突及三个指定类目的真实零写链仍需外部复验。
- 交付前差异安全扫描（排除 `data/**`）：用户曾提供的账号/密码字面量命中 `0`，`runner_released=true` / `publish_allowed=true` 正向模式命中 `0`；`/start|/publish` 的 20 个文本命中经逐条查看均来自既有删除内容、历史说明或禁止语义，没有新增 E2 写入入口。

## `REOPEN E2`（2026-07-30 · 第三次独立验收不通过）

- **当前裁定：E2 继续打开，禁止进入 E3；不宣称 E2 完成、`MVP_READY` 或 `PROD_READY`。**
- 本轮三个 P0：字段解析优先级错误，用户配置会被商品当前值/店小秘模板吞掉；真实模板空 ID 占位和 `promiseTemplateId=0` 哨兵仍被拒；真实类目 `2621` 的单选 checkbox 被读成 scalar，预览返回 `PLAN_FIELD_SCHEMA_INVALID`。
- 本轮 P1：生产链未调用真实 `POST /api/smtCategory/childAttributeList.json`；英文门禁既接受 `Product title malapa rebeka`，又拒绝正常英文标题；Schema 与中文结构化固定值/规则入口不完整。
- 本轮 P2：`CLAUDE.md` 仍把三份已删除文档当现行指针；`E2PlanService` 约 918 行且安全 helper 重复；指定三类目仅有替换 ID 的脱敏合成矩阵，没有三类目真实零写只读证据。
- 完整门禁事实保持红：后端完整 L0 为 `509 failed / 1372 passed / 0 skipped`；专项绿不能替代完整门禁。旧五文件仍为 `111 failed / 24 passed`。
- 返修顺序：字段优先级红→绿 → 空 ID/零哨兵模板红→绿 → checkbox scalar→array 红→绿 → 真实 childAttributeList 调用与条件 Schema → 英文/完整 Schema/中文结构化模式 → 陈旧指针与模块重复 → 完整 L0 失败簇。
- 安全边界不变：不读取 `DXM-TX/data/**`、raw 抓包、Cookie 或真实业务样例；只使用验收披露形态构造脱敏 wire 回归。不得启动 Runner、保存、发布或进入 E3。
- 下方第二次返修中“fixed values/真实 Schema/英文/三类目已关闭”的表述已被本次复验覆盖，仅保留为历史过程证据。
- 字段优先级 P0 已红→绿：公开预览先证明用户补差标题实际冻结为 `source=current`；现按“明确固定值 → 用户补差规则 → 店小秘只读模板 → 商品当前值”解析，固定值仍高于补差，配置值不会再被模板或旧商品值吞掉。定向 `1 passed`，整份 E2 API `19 passed in 12.83s`。
- 真实模板格式 P0 已红→绿：50 条脱敏属性模板中 38 条加入全空 ID 占位后先稳定报 `DXM_PLAN_IDENTITY_INVALID`，现仅忽略所有已知身份/值字段都为空的占位；有值但无 ID 仍 fail-closed。5 条产品模板加入精确 `promiseTemplateId=0` 未选择哨兵后先稳定报 `DXM_TEMPLATE_RESPONSE_INVALID`，现只把整数/字符串零视为“未选择”并从解析结果省略，其他模板 ID 仍要求正整数。定向分别 `1 passed`、组合严格类型 `5 passed`。
- 类目 `2621` checkbox P0 已红→绿：公开预览用 `attr_400000603` 的单个当前选中值与冻结 array Schema 先稳定返回 409 `PLAN_FIELD_SCHEMA_INVALID`；现只对 Schema 明确声明为 array 的类目属性把 scalar 包为单元素数组，scalar Schema 保持原值。公开预览与旧 scalar 规范化组合 `2 passed`。
- 真实级联属性 P1 已红→绿：生产只读白名单新增 `POST /api/smtCategory/childAttributeList.json` 及精确 `categoryId/arrtNameId/arrtValueId` 表单；Reader 从具体 option 的 `hasSubAttr` 触发读取，不再信任父属性顶层内嵌 children。array 父值冻结为 `allOf.if.properties.<field>.contains.const` 条件，选中该值才激活子字段 required；严格缺子定义继续 fail-closed。端点用例与公开预览条件激活均转绿，Reader+E2 API 集中回归 `63 passed in 12.37s`。
- 英文门禁 P1 已红→绿：`Product title malapa rebeka` 先被错误接受，现限制未知词比例并保持混合脚本、法/西语和占位乱码拒绝；同时补充词形与保守商品领域词汇，5 条正常英文商品标题从全部误拒转为全绿。HTML 与移动端 JSON 描述先因标签/结构键误拒，现仅抽取文本叶子再验证；非英文仍返回 `UNKNOWN` 停批。英文正反例合计 `11 passed`，描述链 `1 passed`，未新增第三方依赖。
- 编辑 Schema/UI P1 已红→绿：生产 Schema 新增 PC/移动描述、图片、SKU 子项（编码/售价/货值/库存/属性轴）和价格区间约束；中文界面为每字段显式提供“继承 / 补差 / 固定”来源策略，序列化到互斥 `fill_rules` 与 `fixed_values.field_values`。图片与带 object 子项的数组使用结构化增删控件，不开放 JSON textarea。真实 Chromium 证明固定标题+图片和补差材质进入正确请求区；集中后端/合同 `72 passed in 24.08s`，前端 Node `12/12`、Browser `6/6`、typecheck 与 Vite `56 modules` 构建通过。
- 文档/模块 P2 已红→绿：`CLAUDE.md` 不再把三份既有删除文档当现行架构/门禁指针，改指可解析 docs 索引、MVP 主合同与 Gold，并明确旧文件不得用于 READY。发布指令扫描、规范化 ID/hash/text、canonical clone 等公共安全 helper 抽到单一 `plan_value_contract.py`；DXM 只读模板同步/持久化再抽到 `plan_reference_store.py`。`plan_contract.py` 从本轮 866 行降至约 630 行，`plan_template_contract.py` 降至约 300 行；共享安全契约与集中回归 `75 passed in 25.04s`。
- 第三次返修完整 L0：在 D: 临时目录规避 C: 满盘后原样完成，实际 `509 failed / 1386 passed / 0 skipped in 981.02s`。失败数与复验输入完全相同，passed 增加 14 来自本轮新增回归；因此没有本轮新增全仓失败，但完整门禁仍红，E2 不得关闭。下一步按 `login_flow` TypeError、action evidence、旧 task/runner 模式和旧批量安全门四簇抽样定位。
- 完整 L0 失败簇抽样：旧登录流用例直接调用现在要求 `target_identity/store_name/baseline_field_integrity/required_readback_complete` 的私有 `_save_only_on_page()`，当前精确报 `TypeError`；另有旧 action-result 夹具缺少结构化 `save_result/fresh_probe`，以及历史 `claim_only/single_save` runner 合同。为这些旧调用补不安全默认值或接受缺三铁证回包会放宽 fail-closed，本轮按“零发布与真实证据优先”拒绝这样改绿。
- 旧五文件原样复跑：`111 failed / 24 passed / 0 skipped in 65.31s`，与第三次验收输入一致；主要失败仍是旧批量范围/批准/执行与组合器合同，不把它们解释为 E2 通过。当前状态继续为 `REOPEN E2`。
- 最终集中回归：E2 value/Reader/snapshot/frontend 合同 `75 passed in 35.32s`；文档 SelfTest 实际输出两项 `RED_EXPECTED` 后 `MVP_DOCS_OK`，exit 0；`git diff --check` exit 0（仅既有 LF→CRLF warning）。
- 保护哈希与身份：分支 `fix/dxm-two-stage-runtime-truth`、HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；Gold SHA256=`648E004FBF600AE4620435ADD3C8324D473710EC283ACDA139BCF337FE8EAE1C`，根原型 SHA256=`29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`，均与冻结值一致。
- 最终工作树事实：`610` 条状态记录（tracked=`79`、其中既有 deleted=`52`、untracked=`531`），未恢复 52 个删除、未清理既有未跟踪文件、未提交/推送。`plan_contract.py=628` 行、`plan_template_contract.py=303` 行；受审阅 E2 文件中用户账号/密码字面量命中均为 0，E2 plan/Reader/UI 的 `/start`、`/publish`、`runner_released=true`、`publish_allowed=true` 正向模式命中 0。
- 最终前端复核：聚合 `npm run build` 中 Node `12/12`、Browser `6/6 in 221.05s` 均实际完成；因浏览器阶段长时间无输出，本执行者误把它判断为清理卡住并终止了随后刚开始的 typecheck，所以不把该次聚合命令记为 exit 0。随后原样补跑 `npm run typecheck` 与 `npx vite build` 均 exit 0，Vite `56 modules transformed`、产物 `index-DfpWeZYY.css` / `index-Mfm65qVn.js`；本轮没有为此修改测试或产品代码。

## `REOPEN E2`（2026-07-30 · 第二次独立验收不通过）

- **当前裁定：E2 继续打开，禁止进入 E3；不宣称 E2 完成、`MVP_READY` 或 `PROD_READY`。**
- 最新 P0：真实模板同一属性多值被误判为 `DXM_TEMPLATE_VALUE_CONFLICT`，`originalBox="1"` 被拒；真实 edit 当前值中的无 ID 自定义属性与 JSON 字符串 SKU 无法进入快照。
- 最新 P1：重复当前属性会被覆盖；同一 snapshot 的新幂等键未被绑定或拒绝；LATIN 字符启发式会把法语、西语和乱码误判为英文。
- 最新 P1：`check_box`、`hasSubAttr`、`childAttributeList` 尚未由生产 Reader 形成真实条件/依赖 Schema；`fixed_values` 尚未进入字段解析优先级。
- 最新 UI 缺口：枚举未优先采用 `names.zh`，`ui_binding=reviewed:${fieldKey}` 未经 Schema 证明，普货模板库与铺货方案分层不足。
- 最新测试缺口：三类目矩阵仍是合成的 100/200/300；没有指定 `201273776 / 2621 / 201898401` 的完整只读链，也没有当次全量后端 L0 绿证据。
- **事实更正：下方首次返修记录中“完整当前值、条件/依赖/子属性、英文校验、原子幂等、三类目矩阵已修”的结论均被本次真实 wire-format 复验推翻，只保留为历史过程证据，不再作为当前完成声明。**
- 返修顺序：脱敏 raw-wire 模板红→绿 → edit 当前值红→绿 → 幂等键绑定 → 真实子属性/fixed values/英文 fail-closed → UI binding/分层 → 指定三类目与全量 L0。
- 安全边界：原始 `DXM-TX/data/**`、Cookie、真实业务样例仍禁止读取；只依据验收已披露的字段形态制作脱敏夹具。不得启动 Runner、保存、发布或进入 E3。
- 模板 raw-wire P0 已红→绿：公开只读链把 `originalBox` 改为真实字符串 `"1"` 后先报 `DXM_TEMPLATE_RESPONSE_INVALID`，现严格兼容 `"0"/"1"`；同一属性两个值先稳定复现 `DXM_TEMPLATE_VALUE_CONFLICT`，现按原序去重聚合且产品模块的普通字段冲突仍 fail-closed。脱敏 50 条属性模板达到 `50/50` 可解析；组合定向结果 `8 passed in 1.50s`。
- edit 当前值 P0 已红→绿：公开预览先以 JSON 字符串 `aeopAeProductSKUs` 复现 409，现严格解码且非数组拒绝；再以无 `attrNameId` 自定义属性复现 `DXM_PLAN_IDENTITY_INVALID`，现保留为不可冒充 Schema 映射的 `__unmapped_custom_attributes__` 审计列表。同 ID 多值按原序去重聚合，完整 `current_value_snapshot` 纳入逐商品快照/hash；公开链+ID 规范化定向 `2 passed in 2.03s`。
- 幂等键 P1 已红→绿：同一 snapshot 用新键先返回旧记录但未登记，随后该键冻结另一 snapshot 错误返回 201；现新增持久化键→snapshot 绑定表并迁移旧主键，任何成功别名键都在同一事务内绑定，跨 hash 复用返回 `PLAN_SNAPSHOT_IDEMPOTENCY_CONFLICT`。别名、原子回滚和主冻结链组合 `3 passed in 6.89s`。
- 真实 Schema/fixed values/英文 P1 已红→绿：`attributeShowTypeValue=check_box` 现冻结为 array；`hasSubAttr + childAttributeList` 形成子字段与 `dependentRequired`，声明有子属性但缺少可冻结定义即 fail-closed。`fixed_values.field_values` 按类目隔离并以 current→模板→fixed→fill 的顺序参与解析，公开快照证明 `source=fixed_value`。法语、西语、Latin 占位词、混合脚本和无可读元音乱码均改为 `UNKNOWN`，新依赖为 0；组合定向 `7 passed in 4.15s`。
- UI Schema P1 已红→绿：生产 Reader 为 editor/attribute 字段签发 `dxm_editor:*` / `dxm_attribute:*` binding；后端冻结时逐字段比对，前端缺 binding 直接阻断，不再生成 `reviewed:${fieldKey}`。枚举优先显示 `names.zh`，checkbox 数组使用多选控件；“普货模板库”与“铺货方案（本地）”标签显式分层。源码合同 `1 passed`、typecheck exit 0、真实 Chromium 组件链 `1 passed in 12.92s`，浏览器断言中文选项与提交 binding。
- 指定三类目与模块 P2：自动化只读矩阵已改用 `201273776 / 2621 / 201898401`，逐商品 Schema/mapping/hash 隔离和第三类目当前值证明 `1 passed`。方案 CRUD/快照编排与本地方案规范化/字段 binding 已拆分，`plan_contract.py` 从 1090 降至 918 行；拆分后同一 E2+Reader+前端合同仍为 `61 passed in 12.59s`。
- 当次全量证据：后端完整 L0 实际 `509 failed / 1372 passed / 0 skipped in 677.34s`，因此 **E2 仍不得关闭**；失败跨历史 claim_only/single_save、登录流、Runner 和旧文档门禁。原指定五文件仍精确为 `111 failed / 24 passed / 0 skipped in 42.55s`，未比本轮开工基线恶化。
- 前端完整门禁：`npm run build` exit 0，内部 Node `12/12`、Chromium `6/6`、typecheck 通过，Vite `56 modules transformed`，生成 `index-V7tVc0u4.js` 与 `index-DXiJNzav.css`。
- 文档/保护门禁：SelfTest 实际输出两条 `RED_EXPECTED` 后 `MVP_DOCS_OK`；`git diff --check` exit 0（仅既有 LF→CRLF warning）。Gold=`648E004FBF600AE4620435ADD3C8324D473710EC283ACDA139BCF337FE8EAE1C`、根原型=`29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`。
- 当前收口：工作树 607 条（tracked 79、既有删除 52、untracked 528），HEAD 仍为 `fd0da945…`；相对独立验收的 605 条新增两个拆分模块 `english_policy.py` / `plan_template_contract.py`，未恢复删除、未提交/推送、未读取 `data/**`、未启动 Runner/保存/发布。E2 保持 `REOPEN`，等待真实账号指定三类目的零写只读证据与全量 L0 裁决。

## `REOPEN E2`（2026-07-30 · 独立验收不通过）

- **当前裁定：E2 重新打开，禁止进入 E3；不宣称 E2 完成、`MVP_READY` 或 `PROD_READY`。**
- 验收基准：分支 `fix/dxm-two-stage-runtime-truth`、HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；因 E1/E2 尚无独立提交，按当前工作树对照 Gold §5.4/§7 与 MVP 合同 §4/§7.3。
- P0：真实 wire format 的 `productPropertys`、`values`、`units` 为 JSON 字符串，当前 Reader 只接受数组；必填字段未配置映射仍可预览/冻结。
- P1：旧 `BATCH_CATEGORY_SCOPE_UNVERIFIABLE` 门禁被删除；英文判断为字符启发式；快照缺少 fixed values、完整当前值及会话/账号/批准上下文；运营 UI 仍要求手写 JSON。
- P2：冻结快照与任务创建非原子且无幂等键；E2 浏览器测试、三类目矩阵和模块边界不足。
- 返修顺序：恢复旧安全门禁 → 原始 wire format 红→绿 → 必填映射差集/依赖/完整当前值 → 完整上下文+原子幂等冻结 → 中文结构化 UI → 三类目与浏览器验收。
- 安全边界：仍禁止真实保存、发布、Path B、Runner 释放和第三套 runner；未获 E2 复验通过前不得推进 Epic。
- 已恢复旧安全门禁：`bundle options`、`freeze_template_bundle` 与数据库模板写入隔离重新拒绝类目绑定旧批量编辑包，reason=`BATCH_CATEGORY_SCOPE_UNVERIFIABLE`。三项分别先红，恢复后组合为 `3 passed in 4.54s`；未接触 E2 的只读 categoryId 快照路径。
- 真实 wire format：生产 Reader 现直接接受数组或数组形式 JSON 字符串的 `productPropertys`、`attributeList.values`、`attributeList.units`，不要求测试先预归一化；属性名/值 ID 的 int/string 统一为规范字符串。三轮分别以字符串解析、类目数组解析、ID 类型漂移判红，同一生产端点现为 `1 passed in 3.03s`。
- 必填映射差集：新增公开预览回归，删除 Schema 必填 `material` 的整个映射后先复现 `200` 假成功；现按 `required − mapped_fields` 计算差集并返回 `PLAN_REQUIRED_FIELD_MAPPING_MISSING`，同一用例 `1 passed in 2.94s`。
- 英文校验：新增西里尔文/阿拉伯文各混入一个 `a` 的公开预览反例，旧逻辑均返回 200；现按 Unicode 字符名称严格要求所有字母属于 LATIN script，数字、空白、标点/符号可保留且至少两个拉丁字母，混合脚本与既有中文反例组合 `3 passed in 2.91s`。
- 快照 fixed values：公开预览断言先因缺少 `fixed_values` 判红；现把本地方案的完整 `fixed_values` 深拷贝纳入 snapshot/hash，原冻结与任务链路用例恢复为 `1 passed in 1.85s`。
- 商品完整当前值：新增生产只读白名单 `GET /api/smtProduct/edit.json?id=…`，冻结前逐个重读当次 3–100 件草稿并复核浏览器/账号、店铺、商品、类目与 draft 状态；公开链路先证明非标题 `material` 被错误取自模板，现冻结为 `source=current`。生产 endpoint/allowlist `2 passed in 0.90s`，完整快照链路 `1 passed in 1.40s`；无 edit Reader 或范围不完整即 fail-closed。
- 快照上下文：公开接口先因缺少 `session_context` 判红；现把当次 Reader `session_ref`、不可逆 `account_ref_hash`、店铺作用域和明确未批准的 `approval_context(state=not_granted, runner_released=false, publish_allowed=false)` 纳入 snapshot/hash 与任务副本，定向链路 `1 passed in 1.09s`。
- 原子幂等冻结：公开 API 先因 `idempotency_key` 被拒绝且任务仍需第二次创建判红；现 `POST /api/plan-snapshots` 在单个 `BEGIN IMMEDIATE` 事务内插入 snapshot、`batch_draft_save` draft task 与 jobs，并把稳定幂等键唯一绑定，重试返回同一 snapshot/task。旧 `/tasks` 子端点只读回原子任务；强制 task INSERT 失败时 snapshot/task 均为 0，主链路+回滚证据 `2 passed in 2.20s`。
- 条件/依赖/子属性：Schema 现冻结并校验受限 `allOf if/then.required`、`dependentRequired` 及 object/array 子属性；所有潜在必填先做映射差集，实际条件按逐品解析值固化 `active/required_when`，嵌套 required 递归 fail-closed。条件映射和子属性分别先出现错误 reason/200 假绿，修复后与字段依赖组合 `3 passed in 2.19s`。
- 中文结构化方案 UI：源码门禁先因缺少 `category_schemas` 且仍含两块 JSON textarea 判红；只读同步现返回当次真实类目 Schema，界面按类目/字段展示中文映射、必填/英文标记、枚举/布尔/数字/嵌套对象控件，数组明确只沿用当前值/模板，不再允许手写 JSON。前端 E2 合同 `2 passed in 0.24s`，`npm run typecheck` exit 0。
- E2 浏览器组件链路：新增 Vite + Chromium 挂载验收，真实渲染后确认 0 个 textarea、Schema 中文字段控件可形成结构化 `fill_rules/field_mappings`；“预览→冻结”回包直接取原子 `task_id`，请求含稳定幂等键且没有 POST 旧 `/tasks` 子端点。首次定位误把 input value 当文本导致 1 例失败，修正为 DOM value 定位后 `2 passed, 4 deselected in 10.06s`。
- 三类目矩阵：新增 3 件商品分别属于 100/200/300 三个类目的默认矩阵；逐品冻结不同 Schema hash、映射 hash 和解析结果，第三类目 `voltage` 取自自己的 edit 当前值且不混入第一类目 `material`，定向 `1 passed in 1.82s`。
- 模块边界：把 snapshot/task/jobs 原子持久化抽到 `plan_snapshot_store.py`，把类目 Schema/条件依赖/嵌套值校验抽到 `plan_schema_contract.py`；`plan_contract.py` 从返修中峰值 1403 行降到 1053 行，保留方案 CRUD/编排/hash，不改 API/Runner。拆分后 E2+Reader+前端合同 `54 passed in 11.08s`。
- edit 当前属性 ID：补充 `aeopAeProductPropertys` 的 int/string 漂移反例，先复现 `attrValueId=7301` 被保留为 number；现规范为稳定字符串 `"7301"`，定向红→绿 `1 passed in 1.02s`。
- 前端标准 build：`npm run build` exit 0；Node `12/12`、Chromium `6/6`、TypeScript 通过，Vite `56 modules transformed`，生成 `dist/assets/index-Nil8DBvR.js` 与 `index-DXiJNzav.css`。无 skipped/todo。
- 后端 E2/Reader 最终专项：`test_e2_plan_snapshot_api.py + test_dxm_draft_reader.py + test_frontend_e2_plan_contract.py` 在模块拆分后共 `54 passed in 11.08s`，0 failed/0 skipped。
- 旧五文件红基线：原命令收集/执行 135 项，结果 `111 failed, 24 passed in 83.14s`，0 skipped；比任务 0 的 `114 failed / 18 passed` 不差，但比本轮验收输入的 `86 failed / 46 passed` 更红。主要原因是按验收要求恢复 `BATCH_CATEGORY_SCOPE_UNVERIFIABLE` 后，旧真实编辑/组合包 happy-path 再次被安全拒绝；未放宽门禁或改旧测试，本项继续作为进入 E3 前红基线。
- 文档防回退：`validate-mvp-docs.ps1 -SelfTest` exit 0，实际输出两项 `RED_EXPECTED`（删除 PublishGuard、注入悬空链接）后 `MVP_DOCS_OK`；Gold/原型锁定仍由校验器通过。
- 完整性复核：Gold SHA256=`648E004F…EAE1C`、根原型 SHA256=`29B76F8F…4A847`，与冻结值一致；`git diff --check` exit 0（仅现有 LF→CRLF 提示）。
- 返修结论：自动化规格缺口已修并形成红→绿证据，但状态仍为 **`REOPEN E2` / 待独立复验**；本轮没有使用真实账号重跑 3 件商品 `edit.json` 当前值链路，也没有启动 Runner、保存或发布，禁止进入 E3。

## E1 正式验收关闭（2026-07-29 · 独立验收）

- **裁定：`E1_ACCEPTED` = 是 · E1 正式关闭。**
- 验收方：用户授权的独立复核（非 Codex 自证）；对照合同 `docs/product/MVP-竖切-草稿箱批量只保存.md` §7.2 / §9.1。
- 自动化（当次复跑）：前端 typecheck exit 0；Node 行为测试 12 passed；文档 SelfTest → `MVP_DOCS_OK`；隔离 `DXM_DATA_DIR` 下 CSS/导航合同 + browser 8 passed；Reader 单测 28 passed。先前 P1（860 断点误断言 `width: 64px`）已修为 `display: none`。
- 实机只读（当次存活会话，不输出业务明文）：`GET /api/dxm/draft-reader/shops` → 200，`source=api`，`session_bound=true`，店铺数 2；`products` 分页 total=116、页内均为 `dxm_state=draft`；snake_case `page_no=2&page_size=20` 返回第 2 页。前端 5173 可达。
- 人工链路（Codex 实机记录 + 本轮 API 复核采信）：真实可见登录成功 → 真实 shopMap/pageList → 多选 ≥3 草稿 + 本地只读验证方案 →「确认任务输入（不启动）」→ 零保存/零发布。
- **明确不宣称**：`MVP_READY`、`PROD_READY`、批量只保存放行、Path B。
- **下一入口：E2**（`local_plan_template` / `dxm_template_ref` / 不可变 `plan_snapshot`）；禁止启动 `batch_draft_save` 写路径。E2 前注意 BLOCKED 中「方案组合器 `source_digest` 漂移」。
- E0 保持已关闭；本记录不替代历史 E0/E1 过程段，仅作当前裁决入口。

---

# E0 执行进度
- 目标：仅冻结「草稿箱批量只保存」MVP 主合同、4 个指针与防回退校验；完成 E0 即停。
- 顺序：任务 0 基线 → DXM-TX/Gold/根原型只读取真 → 主合同 → 指针 → 校验器红→绿 → 范围/哈希验收。
- 最大风险：旧 `claim_only`/`single_save` 叙事回流、假证据冒充真实批量成功、越过零发布边界。
- 任务 0：D: 权威检出身份与 56 tracked/52 deleted/483 untracked 基线吻合；C: 会话目录差异见 BLOCKED。
- P0 红基线：typecheck 1 个 TS18048；5 文件 pytest 收集期 2 errors（`repository` ↔ `batch_edit` 循环导入）。
- 环境：`start-mvp --check`=0；8000 端口仍被 php 占用，PID 漂移见 BLOCKED；未启动服务。
- 真相读取：已完整读取 DXM-TX 导航列出的 8 份当前文档、PROGRESS/BLOCKED 与 1699 行根原型；未进入 `data/**`。
- PASSIVE_ONLY 审计：4 份 GPT 大文档仅保留“被动观察、候选不得升级为重放”的边界；不导入调用法或 STRUCTURAL_CANDIDATE。
- 原型裁决：继承 7 导航、240/56 布局、主题/断点/HVD 四键；拒绝 Path B、mock、真实样例与 localStorage 数据源。
- 哈希基线：Gold=`648E004F…EAE1C`；根原型=`29B76F8F…4A847`，均吻合。
- 主合同：已起草并冻结 Path A、读接口+UI写、双模型/不可变快照、`batch_draft_save`、三铁证、UNKNOWN、HVD 四键及 E0–E4 DoD。
- 主合同边界：Path B 仅“后续阶段/运行拒绝”；明确 `MVP_READY ≠ PROD_READY`，当前不宣称任何 READY。
- 指针：Gold/AGENTS/CLAUDE/docs 索引 4/4 已指向现已存在的主合同；三份现有指针无需追加改写，用户预置差异原样保留。
- 校验器：已实现文件/章节/术语/链接/AI 标注/旧叙事/锁定哈希检查；SelfTest 只在内存删 `PublishGuard`。
- 红→绿：正式同命令第 1 轮因 PS5.1 UTF-8 BOM 解析失败，第 2 轮因 READY 措辞误报失败；均只修校验器，第 3 轮输出 `RED_EXPECTED` + `MVP_DOCS_OK`，exit 0。
- 范围预检：相对任务 0 基线 tracked/deleted 增量 0/0、untracked 增量 4，正好是本轮 4 个新白名单文件；`app/**` 状态为空，52 个既有删除未恢复。
- diff 门禁：首轮发现 AGENTS 既有指针差异中 4 处行尾双空格；仅去空格后 `git diff --check` exit 0，文字/语义不变。
- 安全扫描：本轮 4 个新文件的 secret/token/password/cookie 赋值形态命中 0；Gold/原型复哈希吻合。
- DXM-TX：非 `data/**` 2597 文件聚合 SHA256 开工/收尾同为 `7227E40F…F2BD`；该目录零改动。

## E0 复验修正（2026-07-29）

- 验收状态：**复验通过，仅 E0 正式关闭**；下述 2026-07-28 初验结论仍只作历史记录，本节是当前结论。
- 独立裁定：2026-07-29 用户提供的独立复核再次实跑校验器、7 份受管文档链接、Gold/根原型哈希、`git diff --check` 与 `app/**` 范围，明确结论为 **E0 验收通过、正式关闭**；`MVP_READY` / `PROD_READY` 均为否，仅允许另立授权后进入 E1。
- 已复现假绿：当前 `validate-mvp-docs.ps1 -SelfTest` 输出 `RED_EXPECTED` + `MVP_DOCS_OK` 且 exit 0，但独立逐链接审计检出 `docs/README.md` 共 10 个本地悬空链接。
- 悬空范围：原索引第 20–25、29–32 行，均指向 52 个既有删除中的旧文档；不恢复这些删除，需把索引改为非指针历史说明并让校验器覆盖全部受管文档链接。
- 已补语言合同：明确中文界面、`ui_label_zh → field_key → category_schema_path → UI binding` 中文字段映射，以及自动写入自然语言必须英文并在保存前完成非空/Schema/语言/精确读回校验；中文、混合语言或 `UNKNOWN` 均不得点击「保存」。
- 已补逐商品快照：`item_snapshots[]` 一一绑定商品、店铺、`categoryId`、规范化类目 Schema/SHA256、中文字段映射、必填字段和完整解析结果；顶层 hash 覆盖全部嵌套内容，多类目不得借值，执行/恢复不得临时重算。
- 已清理索引假指针：10 个既有删除目标保留为反引号历史路径，不恢复文件、不再伪装为可解析链接；独立逐链接审计现为 `BROKEN_LINKS=0`。
- 已加固校验器：链接检查覆盖合同、Gold、AGENTS、CLAUDE、docs 索引、PROGRESS、BLOCKED 共 7 份受管文档；`-SelfTest` 既删除 `PublishGuard`，也向索引内存注入悬空链接。
- 红→绿第 1 轮通过：两条 `RED_EXPECTED`（坏合同、坏索引）后输出 `MVP_DOCS_OK: contract=1 pointers=4 link_docs=7 links=resolved ai_notice=3 legacy_conflicts=0 hashes=locked`，exit 0。
- 最终门禁：`git diff --check`=0、未跟踪交付文件尾随空格=0、独立 `BROKEN_LINKS=0`、秘密赋值形态命中=0、校验器 UTF-8 BOM=True。
- 身份/范围：分支 `fix/dxm-two-stage-runtime-truth`、HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；tracked/deleted/untracked=`56/52/487`，相对任务 0 基线增量 `0/0/+4`；`app/**` 状态为空。
- 保护复核：Gold=`648E004F…EAE1C`、根原型=`29B76F8F…4A847`；DXM-TX 非 `data/**` 2597 文件聚合=`7227E40F…F2BD`，unchanged=True。
- 关闭边界：三项 E0 修正已通过；未进入 E1、未改业务代码、未恢复 52 个既有删除、未宣称 `MVP_READY` 或 `PROD_READY`。
- 保护事实：分支/HEAD、Gold SHA256、根原型 SHA256 当前仍与 E0 基线一致；未进入 E1，未改 `app/**` 或 DXM-TX。

## 2026-07-28 E0 初验结论（已被复验重开）

- **初验时曾判仅 E0 完成，现已撤回该关闭结论**：1 份主合同、Gold/AGENTS/CLAUDE/docs 4 个有效指针、1 个防回退校验器；未改业务代码。
- 验收事实：SelfTest 真实红→绿（`RED_EXPECTED` → `MVP_DOCS_OK`）、`git diff --check`=0、锁定哈希不变、`app/**` 与 DXM-TX 零改动。
- 当前 P0 红基线保持：前端 1 个 TS18048；5 文件 pytest 收集期 2 errors（循环导入）；本轮未修、未恶化。
- E1 建议入口：先清零上述 P0，再实现只读 shopMap + `pageList(draft)` + 真实 draft 多选；不得越过到 E2–E4。
- 就绪声明：**不宣称 `MVP_READY`，不宣称 `PROD_READY`**；人工验收和 E1–E4 均未执行。
- 待裁决：仅 BLOCKED.md 中的 C:/D: 会话目录差异与 8000 端口 php PID 漂移，均不阻塞 E0。
- 当前：等待 2026-07-29 三项复验修正完成，禁止沿用本节初验结果关闭 E0。

## E1 开发进度（2026-07-29）

- 当前结论：E1 开发纵切已实现，**尚未做真实登录会话人工验收，因此 E1 未正式验收关闭**；不宣称 `MVP_READY` 或 `PROD_READY`。
- 权威检出：继续只写 `D:\Desktop\py\dxm-auto-uikit`；分支 `fix/dxm-two-stage-runtime-truth`、HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；C: 非 Git 镜像保持只读。
- P0 TypeScript：复现 `WorkbenchModules.tsx:2226` 的 TS18048 后，以提前归一化 `visibleMissingFields` 修复；`npm run typecheck` 从 exit 1 转为 exit 0。
- P0 循环导入：确认 `repository → batch_edit.execution_state → batch_edit.__init__ → coordinator → repository`；仅把 `coordinator.py` 的 `Repository` 类型导入移入 `TYPE_CHECKING`，导入探针输出 `IMPORT_ORDER_OK`。
- P0 收集门禁：任务指定 5 文件已从收集期 2 errors 推进到 `132 tests collected`；全量运行暴露既有 E2/E3 红基线 `114 failed, 18 passed`，E1 收尾复跑仍为 `114 failed, 18 passed`，未变差且未越界修旧批次实现。
- 后端 Reader：新增仅允许当前真实可见会话读取的 `userInfo.shopMap` 与 `smtProduct/pageList` 边界；固定 `dxmState=draft`、表单键和两个 URL，不导航、不另开浏览器、不导出 Cookie、不提供 mock/fallback。
- 失败关闭：校验 HTTP/JSON/code/data/`shopMap`、店铺与商品稳定 ID、店铺绑定、`dxmState`、分页闭合、同页去重冲突及同一浏览器会话；会话变化丢弃回包。
- 会话跨页保护：API 仅返回原始会话 ID 的不可逆 16 位 `session_ref`；前端检测到会话变化即清空跨页选择，原始 `browser_session_id` 不透传。
- 前端 E1：新增真实店铺/全部店筛选、加载/刷新/错误/空态、20 条分页、跨页多选、当前页全选、至少 3 件门禁、本地 `edit_batch_bundle` 方案选择和 `{shopId, productIds, planId}` 可复核任务输入；确认按钮明确“不启动”。
- 原型体验：主导航更新为 7 项；使用 240px rail、56px topbar、`#4f46e5`、16px 圆角、明暗主题及 1100/860 断点；未复制原型店铺/商品/模板样例或 localStorage 数据源。
- E1 红→绿：后端 Reader/前端源码合同 `24 passed`（含浏览器 owner 线程调度与显式双接口白名单）；前端纯选择状态 `5 passed`；`npm run typecheck` exit 0；`npm run build` 完成 54 modules transform。
- 最终环境检查：`start-mvp --check` exit 0、5173 可用，但 8000 再次被外部 Laravel `php.exe` PID `36316` 占用；未终止进程，真实会话人工验收受阻，见 BLOCKED。
- 保护门禁：文档 SelfTest 输出两条 `RED_EXPECTED` 与 `MVP_DOCS_OK`；`git diff --check`、Python compileall 均 exit 0；Gold 与根原型 SHA256 仍分别为 `648E004F…EAE1C`、`29B76F8F…4A847`。
- 旧 Adapter 事实：`test_dxm_adapter.py` 单独保留既有 `26 failed, 42 passed`，失败集中于冻结身份及旧 claim/single_save 断言；本轮新增两个只读 adapter 方法对应测试通过，不修改旧叙事测试。
- 零发布边界：本轮没有启动浏览器、没有调用店小秘、没有读取 `data/**`/Cookie/抓包/真实业务样例、没有真实写入；没有实现 E2 plan snapshot、E3 runner 或 E4 三铁证/HVD。
- 提交边界：未提交、未推送；“单独提交 E0”和“修改 Gold 陈旧指针/哈希”都只是建议，未获得明确授权，见 BLOCKED。
- 最终范围：tracked/deleted/untracked=`65/52/493`；相对 E1 开工 `56/52/487` 为 `+9/0/+6`，对应 9 个受控既有源码文件与 6 个 E1 新源码/测试文件；52 个既有删除未恢复。

## E1 复验缺陷修正（2026-07-29）

- 当前结论：验收指出的 P1/P2 已完成代码与本地自动化修正；**E1 仍未关闭，不进入 E2**，真实登录只读验收继续列在 BLOCKED。
- Reader 成功码反向验证：新增 `{code: false}`、`{code: 0.0}` 用例先得到 `2 failed, 21 passed`；改为严格只接受 `type(code) is int and code == 0` 或精确字符串 `"0"` 后，Reader/前端接线合计 `27 passed`。
- 会话生命周期：确认输入改为 `{sessionRef, input:{shopId, productIds, planId}}`；Reader 失败、页面重挂载、手动刷新或浏览器会话变化均使旧选择与父级确认输入失效。
- 会话漂移：商品回包必须与当前店铺读回的 `session_ref` 一致；不一致即拒绝该回包，清空旧 `shopMap`/商品/选择/确认值，再重新读取店铺，禁止新商品与旧店铺映射组合。
- 来源错误态：公开响应守卫会实际拒绝 `fallback`/`mock`；失败标签固定为“真实 Reader 读取失败 · 状态已失效”，确认按钮在未取得同会话商品回包时禁用。
- 前端行为红→绿：新增 API 尚不存在时测试入口 exit 1；实现后标准 `npm run test` 为 `11 passed, 0 failed, 0 skipped`，覆盖来源拒绝、会话漂移、三类状态失效、来源标签与会话绑定输入。
- 标准门禁：`package.json` 新增标准 `test`，`build` 串联 `test → typecheck → vite build`；最终 `npm run build` exit 0，11 项行为测试、TypeScript 和 54 modules 构建全部通过。
- 导航合同：七项名称改为“工作台、连接店小秘、采集箱选品、铺货方案、开始批量保存、保存结果、设置”；短标签始终存在于 DOM。
- 680px 历史视觉验证（已被 §8.1 再次复验覆盖）：当时第二轮截图仍显示 64px rail 与短标签；该状态后来被裁定违反“≤860px 隐藏 rail”，不得作为当前验收依据。
- 视觉证据：`output/playwright/e1-680-nav-fixed-v2.png`、`output/playwright/e1-680-draft-reader-failed-v2.png`；本地 Playwright 会话已关闭，4173 预览已停止。
- 旧红基线：原指定 5 文件仍为 `114 failed, 18 passed`，与修正前完全一致；未改 E2/E3 业务合同、未降低断言或跳过测试。
- 文档/保护门禁：SelfTest 输出两条 `RED_EXPECTED` 与 `MVP_DOCS_OK`；`git diff --check`=0；Gold=`648E004F…EAE1C`，受保护 DXM-TX 根原型=`29B76F8F…4A847`。
- 环境：`start-mvp --check` exit 0，5173 可用；8000 当前由外部 `php` PID `30792` 占用，未终止或接管。
- 最终范围：tracked/deleted/untracked=`66/52/495`；相对本次复验修正前 `65/52/493` 为 `+1/0/+2`，新增状态项仅是已纳入门禁的 `app/frontend/package.json` 修改和两张最终视觉证据；既有 52 个删除及其余未跟踪文件未恢复、未清理。
- 零发布边界：没有连接真实店小秘、没有读取 Cookie/抓包/真实业务样例、没有真实写入、没有实现 E2；不宣称 `MVP_READY` / `PROD_READY`。

## E1 端口阻塞解除（2026-07-29）

- 用户明确授权关闭当前占用 8000 的任意进程并将该端口用于 DXM。
- 终止前只读复核输出 `LISTENER_COUNT=0`，当时已无监听者；因此没有执行无目标或伪造的 `Stop-Process`。
- 官方 `scripts\start-mvp.bat --check` exit 0，实际输出 8000、5173 均 available；服务未启动。
- 结论：8000 环境阻塞已解除；E1 仍等待真实登录只读人工验收，不因端口可用自动宣称 E1、`MVP_READY` 或 `PROD_READY`。

## E1 再次复验缺陷修正（2026-07-29）

- 当前结论：本轮复验指出的账号绑定、运行时错误、跨页身份冲突、860px 布局、错误路由和浏览器测试均已完成代码与自动化修正；**真实账号只读链路仍未验收，因此不标记 `E1_ACCEPTED`，不进入 E2**。
- 运行时根因：`continue_login()` 在保留可见 Sync Playwright 的同一 owner 线程内又调用 `live_client.probe_session()`，会启动第二套 Sync Playwright，并以 `Sync API inside the asyncio loop` 的误导性错误失败；旧测试还把该错误后的页面外观当成成功。
- 登录真相修正：`continue_login()` 不再启动第二套 headless probe；成功必须由当前可见 BrowserContext 对 allowlist `userInfo` 的严格成功回包和稳定账号字段共同证明。适配器 probe 异常不再回退磁盘旧“已登录”状态，而是 `login_failed` fail-closed。
- 账号级证明：Reader 源 envelope 新增仅在进程内使用的 `account_ref`；它是稳定账号字段的不可逆 SHA256 摘要。公开 `session_ref` 现在同时绑定 Browser/Context 代次和 `account_ref`；店铺读与分页读账号不一致返回 `AUTH_ACCOUNT_MISMATCH`。
- 确认前重验：点击“确认任务输入（不启动）”先重新读取当前账号级 session proof；账号、Browser/Context 或 Reader 变化会清空商品、选择和父级确认输入，不允许缓存 `session_ref` 单独放行。
- 跨页身份冲突：新增严格商品合并器；相同 ID 的 `shop_id`、`category_id`、`subject` 或 `dxm_state` 任一变化即 `DraftProductIdentityConflictError`，已选范围和确认输入立即失效，禁止静默覆盖。
- 原型布局：`<=860px` 的 `.sidebar` computed style 改为 `display:none`，工作区从 x=0 占满 680px；不再保留 64px rail。
- 安全路由：七项导航中的“开始批量保存”不再进入旧 ExecutionConsole/“浏览器诊断”；现在只显示 E1 后续阶段占位与“不会启动保存或发布”，没有执行按钮。旧诊断内部 section 未扩张为 E1 执行入口。
- 浏览器级门禁：新增真实挂载 `DraftSelectionPage`/`AppShell` 的 Playwright 测试，不 mock 被测组件；外部 Reader 边界由路由 fixture 提供。三轮结果依次为 `2 failed, 1 passed`、`1 failed, 2 passed`、`3 passed`，修正闪退错误态后再加入跨页冲突场景，最终 `4 passed`。
- 标准门禁：`package.json` 的 `build` 现串联 `test → test:browser → typecheck → vite build`；最终输出为 Node 状态测试 `12 passed`、浏览器测试 `4 passed`、TypeScript exit 0、Vite `55 modules transformed`。
- 后端定向回归：账号/登录/Reader/浏览器接线合计 `37 passed in 12.07s`；其中缺少稳定账号字段必须 `AUTH_ACCOUNT_UNPROVEN`，账号变化会产生不同证明。
- 旧批次红基线：原指定 5 文件仍为 `114 failed, 18 passed in 55.37s`，与两次修正前完全一致；没有修改 E2/E3 旧批次实现、判卷阈值或跳过策略。
- 实机复验：用户授权使用 8000 后启动官方 `scripts\start-mvp.bat`，backend PID `9156`、8000/5173 健康并输出 `STARTED_OK`；`POST /api/dxm/login/continue` 不再出现 Sync API 错误，而是打开可见浏览器并诚实返回 `login_failed`。
- 实机阻塞：当前没有完成登录的可复用会话；`GET /api/dxm/draft-reader/shops` 返回 409 `BROWSER_SESSION_UNAVAILABLE`。没有读取持久化凭据、`data/sessions` 或 Cookie，也没有取得真实 shopMap/pageList；详见 BLOCKED。
- 运行收尾：为释放测试租约，仅停止本轮启动的确切 DXM backend PID `9156`；8000 随后为 free。按专用 `dxm_workflow` profile 复核浏览器进程为 0，没有留下失控浏览器、没有终止不相关进程、没有保存或发布。
- 最终标准构建：`npm run build` exit 0；Node `12 passed`、Playwright `4 passed`、TypeScript 通过、Vite `55 modules transformed`。
- 最终文档/差异门禁：SelfTest 输出两条 `RED_EXPECTED` 后输出 `MVP_DOCS_OK`，exit 0；`git diff --check`=0；11 个本轮相关未跟踪交付文件尾随空格=0。
- 保护哈希：Gold=`648E004FBF600AE4620435ADD3C8324D473710EC283ACDA139BCF337FE8EAE1C`；根原型=`29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`，均与冻结值一致。
- 最终身份/状态：分支 `fix/dxm-two-stage-runtime-truth`、HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；tracked/deleted/untracked=`68/52/507`，既有 52 个删除未恢复、未清理任何既有未跟踪文件；8000/5173 listener 均为 0。
- 未跟踪边界：本轮只审阅列明的 E1 源码/测试与 PROGRESS/BLOCKED；运行时产生或既有的 `data/**` 继续排除在读取、差异审阅和交付之外，不提交其中任何内容。
- 就绪边界：只证明上述规格缺陷的本地修正与 Sync API 运行时错误消失；**不宣称 E1 正式验收，不宣称 `MVP_READY` / `PROD_READY`**。

## E1 CSS 合同复验修正（2026-07-29）

- 验收结论保持：**E1 不通过、不关闭，不进入 E2 或任何 READY**；本节只关闭待清单中的 P1“CSS 合同测试与 `display:none` 不一致”。
- 精确复现：`tests/test_frontend_draft_selection_contract.py` 为 `1 failed, 3 passed`，唯一失败是全局要求 `width: 64px;`，把桌面手动折叠 rail 与 §8.1 的移动断点错误合并。
- 测试修正：合同测试现在截取最后一个 `@media (max-width: 860px)` override，要求 app shell 单列、`.sidebar { display: none; }`，并明确该移动块内不得出现 `width: 64px;`；桌面折叠 rail 行为不变。
- 红→绿：同一合同文件复跑为 `4 passed in 0.18s`；与 Reader、登录 fail-closed、浏览器验收组合复跑为 `38 passed in 22.78s`。
- 浏览器证据：标准 `test:browser` 仍为 `4 passed`，其中 680px 读取真实 computed style=`display:none`、workspace x=0 且宽度=680。
- 标准构建：`npm run build` exit 0；Node `12 passed`、Playwright `4 passed`、TypeScript 通过、Vite `55 modules transformed`。
- 未处理项：真实账号登录 + shopMap/pageList 人工链路仍为 P0；commit 和 Gold 指针修改仍需另行授权；旧批次 5 文件的 `114 failed / 18 passed` 按合同不在 E1 修复范围。

## E1 真实登录人工链路进行中（2026-07-29）

- 用户已明确要求开始真实登录与真实 shopMap/pageList 人工链路。
- 官方 `scripts\start-mvp.bat` 已输出 backend/frontend 健康及 `STARTED_OK`；backend PID=`25180`，8000/5173 当前由本轮 DXM 服务使用。
- Playwright 可见会话 `dxm-real-login` 已打开 `http://127.0.0.1:5173`，进入“账号与浏览器 → 登录真实店小秘”。
- 当前人工门禁：账号、密码字段为空，因此产品按设计禁用“打开真实登录页”；等待用户仅在本机可见窗口输入凭据、完成验证码/账号选择并点击检测登录状态。
- 安全边界：未从聊天、命令或文件读取/回显账号密码，未读取 Cookie、`data/sessions` 或 raw 抓包；尚未调用 shopMap/pageList，未保存、未发布。

## E1 真实登录与 Reader 人工链路完成（2026-07-29）

- 用户现场裁决：真实可见浏览器稳定进入 HTTPS `www.dianxiaomi.com/web/home`，页面正文非空且不是“欢迎登录”页，即证明页面登录成功；账号级身份绑定继续由随后 `userInfo` Reader 和确认前重验负责，二者不得混为同一门禁。
- 登录假失败红→绿：新增公共 Adapter 合同测试后先得到 `1 failed, 437 deselected`，证明旧实现缺少 `business_page_ready` / `loading_absent`；生产检查补齐三项事实后，真实首页、显式登录页、空白首页及新版首页合计 `4 passed, 434 deselected`。
- 启动真相：官方启动器现在显式设置 `DXM_WORKFLOW_ACTION_RUNTIME=browser_agent`、持久 profile 目录及 `DXM_WORKFLOW_PERSISTENT_PROFILE=1`；对应启动器回归测试已红→绿。服务重启后 backend/frontend 健康，当前 8000/5173 由本轮 DXM 服务使用。
- 账号证明兼容：现场只审计 `userInfo` 字段名与类型，不输出值；稳定身份白名单补入当前真实 Schema 的 `id`、`puid`、`account`，缺字段与账号变化仍分别以 `AUTH_ACCOUNT_UNPROVEN` / `AUTH_ACCOUNT_MISMATCH` 失败关闭。
- 登录实机回包：`ok=true`、`stage=login_success`、URL=`https://www.dianxiaomi.com/web/home`、`visible_logged_in=true`；`session_authenticated`、`business_page_ready`、`loading_absent` 全为 true，`failure_code=null`。
- 真实 Reader：shopMap 回包 `source=api`、`session_bound=true`、`session_ref` 长度 16、真实店铺数 2；pageList 固定 `draft`，第 1 页 `100/116`、共 2 页、`has_next=true`、`deduplicated_count=0`。未输出店铺、商品、账号或 Cookie 内容。
- 本地方案前置：现有 257 条旧模板在 8 个必需分区均无有效候选；通过既有本地模板 API 新建 8 个明确标注 `E1_READONLY_VALIDATION_DO_NOT_EXECUTE` 的无发布指令源模板和 1 个启用的 `edit_batch_bundle`。所有 DXM 引用项均为空且 `required=false`，没有伪造真实店小秘引用。
- 方案接口事实：第一次组合请求携带前端当前的 `source_digest` 被请求模型以 8 个 `extra_forbidden` 拒绝，未生成 bundle；按当前后端正式模型只提交 `template_id` 后得到 `ready_sections=8`、`bundle_type=edit_batch_bundle`、`bundle_enabled=true`。该前后端漂移已写入 BLOCKED，不在 E1 内扩张修改旧批次合同。
- 人工任务输入：本地控制页重新加载真实 Reader，页面存在 20 条当前页草稿；选中 3 件并选择上述本地方案后，确认按钮可用。点击唯一的“确认任务输入（不启动）”并通过账号级重验，页面实际显示“任务输入已形成；本步骤没有启动保存、发布或任何真实写入。”及“任务输入已确认”。
- 零写入界面证据：确认后的当前页面精确名称为“保存”与“发布”的按钮数量均为 0；本轮没有调用店小秘保存/发布接口，没有进入 E2 runner，也没有宣称任何三铁证或 READY。
- 定向回归：登录、Reader、账号证明和启动器合计 `42 passed in 1.77s`；前端标准构建为 Node `12 passed / 0 failed / 0 skipped / 0 todo`、Playwright `4 passed`、TypeScript 通过、Vite `55 modules transformed`。
- 冻结旧红基线：原指定 5 文件仍为 `114 failed, 18 passed in 46.01s`，与 E1 开工后两次复验完全一致；未通过 skip/todo、放宽断言或修改旧批次实现来掩盖。
- 文档与保护门禁：SelfTest 实际输出两条 `RED_EXPECTED` 后输出 `MVP_DOCS_OK`；`git diff --check` exit 0。Gold=`648E004FBF600AE4620435ADD3C8324D473710EC283ACDA139BCF337FE8EAE1C`、根原型=`29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`，均保持冻结值。
- 最终工作树身份：分支 `fix/dxm-two-stage-runtime-truth`、HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；tracked/deleted/untracked=`70/52/517`，既有 52 个删除未恢复。受审阅本轮文件的硬编码秘密赋值形态命中 0。
- 运行交接：官方 launcher、8000 backend、5173 frontend、真实 DXM 可见浏览器及本地 `dxm-real-login` 验收页保持运行，便于用户现场查看；没有提交、推送或把 `data/**` 纳入交付。
- 当前结论：真实登录、真实 shopMap/pageList、至少 3 件选择与只读任务输入形成均已有实际证据；E1 已具备再次独立验收条件，但本执行者不代替外部裁定标记 `E1_ACCEPTED`，不进入 E2，不宣称 `MVP_READY` / `PROD_READY`。

## E2 开工（2026-07-29）

- 外部裁定：用户确认 E1 已由独立验收正式关闭，状态为 `E1_ACCEPTED`；本节覆盖上节“等待再次独立验收”的历史结论，当前唯一 Epic 切换为 E2。
- E2 目标：按合同 §4 / §7.3 分离 `local_plan_template` 与 `dxm_template_ref`，并在任何启动动作前生成不可变 `plan_snapshot`，完整冻结逐商品 `item_snapshots[]`。
- 顺序：修复 `source_digest` 前后端漂移 → 双模型 schema/API/UI → 快照预览/冻结 → 多类目、Schema/hash、字段映射、解析结果与英文校验 → 版本不可变回归。
- 最大风险：为追求现有红测快速变绿而删除摘要字段、混淆本地方案与 DXM 引用、从另一类目借配置，或把 E2 快照接口误接到真实 `batch_draft_save` 写路径。
- 硬边界：仅本地模板/只读引用/快照数据；不触发真实保存、不实现 Path B、不新增第三套 runner、不宣称 `MVP_READY` / `PROD_READY`。
- 开工身份：`D:\Desktop\py\dxm-auto-uikit`，分支 `fix/dxm-two-stage-runtime-truth`，HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；tracked/deleted/untracked=`70/52/517`，既有 52 个删除原样保留。
- 红基线：E2/E3 共用的指定 5 文件当前为 `114 failed / 18 passed`；E2 只关闭 §7.3 对应失败，不通过 skip/todo、放宽断言或修改 E3 runner 来缩短红线。
- `source_digest` 红→绿：先修正测试夹具中 3 类不可执行 DXM 名称引用的错误必填状态，并恢复类目绑定组合入口；随后公开 API 用例精确判红为候选缺少 `source_digest`。现已由候选接口返回 SHA256、前端随选择提交，后端在同一事务重读源模板并严格比对，漂移返回 `TEMPLATE_SOURCE_DIGEST_DRIFT` 且不建包。
- 本项验证：隔离 `DXM_DATA_DIR` 后运行组合成功与事务漂移反向测试，结果 `2 passed in 4.62s`；未使用真实店小秘、未调用保存/发布、未进入 batch runner。
- 模型与快照红→绿：新增公开 E2 合同测试先以 3 个 `404` 判红；现已分离 `local_plan_template` 与只读 `dxm_template_ref` 的存储/API，方案内容不可原地修改、只能创建新版本，DXM 引用只允许只读同步且按来源摘要/店铺/类目校验。
- `plan_snapshot`：预览与冻结均生成 `dxm_batch_draft_save_plan.v1`，逐件冻结 `categoryId`、规范化 Schema/hash、中文字段映射/hash、必填字段及解析结果；跨两个类目的 3 件商品分别解析，不借用另一类目配置。顶层 `snapshot_hash` 覆盖完整嵌套快照。
- fail-closed 覆盖：Schema/hash 漂移、店铺/类目作用域冲突、引用漂移、未解析必填和自然语言非英文均返回明确 409 reason code；冻结快照生成的 `batch_draft_save` 任务保留完整副本，后续方案新版本不改变既有任务。
- 本项验证：`tests/test_e2_plan_snapshot_api.py -q` 结果 `3 passed in 2.83s`；任务保持 `draft`，现有启动门禁拒绝未发布的 `batch_draft_save` mode，没有派发 runner 或真实写路径。
- 中文 UI：主导航「铺货方案」现进入 E2 视图，明确分栏展示可版本化 `local_plan_template` 与只读 `dxm_template_ref`；方案编辑器固定 Path A、零发布、英文自然语言和 UNKNOWN 停批，并按类目录入补差规则/中文字段映射，不使用 localStorage 或 mock 数据源。
- 启动前复核页：保留当次 Reader 的逐商品 `productId/shopId/categoryId`，按类目接收真实只读 Schema，支持预览、显示 hash、冻结为 draft 任务；页面没有 `/start` 调用，明确 E2 不执行保存/发布。
- UI 反向复跑曾发现全店 `shopId=-1` 选择被过早拒绝和“尚未开放执行”文案回归，已保留每件商品真实 shopId 并把单店限制留在 E2 冻结门禁，同时恢复原安全文案。最终生产构建包含 Node `12 passed`、浏览器 `4 passed`、TypeScript 通过、Vite `56 modules transformed`。
- E2 前后端专项合并：`tests/test_e2_plan_snapshot_api.py tests/test_frontend_e2_plan_contract.py -q` 为 `5 passed in 7.54s`。
- 真实类目 Schema 补齐：以生产只读 Reader 契约新增固定编辑器字段 `aeopAeProductSKUs`、重量/尺寸、价格/币种及运费/服务/尺码模板引用；字段均有中文标签、类型和非自然语言标记，动态类目属性继续来自 `attributeList`。红测先因缺少 `grossWeight` 得到 `1 failed`，修正后同一生产端点测试 `1 passed in 1.27s`。
- 模板表单值归一化：生产 Reader 对重量/尺寸/价格的严格数字字符串、`originalBox` 严格布尔值、SKU JSON 数组和正整数模板 ID 做可无损归一化，避免 Schema 类型与 DXM 表单编码漂移；含糊值统一 `DXM_TEMPLATE_RESPONSE_INVALID`。正向用例先因字符串未转换判红，修正后正向 + 4 个反例为 `5 passed, 31 deselected in 4.74s`。
- E2 收尾组合：隔离 `DXM_DATA_DIR` 下 E2/前端/Reader 初次为 `40 passed in 4.12s`；加入模板表单值 4 个反例后的最终复跑为 `44 passed in 6.80s`。连同旧模板组合兼容的最终复跑为 `78 passed in 27.15s`。
- 标准前端门禁：`npm run build` exit 0；Node `12 passed / 0 skipped / 0 todo`、Playwright `4 passed`、TypeScript 通过、Vite `56 modules transformed`。
- 冻结五文件旧基线：本轮为 `86 failed / 46 passed in 59.55s`，相对 E2 开工 `114 failed / 18 passed` 有改善且与 E2 中期复跑一致；剩余失败属于未授权 E3/旧批次合同，本轮不修改。

## 登录事实与 Reader 证明解耦修正（2026-07-29）

- 用户裁决：真实可见浏览器稳定进入 HTTPS `www.dianxiaomi.com/web/home`，页面正文非空且不是显式登录页，即已证明页面登录成功；shopMap Reader 可用性不是登录成功的前置条件。
- 精确红测：把 `read_draft_shops()` 设置为一旦调用即记录失败，旧 `continue_login()` 仍调用 Reader，结果 `1 failed, 437 deselected`。
- 根因：`continue_login()` 在页面登录事实成立后强制读取 shopMap/account_ref，Reader 暂不可用会把 `login_success` 错改为 `login_failed`，混淆了两个独立状态。
- 修正：`continue_login()` 只根据受限 HTTPS DXM 首页与可读业务页事实返回 `login_success`，不再调用 shopMap Reader 或 Cookie probe；账号级证明保留在 Reader 读取、会话绑定和确认任务输入前重验。
- 回归：登录继续/首页判定/Adapter 后置条件组合为 `5 passed, 433 deselected`；Reader 未被调用、`account_ref` 不伪装进登录状态，真实浏览器仍保留。
- 账号安全组合复跑：登录、Adapter、Reader 中 `continue_login` / 首页检测 / account_ref / account mismatch 相关用例为 `10 passed, 528 deselected in 6.05s`。
- 安全边界：未放宽 Reader 的 `AUTH_ACCOUNT_UNPROVEN` / `AUTH_ACCOUNT_MISMATCH`；本修正没有调用真实店小秘接口、没有保存或发布，也不改变 E2 的零写入边界。

## E2 完成结论（2026-07-29）

- **历史结论已被 2026-07-30 独立验收撤销；当前以置顶 `REOPEN E2` 为准。**
- **裁定：仅 E2 工程实现与本地门禁完成；到此停止，不进入 E3。** E0/E1 既有裁定不变；不宣称 `MVP_READY` 或 `PROD_READY`。
- 已交付：可版本化且可归档的 `local_plan_template`、真实会话只读同步的 `dxm_template_ref`、服务端权威重读与预览 hash 锁定的不可变 `plan_snapshot/item_snapshots[]`，以及只读中文 UI。
- 快照真相：逐商品冻结店铺、商品、类目、Schema/hash、中文字段映射、必填字段、解析来源/值/hash；解析优先级固定为当前商品 → DXM 模板引用 → 本地补差，不跨类目借值，方案新版本不改变既有任务。
- 信任边界：客户端不得提交模板 records、Schema 或 current values；登录首页事实与 Reader 账号证明已解耦，Reader/冻结仍绑定当前真实会话和账号并在前后重验。
- 最终后端门禁：E2/前端/Reader `44 passed in 6.80s`；模板兼容组合 `78 passed in 27.15s`；登录与账号安全定向 `10 passed, 528 deselected in 6.05s`。
- 最终前端门禁：`npm run build` exit 0；Node `12 passed`、Playwright `4 passed`、TypeScript 通过、Vite `56 modules transformed`。
- 冻结旧红基线：指定五文件为 `86 failed / 46 passed in 59.55s`，优于 E2 开工 `114 failed / 18 passed`；未修改剩余 E3 runner 红项。
- 文档门禁：SelfTest 实际输出两条 `RED_EXPECTED` 后输出 `MVP_DOCS_OK`，exit 0；`git diff --check` exit 0。
- 保护事实：Gold SHA256=`648E004FBF600AE4620435ADD3C8324D473710EC283ACDA139BCF337FE8EAE1C`；根原型 SHA256=`29B76F8F2ACC6DDA15393AB20B4D0C07A10739B94A4E8E11A8341AD0DEC4A847`。
- 安全扫描：用户凭据字面量命中 0、硬编码秘密赋值命中 0、E2 `/start`/调度路径命中 0；发布相关命中均为 `publish_allowed=false`、拒绝器或“不会发布”文案。
- 工作树事实：分支 `fix/dxm-two-stage-runtime-truth`、HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`；tracked/deleted/untracked=`78/52/522`，既有 52 个删除未恢复，未清理既有未跟踪文件。
- 真实操作计数：E2 开发与门禁调用真实店小秘写接口 0、保存 0、发布 0、runner 启动 0；DXM-TX 保持只读，未读 `data/**`、Cookie 或 raw 抓包。
- E3 建议入口：另立授权后只实现 `batch_draft_save` 一次批准、开始/暂停/继续/停止与 UNKNOWN 停批；必须继续保留 E2 冻结快照和零发布边界，本轮不执行。
