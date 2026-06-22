# DXM UX Productization 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已可交付的 DXM 单商品只保存路径继续收敛为普通运营用户可自助、可理解、可恢复的生产级体验。

**Architecture:** 保持现有 React/Vite/Electron/FastAPI/Playwright 架构不变。本阶段只改用户默认路径、菜单心智、状态语言和可见信任链；技术诊断、证据链和 READY 门禁继续保留，但默认下沉。

**Tech Stack:** React 18 + TypeScript + Vite, FastAPI contract tests, PowerShell browser QA and desktop delivery checks.

---

## Scope Guard

- 只放行受控 `single_save` 单商品只保存。
- 不新增发布、批量、无人值守入口。
- 不把 `L2/L3/probe/run-id/HAR` 作为普通用户默认语言。
- 不用截图假装执行，真实操作仍发生在独立可见店小秘浏览器。

## Task 1: Information Architecture Tightening

**Files:**
- Modify: `app/frontend/src/components/AppShell.tsx`
- Modify: `app/frontend/src/components/workbench/HomePage.tsx`
- Modify: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] Remove `保存证据` from the primary sidebar. Keep the `evidence` route reachable from `保存结果`.
- [x] Rename `失败处理` to `问题处理` in the primary sidebar and page labels.
- [x] Add a visible homepage control ownership card: `当前控制权` with values `用户操作中`, `Agent 操作中`, or `系统等待确认`.
- [x] Verify the sidebar reads like a task flow: `今日任务`, `登录店小秘`, `选择商品`, `填写编辑页`, `开始只保存`, `保存结果`, `问题处理`, `使用帮助`, `系统设置`.

## Task 2: Operator Language Pass

**Files:**
- Modify: `app/frontend/src/components/SafetyStatusBar.tsx`
- Modify: `app/frontend/src/components/workbench/IssuesPage.tsx`
- Modify: `app/frontend/src/components/workbench/ResultsPage.tsx`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] Keep the top status bar to one decision: current step, safety boundary, primary action.
- [x] Move technical evidence words behind `查看状态详情`, `技术诊断`, or result evidence details.
- [x] Ensure every blocking/default issue card uses `发生了什么 / 为什么不能继续 / 下一步`.
- [x] Ensure the result page first answers `保存成功了吗 / 有没有发布 / 商品 / 完成时间 / 下一步`.

## Task 3: Configuration As Execution Brief

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/styles.css`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] Reword configuration entry copy from system settings to `告诉 Agent 到店小秘编辑页怎么填`.
- [x] Keep one focused editable section open by default.
- [x] Keep template selector, match trace, and advanced mapping collapsed by default.
- [x] Show the current execution value source near the focused fields.

## Task 4: Browser Trust Chain

**Files:**
- Modify: `app/frontend/src/components/WorkbenchModules.tsx`
- Modify: `app/frontend/src/App.tsx`
- Test: `app/backend/tests/test_agent_console.py`
- Test: `app/backend/tests/test_frontend_demo_workflow_contract.py`

- [x] Preserve the real browser HUD with Chinese progress steps.
- [x] Make the console copy consistently say the real browser is the operation site.
- [x] Expose manual takeover as a user recovery action, not as a technical control.
- [x] Keep click/fill/page-write controls disabled outside the approved task flow.

## Task 5: Verification And Delivery

**Files:**
- Modify: `docs/superpowers/plans/2026-06-22-dxm-ux-productization-2.md`

- [x] Run focused frontend contract tests.
- [x] Run frontend production build.
- [x] Run browser QA against the rendered app.
- [x] If delivery scope changes visible package output, rebuild portable Electron and copy the no-install EXE.
- [x] Record evidence and leave publish/batch/unattended blocked.

**Evidence recorded on 2026-06-22:**
- Backend focused suite: `272 passed`.
- Frontend contract + agent console suite after QA update: `209 passed`.
- Frontend production build: `npm run build` passed.
- Browser QA: `outputs/browser-checks/ux-productization-2-current-backend/qa-browser-check.json` passed with `ok=true`.
- Desktop package verification: `scripts/verify-desktop-package.ps1 -CheckPortable -WaitSeconds 180` passed packaged, credential, visible-window, and portable smoke checks.
- User-facing no-install exe updated at `D:\Desktop\DXM-Agent-Console-免安装版\DXM-Agent-Console-Portable-0.1.0.exe`.
