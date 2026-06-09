# odoo-cli Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `odoo-mcp` FastMCP server with a Claude Code plugin that bundles a single-file, zero-dependency Python CLI (`scripts/odoo.py`), an `odoo` skill, and an `/odoo:odoo` slash command.

**Architecture:** The `odoo-cli` repo **is** the plugin (manifest `name: odoo`). `scripts/odoo.py` inlines the JSON-RPC client and exposes 8 subcommands mirroring the old MCP tools plus a `config` subcommand. Claude and humans both call the same script. Large results auto-spill to a file with a stdout summary to save context.

**Tech Stack:** Python 3.10+ standard library only (`urllib.request`, `json`, `argparse`, `pathlib`). Tests use `pytest`, run via `uv run --with pytest pytest`. Distribution via Claude Code plugin (`${CLAUDE_PLUGIN_ROOT}`, `claude --plugin-dir`).

**Conventions:** TDD (test first), frequent commits. Every commit message ends with:
`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

| Path | Responsibility |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest (name `odoo`). |
| `.claude-plugin/marketplace.json` | Local marketplace for persistent install. |
| `scripts/odoo.py` | The whole CLI: JSON-RPC client, config/profile resolution, output emit, error classification, argparse + subcommand handlers. |
| `skills/odoo/SKILL.md` | When-to-use + CLI reference + Odoo conventions + output behavior. |
| `commands/odoo.md` | `/odoo:odoo` flexible entry point. |
| `config.example.json` | Example profile config. |
| `tests/test_odoo.py` | pytest unit tests (mock `urlopen` / inject fake client). |
| `tests/conftest.py` | Puts `scripts/` on `sys.path` so tests can `import odoo`. |
| `pyproject.toml` | Minimal pytest config. |
| `README.md` | Install + usage docs. |

`scripts/odoo.py` is one file by design (zero-install portability). Internally it is organized in clearly separated sections (client / config / output / errors / handlers / parser) so each concern is independently testable.

**Public surface used across tasks (names are fixed — keep them consistent):**

- `OdooServerError(Exception)`, `ConfigError(Exception)`
- `class OdooClient(url, db, username, password)` → `.execute_kw(model, method, args=None, kwargs=None)`
- `coerce_json(value)`
- `load_config(path)` , `resolve_connection(config, profile=None, env=None)`
- `classify_error(exc, url)` → `(error_dict, exit_code)`
- `emit_result(result, *, model="result", out=None, inline=False, max_inline_bytes=DEFAULT_MAX_INLINE_BYTES, max_inline_records=DEFAULT_MAX_INLINE_RECORDS, stdout=None)`
- `_context_kwargs(args)`
- Handlers `cmd_search_read / cmd_read / cmd_create / cmd_write / cmd_unlink / cmd_list_models / cmd_list_fields / cmd_execute_method / cmd_config` — each `(client, args)`.
- `build_parser()`, `main(argv=None, *, client_factory=OdooClient)`
- Constants: `EXIT_OK=0, EXIT_ODOO=1, EXIT_USAGE=2, EXIT_CONN=3`, `DEFAULT_MAX_INLINE_BYTES=16384`, `DEFAULT_MAX_INLINE_RECORDS=50`, `DEFAULT_CONFIG_PATH`.

---

## Task 1: Repo & plugin scaffolding

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `config.example.json`
- Create: `scripts/odoo.py` (empty shebang stub for now)

- [ ] **Step 1: Create the plugin manifest**

`.claude-plugin/plugin.json`:

```json
{
  "name": "odoo",
  "displayName": "Odoo CLI",
  "description": "Odoo ERP over JSON-RPC — CRUD, search, schema exploration, and workflow actions via a zero-dependency CLI.",
  "version": "0.1.0",
  "author": { "name": "truney", "email": "mick@truney.com" },
  "keywords": ["odoo", "erp", "json-rpc", "cli"]
}
```

- [ ] **Step 2: Create pytest config**

`pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 3: Create the test path shim**

`tests/conftest.py`:

```python
import sys
from pathlib import Path

# Make scripts/odoo.py importable as `odoo` in tests.
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
```

- [ ] **Step 4: Create the example config**

`config.example.json`:

```json
{
  "default_profile": "prod",
  "profiles": {
    "prod": {
      "url": "https://odoo.example.com",
      "db": "prod_db",
      "user": "admin",
      "password": "CHANGE_ME_OR_USE_ODOO_PASSWORD_ENV"
    },
    "dev": {
      "url": "http://localhost:8069",
      "db": "odoo",
      "user": "admin"
    }
  }
}
```

- [ ] **Step 5: Create the CLI stub**

`scripts/odoo.py`:

```python
#!/usr/bin/env python3
"""odoo — single-file CLI for Odoo ERP over JSON-RPC (pure stdlib)."""
```

- [ ] **Step 6: Make the script executable and verify pytest runs (no tests yet)**

Run:
```bash
chmod +x scripts/odoo.py
uv run --with pytest pytest
```
Expected: pytest collects 0 items and exits 0 (`no tests ran`).

- [ ] **Step 7: Commit**

```bash
git add .claude-plugin/plugin.json pyproject.toml tests/conftest.py config.example.json scripts/odoo.py
git commit -m "chore: scaffold odoo-cli plugin (manifest, pytest, stubs)"
```

---

## Task 2: JSON-RPC client (`OdooClient`)

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_odoo.py`:

```python
import json
import pytest
import odoo


class FakeResp:
    def __init__(self, data):
        self._data = json.dumps(data).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_client_authenticates_then_executes(monkeypatch):
    calls = []
    responses = [{"result": 7}, {"result": [{"id": 1, "name": "Acme"}]}]

    def fake_urlopen(req):
        calls.append(json.loads(req.data.decode("utf-8")))
        return FakeResp(responses[len(calls) - 1])

    monkeypatch.setattr(odoo.urllib.request, "urlopen", fake_urlopen)
    client = odoo.OdooClient("http://x", "db", "u", "p")
    result = client.execute_kw("res.partner", "search_read", [[]], {"limit": 5})

    assert result == [{"id": 1, "name": "Acme"}]
    assert calls[0]["params"]["service"] == "common"
    assert calls[0]["params"]["method"] == "authenticate"
    assert calls[1]["params"]["service"] == "object"
    assert calls[1]["params"]["method"] == "execute_kw"
    # args = [db, uid, password, model, method, args, kwargs]
    assert calls[1]["params"]["args"][1] == 7
    assert calls[1]["params"]["args"][3] == "res.partner"


def test_client_caches_uid(monkeypatch):
    calls = []

    def fake_urlopen(req):
        calls.append(json.loads(req.data.decode("utf-8")))
        return FakeResp({"result": 7} if len(calls) == 1 else {"result": True})

    monkeypatch.setattr(odoo.urllib.request, "urlopen", fake_urlopen)
    client = odoo.OdooClient("http://x", "db", "u", "p")
    client.execute_kw("m", "a")
    client.execute_kw("m", "b")
    # authenticate once, two execute_kw calls => 3 total
    assert len(calls) == 3


def test_client_raises_on_error(monkeypatch):
    monkeypatch.setattr(
        odoo.urllib.request,
        "urlopen",
        lambda req: FakeResp({"error": {"data": {"message": "boom"}}}),
    )
    client = odoo.OdooClient("http://x", "db", "u", "p")
    with pytest.raises(odoo.OdooServerError):
        client.execute_kw("m", "a")


def test_client_raises_on_auth_failure(monkeypatch):
    monkeypatch.setattr(
        odoo.urllib.request, "urlopen", lambda req: FakeResp({"result": False})
    )
    client = odoo.OdooClient("http://x", "db", "u", "p")
    with pytest.raises(PermissionError):
        client.execute_kw("m", "a")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --with pytest pytest tests/test_odoo.py -k client`
Expected: FAIL — `AttributeError: module 'odoo' has no attribute 'OdooClient'`.

- [ ] **Step 3: Implement the client**

Append to `scripts/odoo.py`:

```python
import json
import urllib.request


class OdooServerError(Exception):
    """Raised when Odoo returns a JSON-RPC error response."""


class OdooClient:
    """Wraps Odoo's /jsonrpc endpoint with lazy auth and uid caching."""

    def __init__(self, url, db, username, password):
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self._uid = None
        self._request_id = 0

    def _jsonrpc(self, service, method, args):
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": self._request_id,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/jsonrpc",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("error"):
            err = result["error"]
            message = err.get("data", {}).get("message") or err.get("message", str(err))
            raise OdooServerError(message)
        return result.get("result")

    def _authenticate(self):
        if self._uid is not None:
            return self._uid
        uid = self._jsonrpc(
            "common", "authenticate", [self.db, self.username, self.password, {}]
        )
        if not uid:
            raise PermissionError(
                f"Authentication failed for user '{self.username}' on database '{self.db}'"
            )
        self._uid = uid
        return uid

    def execute_kw(self, model, method, args=None, kwargs=None):
        uid = self._authenticate()
        return self._jsonrpc(
            "object",
            "execute_kw",
            [
                self.db,
                uid,
                self.password,
                model,
                method,
                args if args is not None else [],
                kwargs if kwargs is not None else {},
            ],
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k client`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add Odoo JSON-RPC client with lazy auth and uid caching"
```

---

## Task 3: JSON coercion helper

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odoo.py`:

```python
def test_coerce_json_parses_list():
    assert odoo.coerce_json('[["is_company","=",true]]') == [["is_company", "=", True]]


def test_coerce_json_parses_dict():
    assert odoo.coerce_json('{"name": "X"}') == {"name": "X"}


def test_coerce_json_literal_fallback():
    assert odoo.coerce_json("name asc") == "name asc"


def test_coerce_json_none():
    assert odoo.coerce_json(None) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest pytest tests/test_odoo.py -k coerce`
Expected: FAIL — `module 'odoo' has no attribute 'coerce_json'`.

- [ ] **Step 3: Implement**

Append to `scripts/odoo.py`:

```python
def coerce_json(value):
    """Parse a CLI flag value as JSON; fall back to the literal string.

    Preserves the old MCP tolerance for arrays passed as strings.
    """
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k coerce`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add coerce_json flag parser with literal fallback"
```

---

## Task 4: Config & connection resolution

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odoo.py`:

```python
CONFIG = {
    "default_profile": "dev",
    "profiles": {
        "dev": {"url": "http://dev", "db": "d", "user": "u", "password": "p"},
        "prod": {"url": "http://prod", "db": "pd", "user": "pu", "password": "pp"},
    },
}


def test_resolve_explicit_profile_wins():
    c = odoo.resolve_connection(CONFIG, profile="prod", env={})
    assert c["url"] == "http://prod"


def test_resolve_env_profile_over_default():
    c = odoo.resolve_connection(CONFIG, profile=None, env={"ODOO_PROFILE": "prod"})
    assert c["url"] == "http://prod"


def test_resolve_default_profile_fallback():
    c = odoo.resolve_connection(CONFIG, profile=None, env={})
    assert c["url"] == "http://dev"


def test_resolve_per_field_env_override():
    c = odoo.resolve_connection(CONFIG, env={"ODOO_PASSWORD": "secret"})
    assert c["password"] == "secret"
    assert c["url"] == "http://dev"


def test_resolve_no_config_uses_env_and_defaults():
    c = odoo.resolve_connection({}, env={"ODOO_URL": "http://x"})
    assert c["url"] == "http://x"
    assert c["db"] == "odoo"
    assert c["user"] == "admin"


def test_resolve_missing_profile_raises():
    with pytest.raises(odoo.ConfigError):
        odoo.resolve_connection({"profiles": {}}, profile="nope", env={})


def test_load_config_missing_file_returns_empty(tmp_path):
    assert odoo.load_config(tmp_path / "nope.json") == {}


def test_load_config_reads_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(CONFIG), encoding="utf-8")
    assert odoo.load_config(p)["default_profile"] == "dev"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest pytest tests/test_odoo.py -k "resolve or load_config"`
Expected: FAIL — `module 'odoo' has no attribute 'resolve_connection'`.

- [ ] **Step 3: Implement**

Append to `scripts/odoo.py`:

```python
import os
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "odoo-cli" / "config.json"

_CONN_DEFAULTS = {
    "url": "http://localhost:8069",
    "db": "odoo",
    "user": "admin",
    "password": "admin",
}
_ENV_KEYS = {
    "url": "ODOO_URL",
    "db": "ODOO_DB",
    "user": "ODOO_USER",
    "password": "ODOO_PASSWORD",
}


class ConfigError(Exception):
    """Raised for configuration/usage problems (bad profile, etc.)."""


def load_config(path=DEFAULT_CONFIG_PATH):
    """Return the parsed config file, or {} if it does not exist."""
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def resolve_connection(config, profile=None, env=None):
    """Resolve url/db/user/password.

    Profile selection precedence: explicit `profile` -> env ODOO_PROFILE ->
    config 'default_profile'. Per-field ODOO_* env vars override profile fields.
    With no config and no profile, returns defaults overridden by env.
    """
    env = os.environ if env is None else env
    name = profile or env.get("ODOO_PROFILE") or config.get("default_profile")
    fields = dict(_CONN_DEFAULTS)
    profiles = config.get("profiles", {})
    if name:
        if name not in profiles:
            raise ConfigError(f"Profile '{name}' not found in config")
        fields.update({k: v for k, v in profiles[name].items() if k in fields})
    for key, env_key in _ENV_KEYS.items():
        if env.get(env_key):
            fields[key] = env[env_key]
    return fields
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k "resolve or load_config"`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add config loading and profile/env connection resolution"
```

---

## Task 5: Error classification & exit codes

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odoo.py`:

```python
def test_classify_connection_refused():
    err, code = odoo.classify_error(ConnectionRefusedError(), "http://x")
    assert code == odoo.EXIT_CONN
    assert "Cannot connect" in err["error"]


def test_classify_permission():
    err, code = odoo.classify_error(PermissionError("Auth failed"), "http://x")
    assert code == odoo.EXIT_ODOO
    assert err["error"] == "Auth failed"


def test_classify_access_error():
    err, code = odoo.classify_error(odoo.OdooServerError("AccessError: nope"), "http://x")
    assert code == odoo.EXIT_ODOO
    assert err["error"].startswith("Access denied")


def test_classify_missing_error():
    err, code = odoo.classify_error(odoo.OdooServerError("MissingError: gone"), "u")
    assert err["error"].startswith("Not found")


def test_classify_generic_odoo_error():
    err, code = odoo.classify_error(odoo.OdooServerError("boom"), "u")
    assert code == odoo.EXIT_ODOO
    assert err["error"].startswith("Odoo error")


def test_classify_oserror_is_connection():
    err, code = odoo.classify_error(OSError("refused"), "http://x")
    assert code == odoo.EXIT_CONN
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest pytest tests/test_odoo.py -k classify`
Expected: FAIL — `module 'odoo' has no attribute 'classify_error'`.

- [ ] **Step 3: Implement**

Append to `scripts/odoo.py`:

```python
EXIT_OK = 0
EXIT_ODOO = 1
EXIT_USAGE = 2
EXIT_CONN = 3


def classify_error(exc, url):
    """Map an exception to ({"error": msg}, exit_code).

    Order matters: ConnectionRefusedError is checked before its OSError base.
    """
    if isinstance(exc, ConnectionRefusedError):
        return {"error": f"Cannot connect to Odoo at {url}"}, EXIT_CONN
    if isinstance(exc, PermissionError):
        return {"error": str(exc)}, EXIT_ODOO
    if isinstance(exc, OdooServerError):
        msg = str(exc)
        if "AccessError" in msg or "AccessDenied" in msg:
            return {"error": f"Access denied: {msg}"}, EXIT_ODOO
        if "MissingError" in msg or "does not exist" in msg.lower():
            return {"error": f"Not found: {msg}"}, EXIT_ODOO
        return {"error": f"Odoo error: {msg}"}, EXIT_ODOO
    if isinstance(exc, OSError):
        return {"error": f"Cannot connect to Odoo at {url}: {exc}"}, EXIT_CONN
    return {"error": f"Error: {exc}"}, EXIT_ODOO
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k classify`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add error classification with exit codes"
```

---

## Task 6: Output emit (threshold spill + summary)

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odoo.py`:

```python
import io


def test_emit_small_inline():
    buf = io.StringIO()
    path = odoo.emit_result([{"id": 1}], model="res.partner", stdout=buf)
    assert path is None
    assert json.loads(buf.getvalue()) == [{"id": 1}]


def test_emit_force_out(tmp_path):
    buf = io.StringIO()
    out = tmp_path / "o.json"
    data = [{"id": 1, "name": "Acme"}]
    path = odoo.emit_result(data, model="m", out=str(out), stdout=buf)
    assert path == str(out)
    summary = json.loads(buf.getvalue())
    assert summary["saved_to"] == str(out)
    assert summary["count"] == 1
    assert summary["fields"] == ["id", "name"]
    assert summary["sample"] == data
    assert json.loads(out.read_text(encoding="utf-8")) == data


def test_emit_auto_spill_when_over_records(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    data = [{"id": i} for i in range(60)]
    buf = io.StringIO()
    path = odoo.emit_result(data, model="res.partner", stdout=buf)
    assert path is not None
    assert path.startswith(str(tmp_path))
    summary = json.loads(buf.getvalue())
    assert summary["count"] == 60
    assert len(summary["sample"]) == 2


def test_emit_auto_spill_when_over_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    data = [{"id": 1, "blob": "x" * 100}]
    buf = io.StringIO()
    path = odoo.emit_result(data, stdout=buf, max_inline_bytes=10)
    assert path is not None


def test_emit_inline_overrides_threshold():
    data = [{"id": i} for i in range(100)]
    buf = io.StringIO()
    path = odoo.emit_result(data, inline=True, stdout=buf)
    assert path is None
    assert json.loads(buf.getvalue()) == data


def test_emit_non_list_result():
    buf = io.StringIO()
    path = odoo.emit_result(42, stdout=buf)
    assert path is None
    assert buf.getvalue().strip() == "42"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest pytest tests/test_odoo.py -k emit`
Expected: FAIL — `module 'odoo' has no attribute 'emit_result'`.

- [ ] **Step 3: Implement**

Append to `scripts/odoo.py`:

```python
import sys

DEFAULT_MAX_INLINE_BYTES = 16384  # ~16 KB
DEFAULT_MAX_INLINE_RECORDS = 50
_spill_seq = 0


def _spill_dir():
    base = os.environ.get("TMPDIR", "/tmp")
    d = Path(base) / "odoo-cli"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _next_seq():
    global _spill_seq
    _spill_seq += 1
    return _spill_seq


def emit_result(
    result,
    *,
    model="result",
    out=None,
    inline=False,
    max_inline_bytes=DEFAULT_MAX_INLINE_BYTES,
    max_inline_records=DEFAULT_MAX_INLINE_RECORDS,
    stdout=None,
):
    """Print result JSON to stdout, or spill to a file + print a summary.

    Returns the path written to, or None when printed inline. `out` forces a
    write; `inline` forces stdout; otherwise spills when the payload exceeds
    `max_inline_bytes` or the record count exceeds `max_inline_records`.
    """
    stream = sys.stdout if stdout is None else stdout
    payload = json.dumps(result, ensure_ascii=False)
    nbytes = len(payload.encode("utf-8"))
    count = len(result) if isinstance(result, list) else 1
    big = nbytes > max_inline_bytes or count > max_inline_records

    write_to_file = out is not None or (big and not inline)
    if not write_to_file:
        stream.write(payload + "\n")
        return None

    if out is not None:
        path = Path(out)
        if path.parent != Path(""):
            path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = _spill_dir() / f"{model}-{_next_seq()}.json"
    path.write_text(payload, encoding="utf-8")

    summary = {"saved_to": str(path), "count": count, "bytes": nbytes}
    if isinstance(result, list):
        if result and isinstance(result[0], dict):
            summary["fields"] = list(result[0].keys())
        summary["sample"] = result[:2]
    else:
        summary["sample"] = result
    stream.write(json.dumps(summary, ensure_ascii=False) + "\n")
    return str(path)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k emit`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add output emit with auto-spill to file and summary"
```

---

## Task 7: Parser + `main` dispatch + `search-read`

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odoo.py`:

```python
class FakeClient:
    def __init__(self, **kw):
        self.kw = kw
        self.calls = []
        self.result = [{"id": 1, "name": "Acme"}]

    def execute_kw(self, model, method, args=None, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        return self.result


@pytest.fixture
def capture_client(monkeypatch):
    holder = {}

    def factory(**kw):
        c = FakeClient(**kw)
        holder["client"] = c
        return c

    holder["factory"] = factory
    return holder


def _no_config(tmp_path):
    return ["--config", str(tmp_path / "none.json")]


def test_main_search_read_maps(capsys, capture_client, tmp_path):
    rc = odoo.main(
        ["search-read", "res.partner",
         "--domain", '[["is_company","=",true]]',
         "--fields", '["name"]', "--limit", "5"] + _no_config(tmp_path),
        client_factory=capture_client["factory"],
    )
    assert rc == odoo.EXIT_OK
    model, method, args, kwargs = capture_client["client"].calls[0]
    assert model == "res.partner"
    assert method == "search_read"
    assert args == [[["is_company", "=", True]]]
    assert kwargs["fields"] == ["name"]
    assert kwargs["limit"] == 5
    assert kwargs["offset"] == 0


def test_main_search_read_default_domain(capsys, capture_client, tmp_path):
    odoo.main(["search-read", "res.partner"] + _no_config(tmp_path),
              client_factory=capture_client["factory"])
    _, _, args, _ = capture_client["client"].calls[0]
    assert args == [[]]


def test_main_search_read_lang_context(capsys, capture_client, tmp_path):
    odoo.main(["search-read", "product.template", "--lang", "zh_TW"] + _no_config(tmp_path),
              client_factory=capture_client["factory"])
    _, _, _, kwargs = capture_client["client"].calls[0]
    assert kwargs["context"] == {"lang": "zh_TW"}


def test_main_bad_profile_returns_usage(capsys, capture_client, tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"profiles": {}}), encoding="utf-8")
    rc = odoo.main(["search-read", "res.partner", "--profile", "nope",
                    "--config", str(cfg)],
                   client_factory=capture_client["factory"])
    assert rc == odoo.EXIT_USAGE
    assert "not found" in json.loads(capsys.readouterr().out)["error"]


def test_main_odoo_error_returns_code(capsys, tmp_path):
    def boom_factory(**kw):
        class C:
            def execute_kw(self, *a, **k):
                raise odoo.OdooServerError("AccessError: denied")
        return C()

    rc = odoo.main(["search-read", "res.partner"] + _no_config(tmp_path),
                   client_factory=boom_factory)
    assert rc == odoo.EXIT_ODOO
    assert json.loads(capsys.readouterr().out)["error"].startswith("Access denied")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest pytest tests/test_odoo.py -k main`
Expected: FAIL — `module 'odoo' has no attribute 'main'`.

- [ ] **Step 3: Implement parser, context helper, search-read handler, and main**

Append to `scripts/odoo.py`:

```python
import argparse


def _context_kwargs(args):
    """Return {'context': {'lang': ...}} if --lang was given, else {}."""
    lang = getattr(args, "lang", None)
    if lang:
        return {"context": {"lang": lang}}
    return {}


def cmd_search_read(client, args):
    kwargs = {"limit": args.limit, "offset": args.offset}
    fields = coerce_json(args.fields)
    if fields is not None:
        kwargs["fields"] = fields
    if args.order:
        kwargs["order"] = args.order
    kwargs.update(_context_kwargs(args))
    domain = coerce_json(args.domain) or []
    return client.execute_kw(args.model, "search_read", [domain], kwargs)


def build_parser():
    parser = argparse.ArgumentParser(prog="odoo", description="Odoo ERP CLI over JSON-RPC")
    sub = parser.add_subparsers(dest="command", required=True)

    conn = argparse.ArgumentParser(add_help=False)
    conn.add_argument("--profile")
    conn.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))

    out = argparse.ArgumentParser(add_help=False)
    out.add_argument("--out")
    out.add_argument("--inline", action="store_true")
    out.add_argument("--lang")
    out.add_argument(
        "--max-inline-bytes", type=int, dest="max_inline_bytes",
        default=DEFAULT_MAX_INLINE_BYTES,
    )

    sr = sub.add_parser("search-read", parents=[conn, out])
    sr.add_argument("model")
    sr.add_argument("--domain")
    sr.add_argument("--fields")
    sr.add_argument("--limit", type=int, default=80)
    sr.add_argument("--offset", type=int, default=0)
    sr.add_argument("--order")
    sr.set_defaults(func=cmd_search_read)

    return parser


def main(argv=None, *, client_factory=OdooClient):
    args = build_parser().parse_args(argv)
    config = load_config(getattr(args, "config", None) or DEFAULT_CONFIG_PATH)
    try:
        conn = resolve_connection(config, profile=getattr(args, "profile", None))
    except ConfigError as e:
        sys.stdout.write(json.dumps({"error": str(e)}) + "\n")
        return EXIT_USAGE
    client = client_factory(
        url=conn["url"], db=conn["db"], username=conn["user"], password=conn["password"]
    )
    try:
        result = args.func(client, args)
    except Exception as e:  # noqa: BLE001 - classified below
        err, code = classify_error(e, conn["url"])
        sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
        return code
    if result is None:
        result = True
    emit_result(
        result,
        model=str(getattr(args, "model", args.command)),
        out=getattr(args, "out", None),
        inline=getattr(args, "inline", False),
        max_inline_bytes=getattr(args, "max_inline_bytes", DEFAULT_MAX_INLINE_BYTES),
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k main`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add argparse dispatch, main loop, and search-read command"
```

---

## Task 8: `read`, `create`, `write`, `unlink`

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odoo.py`:

```python
def test_main_read_maps(capsys, capture_client, tmp_path):
    odoo.main(["read", "res.partner", "--ids", "[1,2]", "--fields", '["name"]']
              + _no_config(tmp_path), client_factory=capture_client["factory"])
    model, method, args, kwargs = capture_client["client"].calls[0]
    assert method == "read"
    assert args == [[1, 2]]
    assert kwargs["fields"] == ["name"]


def test_main_create_maps(capsys, capture_client, tmp_path):
    odoo.main(["create", "res.partner", "--values", '{"name":"Bob"}']
              + _no_config(tmp_path), client_factory=capture_client["factory"])
    model, method, args, kwargs = capture_client["client"].calls[0]
    assert method == "create"
    assert args == [{"name": "Bob"}]


def test_main_write_maps_with_lang(capsys, capture_client, tmp_path):
    odoo.main(["write", "product.template", "--ids", "[10209]",
               "--values", '{"name":"中文名"}', "--lang", "zh_TW"]
              + _no_config(tmp_path), client_factory=capture_client["factory"])
    model, method, args, kwargs = capture_client["client"].calls[0]
    assert method == "write"
    assert args == [[10209], {"name": "中文名"}]
    assert kwargs["context"] == {"lang": "zh_TW"}


def test_main_unlink_maps(capsys, capture_client, tmp_path):
    odoo.main(["unlink", "res.partner", "--ids", "[5]"]
              + _no_config(tmp_path), client_factory=capture_client["factory"])
    model, method, args, kwargs = capture_client["client"].calls[0]
    assert method == "unlink"
    assert args == [[5]]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest pytest tests/test_odoo.py -k "read or create or write or unlink"`
Expected: FAIL — `argument command: invalid choice: 'read'`.

- [ ] **Step 3: Implement the handlers and register subparsers**

Append the handlers to `scripts/odoo.py` (after `cmd_search_read`):

```python
def cmd_read(client, args):
    kwargs = dict(_context_kwargs(args))
    fields = coerce_json(args.fields)
    if fields is not None:
        kwargs["fields"] = fields
    return client.execute_kw(args.model, "read", [coerce_json(args.ids)], kwargs)


def cmd_create(client, args):
    return client.execute_kw(
        args.model, "create", [coerce_json(args.values)], _context_kwargs(args)
    )


def cmd_write(client, args):
    return client.execute_kw(
        args.model,
        "write",
        [coerce_json(args.ids), coerce_json(args.values)],
        _context_kwargs(args),
    )


def cmd_unlink(client, args):
    return client.execute_kw(args.model, "unlink", [coerce_json(args.ids)])
```

In `build_parser()`, add these subparsers immediately before `return parser`:

```python
    rd = sub.add_parser("read", parents=[conn, out])
    rd.add_argument("model")
    rd.add_argument("--ids", required=True)
    rd.add_argument("--fields")
    rd.set_defaults(func=cmd_read)

    cr = sub.add_parser("create", parents=[conn, out])
    cr.add_argument("model")
    cr.add_argument("--values", required=True)
    cr.set_defaults(func=cmd_create)

    wr = sub.add_parser("write", parents=[conn, out])
    wr.add_argument("model")
    wr.add_argument("--ids", required=True)
    wr.add_argument("--values", required=True)
    wr.set_defaults(func=cmd_write)

    ul = sub.add_parser("unlink", parents=[conn, out])
    ul.add_argument("model")
    ul.add_argument("--ids", required=True)
    ul.set_defaults(func=cmd_unlink)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k "read or create or write or unlink"`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add read, create, write, unlink commands"
```

---

## Task 9: `list-models`, `list-fields`, `execute-method`

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odoo.py`:

```python
def test_main_list_models_no_search(capsys, capture_client, tmp_path):
    odoo.main(["list-models"] + _no_config(tmp_path),
              client_factory=capture_client["factory"])
    model, method, args, kwargs = capture_client["client"].calls[0]
    assert model == "ir.model"
    assert method == "search_read"
    assert args == [[]]
    assert kwargs["fields"] == ["name", "model"]


def test_main_list_models_search(capsys, capture_client, tmp_path):
    odoo.main(["list-models", "--search", "partner"] + _no_config(tmp_path),
              client_factory=capture_client["factory"])
    _, _, args, _ = capture_client["client"].calls[0]
    assert args == [["|", ["model", "ilike", "partner"], ["name", "ilike", "partner"]]]


def test_main_list_fields(capsys, capture_client, tmp_path):
    odoo.main(["list-fields", "res.partner", "--attributes", '["type","string"]']
              + _no_config(tmp_path), client_factory=capture_client["factory"])
    model, method, args, kwargs = capture_client["client"].calls[0]
    assert model == "res.partner"
    assert method == "fields_get"
    assert args == []
    assert kwargs["attributes"] == ["type", "string"]


def test_main_execute_method(capsys, capture_client, tmp_path):
    odoo.main(["execute-method", "sale.order", "action_confirm", "--args", "[[5]]"]
              + _no_config(tmp_path), client_factory=capture_client["factory"])
    model, method, args, kwargs = capture_client["client"].calls[0]
    assert model == "sale.order"
    assert method == "action_confirm"
    assert args == [[5]]


def test_main_execute_method_kwargs(capsys, capture_client, tmp_path):
    odoo.main(["execute-method", "res.partner", "copy", "--args", "[[10]]",
               "--kwargs", '{"default":{"name":"X"}}'] + _no_config(tmp_path),
              client_factory=capture_client["factory"])
    _, _, args, kwargs = capture_client["client"].calls[0]
    assert args == [[10]]
    assert kwargs["default"] == {"name": "X"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest pytest tests/test_odoo.py -k "list_models or list_fields or execute_method"`
Expected: FAIL — `argument command: invalid choice: 'list-models'`.

- [ ] **Step 3: Implement the handlers and register subparsers**

Append the handlers to `scripts/odoo.py`:

```python
def cmd_list_models(client, args):
    domain = []
    if args.search:
        domain = ["|", ["model", "ilike", args.search], ["name", "ilike", args.search]]
    return client.execute_kw(
        "ir.model", "search_read", [domain],
        {"fields": ["name", "model"], "order": "model asc"},
    )


def cmd_list_fields(client, args):
    kwargs = {}
    attributes = coerce_json(args.attributes)
    if attributes is not None:
        kwargs["attributes"] = attributes
    return client.execute_kw(args.model, "fields_get", [], kwargs)


def cmd_execute_method(client, args):
    kwargs = coerce_json(args.kwargs) or {}
    kwargs.update(_context_kwargs(args))
    return client.execute_kw(
        args.model, args.method, coerce_json(args.args), kwargs or None
    )
```

In `build_parser()`, add before `return parser`:

```python
    lm = sub.add_parser("list-models", parents=[conn, out])
    lm.add_argument("--search")
    lm.set_defaults(func=cmd_list_models)

    lf = sub.add_parser("list-fields", parents=[conn, out])
    lf.add_argument("model")
    lf.add_argument("--attributes")
    lf.set_defaults(func=cmd_list_fields)

    em = sub.add_parser("execute-method", parents=[conn, out])
    em.add_argument("model")
    em.add_argument("method")
    em.add_argument("--args")
    em.add_argument("--kwargs")
    em.set_defaults(func=cmd_execute_method)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k "list_models or list_fields or execute_method"`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add list-models, list-fields, execute-method commands"
```

---

## Task 10: `config` subcommand (`list` / `use`)

**Files:**
- Modify: `scripts/odoo.py`
- Test: `tests/test_odoo.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_odoo.py`:

```python
def test_config_list_masks_password(capsys, tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
    rc = odoo.main(["config", "list", "--config", str(cfg)])
    assert rc == odoo.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["default_profile"] == "dev"
    assert out["profiles"]["dev"]["password"] == "***"
    assert out["profiles"]["dev"]["url"] == "http://dev"


def test_config_use_sets_default(capsys, tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
    rc = odoo.main(["config", "use", "prod", "--config", str(cfg)])
    assert rc == odoo.EXIT_OK
    assert json.loads(cfg.read_text(encoding="utf-8"))["default_profile"] == "prod"


def test_config_use_unknown_profile(capsys, tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps(CONFIG), encoding="utf-8")
    rc = odoo.main(["config", "use", "ghost", "--config", str(cfg)])
    assert rc == odoo.EXIT_USAGE
    assert "not found" in json.loads(capsys.readouterr().out)["error"]
```

Note: the `config` command is dispatched **before** connection resolution, so add an early branch in `main`. Update the existing `main` (see Step 3).

- [ ] **Step 2: Run to verify failure**

Run: `uv run --with pytest pytest tests/test_odoo.py -k config_`
Expected: FAIL — `argument command: invalid choice: 'config'`.

- [ ] **Step 3: Implement the handler, register subparser, and short-circuit in main**

Append the handler to `scripts/odoo.py`:

```python
def cmd_config(args):
    """Handle `config list` / `config use <name>`. Returns an exit code."""
    path = Path(args.config)
    config = load_config(path)
    if args.action == "list":
        masked = {}
        for name, prof in config.get("profiles", {}).items():
            masked[name] = {k: v for k, v in prof.items() if k != "password"}
            masked[name]["password"] = "***" if prof.get("password") else None
        sys.stdout.write(
            json.dumps(
                {"default_profile": config.get("default_profile"), "profiles": masked},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        return EXIT_OK
    # action == "use"
    if args.name not in config.get("profiles", {}):
        sys.stdout.write(json.dumps({"error": f"Profile '{args.name}' not found"}) + "\n")
        return EXIT_USAGE
    config["default_profile"] = args.name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.stdout.write(json.dumps({"default_profile": args.name}) + "\n")
    return EXIT_OK
```

In `build_parser()`, add before `return parser`:

```python
    cfg = sub.add_parser("config")
    cfg.add_argument("action", choices=["list", "use"])
    cfg.add_argument("name", nargs="?")
    cfg.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    cfg.set_defaults(func=None)
```

In `main`, add this short-circuit immediately after `args = build_parser().parse_args(argv)`:

```python
    if args.command == "config":
        return cmd_config(args)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run --with pytest pytest tests/test_odoo.py -k config_`
Expected: 3 passed.

- [ ] **Step 5: Run the whole suite**

Run: `uv run --with pytest pytest`
Expected: all tests pass (≈ 40).

- [ ] **Step 6: Commit**

```bash
git add scripts/odoo.py tests/test_odoo.py
git commit -m "feat: add config list/use subcommand"
```

---

## Task 11: Skill (`skills/odoo/SKILL.md`)

**Files:**
- Create: `skills/odoo/SKILL.md`

- [ ] **Step 1: Write the skill**

`skills/odoo/SKILL.md`:

````markdown
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
````

- [ ] **Step 2: Verify it loads as a plugin**

Run (from a separate shell, manual check):
```bash
claude --plugin-dir /Users/truney/projects/odoo-cli
```
Then in that session type `/` and confirm `odoo` skill appears, and ask Claude to run
`list-models --search partner`. Expected: it invokes the CLI and returns models.

- [ ] **Step 3: Commit**

```bash
git add skills/odoo/SKILL.md
git commit -m "feat: add odoo skill describing the CLI"
```

---

## Task 12: Slash command (`commands/odoo.md`)

**Files:**
- Create: `commands/odoo.md`

- [ ] **Step 1: Write the command**

`commands/odoo.md`:

````markdown
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
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/odoo.py" $ARGUMENTS
   ```

2. **Natural language** — otherwise, treat `$ARGUMENTS` as a request (e.g.
   "翻譯 product 10209 名稱成中文") and fulfill it using the `odoo` skill: pick the
   right subcommand(s) and run the CLI the same way.

If `$ARGUMENTS` is empty, briefly list the available subcommands from the skill.
````

- [ ] **Step 2: Verify it loads**

In a `claude --plugin-dir /Users/truney/projects/odoo-cli` session, run
`/odoo:odoo list-models --search sale`. Expected: passthrough runs the CLI and returns models.

- [ ] **Step 3: Commit**

```bash
git add commands/odoo.md
git commit -m "feat: add /odoo:odoo slash command"
```

---

## Task 13: Marketplace, README, and end-to-end verification

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Create: `README.md`

- [ ] **Step 1: Create the local marketplace descriptor**

`.claude-plugin/marketplace.json`:

```json
{
  "name": "odoo-local",
  "owner": { "name": "truney" },
  "plugins": [
    {
      "name": "odoo",
      "source": "./",
      "description": "Odoo ERP CLI plugin (CRUD, search, schema, workflow actions)."
    }
  ]
}
```

- [ ] **Step 2: Verify the marketplace registers**

Run:
```bash
claude plugin marketplace add /Users/truney/projects/odoo-cli
```
Expected: the `odoo-local` marketplace registers and lists the `odoo` plugin. If the
command reports a schema error, adjust the field names per the error message and re-run.
(The `claude --plugin-dir` path from Tasks 11–12 already proves the plugin loads; this step
only adds the persistent-install option.)

- [ ] **Step 3: Write the README**

`README.md`:

````markdown
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

Quick (dev): `claude --plugin-dir /Users/truney/projects/odoo-cli`
Persistent: `claude plugin marketplace add /Users/truney/projects/odoo-cli`, then install
the `odoo` plugin from the `odoo-local` marketplace. Invoke via the `odoo` skill or
`/odoo:odoo <args>`.

## Test

```bash
uv run --with pytest pytest
```

## Output behavior

Small results print JSON to stdout; large results (> ~16 KB or > 50 records) write to
`$TMPDIR/odoo-cli/` with a stdout summary. Use `--out PATH` or `--inline` to override.
````

- [ ] **Step 4: Full regression — tests + a real query**

Run:
```bash
uv run --with pytest pytest
```
Expected: all pass.

Then a live smoke test against the prod profile (requires a configured
`~/.config/odoo-cli/config.json`):
```bash
python3 scripts/odoo.py search-read res.partner --fields '["name"]' --limit 3 --profile prod
```
Expected: a small JSON array of 3 partners (or a clear `{"error": ...}` with non-zero exit
if credentials are wrong). If it errors on connection, confirm the profile URL/db/credentials.

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/marketplace.json README.md
git commit -m "docs: add marketplace descriptor and README"
```

---

## Task 14: Cut over from the MCP

**Files:** none in this repo (config change elsewhere).

- [ ] **Step 1: Confirm the plugin fully covers prior MCP usage**

Manually exercise each operation once via the CLI (search-read, read, create on a throwaway
record, write, unlink that record, list-models, list-fields, execute-method) against a safe
profile. Expected: each returns sensible JSON / ids and clean exit codes.

- [ ] **Step 2: Remove the live MCP registration**

Only after Step 1 passes, remove the `odoo-prd-truney` MCP server registration from the
user's MCP config (e.g. `claude mcp remove odoo-prd-truney`, or delete its entry from the
relevant `.mcp.json` / settings). The plugin now replaces it. Leave the old `odoo-mcp` repo
archived as-is.

- [ ] **Step 3: Commit any tracked config change (if applicable)**

If the MCP registration lived in a tracked file in this repo, commit its removal. Otherwise
no commit is needed.

---

## Notes for the implementer

- Run a focused subset with `-k`, e.g. `uv run --with pytest pytest -k emit`.
- `scripts/odoo.py` is appended to across tasks; keep the section order
  (client → coerce → config → errors → emit → handlers → parser → main) readable, but
  exact ordering is not asserted by tests.
- Never weaken a test to make it pass. If a test reveals a design gap, fix the code.
