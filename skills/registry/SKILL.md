---
name: registry
description: Use to find out which Odoo module something came from, or what a module contributed — which modules are actually installed, which of them extended a given model's fields, and which module owns a view, ACL, or record rule. Read-only, answered from the live database's own registry (ir.model.data, ir.module.module). Reach for this when the question is provenance ("who added this", "which modules touch sale.order", "is this module really installed"), not record data.
allowed-tools: Bash(python3 *)
metadata:
  author: truney
  version: "0.1.0"
---

# Odoo Registry

Provenance questions the source tree cannot answer. Odoo assembles models at run
time from `_inherit` strings, XML view inheritance, and manifest dependencies —
none of which grep or a static call graph can follow. The assembled result is
recorded in Odoo's own tables, so this skill reads those.

**Boundary with the `odoo` skill:** what a field *is* → `odoo list-fields`. What
*added* it → here. This skill never returns record data and never writes.

Run the bundled CLI at **`scripts/registry.py` inside this skill's own
directory** (it imports the `odoo` skill's client, which ships alongside it):

```bash
python3 <skill-dir>/scripts/registry.py <subcommand> [options]
```

Resolve `<skill-dir>` the same way as the `odoo` skill — the directory holding
this `SKILL.md`, or `"${CLAUDE_PLUGIN_ROOT}/skills/registry/scripts/registry.py"`
as a Claude Code plugin. Below, `registry.py` is shorthand for that full path.

Connection flags match the `odoo` skill: `--profile`, `--config`, plus
`--inline` / `--out` / `--max-inline-bytes` for output. Without `--config`, the
same lookup applies — `.config/odoo-cli/config.json` in the current directory,
then `~/.config/odoo-cli/config.json`.

## Subcommands

| Subcommand | Answers |
|---|---|
| `model <model> [--module NAME]` | Which modules extended this model — fields, views, ACLs, record rules. `--module` lists the records that one module owns instead of the counts. |
| `module <name>` | Its install state, what it depends on, and what depends on it. |
| `modules [--state STATE] [--addons-path ROOTS]` | How many modules are in each state; the names in one state; or a diff against code on disk. |

## Reading the output

`model` returns one block per dimension:

```json
{"total": 164, "by_module": {"sale": 77, "ecpay_invoice_tw": 14}, "unattributed": 3}
```

- **`by_module`** is sorted by count, then name.
- **`unattributed`** — records with no `ir.model.data` row, so no module owns
  them: typically fields added through the UI. Present only when non-zero.
  `by_module` alone is never a full census; `total` is.
- **`archived`** — on views and record rules only. Odoo's search hides archived
  rows, so `total` counts live records; this is what was excluded. A view that
  exists in the table but is archived is genuinely not loaded, which is why it is
  reported separately rather than folded in.

`modules --addons-path` diffs the registry against directories holding a
`__manifest__.py` (any depth; hidden directories such as `.claude/worktrees/`
are skipped):

- **`registry_only`** — Odoo knows them, this tree does not have them.
- **`disk_only`** — present but never scanned; no *Update Apps List* since they
  landed, so Odoo cannot install them.
- **`installed_without_code`** — the subset to act on: the database says these
  are running, but their code is absent from the tree compared.

**Only compare against the tree the database actually runs.** Diffing production
against a local checkout reports drift that is really just a version difference,
since deployments pin an image rather than a working copy.

## Notes

- Every subcommand is read-only by construction — no code path calls a write
  method — so it is safe against production whatever the profile allows.
- A misspelled model or module is an error, not an empty result: "has no
  dependencies" and "does not exist" are different answers.
- `model` costs about two round trips per dimension. `--module` narrows in the
  `ir.model.data` domain rather than filtering client-side, so drilling into one
  module stays cheap even on a model with 200 fields.
