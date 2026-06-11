---
description: Run an Odoo CLI subcommand directly, or fulfill a natural-language Odoo request.
argument-hint: "[search-read res.partner --limit 5  |  a plain-English Odoo request]"
---

The user invoked `/odoo:odoo` with: `$ARGUMENTS`

Decide how to handle it:

1. **Direct passthrough** — if `$ARGUMENTS` begins with a known subcommand verb
   (`search-read`, `read`, `create`, `write`, `unlink`, `list-models`,
   `list-fields`, `execute-method`, `config`), run it verbatim and show the result:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/odoo/scripts/odoo.py" $ARGUMENTS
   ```

2. **Natural language** — otherwise, treat `$ARGUMENTS` as a request (e.g.
   "翻譯 product 10209 名稱成中文") and fulfill it using the `odoo` skill: pick the
   right subcommand(s) and run the CLI the same way.

If `$ARGUMENTS` is empty, briefly list the available subcommands from the skill.
