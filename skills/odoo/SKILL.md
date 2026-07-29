---
name: odoo
description: Use for any Odoo ERP operation over JSON-RPC — search/read/create/write/delete records, explore models and fields, run workflow actions (e.g. confirm a sale order), or translate fields. Invokes the bundled zero-dependency CLI via Bash.
allowed-tools: Bash(python3 *)
metadata:
  author: truney
  version: "0.3.0"
---

# Odoo ERP CLI

This skill bundles a zero-dependency Python CLI at **`scripts/odoo.py` inside this skill's
own directory**. Run it with `python3`, pointing at wherever this skill is installed:

```bash
python3 <skill-dir>/scripts/odoo.py <subcommand> [options]
```

Resolve `<skill-dir>` by how the skill was installed:

- **Installed skill (skills.sh / most agents):** the directory holding this `SKILL.md`,
  e.g. `~/.claude/skills/odoo/`, `~/.codex/skills/odoo/`, `~/.config/opencode/skills/odoo/`,
  or a project-local `./.<agent>/skills/odoo/`. → `python3 ~/.claude/skills/odoo/scripts/odoo.py …`
- **Claude Code plugin:** `python3 "${CLAUDE_PLUGIN_ROOT}/skills/odoo/scripts/odoo.py" …`

Below, `odoo.py` is shorthand for that full path. Select the Odoo instance with
`--profile <name>` (defaults to the config's `default_profile`). Connection comes from
`~/.config/odoo-cli/config.json`; `ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD` override
individual fields.

## Subcommands

| Subcommand | Purpose |
|---|---|
| `search-read <model> [--domain JSON] [--fields JSON] [--limit N] [--offset N] [--order STR]` | Search + read records. **Always pass `--fields`** to keep payloads small. Returns **all** matching rows unless `--limit` is given — see below. |
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

### `search-read` row limits

`--limit` is **not** set by default: `search-read` returns every matching row,
so counting and inventory queries are correct without extra flags. Large
results spill to a file automatically, so this does not flood the context.

A 10,000-row safety cap protects the Odoo worker. Filling it is an **error**
(exit 2), never a short result:

```
{"error": "sale.order.line: filled the 10000-row safety cap, so this result is
incomplete. Narrow --domain, or pass --limit explicitly to accept a truncated slice."}
```

Pass `--limit N` when you deliberately want the first N rows — an explicit
limit is never treated as an error, even when completely filled.

## Read-only profiles

A profile carrying `"readonly": true` refuses anything that could modify data.
`create`, `write`, `unlink` and any unrecognised subcommand are rejected before the
CLI even authenticates:

```
{"error": "read-only profile: 'write' can modify data"}   # exit 2
```

`execute-method` is judged by method name, since it can reach anything the ORM
exposes. Only `read_group`, `search_count`, `fields_get` and `name_search` pass —
the read paths the other subcommands cannot cover, notably counting and aggregating
past `search-read`'s row cap.

Use it for an instance that must never be written to: a frozen legacy system, or a
production database you only report on. The flag lives on the profile rather than
the invocation, so it protects the target no matter who calls or how.

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
python3 <skill-dir>/scripts/odoo.py write product.template \
  --ids '[10209]' --values '{"name":"中文名"}' --lang zh_TW

# Copy a record with overrides
python3 <skill-dir>/scripts/odoo.py execute-method product.template \
  copy --args '[[10209]]' --kwargs '{"default":{"name":"New"}}'

# Confirm a sale order
python3 <skill-dir>/scripts/odoo.py execute-method sale.order \
  action_confirm --args '[[5]]'
```

## Output behavior (saves context)

Small results print as JSON to stdout. Large results (> ~16 KB or > 50 records)
are written to a file under `$TMPDIR/odoo-cli/` and stdout shows a summary:
`{"saved_to": "...", "count": N, "fields": [...], "sample": [...]}`. Read the
`saved_to` file only when you need the full data. Force behavior with `--out PATH`
(write) or `--inline` (never spill). Errors print `{"error": "..."}` and exit
non-zero (1 Odoo error, 2 usage, 3 connection).
