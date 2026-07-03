# dxm-auto-uikit

DXM 半托管自动化工作台，面向真实店小秘账号、真实浏览器和受控只保存流程。

当前用户路径是：启动工作台、登录真实店小秘、先在店小秘已有待认领商品列表中把目标商品放进商品箱，再从商品箱进入编辑页，按模板补齐字段并在真实浏览器中完成“只保存不发布”的保存核验。它不是商品采集器、本地演示页，也不是安全诊断工具。

普通用户主流程：从“首页”查看下一步，到“账号与浏览器”打开真实店小秘浏览器并登录，进入“待认领商品”创建任务，进入“模板中心”按店小秘编辑页分区确认店铺默认和类目默认模板，再到“商品箱编辑保存”选择已进入商品箱的商品，最后在“浏览器现场”中观察真实浏览器自动只保存。

当前可用范围：
- 已验证受控单商品只保存；最终动作只保存，不发布。
- 批量保存、无人值守和任何发布动作仍保持关闭。
- 每次执行前都以工作台当前状态为准：真实登录、配置完整、真实只读检查通过、人工确认后才启动保存。

## 真实用户快速开始

> 当前用户可执行范围：受控“单商品只保存”。最终动作只保存，不发布；内部任务模式为 `single_save`，普通操作时只看页面上的中文按钮。

### 推荐入口：DXM Agent Console 桌面版

交付用户优先使用桌面版，不需要分别打开后端和前端两个控制台窗口。

当前给用户的免安装 EXE：

```text
D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

2026-07-04 04:14（Asia/Shanghai）当前分支 packaged/portable smoke 已通过，文件 SHA-256：

```text
83F162F579A1F45971ADDA7ABC93EB2FF206BC25FA6E0DB965872EEC5B9C0F75
```

本轮桌面包验收记录：`docs/product/最终交付验收记录-20260623-桌面包.md`。当前 2026-07-04 `167fb6f` 工作树新包已通过 backend pytest、frontend production build、desktop production build、packaged smoke、portable smoke、browser workbench QA 和 final report center QA，证明当前分支免安装包可启动，并包含“待认领商品 -> 商品箱编辑保存”的主路径桥接、结果页两段式生产交付状态、真实浏览器 HUD 保活、测试商品阻断、模板中心默认配置主路径优化，以及新版两段式菜单与操作引导；真实店小秘“两段式端到端验收”仍需现场跑通后再标记最终生产交付。

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
6. 进入“待认领商品”，选择真实店铺和店小秘已有待认领商品，先把商品放进商品箱，再到“商品箱编辑保存”选择已进入商品箱的商品。
7. 只有真实只读检查通过、配置检查通过且人工批准完成后，才能在页面内填写批准人标识并点击“申请并启动单商品只保存”。
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
- 真实只读检查 / 单商品只保存任务创建
- Task/Job 状态流转
- WebSocket 实时执行事件
- 真实浏览器页、执行浏览器会话状态、页面内中文进度 HUD、折叠式页面内操控和日志中心
- 证据面板
- 结果与问题页（真实失败按问题卡展示，技术诊断默认折叠）
- Playwright 主引擎骨架
- POP 保存待发布链路（真实单商品只保存已具备受控证据；批量、无人值守和发布仍不放行）

### 当前是“受控单商品只保存版”
说明：
- 右侧实时执行区已经能看到任务状态、步骤流、日志和证据
- 工作台会显示真实只读检查、人工确认、证据等级和真实保存阻断原因
- 前置条件不满足时，真实认领、单商品只保存和批量保存会被后端与前端双重阻断
- 当前已验证的真实写入范围仅为受控单商品只保存；批量、无人值守和发布仍保持阻断
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

当前给用户的免安装 EXE：

```bat
D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

2026-07-04 04:14（Asia/Shanghai）当前分支 packaged/portable smoke 已通过，文件 SHA-256：

```bat
83F162F579A1F45971ADDA7ABC93EB2FF206BC25FA6E0DB965872EEC5B9C0F75
```

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
- L2：需要真实店小秘登录态，已有待认领列表与商品箱两个目标必须使用同一个 `--run-id` 完成保存前安全检查，并共享同一 session fingerprint、脚本 hash 与 git head；全部通过后才允许 L3。探针内部参数仍使用 `data_acquisition` / `draft_box`，这是店小秘页面适配名，不代表系统会采集或创建商品。
- 浏览器 QA：前后端启动后运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1`，输出 `outputs/browser-checks/qa-browser-check.json`、桌面/移动页面截图、`qa-console.jsonl`、`qa-network.json` 和 `qa-blocked-actions.json`；JSON 会记录浏览器/OS/git/script hash，并断言无 console error、无网络失败、无 4xx/5xx、无非 GET、无外部 origin，且本地启动与直接 DXM 写入端点均被 403 阻断

DXM 半托管自动化工作台交付自检（推荐给验收人）：

```bat
scripts\final-delivery-check.bat
```

它会串行运行 Windows 启动前检查、后端全量测试、前端生产构建、L1 selector replay、`git diff --check`、浏览器 QA，并输出 `outputs/final-delivery-check/final-delivery-check.md` / `.json`。最终自检模式下，浏览器 QA 截图和 sidecar 文件位于 `outputs\final-delivery-check\browser-checks\`。浏览器 QA 会临时启动隔离的当前源码后端和前端预览服务，避免误测 8000/5173 上的旧进程；检查模式可能安装前端依赖，但不会访问店小秘、不会执行真实保存。报告顶部会分别显示“自动化工作台自检结果”和“真实 DXM 写入放行状态”。

当前源码包验收成功标准：`Local workbench check: PASS`、`Browser QA: PASS`、`Final report center QA: PASS`、`Source package check: PASS`，并按 L2/L3 门禁计算 `Real DXM write readiness`。当前最新归档本地工作台验收为 2026-06-22 18:14（Asia/Shanghai）：自动化工作台、桌面 portable 构建、packaged smoke、Browser QA 和最终报告中心 QA 均已通过；后端全量测试为 `678 passed`；报告内 Git HEAD 为 `4e555da7080ac1e5423d89ad86a2d290cda446c7`，本轮最终提交并推送为 `83537919cd3a3f3366caaff69032b1f01231b047`；报告目录为 `outputs\final-delivery-check`；`Source package check=NOT_REQUIRED`、`Source package readiness=DIRTY`。正式源码包交付仍必须重新运行 `-RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY`，并让报告 Git HEAD 与提交后的源码一致。历史 `READY` 只代表当时受控单商品只保存，不代表批量、无人值守或发布放行；当前两段式真实端到端仍需现场验收，不能把历史 READY 当永久授权。

自动化或管理摘要读取 `final-delivery-check.json` 时，不能只读取 `ok`。当前 `ok: true` 只代表 `okScope` 所声明的范围通过；必须同时读取 `realDxmMutationAllowed`、`realDxmMutationScope` 与当次验收记录。若 `okScope` 为 `local_workbench_and_controlled_single_save_ready`、`realDxmMutationAllowed` 为 `true` 且 `realDxmMutationScope` 为 `controlled_single_save_only`，结论只支持保存阶段可按门禁启动；两段式生产交付还必须额外具备已有待认领商品进入商品箱的真实验收记录。

启动工作台后，结果与问题页会显示交付自检摘要和报告路径，方便验收人直接确认自动化工作台 PASS、真实写入门禁状态与源码包状态。

开发自检入口只在 `?dev=1` 或显式启用 `VITE_DXM_ENABLE_DEMO=1` 时可用；它只创建本地 `dry_run` 自检任务，不触达 DXM，不能作为真实交付验收依据。真实用户交付路径是两段式：先完成待认领商品处理，再执行商品箱编辑保存；保存阶段只在当前 L2/L3 READY、人工批准令牌和金丝雀证据链约束下放行。`batch_save`、批量无人值守和发布仍保持阻断。

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
2. 每次源码发布包前重新运行 `scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop -ExpectedRealDxmWriteReadiness READY`，并核对报告 Git HEAD 与交付源码一致。
3. 当前主路径包含“待认领商品处理 -> 商品箱编辑保存”；若要扩大到批量保存或其他真实写入范围，必须为对应范围重新建立真实只读检查、人工批准和保存/回滚证据，不复用单商品只保存结论。
4. 批量、无人值守和发布必须单独设计门禁、人工批准和回滚策略。

免安装版快速使用说明见 `docs/product/免安装版快速使用说明-20260615.md`。当前本地交付记录见 `docs/product/最终交付验收记录-20260622.md`；2026-06-18 与 2026-06-17 记录保留为历史验收记录。当前源码有新改动或 L2/L3 证据过期时，交付前必须重新跑 clean worktree 验收或新鲜门禁。真实写入放行范围仅为受控 `single_save`；待认领商品处理是当前两段式主流程的第一段，批量、无人值守、发布以及扩大保存范围仍需单独证据链。

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

**dxm-auto-uikit 已经进入“DXM 半托管自动化工作台 + 受控单商品只保存”阶段；批量、无人值守和发布仍保持单独门禁，不随当前单商品只保存证据自动放行。**
