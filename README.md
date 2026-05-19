# dxm-auto-uikit

店小秘自动刊登助手 MVP。

当前已落地为 **可运行原型**，不是纯文档项目了。

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

### 已实现
- 店铺连接（演示态）
- 模板中心基础 CRUD
- 商品导入（JSON/演示数据）
- 任务创建
- 任务启动
- Task/Job 状态流转
- WebSocket 实时执行事件
- 日志中心
- 证据面板
- 异常池（当前框架已接入，演示流程暂未主动制造异常）
- Playwright 主引擎骨架
- POP 保存待发布演示链路（模拟执行）

### 当前是“演示可运行版”
说明：
- 右侧实时执行区已经能看到任务状态、步骤流、日志和证据
- 当前执行器采用 **模拟链路 + Playwright 骨架**
- 下一步重点是把真实店小秘页面适配接上

---

## 启动方式

### 1. 启动后端
```bash
bash scripts/start-backend.sh
```

后端地址：
- `http://127.0.0.1:8000`

### 2. 启动前端
```bash
bash scripts/start-frontend.sh
```

前端地址：
- `http://127.0.0.1:5173`

### 3. 一键启动（后台方式）
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

当前结果：
- `2 passed`

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
└── start-mvp.sh
```

---

## 一句话状态

**dxm-auto-uikit 已经从“文档方案”进入“可运行 MVP 原型”。**
