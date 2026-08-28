> 由 OpenAI GPT（Codex）AI 生成/维护。

# dxm-auto-uikit

DXM 完整商品编辑工作台：从店小秘真实 draft 列表选择商品，按冻结方案在真实可见浏览器中逐件完成普通编辑、视频、批发、翻译、半托管双阶段与安全恢复，只保存草稿，不发布，最终发布永久禁止。

## 当前状态

**0.3.0 开发中，`E3_OPEN / BLOCKED`。不是 `MVP_READY`，不是 `PROD_READY`。**

- backend、frontend、desktop 与根 `package.json` 均为 `0.3.0`；源码 manifest 版本已统一，但尚无同源 0.3.0 portable。
- 当前没有 `DXM-Agent-Console-Portable-0.3.0.exe`；本地最新历史 portable 为 `0.2.3`，不能代表当前源码。
- Reader、方案、快照、Path A Runner、BrowserAgent 和四键已有大量代码；当前工作树的完整 backend L0 已达到 `2344 passed / 0 skipped`，但固定提交、同源 portable 与真实三商品证据尚未形成一组放行证据。
- 视频、翻译、批发、半托管和回滚是每件商品无条件执行的必需能力；当前生产接线未闭合，因此它们是产品放行阻断，不能写成可选扩展或已完成功能。
- 完整产品成功路径是 Path B。点击“编辑半托管信息”后由店小秘执行原生半托管门，本系统不做资格预检；精确中间“继续发布”仅允许作为进入 `editFromSmt` 的受控转换，最终发布仍永久禁止。

最新工程事实见 [PROGRESS](PROGRESS.md)，未关闭门禁见 [BLOCKED](BLOCKED.md)。

## 产品主路径

```text
真实可见浏览器登录
  → 只读读取当前账号店铺
  → pageList(dxmState=draft) 分页
  → 人工选择 draft ≥3
  → 动态类目目录选择无冲突目标叶子
  → 选择 local_plan_template + dxm_template_ref
  → preview / freeze 五项 ALWAYS_ON 的不可变 plan_snapshot
  → 人工批准 batch_draft_save
  → Runner 串行逐件：preimage → 普通编辑 → 视频 → 批发 → 翻译
  → 主保存意图 Modal → 编辑半托管信息/店小秘原生门
  → 按真实事件闭合主编辑 SAVE（不预设与原生门先后）
  → 必要的受控中间转换 → editFromSmt → 半托管保存
  → 两次保存分别具备：回包 + 页面成功态 + 独立未发布证明
  → UNKNOWN 停批且不自动重试
```

读路径优先使用已登录会话内的受审阅接口；写路径只通过真实可见 UI。中文用于产品界面和字段映射，自动写入的自然语言内容必须英文并在保存前逐字段读回校验。

## 启动

权威 checkout：

```text
D:\Desktop\py\dxm-auto-uikit
```

先检查，再启动：

```bat
cd /d D:\Desktop\py\dxm-auto-uikit
scripts\start-mvp.bat --check
scripts\start-mvp.bat
```

桌面开发入口：

```bat
scripts\start-desktop.bat
```

若出现 `DXM_SAME_DATA_RUNTIME`，说明旧实例仍持有同一数据目录。回到原窗口确认没有真实任务后正常退出；不要让新实例自动接管或误杀旧进程。详见 [操作与验收手册](docs/runbook/操作与验收手册.md)。

## 文档入口

只从 [docs/README.md](docs/README.md) 进入当前文档。

- [MVP 唯一主合同](docs/product/MVP-竖切-草稿箱批量只保存.md)
- [普货方案配置与执行架构](docs/product/普货方案配置与执行架构.md)
- [当前运行时架构](docs/architecture/当前运行时架构.md)
- [工作台与分区自动化统一开发方案](docs/architecture/DXM-工作台与分区自动化统一开发方案.md)
- [DXM-TX 上游事实合同](docs/integration/DXM-TX-上游事实合同.md)
- [DXM-TX 类目节点与目录合同](docs/integration/DXM-TX-类目节点与目录合同.md)
- [运营操作详细文档](docs/runbook/运营操作详细文档.md)
- [操作与验收手册](docs/runbook/操作与验收手册.md)
- [免安装桌面版说明](docs/user/免安装桌面版.md)

DXM-TX 保持只读。上游文档按来源 hash 和允许用途提炼；经明确授权，只把 `data/capture/categories` 的纯类目结构规范化到 `resources/dxm/category-catalog`。Cookie、sessions、raw 业务抓包、真实账号/店铺/商品/模板和原型 mock 仍不迁移。

## 代码结构

```text
app/backend/    FastAPI、SQLite、Reader、方案/快照、Runner、BrowserAgent、安全与证据
app/frontend/   React 工作台、七项导航、方案编辑、批次控制与结果
app/desktop/    Electron 桌面壳、单实例/数据目录、构建身份
scripts/        启动、文档、QA、package 与交付门禁
docs/           当前合同、架构、上游事实与 runbook
prototypes/     原型与原型 QA；不是运行事实
data/           本机运行数据；敏感且不得提交
outputs/        构建/验收产物；必须核对来源身份
```

## 开发验证

文档：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\validate-mvp-docs.ps1 -SelfTest
git diff --check
```

Backend 完整门禁：

```powershell
cd app\backend
$env:DXM_DATA_DIR = Join-Path $env:TEMP ("dxm-pytest-" + [guid]::NewGuid().ToString("N"))
.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q -ra
```

Frontend 标准构建：

```powershell
cd app\frontend
npm run build
```

Desktop：

```powershell
cd app\desktop
npm test
```

交付自检：

```bat
scripts\final-delivery-check.bat -RequireCleanWorktree
```

聚焦测试、单独 Vite build、旧 clean commit、历史 portable 或 HTML 演示都不能替代当前完整门禁与真实人工验收。

## 永久安全边界

- 禁止最终发布、立即发布、保存并发布、保存并移入待发布和任何 release/online 意图。中间“继续发布”只有在 Path B 的 `SEMI_MANAGED_CONTINUE_TRANSITION` 精确合同下允许。
- 真实写入前必须绑定当前账号、会话、店铺、页面、商品、快照、审批、lease、队列和 mutation ledger。
- 保存派发后证据不确定必须进入 `UNKNOWN` 并停止，不得自动重试。
- 中文标签不能单独作为执行主键；隐藏字段、额外匹配或 Schema 漂移必须在写入前拒绝。
- 不提交账号密码、Cookie、token、真实抓包、真实业务样例、SQLite、会话或未脱敏日志。
- 不用 mock/fallback/原型/旧 `claim_only` 或 `single_save` 证据宣称批量已放行。
- 不从旧 C: 镜像、旧后端、旧包或不同数据目录拼接 READY 证据。

## 项目判断

视频、翻译、批发、半托管和回滚不是新增装饰，而是完整商品编辑产品的必需 Module。当前核心工作是把它们接入同一条深链并收口：

1. Reader 与上游私有接口形成一个版本化、可漂移检测的 Read Contract；
2. 方案 preview/freeze 到 Runner 只消费同一份不可变 execution payload；
3. 视频/批发/翻译/rollback preparation 形成每品一致的 ContentPreparation；
4. Path B 两次 SAVE/VERIFY/三铁证/UNKNOWN 形成 Canonical Save Receipt。

在这些链和当前 package identity 闭合前，应停止把配置面板或 executor 数量当作版本进度，也不得用 Path A canary 替代完整产品验收。
