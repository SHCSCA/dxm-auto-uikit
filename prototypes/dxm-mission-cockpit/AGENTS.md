# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

## Current product direction (2026-07-21)

- Remove the claim/acquisition experience from this prototype. The primary product is batch editing for products already in the live 店小秘商品箱.
- The operator prepares the scope in 店小秘; this system reads and freezes that live scope. Do not add a local product or store picker.
- Approval is once per immutable batch. After approval, products run sequentially and advance automatically without per-product review or a “start next item” click.
- Normal success continues silently. Only pre-save validation exceptions may be isolated; `UNKNOWN`, identity drift, session loss, or publish risk must stop the batch for reconciliation.
- Use the production frontend (`app/frontend`) as the functional and visual baseline. The previous prototype skin is comparison material only.
