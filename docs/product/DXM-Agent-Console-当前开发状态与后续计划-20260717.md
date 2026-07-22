# DXM Agent Console 当前开发状态与后续计划

更新时间：2026-07-22

## 结论

DXM Agent Console 的核心需求已经收敛为：

> 从店小秘商品箱选择已经存在且身份可验证的商品，按已确认模板编辑，只保存、不发布；既支持单商品金丝雀，也支持一次批准后严格串行执行的受控整批。

认领环节及相关页面、任务模式、API、运行时状态和验收字段已经移除。系统不再从“待认领列表”创建或搬运商品，也不要求保存任务关联历史认领任务。

当前源码边界已经变更，但在同一干净 Git HEAD 的全量测试、全新 portable、packaged/portable smoke、新鲜 L2 商品箱只读证据和真实保存现场验收完成前，生产状态仍为 `BLOCKED`。

## 当前源码边界

| 能力 | 当前事实 |
|---|---|
| `single_save` | 只能选择商品箱中现有且已验证的一个商品；创建任务时冻结商品、店铺、来源、目标与证据快照 |
| `controlled_edit_batch` | 冻结当前可见商品箱范围与顺序，一次批准后全局单并发、逐商品即时授权、串行只保存 |
| 审批 | 服务端签发短租约；读 API 不回显 token/hash；真实保存动作前必须完成实时复核并消费批准 |
| Browser Agent | 使用持久化运行时和可见浏览器；命令绑定 runtime/session/page/target 与 mutation ledger |
| 动作结果 | `dxm.action-result.v1` 必须同时证明精确保存目标、保存回包、页面成功和独立未发布读回 |
| 单次保存验收 | `dxm_single_save_acceptance.v1` 聚合商品箱快照、批准消费、保存、未发布、证据完整性和状态一致性 |
| 状态一致性 | `dxm_state_consistency.v1` 审计 task/job/report/exception 冲突并阻断 READY |
| L2 | 只检查商品箱 `draft_box`，必须绑定同一脚本、Git HEAD、session fingerprint 与证据文件 hash |
| 禁止范围 | 旧 `batch_save`、无人值守调度、发布、继续发布、保存并发布、移入待发布全部保持关闭 |

这些是源码边界，不等于本轮测试、打包或真实写入已经获准。

## 仍需完成的生产门禁

### P0：完整删除验证

- 后端、前端、脚本和当前文档不得再暴露旧认领入口或旧验收 schema。
- 删除后的导入、路由、任务模式和状态机必须通过契约测试，不能保留静默兼容 alias。
- 历史验收记录和历史计划保留用于审计，但不能被运行时或当前 UI 消费。

### P0：保存动作不确定性收口

- mutation ID 稳定绑定任务/批次、商品、state、ordinal 和 action，不能依赖短生命周期 runtime ID。
- `PENDING -> DISPATCHING -> DISPATCHED` 必须由持久化 ledger 原子推进。
- 崩溃、超时或外部结果不确定时进入 `UNKNOWN`，停止当前批次并人工对账，绝不自动重试。
- 保存点击前重查 session、精确页面、商品箱冻结目标、店铺、批准租约、deadline 和 lifecycle generation。

### P0：同 HEAD portable 与真实现场验收

1. 在干净提交上运行后端全量、前端 build、脚本契约和 `git diff --check`。
2. 从该提交构建全新的 portable，记录 Git HEAD、build identity 与 SHA-256。
3. 启动该 portable，验证后端身份、持久化登录、Browser Agent/HUD 和 packaged smoke。
4. 产生新鲜的商品箱 L2 只读证据。
5. 在产品内选择一个真实商品箱商品，批准并完成 `single_save`。
6. 核对精确保存回包、保存截图、独立未发布截图、文件 hash 和零发布信号。
7. 若交付受控整批，再验证一次批准、严格串行、逐商品证据、失败隔离与 `UNKNOWN` 停批。

## 当前验收口径

只有以下条件同时满足，才能把 `ExpectedRealDxmWriteReadiness` 改为 `READY`，并把 `ExpectedRealDxmSingleSaveEndToEnd` 改为 `passed`：

- clean Git、runtime/build/package identity 完全一致；
- 新 portable 的 packaged 与 portable smoke 通过；
- 新鲜 L2 商品箱证据通过，且 `evidence_binding.target_set=["draft_box"]`；
- `delivery_readiness.ready=true`；
- `single_save_acceptance.passed=true` 且 `missing_codes=[]`；
- `state_consistency.consistent=true` 且无 violation；
- mutation ledger 无 `UNKNOWN` 或未对账动作；
- 保存结果、网络回包、保存截图和独立 `published=false` 证明完整；
- 没有发布、旧批量任务或无人值守范围扩张。

在此之前，交付检查应使用：

```bat
scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness BLOCKED -ExpectedRealDxmSingleSaveEndToEnd pending_live_dxm_validation
```

## 历史资料说明

- 旧 portable、旧 `READY`、双目标 L2 和旧流程现场证据只属于记录中的 commit、包 hash 与功能范围。
- 旧计划与历史验收记录不修改；它们用于解释变更原因，不构成当前实现要求。
- 当前结论以代码、测试、运行中的工作台和同 HEAD 新包证据为准。

## 下一步顺序

1. 完成删除契约与全量回归，清除当前运行表面的旧字段。
2. 对齐 UI、workspace、final-delivery-check 和最终报告摘要。
3. 从合并后的同一 HEAD 构建全新 portable，删除旧交付包。
4. 执行商品箱 L2 和真实 `single_save` 现场验收。
5. 若交付受控整批，单独完成批次级验收与人工对账演练。
