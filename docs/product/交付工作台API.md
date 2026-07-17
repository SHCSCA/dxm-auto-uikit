# 交付工作台 API

更新时间：2026-07-17

## Endpoint

```http
GET /api/delivery/workspace?task_id={task_id}
```

该接口只读聚合 `tasks/jobs/reports/evidences/logs/templates/exceptions` 以及门禁计算，不执行店小秘动作，不修改任务，不发布。

### 空任务与不存在的任务

当前实现按 fail-closed 空工作台返回 HTTP 200：

- 省略 `task_id` 且没有任务：`current_task=null`，列表为空，`acceptanceGaps` 含 `empty-workspace` blocker。
- 指定不存在的 `task_id`：同样返回空工作台，并额外返回 `requested_task_missing=true` 与 `requested_task_id`。

前端不得在空工作台中注入 mock 报告、mock 证据或历史任务来伪装当前任务。调用方也不得依赖 404 判断任务是否存在。

## 顶层返回结构

| 字段 | 含义 |
|---|---|
| `baseline` | 后端交付契约、静态基线和只读 schema 声明 |
| `current_task` | 当前任务、公开 payload 与 jobs；审批 token/hash 不得出现在读 API |
| `stores` / `templates` / `products` / `tasks` | 工作台只读基础列表 |
| `steps` | V1 状态机步骤及 `status`、证据/工作流结果引用 |
| `logs` / `evidences` / `reports` / `exceptions` | 当前任务的运行事实 |
| `evidence_points` / `report_summary` | 保存结果、未发布证明、网络/HAR 与证据路径的聚合视图 |
| `template_resolution` / `dxmReferenceTemplates` | 任务快照中的模板解析和分区结果 |
| `publish_guard_state` | 发布封锁状态；任何情况下都不代表开放发布 |
| `evidence_grade` | 原始证据质量与受门禁约束后的对外等级 |
| `regression_gates` | L0/L1/L2/L3 与两段式、状态一致性相关门禁视图 |
| `state_consistency` | `dxm_state_consistency.v1`，审计 task/job/report/exception 是否互相冲突 |
| `delivery_readiness` | `dxm_delivery_readiness.v1`，按 job 聚合证据完整度及阻断原因 |
| `two_stage_acceptance` | `dxm_two_stage_acceptance.v1`，校验 Stage A/Stage B 是否属于同一商品真相链 |
| `real_mode_release_plan` | 真实模式的源码 release surface 与当前阻断原因 |
| `claim_candidates` | 从新鲜 L2 只读证据提取的候选，只是候选，不是写入授权 |
| `acceptanceGaps` / `safety` | 面向操作员的缺口与安全状态 |
| `l2_probe_plan` | L2 执行说明与证据入口 |

## 三个必须联合读取的 schema

### `delivery_readiness` (`dxm_delivery_readiness.v1`)

任务级 `ready=true` 至少要求每个目标 job 都有：

- `save_result`；
- 独立 `published=false` 证明；
- 保存与未发布截图或路径；
- network/HAR 保存回包；
- 非空且可校验的证据引用；
- 任务状态允许验收，且未被状态一致性或两段式验收阻断。

任一 job 缺失时必须在 `jobs[].missing` 和 `acceptanceGaps` 中暴露，不能只依赖顶层证据等级。

### `state_consistency` (`dxm_state_consistency.v1`)

`consistent=true` 仅在审计范围内无 task/job/report/exception 矛盾时成立。`violation_codes` 或 `violations` 非空、审计任务为空、或 READY 聚合与审计结果不一致时，最终生产结论必须为 `BLOCKED`。

### `two_stage_acceptance` (`dxm_two_stage_acceptance.v1`)

`passed=true` 必须证明：

- Stage A 为受控 `claim_only`，Stage B 为受控 `single_save`；
- 两者绑定同一个店铺、商品、来源身份与认领结果；
- Stage A 完成并验证商品箱后，Stage B 才能引用其快照；
- Stage B 具有保存成功、未发布和网络证据；
- `missing_codes` 与 `state_violation_codes` 均为空。

## 回归门禁

- L0：离线单测和前端生产构建，不访问店小秘。
- L1：`tools/probes/l1_selector_replay.py` 的离线 DOM replay。
- L2：`data_acquisition` 与 `draft_box` 两个真实目标必须同 `run_id`、脚本 hash、Git HEAD 和 session fingerprint，且网络安全计数全部为 0。
- L3：真实 `claim_only` / `single_save` 金丝雀。每个阶段都要求独立服务端审批租约与动作前复核；L2 通过本身不能放行写入。

## Mutation 不确定性边界

交付工作台的 `ready` 不是浏览器点击授权。Browser Agent 还必须在 mutation 发生前核对 runtime、session、精确页面、目标与审批租约，并通过持久化 mutation ledger 的原子状态迁移。崩溃后残留的 `DISPATCHING` 必须转为 `UNKNOWN` 并人工对账，不能自动重试。

当前 API 没有把完整 mutation ledger 作为单独顶层字段公开；因此调用方不得从 workspace 缺少 ledger 告警就推断“没有未对账动作”。生产 `READY` 必须由最终交付检查和现场验收共同证明该门禁已通过。

## 证据等级

- A：保存结果、`published=false`、network/HAR、截图/路径与结构化引用齐全。
- B：保存结果与 `published=false` 齐全，但缺 network/HAR。
- C：任一核心证据缺失，或 L2、状态一致性、两段式验收等上游门禁未通过。

证据等级只描述证据质量，不是生产授权。
