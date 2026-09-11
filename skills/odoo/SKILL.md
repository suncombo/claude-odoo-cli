---
name: odoo
description: Use for any Odoo ERP operation over JSON-RPC — search/read/create/write/delete records, count or aggregate with read_group, explore models and fields, run workflow actions (e.g. confirm a sale order), or translate fields.
allowed-tools: Bash(python3 *)
argument-hint: "[search-read res.partner --limit 5  |  a plain-English Odoo request]"
metadata:
  author: truney
  version: "0.7.0"
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
`.config/odoo-cli/config.json` in the current directory if present, otherwise
`~/.config/odoo-cli/config.json` (`--config PATH` overrides both);
`ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD` override individual fields.

## Slash invocation (`/odoo:odoo`)

When invoked as a slash command, `$ARGUMENTS` holds the user's input:

1. **Direct passthrough** — if it begins with a subcommand verb (`search-read`,
   `read`, `create`, `write`, `unlink`, `list-models`, `list-fields`,
   `execute-method`, `config`), run `odoo.py $ARGUMENTS` verbatim and show the result.
2. **Natural language** — otherwise treat it as a request (e.g. "翻譯 product 10209
   名稱成中文"): pick the right subcommand(s) below and run them.
3. **Empty** — briefly list the subcommands.

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
`--lang CODE`, `--context JSON`, `--max-inline-bytes N`. `--context` is a JSON
object merged into the Odoo context; `--lang` wins on the `lang` key.

Which subcommand for which need:

| Need | Use |
|---|---|
| Read records or settings | `search-read` — add `--context '{"active_test":false}'` to include archived rows |
| Count or aggregate | `execute-method <model> search_count` / `read_group` (see below) |
| Field definitions | `list-fields <model>` |
| Find an id by name | `execute-method <model> name_search` |

### `search-read` row limits

`--limit` is **not** set by default: `search-read` returns every matching row.
Filling the 10,000-row safety cap is an **error** (exit 2), never a short result:

```
{"error": "sale.order.line: filled the 10000-row safety cap, so this result is
incomplete. Narrow --domain, or pass --limit explicitly to accept a truncated slice."}
```

Pass `--limit N` when you deliberately want the first N rows — an explicit
limit is never treated as an error, even when completely filled.

## Read-only profiles

A profile carrying `"readonly": true` refuses `create`, `write`, `unlink` and any
unrecognised subcommand before the CLI even authenticates:

```
{"error": "read-only profile: 'write' can modify data"}   # exit 2
```

`search-read`, `read`, `list-models` and `list-fields` pass. `execute-method` is
judged by method name: only `read_group`, `search_count`, `fields_get` and
`name_search` pass — `search_read` does not. Read records with `search-read`
(`--context '{"active_test":false}'` for archived rows), never with
`execute-method search_read`.

## Domain syntax

`[["field", "op", value]]` — ops: `=, !=, like, ilike, in, not in, >, <, >=, <=, =?, child_of`.
Prefix logic operators: `"&"` (AND, default), `"|"` (OR), `"!"` (NOT).

- OR: `["|", ["name","ilike","gold"], ["name","ilike","silver"]]`
- AND+OR: `["&", ["active","=",true], "|", ["name","ilike","a"], ["name","ilike","b"]]`
- `"!"` on `=like` / `=ilike` becomes SQL `NOT` and drops rows where the field is
  NULL; `!= value`, `not in`, `not like`, `not ilike` keep them. To negate a prefix match
  without losing empties, count `[["f","=",false]]` separately and add it.
- `html` fields (`mail.message.body`, `note`, ...) are stored sanitized. The outer
  tag (`<p>`, `<span>`, `<div>`) comes from the write path, not from the code that
  posted the text, and varies between records. Do not anchor `=like` on a tag:
  match the inner text with `ilike`, or, when a prefix anchor is required,
  `search-read` a few rows to see which wrappers exist, run one query per
  observed wrapper, and deduplicate on the parent record (`res_id` for
  `mail.message`).
- A condition through a one2many/many2many path means "some child matches". Two
  such conditions can be satisfied by two different children, and
  `[["lines.f","=",false]]` never matches a parent with no lines. To count parents
  by child conditions, `read_group` the child model by its parent field. On
  Odoo 13, `search_count` through an `auto_join` one2many counts one per matching
  child, not per parent. `execute-method <model> search_count` warns on stderr when
  the domain goes through such a path (stdout unchanged); act on it by switching to
  the `read_group` above.
- A non-stored field with no `search` implementation is silently dropped from the
  domain: Odoo logs an error and returns the unfiltered set. Check `store` with
  `list-fields` first; query the stored field on the related record instead
  (`mail_message_id.subject`, not `subject`).
- Datetimes are stored and compared in UTC and returned to the second. Match a
  timestamp with `>= T` and `< T+1s`, never `=`; compute "today" / "N days ago"
  boundaries in UTC.

## `read_group`

```bash
python3 <skill-dir>/scripts/odoo.py execute-method sale.order read_group \
  --args '[[["state","=","sale"]], ["partner_id","amount_total:sum"], ["partner_id"]]' \
  --kwargs '{"lazy":false}'
```

- Pass `{"lazy":false}` to group by every field in the list; the count column is
  then `__count`. In the default lazy mode only the first field groups and the
  count is `<first_field>_count`.
- many2one group keys come back as `[id, display_name]`.
- The same field twice needs aliases: `"first:min(date_created)"`,
  `"last:max(date_created)"`.
- many2many fields cannot be grouped on (Odoo ≤16); run `search_count` per id instead.

## Gotchas

- `create --values` takes a plain JSON object: `'{"name":"X"}'` (not wrapped in a list).
- `execute-method --args` is a list of positional args: `copy([10])` → `--args '[[10]]'`;
  `write([id], vals)` → use the dedicated `write` command instead.

## Common patterns

```bash
# Translate a product name to Traditional Chinese
python3 <skill-dir>/scripts/odoo.py write product.template \
  --ids '[10209]' --values '{"name":"中文名"}' --lang zh_TW

# Include archived partners
python3 <skill-dir>/scripts/odoo.py search-read res.partner \
  --fields '["name","active"]' --context '{"active_test":false}'

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
