# Baseline blocker B：原生标题空回读 fail-closed 报告

## 结论

`_fill_visible_editor_title_with_native_input()` 现在只会在原生输入后的 DOM 回读非空，且规范化后与请求标题一致时返回成功。空回读会记录独立的 `visible_editor_title:native_empty_readback` trace，继续尝试剩余候选点，并在全部候选失败后 fail closed；不会记录 `visible_editor_title:native_done`。

原有 `force_replace=False` 且 DOM 已存在非空标题时跳过原生输入的行为保持不变；非空但不匹配的回读仍按失败处理。

## TDD 证据

### RED

先只修改 `app/backend/tests/test_login_flow.py`：

- 新增 `test_visible_editor_title_native_input_rejects_empty_readback_after_every_candidate`，模拟预读和三次写入后回读均为空，但 Win32 点击与剪贴板写入均成功。
- 更新 `test_visible_editor_title_native_input_uses_win32_only_click_path`，让写入后的回读返回真实匹配标题，不再把空回读编码成成功。

运行：

```powershell
cd app/backend
.\.venv\Scripts\python.exe -m pytest tests\test_login_flow.py -q -k "visible_editor_title_native_input_uses_win32_only_click_path or visible_editor_title_native_input_rejects_empty_readback_after_every_candidate"
```

结果：`1 failed, 1 passed, 356 deselected in 4.50s`。

预期失败证据：新增回归期望 `ok=False`，旧逻辑却在第一个空回读后返回 `ok=True`、`confirmed=False`，证明测试准确复现了空回读假成功。

### GREEN（focused）

最小生产修改后运行：

```powershell
cd app/backend
.\.venv\Scripts\python.exe -m pytest tests\test_login_flow.py -q -k "visible_editor_title_native_input"
```

结果：`4 passed, 354 deselected in 6.98s`。

新增回归同时验证：

- 三个候选点均被尝试；
- 三次剪贴板输入均执行；
- 三次空回读各记录一条 `visible_editor_title:native_empty_readback`；
- 最终返回 `visible_editor_title_native_input_failed`；
- 全程没有 `visible_editor_title:native_done`。

### GREEN（完整文件）

运行：

```powershell
cd app/backend
.\.venv\Scripts\python.exe -m pytest tests\test_login_flow.py -q
```

结果：`358 passed in 199.48s (0:03:19)`。

## 安全边界

本次仅修改离线单元测试、标题原生输入后的回读判定与本报告；未启动浏览器、未连接真实 DXM、未执行任何认领、保存、批量或发布动作，也未扩大 `controlled_single_save_only` 边界。
