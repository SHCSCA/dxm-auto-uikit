> 由 OpenAI GPT（Codex）AI 生成/维护。

# Gold 指针：DXM 完整商品编辑

**状态：原 Path A-only E0–E4 指令已于 2026-08-25 被产品裁决取代。**

唯一产品合同：[`docs/product/MVP-竖切-草稿箱批量只保存.md`](MVP-竖切-草稿箱批量只保存.md)。
上游事实：[`docs/integration/DXM-TX-上游事实合同.md`](../integration/DXM-TX-上游事实合同.md)。
类目合同：[`docs/integration/DXM-TX-类目节点与目录合同.md`](../integration/DXM-TX-类目节点与目录合同.md)。

本页不再复制第二套 Epic、DoD 或可执行 prompt。任何 Agent 必须先读唯一主合同、`AGENTS.md`、`PROGRESS.md` 和 `BLOCKED.md`，再按当前代码事实工作。

## 当前不可改写的产品裁决

- 真实可见浏览器；只读接口，UI 写。
- 当次 `pageList(draft)` 多选 `draft ≥3`；`claim_only 非前置`。
- 每件商品无条件执行视频、翻译、批发、半托管和 rollback preparation。
- 完整成功路径为 Path B：主编辑 SAVE → 受控中间 `SEMI_MANAGED_CONTINUE_TRANSITION` → `editFromSmt` → 半托管 SAVE。
- Path A 只可作为底层诊断/canary，不得代表完整产品完成。
- 中间“继续发布”只在主合同精确上下文中允许；最终发布、立即发布、保存并发布、保存并移入待发布永久禁止。
- 每次 SAVE 都必须具备回包、页面成功态和独立未发布证明。
- UNKNOWN 停批且不得自动重试。
- 动态类目任意深度，只允许无冲突叶子；catalog 不能替代当前页面类目和 Schema。
- `MVP_READY ≠ PROD_READY`；当前仍 `E3_OPEN / BLOCKED`。

## 执行顺序

```text
E0 主合同/指针/catalog/防回退
→ E1 RuntimeTruth/Reader/动态类目/draft ≥3
→ E2 五项 ALWAYS_ON 方案与不可变 snapshot
→ E3 完整可见编辑/rollback/Path B 双阶段保存
→ E4 HVD/四键/结果/真实三商品人工验收
```

一次只关闭一个 Epic。专项绿、mock、空 executor、历史 Path A canary 或本页存在均不能跳过前置门禁。

## 当前实现边界

截至 2026-08-25，现有代码仍主要是 Path A 和基础 Runner；视频、翻译、批发、完整 Path B、真实 rollback 和两阶段 receipt 未闭合。实现缺口必须写进 `BLOCKED.md`，不得把必需能力降级为“可选/以后再做”，也不得伪称已经完成。
