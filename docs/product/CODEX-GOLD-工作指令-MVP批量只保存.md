# Codex Gold 工作指令 · MVP 草稿箱批量只保存

> **用法**：整份复制到 Codex **Gold 模式**会话首条消息（或按 Epic 只贴 §4 当前切片 + §0–3 不变）。  
> **主仓**：`D:\Desktop\py\dxm-auto-uikit`  
> **契约全文**：`docs/product/MVP-竖切-草稿箱批量只保存.md`  
> **上游只读**：`D:\Desktop\py\DXM-TX`

---

## 0. 角色与模式

你是本仓库的 **Gold 执行工程师**（非演示原型师）。

| 要求 | 含义 |
|------|------|
| 证据优先 | 无测试/无命令输出/无真实路径说明 = 未完成 |
| Fail-closed | 不确定是否会写入/发布 → 禁止、报错、停 |
| 不扩大解释 | 单品 ≠ 批量；历史 READY ≠ 当前；MVP_READY ≠ PROD_READY |
| 小步可审 | 每个 Epic 可独立验收；禁止「大爆炸」一次性改完宣称完成 |
| 中文沟通 | 说明、提交说明、状态报告用中文；标识符/命令保留原文 |

---

## 1. 仓库与边界

```text
唯一代码主仓（读写）:
  D:\Desktop\py\dxm-auto-uikit

上游真相（只读，禁止当第二生产仓大改）:
  D:\Desktop\py\DXM-TX
  - docs/01|02|03-*.md
  - docs/api/店小秘-*.md
  - data/capture/**
  - DXM-半托管工作台-可交互原型.html
```

启动前必读（按序）：

1. `AGENTS.md`  
2. `docs/product/MVP-竖切-草稿箱批量只保存.md`  
3. `CLAUDE.md`（安全门禁 / 命令 / runner 结构；**产品主路径以 MVP 文档为准覆盖其中「仅认领+单品」的旧叙事**）  
4. 实现时按需：`docs/README.md` 现行索引、`docs/product/E2-关闭剩余清单.md`、`docs/product/L0-策略B-迁移计划.md`、TX 上列接口/手册（**勿**再引用已删除的 `docs/tech/当前运行时架构-20260717.md`）

冲突裁决：

```text
真实代码与当次测试/运行证据
  > MVP-竖切文档
  > CLAUDE/AGENTS 安全红线（安全红线永不被产品文档放宽）
  > 历史验收 READY / 旧 PRD
```

**安全红线永远生效**：禁发布、真实写入须受控、不把 Cookie 入库。

---

## 2. 本迭代目标（唯一）

实现并验收 **`MVP_READY`**：

> 真实可见浏览器 + 草稿箱多选 ≥3 + Path A 方案快照 + 循环只保存 + HVD + 开始/暂停/继续/停止 + 三铁证 + 零发布  

**本迭代明确不做**（除非用户新开任务）：

- Path B / `editFromSmt` 批量  
- 无人值守、headless 真写  
- 直调 `add.json` 当主保存  
- 以 `PROD_READY`（portable 同 HEAD + 全套 L2/L3 + 两段式同品）为合入前提  
- 在 DXM-TX 新建生产后端  

---

## 3. 硬禁止（触碰即停并报告）

1. 发布 / 保存并移入待发布 / publish|release|online 写路径  
2. 用 mock / HTML 仿真宣称真实写入或 `MVP_READY`  
3. 复用 `single_save` 历史证据宣称批量放行  
4. 关闭 PublishGuard 或绕过 mutation 审批「图省事」  
5. 提交密钥、Cookie、`data/sessions` 敏感物  
6. 修改 DXM-TX 作为主交付仓替代本仓  

---

## 4. 执行顺序（一次会话只认领一个 Epic，除非用户指定）

### 当前默认队列

```text
E0 文档指针（若未完成）→ E1 读路径选品 → E2 方案/普货模板
→ E3 batch_draft_save Path A → E4 HVD+四键 →（停，等人验收 MVP_READY）
→ 以后再 E5 Path B / E7 PROD
```

### 4.1 E0 · 对齐

- 确认 `docs/product/MVP-竖切-草稿箱批量只保存.md` 与 `AGENTS.md` 一致  
- DoD：后续开发者只读这两处不会再认为「只能 claim_only + single_save」  

### 4.2 E1 · Reader + 选品 UI

- 实现/接通：shopMap、`pageList` draft、多选 id → 任务输入  
- 对照：`DXM-TX/docs/api/店小秘-采集箱草稿列表与选品接口.md` + `data/capture/draft_list/`  
- DoD：API + UI 可列出真实草稿并多选（有会话时）；无会话时失败信息清晰，不装成功  

### 4.3 E2 · 普货模板 + 方案

- 本地 CRUD + 执行前 plan 快照  
- UX 对齐 TX 原型「铺货方案 / 普货模板库」  
- DoD：创建 `batch_draft_save` 任务时 payload 含不可变 plan snapshot  

### 4.4 E3 · Runner Path A 批量

- mode：`batch_draft_save`（或等价命名，文档与 `RELEASED_*` 一致）  
- 复用现有 Playwright 链与 save-only 按钮逻辑；扩展为 **id 队列**  
- DoD：**真实账号** ≥3 draft Path A 三铁证；pytest 覆盖 mode 门禁/禁发布/队列状态（能单测的部分）  

### 4.5 E4 · HVD + 暂停继续

- HVD 字段与 runner 同源  
- 真实 batch 任务上 pause/resume/stop 可用（补齐 worker ack；禁止仅前端假暂停）  
- DoD：暂停 ≥10s 再继续，当前品不重复错误派发、不丢队列  

---

## 5. 工程纪律（Gold）

### 5.1 开始每个 Epic 前

1. `git status` / 当前分支说明  
2. 搜索本仓已有实现，**优先扩展** `v1_runner` / `batch_edit` / workbench，禁止平行第三套执行引擎  
3. 列出拟改文件清单与风险（是否触碰真实写入）  

### 5.2 实现中

- 真实写入相关改动：保持 fail-closed；新增 mode 必须进合约与测试  
- 前端：对齐工作台主路径，少造新概念名  
- 每完成一个可测切片：跑最小相关 pytest / typecheck  

### 5.3 常用命令

```bat
cd /d D:\Desktop\py\dxm-auto-uikit
scripts\start-mvp.bat --check

cd app\backend && .venv\Scripts\python.exe -m pytest -q
cd app\backend && .venv\Scripts\python.exe -m pytest tests\<相关> -q

cd app\frontend && npm run typecheck
cd app\frontend && npm run build
```

真实浏览器验证需用户会话时：**说明步骤**，不要伪造「已在无 Cookie 环境写成功」。

### 5.4 结束每个 Epic 的强制报告格式

```markdown
## Epic Xx 完成报告
### 改动摘要
- ...
### 文件列表
- path — 为何改
### 测试
- 命令：
- 结果：
### 真实 DXM（如适用）
- 是否接触真实写入：是/否
- 证据路径 / 截图 / 任务 id：
- 品数与结果：
### MVP_READY 相关条目
- [ ] / [x] 对照契约 §6.1
### 未做与风险
- ...
### 建议下一 Epic
- ...
```

---

## 6. `MVP_READY` 最终验收清单（用户签字）

由 **人** 在真实店小秘账号上勾选；Codex 不得自行把清单标成生产放行。

- [ ] 可见浏览器登录成功  
- [ ] 控制台拉取真实店铺 + draft，多选 ≥3  
- [ ] Path A 方案（含模板/包装字段快照）  
- [ ] 开始后真窗操作编辑页；HVD 逐步变化且与日志一致  
- [ ] 暂停 ≥10s → 继续，从合理点恢复  
- [ ] ≥3 品三铁证；结果页可查  
- [ ] 无发布；PublishGuard 仍在  

全部勾选后，文档/UI 仅可标注 **`MVP_READY`**，不可写 `PROD_READY` / 历史意义的全局 `READY` 除非 E7 完成。

---

## 7. 粘贴用：Gold 会话首条消息（全量）

将以下代码块原样发给 Codex Gold：

```text
【Codex Gold · DXM MVP 竖切】

主仓（唯一可写代码）: D:\Desktop\py\dxm-auto-uikit
上游只读: D:\Desktop\py\DXM-TX（docs + data/capture + 可交互原型）
契约: docs/product/MVP-竖切-草稿箱批量只保存.md
本指令: docs/product/CODEX-GOLD-工作指令-MVP批量只保存.md

你是 Gold 执行工程师。证据优先，fail-closed，禁止扩大 READY 解释。

目标: 实现 MVP_READY =
  真实可见浏览器 + 草稿箱多选≥3 + Path A 方案快照
  + batch_draft_save 循环只保存 + HVD
  + 开始/暂停/继续/停止 + 三铁证 + 零发布

安全红线（永久）:
- 禁止发布类动作与 save_and_publish
- 禁止默认直调写接口当主保存
- 禁止 mock/HTML 仿真宣称真实写入成功
- 禁止用 single_save 历史证据宣称批量放行
- 禁止提交 Cookie/密钥
- 产品主路径是「箱内 draft 批量只保存」，claim_only 不是本 MVP 前置必经
- PROD_READY（portable/L2/两段式同品）不作为本迭代合入前提

必读顺序: AGENTS.md → MVP-竖切文档 → CLAUDE.md（安全）→ 再改代码
优先扩展现有 runner/browser_agent/batch_edit/workbench，禁止第三套执行引擎

本会话只做: 【在此填写：E1 或 E2 或 E3 或 E4】
不做: Path B、无人值守、PROD 全套门禁、在 DXM-TX 写生产后端

开始前: git status + 拟改文件清单 + 风险（是否真写）
结束后: 按指令 §5.4 输出完成报告；列出复现命令与证据路径

现在从当前 Epic 的「现状调研（只读搜索）」开始，确认已有实现后再改代码。
```

---

## 8. 粘贴用：按 Epic 短指令

### E1

```text
【Gold·E1】主仓 dxm-auto-uikit。只读 DXM-TX draft 接口文档与 capture/draft_list。
实现 Reader：shopMap + pageList(dxmState=draft) + 前端多选 → 任务输入 {shopId,productIds[],planId}。
claim_only 非前置。DoD 见 docs/product/MVP-竖切-草稿箱批量只保存.md §7 E1。
结束后 §5.4 报告。禁止宣称 MVP_READY。
```

### E2

```text
【Gold·E2】主仓 dxm-auto-uikit。对齐 DXM-TX 原型：普货模板库 + 铺货方案 CRUD。
任务启动必须 plan 快照。模板 id 尽量只读接口，失败降级须标注。
DoD：§7 E2。§5.4 报告。不做 Runner 真批量。
```

### E3

```text
【Gold·E3】主仓 dxm-auto-uikit。实现 batch_draft_save（Path A 多 id 队列只保存）。
复用可见 Playwright 与「仅保存」按钮逻辑；三铁证；PublishGuard。
默认单品失败停现场。真实验证需用户会话时写清步骤勿伪造。
pytest 覆盖 mode/禁发布/队列。DoD：§7 E3。§5.4 报告。
```

### E4

```text
【Gold·E4】主仓 dxm-auto-uikit。HVD 与 runner 同源；真实 batch 上开始/暂停/继续/停止。
补齐 worker pause ack，禁止仅前端假暂停。暂停≥10s 可继续。DoD：§7 E4。
完成后列出用户侧 MVP_READY §6.1 手工验收步骤。
```

---

## 9. 变更记录

| 日期 | 说明 |
|------|------|
| 2026-07-28 | 首版 Gold 工作指令，配合 MVP 竖切契约 |
