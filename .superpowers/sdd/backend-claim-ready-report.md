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
