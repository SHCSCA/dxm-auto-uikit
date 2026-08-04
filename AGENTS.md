# AGENTS.md

本仓库为中文项目，默认用中文沟通；命令、路径、代码标识符保留原文。

## 必读（按序）

1. **`docs/product/MVP-竖切-草稿箱批量只保存.md`** — **当前产品主迭代契约**（草稿箱多选批量只保存 / Path A / 双就绪）。
2. **`docs/product/CODEX-GOLD-工作指令-MVP批量只保存.md`** — 交给 Codex Gold 的执行指令与粘贴模板。
3. **`CLAUDE.md`** — 工程结构、命令、真实写入安全门禁、runner/L 阶梯；**安全红线永久有效**。其中「仅 claim_only + single_save 为唯一主路径」的**产品叙事已被 MVP 文档覆盖**；实现 bulk 时以 MVP 文档为准，但**不得放松**禁发布 / fail-closed / 证据要求。
4. 上游只读契约与金样（**禁止当第二生产代码仓**）：`D:\Desktop\py\DXM-TX`
   - `docs/01|02|03-*.md`、`docs/api/店小秘-*.md`
   - `data/capture/**`、`DXM-半托管工作台-可交互原型.html`

## 项目是什么

- 核心：**DXM 半托管自动化工作台**——真实可见浏览器操作店小秘；**只保存、不发布**。
- **当前主路径（MVP）**：采集箱（draft）多选 → 方案快照 → **`batch_draft_save` 循环只保存（先 Path A）** + HVD + 暂停/继续。
- **历史受控路径（代码仍保留）**：Stage A `claim_only`、Stage B `single_save`；**不是**本 MVP 的前置必经，也不能用其历史 READY 证据宣称批量已放行。
- 不是本地演示页，不是安全诊断工具；HTML 仿真不得冒充真实写入成功。

## 写入与就绪口径

| 口径 | 含义 |
|------|------|
| **安全红线** | 禁止发布类动作；真实写入须受控；不提交 Cookie/密钥 |
| **`MVP_READY`** | 草稿箱 ≥3 品 Path A 真批量只保存 + 三铁证 + HVD + 暂停继续（见 MVP 文档 §6.1） |
| **`PROD_READY`** | 原硬化门禁（portable 同 HEAD、新鲜 L2、ledger、两段式同品等）；**后置**，不挡 MVP 合入 |
| **历史 `READY` / `controlled_single_save_only`** | 只对记录中的 commit/包有效；**禁止扩大解释为批量** |

- `claim_only`、旧语义不清的 `batch_save`、无人值守、任何发布：**不得**在未完成对应 DoD 前对外宣称可用。
- 新 bulk 模式须在合约与测试中显式命名（推荐 `batch_draft_save`），并写清与单品 `single_save` 的证据边界。

## 检索约定

主检索工具为 ace-tool（`mcp__ace-tool__search_context`）。当 ace-tool 无法满足语义搜索需求时，使用 `mcp__fast-context__fast_context_search` 作为补充。

适合使用 fast-context 的场景：

- 用自然语言描述要找的逻辑，例如“部署流程”“事件处理”。
- 跨模块、跨层级的调用链路追踪。
- 中文语义搜索。

## 交付口径

- 源码包 **生产** 交付仍可跑：
  `scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop ...`
  读取 `final-delivery-check.json` 时不能只看 `ok`；必须同时读 `okScope`、`realDxmMutationScope`、`realDxmWriteReadiness`、`sourcePackageReadiness`。
- **本迭代验收优先 `MVP_READY` 清单**（MVP 文档 §6.1 / §11），不要用未达成的 `PROD_READY` 否定 MVP 功能完成。
- 不要把历史 READY 当永久授权；启动真实保存前确认当次会话与门禁仍有效。

## 实现偏好

- **优先扩展**现有 `execution/v1_runner.py`、`BrowserAgent*`、`batch_edit/*`、workbench 页面；禁止平行第三套执行引擎。
- 读路径：接口直读；写路径：UI 仿真；成功 = 回包 + 页面成功态 + 未发布证明。

<!-- CODEX-OBSIDIAN-PROTOCOL:START -->
## Obsidian 项目记忆

- `project_id`: `dxm-auto-uikit`
- 项目知识库入口：`C:\Users\wz\Documents\Obsidian Vault\20_Projects\dxm-auto-uikit\项目主页.md`
- 默认不自动检索 Vault。只有用户明确要求查知识库、历史记录或过往决策时，才运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\wz\Documents\Codex\obsidian-memory-system\scripts\get-context.ps1" -Project dxm-auto-uikit`；普通任务不得自动运行。
- Vault 默认只读；只有用户明确要求整理或更新笔记时才允许写入。
- 本文件和 `CLAUDE.md` 的 DXM **安全**写入门禁优先；**产品主路径**以 `docs/product/MVP-竖切-草稿箱批量只保存.md` 为准。事实状态以当前 Git、代码、运行、测试和交付证据为准。Vault 是历史上下文和可重建投影，冲突时标记旧笔记可能过期。
- 自动更新只能替换一对 `CODEX-KB-CURATOR` marker 之间的内容；marker 缺失、重复、嵌套或失衡时停止并报告。
- 不得修改 marker 外的人工内容，不得写入密钥、令牌、Cookie、完整原始对话或未筛选工具输出。
- 项目链接必须使用包含 `project_id` 的限定路径，禁止生成跨项目歧义裸链接。
<!-- CODEX-OBSIDIAN-PROTOCOL:END -->
