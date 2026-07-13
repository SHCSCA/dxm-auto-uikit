# Backend claim approval and truthful READY report

## Scope

- Task: baseline blocker A1, backend only.
- Branch: `fix/dxm-two-stage-runtime-truth`.
- Starting HEAD: `994c61d20c40a9d9c77209721b2c3c0837796d3e`.
- Safety boundary: no real DXM execution; no frontend or template changes.

## Contract implemented

- Released real mutation modes are exactly `claim_only` and `single_save`; `batch_save` remains blocked.
- Stage A uses the exact confirmation `确认将该已有商品认领到商品箱`.
- Stage B retains `CONFIRM_DXM_SAVE_ONLY`.
- Manual approval selects and returns the confirmation required by task mode.
- `claim_only` approval/start requires the claim-to-draft scene and acquisition-claim job shape with no bound product ID.
- `single_save` retains save-only scene, single-product, non-fixture, and claimed-draft provenance checks.
- Both released modes require request approval, the mode-specific confirmation, a non-empty approver, stored server approval, a matching token hash, and then a passed L2 gate.
- Runtime READY additionally requires `two_stage_acceptance.passed is True`; missing or failed two-stage evidence returns BLOCKED with `two_stage_ready=False` and a clear reason.
- The unreleased-mode detail now describes `claim_only` and `single_save` as the two controlled released modes.

## TDD evidence

### RED

The first invocation used the system Python and did not enter the test suite because `pytest` was not installed there. It was not counted as RED. The same test selection was immediately rerun with the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_task_start_guard.py::test_claim_only_start_rejects_missing_stage_a_confirmation tests/test_task_start_guard.py::test_claim_only_start_rejects_wrong_stage_a_confirmation tests/test_task_start_guard.py::test_claim_only_manual_approval_token_allows_stage_a_start tests/test_task_start_guard.py::test_single_save_manual_approval_keeps_stage_b_confirmation tests/test_task_start_guard.py::test_batch_save_remains_unreleased_when_claim_only_is_released tests/test_final_delivery_check_summary.py::test_current_real_dxm_gate_summary_blocks_ready_when_two_stage_is_false
```

Result before production edits: `5 failed, 1 passed in 2.28s`.

Expected failures:

- Missing Stage A confirmation was still hidden by the old claim-unreleased gate.
- Wrong Stage A confirmation was still hidden by the old claim-unreleased gate.
- A valid server-issued Stage A token could not be issued/started because claim was unreleased.
- The released-mode set lacked `claim_only` while `batch_save` remained blocked.
- L2/L3/delivery-ready with `two_stage_acceptance.passed=False` incorrectly returned READY.

The Stage B unchanged regression test passed during RED, confirming the existing save confirmation contract before implementation.

### Core GREEN

After the minimal backend implementation, the exact RED selection returned:

```text
6 passed in 1.71s
```

### Existing reverse-contract cleanup

The first full three-file run after implementation returned `13 failed, 128 passed in 34.87s`. Every failure was an old assertion that intentionally described `claim_only` as unreleased or expected the old unreleased-mode copy. Those tests were minimally updated to the controlled two-stage contract; no production behavior was broadened in response to this run.

### Final GREEN

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_task_start_guard.py tests/test_acquisition_claim_workflow.py tests/test_final_delivery_check_summary.py
```

Result:

```text
141 passed in 32.50s
```

## Files changed

- `app/backend/src/main.py`
- `app/backend/tests/test_task_start_guard.py`
- `app/backend/tests/test_final_delivery_check_summary.py`
- `.superpowers/sdd/backend-claim-ready-report.md`

`tests/test_acquisition_claim_workflow.py` was run but not changed.

## Review fix: approver binding and login-success copy

Review found two follow-up gaps:

- The start guard accepted a correct token even when the request approver did not match the server-stored approver, and it did not require the stored approver to be non-empty.
- The post-login operator copy still said `claim_only` was unreleased.

### Review RED

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_task_start_guard.py::test_claim_only_start_rejects_mismatched_stage_a_approver tests/test_task_start_guard.py::test_claim_only_start_rejects_empty_stored_stage_a_approver tests/test_task_start_guard.py::test_single_save_start_rejects_mismatched_stage_b_approver tests/test_login_flow.py::test_login_success_copy_describes_controlled_two_stage_start_boundary
```

Result before the review fix: `4 failed in 3.49s`.

Expected failures:

- A correct Stage A token with a different request approver incorrectly returned 200.
- A correct Stage A token with an empty stored approver incorrectly returned 200.
- A correct Stage B token with a different request approver incorrectly returned 200.
- Login-success copy still described `claim_only` as unreleased.

### Review GREEN

The start guard now trims both approver values, requires both to be non-empty, and requires the normalized request approver to match the stored server approver. The login-success copy now states that controlled `claim_only` uses Stage A approval, controlled `single_save` uses Stage B approval, and `batch_save` plus publish remain closed.

The exact RED selection then returned:

```text
4 passed in 1.32s
```

Focused full-file checks:

```text
tests/test_task_start_guard.py: 118 passed in 33.55s
tests/test_login_flow.py: 357 passed in 149.25s
```

Final combined review regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_task_start_guard.py tests/test_acquisition_claim_workflow.py tests/test_final_delivery_check_summary.py tests/test_login_flow.py
```

Result:

```text
501 passed in 202.26s
```

## Second review fix: non-ASCII approver comparison

Second review found that `hmac.compare_digest()` was receiving normalized Python `str` values. Matching non-ASCII approvers such as `张三` therefore raised `TypeError` instead of allowing the approved task to start.

### Second review RED

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_task_start_guard.py::test_claim_only_start_accepts_matching_chinese_stage_a_approver tests/test_task_start_guard.py::test_single_save_start_accepts_matching_chinese_stage_b_approver
```

Result before the fix:

```text
2 failed in 1.43s
```

Both Stage A and Stage B returned HTTP 500 instead of 200. The active comparison primitive reproduced the underlying exception:

```text
TypeError: comparing strings with non-ASCII characters is not supported
```

### Second review GREEN

The minimal implementation keeps trimming, non-empty checks, and mismatch rejection unchanged, but compares the normalized approver values as UTF-8 bytes.

Exact RED selection after the fix:

```text
2 passed in 0.97s
```

Approval-focused regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_task_start_guard.py -k "approval or approver"
```

```text
24 passed, 96 deselected in 5.69s
```

Complete start-guard regression:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_task_start_guard.py
```

```text
120 passed in 29.15s
```
