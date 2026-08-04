> 由 OpenAI GPT（Codex）AI 生成/维护。

# 待裁决清单（BLOCKED）

## 置顶差异：8000 端口占用 PID 已漂移

- 发现时间：2026-07-28 16:22（Asia/Shanghai）。
- `scripts\start-mvp.bat --check` 返回码仍为 `0`，仍判断 8000 端口被 `php` 占用，但实测 PID 为 `38752`，不是任务基线中的 `2756`。
- 当前处置：不启动服务、不终止或接管该进程；把端口占用视作 E1 前环境门禁，本轮仅继续不依赖服务启动的 E0 文档工作。
- 待裁决：E1 启动前确认 PID `38752` 是否为预期服务，并释放或改用正确端口；本项不阻塞 E0。
- 2026-07-29 E1 复核：`scripts\start-mvp.bat --check` 当前显示 8000 与 5173 均可用并返回 0；未终止任何进程。本项当前已解除，不再阻塞 E1 开发。
- 2026-07-29 10:16 最终复核：状态再次漂移；`--check` 返回 0，但 8000 当前由 `php.exe` PID `36316` 监听，命令行为 `php.exe -S 127.0.0.1:8000 ...D:\Desktop\laravel\apps\api\...\server.php`，不是 DXM backend；5173 可用。
- 2026-07-29 11:11 E1 缺陷修正复核：`--check` 仍返回 0，8000 占用 PID 已漂移为 `30792`（`php`），5173 可用；本轮没有终止、接管或探测该外部服务的业务数据。
- 2026-07-29 11:23 用户明确授权关闭当前占用 8000 的任意进程并将该端口交给 DXM；执行前只读复核为 `LISTENER_COUNT=0`，当时已无监听者，因此没有进程被终止。
- 2026-07-29 11:24 官方 `scripts\start-mvp.bat --check` 输出 `Backend port 8000 is available`、`Frontend port 5173 is available`，exit 0；**8000 端口占用阻塞当前已解除**。
- 当前处置：不终止、不接管外部 Laravel 服务。该项不阻塞已完成的静态开发/测试，**阻塞 DXM backend 在默认 8000 端口启动及真实会话人工验收**。
- 当前处置（覆盖上一条历史状态）：8000/5173 均可用；服务尚未启动，端口不再阻塞 DXM backend 或后续真实会话人工验收。
- 待裁决：真实验收前由外部释放 8000，或明确授权 DXM 使用另一端口并同步启动配置。
- 待裁决（已解除）：无需再裁决端口释放；若端口在启动前再次被占用，本轮用户已授权关闭该占用者。

## 置顶差异：会话工作目录不是目标 Git 检出

- 发现时间：2026-07-28。
- 任务提供的会话工作目录为 `C:\Users\wz\Desktop\py\dxm-auto-uikit`；在该目录原样运行 `git status --porcelain=v1 -uall`、`git branch --show-current`、`git rev-parse HEAD`，三者均返回 `fatal: not a git repository (or any of the parent directories): .git`。
- 只读核对发现，`D:\Desktop\py\dxm-auto-uikit` 才是满足任务给定身份的检出：分支 `fix/dxm-two-stage-runtime-truth`，HEAD `fd0da9457e18b2db77bc0c3356f3f63213ce54a8`，且 Gold 文件存在。
- 当前处置：依据任务中对 `D:\Desktop\py\DXM-TX`、Gold 文件及既有基线的明确引用，并结合目标 Git 身份完全吻合，后续命令与白名单写入均限定在 `D:\Desktop\py\dxm-auto-uikit`。C: 镜像保持只读且不写。
- 待裁决：会话默认工作目录是否应在后续任务中修正到 D: 权威检出；本项不阻塞 E0 文档合同工作。
- 2026-07-29 E1 处置：继续在 D: 权威检出开发并复核分支/HEAD；C: 保持只读。本项不阻塞当前交付，但默认工作目录仍待外部修正。

## 其他待裁决

### E2 待裁决

- **状态：`REOPEN E2`，独立验收不通过；禁止进入 E3。**
- **G0 关闭口径：已裁定策略 B**（2026-08-03 用户）。完整 L0 绿或可审计簇关闭为硬门槛；计划见 `docs/product/L0-策略B-迁移计划.md`。
- **G1 Git 固定点：已授权 commit（不自动 push）**（2026-08-03 用户）。`E2-CLOSE-CANDIDATE` 以 `PROGRESS` 置顶回填的 SHA 为准。
- **G4 真实零写/fixture 待授权：**当前仍禁止登录、读取 `DXM-TX/data/**`、raw/Cookie/真实业务样例；无法自行补齐另两指定类目、非空 child 回包或真实脱敏固定 fixture。需要单独授权合规只读范围与脱敏落盘目录，或由人工提供脱敏 JSON。
- **G5-1 Gold 指针待授权：**Gold 文件及其冻结 SHA256 仍只读；不得自行修复其悬空链接或更新校验器期望哈希。
- **G3 旧独立批准测试簇待 G0 裁决：**`test_batch_edit_api.py` 当前剩余 22 个失败全部来自历史 `/manual-approval` 成功/漂移/单次令牌测试；生产端点现统一 409 `BATCH_APPROVAL_REQUIRES_ATOMIC_START`，防止批准令牌与启动分离。为这些旧测重开端点会越过 E2 并削弱原子批准边界；若选择策略 B，需另行裁决将其迁入 E3 的 `approve-and-start`/内部安全合同，或以获批的可接受剩余失败表登记，不能由本执行者擅自改成成功。
- **批准簇等价覆盖复核：**底层 `authorize_batch_start` 已有绑定/过期/replay 合同测，但当前没有 `/approve-and-start` API 等价测试；旧 22 项还独立覆盖 runtime/session/DOM/order 漂移、数据库冻结事实、CAS 和 token 不泄露。统一改断言为 409 会实质删掉安全覆盖，直接迁到 `/approve-and-start` 会调度 Runner 并进入 E3，因此本轮不存在无需裁决的安全迁移路径。
- **2026-08-03 第五次复验：**真实 raw 解析比例已由独立验收确认关闭，但真实 `2621` 被错误的 `productPrice` 与 SKU min/max 关系拒绝；两条正常英文标题仍为 `UNKNOWN`。完整 L0、Git 可复现固定点、另两类目真实只读链、非空 child 与脱敏固定 fixture 仍阻断 E2。
- 真实证据授权边界未变化：本执行者仍不得读取 `DXM-TX/data/**`、raw、Cookie 或真实业务样例，也不得登录、保存或发布；因此只能按第五轮披露的价格关系与标题制作脱敏公开回归，不能自行抓取另两类目或非空 child。
- 第五轮可执行修复已关闭：错误的 `productPrice` 区间关系已从冻结 Schema/校验/UI 删除，真实披露形态 preview 转绿且 cargo 超价仍拒绝；两条英文标题逐条红→绿；DOM `id=abcde` 假身份已双层拒绝；版本统一为 `0.1.1`。最终集中后端 `86 passed`、桌面 `89/89`、标准前端 Node `12/12` + Browser `6/6` + typecheck + Vite 全绿。
- **仍阻断 E2 关闭：**完整 L0 最近完整证据仍为 `509 failed / 1392 passed`；本轮只关闭其中已披露的 DOM 身份红点，未重跑 45 分钟全套，不能推断当前失败总数或宣称清零。其余历史 acquisition/action evidence/v1 Runner 合同不得靠旧 `claim_only/single_save` 默认值放宽。
- **仍阻断可复现固定点：**当前核心 E2 源码仍在未跟踪工作树；原始任务禁止未另行授权的 commit/push，本轮不擅自建立 Git commit。Gold 第 43 行同样受只读冻结哈希约束。
- **仍阻断真实三类目/child/fixture：**`201273776` 与 `201898401` 缺真实 edit/schema，现有 13 个 child raw 均为空；获取非空回包和沉淀真实脱敏 fixture 需要解除 `DXM-TX/data/**`/真实只读抓取禁令并提供合规脱敏授权。
- **2026-07-30 第四次复验覆盖第三次“模板/英文/模块已关闭”结论：**真实属性模板与 `2621` edit 仍能击穿生产解析，标准 `npm run build` 当次整体 exit 1；下方旧绿仅保留为过程证据。
- 当前 P0：有内容但无 ID 的模板属性必须保存为不可执行审计项而非阻断整份模板；template checkbox、SKU 库存数字字符串、分号图片串必须按冻结 Schema 严格归一化并保留错误关闭。
- 第四次返修已关闭模板侧 P0：有名称/值但无 ID 的属性现保存为不可执行审计项并持久化/hash；template checkbox singleton 由对应冻结 Schema 数组化。仍需独立验收用允许读取的真实 50 条/`2621` 2 条数据确认全量比例，本执行者受 raw 禁读边界不能自证该数字。
- 第四次返修已关闭披露的 edit 类型 P0：模板和商品当前值共用 Schema-aware normalization，`ipmSkuStock` 严格数字串转 integer，分号图片串按明确 wire format 转 URL array，歧义值保持失败关闭。仍需独立验收用获准的真实 `2621` raw 证明实际字段冲突为 0。
- 当前 P1：目标类目常见正常英文标题仍被误拒；价格/售价/货值关系未冻结；SKU 子字段中文标签不完整。
- 第四次返修已关闭已披露英文反例：三条目标类目正常标题已由正式预览接受，原非英文/伪词仍 fail-closed。当前仍是无新增依赖的保守词汇门禁，不宣称可替代通用语言模型；未知领域词会继续 `UNKNOWN`。
- 第四次返修已关闭价格/SKU 展示 P1：价格关系已冻结并进入 snapshot resolution hash，违规关系 fail-closed；SKU 与嵌套属性字段已补中文标签，前端显示中文与只读价格规则。
- 当前 Standards：完整 L0=`509 failed / 1386 passed`；标准 build 当次 Browser=`1 failed / 5 passed`、整体 exit 1。单测或直接 Vite 绿不得覆盖。
- 第四次返修本地复跑事实：标准 `npm run build` 已取得一次完整 exit 0（Node `12/12`、Browser `6/6`、typecheck、Vite 均绿），关闭本次环境稳定性缺口；完整后端 L0 为 `509 failed / 1392 passed / 0 skipped in 2742.15s`，failed 未增加但仍远未清零。旧 acquisition/action evidence/v1 Runner 合同的 509 项修复超出本轮 E2 且不能靠降低 fail-closed 要求处理，继续阻断 E2 关闭。
- 2026-08-03 架构 P2 已在不改变外部合同的前提下收束：已解析模板引用集隐藏持久化私有字段并集中冲突/类目隔离/冻结摘要；本地方案版本目录集中 SQL/lineage/归档；快照编译集中 session/scope/Schema/解析/英文/必填/价格/hash。`E2PlanService` 从约 628 行降为 163 行 façade，集中回归 `83 passed`。该项不再作为 E2 阻断；剩余阻断仍是完整 L0 红、Gold 只读悬空链接和真实 raw/三类目零写证据。
- Gold 悬空指针待裁决：`docs/product/CODEX-GOLD-工作指令-MVP批量只保存.md` 第 43 行仍引用已删除的 `docs/tech/当前运行时架构-20260717.md`；原始任务明确 Gold 只读且 SHA256 必须冻结，本轮不得修改。需外部另行授权修改 Gold 并同步哈希，或接受其为历史说明。
- 真实证据仍阻断：任务硬边界禁止本执行者读取 `DXM-TX/data/**`/raw/真实业务样例；本轮只能用验收披露形态做脱敏生产链回归，不能自证真实模板 50/50、`2621` 实际 raw 预览或三个指定类目的真实零写链。
- **2026-07-30 第三次复验覆盖旧完成项：**字段优先级、真实模板空 ID/`promiseTemplateId=0`、类目 `2621` checkbox 单值数组化三个 P0 均已完成公开红→绿；E2 仍被下列 P1、完整 L0 与真实零写证据阻断。
- 当前 P1：真实 `childAttributeList`、英文门禁双向误判、编辑 Schema 与中文固定值/规则入口均已完成公开红→绿；仍需处理模块重复/陈旧指针，并以完整 L0 与真实三类目零写证据裁决 E2。
- 当前 P2：`CLAUDE.md` 三个已删除文档指针、发布安全 helper 重复与 DXM 引用持久化已拆分关闭；仍缺三指定类目的真实零写链证据。
- 当前完整门禁仍为 `509 failed / 1372 passed / 0 skipped`，E2 专项绿不得覆盖；本轮将按失败簇逐项核对，不以放宽安全断言换绿。
- 第三次返修后完整 L0 再跑为 `509 failed / 1386 passed / 0 skipped`；失败数未下降，新增 14 个 passed 来自本轮测试。该门禁继续阻断 E2，不能以“非本轮回归”替代全绿要求。
- 完整 L0 的代表性失败无法在 E2 内安全兼容：旧 `login_flow` 测试绕过公开入口直接调用私有 `_save_only_on_page()`，未提供当前强制的目标身份、店铺、基线字段完整性和必需读回证明；旧 action-result 夹具缺少 `save_result/fresh_probe`，并仍有 `claim_only/single_save` 叙事。给这些调用加默认值、接受缺证据回包或恢复旧 mode 都会削弱零发布/三铁证/身份绑定，需另立旧 L0 合同迁移裁决，E2 本轮不做。
- 旧五文件当次复跑为 `111 failed / 24 passed / 0 skipped in 65.31s`，没有比第三次验收输入恶化，但仍是红门禁；不得用专项绿或“历史失败”标签替代通过。
- **2026-07-30 第二次复验覆盖旧结论：**真实 wire-format 再次击穿模板与 edit 当前值链；下方“已修，待复验”仅是旧一轮历史记录，不代表当前关闭。
- 当前 P0：模板同一属性多值误报冲突、`originalBox="0"/"1"` 不兼容；edit 无 ID 自定义属性和 JSON 字符串 SKU 不能形成快照。
- 当前 P1：重复属性聚合、幂等键绑定、真实子属性/条件 Schema、fixed values 解析优先级、真实英文判断、中文枚举、可验证 UI binding 与模板/方案分层尚未闭环。
- 当前测试门禁：指定类目 `201273776 / 2621 / 201898401` 只读矩阵和当次全量后端 L0 尚未完成；旧五文件仍为 `111 failed / 24 passed` 历史红基线。
- 原始抓包取证阻断：任务硬边界禁止读取 `DXM-TX/data/**`、raw 抓包或真实业务样例，因此本轮不会打开验收给出的 `edit.json` 路径；仅可根据验收已披露的 `productPropertys` 多值、`originalBox` 字符串、无 ID 自定义属性、SKU JSON 字符串及子属性字段制作脱敏 raw-wire 回归。若最终裁决强制要求逐字使用该真实文件，需另行解除该读取禁令；此项不阻塞先修生产解析器。
- 状态文档更正：`PROGRESS.md` 旧“完整当前值、条件/依赖/子属性已修”等表述已明确标成被第二次复验推翻的历史过程证据。
- 已关闭本轮模板 P0：脱敏 raw-wire 50 条属性模板全部解析，多值同属性聚合；产品模板 `originalBox="0"/"1"` 严格转换为布尔值。定向 `8 passed`，没有读取真实抓包。
- 已关闭本轮 edit 当前值 P0：SKU 字符串严格解码为数组；重复属性不覆盖；无 ID 自定义属性保留为独立审计列表，不参与已验证 Schema 字段解析；完整当前值进入 item snapshot/hash。定向公开链 `2 passed`，仍未读取真实 `data/**`。
- 已关闭本轮幂等 P1：成功返回的主键和别名键均持久绑定 snapshot；同键跨 hash 复用 409，绑定、task/jobs 与 snapshot 保持同事务。定向 `3 passed`。
- 已关闭本轮可执行 Schema/fixed values P1：真实 show-type、内嵌子属性和依赖进入冻结 Schema；缺 child 定义停止；类目隔离 fixed field values 进入解析优先级。英文门禁已从“LATIN 即 en”改为依赖零、保守 fail-closed 词汇/脚本门禁，已拒绝验收指出的法语、西语和乱码反例。
- 英文识别剩余边界：任务禁止新增依赖，当前实现不宣称通用语言模型；对无法以本地严格词汇证据证明的拉丁文本一律返回 `UNKNOWN` 并停批。若后续要求高召回的任意领域英文识别，需要另行批准经过固定版本/离线模型审计的语言检测依赖；本项不阻塞“不得把非英文当成功”的 E2 fail-closed 目标。
- 已关闭本轮 UI P1：中文枚举采用 `names.zh`；mapping binding 必须与生产 Schema 签发值完全一致；普货模板库/本地铺货方案在导航文案和模式标签上分层。Chromium 已验证中文选项及实际 POST body，不只是源码字符串。
- 已关闭本轮三类目/P2 自动化：指定 `201273776 / 2621 / 201898401` 已进入脱敏只读矩阵；`plan_contract.py` 降至 918 行且 61 项专项保持全绿。
- **仍阻塞 E2 关闭：**当次完整后端 L0 为 `509 failed / 1372 passed / 0 skipped`；不能用 61 项专项、12 项 Node 或 6 项 Browser 绿覆盖。旧五文件仍为 `111 failed / 24 passed`。这些历史链路不在本轮 E2 安全范围内，未通过放宽门禁或修改旧测试处理。
- **仍缺真实账号最终证据：**本轮遵守 `data/**`/raw/真实样例禁读，只完成脱敏 wire-format 与指定 ID 的自动化只读链；尚未在当前可见真实会话对三个指定类目完成 shopMap/pageList→edit/template/schema→preview/freeze 的零保存、零发布证据。未获得该证据前不得标记 `E2_ACCEPTED`。
- P0（已修，待最终复验）：生产 Reader 已用原始 JSON 字符串夹具覆盖 `productPropertys` 与 `attributeList.values/units`，并统一属性 ID 类型；生产端点定向 `1 passed in 3.03s`。
- P0（必填闭环已修，待最终复验）：Schema 直接 required、受限条件 required、`dependentRequired` 与嵌套 object/array 子属性均进入冻结校验；潜在必填缺映射与实际激活后缺值均 fail-closed，条件/依赖/子属性组合 `3 passed in 2.19s`。
- P1（已修，待最终复验）：旧批量入口的 `BATCH_CATEGORY_SCOPE_UNVERIFIABLE` 已在候选、冻结合同和数据库隔离三处恢复；定向组合 `3 passed in 4.54s`。
- P1（英文/fixed values/完整当前值/上下文/结构化 UI/浏览器链路已修，待最终复验）：结构化方案组件与“预览→原子冻结”已由真实 Chromium 挂载验证，`2 passed`；没有旧 `/tasks` POST，也没有 JSON textarea。
- P2（已修，待最终复验）：冻结/任务/jobs 单事务且稳定幂等；三类目逐品隔离；真实 Chromium 组件链路；原子持久化与 Schema 校验已分别抽离，`plan_contract.py` 降至 1053 行，集中回归 `54 passed`。不宣称因此进入 E3。
- 旧五文件基线仍红：本轮实际 `111 failed / 24 passed / 0 skipped`；优于任务 0 的 `114/18`，但低于验收输入的 `86/46`。恢复旧类目范围 fail-closed 门禁会让大量旧真实编辑 happy-path 被 409 拒绝；按“零发布与真实证据 > 旧测试通过”保留门禁，禁止为变绿放宽。该基线不否定 E2 专项 54 绿，但在 E3 前必须另行裁决/迁移旧合同测试。
- 真实会话最终证据未补：本轮只用审计给出的 wire shape 与合成原始 JSON 字符串/编辑回包复现修复，没有读取真实业务样例，也未在当前可见登录会话对 ≥3 个 draft 实跑 `pageList → edit.json → template/schema → preview → 原子冻结`。独立验收必须在零保存/零发布下补这条只读证据后再裁决 E2；当前不得标记 `E2_ACCEPTED`。
- 当前处置：按 PROGRESS 置顶顺序返修；本清单在每项红→绿后逐项关闭，E2 外部复验前保持阻塞。

### E1 真实登录人工验收（已关闭 · `E1_ACCEPTED`）

- **2026-07-29 独立验收裁定：`E1_ACCEPTED`，本项关闭，不再阻塞 E2 开工。** 详见 `PROGRESS.md` 置顶「E1 正式验收关闭」。
- 过程摘要：真实可见登录、shopMap/pageList(draft)、≥3 选品、确认任务输入（不启动）、零保存/零发布；CSS 合同与 860 断点 `display:none` 已对齐。
- 仍不宣称 `MVP_READY` / `PROD_READY`；E2 仅允许方案/快照范围，禁止 runner 真写。

### 前端方案组合器与当前后端请求模型漂移（已关闭）

- 发现时间：2026-07-29 15:17（Asia/Shanghai）。
- 当前事实：`BatchTemplateComposer.tsx` 为每个分区提交 `{template_id, source_digest}`，但当前后端请求模型禁止 `source_digest`，正式 POST 实测返回 8 个 `extra_forbidden`；仅提交当前模型接受的 `{template_id}` 后，本地 `edit_batch_bundle` 可成功生成。
- 安全影响：本次只为 E1 形成任务输入，使用明确标注 `E1_READONLY_VALIDATION_DO_NOT_EXECUTE` 的本地方案，没有保存、发布或进入 runner；不把该方案当成 E2 不可变 plan snapshot 或真实执行证据。
- 2026-07-29 E2 处置：后端请求模型已接受 `source_digest`，并在创建组合包的同一事务内重读源模板、严格比对摘要；源内容漂移返回 `TEMPLATE_SOURCE_DIGEST_DRIFT` 且不创建组合包。
- 红→绿证据：公开 API 缺少摘要先判红；组合成功与事务漂移反向测试最终 `2 passed in 4.62s`。
- 当前结论：本项已关闭，无需裁决；没有通过前端静默删字段或放松断言规避漂移。

### Gold 陈旧指针与 E0 独立提交未获授权

- Gold 仍引用已删除的 `docs/tech/当前运行时架构-20260717.md`；Gold SHA256 当前被校验器锁定。
- E0 合同/指针/校验器仍与大量既有删除共处未提交工作树；用户目标仅将“单独提交 E0”“修 Gold 并同步哈希”表述为建议。
- 当前处置：不提交、不推送、不修改 Gold 或期望哈希，避免把建议扩张成授权。
- 待裁决：如需执行上述两项，请另行明确授权及 Gold 新文本；本项不阻塞 E1 代码交付。
