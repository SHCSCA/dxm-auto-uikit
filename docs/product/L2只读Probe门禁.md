# L2 只读 Probe 门禁

## 目标

L2 只读 probe 只用于验证登录态、目标页面可达性、DOM/按钮文本和截图证据。它不得写备注、不得认领、不得保存、不得发布。

## 运行命令

真实店小秘 L2 只读探测仍会打开真实页面。只有在用户明确批准“执行 L2 真实只读探测”后才运行以下命令；它不会点击、输入、认领、备注、保存或发布。

```powershell
cd C:\Users\wz\Desktop\py\dxm-auto-uikit
app\backend\.venv\Scripts\python.exe tools\probes\l2_readonly_probe.py --target data_acquisition
app\backend\.venv\Scripts\python.exe tools\probes\l2_readonly_probe.py --target draft_box
```

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
- 输出 JSON、Markdown、截图和 DOM 路径
- 截图记录 `sha256`
- DOM 记录 `sha256`
- 报告包含 OS、浏览器版本、Python 版本、目标 URL、最终 URL、登录态、网络摘要

## 禁止范围

- 不运行 `claim`、`note`、`remark`、`save`、`publish` 相关临时脚本
- 不点击认领、编辑、保存、发布按钮
- 不填写输入框、不搜索商品、不选择店铺、不勾选半托管
- 不允许 `POST`、`PUT`、`PATCH`、`DELETE`
- 不允许 URL 命中 `save`、`publish`、`submitPublish`、`claim`、`remark`、`note`
- 真实店小秘目标默认拦截 XHR、fetch、WebSocket、EventSource 等主动请求；如果页面自动发起这类请求，L2 判定不通过，后续必须单独评审只读 allowlist
- BrowserContext 禁用 Service Worker，避免请求绕过路由门禁
- 不把 `tools/probes/**/tmp_*` 历史脚本作为 L2 门禁入口

## 输出位置

运行产物在 `data/l2_readonly_probe/`，该目录受 `.gitignore` 保护，不随代码提交。
截图和 DOM 是本地敏感证据，只用于交付审查，不应贴到公开日志、PR 描述或外部工单。
CLI 标准输出只打印安全摘要、证据路径和 hash，不打印完整 DOM、可见文本或 body 预览。

## 证据等级

- A 级：L2 JSON/Markdown/截图/DOM/hash 齐全，网络摘要显示 0 写请求、0 拦截、0 禁用关键词命中，且登录态有效。
- B 级：页面截图和 DOM 齐全，但真实站点存在无法规避的读接口非 GET 行为，报告必须显示已 abort 并判定不通过。
- 不通过：任何写方法、发布/保存/认领/备注关键词、登录态失效或证据文件缺失。
