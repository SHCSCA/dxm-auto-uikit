> 由 OpenAI GPT（Codex）AI 生成/维护。

# CODEX 开发目标：免安装桌面版与全链路操作日志

- 编写日期：2026-08-14
- 当前状态：`IN_PROGRESS`（A–E 代码切片已落地并通过专项复验；portable 同 HEAD smoke 与完整 L0 仍未关闭）
- 后续关系：本目标完成后，用户才能在同源免安装桌面版中配置真实模板并生成新的三商品快照；真实保存另行批准，旧任务 `#191` 不复用。

以下内容可整体复制给开发 Agent：

```text
【1. 唯一目标】
在权威仓 D:\Desktop\py\dxm-auto-uikit 完成“Windows 免安装桌面交付 + 可持久化全链路操作审计”。用户只需双击 DXM-Agent-Console-Portable-<version>.exe，在中文控制台完成登录、店铺/类目/模板配置、预览冻结和任务控制；真实店小秘浏览器继续可见。系统必须把每一步从用户点击到 API、任务/商品、Runner、浏览器、网络摘要和证据结果串成同一时间线，并可导出脱敏诊断包。本目标不执行真实保存或发布。

【2. 已测基线与事实】
- 分支 fix/dxm-two-stage-runtime-truth，HEAD=416810f61ad0f038bdd5bde850ed1dd50300d354；开工重测身份和 status，不覆盖既有改动/52 个删除。
- backend/frontend/desktop 当前版本均 0.1.4；outputs/desktop-build 不存在，尚无当前 portable。
- app/desktop 已有 build:portable；scripts/verify-desktop-package.ps1 仍硬编码 0.1.0，必须改为从同一 manifest 解析版本/产物，禁止猜文件名。
- 已有 job_logs、job_evidences、reports、mutation ledger、runtime text logs、AgentConsole/BrowserAgent 事件；但日志分散，BrowserAgent 仅保留 50 条、AgentConsole 主要驻内存，不能完整复盘一次操作。
- E3 真实保存仍因按类目属性/运费/服务模板未配齐而 BLOCKED；E4 只有代码控制面，真机 DoD 未关闭；#191 保持 draft。

【3. 实施范围】
A. 建立 append-only `operation_audit_events`（名称可按现有迁移规范调整）：UTC 微秒时间、递增序号、event/correlation/causation/session/runtime/browser ID、actor/component/action/phase、task/job/batch/item/product/store/category、snapshot/command/mutation/lease/build 身份、reason/status、输入输出摘要、evidence refs、prev_hash/event_hash。提供 repository/service/API 合同、分页/筛选和重启恢复。
B. 接入必记节点：桌面启动/后端健康；登录与人工接管；页面切换；店铺/类目/商品/模板选择；配置增删改、校验、preview/freeze；审批与开始/暂停/继续/停止；每个 Runner step；导航、定位、字段写入与逐字段读回；保存点击前授权、网络回包摘要、页面成功态、未发布证明、异常/UNKNOWN、证据/报告落盘。配置阶段也必须记，不能只记保存阶段。
C. 记录策略：凭据、Cookie、Authorization、token、完整 HTML/原始响应永不入库/接口/导出；普通事件记录字段键、类型、长度、期望/观察 hash 与 match。失败证据只保留有界且脱敏的 DOM 摘要/截图。标准诊断包默认脱敏；“包含业务字段明文”须用户二次确认，但任何模式都不得包含密钥和会话秘密。
D. 写入规则：真实 mutation 前的 requested/authorized/dispatching 审计必须与权威状态成功持久化，否则 `AUDIT_WRITE_FAILED` 且零点击；点击后审计/证据不确定则记 `UNKNOWN`、停批、禁自动重试。只读/配置日志降级必须在 UI 显示 `AUDIT_DEGRADED`，不得静默。
E. 不新增第 8 个导航。复用“真实浏览器/结果与问题/系统设置”：实时中文时间线；按时间、任务、商品、组件、阶段、reason 搜索；展示关联 ID 和证据；一键导出 ZIP（manifest.json、events.jsonl、相关报告/证据、SHA256 清单、脱敏报告）。默认保留 90 天或 1GB（可配置）；活动任务、UNKNOWN 和最近一次诊断包不得被静默清理。
F. 桌面交付：修复动态版本验包；portable 双击后隐藏启动本机后端并加载内置前端，不要求用户安装 Python/Node、不把浏览器 URL 当产品入口。数据/日志在 %APPDATA%\DXM Agent Console\data，首次启动失败也写 desktop-main.log。输出 EXE、SHA256、build manifest、验收报告和一页用户说明。

【4. 边界与禁止】
- 只读接口取数、UI 写入、零发布、Path A、可见浏览器、三铁证、UNKNOWN 停批等主合同不变；不得加入 API 写 DXM、Path B、保存并发布或无人值守扩批。
- 不启动/克隆 #191，不登录 DXM，不保存、不发布；不把 mock、旧 portable、源码网页、目录版或绿色 build 冒充免安装验收。
- 不恢复既有删除，不清理用户文件，不修改 Gold/MVP 冻结边界；不得在日志中打印账号密码、Cookie、token 或完整请求体。
- 本目标不含 commit/push；若需形成 clean 固定提交和发布级包，先取得用户单独授权。

【5. 验收与反作弊】
- RED→GREEN：①注入 password/Cookie/token/Authorization，DB/API/ZIP 全部检索不到；②篡改/删序事件能报 hash-chain gap；③审计落盘失败时 mutation operation=0；④点击后证据失败变 UNKNOWN 且无下一商品；⑤重启后时间线、关联链和 UNKNOWN 不丢；⑥同一用户操作只生成一个 root correlation，重复请求保持幂等。
- Backend 全量 pytest 0 failed/0 skipped；frontend 标准 build（Node/Chromium/typecheck/Vite）、desktop npm test、文档 SelfTest、git diff --check 全绿。不得用 focused suite 代替全量。
- 在隔离 user-data 下做目录包和 portable smoke：无系统 Python/Node 依赖，启动→本地配置→preview dry-run→查看时间线→导出诊断包→重启读回；全程真实 DXM mutation=0。
- 获得 commit 授权后才运行 scripts\final-delivery-check.bat -RequireCleanWorktree -CheckPortableDesktop；报告必须同时解释 okScope、realDxmMutationScope、realDxmWriteReadiness、sourcePackageReadiness，不能只读 ok。
- 交付物必须绑定同一 source/build identity：portable 路径、大小、SHA256、manifest、测试日志、smoke 截图/诊断包；缺任一项只能标 DESKTOP_CANARY_BLOCKED，不能标 MVP_READY/PROD_READY。

【6. 执行与汇报规则】
先更新 PROGRESS.md 写开工身份/基线；每完成 A–F 一段就写实测命令、exit、计数、产物 hash。阻断写 BLOCKED.md，安全范围内继续其他项。不得覆盖历史结果，不得把旧证据绑定新 HEAD。最终报告分“代码、测试、portable、日志可追溯、真实 DXM 证据”五栏；本目标最后一栏必须是 0 保存/0 发布。完成后下一张任务才是：用户在新 portable 内配置真实店铺与类目分区模板，重新 preview/freeze 至少 3 件商品，再由用户批准 SAVE_ONLY canary。
```

## 规划后的用户实际流程

1. 双击免安装 EXE，不需要打开 PowerShell，也不需要访问 `localhost` 网页。
2. 在中文控制台登录店小秘并选择真实店铺、类目和商品。
3. 为每个类目选择店小秘已有的产品属性、运费、服务等模板；填写值在控制台中文映射，真正写入店小秘的内容按业务要求使用英文。
4. 系统完成校验、预览和冻结；每次点击、选择、校验与异常都进入同一审计时间线。
5. 出现问题时，在“结果与问题”按任务/商品查看链路，或导出脱敏诊断 ZIP 交给开发排查。
6. 配置确认后创建新三商品任务；真实只保存必须再次取得明确批准，且任何 `UNKNOWN` 立即停批。

## 2026-08-19 复核记录

- 当前权威仓：`D:\Desktop\py\dxm-auto-uikit`；分支：`fix/dxm-two-stage-runtime-truth`；复核前 HEAD：`416810f61ad0f038bdd5bde850ed1dd50300d354`。
- 已复验：backend 审计/E4/模板/派发专项 `39 passed`；frontend Node `27 passed`、browser harness `9 passed`、typecheck 通过；desktop `92 passed`；均为隔离数据或离线测试，真实店小秘保存/发布为 `0/0`。
- 未宣称：完整 backend L0 未绑定本轮新提交重新跑绿；`outputs\desktop-build` 当前不存在；portable smoke、真实登录、三商品 preview/freeze/save 与 `MVP_READY` / `PROD_READY` 均未完成。
- 用户已明确授权本次分支整理、文档同步、提交、推送；该授权不改变零发布、可见浏览器、三铁证和 `UNKNOWN` 停批边界。
