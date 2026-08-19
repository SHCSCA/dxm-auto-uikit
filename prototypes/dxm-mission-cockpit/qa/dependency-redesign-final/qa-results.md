# Dependency redesign QA results

## Functional acceptance

| Check | Result | Evidence |
| --- | --- | --- |
| No in-system product or store picker | PASS | claim/edit builders expose 店小秘 scene readback only |
| Claim batch reads one current item per start | PASS | one item created after `开始下一件`; future slots remained unidentified |
| Edit batch reads one Stage A-matched item per start | PASS | current item entered separate `CONFIRM_DXM_SAVE_ONLY` approval |
| No automatic next item | PASS | successful item returned to `ready`; second slot remained a placeholder |
| Manual takeover before write preserves the same item | PASS | handback restored `awaiting_approval`, not a generic resume state |
| UNKNOWN stops the sequence | PASS | no next-item or retry action on `EDT-20260719-006` |
| Template editing works | PASS | real field value edited and saved as a patch draft |
| Template field catalog matches current project | PASS | 9 groups, 60 fields, 24 required |
| Real browser trust path exists | PASS | direct 店小秘 link opened; HUD separates real evidence from non-live state |
| Records remain per-item and evidence-backed | PASS | batch → item → stage → evidence tabs verified |

## Visual and responsive acceptance

- 1280 × 720: workbench, claim, edit, cockpit, templates, browser, records, settings checked.
- 900 × 720: workbench checked; no document horizontal overflow.
- 680 × 820: claim and templates checked; no document horizontal overflow.
- Settings overflow found in the first pass was fixed with grid min-width constraints and recaptured.
- HUD empty placeholder found in the first pass was replaced with real current-project 店小秘 evidence and recaptured.

## Runtime checks

- Local application console errors: none.
- Build: `npm run build -- --logLevel error` → `BUILD_OK`.
- Design gate: `../../design-qa.md` → `final result: passed`.
