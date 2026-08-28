> 由 OpenAI GPT（Codex）AI 生成/维护。

# AGENTS.md

本仓库默认用中文沟通；命令、路径和代码标识符保留原文。

## 必读（按序）

1. `docs/README.md` — 唯一文档导航与当前/历史边界。
2. `docs/product/MVP-竖切-草稿箱批量只保存.md` — **唯一完整产品主合同**；固定每品五项 ALWAYS_ON 与 Path B 双阶段只保存。
3. `PROGRESS.md` / `BLOCKED.md` — 当前证据和活跃阻断；旧完成记录不能覆盖置顶事实。
4. `docs/architecture/当前运行时架构.md` — 当前实际代码、路由和能力成熟度。
5. `docs/architecture/DXM-工作台与分区自动化统一开发方案.md` — 目标态、单 Runner、11 分区、Path B 与 R0–R6；不代表当前已实现。
6. `docs/runbook/运营操作详细文档.md` / `操作与验收手册.md` — 逐分区真实操作与当前验收命令；只能在主合同和统一方案约束下使用。
7. `docs/integration/DXM-TX-上游事实合同.md` / `DXM-TX-类目节点与目录合同.md` — 已迁入且脱敏的上游事实和版本化类目目录。
8. `CLAUDE.md` — 命令与安全不变量；不是第二套产品合同。

Gold 指令位于 `docs/product/CODEX-GOLD-工作指令-MVP批量只保存.md`，只补充 Epic 边界，不单独证明当前状态。

## 权威仓与上游

- 唯一开发 checkout：`D:\Desktop\py\dxm-auto-uikit`。先运行 `git rev-parse --show-toplevel`，不要在 C: 镜像编辑或验收。
- 上游 `D:\Desktop\py\DXM-TX` 永久只读，只是产品观察与接口证据源，不是第二生产代码仓。
- 默认只读其项目自有文档、`contracts/dxm/**` 元数据和根原型结构。2026-08-25 唯一数据例外是用 `scripts/sync-dxm-category-catalog.ps1` 读取 `data/capture/categories` 并输出脱敏 catalog；其它 `data/**`、Cookie、storage state、raw 抓包、真实店铺/商品/模板/联系人样例仍禁止读取或复制。
- 上游 `PASSIVE_ONLY`、`SAMPLE_ONLY`、目录 `ready=true` 或结构候选都不等于主动调用、写入、保存或 READY 授权。
- 上游事实有变化时先标 `STALE_REVIEW_REQUIRED`，做脱敏差分审阅；不得自动覆盖当前合同。

## 项目与当前产品

- 产品：真实可见浏览器中的店小秘草稿箱批量只保存工作台。
- 当前产品主链：同源登录/Reader → draft ≥3 → 动态目标叶子 → 完整方案 + 只读模板 → 五项 ALWAYS_ON snapshot → 普通编辑/视频/批发/翻译 → 主保存意图 Modal → 点击“编辑半托管信息”触发店小秘原生门 → 按真实事件闭合 SAVE1 → `editFromSmt` → SAVE2 → 两次三铁证。
- `claim_only` / `single_save` 是历史兼容路径，不是 MVP 前置，也不能提供批量授权。
- 视频、翻译、批发、半托管和 rollback preparation 是每件商品无条件执行的产品必需能力；当前未接生产意味着 `BLOCKED`，不意味着可选。
- Path B 是完整成功路径。中间“继续发布”仅允许以 `SEMI_MANAGED_CONTINUE_TRANSITION` 的精确上下文自动化；最终发布、立即发布、保存并发布和移入待发布永久禁止。
- 半托管资格不做本地/接口预检；`verifyPopChoiceShop` 只能作为点击“编辑半托管信息”后店小秘自身请求的被动证据。提示 Modal 不能证明 SAVE1 已完成；SAVE1 与原生门先后以 network/page/ledger 为准。

## 永久安全门禁

- 读接口、写 UI；保存接口只能作为证据观察，不得直调为主实现。
- SAVE 只点击规范化文本精确等于“保存”的可见按钮。含发布文字的唯一例外是精确 Path B 中间转换；任何最终发布意图立即拒绝。
- 成功三缺一不可：业务成功回包 + 页面成功态 + 独立未发布证明。
- 真实动作前实时复核账号、会话、店铺、页面、商品、快照、队列、批准 lease 与 ledger。
- 派发后断线、超时、重启或证据冲突必须 `UNKNOWN`、停批、人工对账，禁止自动重试。
- 中文用于界面/字段映射；中文标签不得单独作为执行主键。自动写入自然语言必须英文并在保存前逐字段读回。
- 不用 HTML/mock/fallback/旧包/历史 clean commit/单独绿测拼接 READY。
- 不提交密码、Cookie、token、SQLite、会话、raw、真实业务样例或未脱敏日志。

## 实现与文档规则

- 优先深化现有 Reader、CategoryCatalog、`PlanSnapshotCompiler`、`V1TaskRunner`、BrowserAgent、ActionResult 与 ledger；不得新增或保留第二个拥有队列、任务状态迁移、HVD 或写派发权的 Runner/Runtime。
- 配置控件存在不等于 executor 可用；状态枚举、空实现、未挂载组件和聚焦测试必须标为“必需能力未接生产”，不能标为可选扩展或已完成。
- 文档只从 `docs/README.md` 建立当前入口。新文档首个非空行标注“由 OpenAI GPT（Codex）AI 生成/维护”。
- 被替代的一次性任务书、旧版本计划和假流程应删除；有价值原则合并到现行文档，不恢复第二套叙事。
- 每次文档变更运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\validate-mvp-docs.ps1 -SelfTest
git diff --check
```

## 检索约定

主检索工具为 ace-tool（`mcp__ace-tool__search_context`）。当 ace-tool 无法满足语义搜索需求时，使用 `mcp__fast-context__fast_context_search` 作为补充。命令行文本/文件检索优先 `rg` / `rg --files`。

<!-- CODEX-OBSIDIAN-PROTOCOL:START -->
## Obsidian 项目记忆

- `project_id`: `dxm-auto-uikit`
- 项目知识库入口：`C:\Users\wz\Documents\Obsidian Vault\20_Projects\dxm-auto-uikit\项目主页.md`
- 默认不自动检索 Vault。只有用户明确要求查知识库、历史记录或过往决策时，才运行 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Users\wz\Documents\Codex\obsidian-memory-system\scripts\get-context.ps1" -Project dxm-auto-uikit`；普通任务不得自动运行。
- Vault 默认只读；只有用户明确要求整理或更新笔记时才允许写入。
- 本文件和 `CLAUDE.md` 的 DXM 安全门禁优先；产品主路径以 `docs/product/MVP-竖切-草稿箱批量只保存.md` 为准。事实状态以当前 Git、代码、运行、测试和交付证据为准。Vault 冲突时标记旧笔记可能过期。
- 自动更新只能替换一对 `CODEX-KB-CURATOR` marker 之间的内容；marker 缺失、重复、嵌套或失衡时停止并报告。
- 不得修改 marker 外的人工内容，不得写入密钥、令牌、Cookie、完整原始对话或未筛选工具输出。
- 项目链接必须使用包含 `project_id` 的限定路径，禁止生成跨项目歧义裸链接。
<!-- CODEX-OBSIDIAN-PROTOCOL:END -->
