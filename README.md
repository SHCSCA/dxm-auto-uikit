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
- 本地任务启动与状态流转
- Task/Job 状态流转
- WebSocket 实时执行事件
- 日志中心
- 证据面板
- 异常池（当前框架已接入，演示流程暂未主动制造异常）
- Playwright 主引擎骨架
- POP 保存待发布演示链路（模拟执行，不代表真实 DXM 写入放行）

### 当前是“安全门禁可运行版”
说明：
- 右侧实时执行区已经能看到任务状态、步骤流、日志和证据
- 工作台会显示 L0/L1/L2/L3 门禁、证据等级和真实保存阻断原因
- L2 真实只读未通过前，真实 `single_save` / `batch_save` 会被后端与前端双重阻断
- 下一步重点是让真实 L2 双目标只读 probe 通过，再由人工批准执行 L3 金丝雀

---

## 启动方式

当前仓库默认面向 Windows 本地交付；推荐先运行检查模式，确认 Python、npm、后端依赖和前端依赖都就绪。

### 0. Windows 启动前检查

```bat
scripts\start-mvp.bat --check
```

检查通过后再启动完整工作台：

```bat
scripts\start-mvp.bat
```

启动后会打开两个 CMD 服务窗口，并自动打开前端页面：

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
- L2：需要真实店小秘登录态，双目标 `data_acquisition` / `draft_box` 全部通过后才允许 L3
- 浏览器 QA：前后端启动后运行 `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1`，输出 `outputs/browser-checks/qa-browser-check.json`、两张页面截图、`qa-console.jsonl` 和 `qa-network.json`；JSON 会记录浏览器/OS/git/script hash，并断言无 console error、无网络失败、无 4xx/5xx、无非 GET、无外部 host

本地工作台交付自检（推荐给验收人）：

```bat
scripts\final-delivery-check.bat
```

它会串行运行 Windows 启动前检查、后端全量测试、前端生产构建、L1 selector replay、`git diff --check`、浏览器 QA，并输出 `outputs/final-delivery-check/final-delivery-check.md` / `.json`。报告顶部会分别显示“本地工作台自检结果”和“真实 DXM 写入放行状态”；如果前后端服务尚未启动，请先运行 `scripts\start-mvp.bat`。检查模式可能安装前端依赖，但不会启动服务、不会访问店小秘、不会执行真实保存。

发布源码包前可加 clean worktree 门禁：

```bat
scripts\final-delivery-check.bat -RequireCleanWorktree
```

当前开发态有未提交改动时，该模式会把 `Source package check` 标为 `FAIL`；本地工作台自检结果会单独保留。

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
└── final-delivery-check.bat
```

---

## 一句话状态

**dxm-auto-uikit 已经从“文档方案”进入“本地工作台 + 安全门禁原型”；真实保存交付仍以 L2 双目标通过和 L3 人工批准金丝雀为前置。**
