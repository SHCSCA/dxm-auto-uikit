# Task 1A2-B：后端所有权与精确关闭验收报告

## 结论

Task 1A2-B 已把后端数据目录租约、Electron 精确父通道、Windows Job 进程树所有权，以及 Electron 对唯一 authoritative backend child 的有界关闭链和被拒绝 newcomer 的 exact cleanup 闭合。当前源码门禁、纯合同测试、完整后端回归和真实 Windows 子进程证明均通过；本阶段没有启动 Electron、浏览器、DXM，也没有构建或宣称 portable/production READY。

Phase 1A2-A 的最终质量修复提交为 `9ff20ae`，其独立复审已清零阻断问题；后端 ownership/bootstrap 基础随后完成到 `02e04d9`。本报告所述 Electron 精确关闭工作以 `02e04d9` 为固定审查点，最终规格轴和质量轴均无 P0/P1。

## RED / GREEN

### RED

- 精确关闭控制器落地前，首批 8 个纯 Node 合同为 `0/8`：缺少独立 shutdown controller，无法证明 START 一次性写入、共享 termination promise、优雅 close、超时 exact-child kill、exit/close 乱序、stale ownership 惰性以及 before-quit 幂等。
- 后续审查 RED 依次锁定并修复：`fs.createWriteStream()` 异步 open error 逃逸、setup close barrier 安装过晚、opened log error 的 setup/exact/stale 副作用混淆，以及旧 backend 的迟到日志错误污染当前实例退出状态。
- 首轮双轴复审发现 spawn 已返回但 ownership 尚未发布时，before-quit/QA 看不到局部 setup cleanup，会提前放行；对应合同先以缺少 `registerSpawnSetup` 及陈旧 runtime-control key 两项 `0/2` 失败，再实现 pending setup authority。
- 增量质量复审继续发现两个 P1：API 允许 old current 与 newcomer pending 并存时 current-first 终止会漏等 newcomer；`registerSpawnSetup()` 位于 `try` 外且在 active-pending 冲突前没有先为 newcomer 安装 barrier。两项均先以 coded error 缺失和静态顺序错误稳定 RED，再收紧为“先装 exact barrier，冲突只清理 newcomer，错误携带同一 cleanup promise，由 main catch 等待”。
- 父环境中的 mixed-case `DXM_RUNTIME_CONTROL_COMMAND_FILE` 曾进入 Electron backend，使其误报为 launcher-managed；环境合同先失败，再改为大小写不敏感清除。
- 仅测试引用的旧 `clearOwnershipForChild` 仍表达“exit 即清空”的过时规则；已先改合同再删除，所有权现在只在 exact `close` 时释放。
- 一次完整 pytest 重跑被外层工具 13 秒超时打断并返回 `124`；该结果没有计入代码 RED 或 GREEN。随后以独立后台进程、持久 stdout/stderr 和退出码重新验证。
- P1 修复期间启动的一轮 full pytest 跨越了源码变更，即使最终返回 `1211 passed` 也没有计作冻结工作树证据；最终代码冻结后使用全新 data directory 从头重跑。

### 最终 GREEN（当前工作树）

| 门禁 | 结果 |
| --- | --- |
| 完整 backend | `1211 passed in 496.61s (0:08:16)`，exit `0` |
| shutdown 聚焦合同 | `35 tests / 35 pass / 0 fail`（另以 `--unhandled-rejections=strict` 复核） |
| 完整 desktop Node | `89 tests / 89 pass / 0 fail` |
| desktop package contract | `40 passed in 0.14s` |
| 真实 `desktop_server` graceful + Windows EOF/Job proof | `2 passed in 7.56s` |
| frontend production build | exit `0`；49 modules；Vite `built in 1.94s` |
| Node 语法 | 7/7 变更 CJS 文件 `node --check` 通过 |
| Python 语法 | process proof 与 EOF fixture 2/2 `py_compile` 通过 |
| diff/遗留符号 | `git diff --check` exit `0`；`terminateExactOwnedBackend`、`createBackendChildLifecycle`、`requestExactBackendTermination`、`clearOwnershipForChild` 均 0 命中 |
| 孤儿进程 | process proof 前后均无匹配 backend/probe/120 秒 descendant 的 Python 残留 |

最终 full pytest 在 `app/backend` 下执行：`$env:DXM_DATA_DIR='<repo>/output/codex-evidence/b2-final-verified-20260715-final/data'; .venv/Scripts/python.exe -m pytest -q`。该目录全新且隔离，没有复用旧数据库或 artifact；本轮工具终端摘要和其余门禁已转录到同级 `verification-summary.md`，但它不是原始 stdout。`output/**` 是本地证据，不纳入提交；7 月 14 日的持久 stdout/exit 文件仅保留为修复前历史证据，不用于本报告最终 GREEN。

## 唯一启动顺序

1. Electron 先完成 Phase A 参数分类、`userData` 选择和 single-instance lock；失败时不创建 backend。
2. Electron 冻结 build/runtime identity 和精确环境，使用 `python -m src.desktop_server` 启动唯一子进程，`stdio` 固定为三条 pipe。
3. `spawn()` 返回后的第一个同步动作是在 shutdown controller 中为 newcomer 安装 pending setup authority；若 old current 或另一 pending authority 已存在，只清理 newcomer，错误携带可等待的 exact cleanup promise，不覆盖旧权威。
4. backend 日志文件必须先通过异步 open gate；open error、close-before-open 或 timeout 都在输出绑定、ownership handoff 和 START 前 fail closed。startup、QA 与 before-quit 在该窗口通过同一 current-or-pending 入口复用 setup cleanup promise。
5. handoff 只接受同一 child/authority，并原子地从 setup listeners 转移到 owned exit/close/error/stdin listeners；随后只向该 `child.stdin` 写一次 `START <instanceId>\n`，并等待 write callback。
6. `src.desktop_server` 有界读取并精确校验 START，发布进程内 armed channel，随后才构造固定目标 `uvicorn.Config("src.main:app", ...)`。
7. server 先 attach 到 channel，再由 `run_if_not_shutdown(server.run)` 线性化“早到 SHUTDOWN”和“允许导入 app”的竞态。
8. `src.main` 顶部先调用唯一 `ensure_runtime_bootstrap()`；其后才导入数据库、artifact、Browser Agent 和业务服务模块。
9. bootstrap 顺序固定为：无写入解析 owner/channel -> 冻结 identity 与 canonical paths -> 仅创建 canonical data root -> 获取 live data lease -> Windows Electron 创建/配置/绑定 Job -> 创建其余运行目录。
10. 完成所有权步骤后才允许 artifact mount、`init_db()`、repository/thread pool/Browser Agent/Agent Console 构造；health 再由 Electron 对 exact PID、instance、路径、manifest 和 fingerprint 做验证。

## Owner matrix

| owner | desktop 标记 | stdin-v1 | Windows Job | data lease |
| --- | --- | --- | --- | --- |
| `electron_desktop` | 必须 `DXM_DESKTOP=1` | 必须有进程内 armed channel 且 instance 一致 | Windows 必须成功，否则 fail closed | 必须 |
| `package_probe` | 不得冒充 desktop | 不要求 | 不声称 Windows 所有权 | 必须 |
| `start_mvp` | 不得冒充 desktop | 不要求 | 不要求 | 必须 |
| `direct` | 不得冒充 desktop | 不要求 | 不要求 | 必须 |

`DXM_DESKTOP=1` 但 owner、protocol、armed channel 或 instance 任一不匹配时，在创建 data root 前失败。Electron 环境构造会先大小写不敏感地删除陈旧 owner/desktop/channel/port 以及 `DXM_RUNTIME_CONTROL_COMMAND_FILE`，再写入唯一合同，避免 desktop backend 冒充 start-mvp launcher-managed 实例。

## 数据租约、父通道与 Job 语义

### RuntimeDataLease

- `<canonicalDataDir>/.dxm-runtime.lock` 是永久文件；live OS lock 才是权威，陈旧文件和 JSON metadata 不能阻止 takeover，也不会被删除。
- Windows 锁严格覆盖 byte `[0,1)`；不同长度 metadata 不改变权威区间。descriptor/handle 不可继承。
- 创建 canonical data root 是持锁前唯一允许的目录写入；SQLite、artifact、服务和浏览器 profile 均在租约后。
- production lease 保存在模块进程全局，FastAPI lifespan 退出不会释放；`release()` 只供隔离测试/显式 app-factory owner。

### stdin-v1 parent channel

- 环境变量只表示请求；唯一证明是进程内 armed channel。
- 首行必须精确为 `START <instanceId>\n`。EOF、unknown、oversize 或 instance mismatch 均在 `src.main` import 前失败。
- `SHUTDOWN\n` 原子设置 pending shutdown；已 attach 时设置 `server.should_exit=True`，reader 立即返回，Electron 可继续保持 writer 打开直到 child close。
- parent EOF 走 `os._exit`，由 OS 回收 lease、port 和 backend-owned Job；不轮询或猜测 parent PID。

### Windows Job

- backend 自己创建 unnamed、non-inheritable Job，设置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，再把当前 backend 进程分配进去。
- 创建、limit 或 assignment 任一失败都保留 stage/GetLastError 并使 desktop 启动失败；没有 process-tree 降级声明。
- 成功 handle 为进程全局，不由 context manager、`finally`、lifespan 或 `atexit` 主动关闭，避免 backend 在清理中自杀。

## Electron exact-child 关闭合同

- ownership record 绑定 exact `ChildProcess`、PID、instance 和 expected/verified identity，并记录 START、termination、exit、close、SHUTDOWN 和 kill facts。
- ownership handoff 前的 child 不是局部或第二套权威：controller 持有唯一 pending setup record；注册冲突先为 newcomer 安装 barrier，再只终止 newcomer，old current/首个 pending 均不被覆盖或误杀。
- 对同一个 exact child scope，startup failure、QA deadline、重复 quit 和 before-quit 复用同一个 `terminationPromise`；被拒绝的 newcomer 使用自己的 exact cleanup promise，不会与 old current/首个 pending 混用。
- 已完成 ownership handoff 的 exact current child 首次终止时向 stdin 写一次 `SHUTDOWN\n`，在 grace deadline 内等待 `close`；仅当它仍 live 时调用一次 `child.kill()`，随后再进行 final bounded wait。pending setup child 不声称 graceful protocol，直接关闭 stdin、kill exact newcomer 一次并等待 bounded close。
- `kill()` 返回值不释放 authority；`exit` 只记录事实并阻止再次 kill；只有 exact `close` 才清空 current ownership、结束日志并完成终止 promise。
- unexpected exact exit/pipe failure 会使 startup/runtime 失效；已请求终止后的正常事件不重复 invalidation。stale/unrelated child 的事件、timer 和迟到日志错误均惰性。
- before-quit 会阻止所有早期 quit，等待当前 exact child scope 的 promise settle，然后只允许一次 final `app.quit()`；清理失败会设置 native failure exit，但不会把 Electron 永久困在 quit 循环。
- 未完成 ownership handoff 的 spawned child 由 controller 的 pending authority 管理：关闭 stdin、仅 kill exact child 一次、等待 bounded close；startup、QA、before-quit 和 main catch 复用同一 promise，晚到 close 仍只结束日志一次。

## 真实进程证明

- Graceful：真实 `src.desktop_server` 通过 START 与 health 后持有 lease/port；发送 SHUTDOWN 时 Electron 模拟 writer 仍保持打开，FastAPI cleanup marker 在 child close 前出现；child exit `0` 后 lease 与 port 均可重新获取。
- Forced EOF（Windows）：真实 `electron_desktop` bootstrap 证明 backend 与 120 秒 harmless descendant 同属 backend-owned Job，而 pytest parent 不在该 Job；关闭 parent stdin 后 backend exit `72`，backend 与 descendant 均在自然 TTL 前退出，lease/port 可重新获取，测试兜底 cleanup 未被使用。

## 实现与测试变更文件

后端所有权基础（`5cc92de` 至 `02e04d9`）：

- `app/backend/src/core/config.py`
- `app/backend/src/desktop_server.py`
- `app/backend/src/main.py`
- `app/backend/src/services/desktop_parent_channel.py`
- `app/backend/src/services/runtime_bootstrap.py`
- `app/backend/src/services/runtime_lease.py`
- `app/backend/src/services/windows_job.py`
- `app/backend/tests/fixtures/windows_job_owner.py`
- `app/backend/tests/test_desktop_parent_channel.py`
- `app/backend/tests/test_desktop_server.py`
- `app/backend/tests/test_health.py`
- `app/backend/tests/test_runtime_bootstrap.py`
- `app/backend/tests/test_runtime_lease.py`
- `app/backend/tests/test_runtime_lifespan.py`
- `app/backend/tests/test_windows_job.py`

本次 exact shutdown 收口：

- `app/desktop/src/backend-shutdown.cjs`
- `app/desktop/src/main.cjs`
- `app/desktop/src/runtime-identity.cjs`
- `app/desktop/src/runtime-start.cjs`
- `app/desktop/test/backend-shutdown.test.cjs`
- `app/desktop/test/runtime-identity.test.cjs`
- `app/desktop/test/runtime-start.test.cjs`
- `app/backend/tests/test_desktop_package_contract.py`
- `app/backend/tests/test_desktop_server_process_contract.py`
- `app/backend/tests/fixtures/desktop_server_windows_eof_probe.py`

验收与进度文档：

- `.superpowers/sdd/task-1a2b-backend-ownership-report.md`
- `.superpowers/sdd/progress.md`

## 独立复审

### Spec 轴

- 最终复审 PASS，P0/P1 为 0。复审逐项确认 pending registration、termination-wins handoff、registration conflict newcomer-only cleanup、main catch 等待 exact error promise、环境清洗和报告存在性符合 brief；未发现有害 scope creep。

### Standards / quality 轴

- P0/P1：无；仓库没有额外文档化代码规范，当前 diff 通过 smell baseline 审查。
- 非阻断 P2：ownership 仍以多字段 mutable facts 表达；`backend-shutdown.cjs` 同时包含日志门禁、setup cleanup、精确关闭与 before-quit。下一阶段设计显式任务/运行时状态机时应避免继续扩大该文件，但本阶段不为形式拆分引入高风险重写。
- 非阻断 P3：三处安全 diagnostic wrapper 形状重复，可在后续无行为变更的清理中抽取。

审查过程中已修复的 P1：异步日志 open failure 逃逸；旧实例迟到日志错误污染当前实例；setup close barrier 与 log close 的晚到竞态；spawn-to-handoff 窗口不可见；current/pending 并存时漏等 newcomer；registration 在受控 `try` 外。最终 Spec 与 quality 增量复审均 PASS，P0/P1 清零。

## 明确延期与禁止声明

- Phase 1A2-C launcher/PowerShell/smoke cleanup 未编辑。
- Task 1B 的 task/runtime/mutation authorization 绑定未在本阶段实现。
- Task 2 的任务、作业、异常和晚到结果状态机未在本阶段实现。
- Task 3 Browser Agent command ownership、常驻、恢复和正确 session binding 未在本阶段实现。
- Task 4 版本化模板 snapshot、业务示例隔离和逐字段非空精确读回未在本阶段实现。
- 低噪音前端工作流重构与视觉验收未在本阶段实施。
- Task 6 同一 Git HEAD 的 portable build、真实单商品 canary、未发布证明和不可变 manifest 未执行。

因此本报告只证明 Task 1A2-B 的 backend/runtime ownership 与 exact shutdown；不得据此显示 portable、真实两阶段业务或 production READY。
