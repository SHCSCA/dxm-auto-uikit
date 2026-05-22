# 交付工作台 API

## Endpoint

`GET /api/delivery/workspace?task_id={task_id}`

`task_id` 可省略；省略时返回最新任务的交付工作台视图。无任务时返回 404，前端必须展示空工作台，不得把 mock 报告或 mock 证据混入真实工作台。

该接口只读聚合现有 `tasks/jobs/reports/evidences/logs/templates/exceptions` 能力，不新增或修改数据库 schema，不触发真实店小秘操作，不发布、不部署。

## 返回结构

- `baseline`：当前后端交付契约、静态测试基线和只读 schema 声明。
- `current_task`：任务、任务 payload 和 jobs 当前状态。
- `stores` / `templates` / `products` / `tasks` / `logs` / `evidences` / `reports` / `exceptions`：前端工作台可直接消费的只读列表。
- `steps`：V1 状态机步骤，包含 `status`、`has_evidence`、`has_workflow_result`、`evidence_ids`。
- `evidence_points`：原始证据点和从报告/证据中提取的 `save_result`、`published_proof`、`network_save_result`、`har_summary`。
- `report_summary`：报告计数、最新报告、保存结果、未发布证明、网络/HAR 摘要和 dxm_reference 字段。
- `template_resolution`：`dxm_reference_templates_resolved`、`dxm_reference_template_results`、`template_trace`、`resolved_defaults`。
- `dxmReferenceTemplates`：前端模板矩阵使用的分区映射视图。
- `publish_guard_state`：交付安全状态，固定不开放发布动作；当现有报告和证据均显示 `published=false` 时返回 `safe_unpublished`。
- `evidence_grade`：证据等级。
- `acceptanceGaps` / `safety`：交付缺口和只保存不发布安全条。

## 证据等级

- `A`：存在 `save_result`、`published=false` 证明，并捕获到 network 或 HAR 保存响应。
- `B`：存在 `save_result` 与 `published=false` 证明，但缺少 network/HAR 保存响应。
- `C`：保存结果或未发布证明不完整。
