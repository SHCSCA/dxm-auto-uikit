> 由 OpenAI GPT（Codex）AI 生成/维护。

# CLAUDE.md

本文件是本仓库的薄工具适配：保留常用命令和必要安全边界。默认用中文沟通；共同规则见 [AGENTS.md](AGENTS.md)，不在此复制实现机制或历史验收记录。

## 工作目录与文档权威

- 当前授权 checkout 为 `G:\AI\dxm-auto-uikit`；操作前运行 `git rev-parse --show-toplevel`，不要在历史镜像编辑或验收。
- 只从 [docs/README.md](docs/README.md) 进入当前文档；[PROGRESS.md](PROGRESS.md) / [BLOCKED.md](BLOCKED.md) 的置顶事实决定当前成熟度，旧绿测与旧包不能覆盖。
- 唯一产品主合同：[docs/product/MVP-竖切-草稿箱批量只保存.md](docs/product/MVP-竖切-草稿箱批量只保存.md)。
- 实际结构：[当前运行时架构](docs/architecture/当前运行时架构.md)；目标态：[统一开发方案](docs/architecture/DXM-工作台与分区自动化统一开发方案.md)。目标态不是已实现清单。
- 操作与验收：[操作与验收手册](docs/runbook/操作与验收手册.md)；逐分区操作：[运营操作详细文档](docs/runbook/运营操作详细文档.md)。
- 上游 `D:\Desktop\py\DXM-TX` 永久只读；允许来源与唯一纯类目数据例外以 AGENTS.md 和 [上游事实合同](docs/integration/DXM-TX-上游事实合同.md) 为准，不读取或复制其它真实业务数据。

## 不可破坏的安全边界

- **每件商品无条件执行**视频、翻译、批发、半托管和 rollback preparation；缺一项即 `BLOCKED`，不能降级为可选能力。
- 完整产品成功路径固定为 **Path B**。当前完整生产链尚未放行；`claim_only` 已删除，`single_save` / Path A 的历史代码和证据不能授权批量 Path B。
- 只通过真实可见 UI 写入；SAVE 仅点击规范化文本精确等于“保存”的可见按钮。每次成功必须同时具备业务成功回包、页面成功态和独立未发布证明。
- 半托管资格不做预检，不主动调用 `verifyPopChoiceShop`。点击“编辑半托管信息”后被动观察原生门；SAVE1 与门的先后依据真实 network/page/ledger，不从提示 Modal 推断完成。
- 唯一含发布文字的允许动作是 Path B 中间转换 `SEMI_MANAGED_CONTINUE_TRANSITION`，用于进入冻结的 `editFromSmt`；最终发布、立即发布、保存并发布和移入待发布永久禁止。
- 真实动作前复核当前账号、浏览器会话、店铺、页面、商品、不可变 snapshot、队列、批准 lease 和 mutation ledger；动作参数不能替代仓储权威或活页面 JIT。
- 派发后断线、超时、重启或证据冲突必须 `UNKNOWN`、停批并人工对账，禁止自动重试。
- 唯一任务执行链为 `V1TaskRunner → BrowserAgent → DxmWorkflowAdapter → DxmLoginFlow`；不得新增拥有队列、任务状态迁移、HVD 或写派发权的第二 Runner/Runtime。
- `CategoryCatalog` 只提供版本化类目参考；当前同源可见页面的类目、Schema 和能力事实才是写前权威。诊断 inventory、只读弹窗或候选来源不等于完整 FILL、rollback、输入冻结或执行资格。
- 中文用于界面与映射，不能单独充当执行主键；自动写入自然语言必须英文，并在保存前逐字段读回。
- 不提交密码、Cookie、token、SQLite、会话、raw、真实业务样例或未脱敏日志。`data/`、`outputs/`、`output/` 是本机私有产物，不随 Git 交付。
- 工程验证通过不等于真实产品验收；不得用 mock、HTML、fallback、聚焦绿测、历史 clean commit 或旧 portable 拼接 READY。

## 常用命令

以下示例从仓库根目录执行；已有依赖使用项目环境，不用系统 Python 代替后端 venv。

启动检查与源码工作台：

```powershell
git rev-parse --show-toplevel
scripts\start-mvp.bat --check
scripts\start-mvp.bat
```

桌面开发入口为 `scripts\start-desktop.bat`。遇到 `DXM_SAME_DATA_RUNTIME`，回原窗口确认空闲后正常退出；不要自动接管或误杀旧实例。

修改后端时先指定相关测试，需要完整验收时再执行一次全量；纯文档同步不重跑后端测试。使用 Git 外的新数据目录，并在命令结束后恢复原配置：

```powershell
$testDataBefore = $env:DXM_DATA_DIR
Push-Location app\backend
try {
    $env:DXM_DATA_DIR = Join-Path $env:TEMP ("dxm-pytest-" + [guid]::NewGuid().ToString("N"))
    .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_task_start_guard.py -q
    # 完整验收时改为不指定测试文件的全量命令。
} finally {
    $env:DXM_DATA_DIR = $testDataBefore
    Pop-Location
}
```

前端标准构建包含 Node 测试、隔离 Chromium 检查、类型检查与 Vite 构建；桌面单测与打包分别执行：

```powershell
npm --prefix app/frontend run build
npm --prefix app/desktop test
npm --prefix app/desktop run build:portable
```

离线 L1 不访问店小秘；真实 L2 探针的授权与双目标证据要求见操作手册，不因构建命令自动获得授权：

```powershell
app\backend\.venv\Scripts\python.exe tools\probes\l1_selector_replay.py --output-dir data\l1_selector_replay
```

文档自检与交付检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\validate-mvp-docs.ps1 -SelfTest
git diff --check
scripts\final-delivery-check.bat -RequireCleanWorktree
```

可见桌面 QA 在用户已授权时直接带 `-AllowVisibleWindow`，不重复索取同一授权；省略参数产生的等待或跳过不能宣称完整验收。文档自检遇缺失上游原型不得伪造来源或跳过门禁。

## 定位与协作

- 装配与 API：`app/backend/src/main.py`；配置总线：`app/backend/src/core/config_bus.py`；统一脱敏日志：`app/backend/src/services/structured_logging.py`。
- 主执行与浏览器：`app/backend/src/execution/v1_runner.py`、`browser_agent_protocol.py`、`browser_agent_worker.py`、`browser_action_dispatch.py`、`dxm_adapter.py`、`dxm_login_flow.py`。
- 前端挂载入口：`app/frontend/src/App.tsx`；桌面实际入口：`app/desktop/src/main.cjs`，预加载：`app/desktop/src/preload.cjs`。先查实际 import/委托，未挂载重复组件不能作生产依据。
- 新开发遵守 AGENTS.md 的职责拆分、中文注释、异常日志及配置总线要求；不往历史巨型文件堆积新机制。
- 保存、授权或状态机改动按受影响合同定向回归；错误必须保留来源和失败语义，不靠修改期望、伪造成功或放宽门禁变绿。
- 推送前核对提交范围与敏感产物；源码、Git、构建 manifest、包哈希、运行实例和证据必须同源，未完成检查如实保持未完成。
