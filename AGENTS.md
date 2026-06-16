# AGENTS.md

本仓库为中文项目，默认用中文沟通；命令、路径、代码标识符保留原文。

## 必读

- 先读 `CLAUDE.md`。它是当前项目级 AI 指引的权威来源，包含真实 DXM 写入门禁、状态机、安全边界和常用命令。
- 本项目核心是 **DXM 半托管自动化工作台**，不是本地演示页，也不是安全诊断工具。
- 当前可交付真实写入范围仅为 `controlled_single_save_only`：单店、单商品、人工批准、只保存、不发布。
- `claim_only`、`batch_save`、批量、无人值守和任何发布动作均未放行；不能复用 `single_save` 证据扩大解释。

## 检索约定

主检索工具为 ace-tool（`mcp__ace-tool__search_context`）。当 ace-tool 无法满足语义搜索需求时，使用 `mcp__fast-context__fast_context_search` 作为补充。

适合使用 fast-context 的场景：

- 用自然语言描述要找的逻辑，例如“部署流程”“事件处理”。
- 跨模块、跨层级的调用链路追踪。
- 中文语义搜索。

## 交付口径

- 源码包交付前必须运行 clean worktree 验收：`scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY`。
- 读取 `final-delivery-check.json` 时不能只看 `ok`；必须同时读取 `okScope`、`realDxmMutationScope`、`realDxmWriteReadiness` 和 `sourcePackageReadiness`。
- `READY` 只表示受控单商品只保存路径具备当前有效证据，不表示批量、无人值守、认领或发布可用。
