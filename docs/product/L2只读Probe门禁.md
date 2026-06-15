# L2 只读 Probe 门禁

## 目标

L2 只读 probe 只用于验证登录态、目标页面可达性、DOM/按钮文本和截图证据。它不得写备注、不得认领、不得保存、不得发布。

## 运行命令

真实店小秘 L2 只读探测仍会打开真实页面。只有在用户明确批准“执行 L2 真实只读探测”后才运行以下命令；它不会点击、输入、认领、备注、保存或发布。

```powershell
Set-Location <PROJECT_ROOT>
$runId = "l2-real-" + (Get-Date -Format "yyyyMMddTHHmmssZ")
app\backend\.venv\Scripts\python.exe tools\probes\l2_readonly_probe.py --target data_acquisition --run-id $runId --cookie-file data\sessions\dianxiaomi_cookies.json --output-dir data\l2_readonly_probe --allowlist-file config\l2_readonly_allowlist.json
app\backend\.venv\Scripts\python.exe tools\probes\l2_readonly_probe.py --target draft_box --run-id $runId --cookie-file data\sessions\dianxiaomi_cookies.json --output-dir data\l2_readonly_probe --allowlist-file config\l2_readonly_allowlist.json
```

两个真实目标必须使用同一个 `--run-id`，并且由同一脚本版本、同一 git head、同一 cookie/session fingerprint 生成。缺少 `evidence_binding` 或 run metadata 的历史证据只允许展示诊断，不能解锁 L3。

`--allowlist-file` 不会默认启用，必须显式传入。当前仓库的 `config/l2_readonly_allowlist.json` 只批准已审计的 DXM SPA 启动读取依赖；对于 DXM 用 POST 承载的查询接口，必须显式标注 `readonly_post=true`。它不会放行 WebSocket、EventSource、认领、备注写入、保存、提交或发布端点。

历史交付证据：2026-06-03 08:49 左右，`run_id=l2-real-20260603T084921Z` 曾完成 `data_acquisition` 与 `draft_box` 双目标真实只读 probe，两份证据均 `ok=true`，写入、非只读、拦截、禁词和 WebSocket 计数均为 0。该证据只能说明当时的只读门禁通过；当前真实写入 READY 必须重新取得同一 run-id 的新鲜 L2 双目标证据，并补齐 L3 单商品只保存证据链。历史证据不自动放行批量、无人值守或发布。

离线/mock 验证必须使用 `--url` 指向本地页面，不访问 `dianxiaomi.com`：

```powershell
app\backend\.venv\Scripts\python.exe tools\probes\l2_readonly_probe.py --target data_acquisition --url file:///C:/path/to/mock.html
```

## 门禁断言

- `network.write_request_count == 0`
- `network.non_read_request_count == 0`
- `network.blocked_request_count == 0`
- `network.forbidden_keyword_request_count == 0`
- `network.websocket_count == 0`
- `safety.ok == true`
- 真实店小秘目标必须加载 cookie，且不得疑似停留在登录页
- `data_acquisition` 与 `draft_box` 必须共享同一个 `evidence_binding.run_id`、`script_sha256`、`git_head` 和 `session_fingerprint_sha256`
- 输出 JSON、Markdown、截图和 DOM 路径
- 截图记录 `sha256`
- DOM 记录 `sha256`
- 报告包含 OS、浏览器版本、Python 版本、目标 URL、最终 URL、登录态、网络摘要和 `diagnostics`
- 未完成配置化评审时，`diagnostics` 只解释失败原因，不参与放行宽松化；`allowlist_review_candidates` 仍必须保持 `allowlist_applied=false` 且 `safety.ok=false`
- 已完成评审并显式传入 `--allowlist-file` 后，被批准的启动依赖必须记录到 `network.allowlisted_requests` 与 `diagnostics.allowlisted_request_groups`；未批准的 `blocked/forbidden/websocket/write` 计数仍必须为 0
- 精确匹配的第三方遥测 denylist 会在发出前 abort，并记录到 `network.suppressed_requests`；该机制不得用于 `dianxiaomi.com` 或任何业务写入接口

## 禁止范围

- 不运行 `claim`、`note`、`remark`、`save`、`publish` 相关临时脚本
- 不点击认领、编辑、保存、发布按钮
- 不填写输入框、不搜索商品、不选择店铺、不勾选半托管
- 不允许 `POST`、`PUT`、`PATCH`、`DELETE`
- 不允许真实业务写入 POST；DXM 查询型 POST 只有在 `readonly_post=true` 且精确匹配 host/path/resource_type/reason/keyword 时才能放行并记入 `allowlisted_non_read_request_count`
- 不允许 URL 命中 `save`、`publish`、`submitPublish`、`claim`、`remark`、`note`；唯一例外是 `config/l2_readonly_allowlist.json` 中窄范围批准的被动静态 JS chunk，且必须同时匹配 host/path/resource_type/reason/keyword
- 真实店小秘目标默认拦截 XHR、fetch、WebSocket、EventSource 等主动请求；如果页面自动发起这类请求，L2 判定不通过，后续必须单独评审只读 allowlist
- 真实 `dianxiaomi.com` 目标不忽略 HTTPS 证书错误；只有本地/mock URL 才允许 `ignore_https_errors`
- BrowserContext 禁用 Service Worker，避免请求绕过路由门禁
- 不把 `tools/probes/**/tmp_*` 历史脚本作为 L2 门禁入口

## 输出位置

运行产物在 `data/l2_readonly_probe/`，该目录受 `.gitignore` 保护，不随代码提交。
截图和 DOM 是本地敏感证据，只用于交付审查，不应贴到公开日志、PR 描述或外部工单。
CLI 标准输出只打印安全摘要、证据路径和 hash，不打印完整 DOM、可见文本或 body 预览。

## 失败诊断

JSON/Markdown 的 `diagnostics` 包含：

> 注：`data/l2_readonly_probe/real_20260522/` 中的早期失败证据可能没有完整 `diagnostics` 字段；当前代码会在工作台聚合层派生诊断摘要，但重新跑 L2 时应以新版 JSON/Markdown 产物为准。

- `strict_pass_checks`：逐项列出 `ok/safety_ok/final_url_matches/zero_*` 等硬门禁布尔值。
- `navigation`：记录请求目标 path、最终 path、是否离开目标 path，以及最终 path 分类（如 `home/login/target/other`）。
- `render_state`：记录 body 长度、可见匹配数量、是否疑似 loading/app shell。
- `blocked_request_groups`：按 host/path/method/resource_type/reason/keyword 聚合被拦截请求，避免只看前 50 条原始请求。
- `allowlisted_request_groups`：按 host/path/method/resource_type/reason/keyword 聚合被显式配置批准的只读启动请求。
- `suppressed_request_groups`：按 host/path/method/resource_type/reason/keyword 聚合被预拦截的第三方遥测请求。
- `allowlist_review_candidates`：仅用于人工评审“可能是只读启动依赖”的 GET active request；该字段不得自动放行 L2。

## Allowlist 人工评审记录

最终自检会生成 `outputs/final-delivery-check/l2-allowlist-review-template.md` 和 `outputs/final-delivery-check/l2-allowlist-review-template.json`。该模板用于归档人工判断，不是 L2 通过证明。

最终自检报告会记录模板 Markdown/JSON 的 `sha256` 哈希；报告中心也会展示同一组哈希短值。人工评审归档时必须保留原始模板、填写后模板以及各自哈希，避免后续复跑或审批时混淆不同批次的候选。

每个候选至少需要补齐：

- `reviewer` / `reviewed_at`
- `decision`：`approve`、`reject` 或 `needs_info`
- `rationale`：业务必要性与只读依据
- `approved_scope`：精确到 method、host、path、resource_type 的最小范围
- `residual_risk`：残余风险和监控/到期复核策略
- `l2_recheck_required=true`

只有当评审记录完成、代码或配置实现了显式最小 allowlist，并且重新运行真实 L2 双目标通过后，才允许进入 L3 判断。任何缺少评审人、理由、范围或复跑证据的候选都必须继续阻断。

## 证据等级

- A 级：L2 JSON/Markdown/截图/DOM/hash 齐全，网络摘要显示 0 写请求、0 拦截、0 禁用关键词命中，且登录态有效。
- B 级：页面截图和 DOM 齐全，但真实站点存在无法规避的读接口非 GET 行为，报告必须显示已 abort 并判定不通过。
- 不通过：任何写方法、发布/保存/认领/备注关键词、登录态失效、证据文件缺失，或双目标缺少同轮次 evidence binding。
