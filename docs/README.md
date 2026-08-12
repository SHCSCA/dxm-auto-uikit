# DXM 文档导航

更新时间：2026-07-28

这里区分“当前真相”与“历史快照”。日期较早的验收记录和计划保留用于审计，但不得覆盖当前代码、运行和打包证据。

## 当前真相（先读）

### 主迭代（2026-07-28 · 优先）

- [MVP 竖切：草稿箱批量只保存](product/MVP-竖切-草稿箱批量只保存.md)：**产品主路径**、Path A 批量、`MVP_READY` / `PROD_READY` 双就绪、Epic DoD。
- [Codex Gold 工作指令](product/CODEX-GOLD-工作指令-MVP批量只保存.md)：Gold 模式粘贴模板、红线、按 Epic 短指令。
- 上游只读（非本仓代码）：`D:\Desktop\py\DXM-TX` 的 `docs/`、`data/capture/`、可交互原型。

### 工程与安全（当前可解析）

- [项目 README](../README.md)：启动方式；其中生产 `BLOCKED`/两段式结论与 **MVP 主路径**并存——实现 bulk 以 MVP 文档为准，安全红线以 CLAUDE/门禁为准。
- [AGENTS.md](../AGENTS.md)：AI 必读顺序与就绪口径。
- [CLAUDE.md](../CLAUDE.md)：命令、runner、L 阶梯、禁发布。
- [SDD progress](../.superpowers/sdd/progress.md)：仓库内仍可解析的实施状态；与 MVP 主合同冲突时，以当前代码/测试事实和 MVP 零发布边界为准。

以下旧工程文档属于本工作树既有删除，不恢复、不再作为索引指针：`product/DXM-Agent-Console-当前开发状态与后续计划-20260717.md`、`tech/当前运行时架构-20260717.md`、`product/交付工作台API.md`、`product/店小秘半托管执行器可交付化回归矩阵.md`、`product/L2只读Probe门禁.md`、`superpowers/plans/2026-07-13-dxm-two-stage-runtime-truth.md`。若未来恢复，必须按当前 HEAD 与 MVP 主合同重新审阅后再建立链接。

## 产品与操作参考（历史路径，非指针）

`product/店小秘速卖通半托管自动化执行器_PRD_V1.0.md`、`tech/全量字段矩阵.md`、`product/用户交付使用说明-20260526.md`、`product/免安装版快速使用说明-20260615.md` 只保留文件名用于历史审计；无论历史文件在某个检出中是否仍然存在，都不是当前真相、可执行任务或有效链接。旧操作说明对应旧包和旧界面；若以后重新启用，必须先按当前代码、README、MVP 主合同与现场证据审阅，再显式建立新指针。

## 历史快照

- `product/最终交付验收记录-*.md`：各日期的源码/portable/现场证据，只对记录中的 commit、包 hash 和范围有效。
- `product/DXM-Agent-Console-当前开发状态与后续计划-20260706.md` 与 `...-20260709.md`：当时的真实任务和问题快照。
- `tech/技术实现图.md`、`api/数据库表结构与API草案.md`：v0.1 早期设计，不是当前运行时或数据库契约。
- `superpowers/plans/2026-06-*.md`：已归档的历史实施计划。

## 文档判定规则

发生冲突时，可信度顺序为：当前代码与测试/运行证据 → 同 HEAD 构建与现场证据 → 当前状态/API/架构文档 → 历史验收和旧计划。没有同一证据链时一律保持 `BLOCKED`。
