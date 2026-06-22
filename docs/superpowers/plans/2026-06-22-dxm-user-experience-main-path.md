# DXM User Experience Main Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 DXM Agent Console 的默认体验从工程诊断台收敛为普通运营人员能按步骤完成真实店小秘单商品只保存的产品路径。

**Architecture:** 保持 React/Vite/Electron/FastAPI/Playwright 架构不变。用户主路径在前端收敛为“登录店小秘 -> 选择商品 -> 填写编辑页 -> 页面检查 -> 人工确认并只保存 -> 查看保存结果”；后端继续负责真实门禁和证据，前端默认只呈现业务动作、阻断原因和下一步。

**Tech Stack:** React 18 + Vite + TypeScript, FastAPI, pytest contract tests, PowerShell delivery checks.

---

## File Structure

- Modify: `app/frontend/src/components/AppShell.tsx`  
  负责侧边栏信息架构、菜单中文命名、折叠态 tooltip 和屏幕阅读器路径。
- Modify: `app/frontend/src/components/workbench/HomePage.tsx`  
  负责首页“现在只做这一步”、4 步路径和用户下一步。
- Modify: `app/frontend/src/components/workbench/ProductTaskPanels.tsx`  
  负责商品任务页的阻断卡、只读检查入口、人工确认入口文案。
- Modify: `app/frontend/src/components/workbench/ResultsPage.tsx`  
  负责保存结果页第一屏，优先回答“保存成功了吗 / 有没有发布 / 下一步是什么”。
- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`  
  负责把技术错误降级成人话提示。
- Modify: `app/frontend/src/styles.css`  
  负责主路径卡片、菜单、状态条、折叠诊断和移动端布局。
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`  
  负责前端静态契约：菜单是业务入口、默认不暴露技术词、主按钮唯一。
- Test: `app/backend/tests/test_frontend_api_error_contract.py`  
  负责错误文案不泄露 raw 技术异常。

## Task 1: Sidebar And Route Vocabulary

**Files:**
- Modify: `app/frontend/src/components/AppShell.tsx`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Update contract assertions**

Add or adjust assertions so the sidebar exposes these business labels:

```python
expected_labels = [
    "今天做什么",
    "登录店小秘",
    "选择商品",
    "填写编辑页",
    "开始只保存",
    "保存结果",
    "保存证据",
    "失败处理",
    "帮助与设置",
]
```

Run:

```bat
cd app\backend
.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
```

Expected before implementation: fails on missing old/new sidebar labels.

- [x] **Step 2: Rename AppShell menu labels**

Change `primaryAreas` to these user-facing groups:

```ts
const primaryAreas: WorkbenchPrimaryArea[] = [
  { id: 'start', label: '开始', short: '1', items: [
    { id: 'home', label: '今天做什么', short: '今', hint: '看当前进度和唯一下一步' },
    { id: 'dxm_access', label: '登录店小秘', short: '登', hint: '打开真实店小秘并检测登录状态' },
  ] },
  { id: 'task', label: '准备商品', short: '2', items: [
    { id: 'product_tasks', label: '选择商品', short: '选', hint: '选择一个商品并创建单商品只保存任务' },
    { id: 'edit_config', label: '填写编辑页', short: '填', hint: '按店小秘编辑页分区填写本次任务取值' },
  ] },
  { id: 'run', label: '执行保存', short: '3', items: [
    { id: 'agent_execution', label: '开始只保存', short: '存', hint: '页面检查、人工确认、启动真实浏览器只保存' },
  ] },
  { id: 'review', label: '复盘', short: '4', items: [
    { id: 'results', label: '保存结果', short: '果', hint: '查看保存成功、未发布证明和验收报告' },
    { id: 'evidence', label: '保存证据', short: '证', hint: '核对只保存、未发布和浏览器证据' },
    { id: 'issues', label: '失败处理', short: '错', hint: '查看失败原因、阻断说明和处理建议' },
  ] },
  { id: 'system', label: '帮助', short: '5', items: [
    { id: 'settings', label: '帮助与设置', short: '帮', hint: '查看使用范围、服务状态和高级诊断入口' },
  ] },
]
```

- [x] **Step 3: Run focused test**

Run:

```bat
cd app\backend
.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
```

Expected after implementation: pass.

## Task 2: Home Page First Successful Run Guide

**Files:**
- Modify: `app/frontend/src/components/workbench/HomePage.tsx`
- Modify: `app/frontend/src/styles.css`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add contract for one visible primary action**

Assert `HomePage.tsx` contains `现在只做这一步`, `登录店小秘`, `选择商品`, `填写编辑页`, `开始只保存`, `保存结果`, and does not put `run-id` or `HAR` in the first command section.

- [x] **Step 2: Adjust copy**

Map `nextAction` CTAs to route labels:

```ts
goLogin: '去登录店小秘'
goProduct: '去选择商品'
goConfig: '去填写编辑页'
goRun: '去开始只保存'
goResult: '查看保存结果'
```

- [x] **Step 3: Run focused test and frontend build**

Run:

```bat
cd app\backend
.venv\Scripts\python.exe -m pytest tests\test_frontend_demo_workflow_contract.py -q
cd ..\frontend
npm run build
```

Expected: test pass and Vite build pass.

## Task 3: Error Cards In User Language

**Files:**
- Modify: `app/frontend/src/components/workbench/workbenchCopy.ts`
- Modify: `app/frontend/src/components/workbench/ProductTaskPanels.tsx`
- Modify: `app/frontend/src/components/workbench/IssuesPage.tsx`
- Test: `app/backend/tests/test_frontend_api_error_contract.py`

- [x] **Step 1: Extend raw technical error sanitizer**

Add mappings for `L2 readonly probe`, `L3`, `run_id`, `save_result`, `network/HAR`, and `Cannot switch to a different thread`.

- [x] **Step 2: Make blocking cards use three-part shape**

Each visible failure card must include:

```text
发生了什么
为什么不能继续
下一步
```

- [x] **Step 3: Run tests**

```bat
cd app\backend
.venv\Scripts\python.exe -m pytest tests\test_frontend_api_error_contract.py tests\test_frontend_demo_workflow_contract.py -q
```

Expected: pass.

## Task 4: Results Page User-First Summary

**Files:**
- Modify: `app/frontend/src/components/workbench/ResultsPage.tsx`
- Modify: `app/frontend/src/styles.css`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] **Step 1: Add first-screen contract**

Assert the first results section shows `保存成功了吗`, `有没有发布`, `商品`, `完成时间`, and `下一步`.

- [x] **Step 2: Move technical evidence lower**

Keep L2/L3, run binding, screenshot hashes, HAR paths and QA service details inside details blocks or technical sections.

- [x] **Step 3: Run build and QA script**

```bat
cd app\frontend
npm run build
cd ..\..
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1
```

Expected: build pass and Browser QA pass.

## Task 5: Rendered Validation

**Files:**
- Temporary only outside repo for Playwright screenshot scripts.

- [x] **Step 1: Start current app**

Use the repo startup path that matches the validation target:

```bat
scripts\start-mvp.bat
```

or use the isolated final QA script when avoiding existing ports:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\qa-browser-check.ps1
```

- [x] **Step 2: Validate rendered flow**

The flow under test is: app loads -> sidebar navigation -> homepage next action -> product task/config/run/result labels render without exposing technical terms in the default first viewport.

Required evidence:

- Page is not blank.
- No Vite/React error overlay.
- No relevant console errors.
- Desktop first viewport has one obvious primary action.
- Mobile viewport has no horizontal overflow.

- [x] **Step 3: Commit**

```bat
git add app/frontend app/backend/tests docs/superpowers/plans/2026-06-22-dxm-user-experience-main-path.md
git commit -m "Polish DXM user main path"
```
