# DXM 店小秘逐件批次原型 — Design QA

## Comparison target

- Source visual truth: `qa/dependency-redesign-audit/01-system-workbench-before.png`
- Source flow evidence: `qa/dependency-redesign-audit/02-system-product-picker-before.png`
- Rendered implementation: `qa/dependency-redesign-final/01-workbench.png`
- Corrected claim screen: `qa/dependency-redesign-final/02-claim-live-scene.png`
- Full-view comparison: `qa/dependency-redesign-final/11-reference-vs-implementation.png`
- Focused flow comparison: `qa/dependency-redesign-final/12-claim-before-vs-final.png`
- Primary viewport: 1280 × 720 CSS px, desktop, light theme, local prototype data
- Responsive evidence: 900 × 720 and 680 × 820 CSS px
- URL: `http://127.0.0.1:4173/#/tasks/current`

The source and implementation use the same accepted DXM visual system and viewport. The focused claim comparison intentionally shows different product states: the source contains the rejected local product picker, while the implementation shows the corrected 店小秘 live-scene intake. It is used to compare design-system continuity and to verify that the incorrect interaction was actually removed.

## Findings

No actionable P0, P1, or P2 findings remain.

- Fonts and typography: Noto Sans SC Variable, weights, hierarchy, line height, and compact operations-console density remain consistent with the accepted source. Chinese wrapping is readable at 1280, 900, and 680 widths.
- Spacing and layout rhythm: the navy sidebar, content margins, 8–10 px radii, card borders, blue/green flow split, and dense control spacing remain aligned with the source. No document-level horizontal overflow remains.
- Colors and visual tokens: the navy shell, primary blue, edit green, warning amber, neutral borders, and white surfaces preserve the established semantic palette and contrast.
- Image quality and assets: the DXM mark remains a real source asset, and interface icons use the existing Phosphor icon family. The browser HUD uses a cropped copy of the current project's real 店小秘 test evidence at `public/assets/dxm-real-evidence-semi-managed.png`; no fake product page, handcrafted SVG, emoji, or CSS illustration substitutes it.
- Copy and content: all reachable core screens now state that products and stores remain in 店小秘, every click starts one item only, every item receives a separate authorization, and UNKNOWN stops the sequence.
- Interaction states: template edit/save/versioning, claim/edit plan creation, live item capture, per-item approval, manual takeover and safe handback, UNKNOWN blocking, records tabs, and the real 店小秘 link were exercised successfully.
- Accessibility: headings, landmarks, labels, tabs, radio/checkbox semantics, disabled states, focus styles, alt text, and button names are present. Keyboard-oriented controls remain native HTML elements.

## Full-view comparison evidence

`qa/dependency-redesign-final/11-reference-vs-implementation.png` places the accepted workbench capture on the left and the corrected implementation on the right. Navigation, page frame, main hierarchy, card proportions, typography, color tokens, and CTA placement remain visually continuous. The intentional content change is the visible single-item contract: counts change from a preselected batch inventory model to `1` item per explicit start.

## Focused region comparison evidence

`qa/dependency-redesign-final/12-claim-before-vs-final.png` compares the old local product picker with the new 店小秘现场 step at the same 1266 × 713 captured size. The final screen removes search, selection checkboxes, local product rows, and local store choice while preserving the same stepper, card system, spacing, and primary action hierarchy. This focused comparison was required because the interaction change is the central acceptance condition and is not legible enough in the workbench-only comparison.

Additional final-state evidence:

- `qa/dependency-redesign-final/03-edit-template-contract.png`
- `qa/dependency-redesign-final/04-edit-item-approval.png`
- `qa/dependency-redesign-final/05-template-real-fields.png`
- `qa/dependency-redesign-final/06-browser-session-console.png`
- `qa/dependency-redesign-final/07-item-records.png`
- `qa/dependency-redesign-final/08-settings-single-item.png`
- `qa/dependency-redesign-final/14-browser-live-hud.png`

## Comparison history

### Iteration 1 — blocked

- P1: the claim and edit builders still presented locally selectable products and stores.
  - Fix: replaced both builders with 店小秘 live-scene intake, a stop limit, a single-item loop, per-item approval, and runtime item creation only after `开始下一件`.
  - Post-fix evidence: `02-claim-live-scene.png`, `03-edit-template-contract.png`, and `12-claim-before-vs-final.png`.
- P1: batch construction pre-generated all future product items and could imply one approval for the whole batch.
  - Fix: future positions are non-product UI slots; one observed item is created per explicit start, then independently approved and completed before the next start becomes available.
  - Post-fix evidence: `04-edit-item-approval.png` and the interaction run described below.
- P1: the template screen could suggest arbitrary template fields.
  - Fix: normalized every template to the current project's 9 canonical groups, 60 fields, and 24 required fields; removed field duplication while retaining edit, draft save, validation, enable, comparison, and history.
  - Post-fix evidence: `05-template-real-fields.png` and `13-template-680.png`.

### Iteration 2 — blocked

- P2: the settings page expanded its single CSS-grid track beyond the available main-stage width at 1280 px, producing a horizontal scrollbar.
  - Fix: constrained `.secondary-view` and every direct grid item with `min-width: 0`, `width/max-width: 100%`.
  - Post-fix evidence: `08-settings-single-item.png`; measured document width 1266 px inside a 1280 px viewport.
- P2: the independent HUD contained a large empty placeholder and could look like a simulated browser rather than evidence-backed handoff.
  - Fix: replaced it with the current project's real 店小秘 field evidence, labeled non-realtime, plus a direct `打开真实店小秘` action and explicit Session HUD.
  - Post-fix evidence: `14-browser-live-hud.png`.
- P2: requested HUD routes could prefer the previously bound batch, and manual handback could return an already captured item to a generic paused state.
  - Fix: requested batch now wins unless another batch is actually running; handback restores `awaiting_approval` when an item has already been read, otherwise `ready`.
  - Post-fix evidence: manual takeover → handback returned the same item to `批准并开始本件`; no second item was created.

### Iteration 3 — passed

- Re-captured desktop and responsive evidence after the fixes.
- No remaining P0/P1/P2 visual, responsive, or core-interaction findings.

## Primary interactions tested

- Claim flow: 店小秘 scene readback → stop limit → `claim_only` contract → plan confirmation → `开始下一件` → current item read → separate item approval → success readback → stopped awaiting the next explicit start.
- Edit flow: 店小秘商品箱 scene → 60-field ready template → plan confirmation → one Stage A-matched item read → `CONFIRM_DXM_SAVE_ONLY` approval → saved + unpublished readback → stopped awaiting the next explicit start.
- Manual control: takeover before mutation → handback → the same captured item returns to `等待逐件批准`; running interruption remains UNKNOWN.
- Templates: edit an enabled template into a patch draft, change a real field value, save the draft, and retain validation/version history.
- Records: batch, item, evidence, and UNKNOWN tabs all render and preserve per-item evidence semantics.
- Real browser trust: `打开真实店小秘` opened `dianxiaomi.com` in a visible browser tab; the temporary QA tab was then closed.
- UNKNOWN: the historical unknown batch exposes the manual-reconciliation route and no next-item or retry action.

## Browser and build checks

- Browser-rendered evidence captured with the selected Codex in-app browser.
- 1280, 900, and 680 px widths have no document-level horizontal overflow on the checked core screens.
- Browser console checked: no localhost application errors. Browser-plugin telemetry timeouts to `ab.chatgpt.com` were external to the prototype and did not appear as page application errors.
- `npm run build` passes; the remaining Vite notice is the existing large-chunk advisory.

## Residual test gaps

- This is a target interaction prototype. It intentionally does not authenticate, attach CDP/PID identity, or execute mutation against a real 店小秘 account.
- The real-link check reached the 店小秘 public entry because the in-app browser did not carry the user's authenticated Chrome session. The production requirement remains one visible, identity-verified Chrome Session.

## Implementation checklist

- [x] Remove system-owned product and store selection.
- [x] Separate claim and edit as two supervised flows.
- [x] Create only one runtime item per explicit start.
- [x] Require a separate authorization and evidence set per item.
- [x] Use current-project template fields only.
- [x] Keep the real 店小秘 browser visible and distinguish live state from evidence/demo state.
- [x] Verify responsive fit, console, build, and comparison evidence.

final result: passed
