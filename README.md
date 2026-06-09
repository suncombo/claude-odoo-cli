# odoo-cli

Claude Code plugin for Odoo ERP over JSON-RPC. Bundles a zero-dependency Python CLI
(`scripts/odoo.py`), an `odoo` skill, and an `/odoo:odoo` slash command. Replaces the
older `suncombo-odoo-mcp` MCP server.

## Configure

Copy `config.example.json` to `~/.config/odoo-cli/config.json` and edit profiles.
Passwords can be omitted from the file and supplied via `ODOO_PASSWORD` (per-field
`ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD` override the selected profile).

## Use from the shell

```bash
python3 scripts/odoo.py search-read res.partner --fields '["name","email"]' --limit 5
python3 scripts/odoo.py --help
python3 scripts/odoo.py config list
```

## Install into Claude Code

From GitHub (anyone):

```bash
claude plugin marketplace add suncombo/claude-odoo-cli
claude plugin install odoo@claude-odoo-cli
```

Then invoke via the `odoo` skill (Claude runs the CLI for you) or the `/odoo:odoo <args>`
slash command. After installing, create your config (see **Configure** above).

Local development: `claude --plugin-dir /path/to/claude-odoo-cli`, then `/reload-plugins`
after edits.

## Test

```bash
uv run --with pytest pytest
```

## Output behavior

Small results print JSON to stdout; large results (> ~16 KB or > 50 records) write to
`$TMPDIR/odoo-cli/` with a stdout summary. Use `--out PATH` or `--inline` to override.
