# dxm-auto-uikit

DXM 半托管自动化工作台：用真实可见浏览器处理店小秘已有商品，受控完成“待认领商品入箱 → 商品箱编辑 → 只保存不发布”。

## 当前状态（2026-08-12）

当前产品主合同是 [MVP 竖切：草稿箱批量只保存](docs/product/MVP-竖切-草稿箱批量只保存.md)：从店小秘草稿箱只读选择多件商品，以本地方案和只读店小秘模板形成不可变 `plan_snapshot`，后续仅允许 `batch_draft_save`；发布、保存并发布和移入待发布始终禁止。旧 `claim_only` / `single_save` 只保留为历史兼容能力，不是 MVP 前置或当前产品主叙事。

**当前工程状态为 `E2_DEFERRED` / `E3_READY_FOR_CANARY`，生产交付仍为 `BLOCKED`。** 这只表示 E3 代码、合同和固定提交的本地工程门禁已通过，不是 `E2_ACCEPTED`、`E3_ACCEPTED`、`MVP_READY` 或 `PROD_READY`。本轮已把 JIT 授权、队列顺序、审批租约、冻结 snapshot/Schema/字段值、页面身份、SAVE ActionResult、mutation ledger、重启 `UNKNOWN` 与后续 `VERIFY_NOT_PUBLISHED` 绑定为同一不可变执行链；发布、保存并发布和移入待发布仍无入口。

本轮真实店小秘登录、保存、发布和站点浏览器操作均为 0。固定代码提交 `717ae3c5618ced19467d528e41aac784e896c810` 的独立 clean worktree 完整 backend L0 为 `2168 passed / 0 failed / 0 skipped`；frontend 标准 build（Node `12/12`、Chromium `7/7`、typecheck、Vite）、desktop `89/89`、文档 SelfTest 红→绿、diff/status/端口门禁也已通过。下一步只能在另行明确授权后执行可见浏览器三商品 canary，详见 [PROGRESS](PROGRESS.md) 与 [BLOCKED](BLOCKED.md)。

当前源码/package 版本是 `0.1.3`，但本轮没有构建或交付 `0.1.3` portable。2026-07-04 的 `0.1.0` portable 与 `READY` 记录仅是历史构建快照，不是当前分支或 `0.1.3` 的放行结论。当前事实入口见 [文档导航](docs/README.md)、[MVP 主合同](docs/product/MVP-竖切-草稿箱批量只保存.md) 和 [E2 冻结遗留与 E3 开工](docs/product/E2-冻结遗留与E3开工.md)。

真实用户主路径从草稿箱只读 Reader 开始：选择至少 3 件草稿、审阅本地方案与只读模板、预览并冻结逐商品计划。E2 到此停止，不触发 Runner、保存或发布；任何事实缺失、身份/Schema/模板漂移或语言结果为 `UNKNOWN` 都必须失败关闭并转人工复核。

## 真实用户快速开始

> 本节保留源码启动方式和 2026-07-04 的 `0.1.0` 历史包路径，便于追溯。它不是当前 `0.1.3` 源码的构建产物，也不代表当前分支已放行；真实写入继续保持 `BLOCKED`。

### 推荐入口：DXM Agent Console 桌面版

交付用户优先使用桌面版，不需要分别打开后端和前端两个控制台窗口。

2026-07-04 历史验收使用的免安装 EXE：

```text
D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

2026-07-04 05:43（Asia/Shanghai）main 构建后 packaged/portable smoke 已通过，文件 SHA-256：

```text
87FF78089190226C2E98FAA1B4BA60DA25E25C320901B9FD7C0A6207F9C140F8
```

历史桌面包验收记录：`docs/product/最终交付验收记录-20260623-桌面包.md`。其中 `READY` 只属于记录内的旧 commit、旧包和受控单商品保存范围；它没有证明当前源码或完整两段式生产交付。

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

### 当前源码是“受控两段式加固版”
说明：
- 右侧实时执行区已经能看到任务状态、步骤流、日志和证据
- 工作台会显示真实只读检查、人工确认、证据等级和真实保存阻断原因
- 前置条件不满足时，真实认领、单商品只保存和批量保存会被后端与前端双重阻断
- Stage A `claim_only` 与 Stage B `single_save` 已进入源码级契约加固；这不等同于当前生产放行
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

2026-07-04 历史验收使用的免安装 EXE：

```bat
D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe
outputs\desktop-build\DXM-Agent-Console-Portable-0.1.0.exe
```

2026-07-04 05:43（Asia/Shanghai）main clean worktree 构建后 packaged/portable smoke 已通过，文件 SHA-256：

```bat
87FF78089190226C2E98FAA1B4BA60DA25E25C320901B9FD7C0A6207F9C140F8
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

2026-07-04 的 clean-worktree 检查、测试计数、L2 run-id 和 `READY` 结论只属于历史验收记录。2026-07-17 当前分支必须重新产生自己的测试、构建、portable smoke、L2 和两段式现场证据；在此之前，预期状态是 `BLOCKED` / `pending_live_dxm_validation`。

自动化或管理摘要读取 `final-delivery-check.json` 时，不能只读取 `ok`。当前 `ok: true` 只代表 `okScope` 所声明的范围通过；必须同时读取 `realDxmMutationAllowed`、`realDxmMutationScope` 与当次验收记录。若 `okScope` 为 `local_workbench_and_controlled_single_save_ready`、`realDxmMutationAllowed` 为 `true` 且 `realDxmMutationScope` 为 `controlled_single_save_only`，结论只支持保存阶段可按门禁启动；两段式生产交付还必须额外具备已有待认领商品进入商品箱的真实验收记录。

启动工作台后，结果与问题页会显示交付自检摘要和报告路径，方便验收人直接确认自动化工作台 PASS、真实写入门禁状态与源码包状态。

开发自检入口只在 `?dev=1` 或显式启用 `VITE_DXM_ENABLE_DEMO=1` 时可用；它只创建本地 `dry_run` 自检任务，不触达 DXM，不能作为真实交付验收依据。真实用户交付路径是两段式：先完成待认领入箱，再执行同商品编辑保存；每个阶段只有在当次上游门禁、专属人工审批租约、实时身份复核和 mutation ledger 共同允许时才可执行。`batch_save`、批量无人值守和发布仍保持阻断。

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

1. 保持 `config/l2_readonly_allowlist.json` 的最小只读范围；Schema 查询即使使用 POST 也只能进入明确只读审计白名单，未知请求一律失败关闭。
2. 保持固定提交 clean worktree 的 backend L0、frontend 标准 build、desktop 测试、文档 SelfTest、范围/秘密/哈希门禁全绿；任一项回退都撤销 `E3_READY_FOR_CANARY` 并恢复 `E3_OPEN / BLOCKED`。
3. 当前 `E3_READY_FOR_CANARY` 仍不是 `E3_ACCEPTED`、`MVP_READY` 或 `PROD_READY`，真实写入必须另行明确授权，且授权必须绑定实际固定提交与工作树身份。
4. 获得授权后的可见浏览器 canary 必须由工作台 UI 完成真实登录、同次 Reader 选择至少 3 件草稿、按冻结 snapshot 串行只保存，并逐件取得“回包 + 页面成功态 + 独立未发布”三铁证；任何 `UNKNOWN` 立即停批。扩大批量、无人值守和发布不得从旧能力或本次受控三件 canary 推导授权。

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

**当前源码处于 `E2_DEFERRED / E3_READY_FOR_CANARY`：固定提交 clean 工程门禁已全绿；真实三商品 canary 未授权、未执行，生产交付保持 `BLOCKED`。**
