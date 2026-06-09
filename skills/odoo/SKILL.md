---
name: odoo
description: Use for any Odoo ERP operation over JSON-RPC — search/read/create/write/delete records, explore models and fields, run workflow actions (e.g. confirm a sale order), or translate fields. Invokes the bundled zero-dependency CLI via Bash.
allowed-tools: Bash(python3 *)
---

# Odoo ERP CLI

Run Odoo operations through the bundled CLI. Always invoke it as:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/odoo.py" <subcommand> [options]
```

Select the instance with `--profile <name>` (defaults to the config's
`default_profile`). Connection comes from `~/.config/odoo-cli/config.json`;
`ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD` override individual fields.

## Subcommands

| Subcommand | Purpose |
|---|---|
| `search-read <model> [--domain JSON] [--fields JSON] [--limit N] [--offset N] [--order STR]` | Search + read records. **Always pass `--fields`** to keep payloads small. |
| `read <model> --ids JSON [--fields JSON]` | Read records by id. |
| `create <model> --values JSON` | Create one record. Returns the new id. |
| `write <model> --ids JSON --values JSON` | Update records. |
| `unlink <model> --ids JSON` | Delete records. |
| `list-models [--search TERM]` | List models (`name` + technical `model`). |
| `list-fields <model> [--attributes JSON]` | Field definitions. |
| `execute-method <model> <method> [--args JSON] [--kwargs JSON]` | Any public method (workflow actions, business logic). |
| `config list` / `config use <name>` | Inspect / switch the default profile. |

Common flags on data commands: `--profile`, `--out PATH`, `--inline`,
`--lang CODE`, `--max-inline-bytes N`.

## Domain syntax

`[["field", "op", value]]` — ops: `=, !=, like, ilike, in, not in, >, <, >=, <=, =?, child_of`.
Prefix logic operators: `"&"` (AND, default), `"|"` (OR), `"!"` (NOT).

- OR: `["|", ["name","ilike","gold"], ["name","ilike","silver"]]`
- AND+OR: `["&", ["active","=",true], "|", ["name","ilike","a"], ["name","ilike","b"]]`

## Gotchas

- `create --values` takes a plain JSON object: `'{"name":"X"}'` (not wrapped in a list).
- `execute-method --args` is a list of positional args: `copy([10])` → `--args '[[10]]'`;
  `write([id], vals)` → use the dedicated `write` command instead.
- JSON flags tolerate a bare string: an unparseable value is passed through literally.

## Common patterns

```bash
# Translate a product name to Traditional Chinese
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/odoo.py" write product.template \
  --ids '[10209]' --values '{"name":"中文名"}' --lang zh_TW

# Copy a record with overrides
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/odoo.py" execute-method product.template \
  copy --args '[[10209]]' --kwargs '{"default":{"name":"New"}}'

# Confirm a sale order
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/odoo.py" execute-method sale.order \
  action_confirm --args '[[5]]'
```

## Output behavior (saves context)

Small results print as JSON to stdout. Large results (> ~16 KB or > 50 records)
are written to a file under `$TMPDIR/odoo-cli/` and stdout shows a summary:
`{"saved_to": "...", "count": N, "fields": [...], "sample": [...]}`. Read the
`saved_to` file only when you need the full data. Force behavior with `--out PATH`
(write) or `--inline` (never spill). Errors print `{"error": "..."}` and exit
non-zero (1 Odoo error, 2 usage, 3 connection).
