# L1 离线 Selector Replay 门禁

## 目标

L1 replay 用本地 HTML fixture 验证关键页面信号，不访问店小秘、不启动浏览器、不点击、不填写、不保存、不发布。

## 运行命令

```powershell
cd D:\Desktop\py\dxm-auto-uikit
app\backend\.venv\Scripts\python.exe tools\probes\l1_selector_replay.py
```

## 覆盖范围

- 商品箱归属行：商品标题、Dang Kang、稳定行身份、编辑入口；fixture 不包含已移除的认领动作。
- 普通编辑页：属性信息、引用模板、半托管入口。
- 欧盟外包装图：`外包装/标签实拍图-欧盟`、添加图片、`图片银行（速卖通）`。
- 营销图片：`1:1白底图`、`3:4场景图`、`图片白底`、`一键白底`。
- 半托管页：JIT 库存、是否原箱、物流属性、保存按钮。
- 发布隔离：fixture 中不得出现发布、立即发布、继续发布、保存并发布、确认发布、提交发布、移入待发布。

## 门禁断言

- `ok == true`
- `failed_count == 0`
- 每个 case 都有 `fixture_sha256`
- 输出 JSON 和 Markdown 证据
- 工作台 Dashboard 的 L1 门禁读取 `data/l1_selector_replay/` 最新结果

## 输出位置

运行产物在 `data/l1_selector_replay/`，该目录受 `.gitignore` 保护，不随代码提交。
