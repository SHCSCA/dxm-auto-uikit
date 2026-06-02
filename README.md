# dxm-auto-uikit

DXM 半托管自动化工作台，面向真实店小秘账号、真实浏览器和受控 save-only 流程。

当前已落地为 **DXM 半托管自动化工作台 + 真实保存门禁**。它不是本地演示页，也不是安全诊断工具；普通用户路径是启动工作台、登录真实店小秘、补齐编辑页配置、创建 `single_save` 任务，并在真实浏览器中完成“只保存不发布”的单商品保存核验。

交付状态说明：
- L0 后端/前端本地门禁与 L1 离线 selector replay 可运行。
- 已知真实证据：L3 task 70 受控 `single_save` 成功，保存接口 `popChoiceProduct/add.json` 返回 `code=0`，且 `published=false`。
- 截至 2026-06-01 10:30（Asia/Shanghai），最新 L2 双目标真实只读 probe 与 L3 受控 `single_save` 金丝雀均已通过，最终自检显示 `Real DXM write readiness: READY`，范围仅为 `controlled_single_save_only`。
- 当前交付重点是 DXM 半托管自动化工作台与受控 save-only 自动化链路；批量、无人值守和发布不随 `single_save` READY 自动放行。
- 源码包验收命令：`scripts\final-delivery-check.bat -RequireCleanWorktree`；具体 Git HEAD 以 `outputs/final-delivery-check/final-delivery-check.json` 的 `gitHead` 字段为准。

## 真实用户快速开始

> 当前用户可执行范围：受控单商品 `single_save`。最终动作只保存，不发布。

1. 在 Windows PowerShell 或 CMD 中进入项目根目录。

```bat
cd /d C:\Users\wz\Desktop\py\dxm-auto-uikit
scripts\start-mvp.bat --check
scripts\start-mvp.bat
```

2. 保留启动器窗口。启动器会托管后端和前端；关闭该窗口或按 `Ctrl+C` 会停止服务。
3. 等启动器显示 `STARTED_OK` 后，使用自动打开的工作台页面；如果 5173 被占用，启动器会选择附近空闲端口并在日志中写出实际 URL。
4. 进入工作台的“操作引导”，在“打开真实 DXM 浏览器并确认登录”步骤点击“打开登录页”，在独立店小秘浏览器窗口完成真实账号登录和验证码处理。
5. 回到“配置中心”，按店小秘编辑页分区补齐：店铺与任务基础、类目与标题、SKU/价格/库存、价格策略、图片与素材、包装物流、合规/海关、半托管、店小秘引用模板。保存时可选“仅本次任务使用”或“保存为店铺模板”。
6. 进入“任务中心”，选择真实店铺和商品，模式选择 `L3 single_save`，点击“创建真实任务”。
7. 只有 L2 真实只读检查为 `passed`、配置预检通过且人工批准完成后，才能点击“批准并启动真实金丝雀”。弹窗要求输入 L3 批准人标识。
8. 进入“执行控制台”观察真实浏览器画面、自动操作轨迹、网络响应和实时日志。日志可切换“后端 / 前端 / 启动器 / 任务 / 浏览器 Agent”来源。
9. 任务完成后，到“报告中心”和“证据中心”核对保存响应、未发布证明、截图和结构化报告。验收结论必须是保存成功且 `published=false`。

不要用本地 `dry_run` 演示批次代替真实交付验收。`dry_run` 只用于开发自检，不访问店小秘。

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
- `app/backend/`：FastAPI + SQLite + WebSocket + 任务模拟执行器
- `app/frontend/`：React + Vite 控制台
- `app/desktop/`：Electron 桌面壳
- `data/`：数据库、证据、截图、日志目录
- `scripts/`：启动脚本

---

## 当前产品能力

### 已实现：DXM 半托管自动化工作台
- 店铺与商品队列展示
- 模板中心基础 CRUD
- 商品导入
- 真实 `probe` / `single_save` 任务创建
- Task/Job 状态流转
- WebSocket 实时执行事件
- 执行控制台、真实浏览器画面和日志中心
- 证据面板
- 异常池（当前框架已接入，演示流程暂未主动制造异常）
- Playwright 主引擎骨架
- POP 保存待发布链路（真实 `single_save` 已具备受控 READY 证据；批量、无人值守和发布仍不放行）

### 当前是“受控 single_save READY 版”
说明：
- 右侧实时执行区已经能看到任务状态、步骤流、日志和证据
- 工作台会显示 L0/L1/L2/L3 门禁、证据等级和真实保存阻断原因
- L2/L3 不满足时，真实 `claim_only` / `single_save` / `batch_save` 会被后端与前端双重阻断
- 当前已验证的真实写入范围仅为受控 `single_save`；批量、无人值守和发布仍保持门禁阻断

---

## 启动方式

当前仓库默认面向 Windows 本地交付；推荐先运行检查模式，确认 Python、npm、后端依赖和前端依赖都就绪。

前置条件：
- Windows 10/11 + PowerShell
- Python 3.11+
- Node.js/npm
- Git
- 首次安装前端依赖时需要可访问 npm registry 的网络

### 0. Windows 单窗口启动

```bat
scripts\start-mvp.bat --check
```

检查通过后再启动完整工作台：

```bat
scripts\start-mvp.bat
```

启动后只保留当前启动器控制台窗口。后端和前端会作为同一启动器窗口托管的子进程运行；只有后端 `/health` 与前端页面健康检查都通过时，才会自动打开前端页面。若 5173 被占用，启动器会自动使用附近空闲端口；若启动日志出现 warning，脚本不会自动开页，请先查看日志并等健康检查恢复后再手动访问启动器打印的前端 URL。

- 后端：`http://127.0.0.1:8000`
- 前端：默认 `http://127.0.0.1:5173`，端口占用时以启动器输出为准
- 日志：`data\start-mvp.log`、`data\backend.log`、`data\frontend.log`

停止方式：关闭当前启动器窗口，或在启动器窗口按 `Ctrl+C`。脚本退出时会尽力停止后端和前端子进程树。

### 1. 类 Unix / Git Bash 启动后端（开发备用）
```bash
bash scripts/start-backend.sh
```

后端地址：
- `http://127.0.0.1:8000`

### 2. 类 Unix / Git Bash 启动前端（开发备用）
```bash
bash scripts/start-frontend.sh
```

前端地址：
- `http://127.0.0.1:5173`

### 3. 类 Unix / Git Bash 一键启动（开发备用）
```bash
bash scripts/start-mvp.sh
```

日志输出：
- `data/backend.log`
- `data/frontend.log`

### 4. 启动桌面壳（可选）
先确保前端已运行：
```bash
cd app/desktop
npm install
DXM_FRONTEND_URL=http://127.0.0.1:5173 npm run dev
```

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
- L2：需要真实店小秘登录态，双目标 `data_acquisition` / `draft_box` 必须使用同一个 `--run-id` 完成只读 probe，并共享同一 session fingerprint、脚本 hash 与 git head；全部通过后才允许 L3
- 浏览器 QA：前后端启动后运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1`，输出 `outputs/browser-checks/qa-browser-check.json`、桌面/移动页面截图、`qa-console.jsonl`、`qa-network.json` 和 `qa-blocked-actions.json`；JSON 会记录浏览器/OS/git/script hash，并断言无 console error、无网络失败、无 4xx/5xx、无非 GET、无外部 origin，且本地启动与直接 DXM 写入端点均被 403 阻断

DXM 半托管自动化工作台交付自检（推荐给验收人）：

```bat
scripts\final-delivery-check.bat
```

它会串行运行 Windows 启动前检查、后端全量测试、前端生产构建、L1 selector replay、`git diff --check`、浏览器 QA，并输出 `outputs/final-delivery-check/final-delivery-check.md` / `.json`。最终自检模式下，浏览器 QA 截图和 sidecar 文件位于 `outputs\final-delivery-check\browser-checks\`。浏览器 QA 会临时启动隔离的当前源码后端和前端预览服务，避免误测 8000/5173 上的旧进程；检查模式可能安装前端依赖，但不会访问店小秘、不会执行真实保存。报告顶部会分别显示“自动化工作台自检结果”和“真实 DXM 写入放行状态”。

当前验收成功标准：默认验收要求 `Local workbench check: PASS`、`Browser QA: PASS`、`Source package check: NOT_REQUIRED`，并按 L2/L3 门禁计算 `Real DXM write readiness`。截至 2026-06-01 10:30，最新最终自检在 `-ExpectedRealDxmWriteReadiness READY` 下通过，`okScope=local_workbench_and_controlled_single_save_ready`。如果未来因 L2 证据过期或 L3 未放行显示 `BLOCKED`，表示真实写入不可启动，不表示自动化工作台本地功能失败；发布源码包验收才要求 `Source package check: PASS`。

自动化或管理摘要读取 `final-delivery-check.json` 时，不能只读取 `ok`。当前 `ok: true` 只代表 `okScope` 所声明的范围通过；若 `okScope` 为 `local_workbench_only` 且 `realDxmMutationAllowed` 为 `false`，结论仍然是自动化工作台可交付、真实 DXM 写入不可启动。

启动工作台后，报告中心会显示最近一次交付自检摘要和报告路径，方便验收人直接确认自动化工作台 PASS、真实写入门禁状态与源码包状态。

开发自检可在任务中心点击“创建本地 dry_run 演示批次”，该按钮只创建本地 `dry_run` 演示任务，不触达 DXM，不能作为真实交付验收依据。真实用户交付路径是 `single_save`，且只在当前 L2/L3 READY、人工批准令牌和金丝雀证据链约束下放行；真实 `claim_only` / `batch_save`、批量无人值守和发布仍保持阻断。

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
2. 将当前受控 `single_save` READY 证据纳入交付归档，并在源码发布包前运行 `scripts\final-delivery-check.bat -RequireCleanWorktree`。
3. 若要扩大到 `claim_only` / `batch_save`，必须为对应范围重新建立 L2/L3 证据，不复用 `single_save` 结论。
4. 批量、无人值守和发布必须单独设计门禁、人工批准和回滚策略。

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

**dxm-auto-uikit 已经进入“DXM 半托管自动化工作台 + 受控 single_save READY”阶段；批量、无人值守和发布仍保持单独门禁，不随当前 READY 自动放行。**
