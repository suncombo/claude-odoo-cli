# odoo-cli — Design Spec

**Date:** 2026-06-09
**Status:** Approved design, pending implementation plan
**Supersedes:** `suncombo-odoo-mcp` (FastMCP server, v0.3.2)

## Goal

Replace the existing `odoo-mcp` FastMCP server with a **Claude Code plugin** that bundles a
single-file, zero-dependency Python CLI plus a skill and a slash command. The CLI talks to
Odoo over JSON-RPC (reusing the existing `OdooClient` logic).

### Why (motivations, in priority order)

1. **Save context window** — the MCP's 8 tool schemas are always loaded. A skill loads only
   when relevant; the CLI is invoked via Bash and costs nothing when idle.
2. **Usable from shell / scripts** — the same script runs in a terminal, cron, or any pipeline,
   not only inside Claude.
3. **Better maintainability / testability** — a pure-stdlib CLI is trivial to unit-test
   (mock `urllib`) and version, with no MCP runtime dependency.
4. **Fully replace the MCP** — once verified, the live `mcp__odoo-prd-truney` registration is
   removed.
5. **Output to file to cut tokens** — large query results are written to a file and summarized
   on stdout instead of dumping into context.

## Non-goals (YAGNI)

- No PyPI publishing for the CLI (plugin is the distribution channel).
- No friendlier domain mini-language — JSON-string flags only (matches current MCP syntax,
  zero LLM relearning).
- No human-pretty table output (`--format table`) in v1 — JSON-first.
- No rewrite of the old `odoo-mcp` repo; it is archived as-is.

## Architecture

The `odoo-cli` repo **is** the plugin. Repo folder is `odoo-cli`; the plugin manifest `name`
is `odoo` (this drives the slash-command namespace `/odoo:...`).

```
odoo-cli/                          # repo root = plugin root
├── .claude-plugin/
│   ├── plugin.json                # manifest, name="odoo"
│   └── marketplace.json           # local marketplace for install/testing
├── skills/
│   └── odoo/
│       └── SKILL.md               # when-to-use + command reference + JSON gotchas + output behavior
├── commands/
│   └── odoo.md                    # /odoo:odoo flexible entry point
├── scripts/
│   └── odoo.py                    # single-file CLI (pure stdlib: urllib + json + argparse)
├── tests/
│   └── test_odoo.py               # pytest, mocks urlopen — no live Odoo needed
├── config.example.json            # profile config example
├── docs/superpowers/specs/        # this spec
└── README.md
```

- `scripts/odoo.py` inlines the existing `OdooClient` (JSON-RPC call, lazy auth, uid cache)
  so the file is fully self-contained and runs as `python3 scripts/odoo.py ...` with no install.
- Skill and command invoke it as `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/odoo.py" <args>`.
  `${CLAUDE_PLUGIN_ROOT}` expands to the plugin's absolute path in skill/command bodies and
  when Claude runs Bash.

## CLI command surface

Eight subcommands mirror the existing MCP tools 1:1. Complex arguments are passed as **JSON
strings** on flags — identical to the current MCP call syntax.

```
odoo.py search-read    <model> [--domain JSON] [--fields JSON] [--limit N] [--offset N] [--order STR]
odoo.py read           <model> --ids JSON [--fields JSON]
odoo.py create         <model> --values JSON
odoo.py write          <model> --ids JSON --values JSON
odoo.py unlink         <model> --ids JSON
odoo.py list-models    [--search TERM]
odoo.py list-fields    <model> [--attributes JSON]
odoo.py execute-method <model> <method> [--args JSON] [--kwargs JSON]
odoo.py config         list | use <name>
```

**Shared flags** (on every data subcommand): `--profile NAME`, `--out PATH`, `--inline`,
`--lang CODE` (sugar for `context.lang`, used in translation workflows),
`--max-inline-bytes N`.

**JSON-string tolerance:** every JSON flag value is first attempted with `json.loads`; on
failure it falls back to the literal string. (Preserves the current MCP's
"LLM passed an array as a string" robustness.)

Mapping examples:

| MCP call | CLI |
|---|---|
| `search_read(model="res.partner", domain=[["is_company","=",true]], fields=["name"])` | `odoo.py search-read res.partner --domain '[["is_company","=",true]]' --fields '["name"]'` |
| `write(model="product.template", ids=[10209], values={"name":"中文名"})` lang zh_TW | `odoo.py write product.template --ids '[10209]' --values '{"name":"中文名"}' --lang zh_TW` |
| `execute_method(model="sale.order", method="action_confirm", args=[[5]])` | `odoo.py execute-method sale.order action_confirm --args '[[5]]'` |

## Configuration & profiles

Config file: `~/.config/odoo-cli/config.json`.

```json
{
  "default_profile": "prod",
  "profiles": {
    "prod": { "url": "https://...", "db": "...", "user": "...", "password": "..." },
    "dev":  { "url": "http://localhost:8069", "db": "odoo", "user": "admin" }
  }
}
```

**Profile resolution order:** `--profile` flag → `ODOO_PROFILE` env → config `default_profile`.

**Per-field env override:** `ODOO_URL` / `ODOO_DB` / `ODOO_USER` / `ODOO_PASSWORD` override the
selected profile's corresponding fields. So the password can be omitted from the file and
supplied via env / a secret manager. If no config file exists at all, these four env vars are
used directly — backward-compatible with the current MCP behavior.

`odoo.py config list` prints known profiles (passwords masked) and the active default.
`odoo.py config use <name>` rewrites `default_profile`.

## Output behavior (token-saving core)

- Default: serialize the result as compact JSON to **stdout**.
- If the serialized result exceeds the threshold (default **~16 KB or 50 records**, tunable
  via `--max-inline-bytes`), **auto-spill to a file**: write the full JSON to
  `$TMPDIR/odoo-cli/<model>-<seq>.json` and print a summary to stdout instead:

  ```json
  {"saved_to": "/tmp/odoo-cli/res.partner-3.json", "count": 80, "bytes": 24576,
   "fields": ["name","email","..."], "sample": [ /* first 1-2 records */ ]}
  ```

- `--out PATH` — force write the full result to PATH and print the summary.
- `--inline` — force the full result to stdout, never spill.

Filename uses a monotonic sequence/PID-based suffix (no wall-clock dependency required).

## Error handling

Reuse the existing `_handle_error` classification (connection refused / permission /
`AccessError` / `MissingError` / other). The CLI additionally:

- Prints `{"error": "..."}` to stdout (parseable by Claude).
- Exits with a **non-zero code** so shells/scripts can detect failure:
  - `1` Odoo server/business error
  - `2` usage / argument error
  - `3` connection failure (cannot reach Odoo)

## Slash command `/odoo:odoo`

`commands/odoo.md`. Plugin commands are **always namespaced**, so bare `/odoo` is impossible;
`/odoo:odoo` is the closest form (typing `/odoo` surfaces it in the menu).

Behavior — flexible entry point keyed on `$ARGUMENTS`:

- If `$ARGUMENTS` looks like a subcommand (starts with a known verb such as `search-read`,
  `read`, `create`, …), the command **passes it straight through** to
  `"${CLAUDE_PLUGIN_ROOT}/scripts/odoo.py"` and shows the result. Fast manual queries.
- Otherwise treat `$ARGUMENTS` as a **natural-language request** and fulfill it using the
  `odoo` skill (which explains the CLI and Odoo conventions).

## Skill (`skills/odoo/SKILL.md`)

Frontmatter: `name: odoo`, a `description` covering when to use it (any Odoo ERP read/write,
schema exploration, workflow actions, translations), and `allowed-tools` scoping Bash to the
bundled script.

Body carries the knowledge currently in the MCP `instructions` block, adapted to the CLI:

- How to invoke: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/odoo.py" <subcommand> ...`.
- Domain syntax, operators, AND/OR prefix logic.
- The `create` "pass a plain dict" and `execute-method` args-shape gotchas.
- Common patterns (translate, copy, confirm SO) as CLI invocations.
- Output behavior: results may be written to a file — read the `saved_to` path when needed,
  or pass `--inline` for small results; specify `--fields` to keep payloads small.
- Profile selection via `--profile`.

## Testing

`pytest`, mocking `urllib.request.urlopen` with canned JSON-RPC responses — no live Odoo
required. Coverage:

- Each subcommand → correct `execute_kw(model, method, args, kwargs)` mapping.
- JSON-string flag parsing, including the literal-string fallback.
- Output threshold: small → stdout, large → spill + summary; `--out` / `--inline` overrides.
- Error classification → message + exit code.
- Profile/env resolution precedence.

Optional live integration test, gated behind an env var (e.g. `ODOO_CLI_LIVE=1`), hitting a
real instance.

Implementation follows TDD (test-first per behavior).

## Migration & rollout

1. Build the plugin; test locally with `claude --plugin-dir /Users/truney/projects/odoo-cli`,
   reloading via `/reload-plugins` after edits. (Local `marketplace.json` provides the
   install path for normal use.)
2. Verify the CLI performs real Odoo operations against the prod profile.
3. **Only after verification**, remove the live `mcp__odoo-prd-truney` MCP registration —
   the plugin fully replaces it.
4. Keep the old `odoo-mcp` repo archived as-is.

## Open questions / future work

- A human-friendly `--format table` output mode (deferred).
- Additional convenience subcommands (e.g. `count`) if usage shows a need.
- Publishing the plugin to a shareable marketplace beyond the local one.
