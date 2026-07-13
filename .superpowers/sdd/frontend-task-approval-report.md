# Frontend current-task approval report

Status: DONE

## Scope

- Task: Baseline blocker A2, frontend approval flow and frontend contract tests only.
- Branch: `fix/dxm-two-stage-runtime-truth`.
- Starting HEAD: `02c88b70ec5c2a269680885a118559a3df3ab4d1`.
- Safety boundary: no backend approval implementation changes, no real DXM execution, no batch/publish/unattended release, and no `.claude/` changes.

## Contract implemented

- Frontend released real-mutation modes are exactly `claim_only` and `single_save`; only `batch_save` remains unreleased.
- Stage A uses the exact confirmation `确认将该已有商品认领到商品箱`; Stage B retains `CONFIRM_DXM_SAVE_ONLY`.
- Both released stages require a non-empty current approver, request a server approval from `/api/tasks/{id}/manual-approval`, and immediately start with the returned approval token/confirmation plus that approver.
- The former `claim_only` empty start request was removed.
- Config preview remains a start prerequisite only for `single_save`.
- `ProductTasksPage` derives current approval readiness from the in-memory approver, not the global/historical L3 gate. Global L3 is displayed only as historical execution evidence.
- With L2 passed, draft `claim_only` and `single_save` tasks keep the task-specific confirmation copy and controlled approver input visible while the operator types or corrects the value.
- The primary action remains disabled when that current approver is empty, including after reload when historical L3 or stored approval evidence may still be present.

## TDD evidence

### RED

Only the frontend contract tests were changed before this run:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_frontend_demo_workflow_contract.py::test_frontend_releases_both_controlled_stages_and_blocks_only_batch tests\test_frontend_demo_workflow_contract.py::test_frontend_claim_and_single_save_share_current_task_server_approval_flow tests\test_frontend_demo_workflow_contract.py::test_product_tasks_page_requires_current_approver_for_both_released_stages
```

Result before production edits: `3 failed in 3.54s`.

Expected failures identified the old single-save-only released set, missing Stage A approval confirmation/shared server-approval path, and missing in-memory current-approver fail-closed behavior in `ProductTasksPage`.

### Focused GREEN

The exact RED selection after the minimal frontend implementation returned:

```text
3 passed in 0.19s
```

### Review RED/GREEN: keep the controlled input mounted

Review found that conditioning the form on `currentTaskApprovalMissing` hid the controlled input after its first non-empty character, preventing the operator from typing or correcting a complete approver name. The contract was changed first to require the form to remain mounted for any draft released stage with L2 passed:

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_frontend_demo_workflow_contract.py::test_product_tasks_page_requires_current_approver_for_both_released_stages
```

Result before the one-line JSX fix: `1 failed in 2.05s`.

The exact selection after the fix returned: `1 passed in 0.14s`.

### Final GREEN

```powershell
.venv\Scripts\python.exe -m pytest -q tests\test_frontend_demo_workflow_contract.py
```

Result: `209 passed in 1.38s`.

```powershell
npm run build
```

Result: TypeScript typecheck passed and Vite production build completed successfully (`49 modules transformed`).

## Files changed

- `app/frontend/src/App.tsx`
- `app/frontend/src/components/workbench/ProductTasksPage.tsx`
- `app/backend/tests/test_frontend_demo_workflow_contract.py`
- `.superpowers/sdd/frontend-task-approval-report.md`

## Delivery boundary

This work establishes the offline frontend approval contract only. It does not run a real claim/save, create fresh L2/L3 evidence, package a delivery build, or claim runtime/delivery READY.
