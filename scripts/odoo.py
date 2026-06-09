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
