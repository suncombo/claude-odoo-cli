#!/usr/bin/env python3
"""registry — who owns and who extends what, read from a live Odoo database.

Answers provenance questions the source tree cannot: which modules are actually
installed, which of them extended a given model, and which module a view or ACL
came from. Every answer is read from Odoo's own registry (`ir.model.data`,
`ir.module.module`, ...), so it describes the running system rather than the
checkout on disk — the two drift, and only the registry knows what is live.

Read-only by construction: no code path here calls a write method, so it is safe
against production regardless of how the profile is configured.
"""

import argparse
import json
import sys
from pathlib import Path

# The `odoo` CLI ships as a sibling skill inside the same plugin, so its path is
# fixed relative to this file. Importing it — rather than re-implementing the
# transport — keeps a single connection and credential path to any instance.
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "odoo" / "scripts")
)

try:
    from odoo import (  # noqa: E402
        DEFAULT_CONFIG_PATH,
        DEFAULT_MAX_INLINE_BYTES,
        EXIT_OK,
        EXIT_USAGE,
        ConfigError,
        OdooClient,
        classify_error,
        emit_result,
        load_config,
        resolve_connection,
    )
except ModuleNotFoundError:  # pragma: no cover - install-layout problem
    # The two skills ship together and this one is the odoo skill's client with a
    # different set of questions on top. Installed alone, it has no transport —
    # say so, rather than surfacing a bare import error.
    sys.exit(
        "registry: the 'odoo' skill is missing. It ships alongside this one and "
        "provides the connection layer; expected it at "
        f"{Path(__file__).resolve().parent.parent.parent / 'odoo' / 'scripts' / 'odoo.py'}"
    )


class UsageError(Exception):
    """Input the caller has to fix — reported instead of an answer.

    Every question here has a plausible-looking empty answer, so a typo that is
    allowed through does not fail: it returns a confident, wrong report.
    """


class NotFound(UsageError):
    """A named module or model is absent from this database's registry.

    Distinct from an empty result: 'this module has no dependencies' and 'this
    module does not exist' are different answers, and conflating them turns a
    typo into a confident, wrong report.
    """


def group_counts(rows, field):
    """Collapse `read_group` rows into {value: count}."""
    return {row[field]: row[f"{field}_count"] for row in rows}


def attribution(rows, total):
    """Turn `ir.model.data` read_group rows into an ownership breakdown.

    `total` is how many records of the kind actually exist. Anything the grouping
    does not account for has no `ir.model.data` row — a field or view created
    through the UI rather than by a module — and is reported as `unattributed`
    rather than dropped, so `by_module` is never mistaken for a full census.
    """
    by_module = group_counts(rows, "module")
    ordered = dict(sorted(by_module.items(), key=lambda kv: (-kv[1], kv[0])))
    result = {"total": total, "by_module": ordered}
    unattributed = total - sum(by_module.values())
    if unattributed:
        result["unattributed"] = unattributed
    return result


def scan_addons(roots):
    """Module names found on disk under these roots — a directory holding a
    `__manifest__.py`.

    Searched at any depth: OCA checkouts nest each module a repository deep, so
    a fixed depth would silently miss most of the tree. Hidden directories are
    skipped, because git worktrees are commonly parked inside the addons tree
    (`.claude/worktrees/<name>/`) and their copies are branch work, not code the
    database could be running.
    """
    return {
        manifest.parent.name
        for root in roots
        for manifest in Path(root).rglob("__manifest__.py")
        if not any(part.startswith(".") for part in manifest.parts)
    }


def _state_counts(client):
    rows = client.execute_kw(
        "ir.module.module", "read_group", [[], ["state"], ["state"]]
    )
    by_state = group_counts(rows, "state")
    return {"by_state": by_state, "total": sum(by_state.values())}


def _names_in_state(client, state):
    rows = client.execute_kw(
        "ir.module.module",
        "search_read",
        [[["state", "=", state]]],
        {"fields": ["name"], "order": "name asc"},
    )
    names = [row["name"] for row in rows]
    return {"state": state, "count": len(names), "modules": names}


def _disk_drift(client, roots):
    rows = client.execute_kw(
        "ir.module.module",
        "search_read",
        [[]],
        {"fields": ["name", "state"], "order": "name asc"},
    )
    known = {row["name"]: row["state"] for row in rows}
    on_disk = scan_addons(roots)
    registry_only = sorted(set(known) - on_disk)
    by_state = {}
    for state in known.values():
        by_state[state] = by_state.get(state, 0) + 1
    return {
        "by_state": by_state,
        "total": len(known),
        "addons_path": roots,
        "on_disk": len(on_disk),
        # Known to Odoo but absent from this tree: removed modules whose rows
        # outlived them, or a tree that is not the one this database runs.
        "registry_only": registry_only,
        # Present but never scanned — no Update Apps List since they landed.
        "disk_only": sorted(on_disk - set(known)),
        # The subset that matters: running code that is not in this tree.
        "installed_without_code": [
            name for name in registry_only if known[name] == "installed"
        ],
    }


def cmd_modules(client, args):
    if args.state and args.addons_path:
        raise UsageError(
            "--state and --addons-path answer different questions; pass one. "
            "--state lists names in a state, --addons-path diffs against disk"
        )
    if args.state:
        return _names_in_state(client, args.state)
    if args.addons_path:
        roots = [p for p in args.addons_path.split(",") if p]
        missing = [p for p in roots if not Path(p).is_dir()]
        if missing:
            # rglob on a missing root yields nothing, which would read as "no
            # modules on disk" and flag every installed module as code-less.
            raise UsageError("addons path does not exist: " + ", ".join(missing))
        return _disk_drift(client, roots)
    return _state_counts(client)


# The four kinds of record a module can contribute to a model, and how to find
# them. `ir.ui.view` keys off the model's technical name; the rest off its id.
DIMENSIONS = (
    ("fields", "ir.model.fields", "model_id"),
    ("views", "ir.ui.view", "model"),
    ("acl", "ir.model.access", "model_id"),
    ("rules", "ir.rule", "model_id"),
)

# Odoo's `search` drops archived rows unless `active_test` is off, so on these
# models a plain count is a count of the *live* records. That is the right answer
# for a tool describing the running system — but only if it says so, otherwise
# `total` reads as the whole story and quietly disagrees with the table.
ARCHIVABLE = frozenset({"ir.ui.view", "ir.rule"})


def archived_count(client, target_model, link_field, value):
    return client.execute_kw(
        target_model,
        "search_count",
        [[[link_field, "=", value], ["active", "=", False]]],
        {"context": {"active_test": False}},
    )


def owners(client, target_model, record_ids):
    """Group `ir.model.data` rows for these records by owning module."""
    if not record_ids:
        return []
    return client.execute_kw(
        "ir.model.data",
        "read_group",
        [
            [["model", "=", target_model], ["res_id", "in", record_ids]],
            ["module"],
            ["module"],
        ],
    )


def owned_by(client, target_model, names, module):
    """Names of this model's records that `module` owns, via `ir.model.data`."""
    if not names:
        return []
    rows = client.execute_kw(
        "ir.model.data",
        "search_read",
        [
            [
                ["model", "=", target_model],
                ["res_id", "in", list(names)],
                ["module", "=", module],
            ]
        ],
        {"fields": ["res_id"]},
    )
    # `name` is nullable on some of these models, and a False mixed in with
    # strings makes sorted() raise rather than return a partial answer.
    return sorted(
        names[row["res_id"]] or f'<unnamed id={row["res_id"]}>'
        for row in rows
        if row["res_id"] in names
    )


def cmd_model(client, args):
    found = client.execute_kw(
        "ir.model", "search_read", [[["model", "=", args.model]]], {"fields": ["model"]}
    )
    if not found:
        raise NotFound(f"model '{args.model}' is not in this database's registry")
    model_id = found[0]["id"]

    result = {"model": args.model}
    if args.module:
        # Without this, a typo returns an empty list per dimension — which reads
        # as "that module contributes nothing to this model", not "no such module".
        if not client.execute_kw(
            "ir.module.module", "search_count", [[["name", "=", args.module]]]
        ):
            raise NotFound(
                f"module '{args.module}' is not in this database's registry"
            )
        result["module"] = args.module
    for key, target_model, link_field in DIMENSIONS:
        value = args.model if link_field == "model" else model_id
        # Counting needs only ids; naming a module's records needs the names. A
        # model like res.partner has ~200 fields, so the aggregate path does not
        # pay to fetch names it will discard.
        records = client.execute_kw(
            target_model,
            "search_read",
            [[[link_field, "=", value]]],
            {"fields": ["name"] if args.module else ["id"]},
        )
        if args.module:
            names = {row["id"]: row["name"] for row in records}
            result[key] = owned_by(client, target_model, names, args.module)
            continue
        ids = [row["id"] for row in records]
        entry = attribution(owners(client, target_model, ids), len(ids))
        if target_model in ARCHIVABLE:
            archived = archived_count(client, target_model, link_field, value)
            if archived:
                entry["archived"] = archived
        result[key] = entry
    return result


def cmd_module(client, args):
    rows = client.execute_kw(
        "ir.module.module",
        "search_read",
        [[["name", "=", args.name]]],
        {"fields": ["name", "state"]},
    )
    if not rows:
        raise NotFound(
            f"module '{args.name}' is not in this database's registry — it may be "
            "on disk but never scanned (Update Apps List), or misspelled"
        )
    module = rows[0]
    depends = client.execute_kw(
        "ir.module.module.dependency",
        "search_read",
        [[["module_id", "=", module["id"]]]],
        {"fields": ["name"], "order": "name asc"},
    )
    # The same table read from the other end: rows naming this module belong to
    # the modules that depend on it.
    required_by = client.execute_kw(
        "ir.module.module.dependency",
        "search_read",
        [[["name", "=", args.name]]],
        {"fields": ["module_id"]},
    )
    return {
        "module": module["name"],
        "state": module["state"],
        "depends": [row["name"] for row in depends],
        "required_by": sorted(row["module_id"][1] for row in required_by),
    }


def build_parser():
    parser = argparse.ArgumentParser(
        prog="registry", description="Odoo module attribution from the live registry"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    conn = argparse.ArgumentParser(add_help=False)
    conn.add_argument("--profile")
    conn.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))

    out = argparse.ArgumentParser(add_help=False)
    out.add_argument("--out")
    out.add_argument("--inline", action="store_true")
    out.add_argument(
        "--max-inline-bytes",
        type=int,
        dest="max_inline_bytes",
        default=DEFAULT_MAX_INLINE_BYTES,
    )

    mods = sub.add_parser("modules", parents=[conn, out])
    mods.add_argument(
        "--state",
        choices=["installed", "uninstalled", "uninstallable", "to upgrade"],
        help="list the names in this state instead of the per-state counts",
    )
    mods.add_argument(
        "--addons-path",
        dest="addons_path",
        help="comma-separated roots to diff the registry against; compare only "
             "against the tree this database actually runs, or the drift is bogus",
    )
    mods.set_defaults(func=cmd_modules)

    one = sub.add_parser("module", parents=[conn, out])
    one.add_argument("name")
    one.set_defaults(func=cmd_module)

    mdl = sub.add_parser("model", parents=[conn, out])
    mdl.add_argument("model")
    mdl.add_argument(
        "--module",
        help="list the records this module owns instead of the per-module counts",
    )
    mdl.set_defaults(func=cmd_model)

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
    except UsageError as e:
        sys.stdout.write(json.dumps({"error": str(e)}, ensure_ascii=False) + "\n")
        return EXIT_USAGE
    except Exception as e:  # noqa: BLE001 - classified below
        err, code = classify_error(e, conn["url"])
        sys.stdout.write(json.dumps(err, ensure_ascii=False) + "\n")
        return code
    emit_result(
        result,
        model=args.command,
        out=args.out,
        inline=args.inline,
        max_inline_bytes=args.max_inline_bytes,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
