# L2 只读 Probe 门禁

更新时间：2026-07-22

## 目标

L2 只读 probe 只验证真实登录态、商品箱页面可达性、DOM/按钮文本和证据文件。它不点击、不输入、不编辑、不保存、不发布。

L2 是 `single_save` 和 `controlled_edit_batch` 的保存前安全检查，不是 mutation 授权。通过后仍需服务端批准、实时 browser/session/page/target 复核、持久化 mutation ledger 和动作结果证据。

## 运行命令

只有用户明确批准真实只读探测后才运行：

```powershell
Set-Location <PROJECT_ROOT>
$runId = "l2-real-" + (Get-Date -Format "yyyyMMddTHHmmssZ")
$cookieFile = Join-Path $env:APPDATA "DXM Agent Console\data\sessions\dianxiaomi_cookies.json"
app\backend\.venv\Scripts\python.exe tools\probes\l2_readonly_probe.py --target draft_box --run-id $runId --cookie-file $cookieFile --output-dir data\l2_readonly_probe --allowlist-file config\l2_readonly_allowlist.json --headed
```

当前唯一目标是 `draft_box`。证据必须由当前脚本、当前 Git HEAD 和当前 cookie/session fingerprint 生成。缺少 `evidence_binding` 或 run metadata 的历史结果只能用于诊断。

离线/mock 验证使用本地 URL：

```powershell
app\backend\.venv\Scripts\python.exe tools\probes\l2_readonly_probe.py --target draft_box --url file:///C:/path/to/mock.html
```

## 门禁断言

- `ok == true` 且 `safety.ok == true`
- 登录 cookie 已加载，且页面不疑似登录页
- `target_url` 与 `final_url` 都停留在商品箱路径
- `network.write_request_count == 0`
- `network.non_read_request_count == 0`
- `network.blocked_request_count == 0`
- `network.forbidden_keyword_request_count == 0`
- `network.websocket_count == 0`
- `evidence_binding.schema == dxm_l2_evidence_binding.v1`
- `evidence_binding.target_set == ["draft_box"]`
- `run_id`、`script_sha256`、`git_head`、`session_fingerprint_sha256` 非空且与结果顶层一致
- JSON、Markdown、截图和 DOM 存在；截图与 DOM 的 SHA-256 必须重算一致
- 证据不得超过当前时效上限，也不得出现未来时间

## Allowlist

`config/l2_readonly_allowlist.json` 只批准已审计的 DXM SPA 启动读取依赖。查询型 POST 必须精确标注 `readonly_post=true`，并绑定 host/path/resource type/reason；它不会放行任何真实业务写入。

当前 allowlist 不再包含旧页面专用依赖。防御性禁词仍保留 `claim`、`note`、`remark`、`save`、`publish` 等关键词，目的是阻止 L2 意外进入任何写入路径，不代表产品仍提供这些旧功能。

精确第三方遥测 denylist 可以在发出前 abort 并记录到 `network.suppressed_requests`，但不得用于 `dianxiaomi.com` 业务请求。

## 禁止范围

- 不点击编辑、保存、发布或其他业务动作
- 不填写输入框、不搜索商品、不切换店铺、不勾选半托管
- 不允许普通 `POST`、`PUT`、`PATCH`、`DELETE`
- 不允许 WebSocket、EventSource、Service Worker 绕过路由门禁
- 不忽略真实站点 HTTPS 证书错误
- 不使用 `tools/probes/**/tmp_*` 临时脚本
- 不因 L2 `passed` 自动创建、批准、恢复或重试真实保存
- ledger 存在 `UNKNOWN` 或未对账动作时继续阻断

## 输出与诊断

产物写入 `data/l2_readonly_probe/`，受 `.gitignore` 保护。截图和 DOM 可能包含本地敏感信息，只用于交付审查。

`diagnostics` 至少包含：

- `strict_pass_checks`
- `navigation`
- `render_state`
- `blocked_request_groups`
- `allowlisted_request_groups`
- `suppressed_request_groups`
- `allowlist_review_candidates`

最终自检生成 `l2-allowlist-review-template.md/json` 供人工评审。模板不是 L2 通过证明；任何 allowlist 变更都必须重新运行真实商品箱 L2。

## 证据等级

- A：登录态、商品箱目标、binding、JSON/Markdown/截图/DOM/hash 与零写网络摘要全部通过。
- B：仅离线/mock 证据，或真实页面存在已阻断的只读依赖；不能解锁 L3。
- 不通过：任何写方法、禁词命中、路径漂移、登录失效、证据缺失/失配、binding 不完整或过期。
