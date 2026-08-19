# Batch redesign QA inventory

| User-visible claim | Functional check | Evidence |
| --- | --- | --- |
| Two separate primary flows | Open claim and edit builders from the workbench | `01-workbench.png`, `02-claim-selection.png`, `03-edit-approval.png` |
| Both flows are batch-oriented | Select three products, approve the exact list, create the batch | wizard and cockpit screenshots |
| Batch execution is supervised serial work | Start one item and confirm only one running item across both tabs | `04-batch-cockpit.png`, `07-visible-browser.png` |
| Interrupting a possible write is conservative | Start the next item, immediately pause, confirm `UNKNOWN` and disabled resume | `05-unknown-stop.png` |
| UNKNOWN requires real human intent | Bind visible Session, take over, attest review, then record one explicit outcome | records/issues interaction |
| Templates are editable and versioned | Edit an active template into a patch draft; edit metadata/rule values; save or discard | `06-template-editor.png` |
| Rules are actually frozen | Compare approval and cockpit digests; inspect shared section/rule content | edit approval/cockpit interaction |
| Visible browser is honest | Verify batch/product/Session/action, disabled mock mutations, and prototype warnings | `07-visible-browser.png` |
| Failure is not shown as success | Confirm no-effect outcome yields `completed_with_issues`, failed and skipped counts | records batch summary |
| Evidence can be inspected | Expand evidence details and verify ID/time/type/source/prototype note; inspect manual Session evidence | `08-records.png` |
| Responsive layouts remain usable | Check 900 px and 680 px widths, no document horizontal overflow | `15-workbench-900-final.png`, `16-workbench-680-final.png` |

## Off-happy-path checks

1. Fewer than two products or missing consent does not create a batch.
2. A running batch prevents another batch from using the unique browser.
3. A stale timer cannot complete an interrupted or expired attempt.
4. An active template is never edited in place; invalid rule content cannot be validated and enabled.
5. A stale standalone-browser URL follows the authoritative bound batch instead of reclaiming the Session.

## Sign-off boundary

This inventory validates the local product-target prototype only. It does not claim released batch APIs, a real DXM login, real mutations, or production readiness.
