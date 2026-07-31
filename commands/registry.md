---
description: Ask which Odoo module owns or extended something — installed modules, model extensions, view/ACL provenance. Read-only.
argument-hint: "[model sale.order  |  module truney_hedge_sale  |  modules --state installed  |  a plain-English provenance question]"
---

The user invoked `/odoo:registry` with: `$ARGUMENTS`

Decide how to handle it:

1. **Direct passthrough** — if `$ARGUMENTS` begins with a known subcommand verb
   (`model`, `module`, `modules`), run it verbatim and show the result:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/registry/scripts/registry.py" $ARGUMENTS
   ```

2. **Natural language** — otherwise, treat `$ARGUMENTS` as a provenance question
   (e.g. "哪些模組改過 sale.order 的欄位", "truney_hedge_sale 有裝嗎") and fulfill it
   using the `registry` skill: pick the right subcommand and run the CLI the same way.

Reach for the `odoo` skill instead when the question is about record data or what a
field *is* — this command answers what *added* it.
