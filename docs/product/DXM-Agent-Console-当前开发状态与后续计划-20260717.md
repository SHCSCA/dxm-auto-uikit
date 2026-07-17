# DXM Agent Console 当前开发状态与后续计划

更新时间：2026-07-17

## 结论

DXM Agent Console 的核心需求已经收敛为一条可审计的真实业务闭环：

> 对店小秘已有待认领商品，先受控认领到商品箱，再对同一个商品按既有模板编辑，只保存、不发布；全过程使用真实可见浏览器、独立人工审批和可交叉验证的证据。

当前源码正在实现并加固这条两段式真相链，但**尚未达到当前版本的生产交付标准**。没有同一干净 Git HEAD 的 portable、packaged smoke、新鲜 L2 和同商品 Stage A/Stage B 真实现场闭环，因此生产状态为 `BLOCKED`。

## 当前源码边界

| 能力 | 当前事实 |
|---|---|
| Stage A `claim_only` | 已进入受控源码 release surface；只允许已有待认领商品入箱 |
| Stage B `single_save` | 已进入受控源码 release surface；必须绑定已完成 Stage A 的同商品快照 |
| 审批 | Stage A/B 使用不同确认语义和服务端审批租约；读 API 不回显 token/hash |
| Browser Agent | 真实路径使用持久化运行时和可见浏览器，不再把每一步当作独立新浏览器 |
| 动作结果 | 真实 mutation 按 state/action 契约校验结构化结果与证据，不能用空 readback 或模糊 success 通过 |
| 两段式验收 | `dxm_two_stage_acceptance.v1` 聚合同商品 Stage A/B 事实 |
| 状态一致性 | `dxm_state_consistency.v1` 审计 task/job/report/exception 冲突并阻断 READY |
| 模板 | 创建真实任务不会自动生成、修补或静默持久化硬编码生产模板 |
| 扩大范围 | `batch_save`、批量、无人值守、发布和发布类按钮保持关闭 |

这些是源码边界说明，不是本轮测试通过、打包通过或真实写入授权。

## 仍未完成的生产门禁

### P0：Browser Agent mutation 不确定性收口

- mutation ID 必须独立于短生命周期 runtime，稳定绑定审批/任务 scope、state、ordinal 和 action。
- 真实动作必须通过持久化 ledger 的原子状态迁移；进程重启不能把同一动作当作新动作再次点击。
- 崩溃时仍处于 `DISPATCHING` 的记录必须恢复为 `UNKNOWN`，只允许人工对账。
- 外部浏览器操作不能长期持有生命周期/取消锁；cancel、shutdown、takeover 与 timeout 必须能及时返回且不会自锁。
- mutation 前必须再次核对实时 session、精确页面和目标绑定；授权通过后发生的页面漂移必须阻断点击。
- resume/takeover/shutdown 的 owner 代际必须单调，旧操作不能覆盖新 owner 或重复关闭会话。

### P0：源码级回归与真相聚合

- 完成 Browser Agent 协议、生命周期、ledger、login flow、runner 和状态一致性的聚焦回归。
- 完成后端全量、前端生产构建、脚本契约和 `git diff --check`。
- UI 与 final-delivery-check 必须读取同一套两段式、状态一致性、运行时和证据事实，不能把历史 L2/L3 或单次保存显示成当前生产 READY。

### P0：同 HEAD portable 与真实现场验收

1. 在干净提交上运行全部交付门禁。
2. 从该提交构建新的 portable，记录 Git HEAD、build identity、SHA-256。
3. 启动该 portable，验证 runtime identity、持久化登录、Browser Agent/HUD 和 packaged smoke。
4. 产生新鲜 L2 双目标同轮次只读证据。
5. 在产品内分别审批 Stage A 和 Stage B，对同一个真实商品完成入箱、编辑、只保存。
6. 核对保存回包、截图/路径、结构化证据和独立的 `published=false` 证明。
7. 运行最终交付检查；任一身份或证据不一致都回到 `BLOCKED`。

## 当前验收口径

只有下列条件同时满足，才能把 `ExpectedRealDxmWriteReadiness` 改为 `READY`，并把 `ExpectedRealDxmTwoStageEndToEnd` 改为 `passed`：

- clean Git、runtime/build/package identity 完全一致；
- 新 portable packaged smoke 通过；
- 新鲜 L2 双目标证据通过且绑定一致；
- 同商品 Stage A/B 现场闭环通过；
- `delivery_readiness.ready=true`；
- `two_stage_acceptance.passed=true`；
- `state_consistency.consistent=true` 且无 violation；
- mutation ledger 无 `UNKNOWN` 或未对账动作；
- 没有发布、批量或无人值守范围扩张。

在此之前，交付检查应使用：

```bat
scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness BLOCKED -ExpectedRealDxmTwoStageEndToEnd pending_live_dxm_validation
```

## 历史资料说明

- 2026-07-04 portable 与 `READY` 结论只属于当时构建和 `controlled_single_save_only` 范围。
- 2026-07-06、2026-07-09 状态文档保留真实任务编号和当时页面问题，不能覆盖本文。
- 用户在 2026-07-17 授权更新文档、合并分支和推送代码；该授权只解决 Git 操作权限，不会降低任何发布门禁。

## 下一步顺序

1. 收口 mutation ledger 和 Browser Agent 生命周期 P0。
2. 跑聚焦回归与全量验证，修复失败而不放宽门禁。
3. 对齐 UI、workspace 和 final-delivery-check 的真相字段。
4. 清理并提交受控文件，明确排除用户/本地输出。
5. 合并和推送后，再从合并后的同一 HEAD 构建 portable 并执行真实 Task 6 验收。
