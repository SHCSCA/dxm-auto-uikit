> 由 OpenAI GPT（Codex）AI 生成/维护。

# DXM 文档导航

本目录只保留当前可执行合同、当前架构、上游事实摘录、操作手册和必要的原型 QA。版本计划、一次性任务书、旧 E2 清单、旧 L0 迁移计划和错误 runbook 已从当前文档面移除。

## 必读顺序

1. [完整商品编辑：草稿箱批量只保存](product/MVP-竖切-草稿箱批量只保存.md) — **唯一产品主合同**；每品五项 ALWAYS_ON、Path B 双阶段保存、draft ≥3、最终零发布。
2. [PROGRESS](../PROGRESS.md) / [BLOCKED](../BLOCKED.md) — 当前代码、测试、包、真机和未关闭门禁；决定能否执行。
3. [当前运行时架构](architecture/当前运行时架构.md) — 当前实际路由、Reader、快照、Runner、BrowserAgent、证据和 0.3.0 成熟度。
4. [工作台与分区自动化统一开发方案](architecture/DXM-工作台与分区自动化统一开发方案.md) — 目标态与 R0–R6 路线；单店铺、11 分区、一个串行 Runner、完整 Path B 和分区回执，不代表当前已实现。
5. [运营操作详细文档](runbook/运营操作详细文档.md) — 店小秘逐分区真实操作 source；只在统一方案和主合同约束下使用，历史坐标/等待/Path A 不得升级为执行合同。
6. [DXM-TX 上游事实合同](integration/DXM-TX-上游事实合同.md) — 已脱敏迁入的上游接口/页面/原型事实、来源 hash 和允许用途。
7. [DXM-TX 类目节点与目录合同](integration/DXM-TX-类目节点与目录合同.md) — 动态任意深度类目、叶子身份、版本化 catalog、冲突和漂移。
8. [操作与验收手册](runbook/操作与验收手册.md) — 当前真实命令、UI 流程、`DXM_SAME_DATA_RUNTIME` 与验收边界。

任何文档出现冲突时，按“零发布与真实证据 → 当前代码/测试/运行事实 → MVP 合同 → 原型体验 → 功能完整 → 速度”裁决。

## 当前产品与配置

- [完整产品唯一主合同](product/MVP-竖切-草稿箱批量只保存.md)：五项必经能力、Path B、`MVP_READY` / `PROD_READY` 分离、三铁证、UNKNOWN、HVD 与人工验收。
- [普货方案配置与执行架构](product/普货方案配置与执行架构.md)：单目标类目、店铺隔离、动态中文 10 区、模板优先补差、复杂控件与 snapshot。
- [Codex Gold 指针](product/CODEX-GOLD-工作指令-MVP批量只保存.md)：指向唯一主合同并保留 E0–E4 顺序；不得复制第二套合同或单独作为完成状态。

## 当前工程

- [当前运行时架构](architecture/当前运行时架构.md)：source-of-code 文档；明确 0.3.0 哪些已接主链、哪些产品必需能力仍是生产阻断。
- [工作台与分区自动化统一开发方案](architecture/DXM-工作台与分区自动化统一开发方案.md)：当前 source-of-target v1.1.2；把真实 11 分区运营流程落成单 Runner 的 Module/Interface、工作台、合同迁移、R0–R6 和验收门禁。`architecture/_archive` 中的 v1.0.0/v1.1.1 只供历史核对，不得作为当前实现指令。
- [DXM-TX 上游事实合同](integration/DXM-TX-上游事实合同.md)：source-of-upstream 文档；DXM-TX 保持只读。
- [DXM-TX 类目节点与目录合同](integration/DXM-TX-类目节点与目录合同.md)：唯一获授权的数据迁移是纯类目结构；其它 `data/**` 和真实样例不迁入。
- [CHANGELOG](../CHANGELOG.md)：已发布历史与 0.3.0 Unreleased；未接生产的必需能力不得写成已交付。

## 用户与操作

- [运营操作详细文档](runbook/运营操作详细文档.md)：逐分区真实操作事实、必经能力、Path B 双阶段与 fail-closed 批量循环；不是独立安全授权源。
- [操作与验收手册](runbook/操作与验收手册.md)：源码/桌面启动、登录、Reader、方案、preview/freeze、真实保存授权与验证命令。
- [免安装桌面版](user/免安装桌面版.md)：当前没有 0.3.0 portable，历史 0.2.3 不能代表当前源码。
- [项目 README](../README.md)：项目入口、快速启动、文档和安全边界。

## AI 与协作

- [AGENTS.md](../AGENTS.md)：所有 agent 的共同规则、只读上游和证据边界。
- [CLAUDE.md](../CLAUDE.md)：薄工具适配，命令与不可破坏不变量。

## 原型与原型 QA

`prototypes/dxm-mission-cockpit/**` 只属于其原型资产和历史视觉 QA。它们不是当前 runtime、API、真实保存或 READY 证据。指定根原型仍在只读上游 `D:\Desktop\py\DXM-TX\DXM-半托管工作台-可交互原型.html`；本仓只消费主合同固定的 IA/视觉约束。

## 已移除的滞后文档

以下内容已由当前文档吸收或被事实推翻，不再作为可解析入口：

- v0.1 数据库/API 草案；
- 旧 E2 关闭清单、E2→E3 开工记录和 L0 策略 B 计划；
- 0.1.4 portable/操作日志一次性任务书；
- 2026-08-19 至 2026-08-21 的五份重叠普货方案设计；
- 将不存在路由、轮询写成 WebSocket/SSE、并把实验 executor 写成生产链的旧运行流程详解；
- 已实现且无当前入站引用的旧 draft selection 单页规格；
- 无来源、无当前约束力的项目评估报告。
- `product/用户交付使用说明-20260526.md`
- `product/免安装版快速使用说明-20260615.md`

不是当前真相、可执行任务或有效链接。

这些文档中的仍有效信息已合并到本页列出的主合同、配置架构、运行架构、上游事实或 runbook。不要从本地残留副本恢复第二套叙事。

## 当前发布口径

- 当前 backend/frontend/desktop 与根 package manifest 均为 0.3.0。
- 当前没有 0.3.0 portable；本地历史包最新到 0.2.3。
- 视频、翻译、批发、半托管和回滚是完整产品必需能力；当前未接生产，所以是发布阻断而非可选扩展。
- 当前工作树完整 backend L0 已通过 `2344 passed / 0 skipped`；同源 package smoke、0.3.0 portable 和真实三商品三铁证尚未组成放行证据。
- 所以当前只能是 `E3_OPEN / BLOCKED`；禁止宣称 `MVP_READY` 或 `PROD_READY`。
