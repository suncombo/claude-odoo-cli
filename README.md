# odoo-cli

Agent skill + zero-dependency Python CLI for Odoo ERP over JSON-RPC. The skill bundles its
own CLI at `skills/odoo/scripts/odoo.py`, so it works in any agent that supports the open
Agent Skills format. Also ships as a Claude Code plugin with an `/odoo:odoo` slash command.
Replaces the older `suncombo-odoo-mcp` MCP server.

## Configure

Copy `config.example.json` to `~/.config/odoo-cli/config.json` and edit profiles.
Passwords can be omitted from the file and supplied via `ODOO_PASSWORD` (per-field
`ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD` override the selected profile).

Mark a profile `"readonly": true` when the instance behind it must never be written
to — a frozen legacy system, or a production database you only report on. `create`,
`write` and `unlink` are then refused with exit 2 before the CLI authenticates, and
`execute-method` is limited to `read_group`, `search_count`, `fields_get` and
`name_search`.

## Use from the shell

```bash
python3 skills/odoo/scripts/odoo.py search-read res.partner --fields '["name","email"]' --limit 5
python3 skills/odoo/scripts/odoo.py --help
python3 skills/odoo/scripts/odoo.py config list
```

## Install the skill (any agent)

Works with Claude Code, Codex, OpenCode, Cursor, and 70+ agents via the open
[skills.sh](https://skills.sh) installer:

```bash
# Install globally for all your projects
npx skills add suncombo/claude-odoo-cli -g

# Or install into a specific agent
npx skills add suncombo/claude-odoo-cli -a claude-code -a codex
```

This drops the self-contained `odoo` skill (CLI included) into each agent's skills directory.

## Install as a Claude Code plugin

```bash
claude plugin marketplace add suncombo/claude-odoo-cli
claude plugin install odoo@claude-odoo-cli
```

Then invoke via the `odoo` skill (the agent runs the CLI for you) or the `/odoo:odoo <args>`
slash command. After installing either way, create your config (see **Configure** above).

Local development: `claude --plugin-dir /path/to/claude-odoo-cli`, then `/reload-plugins`
after edits.

## Test

```bash
uv run --with pytest pytest
```

## Output behavior

Small results print JSON to stdout; large results (> ~16 KB or > 50 records) write to
`$TMPDIR/odoo-cli/` with a stdout summary. Use `--out PATH` or `--inline` to override.
