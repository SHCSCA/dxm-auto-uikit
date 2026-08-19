# 采集箱列表展示（图 / 备注 / 店铺 / 平台 / 分页）

> 由 OpenAI GPT（Codex）AI 生成/维护。

已批准：方案 1。只读 `pageList(draft)`。不保存、不发布。

## 展示字段（非任务身份）

- `thumbnail_url`：`imageURLs` 按 `;` 切分后第一条 `http(s)` 图
- `remark`：`comment` 去空白；空则省略
- `source_platform`：`sourceName`（如 1688 / 拼多多）；空则省略
- 店铺名：用已有 `shop_id` + 店铺列表

身份仍只比：id / shop_id / subject / category_id / dxm_state。

## UI

左列表行：勾选 + 缩略图 + 标题 + 备注 + 「店铺名」+ 平台。
底栏：`第 {from}–{to} 条，共 {total} 条` + 上/下一页 + 20/50/100（默认 100）。
右栏任务确认不变。
