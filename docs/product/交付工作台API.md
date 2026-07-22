# 交付工作台 API

更新时间：2026-07-22

## Endpoint

```http
GET /api/delivery/workspace?task_id={task_id}
```

接口只读聚合 `tasks/jobs/reports/evidences/logs/templates/exceptions` 和门禁计算，不执行店小秘动作、不修改任务、不保存、不发布。

### 空任务与不存在的任务

- 省略 `task_id` 且没有任务：HTTP 200，`current_task=null`，`single_save_acceptance.status=no_task`。
- 指定不存在的 `task_id`：同样返回空工作台，并增加 `requested_task_missing=true` 和 `requested_task_id`。

前端不得注入 mock 报告、历史任务或本地候选来伪装当前任务。

### 商品箱范围捕获与单商品任务

```http
POST /api/dxm/draft-box/scope-snapshots
```

该接口只读取当前可见商品箱 DOM，验证页面、店铺、顺序、稳定商品身份、证据摘要和零写入事实后才持久化范围。持久化事务会按稳定记录键 upsert 本地商品身份投影，并返回精确匹配的 `store_identity.store_id` 与每件商品的 `local_product_id`。只有这些现场投影可以用于创建 `single_save`；手工 `/api/products` 记录、旧流程记录和缺少唯一店铺匹配的范围都不能成为真实保存目标。

本地投影不在店小秘创建或搬运商品。它只保存当前商品箱已存在商品的来源、目标、观察时间与不可变证据引用；再次读取同一稳定身份会更新原记录，不会生成第二个可执行身份。

## 顶层返回结构

| 字段 | 含义 |
|---|---|
| `baseline` | 后端交付契约和静态基线 |
| `current_task` | 当前任务、公开 payload 和 jobs；审批 token/hash 不回显 |
| `stores` / `templates` / `products` / `tasks` | 工作台只读基础列表 |
| `steps` | 保存状态机步骤与证据引用 |
| `logs` / `evidences` / `reports` / `exceptions` | 当前任务运行事实 |
| `evidence_points` / `report_summary` | 保存、未发布、网络/HAR 和证据路径聚合 |
| `publish_guard_state` | 发布封锁状态；绝不代表开放发布 |
| `evidence_grade` | 原始证据质量与门禁后的对外等级 |
| `regression_gates` | L0/L1/L2/L3 状态 |
| `state_consistency` | `dxm_state_consistency.v1` |
| `delivery_readiness` | `dxm_delivery_readiness.v1` |
| `single_save_acceptance` | `dxm_single_save_acceptance.v1` |
| `real_mode_release_plan` | `single_save`、`controlled_edit_batch` 与禁用旧模式的当前边界 |
| `acceptanceGaps` / `safety` | 操作员缺口与安全状态 |
| `l2_probe_plan` | 商品箱 L2 执行说明与证据入口 |

接口不再返回旧流程候选或旧验收字段。

## 必须联合读取的 schema

### `delivery_readiness` (`dxm_delivery_readiness.v1`)

`ready=true` 至少要求：任务已完成、状态一致、`single_save_acceptance` 通过，并且每个 job 都有保存结果、独立未发布证明、network/HAR 保存回包、保存证据文件和未发布证据文件。

关键阻断字段：

- `blocked_by_task_status`
- `blocked_by_state_consistency`
- `blocked_by_single_save_acceptance`
- `state_violation_codes`
- `single_save_missing_codes`
- `jobs[].missing`

### `state_consistency` (`dxm_state_consistency.v1`)

`consistent=true` 仅在当前任务范围内无 task/job/report/exception 矛盾时成立。`violation_codes` 或 `violations` 非空、审计任务为空，或 READY 聚合与审计事实不一致时必须 `BLOCKED`。

### `single_save_acceptance` (`dxm_single_save_acceptance.v1`)

`passed=true` 要求 `missing_codes=[]`、`product_box_snapshot_error=null`，并且下列 checks 全为 `true`：

- `save_task_mode_valid`
- `save_task_completed`
- `product_present`
- `product_box_snapshot_valid`
- `single_save_target_bound`
- `manual_approval_consumed`
- `save_success`
- `unpublished_proof`
- `save_evidence_integrity`
- `unpublished_evidence_integrity`
- `publish_guard_safe`
- `state_consistent`

`save_task_id` 与 `product_id` 必须是正整数；`save_report_count>=1`，`evidence_count>=2`。读取端只能把精确 schema 的布尔值当真，字符串 `"true"` 或缺失字段必须 fail-closed。

## 回归门禁

- L0：离线单测和前端生产构建，不访问店小秘。
- L1：`tools/probes/l1_selector_replay.py` 离线 DOM replay。
- L2：只探测真实 `draft_box`；`evidence_binding.target_set` 必须精确为 `["draft_box"]`，并绑定非空 run id、脚本 hash、Git HEAD 和 session fingerprint；文件 hash、登录态、最终路径和零写计数全部通过。
- L3：真实 `single_save` 金丝雀；必须有服务端批准、动作前复核、保存回包和独立未发布证据。

## Mutation 不确定性边界

workspace `ready` 不是浏览器点击授权。点击前仍需核对 runtime、session、精确页面、冻结目标和批准租约，并通过 mutation ledger 原子状态迁移。崩溃后残留的 `DISPATCHING` 进入 `UNKNOWN`，只能人工对账，不能自动重试。

## 证据等级

- A：保存结果、独立 `published=false`、network/HAR、保存与未发布证据文件及 hash 齐全。
- B：保存与未发布证明齐全，但缺 network/HAR。
- C：任一核心证据缺失，或 L2、状态一致性、单次保存验收未通过。

证据等级只描述证据质量，不是生产授权。
