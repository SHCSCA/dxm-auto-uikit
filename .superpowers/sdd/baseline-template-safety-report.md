# Baseline blocker C: template persistence safety report

- Date: 2026-07-13
- Base commit: `520bd81d1375fd321d9ad7bd602801ec12b48bb7`
- Scope: task creation template side effects and the active production `TemplateCenterPage`
- Real DXM activity: none

## Result

PASS for the blocker scope:

- Creating a `single_save` task no longer creates missing templates or repairs legacy templates.
- An empty template library stays empty; a legacy template library stays byte-for-byte equivalent at the API object level after task creation.
- Missing configuration remains visible as `E302` through the existing config validation/preview path, and the existing runner preflight still fails before `save_only`.
- The active production template page no longer contains bundled default-value draft helpers, a bundled pack POST/PATCH path, or actions that can feed those hardcoded values into normal template CRUD.
- Normal user template POST/PATCH, disable, per-task override, template resolution, and config validation remain intact.
- Dev-only bootstrap code and unmounted legacy `WorkbenchModules.ConfigCenter` were intentionally left outside this blocker.

## Root cause

`POST /api/tasks` called `_ensure_single_save_starter_templates` before `repo.create_task`. That helper generated eight hardcoded templates for an empty library and repaired matching legacy category/reference templates.

The active `TemplateCenterPage` also generated hardcoded per-section drafts and exposed an action that POSTed or PATCHed the entire bundled default pack into `/api/templates`. The per-section default draft could also be persisted through ordinary template save actions, so removing only the pack button would not have closed the path.

## TDD evidence

### RED

Command:

```powershell
cd app/backend
.venv\Scripts\python.exe -m pytest tests\test_task_start_guard.py::test_create_single_save_task_leaves_empty_template_library_unchanged tests\test_task_start_guard.py::test_create_single_save_task_leaves_legacy_template_library_unchanged tests\test_frontend_demo_workflow_contract.py::test_template_center_cannot_persist_bundled_default_template_values -q
```

Observed result: `3 failed in 4.48s`.

- Empty library assertion failed because task creation added eight templates.
- Legacy library assertion failed because task creation repaired existing templates and added missing types.
- Frontend contract failed because `保存全部分区为店铺模板` and `saveDefaultTemplatePackAsStoreTemplates` were present.

The active-page workflow contract was then tightened to forbid the single-section default draft path. Before production changes, its RED run produced `2 failed in 1.67s` across the active page workflow and bundled-default persistence contracts.

### GREEN

Immediate focused RED-to-GREEN command:

```powershell
cd app/backend
.venv\Scripts\python.exe -m pytest tests\test_task_start_guard.py::test_create_single_save_task_leaves_empty_template_library_unchanged tests\test_task_start_guard.py::test_create_single_save_task_leaves_legacy_template_library_unchanged tests\test_frontend_demo_workflow_contract.py::test_template_center_page_presents_multi_template_chinese_section_workflow tests\test_frontend_demo_workflow_contract.py::test_template_center_cannot_persist_bundled_default_template_values -q
```

Observed result: `4 passed in 0.99s`.

## Focused verification

Template/config/task-start/frontend contracts:

```powershell
cd app/backend
.venv\Scripts\python.exe -m pytest tests\test_templates.py tests\test_template_center_contract.py tests\test_config_defaults.py tests\test_config_validation.py tests\test_task_start_guard.py tests\test_frontend_demo_workflow_contract.py -q
```

Observed result: `355 passed in 30.32s`.

Existing execution preflight proof:

```powershell
cd app/backend
.venv\Scripts\python.exe -m pytest tests\test_v1_runner.py::test_single_save_missing_required_dxm_reference_template_fails_before_save -q
```

Observed result: `1 passed in 0.51s`. The contract verifies the task becomes failed, the missing required template is reported, and the adapter never receives `save_only`.

Frontend production build:

```powershell
cd app/frontend
npm run build
```

Observed result: typecheck passed and Vite built 49 modules successfully in 1.20s.

Final pre-commit fresh verification combined the focused 355-test suite with the runner preflight contract: `356 passed in 29.72s`. A fresh `npm run build` then passed typecheck and built 49 modules successfully in 1.03s.

## Files changed

- `app/backend/src/main.py`
- `app/backend/tests/test_task_start_guard.py`
- `app/backend/tests/test_frontend_demo_workflow_contract.py`
- `app/frontend/src/components/workbench/TemplateCenterPage.tsx`
- `.superpowers/sdd/baseline-template-safety-report.md`

No real DXM command, browser mutation, L2 probe, or save action was run.
