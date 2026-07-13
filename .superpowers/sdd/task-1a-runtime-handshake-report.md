# Task 1A 运行时身份握手交付报告

日期：2026-07-13
分支：`fix/dxm-two-stage-runtime-truth`

## 结果

Task 1A 已实现并通过自动化验证：backend 在进程启动时冻结一份非空、可复算的 v1 `RuntimeIdentity`；`/health`、`/api/runtime/status.runtimeIdentity` 与 `/api/runtime/status.backend.runtimeIdentity` 返回相同身份值；Electron 在启动 backend 后以完整 launch-known 字段、真实 `child.pid`、规范 UTC `startedAt` 和完整 fingerprint 验证健康响应，再保存 backend 返回的已验证身份。

本子任务没有启动浏览器、Electron、真实 DXM 动作，也没有构建 portable。运行时唯一所有权仍未闭环；Task 1A2 是关闭 Task 1 前的硬前置，详见“明确暂缓边界”。

## 冻结的身份形状

Schema：`dxm.runtime.identity.v1`

```text
schemaVersion
instanceId
gitHead
gitDirty
buildId
packageVersion
packageSha256          # 非 portable/direct/unpacked 为 null
backendPid
browserAgentPid        # 当前真实等于 backendPid
browserExecutionModel # in_process_thread
dataDir
workflowProfileDir
resourceRoot
startedAt
fingerprint
```

`fingerprint` 是前 14 个字段的 canonical JSON SHA-256：递归键排序、UTF-8、保留非 ASCII、无多余空白、标准 JSON null/boolean、规范 UTC 毫秒时间、规范绝对路径和大写 SHA-256。Python 与 Node 共用 `runtime_identity_golden_vector.json`，包含中文、非 ASCII、Windows/UNC/POSIX 路径和固定 fingerprint。

直接启动默认只做一次实时 Git 读取；失败时冻结为 `gitHead=unknown`、`gitDirty=true`、`buildId=direct-<instanceId>`，不会自动读取 `outputs` 中可能遗留的 manifest。显式注入或 packaged 模式使用 `dxm.desktop.build.v1` manifest；packaged 缺失、字段/版本/schema/fingerprint 不匹配均在 spawn 前失败。

Portable 外层 SHA 仅在 packaged portable 的三个环境标记完整且一致、外层路径为绝对 regular file、并且与内部 `process.execPath` 不同时流式计算一次；direct、win-unpacked 或 installer 返回 null，不用 `process.execPath` 冒充外层包。backend 环境在展开父环境后按 Windows 大小写不敏感规则清除所有陈旧身份键，再写入本次冻结值。

## TDD 证据

### RED

1. Backend identity/health 首轮：

   ```powershell
   app\backend\.venv\Scripts\python.exe -m pytest tests/test_runtime_identity.py tests/test_health.py -q
   ```

   结果：collection 失败，`ModuleNotFoundError: No module named 'src.services.runtime_identity'`。

2. Desktop pure Node 首轮：

   ```powershell
   npm --prefix app/desktop test
   ```

   结果：缺少 `src/runtime-identity.cjs`，测试失败。

3. Desktop package contract 首轮：缺少 prebuild metadata、packaged manifest、完整 health handshake 和精确 ChildProcess ownership，共 4 项失败。

4. 后续小步 RED 覆盖了跨语言路径规范化、canonical UTC manifest 时间、portable 标记不完整、unknown/non-object manifest、完整返回身份、自校验 fingerprint、有效 PID 的 `error` 语义、mixed-case 陈旧环境键、child 在健康轮询间退出、late health response、exit/close 日志流与 frontend 类型合同。每项均在对应生产实现前观察到失败，再最小实现转绿；其中合法 JSON 但非 object 的 manifest 用例先稳定复现为 3 项 `AttributeError`，补显式 object guard 后 3 项通过。

### GREEN

最终验证：

```powershell
app\backend\.venv\Scripts\python.exe -m pytest tests/test_runtime_identity.py tests/test_health.py tests/test_desktop_package_contract.py -q
# 43 passed

app\backend\.venv\Scripts\python.exe -m pytest tests/test_task_start_guard.py -q -k runtime_status
# 14 passed, 106 deselected

app\backend\.venv\Scripts\python.exe -m pytest -q
# 1072 passed in 276.49s (0:04:36)

npm --prefix app/desktop test
# 14 passed

npm --prefix app/frontend run build
# tsc --noEmit + Vite build passed

git diff --check
# passed; only existing Git LF/CRLF notices, no whitespace error
```

另有 backend `tests/test_task_start_guard.py` 整文件回归：`120 passed`。

## 文件

Backend：

- `app/backend/src/services/runtime_identity.py`
- `app/backend/src/main.py`
- `app/backend/src/models.py`
- `app/backend/tests/test_runtime_identity.py`
- `app/backend/tests/fixtures/runtime_identity_golden_vector.json`
- `app/backend/tests/test_health.py`
- `app/backend/tests/test_task_start_guard.py`
- `app/backend/tests/test_desktop_package_contract.py`

Desktop/build：

- `app/desktop/src/runtime-identity.cjs`
- `app/desktop/src/main.cjs`
- `app/desktop/scripts/generate-build-manifest.cjs`
- `app/desktop/test/runtime-identity.test.cjs`
- `app/desktop/package.json`
- `app/desktop/electron-builder.yml`

Frontend：

- `app/frontend/src/types.ts`

## 进程所有权合同

- `startBackend` 只在 spawn 返回有效正 PID 后创建 ownership，持有 exact ChildProcess、instance ID 与 expected identity。
- health 成功前仅 exact current live child 可被启动清理；成功后还要求已验证 PID/instance/fingerprint 与完整 identity 相等。
- `error` 对已有有效 PID 只记录错误，不冒充退出；`exit`/`close` 仅能清除事件所属 exact current ChildProcess，日志流只在 `close` 结束一次。
- health 轮询有单一 settled 状态；timeout 或 owned child 退出后，迟到响应不能写入 verified identity。
- `.killed` 不作为退出或所有权证据；Windows 终止保持隐藏；没有加入 Chrome 路径扫描或终止。

## 明确暂缓边界

### Task 1A2：关闭 Task 1 前的硬前置

以下内容未在本提交实现，且未通过前不得宣称运行时唯一所有权闭环：

- Electron single-instance lock 与二次启动只聚焦已有窗口；
- backend 持有的 OS-level `dataDir` runtime lease；
- 普通/生产 8000 端口冲突 fail-closed，不递增、不接管、不杀未知进程；
- 8000–8079 legacy same-data-dir backend 检测；
- 严格隔离的 QA userData/dataDir/profile/dynamic-port 例外。

当前 `findFreePort(8000)` 等旧行为由 Task 1A2 串行收口，不属于本提交完成声明。

### Task 1B

未把授权批准、受控单保存或 task snapshot 绑定到 `RuntimeIdentity.fingerprint`；本提交只建立身份真相，不授权、不启动真实 DXM 任务。

### Task 3

`browserAgentPid` 只如实描述 backend 内的 Browser Agent thread，等于 `backendPid`。外部 Chrome PID、浏览器会话身份及其证明留给 Task 3，本提交未伪造或推断。

### Task 6

本提交只生成并验证 build manifest 及 portable 外层哈希逻辑；未构建、未 smoke、未验收大型 portable 包。固定包构建与可运行产物验证留给 Task 6。
