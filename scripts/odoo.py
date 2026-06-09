#!/usr/bin/env python3
"""odoo — single-file CLI for Odoo ERP over JSON-RPC (pure stdlib)."""

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
