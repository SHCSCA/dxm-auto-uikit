> 由 OpenAI GPT（Codex）AI 生成/维护。

# 待裁决清单（BLOCKED）

## 2026-08-19 分支整理后的仍存阻断

- **完整 L0 同源证据缺失：** 本轮只复验了 backend 审计/E4/模板/派发 `39 passed`、frontend `27 passed` + browser `9 passed` + typecheck、desktop `92 passed`；没有把完整 L0 重新绑定到本轮提交并取得 `0 failed / 0 skipped`，不得用专项绿替代。
- **portable 门禁未完成：** `outputs\desktop-build` 当前不存在；尚未取得目录包/免安装包、manifest、SHA256、隔离 user-data 重启读回和同 HEAD smoke 的同源证据。
- **真实业务验收未执行：** 本轮真实店小秘登录、浏览器操作、保存、发布均为 `0`；类目属性/运费/服务模板尚未为真实三商品配置并冻结，旧任务 `#191` 仍禁止启动或克隆。
- **交付身份：** 本次整理提交为 `ac08b78908d7b23038cffd2b204705fe2c12df44`；用户已授权分支整理、文档同步、提交和推送。生成的 `.agents/`、`.playwright-cli/`、`output/`、`artifacts/` 不进入提交。完成推送不等于 `E3_ACCEPTED`、`E4_ACCEPTED`、`MVP_READY` 或 `PROD_READY`。
- **远端推送：** 已尝试两次 `git push -u origin fix/dxm-two-stage-runtime-truth`，以及 `git ls-remote`；当前环境访问 GitHub 443 失败/连接重置，远端分支未确认更新，未创建 PR。

## 置顶状态（2026-08-14 · 桌面交付与日志规划后）

| 项 | 状态 | 说明 |
|----|------|------|
| E2 | `E2_DEFERRED` | 不挡 E3 canary 预热口径；完整三类目/fixture 等历史项仍见下文 |
| E3 工程 | 历史固定点 `E3_READY_FOR_CANARY`；当前 `E3_OPEN / BLOCKED` | 当前工作树、模板、portable 与统一审计未形成同源验收；**非** `E3_ACCEPTED` |
| E3 真写 canary | **滞后 / BLOCKED** | 分区模板未配齐 + 未口头授权；`#191` 禁启动 |
| E4 代码控制面 | **完成** | request + worker ack + 前端四键 + 单测 |
| E4 §7.5 DoD | **未关闭 / BLOCKED** | 缺真机暂停≥10s、继续不重做、停止不派发、HVD 同源核对 |
| 当前免安装桌面包 | **IN_PROGRESS** | 新 `0.1.4` portable 已加载控制台（SHA256=`C09388177...`）；官方 `-CheckPortable` / 真机登录未做 |
| 全链路操作审计 | **IN_PROGRESS** | A 合同与核心 API/时间线已接线；portable 双击仍待用户用新包验证 |
| 视觉对齐 v6 | **暂不改** | 用户确认；偏差已记录，不挡代码 |
| `MVP_READY` / `PROD_READY` | **禁止宣称** | 生产交付仍 `BLOCKED` |

## 免安装桌面与操作审计阻断（2026-08-14 · 新增）

- **产品入口阻断：** 正式用户必须使用免安装桌面 EXE；当前 backend/frontend/desktop 虽均为 `0.1.4`，但仓内没有 `outputs\desktop-build`，因此不能让用户按旧 `0.1.0` 路径或源码网页开始配置/真机验收。
- **验包阻断：** `scripts/verify-desktop-package.ps1` 仍固定读取 `DXM-Agent-Console-Portable-0.1.0.exe`；不改为 manifest 驱动就会错验、漏验当前包。
- **可追溯阻断：** 当前 `job_logs`/evidence/report/ledger/runtime log/AgentConsole/BrowserAgent 事件没有统一 correlation/causation 和持久化时间线；BrowserAgent 只保留最近 50 条，AgentConsole 事件主要驻内存。现在让用户完成一轮复杂配置后，不能保证逐步回放和精确归因。
- **安全阻断：** 统一日志必须先具备凭据/Cookie/token 永不落盘、诊断包脱敏、事件 hash-chain、点击前 write-ahead 和点击后断链转 `UNKNOWN`；缺任一项不得进入新的真实三商品保存。
- **交付阻断：** 当前工作树不是 clean 固定点，且存在大量既有改动/未跟踪文件/52 个删除。未获 commit 授权前可以开发和生成内部 canary 包，但不得标 source-package/release ready；不得恢复、暂存或覆盖无关历史改动来伪造 clean。
- **关闭条件：** 完成 [免安装桌面版与全链路操作日志任务书](docs/product/CODEX-GOAL-免安装桌面版与全链路操作日志-20260814.md) 的全量、反例、隔离 portable smoke 和同源产物清单；随后用户在新包内配齐真实类目分区模板并创建新 snapshot。真实保存仍需单独批准。
- **本轮未扩大授权：** 不启动/克隆 `#191`，不登录店小秘，不执行浏览器动作、保存或发布，不 commit/push。

## E4 DoD 仍阻断（2026-08-13 · 代码完成之后）

- **已关闭（代码，可复测单测，非真机）：**
  - 真实写入 pause/stop/resume 不再硬 409「until worker acknowledgements」。
  - 状态机：`running` → `pause_requested` → `paused` → resume → `running`；`stop_requested` → `stopped`。
  - Runner 安全点 ack；resume 跳过已完成 job；停止后剩余 pending 不派发。
  - 前端四键绑定 `pause_requested` / `stop_requested` / `paused` / `stopped`（开始批量保存 + 当前保存任务）；列表/详情投影 `workerControl`。
- **仍阻断 E4 验收关闭（§7.5）：**
  1. 未在真实可见浏览器、真实 batch（建议 ≥3 draft）上证明：暂停 ≥10 秒后 worker ack、无下一写动作；继续后不重做已完成保存、不丢队列。
  2. 未证明停止后不再派发新商品；在途不确定 SAVE 归 `UNKNOWN` 的真机/强证据路径未做 E4 专项验收。
  3. HVD / 日志 / 结果 / API / 持久化在同一任务·快照·商品粒度的**真机**一致核对未做。
  4. 前置 E3 真写 canary 未过：模板未配齐时不得为做 E4 而放开保存。
- **不得宣称：** `E4_ACCEPTED`、`E4_DONE`（若指 DoD）、`MVP_READY`、`PROD_READY`。
- **视觉：** 与 `docs/research/dxm-console-v6.html` 的 rail 配色/图标、执行监控整页舞台等偏差**不处理**；MVP 7 导航与 240/56 以主合同为准。

## E3 分区模板 / 真实 Path A 滞后（2026-08-13 · 用户裁定，仍有效）

- **用户明确：** 分区模板配置与真实只保存试跑**本步滞后**；E4 控制面代码已先做完，**不等于** E3/E4 验收关闭。
- **E3 真写仍阻断：**
  1. 类目须配齐分区模板（至少属性 / 运费 / 服务；建议产品模板、变种、尺码表）。类目 `200083142` 冻结目前仅产品模板 `1138913` → 门禁 `PATH_A_SECTION_TEMPLATES_MISSING` 正确挡真写。
  2. 真机 Path A 完整「模板套用 → 保存 → 三铁证」尚未成功；单品 `130658340712223024` 仅证明可开编辑页与部分字段写入。
  3. 任务 `#191`（3 draft）**禁止** `approve-and-start`，保持 draft；未另选并口头授权前不真写。
  4. 发布 / 保存并发布 / Path B / `editFromSmt` 继续永久禁止。
- **生产交付：** 仍为 `BLOCKED`。E4/E3 单测或工程绿 ≠ 人工 §11 签字。

## E3 L0 无轮次限制续跑（2026-08-12 · 原三轮阻断已解除）

- **当前无未解决的 E3 自动化工程红项；状态提升为 `E3_READY_FOR_CANARY`。**固定代码提交 `717ae3c5618ced19467d528e41aac784e896c810` 的 clean backend=`2168 passed / 0 failed / 0 skipped`，frontend/desktop/docs/diff/status/端口门禁均绿。剩余阻断仅是外部真实三商品 canary 尚未获得本轮明确授权、尚未执行；因此不得标 `E3_ACCEPTED`、`MVP_READY` 或 `PROD_READY`，生产交付仍为 `BLOCKED`。
- **待后续授权的唯一执行项：**从工作台 UI 使用同一可见会话完成真实登录 → shops/products 至少 3 件 draft → preview/freeze → 串行 `batch_draft_save`，逐件复核回包、页面成功态与独立未发布三铁证；任何 `UNKNOWN` 必须停批。发布、保存并发布、移入待发布继续禁止。
- 第二固定点 clean backend 已取得 `2168 passed / 0 failed / 0 skipped`；当前新阻断仅为 clean checkout 下 Gold 被全局 `core.autocrlf=true` 转成 CRLF，导致物理 SHA 假漂移。Gold 内容和校验器均不改，正以单文件 `.gitattributes eol=lf` 固定跨 worktree 字节真相；在新 fixed commit 的 docs/frontend/desktop/backend 全门禁重新通过前仍保持 `E3_OPEN / BLOCKED`。
- 本地固定提交已建立，但首次独立 clean worktree 完整 L0 为 `6 failed / 2162 passed / 0 skipped`，因此当前仍不能标 `E3_READY_FOR_CANARY`。失败不是 E3 写链生产反例，而是候选漏收 README/启动配置且 4 个测试错误依赖未提交历史文件删除；正在以“不恢复、不暂存 52 个删除”的最小合同修正后重新 clean 复验。
- 完整后端 L0 已取得 `2168 passed / 0 failed / 0 skipped`；后端事实门禁不再阻断。当前只剩客户端、文档、范围/秘密/哈希、固定提交与干净 worktree 复验。
- login-flow 已完成整文件复验：`461 passed / 0 failed / 0 skipped`；原 29 项及 1 个 skip 均已关闭。完整后端、客户端、文档、范围/秘密/哈希也已全绿；当前仅剩本地固定提交与干净 worktree 复验门禁。
- 中间基线曾从 `29 failed / 431 passed / 1 skipped` 收敛到 `11 failed / 450 passed / 0 skipped`；其中 required-default 7、variants 3、media 1 随后已全部关闭，不再是当前阻断。
- 原 `1 skipped` 已定位并通过生产 JavaScript 修复及 fixture 强化转为通过，不再是阻断；剩余失败继续按根因簇处理。
- 用户已明确取消测试轮次上限，因此“已满三轮、不得继续运行”不再是阻断；下面 29 项与未知 skipped 已重新进入执行队列。
- 仍然有效的阻断只有事实门禁：完整后端必须 `>=2000 passed / 0 failed / 0 skipped`，客户端/文档/diff/秘密扫描必须全绿，随后本地固定 commit 还必须在干净临时 worktree 复验通过。在此之前保持 `E3_OPEN`，禁止真实三商品保存验收。
- 当前没有待用户裁决的产品歧义；若诊断出现需要改变冻结 MVP、安全边界或写入授权的新选择，再置顶登记并继续不受影响项。

## E3 L0 清零续跑（2026-08-12 · 阻断审计已重开）

- **本轮已达到硬停线：继续保持 `E3_OPEN / BLOCKED`。**login-flow 恢复三轮为 `55 failed / 166 passed / 240 deselected` → `75 failed / 386 passed` → `29 failed / 431 passed / 1 skipped`；最终仍 exit `1`，且 skipped 不为 0。按任务书“同一失败簇三轮即停”，不得继续修改/重跑该文件或完整 L0。
- 用户已明确要求继续，本次从历史三轮停线后的失败清单按小簇恢复，不重做已完成的 E3 信任链和十类矩阵。
- 当前尚未产生新的**完整** L0 结论；历史 `253 failed / 1747 passed` 仅作起点。non-login 第 1 轮为 `19 failed / 1686 passed / 0 skipped`，18 项已证实来自运行中共享测试文件迁移前的旧收集源码；当前树相关两文件为 `212 passed`。另 1 项跨测试 shutdown 缓存污染已通过公开 lifecycle seam 关闭；前置原子调度测试改为受控等待真实 Runner 后，相邻最终切片 `4 passed / 0 skipped`。
- login-flow 恢复后前两轮为 `55 / 166 / 240 deselected` 与整文件 `75 / 386`；最终第 3 轮已执行并按置顶结论停线。
- 固定 commit、干净 worktree 与 `E3_READY_FOR_CANARY` 仍须等待完整 L0 真正 `0 failed / 0 skipped`，在此之前保持不提交、不推送、不执行真实保存。

### login-flow 第 3 轮剩余 29 项（精确节点）

1. `test_ensure_page_detaches_browser_session_created_on_another_thread`
2. `test_visible_editor_later_steps_preserve_existing_values_without_dom_eval`
3. `test_visible_semi_managed_defaults_preserve_existing_without_dom_eval`
4. `test_visible_editor_fill_semi_action_does_not_regoto_current_editor`
5. `test_visible_editor_save_prefill_preserves_main_images_without_dom_repair`
6. `test_visible_editor_semi_entry_steps_preserve_existing_without_dom_eval`
7. `test_data_acquisition_claim_does_not_fail_when_visible_screenshot_fails`
8. `test_perform_draft_box_edit_reuses_matching_open_editor_before_search`
9. `test_visible_editor_required_defaults_state_uses_bounded_probe_not_page_evaluate`
10. `test_save_only_from_editor_page_does_not_require_semi_managed_prefill`
11. `test_editor_required_defaults_state_accepts_existing_category_value`
12. `test_apply_reference_templates_treats_existing_attribute_template_text_as_applied`
13. `test_fill_editor_required_defaults_defers_unsupported_reference_templates`
14. `test_fill_editor_required_defaults_skips_manual_attributes_when_template_applied`
15. `test_fill_editor_required_defaults_does_not_manual_fill_when_optional_template_misses`
16. `test_fill_editor_required_defaults_defers_downstream_owned_fields`
17. `test_visible_editor_fill_defaults_uses_safe_modal_checks`
18. `test_visible_editor_fill_defaults_blocks_when_required_sections_remain_missing`
19. `test_visible_editor_required_defaults_state_uses_runtime_probe`
20. `test_visible_editor_fill_defaults_reuses_editor_state_when_title_present`
21. `test_visible_editor_fill_defaults_applies_source_title_template_strategy`
22. `test_visible_editor_fill_defaults_applies_template_goods_code_strategy`
23. `test_visible_editor_fill_defaults_fails_fast_when_required_text_fields_not_found`
24. `test_fill_semi_managed_defaults_uses_column_header_strategy`
25. `test_fill_editor_variants_defers_missing_logistics_attribute_when_table_fields_filled`
26. `test_fill_editor_variants_confirms_each_logistics_icon_even_when_plain_goods_visible`
27. `test_fill_editor_variants_sanitizes_invalid_custom_names_before_save`
28. `test_fill_semi_managed_defaults_accepts_retail_price_and_original_box_select`
29. `test_fill_media_assets_marks_eu_outer_package_manual_required_when_picker_is_unavailable`

- 最终输出只显示 `1 skipped`，没有节点名或 reason，且未重定向日志；为遵守三轮停线，未再执行 pytest 获取详情，故该 skipped 证据保持 `UNKNOWN`。
- 当前不允许形成本地固定 commit：完整 L0 未绿，且 75 个候选依赖闭包仍与 691 个明确排除项共存于大脏工作树。`output/**`、Playwright 产物、prototype、data/raw 与 52 个删除均不得暂存；本轮实际 staged=`0`。

## E3 完整信任链闭环当前阻断（2026-08-12 · 停线）

- **唯一硬阻断仍是完整 L0 未清零。**最近完整运行=`253 failed / 1747 passed`；本轮后置安全强化后只允许并实际完成聚焦复验，不能把 `326 + 89 + 373` 绿或 `2166 collected` 改写成完整 L0 绿。
- **同一失败簇三轮已经耗尽。**`test_login_flow.py` 为 `131 failed / 330 passed → 102 / 359 → 75 / 386`。任务书要求三轮即停，所以本轮禁止再次执行该文件或包含它的完整 L0；剩余旧 source/claim/add-note、ElementHandle/pre-dispatch fixture、legacy defaults/UI、CDP/签名与 `published=None` 必须在后续新轮次按簇迁移后再验。
- **因此不能建立固定提交。**任务只授权在所有门禁绿后形成一个本地 commit；当前条件不成立，故未 staged、未 commit、未建临时 worktree、未 push。最终 status=`764`（tracked non-deleted=`60`、untracked=`652`、deleted=`52`）；当前 E3 核心与新增矩阵仍包含未跟踪文件，干净检出不可复现。
- **状态只能是 `E3_OPEN / BLOCKED`。**不得标 `E3_READY_FOR_CANARY`、不得进入真实三商品保存；真实浏览器操作、保存、发布均为 `0`。
- **非阻断 P2：** `DxmLoginFlow` 仍集中页面写入、读回、Schema、网络审计与身份校验；本轮将新增事务权威放入独立模块但未全量重构巨型类，后续需单独架构任务。
- 任务0身份、只读哈希和端口保持；最终精确账号/密码/token/Cookie 扫描为 `0`，没有读取或写入真实 `data/**`。

## E3 六次返修当前阻断（2026-08-12 · 进行中）

- **本轮三个新生产 P1 已有独立红→绿，但 E3 尚未接受。**动作时租约已并入 ledger 同一事务；VERIFY 元数据改由实际 SAVE/任务/审批/ledger 权威事实重建；SAVE 成功必须携带并匹配当前类目/Schema 且至少一次只读 Schema 请求。三项合并 `160 passed`，不能替代完整 L0、固定点和真机三铁证。
- **V1 已绿，但完整 L0 当次证据仍红。**V1 从第一轮 `21 failed / 68 passed` 收口为第二轮 `89 passed`；安全负例未放宽，legacy `batch_save` 保持写前拒绝。完整 L0 为 `253 failed / 1747 passed`、exit 1，绝不以聚焦绿覆盖。
- **`test_login_flow.py` 已跑满三轮并停线。**三轮为 `131 failed / 330 passed → 102 / 359 → 75 / 386`；剩余 75 项仍覆盖旧 source/claim/add-note fixture、ElementHandle/点击前 guard fake、legacy defaults/UI、CDP/签名与 `published=None`。按硬规则不再运行该文件或包含它的完整 L0，需下一轮从失败清单逐类迁移后再取得新证据。
- **遗留演示/小簇修后缺最终绿证据。**非 login-flow 合同簇由 `116 / 350` 降至 `65 / 401`；demo 最后一次运行在收集期因缩进退出，修正后仅 `py_compile` 通过。小簇第三轮余 1 项后修正文案但未第四跑。不得把语法绿或静态修正解释为 pytest 绿。
- **可复验固定点仍缺失且本轮不能自行提交。**`batch_command_contract.py`、`product_identity.py`、`test_e3_batch_draft_save_gates.py` 仍为 untracked；原任务明确“未经另行授权不提交、不推送”，因此本轮不暂存/提交。若要解除此项，需用户单独授权审定提交范围后形成固定 commit；不能以旧 HEAD 绑定真实写权限。
- **DxmLoginFlow 的 Divergent Change 尚未结构性拆分。**本轮只把租约、VERIFY 权威事实与 ActionResult Schema 规则收进独立深合同；页面写入/读回、Schema、网络审计和身份验证仍集中于超大 flow。该 P2 不用于放宽三个 P1，也不阻塞其专项修复，但在 E3 关闭前仍需架构裁定。
- 真实浏览器操作=0、保存=0、发布=0；继续保持 `E3_OPEN / BLOCKED`，禁止真实三商品保存验收。

## E3 五次返修当前阻断（2026-08-11 · 进行中）

- **置顶：V1 单用例已触发三轮止损，当前完整 L0 不可宣称已复验。**`test_single_save_generates_success_report_and_never_publishes` 三次依次失败于证据引用缺 `kind/captured_at`、kind 不是 `save_screenshot`、VERIFY 与 SAVE 证据时间相同；最新数据库错误为 `VERIFY_NOT_PUBLISHED evidence must be captured after SAVE evidence`。fixture 已改为 SAVE=`08:00:00`、VERIFY=`08:00:01`，但按硬规则本轮不再运行该用例/文件/完整 L0，修正仍待下一轮一次性复验。最近完整 L0 `301 failed / 1668 passed` 只属修改前历史证据，不能代表当前工作树。
- **已关闭“真实 readback producer 会被集中 consumer 自身拒绝”。**正式 producer→consumer 红测先稳定返回 `FROZEN_EXECUTION_READBACK_FIELD_INVALID`；现统一七键字段 schema 并校验定位基数/聚合语义，E3 整文件 `38 passed`。该缺陷已关闭，但不能抵消置顶的 L0/固定点阻断。
- **已关闭“最终页面预检期间授权事实变化仍会点击”，并关闭 JIT→ledger 微窗。**唯一 DB/runtime JIT 已移到 `_pre_dispatch_guard` 成功之后；预检把 job 变为 pending 的反例返回 `AUTH_COMMAND_QUEUE_STATE_MISMATCH` 且 operation 未执行。随后 ledger 的 `BEGIN IMMEDIATE` 事务会再次以 command queue guard 对持久 task/jobs 做 CAS；JIT 后漂移同样拒绝且 ledger 保持 RESERVED，整文件 `16 passed`。
- **已关闭“最终 Schema 复核 POST 会污染唯一 SAVE 审计”。**只豁免精确 `attributeList/childAttributeList` 同源 POST 并单列可审计计数；未知 POST、发布/release/online 与额外保存仍按 mutation fail-closed。真实 capture→finalize 正/负向 `2 passed`。
- **已关闭“VERIFY 只验证自洽 context、未绑定实际 SAVE”。**ledger 新增/迁移 `command_sha256`，在首次 DISPATCHING 时冻结实际 SAVE command；batch VERIFY 必须命中对应 DISPATCHED 行并精确匹配其持久事实，伪造 command hash 即使重算 context 也返回 `SAVE_VERIFICATION_LEDGER_MISMATCH`。Runner pair 还有第二道 actual-command 比较。
- **已关闭稳定 binding/hidden/部分写入/读写定位漂移。**中文字段名仅展示，不参与 frozen resolver；hidden 等不可见/不可操作控件拒绝；所有字段先全量定位与值预检后才允许首次 DOM 变更，后置非法 select/radio 不再污染前置 title；writer/readback 共享同一 resolver，相关 `7 passed`。
- **专项绿不能覆盖当前两个硬阻断。**核心安全聚合 `432 passed`、E2→E3→PublishGuard `179 passed`、frontend/desktop 全绿；但当前没有一次修改后完整 L0，也没有可复验 Git 提交固定点。因此继续保持 `E3_OPEN / BLOCKED`，禁止真实三商品保存验收。

## E3 四次返修当前阻断（2026-08-11 · 进行中）

- **已关闭“JIT 可授权非当前 pending 商品/陈旧队列版本”。**新增集中式 queue guard：稳定 epoch 绑定任务、快照与有序 job 身份，动态 version 绑定 task/job 状态、步骤和更新时间；JIT 要求唯一串行队首并从 SQLite 重算。两个旧 `OK` 反例均已转为 `AUTH_COMMAND_QUEUE_STATE_MISMATCH`。
- **已关闭“读回字段身份可脱离 payload 伪造”。**ActionResult、Runner 与 BrowserAgent 现在共用精确字段合同；总 hash 相同但字段键/binding/值 hash 不属于冻结 payload 时 fail-closed。
- **已关闭“VERIFY 可脱离精确 SAVE 上下文”。**batch VERIFY command 与证据现在绑定 task/job/snapshot、queue generation、runtime/session、Git/worktree、授权事实、target/payload/mutation scope，以及精确 SAVE command/action-result 哈希；篡改回显或替换前序 SAVE 均 fail-closed。
- **已关闭“页面 category/Schema 漂移仍可进入字段写入”。**正式 DxmLoginFlow 在任何字段写入前及 ledger/点击前各读取一次当前页面 categoryId 与同源只读实时 Schema，重建 hash 后与冻结 payload 精确比较；不可读或漂移均零写入停止。
- **已关闭“合法 E2 冻结结果仍必然进入 legacy 固定字段清单”。**batch Path A 现在只按冻结 `ui_binding/resolved_value` 填写；所有 binding 先整体预检，唯一控件成立后才写，支持结构化 editor 字段、类目属性选择与 SKU 行，随后由独立读回逐字段重算 hash。两个相同值的歧义控件、重复 binding marker、缺失 SKU 子字段都会 fail-closed，不会用 `data-resolved-json` 伪造写入。
- **仍阻断 E3 接受：**上述证明来自正式 `DxmLoginFlow` + 本地 Chromium DOM，不是真实店小秘三个类目的 DOM/Schema 集成；完整 L0 与可复验 Git 固定点仍红/缺失。真实店小秘三类目正式填写能力须在固定点与 L0 关闭后另行零发布验收，不以本地 DOM 绿代替。
- **既有 task_start_guard 红簇未扩大。**本轮实测仍为 `4 failed / 131 passed`，分别是 claim_only 旧错误优先级、审批摘要未暴露 lease_id，以及两个测试尝试绕过生产单 active trigger 构造双 running 遗留态；与此前三轮止损记录一致，本轮不削弱生产触发器或批量授权合同换绿。
- **完整 L0 仍是硬阻断。**当前工作树实测 `301 failed / 1668 passed in 617.80s`、exit 1；虽较 `302 / 1662` 改善，但 301 个失败未清零。失败清单仍以旧 single_save/claim_only、旧前端信息架构合同、legacy DxmLoginFlow/Runner 夹具为主；本轮五项 E3 新合同及正式冻结写入纵切均未进入失败清单。聚焦绿不能覆盖此红门禁。
- **L0 首错已再次确认属于旧 single_save 合同。**`pytest -q -x --tb=short` 在 `331 passed` 后首先失败于 `test_valid_single_save_passes_with_required_templates`，其期望与当前“reference template unsupported”事实冲突；按既有三轮止损规则留待独立裁决，不以迁移旧 claim/single_save 夹具污染 batch Path A。
- **可复验 Git 固定点仍缺失。**HEAD 仍为 `7dfab878...`，status=`742`（tracked=`102`、untracked=`640`、deleted=`52`）；本轮执行源码 tree 虽已取证为 `7E999C89...107200`，但实现仍位于大脏工作树，未 commit/push，也未清理用户文件。真机授权不得只绑定旧 HEAD。
- 真实浏览器操作=0、保存=0、发布=0；继续保持 `E3_OPEN / BLOCKED`。

## E3 三次返修当前阻断（2026-08-11 · 进行中）

- **已关闭本轮 mode 降级绕过。**授权分支不再读取可删的 `batch_draft_save_execution` 参数；immutable `execution_mode` 必须与 SQLite 中 `task.mode` 精确一致，降级反例已由红转绿。
- **已关闭“冻结后重新查模板/商品”的直接漂移。**Runner 已改为只从当前 job 对应的 E2 `item_snapshot.resolution_result` 编译执行值，并校验 Schema、mapping、resolution 三类 hash；模板 `10 → 99` 的反例保持执行值 `10`。
- **已关闭 execution payload/readback 漂移。**正式 command、JIT、Runner 与 BrowserAgent 结果均绑定同一冻结 payload hash；保存前逐字段读回发生在预填后和 ledger/click 前，字段值或 readback hash 漂移均拒绝。E3 专项整文件 `33 passed`。
- **已关闭 UNKNOWN 被误归普通失败。**恢复与 Runner 现在持久化 `job/report=unknown`、task=`needs_manual_review`，不增加 `failed_jobs`，并保持尾部 pending 与不可重试。
- **已关闭 desktop 版本漂移。**desktop package/lock、前端与后端均为 `0.1.3`，桌面标准测试 `89/89 passed`。
- **仍阻断 E3：本工作树完整 L0 为 `302 failed / 1662 passed in 519.35s`，exit 1；失败数显著下降仍不等于门禁通过，且没有可复验 Git 固定点。**
- **固定点仍未形成。** 最终身份为 branch=`fix/dxm-two-stage-runtime-truth`、HEAD=`7dfab878...`、status=`741`（tracked=`102`、untracked=`639`、deleted=`52`），status SHA256=`7FBBF23C...15D31`；未 commit、未 push，也未恢复 52 个既有删除或清理用户文件。
- **已关闭用户点名的两个当前红簇。**batch execution `43/43`、BrowserAgent status `93/93`；均在第三轮转绿，未使用 skip、todo 或放宽生产门禁。
- 真实浏览器操作=0、保存=0、发布=0；继续保持 `E3_OPEN / BLOCKED`。

## E3 当前待关闭项（2026-08-11 · 本轮最新）

- **本轮审计两项关键安全缺陷已关闭。**JIT 现在精确绑定 command/snapshot/job/lease/mode/target 与 v2 worktree identity；未完成的 `DISPATCHED` 重启恢复为持久 `UNKNOWN` 且不可重试。HTTPS 正式 origin、模式化页面合同、终态执行身份和持久 worker SAVE→VERIFY 均有反向测试。
- **仍阻断 E3 接受：完整 L0 红。**实测 `404 failed / 1553 passed in 840.36s`，首个失败为审批上下文 `EXACT_OBJECT_REQUIRED`。相对用户验收的 `405 / 1544` 未恶化不等于通过；不得放宽强证据、UNKNOWN 或发布门来换绿。
- **仍缺可复现 Git 固定点。**HEAD 仍为 `7dfab878...`，status=`738`（tracked=`100`、untracked=`638`、deleted=`52`）；本轮执行源码树指纹为 `398FDA7B...E0849`，但 E1–E3 实现仍在大脏工作树。没有 commit/push，也没有恢复既有删除或清理未跟踪文件。
- **当前运行服务不可作为本轮代码证据。**本轮未终止、接管或启动任何服务；收口检测 `8000/5173` 均无监听，与验收输入“8000 为修复前无 reload 后端”不同。真机前必须从审定固定点启动新服务并核对 runtime/Git/worktree identity。
- **真实三商品三铁证仍未执行。**本轮所有 BrowserAgent 测试均使用隔离临时目录与 `external_write=false` 模拟操作；真实浏览器操作、保存、发布均为 0。只有完整 L0 与固定点关闭、服务身份一致，并再次明确授权后，才可逐件执行“回包 + 页面成功态 + 独立未发布”；任一 UNKNOWN 立即停批。
- **当前版本仅为源码 `0.1.3`。**标准前端 build 已绿，但没有 portable 构建或交付，不得把版本升级解释为发布或 READY。
- **L0 子项三轮停点：`test_batch_execution_contract.py`。**三次聚焦复跑依次暴露审批夹具缺 `l2_evidence_fingerprint`、把已禁用的类目绑定模板用于执行 happy path、以及把 name-only 的不支持 DXM 引用段标成必填；前两项迁移后继续向下暴露，第三轮为 `36 failed / 7 passed`。现已将夹具改为仅配置有真实精确控制路径的引用段，但按“同一验收连败 3 次即停”本轮不再复跑或宣称已绿，留待下一轮验证；生产 fail-closed 门禁未放宽。
- **L0 子项三轮停点：`test_browser_agent_status.py`。**三轮由 `26 failed / 67 passed` → `24 / 69` → `7 / 86`；生产侧已把外部 JIT authorizer 移出生命周期锁，并在授权后、ledger/点击前重新检查撤销、页面/目标身份与 preflight，关闭取消/接管被授权调用堵住及授权期间身份漂移窗口。剩余 7 项为取消收口时序 1、晚结果错误码期望 3、旧编辑命令缺 frozen target 1、HUD 夹具身份不一致 2；本轮停止该子项，不宣称整文件已绿。
- **L0 子项三轮停点：`test_task_start_guard.py`。**旧 helper 补齐稳定 1688 来源 URL、当前释放模式、精确直连禁用 reason_code 和不可执行 DXM 引用后，整文件由 `34 failed / 101 passed` 降到第三轮 `4 / 131`。剩余为：反向商品绑定用例仍先命中缺来源 URL 1、公共审批摘要缺 lease_id 1、SQLite 单 active 触发器阻止构造双 running 遗留态 2；本轮停止，不绕过生产触发器或削弱启动门。
- **L0 子项三轮停点：`test_v1_runner.py`。**三轮为 `36 failed / 53 passed` → `34 / 55` → `31 / 58`。已把 description/compliance/semi_managed 三类没有真实精确控件与 readback 的引用改为 `required=false`，并把 `offer/test-1.html` 迁为数字商品 ID；剩余主要是旧 FakeWorkflowAdapter 不接收 frozen `target_identity`、旧 single_save 状态序列/错误码及报告预期。不得删除 target identity 或恢复宽松 URL 来换绿，本轮停止该文件。
- **L0 子项三轮停点：`test_login_flow.py`。**第二轮仍为 `134 failed / 327 passed`；测试授权器补执行 pre-dispatch guard、直接保存调用补齐 frozen target/store/字段完整性后，第三轮为 `131 / 330`。剩余横跨已永久关闭的直连 mutation API、缺 source URL/冻结身份的私有调用、旧 CDP/DOM fake、网络审计 session 与当前严格 SAVE/VERIFY 合同；本轮停止，不给生产 `_save_only_on_page` 增加可省略身份的默认值。
- **已关闭的 L0 子项：`test_batch_edit_api.py`。**当次整文件 `36 passed in 18.23s`；原子 approve-and-start 与 split approval 永久关闭边界保持，不重开旧批准令牌入口。
- **完整 L0 本轮不再重跑。**上述五个文件已触发三轮止损；再次执行全量会重复已停止的同一失败项。最近完整证据保持 `404 failed / 1553 passed`，E3 核心 `160 passed` 与 identity/PublishGuard `27 passed` 只能证明新安全合同未回退，不能关闭 L0 或 E3。

## E3 当前待关闭项（2026-08-10 · 本轮最新）

- **已解除旧 Path A 生产合同阻断：**共享 action-result 现在原生允许批量 Path A `editor`，正式 `dxm_draft_box_target.v1`、批量授权事实、逐 job mutation scope、持久 BrowserAgent 与 ledger 已通过隔离纵切；Runner 不再把结果改写成 Path B。旧 `single_save` 的 `semi_managed` 合同保持。
- **仍阻断 E3 接受：完整 L0 红。**本轮实测 `404 failed / 1545 passed in 770.22s`，虽优于 `425 / 1516`，但“失败数下降”不等于门禁通过。剩余失败仍分布在旧 batch execution、BrowserAgent lifecycle、task start 与 `single_save` V1 等历史簇；不得放宽强证据、恢复旧叙事或批量改断言换绿。
- **仍阻断真机接受：三商品三铁证未执行。**本轮只运行隔离正式 worker，模拟外部 operation 明确 `external_write=false`；没有登录、打开真实编辑页、保存或发布。下一步必须另行明确授权可见浏览器的真实三商品“只保存不发布”验收，并逐件取得回包、页面成功态、独立未发布证据；任一 UNKNOWN 立即停批。
- **仍缺可复现 Git 固定点。**HEAD 仍为 `7dfab878...`，E3 与此前 E1/E2/G4 实现仍位于大脏工作树；本轮没有 commit/push，也没有恢复 52 个既有删除或清理 638 个未跟踪文件。需要单独授权并审定固定点范围后才能形成可复现提交。
- **运行时保持外部所有权。**收口时 8000/5173 分别由既有 PID 33636/31588 监听；PID 33636 同时持有真实 `data` lease。本轮测试全部使用隔离 `DXM_DATA_DIR`，未终止、接管或重启这些进程。

## E3 Path A · BrowserAgent 页面合同旧阻断（已解除，保留历史）

- 旧阻断是共享 BrowserAgent 曾把 `SAVE_ONLY` / `VERIFY_NOT_PUBLISHED` 固定为 `semi_managed/editFromSmt`。本轮用户授权的 E3 返修已将其参数化为 Path A `editor`，同时保留旧 single_save 页面合同；当前以本文件上一节最新裁定为准。

## G4 当前唯一真机阻断（2026-08-10）

- 历史“登录后运行 `scripts/g4-zero-write-after-login.ps1`”路径已被本次用户指令明确废止；G4 唯一主路径改为工作台 UI + 稳定 API，不得以脚本成功代替 UI 验收。
- 会话架构与 UI 主路径已经用真机证明：`/web/home` → `LOGIN_READER_READY` → shops(API/同源会话/2 店铺) → 真实 products → 同店同类目 3 件 → 本地方案 #4 → preview。
- 当前唯一阻断发生在 preview 的 E2 值解析：真实商品详情返回 `detail attrValueId 不是稳定正整数身份。`。生产端按 fail-closed 拒绝，未生成可冻结 snapshot；不得删除身份校验、用 mock/历史 raw 代替或直接构造 snapshot。
- 待后续 E2 解析任务：在不读取 Cookie、不过度记录真实商品内容的前提下，为失败字段提供可审计的 wire-shape 分类，区分 `0` 哨兵、空 ID 自定义属性、缺失 ID 与非法 ID；只允许明确哨兵/不可执行审计项归一化，稳定身份字段继续严格正整数。修复后从同一工作台 UI 重跑 preview→freeze。
- 真机验收仍坚持零店小秘写入：不得调用保存、发布或 Runner 启动。2026-08-10 网络核对未出现保存/发布/Runner/freeze/plan-snapshots 业务请求；当前没有 snapshot/task 可宣称完成。

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
- **G1 Git 固定点：已授权 commit（不自动 push）**（2026-08-03 用户）。`E2-CLOSE-CANDIDATE`=`09fceb756cd56f6971893db3977a1d97671bc208`。
- **G5-1 Gold 哈希：已授权并执行**（2026-08-04）。悬空架构文档引用已改；期望 SHA=`DD41C8A4…CBF2B`；SelfTest 绿。
- **G4 真机零写：已授权，会话未闭环**（2026-08-04）。可见浏览器可到 DXM home URL，但自动 `login/continue` 未稳定 ok；需用户在可见窗完成登录后跑 `scripts/g4-zero-write-after-login.ps1`。
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
