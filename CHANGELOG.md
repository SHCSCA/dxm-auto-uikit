> 由 OpenAI GPT（Codex）AI 生成/维护。

# Changelog

本文件区分“产品 REQUIRED”“当前生产接线”和“已发布产物”。存在源码或测试不等于已发布；没有同源 package、完整门禁和人工证据时不使用“完成/可用/READY”。

## [Unreleased 0.3.0]

### 安全修复

- `ConcurrentEditorGuard.acquire_writer_fence` 修复 shop 级别阻断缺口：原 SQL 查询仅检查 `(shop_id, task_id)`，改为先查任意活跃 fence on shop，再判断是否为同 task+generation 可刷新。防止不同任务在同店铺并发编辑导致数据损坏。
- 视频/翻译/批发执行器 `disabled` 状态修复：`success=True, execution_state="success"` 改为 `success=False, completion_state="disabled"`。防止 disabled 步骤被误判为成功，从而绕过安全门禁放行未真实执行的 Path A。上游 `bundle_composer` 据此正确阻断。

### Path B 安全回锁与执行边界

- Path B 配置、preview 与 freeze 可表达完整产品目标，但真实批准、启动和 Runner 派发统一使用 `PLAN_PATH_EXECUTION_NOT_RELEASED` fail-closed；HTTP 返回 `403 BATCH_PATH_B_FORBIDDEN`，不能把存在的步骤/配置误报为已释放生产执行。
- `PlanSnapshotCompiler` 集中维护 `RELEASED_PLAN_EXECUTION_PATHS={"A"}`；`main.py` 与 `V1TaskRunner` 消费同一判定，删除先前文档中的“Path B 已接通”假真相。
- E2 preview/freeze 显式注入正式必经能力检查器；缺失、无效或未经证明的能力继续拒绝，不再依赖测试顺序或人工夹具形成假绿。
- 移除无实际恢复/派发行为的弃用 `BatchExecutionRuntime` 装配；现行恢复继续由持久数据库与唯一 Runner 合同负责。
- 冻结 `batch_draft_save` 拒绝 `config-overrides`，返回 `409 BATCH_PLAN_SNAPSHOT_IMMUTABLE`；新增 `GET /api/tasks?mode=batch_draft_save&view=summary`，只查询任务摘要且不读取/解码冻结 `payload_json`。
- 15 个 legacy skip 函数（原 23 个参数化 node）迁移到 `plan_snapshot → batch_draft_save → V1TaskRunner` 公共链，没有恢复旧 `/api/edit-batches` 或第二 Runtime。
- 新增回归测试 `tests/test_writer_fence_shop_scope.py`：6 个测试覆盖 shop 级别阻断不变性。
- `test_batch_video_generator.py`、`test_batch_translator.py`、`test_wholesale_filler.py` 中 `test_disabled_returns_success` 改为 `test_disabled_returns_skipped`，assert `success=False`。

### 产品合同裁决（不等于已实现）

- 统一开发方案修订为 v1.1.2：补齐系统内单写者围栏、基于观察事实的 inspect effect、固定 `video → wholesale → translation`、不可放宽的 snapshot 执行约束、resolving/HVD、canonical serialization 与 direct `editFromSmt` 证据门。此项仅是目标合同，不代表代码已交付。
- 视频、翻译、批发、Path B 半托管和 rollback preparation 已明确为每件商品无条件必经的 `REQUIRED` 主流程，不再归类为可选扩展。
- 完整商品成功以 Path B 为准：主编辑完整读回后触发保存意图 Modal，点击“编辑半托管信息”交由店小秘原生门裁决，按真实事件闭合实际主编辑 SAVE，再进入 `/web/smt/editFromSmt` 完成半托管信息并第二次保存；Path A 只保留历史 canary/工程诊断价值。
- 半托管资格禁止本地/接口预检；提示 Modal 不等于 SAVE1 完成。当前尚未实证哪个入口点击触发 SAVE1，故两个点击均按 `MAY_DISPATCH_SAVE1` 防护；SAVE1 与门结果若已验证并因果绑定同一握手，不要求还原墙钟全序。
- Path B 欧盟外包装确认中的精确中间“继续发布”允许自动化，但必须绑定商品、页面、Modal、预期检测请求和跳转上下文；最终发布、立即发布、保存并移入待发布和上线请求继续永久禁止。
- 类目目录改为任意深度、leaf-only、版本化 path↔leaf 发现来源；正式执行仍以当前可见页面 categoryId/Schema/capability 为权威，漂移在任何写入前拒绝。
- `REQUIRED` 只定义产品范围。没有生产接线、真机读回、持久证据和完整门禁时，不能据此宣称功能可用或 READY。

当前实现仍未把上述 REQUIRED 能力全部接入生产链；0.3.0 交付结论保持 `BLOCKED`。

### 当前已接入的开发能力

- backend、frontend、desktop manifest/lock 更新到 0.3.0。
- 店铺/草稿 Reader、动态类目与模板读取、本地方案、preview/freeze 和 `batch_draft_save` 路由继续演进。
- Path A 快照/command/queue/lease/ledger/逐字段读回与三铁证合同已有生产代码。
- HVD 的开始、暂停、继续、停止在 API、状态与 UI 有工程实现。
- 文档收敛为唯一 MVP 合同、当前架构、DXM-TX 上游事实合同与当前 runbook。

### REQUIRED 能力的当前代码事实（尚未接生产 Runner）

- `BatchVideoGenerator`、`BatchTranslator`、`WholesaleFiller`：产品 REQUIRED；`disabled` 安全缺口已修复（返回 `success=False`），但页面动作空实现问题仍待闭合。
- 半托管 `SemiManagedExecutor`：产品 REQUIRED；仓内存在 Path B 步骤与配置骨架，但正式批准/启动/Runner 执行保持回锁，页面动作、双 SAVE、账本和证据闭环后才能释放。
- `RollbackManager`：rollback preparation 产品 REQUIRED；当前没有持久 preimage、逆序恢复、真实读回和 mutation 后 UNKNOWN 的完整合同。
- `EvidenceCollector`：当前只是内存字典列表，未进入 ActionResult、ledger、文件 hash 或正式三铁证。
- 新 `BATCH_*` 状态节点：已定义并进入 `BATCH_DRAFT_SAVE_STEPS` 和 `BATCH_PATH_B_STEPS`。
- 视频/翻译/批发/半托管面板：部分 UI 存在，但不能由 UI 推断 REQUIRED 主流程已挂载或可执行。

### 当前阻断

- 根 `package.json` 已更正为 0.3.0（2026-08-28）。
- CHANGELOG.md 已从 untracked 移入并写入本日安全修复与 Path B 回锁记录。
- 新增核心代码/测试仍位于脏工作树，干净检出可复现性待建立。
- 当前工作树完整 backend L0 已通过：`2344 passed / 0 skipped`；标准 package smoke 与 0.3.0 portable 尚未形成同源放行证据。
- 动态类目目录尚未完成“版本化 catalog + 当前页面 categoryId/Schema/capability 权威”的完整执行门禁。
- 视频、翻译、批发、rollback preparation 与 Path B 两次保存尚未贯通同一正式 snapshot、Runner、BrowserAgent、读回和持久证据。
- 真实三商品完整 Path B 的两段保存事实、独立未发布证明和 E4 四键同源验收未闭合。
- 所以 0.3.0 尚未发布，不得宣称 `MVP_READY` 或 `PROD_READY`。

## [0.2.3] — 本地历史产物

- 本地 `outputs/desktop-build` 中发现 `DXM-Agent-Console-Portable-0.2.3.exe`。
- 该文件是历史 package，只代表其构建时源码和证据；本轮未重新做同源 smoke，不把它提升为当前稳定发布。
- 0.2.x 的共享目标类目、动态编辑器和十区产品投影原则已合并进 [普货方案配置与执行架构](docs/product/普货方案配置与执行架构.md)。旧版本任务书与重复设计文档已删除。

## 更早版本

0.1.x–0.2.2 的具体包、测试数字和一次性任务计划属于历史。只有在可核对 Git/build/package/receipt 时才能引用；它们不进入当前必读文档，也不能授权当前真实写入。
