# dxm-auto-uikit

店小秘自动刊登助手 MVP。

当前已落地为 **本地可运行工作台 + V1 安全门禁原型**，不是纯文档项目了。

交付状态说明：
- L0 后端/前端本地门禁与 L1 离线 selector replay 可运行。
- 真实 L2 只读 probe 最近一次未通过，因此 L3 `single_save` 真实保存入口必须保持阻断。
- 当前可交付给内部验收的是本地安全诊断工作台；当前不可交付的是店小秘真实无人值守保存/写入。

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

## MVP 当前能力

### 已实现：本地/演示/诊断能力
- 店铺连接（演示态）
- 模板中心基础 CRUD
- 商品导入（JSON/演示数据）
- 任务创建
- 本地 `dry_run` 演示任务启动与状态流转
- Task/Job 状态流转
- WebSocket 实时执行事件
- 日志中心
- 证据面板
- 异常池（当前框架已接入，演示流程暂未主动制造异常）
- Playwright 主引擎骨架
- POP 保存待发布演示链路（本地 `dry_run` 可启动；真实 `single_save` 不代表 DXM 写入放行）

### 当前是“安全门禁可运行版”
说明：
- 右侧实时执行区已经能看到任务状态、步骤流、日志和证据
- 工作台会显示 L0/L1/L2/L3 门禁、证据等级和真实保存阻断原因
- L2 真实只读未通过前，真实 `claim_only` / `single_save` / `batch_save` 会被后端与前端双重阻断
- 下一步重点是让真实 L2 双目标只读 probe 通过，再由人工批准执行 L3 金丝雀

---

## 启动方式

当前仓库默认面向 Windows 本地交付；推荐先运行检查模式，确认 Python、npm、后端依赖和前端依赖都就绪。

前置条件：
- Windows 10/11 + PowerShell
- Python 3.11+
- Node.js/npm
- Git
- 首次安装前端依赖时需要可访问 npm registry 的网络

### 0. Windows 启动前检查

```bat
scripts\start-mvp.bat --check
```

检查通过后再启动完整工作台：

```bat
scripts\start-mvp.bat
```

启动后会打开两个 CMD 服务窗口；只有后端 `/health` 与前端页面健康检查都通过时，才会自动打开前端页面。若启动日志出现 warning，脚本不会自动开页，请先查看日志并等健康检查恢复后再手动访问。

- 后端：`http://127.0.0.1:8000`
- 前端：`http://127.0.0.1:5173`
- 日志：`data\start-mvp.log`、`data\backend.log`、`data\frontend.log`

停止方式：关闭 `DXM Backend Service` / `DXM Frontend Service`（中文可理解为 DXM 后端服务 / DXM 前端服务）两个 CMD 窗口。

### 1. 类 Unix / Git Bash 启动后端
```bash
bash scripts/start-backend.sh
```

后端地址：
- `http://127.0.0.1:8000`

### 2. 类 Unix / Git Bash 启动前端
```bash
bash scripts/start-frontend.sh
```

前端地址：
- `http://127.0.0.1:5173`

### 3. 类 Unix / Git Bash 一键启动（后台方式）
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

本地工作台交付自检（推荐给验收人）：

```bat
scripts\final-delivery-check.bat
```

它会串行运行 Windows 启动前检查、后端全量测试、前端生产构建、L1 selector replay、`git diff --check`、浏览器 QA，并输出 `outputs/final-delivery-check/final-delivery-check.md` / `.json`。最终自检模式下，浏览器 QA 截图和 sidecar 文件位于 `outputs\final-delivery-check\browser-checks\`。浏览器 QA 会临时启动隔离的当前源码后端和前端预览服务，避免误测 8000/5173 上的旧进程；检查模式可能安装前端依赖，但不会访问店小秘、不会执行真实保存。报告顶部会分别显示“本地工作台自检结果”和“真实 DXM 写入放行状态”。

当前验收成功标准：默认验收要求 `Local workbench check: PASS`、`Browser QA: PASS`、`Source package check: NOT_REQUIRED` 以及 `Real DXM write readiness: BLOCKED` 同时成立；发布源码包验收才要求 `Source package check: PASS`。这里的 `BLOCKED` 是预期安全状态，表示真实 L2/L3 尚未放行，不表示本地工作台交付失败。

启动工作台后，报告中心会显示最近一次交付自检摘要和报告路径，方便验收人直接确认本地 PASS、真实写入 BLOCKED 与源码包状态。

验收人可以在任务中心点击“创建演示批次（写入本地）”，该按钮只创建本地 `dry_run` 演示任务；“启动本地演示任务”可跑通本地工作台状态流转。真实 `claim_only` / `single_save` / `batch_save` 仍受 L2/L3 与人工批准令牌阻断。

发布源码包前可加 clean worktree 门禁：

```bat
scripts\final-delivery-check.bat -RequireCleanWorktree
```

当前开发态有未提交改动时，该模式会把 `Source package check` 标为 `FAIL`；本地工作台自检结果会单独保留。

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

1. 真实接入店小秘登录态与 session 管理
2. 实现真实 `DxmAdapter`
3. 接入真实字段域填写顺序
4. 把图片上传 / SKU / 价格 / 运费模板做成真实执行步骤
5. 做人工接管模式
6. 增加真实异常归因

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

**dxm-auto-uikit 已经从“文档方案”进入“本地工作台 + 安全门禁原型”；真实保存交付仍以 L2 双目标通过和 L3 人工批准金丝雀为前置。**
