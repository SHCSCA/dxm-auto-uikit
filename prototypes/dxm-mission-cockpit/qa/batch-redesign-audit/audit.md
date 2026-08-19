# Batch redesign source audit

## Captured source state

- `01-current-cockpit.png`: the accepted visual language, but the flow combines claim and edit around one product.
- `02-current-template.png`: version creation and validation are present, while the rule values are not editable.
- `03-current-task-list.png`: the landing experience presents single-product missions instead of two batch-oriented business flows.

## Product gaps found

1. Claim-to-store and edit-claimed-product need separate entry points, approval scopes and evidence contracts.
2. Batch UX must still execute one product at a time in one visible browser, with every item independently recorded.
3. UNKNOWN, identity drift and incomplete evidence must stop the remaining queue without undoing completed items or blindly retrying.
4. Template changes need draft versions, editable fields, comparison, validation and explicit activation; active versions referenced by historical work cannot be changed in place.
5. Trust cannot be represented by an embedded fake screenshot. The product needs an independent visible browser, with batch, product, store, session, current action and control owner bound together.

## Grounded redesign direction

The accepted visual system is retained. Information architecture changes to workbench, claim batch, edit batch, template center, browser workspace, records/issues and settings. The new UI is explicit that it demonstrates the intended contract while the current production repository still does not release native batch execution.
