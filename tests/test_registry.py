import json

import pytest

import registry


class ScriptedClient:
    """Fake client returning canned results in call order, recording every call.

    Registry commands issue several ORM calls per invocation, so the fake is a
    queue rather than a single canned value.
    """

    def __init__(self, results, **conn):
        self.conn = conn
        self.calls = []
        self._results = list(results)

    def execute_kw(self, model, method, args=None, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        return self._results.pop(0) if self._results else []


@pytest.fixture
def scripted():
    """Yields {'make': fn(results) -> factory, 'client': the built fake}."""
    holder = {}

    def make(results):
        def factory(**conn):
            holder["client"] = ScriptedClient(results, **conn)
            return holder["client"]

        return factory

    holder["make"] = make
    return holder


def _no_config(tmp_path):
    return ["--config", str(tmp_path / "none.json")]


def _out(capsys):
    return json.loads(capsys.readouterr().out)


# --- read-only invariant ---------------------------------------------------


class PermissiveClient:
    """Answers plausibly whatever it is asked, so every path runs to the end."""

    def __init__(self, **conn):
        self.calls = []

    def execute_kw(self, model, method, args=None, kwargs=None):
        self.calls.append((model, method, args, kwargs))
        if method == "search_count":
            return 1
        if method == "search_read" and model == "ir.model":
            return [{"id": 1, "model": "sale.order"}]
        if method == "search_read" and model == "ir.module.module":
            return [{"id": 1, "name": "sale", "state": "installed"}]
        return []


READ_ONLY_METHODS = frozenset(
    {"search_read", "read", "read_group", "search_count", "fields_get", "name_search"}
)


def test_no_subcommand_can_issue_a_write_method(capsys, tmp_path):
    """Read-only is a property of this tool, not of the profile it points at.

    The docstring says so and no path calls a write today; this is what keeps
    that true when a subcommand is added.
    """
    for argv in (
        ["modules"],
        ["modules", "--state", "installed"],
        ["modules", "--addons-path", str(tmp_path)],
        ["module", "sale"],
        ["model", "sale.order"],
        ["model", "sale.order", "--module", "sale"],
    ):
        built = {}

        def factory(**conn):
            built["client"] = PermissiveClient(**conn)
            return built["client"]

        registry.main(
            argv + ["--inline"] + _no_config(tmp_path), client_factory=factory
        )
        capsys.readouterr()
        issued = {method for _, method, _, _ in built["client"].calls}
        assert issued, f"{argv} reached the database not at all"
        assert issued <= READ_ONLY_METHODS, f"{argv} issued {issued - READ_ONLY_METHODS}"


# --- modules ---------------------------------------------------------------


def test_modules_groups_by_state(capsys, scripted, tmp_path):
    factory = scripted["make"]([
        [
            {"state": "installed", "state_count": 303},
            {"state": "uninstalled", "state_count": 1009},
            {"state": "uninstallable", "state_count": 25},
        ],
    ])

    rc = registry.main(
        ["modules", "--inline"] + _no_config(tmp_path), client_factory=factory
    )

    assert rc == registry.EXIT_OK
    model, method, _, _ = scripted["client"].calls[0]
    assert (model, method) == ("ir.module.module", "read_group")
    out = _out(capsys)
    assert out["by_state"] == {
        "installed": 303,
        "uninstalled": 1009,
        "uninstallable": 25,
    }
    assert out["total"] == 1337


def test_modules_state_narrows_at_the_server(capsys, scripted, tmp_path):
    """--state lists names, and filters in the domain rather than client-side."""
    factory = scripted["make"]([
        [{"name": "sale"}, {"name": "truney_hedge_sale"}],
    ])

    rc = registry.main(
        ["modules", "--state", "installed", "--inline"] + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_OK
    model, method, args, kwargs = scripted["client"].calls[0]
    assert (model, method) == ("ir.module.module", "search_read")
    assert args == [[["state", "=", "installed"]]]
    assert kwargs["fields"] == ["name"]
    assert _out(capsys) == {
        "state": "installed",
        "count": 2,
        "modules": ["sale", "truney_hedge_sale"],
    }


def test_modules_addons_path_reports_drift_in_both_directions(
    capsys, scripted, tmp_path
):
    disk = tmp_path / "addons"
    for name in ("sale", "auth_jwt"):
        (disk / name).mkdir(parents=True)
        (disk / name / "__manifest__.py").write_text("{}")

    factory = scripted["make"]([
        [
            {"name": "sale", "state": "installed"},
            {"name": "truney_reservation", "state": "installed"},
            {"name": "document_page", "state": "uninstalled"},
        ],
    ])

    rc = registry.main(
        ["modules", "--addons-path", str(disk), "--inline"] + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_OK
    out = _out(capsys)
    assert out["by_state"] == {"installed": 2, "uninstalled": 1}
    assert out["on_disk"] == 2
    assert out["disk_only"] == ["auth_jwt"]
    assert out["registry_only"] == ["document_page", "truney_reservation"]
    # The subset worth alarming on: the registry says these are running, but no
    # code for them exists in the tree being compared.
    assert out["installed_without_code"] == ["truney_reservation"]


def test_modules_addons_path_that_does_not_exist_is_an_error(
    capsys, scripted, tmp_path
):
    """A typo'd root scans as 'no modules on disk', which would flag every
    installed module as running without code — a confident, wrong alarm."""
    factory = scripted["make"]([[]])

    rc = registry.main(
        ["modules", "--addons-path", str(tmp_path / "typo"), "--inline"]
        + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_USAGE
    assert "typo" in _out(capsys)["error"]
    # Nothing was asked of the database on the way to a bad-input failure.
    assert scripted["client"].calls == []


def test_modules_refuses_state_and_addons_path_together(capsys, scripted, tmp_path):
    """They answer different questions; silently honouring one is a wrong answer."""
    factory = scripted["make"]([[]])

    rc = registry.main(
        ["modules", "--state", "installed", "--addons-path", str(tmp_path), "--inline"]
        + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_USAGE
    error = _out(capsys)["error"]
    assert "--state" in error and "--addons-path" in error


# --- module ----------------------------------------------------------------


def test_module_reports_state_and_both_dependency_directions(
    capsys, scripted, tmp_path
):
    factory = scripted["make"]([
        [{"id": 42, "name": "truney_smart_price_lock", "state": "installed"}],
        [{"name": "sale"}, {"name": "website_sale"}],
        [{"module_id": [77, "truney_website_sale_price_lock"]}],
    ])

    rc = registry.main(
        ["module", "truney_smart_price_lock", "--inline"] + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_OK
    calls = scripted["client"].calls
    assert calls[0][0] == "ir.module.module"
    assert calls[0][2] == [[["name", "=", "truney_smart_price_lock"]]]
    # Depends and required-by are opposite ends of the same table.
    assert calls[1][0] == "ir.module.module.dependency"
    assert calls[1][2] == [[["module_id", "=", 42]]]
    assert calls[2][0] == "ir.module.module.dependency"
    assert calls[2][2] == [[["name", "=", "truney_smart_price_lock"]]]

    out = _out(capsys)
    assert out["module"] == "truney_smart_price_lock"
    assert out["state"] == "installed"
    assert out["depends"] == ["sale", "website_sale"]
    assert out["required_by"] == ["truney_website_sale_price_lock"]


def test_module_unknown_name_is_an_error_not_an_empty_shell(
    capsys, scripted, tmp_path
):
    """An empty result must not read as 'installed with no dependencies'."""
    factory = scripted["make"]([[]])

    rc = registry.main(
        ["module", "no_such_module", "--inline"] + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_USAGE
    assert "no_such_module" in _out(capsys)["error"]
    # Nothing further was queried once the module turned out not to exist.
    assert len(scripted["client"].calls) == 1


# --- attribution (pure) ----------------------------------------------------


def test_attribution_orders_by_count_then_name():
    rows = [
        {"module": "sale_stock", "module_count": 8},
        {"module": "sale", "module_count": 77},
        {"module": "delivery", "module_count": 8},
    ]

    result = registry.attribution(rows, total=93)

    assert list(result["by_module"].items()) == [
        ("sale", 77),
        ("delivery", 8),
        ("sale_stock", 8),
    ]
    assert result["total"] == 93
    assert "unattributed" not in result


def test_attribution_counts_records_with_no_owning_module():
    """Fields added through the UI carry no xml_id, so no module owns them.

    Dropping them would make by_module read as a complete census of a model.
    """
    rows = [{"module": "sale", "module_count": 77}]

    result = registry.attribution(rows, total=80)

    assert result["by_module"] == {"sale": 77}
    assert result["unattributed"] == 3


# --- addons scan (pure) ----------------------------------------------------


def test_scan_addons_finds_modules_at_any_depth(tmp_path):
    """OCA checkouts nest modules a repo deep, so a fixed depth would miss them."""
    for rel in ("truney/truney_hedge_sale", "OCA/manufacture/mrp_bom_location"):
        d = tmp_path / rel
        d.mkdir(parents=True)
        (d / "__manifest__.py").write_text("{}")
    (tmp_path / "not_a_module").mkdir()

    assert registry.scan_addons([str(tmp_path)]) == {
        "truney_hedge_sale",
        "mrp_bom_location",
    }


def test_scan_addons_ignores_hidden_directories(tmp_path):
    """Git worktrees live under .claude/worktrees/ inside the addons tree.

    Counting their copies would report a module that exists only in someone's
    half-finished branch as code that is on disk but not installed.
    """
    real = tmp_path / "truney" / "truney_hedge_sale"
    real.mkdir(parents=True)
    (real / "__manifest__.py").write_text("{}")

    wt = tmp_path / ".claude" / "worktrees" / "wip" / "truney" / "experiment"
    wt.mkdir(parents=True)
    (wt / "__manifest__.py").write_text("{}")

    assert registry.scan_addons([str(tmp_path)]) == {"truney_hedge_sale"}


# --- model -----------------------------------------------------------------


def test_model_attributes_every_dimension_and_skips_empty_ones(
    capsys, scripted, tmp_path
):
    factory = scripted["make"]([
        [{"id": 10, "model": "sale.order"}],            # ir.model lookup
        [{"id": 1}, {"id": 2}, {"id": 3}],              # fields
        [{"module": "sale", "module_count": 2}],        # field owners
        [{"id": 100}],                                  # views
        [{"module": "website_sale", "module_count": 1}],
        0,                                              # views archived
        [{"id": 200}],                                  # acl
        [{"module": "sale", "module_count": 1}],
        [],                                             # rules: none
        0,                                              # rules archived
    ])

    rc = registry.main(
        ["model", "sale.order", "--inline"] + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_OK
    calls = scripted["client"].calls
    assert calls[0][0] == "ir.model"
    assert calls[0][2] == [[["model", "=", "sale.order"]]]
    # Ownership is read from ir.model.data, narrowed to the records just found.
    assert calls[2][0] == "ir.model.data"
    assert calls[2][1] == "read_group"
    assert calls[2][2] == [
        [["model", "=", "ir.model.fields"], ["res_id", "in", [1, 2, 3]]],
        ["module"],
        ["module"],
    ]
    # A dimension with no records must not cost a grouping round trip.
    assert [(c[0], c[1]) for c in calls] == [
        ("ir.model", "search_read"),
        ("ir.model.fields", "search_read"),
        ("ir.model.data", "read_group"),
        ("ir.ui.view", "search_read"),
        ("ir.model.data", "read_group"),
        ("ir.ui.view", "search_count"),
        ("ir.model.access", "search_read"),
        ("ir.model.data", "read_group"),
        ("ir.rule", "search_read"),
        ("ir.rule", "search_count"),
    ]

    out = _out(capsys)
    assert out["model"] == "sale.order"
    assert out["fields"] == {
        "total": 3,
        "by_module": {"sale": 2},
        "unattributed": 1,
    }
    assert out["views"] == {"total": 1, "by_module": {"website_sale": 1}}
    assert out["acl"] == {"total": 1, "by_module": {"sale": 1}}
    assert out["rules"] == {"total": 0, "by_module": {}}


def test_model_reports_archived_records_it_would_otherwise_drop(
    capsys, scripted, tmp_path
):
    """Odoo's search hides archived rows, so `total` would silently undercount.

    An archived view is genuinely not loaded, so excluding it from by_module is
    right — but saying so is what keeps `total` from reading as the whole story.
    """
    factory = scripted["make"]([
        [{"id": 10, "model": "sale.order"}],
        [],                                             # fields
        [{"id": 100}],                                  # views: 1 active
        [{"module": "sale", "module_count": 1}],
        1,                                              # ...and 1 archived
        [],                                             # acl
        [],                                             # rules
        0,
    ])

    registry.main(
        ["model", "sale.order", "--inline"] + _no_config(tmp_path),
        client_factory=factory,
    )

    archived_call = scripted["client"].calls[4]
    assert archived_call[1] == "search_count"
    assert archived_call[2] == [
        [["model", "=", "sale.order"], ["active", "=", False]]
    ]
    assert archived_call[3]["context"] == {"active_test": False}

    out = _out(capsys)
    assert out["views"]["total"] == 1
    assert out["views"]["archived"] == 1
    # Dimensions with no archive concept say nothing about it.
    assert "archived" not in out["fields"]


def test_model_module_expands_to_the_records_that_module_owns(
    capsys, scripted, tmp_path
):
    factory = scripted["make"]([
        [{"id": 10, "model": "sale.order"}],
        1,                                                  # the module exists
        [{"id": 1, "name": "locked_price_unit"}, {"id": 2, "name": "amount_total"}],
        [{"res_id": 1}],                                    # only field 1 is theirs
        [{"id": 100, "name": "view_order_form_price_lock"}],
        [{"res_id": 100}],
        [],                                                 # acl
        [],                                                 # rules
    ])

    rc = registry.main(
        ["model", "sale.order", "--module", "truney_smart_price_lock", "--inline"]
        + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_OK
    calls = scripted["client"].calls
    # The module filter belongs in the ir.model.data domain, not in a client-side
    # pass over every record of the model.
    assert (calls[3][0], calls[3][1]) == ("ir.model.data", "search_read")
    assert calls[3][2] == [
        [
            ["model", "=", "ir.model.fields"],
            ["res_id", "in", [1, 2]],
            ["module", "=", "truney_smart_price_lock"],
        ]
    ]

    out = _out(capsys)
    assert out["module"] == "truney_smart_price_lock"
    assert out["fields"] == ["locked_price_unit"]
    assert out["views"] == ["view_order_form_price_lock"]
    assert out["acl"] == []
    assert out["rules"] == []


def test_model_unknown_module_is_an_error_not_four_empty_lists(
    capsys, scripted, tmp_path
):
    """Empty lists read as 'this module contributes nothing to the model', which
    is a different — and wrong — answer to 'that module does not exist'."""
    factory = scripted["make"]([
        [{"id": 10, "model": "sale.order"}],
        0,                                   # no such module in the registry
    ])

    rc = registry.main(
        ["model", "sale.order", "--module", "truney_smart_price_lok", "--inline"]
        + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_USAGE
    assert "truney_smart_price_lok" in _out(capsys)["error"]
    # It stopped before walking any dimension.
    assert len(scripted["client"].calls) == 2


def test_model_unknown_name_is_an_error(capsys, scripted, tmp_path):
    factory = scripted["make"]([[]])

    rc = registry.main(
        ["model", "sale.ordre", "--inline"] + _no_config(tmp_path),
        client_factory=factory,
    )

    assert rc == registry.EXIT_USAGE
    assert "sale.ordre" in _out(capsys)["error"]
    assert len(scripted["client"].calls) == 1
