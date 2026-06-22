# DXM Browser HUD Delivery Plan

**Goal:** 让真实店小秘浏览器里的左上角黑色 HUD 成为普通用户能理解的实时执行进度，而不是工程状态提示。

**Scope:** 只改受控单商品只保存路径。发布、批量、无人值守继续保持关闭。

## Task 1: Correct Browser HUD Entry State

- [x] 启动执行浏览器时，HUD 不再显示“真实只读检查待命 / 只读观察”。
- [x] 初始 HUD 显示“准备开始只保存”，说明真实浏览器已打开，下一步是人工确认后由 Agent 执行。
- [x] 契约测试覆盖初始 HUD 文案。

## Task 2: Make Workflow Steps Match DXM Edit Page Language

- [x] 把 V1 runner HUD 文案改成用户能看到的动作：打开采集箱、定位商品、打开编辑页、输入标题、选择分类、设置 SKU/价格/库存、处理图片、填写合规/海关、设置半托管、保存、确认未发布。
- [x] 保存步骤必须继续明确“只点击保存，不点击发布”。
- [x] 契约测试覆盖关键步骤文案。

## Task 3: Verify

- [x] `app/backend/.venv/Scripts/python.exe -m pytest tests/test_agent_console.py tests/test_v1_runner.py tests/test_frontend_demo_workflow_contract.py -q`
- [x] `cd app/frontend && npm run build`
- [x] 必要时运行 browser QA，确认前端主路径仍无溢出和网络异常。
