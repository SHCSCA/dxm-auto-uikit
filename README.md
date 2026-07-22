# dxm-auto-uikit

DXM 半托管自动化工作台：用真实可见浏览器处理店小秘商品箱中的现有商品，受控完成“选择商品 → 编辑 → 只保存不发布”。

## 当前状态（2026-07-22）

认领环节及相关页面、任务模式、API、运行时状态和验收 schema 已移除。真实入口从店小秘商品箱开始：`single_save` 冻结一个现有商品并受控只保存；`controlled_edit_batch` 冻结当前可见商品范围，一次批准后严格串行逐商品只保存。旧 `batch_save`、无人值守、发布、保存并发布和移入待发布保持关闭。

**当前生产交付状态为 `BLOCKED`。** 当前变更尚需在同一干净 Git HEAD 上完成全量测试、构建全新 portable、启动该 portable、运行新鲜商品箱 L2，并取得真实保存成功与独立 `published=false` 证明。源码测试、历史金丝雀或旧 EXE 都不能替代该证据链。

2026-07-04 的 portable 与 `READY` 记录是历史构建快照，不是当前分支的放行结论。当前事实入口见 [文档导航](docs/README.md) 和 [2026-07-17 状态说明](docs/product/DXM-Agent-Console-当前开发状态与后续计划-20260717.md)。

真实用户主路径是：登录店小秘；进入商品箱；选择已验证商品；确认既有模板；人工批准单次保存或受控整批；最后核对保存回包、证据路径和独立未发布证明。任一身份漂移、批准失效、页面不匹配或动作结果不确定，都失败关闭并转人工复核。

## 真实用户快速开始

> 本节保留源码启动方式和历史包路径用于追溯。旧包不包含当前删除结果，不得作为本版本交付包；必须从合并后的同一 HEAD 构建全新 portable 后再验收。

### 推荐入口：DXM Agent Console 桌面版

交付用户优先使用桌面版，不需要分别打开后端和前端两个控制台窗口。

本次交付使用从当前合并后 Git HEAD 全新构建并完成 smoke 的免安装 EXE：

```text
D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

最终 SHA-256、构建 Git HEAD 和 smoke 结果以本次交付记录为准；旧包路径、旧哈希和旧验收结论不得作为当前版本证据。

仓库内也保留同源构建产物：

```text
outputs\desktop-build\win-unpacked\DXM-Agent-Console.exe
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

目录版必须保留整个文件夹和 `resources` 目录，不能只复制 exe 文件。portable 首次启动会解包 Electron 与 Python 运行时，`%TEMP%` 所在磁盘建议至少保留 1GB 可用空间；空间不足时会出现启动即退出、没有日志的现象。

源码开发态可用下面命令启动桌面壳：

```bat
scripts\start-desktop.bat
```

桌面版会隐藏启动本机后端，并在 Agent 控制台窗口内加载前端页面。桌面运行日志位于：

```text
%APPDATA%\DXM Agent Console\data\desktop-main.log
%APPDATA%\DXM Agent Console\data\backend.log
```

常见展开路径是 `C:\Users\<用户名>\AppData\Roaming\DXM Agent Console\data\desktop-main.log`。

打包验收命令：

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1
```

该命令会启动 `outputs\desktop-build\win-unpacked\DXM-Agent-Console.exe`，检查 `desktop-main.log` 中是否出现 `Starting backend` 和 `Loaded frontend`。

### 源码备用入口：单窗口启动器

1. 在 Windows PowerShell 或 CMD 中进入项目根目录。

```bat
cd /d D:\Desktop\py\dxm-auto-uikit
scripts\start-mvp.bat --check
scripts\start-mvp.bat
```

2. 保留启动器窗口。启动器会托管后端和前端，并把后端/前端新日志实时转发到这一个窗口；关闭该窗口或按 `Ctrl+C` 会停止服务。
3. 等启动器显示 `STARTED_OK` 后，使用自动打开的工作台页面；如果 5173 被占用，启动器会选择附近空闲端口并在日志中写出实际 URL。
4. 进入工作台的“店小秘登录”，点击“打开真实登录页”。系统会打开可见的独立店小秘浏览器窗口，用户可直接输入验证码、查看错误并手动调整；桌面版可勾选“记住账号密码”，账号密码只做本机加密保存。
5. 回到“模板中心”，按店小秘编辑页分区补齐：店铺与任务基础、类目与标题、SKU/价格/库存、价格策略、图片与素材、包装物流、合规/海关、半托管、店小秘引用模板。保存时可选“仅本次任务使用”或“保存为店铺模板”。
6. 进入“商品箱编辑保存”，选择真实店铺和商品箱中已验证的现有商品；系统会冻结商品、店铺、来源、目标和证据快照。
7. 只有商品箱只读检查、配置检查和人工批准全部通过后，才能启动单商品只保存；受控整批需先冻结当前可见范围并一次批准，随后严格串行执行。
8. 进入“真实浏览器”观察真实浏览器会话状态、页面左上角黑色中文任务进度窗、网络响应和实时日志。真实店小秘浏览器是独立窗口；控制台默认只显示主操作和关键日志，账号密码、会话管理、高级浏览器控制、运行维护和自动操作轨迹按需展开。控制台不把本地截图渲染成实时画面，截图只作为报告证据路径保存。
9. 任务完成后，到“结果与问题”核对保存响应、未发布证明、截图和结构化报告；如有失败或阻断，也在“结果与问题”查看原因和下一步。验收结论必须是保存成功且 `published=false`。

不要用开发自检批次代替真实保存结果；真实用户只按上面的单商品只保存路径执行。

## 当前已完成

### 文档层
- `docs/product/店小秘自动刊登助手-PRD.md`
- `docs/product/店小秘真实流程补充-2026-04-20.md`
- `docs/tech/全量字段矩阵.md`
- `docs/tech/技术实现图.md`
- `docs/api/数据库表结构与API草案.md`
- `docs/research/Browser-Use-vs-Playwright-选型对比与技术路线建议.md`
- `.hermes/plans/2026-04-20_133500-dxm-auto-uikit-mvp-implementation-plan.md`

### 工程层
- `app/backend/`：FastAPI + SQLite + WebSocket + 真实浏览器任务执行引擎与受控门禁
- `app/frontend/`：React + Vite 控制台
- `app/desktop/`：Electron 桌面壳
- `data/`：数据库、证据、截图、日志目录
- `scripts/`：启动脚本

---

## 当前产品能力

### 已实现：DXM 半托管自动化工作台
- 店铺与商品队列展示
- 编辑页配置与店铺模板管理
- 商品导入
- 商品箱只读检查 / 单商品只保存 / 受控整批编辑保存
- Task/Job 状态流转
- WebSocket 实时执行事件
- 真实浏览器页、执行浏览器会话状态、页面内中文进度 HUD、折叠式页面内操控和日志中心
- 证据面板
- 结果与问题页（真实失败按问题卡展示，技术诊断默认折叠）
- Playwright 主引擎骨架
- POP 保存待发布链路（真实单商品只保存已具备受控证据；批量、无人值守和发布仍不放行）

### 当前源码是“商品箱受控保存版”
说明：
- 右侧实时执行区已经能看到任务状态、步骤流、日志和证据
- 工作台会显示真实只读检查、人工确认、证据等级和真实保存阻断原因
- 前置条件不满足时，单商品保存和受控整批会被后端与前端双重阻断
- `single_save` 使用不可变商品箱快照；`controlled_edit_batch` 使用冻结范围、全局单并发和逐商品即时授权
- 历史可用状态不是永久授权；每次真实启动前都必须看当前工作台状态，源码包交付前必须重新运行最新 `final-delivery-check`

---

## 启动方式

当前仓库默认面向 Windows 本地交付；推荐先运行检查模式，确认 Python、npm、后端依赖和前端依赖都就绪。

前置条件：
- Windows 10/11 + PowerShell
- Python 3.11+
- Node.js/npm
- Git
- 首次安装前端依赖时需要可访问 npm registry 的网络

### 0. DXM Agent Console 桌面版

推荐给真实用户的入口是桌面版。

本次交付使用从当前合并后 Git HEAD 全新构建并完成 smoke 的免安装 EXE：

```bat
D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

最终 SHA-256、构建 Git HEAD 和 smoke 结果以本次交付记录为准；不要复用历史包哈希。

仓库内同源构建产物：

```bat
outputs\desktop-build\win-unpacked\DXM-Agent-Console.exe
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

目录版必须保留整个文件夹和 `resources` 目录。portable 需要 `%TEMP%` 所在磁盘至少约 1GB 可用空间用于解包；空间不足时请清理旧的 `%TEMP%\ns*.tmp` 解包残留。

源码开发态启动桌面版：

```bat
scripts\start-desktop.bat
```

packaged smoke 验收：

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1
```

桌面版日志：

```bat
%APPDATA%\DXM Agent Console\data\desktop-main.log
%APPDATA%\DXM Agent Console\data\backend.log
```

常见展开路径：`C:\Users\<用户名>\AppData\Roaming\DXM Agent Console\data\desktop-main.log`。

### 1. Windows 单窗口启动器（源码备用）

```bat
scripts\start-mvp.bat --check
```

检查通过后再启动完整工作台：

```bat
scripts\start-mvp.bat
```

启动后只保留当前启动器控制台窗口。后端和前端会作为同一启动器窗口托管的子进程运行，后端/前端新日志会带 `[backend]`、`[frontend]` 前缀实时显示在这个窗口里；完整日志仍保存在 `data\backend.log` 和 `data\frontend.log`。只有后端 `/health` 与前端页面健康检查都通过时，才会自动打开前端页面。若 5173 被占用，启动器会自动使用附近空闲端口；若启动日志出现 warning，脚本不会自动开页，请先查看日志并等健康检查恢复后再手动访问启动器打印的前端 URL。

启动器会自动接管 8000 端口上由本项目旧版本启动的 `uvicorn src.main:app` 后端，以避免继续连接旧代码；若 8000 被未知进程占用则会失败退出。不要在真实任务正在运行时重复启动新的 `start-mvp.bat`，否则会中断旧后端会话；先在工作台确认没有 running/paused 任务，或先正常关闭旧启动器窗口。

- 后端：`http://127.0.0.1:8000`
- 前端：默认 `http://127.0.0.1:5173`，端口占用时以启动器输出为准
- 日志：`data\start-mvp.log`、`data\backend.log`、`data\frontend.log`

停止方式：关闭当前启动器窗口，或在启动器窗口按 `Ctrl+C`。脚本退出时会尽力停止后端和前端子进程树。

登录凭据边界：桌面版可勾选“记住账号密码”，凭据保存到 `%APPDATA%\DXM Agent Console\data` 下的本机加密保存文件，并由 Electron `safeStorage` 加密；取消勾选或点击“清除已记住账号”会清除本机保存的密码。凭据不写入编辑页配置、不上传云端。源码浏览器模式没有桌面安全存储时不会保存密码。

### 2. 类 Unix / Git Bash 启动后端（开发备用）
```bash
bash scripts/start-backend.sh
```

后端地址：
- `http://127.0.0.1:8000`

### 3. 类 Unix / Git Bash 启动前端（开发备用）
```bash
bash scripts/start-frontend.sh
```

前端地址：
- `http://127.0.0.1:5173`

### 4. 类 Unix / Git Bash 一键启动（开发备用）
```bash
bash scripts/start-mvp.sh
```

日志输出：
- `data/backend.log`
- `data/frontend.log`

---

## 后端测试

```bash
cd app/backend
python3 -m pytest tests -q
```

建议门禁：
- 后端：`cd app/backend && .venv\Scripts\python.exe -m pytest -q`
- 前端：`cd app/frontend && npm run build`
- L1：`python tools/probes/l1_selector_replay.py --output-dir data/l1_selector_replay`
- L2：需要真实店小秘登录态，只探测商品箱 `draft_box`。结果必须绑定当前 run id、session fingerprint、脚本 hash、Git HEAD，并通过路径、时效和证据文件 hash 重验后才允许进入 L3 判断。
- 浏览器 QA：前后端启动后运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1`，输出 `outputs/browser-checks/qa-browser-check.json`、桌面/移动页面截图、`qa-console.jsonl`、`qa-network.json` 和 `qa-blocked-actions.json`；JSON 会记录浏览器/OS/git/script hash，并断言无 console error、无网络失败、无 4xx/5xx、无非 GET、无外部 origin，且本地启动与直接 DXM 写入端点均被 403 阻断

DXM 半托管自动化工作台交付自检（推荐给验收人）：

```bat
scripts\final-delivery-check.bat
```

它会串行运行 Windows 启动前检查、后端全量测试、前端生产构建、L1 selector replay、`git diff --check`、浏览器 QA，并输出 `outputs/final-delivery-check/final-delivery-check.md` / `.json`。最终自检模式下，浏览器 QA 截图和 sidecar 文件位于 `outputs\final-delivery-check\browser-checks\`。浏览器 QA 会临时启动隔离的当前源码后端和前端预览服务，避免误测 8000/5173 上的旧进程；检查模式可能安装前端依赖，但不会访问店小秘、不会执行真实保存。报告顶部会分别显示“自动化工作台自检结果”和“真实 DXM 写入放行状态”。

2026-07-04 的 clean-worktree 检查、测试计数、L2 run-id 和 `READY` 结论只属于历史验收记录。当前分支必须重新产生测试、构建、portable smoke、商品箱 L2 和真实保存证据；在此之前，预期状态是 `BLOCKED` / `pending_live_dxm_validation`。

自动化或管理摘要读取 `final-delivery-check.json` 时不能只读 `ok`。必须同时检查 `realDxmMutationAllowed`、`realDxmMutationScope`、`singleSaveAcceptance`、`stateConsistency`、Git/build/package identity 和当次证据路径；单商品结论不能扩大解释为受控整批，受控整批结论也不开放发布或无人值守。

启动工作台后，结果与问题页会显示交付自检摘要和报告路径，方便验收人直接确认自动化工作台 PASS、真实写入门禁状态与源码包状态。

开发自检入口只在 `?dev=1` 或显式启用 `VITE_DXM_ENABLE_DEMO=1` 时可用；它只创建本地 `dry_run` 自检任务，不触达 DXM，不能作为真实交付验收依据。真实用户必须从商品箱选择现有商品，并在当次上游门禁、人工批准、实时身份复核和 mutation ledger 共同允许时执行。旧 `batch_save`、无人值守和发布保持阻断。

发布源码包前可加 clean worktree 门禁：

```bat
scripts\final-delivery-check.bat -RequireCleanWorktree
```

当前开发态有未提交改动时，该模式会把 `Source package check` 标为 `FAIL`；自动化工作台自检结果会单独保留。

查看自检参数：

```bat
scripts\final-delivery-check.bat --help
```

正式验收不要使用 `-SkipBrowserQA`。

---

## 当前技术路线

- 正式产品主路线：**本地版 + 自建 Playwright 主引擎**
- Browser Use：作为后续增强执行器预留，不作为当前底座
- MVP 范围：**速卖通 POP + 保存待发布**

---

## 下一步重点

1. 保持 `config/l2_readonly_allowlist.json` 的最小只读范围；继续禁止写方法、WebSocket、EventSource 和 action 端点。
2. 当前源码发布候选必须先运行 `scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness BLOCKED -ExpectedRealDxmSingleSaveEndToEnd pending_live_dxm_validation`，并核对报告 Git HEAD 与交付源码一致。只有同 HEAD 商品箱 L2 与真实单次保存闭环完成后，才能改用 `READY` 与 `passed`。
3. 当前主路径从商品箱开始；若声明受控整批可交付，必须另行建立批次冻结、一次批准、串行派发、逐项证据、失败隔离和人工对账验收，不能复用单商品结论。
4. 批量、无人值守和发布必须单独设计门禁、人工批准和回滚策略。

免安装版快速使用说明与 2026-06-22/2026-07-04 验收记录均为历史资料。当前源码有新改动或 L2/L3 证据过期时，交付前必须重新跑 clean worktree、同 HEAD portable 和新鲜门禁；不得复用旧 `single_save` 结论扩大解释。

---

## 目录结构

```text
app/
├── backend/
├── desktop/
└── frontend/

docs/
├── api/
├── product/
├── research/
└── tech/

tools/
└── probes/
    ├── draft-box/
    ├── editor/
    ├── login/
    └── navigation/

data/
├── ai/
├── evidences/
├── screenshots/
├── sessions/
└── sqlite/

outputs/
├── reports/
└── spreadsheets/

scripts/
├── start-backend.sh
├── start-frontend.sh
├── start-mvp.sh
├── start-mvp.bat
├── start-mvp.ps1
├── final-delivery-check.bat
└── final-delivery-check.ps1
```

---

## 一句话状态

**当前源码已移除认领环节，主路径为商品箱现有商品的 `single_save` 与 `controlled_edit_batch`；在同 HEAD 全新 portable 和真实保存证据齐备前，生产交付保持 `BLOCKED`。**
