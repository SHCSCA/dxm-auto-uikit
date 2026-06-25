# DXM Production Two Stage Version Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DXM Agent Console 从测试型工作台升级为客户可交付的生产级两段式真实浏览器自动化产品。

**Architecture:** 保持现有 React/Vite/Electron/FastAPI/Playwright 架构。产品主路径固定为两段：第一段从店小秘数据采集认领到采集箱，第二段从采集箱编辑商品并只保存；普通用户界面只展示业务动作，L2、probe、HAR、run-id、路径、原始异常等全部下沉到维护诊断。

**Tech Stack:** React 18 + TypeScript + Vite, Electron portable desktop, FastAPI, SQLite repository, Playwright headed browser automation, pytest contract tests, PowerShell delivery verification.

---

## 0. 当前判断

**当前分支:** `feature/dxm-production-two-stage`

**当前有效工作树:** `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage`

**当前完成度判断:** 约 72%。这不是交付结论，只表示核心方向和部分代码已转向两段式。距离“客户可正常使用”仍缺少真实两段式端到端验收、模板中心生产化、浏览器 Agent 常驻稳定、免安装包重新验收。

**已经具备:**
- 前端已有两段式菜单雏形。
- 后端已有 `claim_only` 和 `single_save` 两类任务。
- 已有 `/api/acquisition/claimed-products` 用于从真实认领商品进入第二段。
- 模板中心已有中文分区和执行取值预览基础。
- Electron 免安装包已有构建基础。

**主要缺口:**
- 真实业务逻辑还没有完全按“数据采集认领 -> 采集箱编辑保存”收口。
- QA 脚本和部分文案仍残留 `single_save` 直接创建、测试商品、L2/probe 等工程概念。
- 模板中心还不像成熟产品，用户不清楚当前用哪套模板、是否已保存、执行实际取哪个值。
- 浏览器 Agent 需要常开、可见、可接管，HUD 需要跨页面常驻。
- 结果、日志、失败原因仍偏技术，不适合客户自助使用。
- 免安装 EXE 需要基于当前分支重新打包、验证、给出路径和 hash。

## 1. 产品边界

### 允许范围

1. 打开真实店小秘浏览器。
2. 用户登录或本机记住账号密码后自动填充。
3. 第一段：在店小秘数据采集页认领真实商品到采集箱。
4. 第二段：从已认领的采集箱商品打开编辑页。
5. 按用户选择的模板填写编辑页。
6. 人工确认后只点击“保存”。
7. 检查保存成功和未发布证明。

### 禁止范围

1. 发布。
2. 保存并发布。
3. 移入待发布。
4. 批量保存。
5. 无人值守写入。
6. 测试商品冒充真实商品。
7. 未经采集箱确认直接进入只保存。

## 2. 版本路线图

### V0.9.1 状态可信和测试残留清理版

**目标:** 当前界面和脚本不再误导用户，不再从测试商品或直接 `single_save` 开始。

**交付内容:**
- QA/browser 脚本改为两段式检查，不再创建 `QA local gated single_save one product fixture`。
- 默认当前任务不从旧测试任务补回。
- 普通界面不显示 `QA guarded product`、`single_save READY`、`L2 probe`、`run-id` 等工程词。
- 首页和顶部状态条只表达：当前要做什么、为什么不能继续、下一步点哪里。
- 当前任务必须区分第一段认领任务和第二段保存任务。

**验收标准:**
- `scripts\qa-browser-check.ps1` 不再直接创建 fake `single_save`。
- 前端契约测试确认主路径不出现测试商品。
- `npm run build` 通过。
- 后端 focused tests 通过。

**建议完成度目标:** 从 72% 提升到 78%。

### V1.0 真实两段式主路径版

**目标:** 单店单商品完成真实 DXM 生产路径。

**用户路径:**
1. 打开免安装 EXE。
2. 登录店小秘。
3. 进入“数据采集认领”。
4. 输入或选择商品线索。
5. Agent 在真实浏览器认领商品到采集箱。
6. 进入“采集箱商品”选择已认领商品。
7. 进入“编辑保存”创建只保存任务。
8. 人工确认只保存。
9. Agent 打开真实编辑页，填写字段，只点击保存。
10. 结果页显示保存成功和未发布证明。

**交付内容:**
- 第一段 `claim_only` 完整闭环：创建任务、打开数据采集、定位商品、认领、采集箱确认、记录 claimed product。
- 第二段 `single_save` 只能从 claimed product 创建。
- 后端启动门禁必须阻止未认领商品进入保存。
- 保存报告必须关联同一个 claimed product。
- publish guard 在 UI 和 API 两层生效。

**验收标准:**
- 真实店小秘跑通一次 `数据采集认领 -> 采集箱确认`。
- 真实店小秘跑通一次 `采集箱编辑 -> 只保存 -> 未发布证明`。
- 证据里能看到同一商品的 source_url、claim result、draft box row、save result。
- 出现发布相关按钮或请求时自动停止。

**建议完成度目标:** 从 78% 提升到 86%。

### V1.1 模板中心生产版

**目标:** 配置中心从“字段堆叠”升级为客户可维护的多模板系统。

**菜单和页面:**
- `模板中心`
  - 当前模板
  - 店铺模板
  - 类目模板
  - 本次任务覆盖
  - 默认示例模板
  - 执行取值预览

**分区表单:**
1. 店铺与任务基础
2. 类目与标题
3. SKU / 价格 / 库存
4. 图片与素材
5. 包装物流
6. 合规 / 海关
7. 半托管
8. 店小秘引用模板
9. 执行策略

**每个分区固定动作:**
- 仅本次任务使用
- 保存为店铺模板
- 保存为类目模板
- 另存为新模板
- 套用默认示例模板

**取值优先级:**
1. 本次任务覆盖
2. 手动选择模板
3. 类目默认模板
4. 店铺默认模板
5. 系统默认模板
6. 商品原始数据

**验收标准:**
- 用户能保存多套模板。
- 用户能看懂当前正在使用哪套模板。
- 修改字段后有明确“未保存/已保存”状态。
- 启动保存前能预览最终执行值。
- 普通用户界面不暴露英文 key。

**建议完成度目标:** 从 86% 提升到 91%。

### V1.2 真实浏览器 Agent 和 HUD 稳定版

**目标:** 用户能看见 Agent 正在真实店小秘浏览器里做什么，失败后能接管。

**浏览器要求:**
- 必须显式打开。
- 必须保持在线。
- 失败时保留现场，不直接闪退。
- 用户可以手动接管。

**浏览器 HUD 要求:**
- 位于浏览器左上角。
- 深色小窗，常驻。
- 中文实时刷新任务进度。
- 页面跳转、刷新、新标签页后自动重注入。

**HUD 步骤示例:**
- 准备打开店小秘
- 检查登录状态
- 打开数据采集
- 搜索商品
- 定位目标商品
- 认领到采集箱
- 确认采集箱商品
- 打开编辑页
- 填写标题
- 选择分类
- 设置 SKU / 价格 / 库存
- 处理图片
- 选择包装物流
- 只点击保存
- 检查未发布
- 完成

**验收标准:**
- HUD 经历至少 5 次页面跳转仍常驻。
- 浏览器关闭、验证码等待、页面加载失败、Agent 异常都有中文恢复提示。
- 主窗口状态、HUD 状态、后台任务状态一致。
- Agent 运行失败不导致浏览器无提示闪退。

**建议完成度目标:** 从 91% 提升到 95%。

### V1.3 用户自助和问题恢复版

**目标:** 普通运营用户不看技术日志，也能知道怎么继续。

**交付内容:**
- 所有失败卡片统一为：
  - 发生了什么
  - 为什么停止
  - 下一步怎么做
  - 维护人员查看技术状态
- 实时日志默认只显示业务事件 5 到 10 条。
- 完整日志进入诊断抽屉。
- 结果页按业务复盘展示，不显示原始异常为主信息。

**覆盖失败场景:**
- 未登录。
- 验证码未处理。
- 未选择真实商品。
- 找不到商品。
- 多个商品匹配。
- 认领失败。
- 采集箱未确认。
- 模板缺失。
- 浏览器被关闭。
- 保存失败。
- 检测到发布风险。

**验收标准:**
- 主路径不出现 `Internal Server Error`、`greenlet`、`Playwright`、`HAR`、`run-id`。
- 每个失败都有一个明确按钮或下一步。
- 页面内容不重叠，不需要下滑很远才能看到主操作。

**建议完成度目标:** 从 95% 提升到 97%。

### V1.4 免安装客户交付版

**目标:** 输出客户可直接使用的 Windows 免安装目录。

**交付目录:**
- `DXM-Agent-Console-Portable-0.1.0.exe`
- `resources`
- 快速使用说明
- 常见问题与恢复说明
- 真实验收报告
- 版本说明
- EXE SHA-256
- Git HEAD

**启动要求:**
- 双击 EXE 后进入控制台。
- 不需要用户手动启动前端或后端窗口。
- 后端、前端、浏览器 Agent 生命周期由 Electron 托管。
- 本机账号密码加密保存。
- 资源缺失、端口占用、浏览器依赖缺失时给中文提示。

**验收标准:**
- `scripts\verify-desktop-package.ps1` 通过。
- `scripts\final-delivery-check.ps1` 通过。
- 真实两段式 DXM canary 通过。
- 最终 EXE 路径、Git HEAD、SHA-256、验收报告一致。

**建议完成度目标:** 从 97% 提升到 100%。

## 3. 推荐菜单结构

### 一级分组

1. 准备
2. 第一段：采集认领
3. 第二段：编辑保存
4. 现场执行
5. 结果复盘
6. 系统维护

### 菜单明细

| 分组 | 菜单 | 用户理解 | 子功能 |
| --- | --- | --- | --- |
| 准备 | 首页 | 今天先做什么 | 当前步骤、阻断原因、下一步按钮、最近结果 |
| 准备 | 店小秘登录 | 连接真实店小秘 | 账号密码、记住账号、打开登录页、检测登录状态 |
| 第一段：采集认领 | 数据采集认领 | 把商品放进采集箱 | 店铺平台、商品线索、搜索定位、认领、采集箱确认 |
| 第一段：采集认领 | 采集箱商品 | 管理已认领商品 | 已认领列表、来源链接、采集箱标题、可保存状态 |
| 第二段：编辑保存 | 模板中心 | 管理填写规则 | 多模板、中文分区表单、默认模板、执行取值预览 |
| 第二段：编辑保存 | 只保存任务 | 启动编辑保存 | 选择已认领商品、人工确认、启动保存、保存边界 |
| 现场执行 | 真实浏览器 | 看 Agent 操作现场 | 浏览器状态、HUD、人工接管、重试 |
| 结果复盘 | 结果报告 | 看保存结果 | 保存成功、未发布证明、证据摘要 |
| 结果复盘 | 问题处理 | 处理失败 | 失败原因、恢复动作、维护诊断 |
| 系统维护 | 系统设置 | 管理本机运行环境 | 数据目录、日志、资源自检、版本信息 |

### 不建议继续作为一级菜单

- Agent 控制台
- 任务中心
- 配置中心
- 证据中心
- 异常池
- L2 / L3
- 只读 Probe

这些技术概念可以保留，但只能放在“维护人员查看技术状态”里。

## 4. 模块拆分

### 4.1 店小秘登录模块

**功能:**
- 本机加密保存账号密码。
- 打开真实店小秘登录页。
- 检测是否已登录。
- 验证码或二次验证时等待用户处理。
- 登录成功后同步主窗口状态。

**必须修复的问题:**
- 浏览器已登录但控制台仍显示未登录。
- 登录失败时只显示技术异常。
- 重复打开登录页导致多个浏览器会话混乱。

### 4.2 数据采集认领模块

**功能:**
- 选择店铺和平台。
- 输入来源链接、关键词或商品线索。
- 打开店小秘数据采集页。
- 搜索或定位目标商品。
- 唯一匹配确认。
- 认领到采集箱。
- 打开采集箱确认。

**记录字段:**
- 店铺
- 平台
- 商品标题
- 来源链接
- 采集箱标题
- 认领标记
- 认领时间
- 认领证据

**阻断:**
- 未登录不能认领。
- 找不到商品不能认领。
- 多个匹配必须人工确认。
- 认领失败不能进入第二段。

### 4.3 采集箱商品模块

**功能:**
- 展示已认领商品列表。
- 展示来源链接和采集箱匹配关系。
- 标记哪些商品可进入编辑保存。
- 标记失败、过期、测试、未确认商品。

**阻断:**
- 非采集箱确认商品不能保存。
- 测试商品不能保存。
- 旧失败任务不能复用为新保存证据。

### 4.4 模板中心模块

**功能:**
- 多套模板管理。
- 店铺默认模板。
- 类目默认模板。
- 手动选择模板。
- 本次任务覆盖。
- 默认示例模板。
- 最终执行取值预览。

**页面原则:**
- 首屏只显示当前模板、保存状态、可启动状态。
- 默认只展开一个分区。
- 模板匹配解释默认折叠。
- 英文字段 key 不出现在普通用户界面。

### 4.5 只保存任务模块

**功能:**
- 从采集箱商品创建保存任务。
- 选择模板。
- 展示最终执行取值。
- 人工确认只保存。
- 启动真实浏览器 Agent。
- 保存成功后生成报告。

**阻断:**
- 未认领不能启动。
- 未确认采集箱不能启动。
- 模板缺失不能启动。
- 未人工确认不能启动。
- 发布风险出现立即停止。

### 4.6 真实浏览器模块

**功能:**
- 显示真实浏览器状态。
- 显示 Agent 状态。
- 显示 HUD 在线状态。
- 支持人工接管。
- 支持保留现场。
- 支持失败后重试。

**核心原则:**
- 浏览器显式。
- 现场可见。
- 失败不闪退。
- 状态可恢复。

### 4.7 结果与问题模块

**功能:**
- 保存成功报告。
- 未发布证明。
- 认领失败报告。
- 保存失败报告。
- 恢复建议。
- 维护诊断。

**报告字段:**
- 商品标题
- 店铺
- 平台
- 来源链接
- 采集箱确认状态
- 模板名称
- 保存结果
- 未发布状态
- 操作时间
- 证据摘要

## 5. 代码实施计划

### Task 1: QA 脚本两段式化

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\scripts\qa-browser-check.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_qa_runtime_data_isolation.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_frontend_demo_workflow_contract.py`

- [ ] 写测试：脚本不能包含 `QA local gated single_save one product fixture`。
- [ ] 写测试：脚本必须使用 `/api/acquisition/claim-requests`。
- [ ] 写测试：脚本必须使用 `/api/acquisition/claimed-products` 检查第二段候选。
- [ ] 删除脚本中直接创建 fake `single_save` 的逻辑。
- [ ] 把 QA 验证改成：无真实 claimed product 时验证第一段路径和空态，不伪造生产保存任务。
- [ ] 运行 `pytest tests\test_qa_runtime_data_isolation.py tests\test_frontend_demo_workflow_contract.py -q`。
- [ ] 运行 `npm run build`。
- [ ] 提交：`test: align browser QA script with two-stage workflow`。

### Task 2: 导航和首屏收口

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\AppShell.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\SafetyStatusBar.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\HomePage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\styles.css`

- [ ] 按本计划第 3 节重做侧边栏。
- [ ] 顶部状态条只保留一个主结论、一个主按钮、一个阻断原因。
- [ ] `状态详情` 改为折叠或右侧抽屉。
- [ ] 首页只显示当前步骤、为什么不能继续、下一步。
- [ ] 技术字段进入维护诊断。
- [ ] Playwright 或浏览器 DOM 检查首屏无技术术语。
- [ ] 提交：`feat: simplify two-stage production navigation`。

### Task 3: 第一段数据采集认领闭环

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AcquisitionClaimPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\repository.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_acquisition_claim_workflow.py`

- [ ] 测试：创建认领任务时不创建 fake 商品。
- [ ] 测试：认领完成后记录 claimed product、source_url、store、claim_mark。
- [ ] 测试：认领失败时不能进入第二段。
- [ ] UI：数据采集认领页只表达第一段，不出现保存入口。
- [ ] 真实浏览器：认领后打开采集箱确认。
- [ ] 运行 `pytest tests\test_acquisition_claim_workflow.py tests\test_v1_runner.py -q`。
- [ ] 提交：`feat: complete acquisition claim stage`。

### Task 4: 第二段采集箱编辑保存闭环

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\DraftEditSavePage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\main.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\v1_runner.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_task_start_guard.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_v1_runner.py`

- [ ] 测试：`single_save` 必须绑定 claimed product。
- [ ] 测试：未人工确认不能启动。
- [ ] 测试：发布风险按钮出现时停止。
- [ ] UI：采集箱编辑保存页五步清晰展示。
- [ ] 后端：保存报告关联第一段 claimed product。
- [ ] 真实浏览器：执行只保存并验证未发布。
- [ ] 运行 `pytest tests\test_task_start_guard.py tests\test_v1_runner.py -q`。
- [ ] 提交：`feat: complete draft edit save stage`。

### Task 5: 模板中心生产化

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\template_center.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\TemplateCenterPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\types.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_template_center_contract.py`

- [ ] 测试：模板取值优先级正确。
- [ ] 测试：普通用户字段全部中文。
- [ ] 测试：多模板保存、复制、停用、设默认。
- [ ] UI：顶部固定显示当前模板、保存状态、执行取值状态。
- [ ] UI：默认只展开一个分区。
- [ ] UI：分区动作固定为仅本次、店铺默认、类目默认、另存、套用示例。
- [ ] 运行 `pytest tests\test_template_center_contract.py -q`。
- [ ] 运行 `npm run build`。
- [ ] 提交：`feat: productionize customer templates`。

### Task 6: 浏览器 Agent 常驻和 HUD

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\services\browser_agent_status.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\src\execution\dxm_login_flow.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AgentExecutionPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_agent_console.py`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_browser_agent_status.py`

- [ ] 测试：HUD 中文业务步骤映射。
- [ ] 测试：HUD 注入脚本包含固定 root id 和高 z-index。
- [ ] 实现：页面跳转后重注入 HUD。
- [ ] 实现：Agent 异常时不主动关闭浏览器。
- [ ] 实现：主窗口显示浏览器、Agent、HUD 三个状态。
- [ ] 使用真实浏览器验证 HUD 常驻。
- [ ] 提交：`feat: keep browser agent visible and recoverable`。

### Task 7: 日志和错误用户化

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\ResultsPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\IssuesPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\components\workbench\AgentExecutionPage.tsx`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend\src\api.ts`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend\tests\test_frontend_api_error_contract.py`

- [ ] 测试：主界面不暴露原始技术异常。
- [ ] 实现：错误结构为发生了什么、为什么停止、下一步怎么做。
- [ ] 实现：实时日志默认只显示业务事件。
- [ ] 实现：完整原始日志进入维护诊断。
- [ ] 验证：用户截图中的日志重叠问题消失。
- [ ] 提交：`feat: make runtime failures customer actionable`。

### Task 8: 免安装包和最终验收

**Files:**
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\scripts\verify-desktop-package.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\scripts\final-delivery-check.ps1`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\最终交付验收记录-20260625-两段式生产版.md`
- Modify: `D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\docs\product\免安装版快速使用说明-20260625.md`

- [ ] 运行后端 focused tests。
- [ ] 运行前端 `npm run build`。
- [ ] 运行桌面 `npm run build:portable`。
- [ ] 覆盖 `D:\Desktop\DXM-Agent-Console-免安装版`。
- [ ] 运行 `scripts\verify-desktop-package.ps1`。
- [ ] 打开 EXE 做真实 DXM 两段式验收。
- [ ] 记录 Git HEAD、EXE SHA-256、真实验收证据。
- [ ] 提交：`docs: record production two-stage portable acceptance`。
- [ ] 推送分支。

## 6. 测试矩阵

### 后端

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\backend
.\.venv\Scripts\python.exe -m pytest tests\test_acquisition_claim_workflow.py tests\test_v1_runner.py tests\test_task_start_guard.py tests\test_delivery_workspace.py tests\test_template_center_contract.py -q
```

### 前端构建

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\frontend
npm run build
```

### 桌面打包

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage\app\desktop
npm run build:portable
```

### 免安装包验证

```powershell
cd D:\Desktop\py\dxm-auto-uikit\.worktrees\dxm-production-two-stage
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180
```

### 真实验收

```text
1. 双击免安装 EXE。
2. 登录店小秘。
3. 第一段：创建数据采集认领任务。
4. 真实浏览器认领商品到采集箱。
5. 第二段：选择采集箱商品。
6. 确认模板和执行取值。
7. 人工确认只保存。
8. 真实浏览器执行保存。
9. 结果页显示保存成功。
10. 结果页显示未发布证明。
```

## 7. 完成判定

只有全部满足以下条件，才算项目完成到客户可交付状态：

1. 双击免安装 EXE 可启动，不需要两个命令行窗口。
2. 店小秘真实浏览器显式打开并保持在线。
3. 浏览器 HUD 常驻，中文显示实时步骤。
4. 第一段真实完成：数据采集认领到采集箱。
5. 第二段真实完成：采集箱编辑商品并只保存。
6. 保存成功证据存在。
7. 未发布证明存在。
8. 模板中心支持多套模板、中文分区、保存状态、执行取值预览。
9. 普通用户主路径不暴露工程术语。
10. 失败时用户能看懂下一步怎么处理。
11. 发布、批量、无人值守在 UI 和 API 双层阻断。
12. 后端 focused tests 通过。
13. 前端 build 通过。
14. 桌面 package 验证通过。
15. 真实验收报告、Git HEAD、EXE SHA-256 三者一致。

## 8. 当前最优下一步

不要先继续做视觉微调。下一步应先做 **Task 1: QA 脚本两段式化**，因为当前脚本仍残留直接创建 `single_save` 的测试路径。这会持续污染验收、误导界面状态，也会让客户以为系统是从测试商品开始，而不是从真实数据采集认领开始。

完成 Task 1 后，再推进导航和首屏收口。原因是只有底层脚本和任务来源可信，UI 收口才不会继续围绕错误状态做补丁。
