# AGENTS.md

本仓库为中文项目，默认用中文沟通；命令、路径、代码标识符保留原文。

## 必读

- 先读 `CLAUDE.md`。它是当前项目级 AI 指引的权威来源，包含真实 DXM 写入门禁、状态机、安全边界和常用命令。
- 本项目核心是 **DXM 半托管自动化工作台**，不是本地演示页，也不是安全诊断工具。
- 当前受控真实写入入口是 `single_save` 与 `controlled_edit_batch`：都只能操作商品箱中已验证的现有商品，必须人工批准、串行执行、只保存、不发布。旧 `batch_save`、无人值守和任何发布动作均未放行。
- 认领环节、认领页面、认领任务和相关 API 已移除；不得恢复旧流程或把历史认领证据当作当前任务前置条件。

## 检索约定

主检索工具为 ace-tool（`mcp__ace-tool__search_context`）。当 ace-tool 无法满足语义搜索需求时，使用 `mcp__fast-context__fast_context_search` 作为补充。

适合使用 fast-context 的场景：

- 用自然语言描述要找的逻辑，例如“部署流程”“事件处理”。
- 跨模块、跨层级的调用链路追踪。
- 中文语义搜索。

## 交付口径

- 源码包交付前必须运行 clean worktree 验收：`scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY`。
- 读取 `final-delivery-check.json` 时不能只看 `ok`；必须同时读取 `okScope`、`realDxmMutationScope`、`realDxmWriteReadiness` 和 `sourcePackageReadiness`。
- `READY` 只表示当前声明范围具备有效证据；必须结合 `realDxmMutationScope` 判断是单商品还是受控整批，不表示旧批量任务、无人值守或发布可用。
- 不要把历史 READY 当永久授权；启动真实保存前必须确认当次工作台或 `final-delivery-check` 仍显示新鲜门禁通过。
