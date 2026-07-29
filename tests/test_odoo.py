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


def test_coerce_json_parses_list():
    assert odoo.coerce_json('[["is_company","=",true]]') == [["is_company", "=", True]]


def test_coerce_json_parses_dict():
    assert odoo.coerce_json('{"name": "X"}') == {"name": "X"}


def test_coerce_json_literal_fallback():
    assert odoo.coerce_json("name asc") == "name asc"


def test_coerce_json_none():
    assert odoo.coerce_json(None) is None


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


def _client_returning(capture_client, rows):
    def factory(**kw):
        c = FakeClient(**kw)
        c.result = rows
        capture_client["client"] = c
        return c
    return factory


def test_main_search_read_without_limit_asks_for_everything(capsys, capture_client, tmp_path):
    """Omitting --limit must not silently page at some UI-sized default."""
    odoo.main(["search-read", "res.partner"] + _no_config(tmp_path),
              client_factory=capture_client["factory"])
    _, _, _, kwargs = capture_client["client"].calls[0]
    assert kwargs["limit"] == odoo.SEARCH_READ_SAFETY_CAP


def test_main_search_read_errors_when_safety_cap_filled(capsys, capture_client, tmp_path):
    """A full cap means the answer is incomplete — fail loudly, never truncate silently."""
    rows = [{"id": i} for i in range(odoo.SEARCH_READ_SAFETY_CAP)]
    rc = odoo.main(["search-read", "res.partner"] + _no_config(tmp_path),
                   client_factory=_client_returning(capture_client, rows))
    assert rc == odoo.EXIT_USAGE
    assert "safety cap" in json.loads(capsys.readouterr().out)["error"]


def test_main_search_read_explicit_limit_may_truncate(capsys, capture_client, tmp_path):
    """An explicit --limit is a deliberate slice, so filling it is not an error."""
    rows = [{"id": i} for i in range(5)]
    rc = odoo.main(["search-read", "res.partner", "--limit", "5"] + _no_config(tmp_path),
                   client_factory=_client_returning(capture_client, rows))
    assert rc == odoo.EXIT_OK
    _, _, _, kwargs = capture_client["client"].calls[0]
    assert kwargs["limit"] == 5


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


RO_CONFIG = {
    "default_profile": "legacy",
    "profiles": {
        "legacy": {
            "url": "http://legacy", "db": "l", "user": "u", "password": "p",
            "readonly": True,
        },
        "live": {"url": "http://live", "db": "v", "user": "u", "password": "p"},
    },
}


def _ro_config(tmp_path):
    cfg = tmp_path / "ro.json"
    cfg.write_text(json.dumps(RO_CONFIG), encoding="utf-8")
    return ["--config", str(cfg)]


def test_readonly_defaults_off_and_comes_from_profile():
    assert odoo.resolve_connection(RO_CONFIG, profile="live", env={})["readonly"] is False
    assert odoo.resolve_connection(RO_CONFIG, profile="legacy", env={})["readonly"] is True


@pytest.mark.parametrize(
    "argv",
    [
        ["create", "res.partner", "--values", '{"name":"X"}'],
        ["write", "res.partner", "--ids", "[1]", "--values", '{"name":"X"}'],
        ["unlink", "res.partner", "--ids", "[1]"],
    ],
)
def test_readonly_refuses_mutating_commands(argv, capsys, capture_client, tmp_path):
    rc = odoo.main(argv + _ro_config(tmp_path), client_factory=capture_client["factory"])
    assert rc == odoo.EXIT_USAGE
    assert "read-only profile" in json.loads(capsys.readouterr().out)["error"]
    # Refused before any connection is attempted, so a read-only profile never
    # authenticates for a write it was going to reject anyway.
    assert "client" not in capture_client


def test_readonly_refuses_execute_method_outside_whitelist(
    capsys, capture_client, tmp_path
):
    rc = odoo.main(
        ["execute-method", "sale.order", "action_confirm", "--args", "[[1]]"]
        + _ro_config(tmp_path),
        client_factory=capture_client["factory"],
    )
    assert rc == odoo.EXIT_USAGE
    assert "action_confirm" in json.loads(capsys.readouterr().out)["error"]
    assert "client" not in capture_client


@pytest.mark.parametrize("method", sorted(odoo.READONLY_METHODS))
def test_readonly_allows_whitelisted_execute_method(
    method, capsys, capture_client, tmp_path
):
    rc = odoo.main(
        ["execute-method", "stock.move", method, "--args", "[[]]"]
        + _ro_config(tmp_path),
        client_factory=capture_client["factory"],
    )
    assert rc == odoo.EXIT_OK
    assert capture_client["client"].calls[0][1] == method


@pytest.mark.parametrize(
    "argv",
    [
        ["search-read", "res.partner", "--fields", '["name"]'],
        ["read", "res.partner", "--ids", "[1]"],
        ["list-models"],
        ["list-fields", "res.partner"],
    ],
)
def test_readonly_allows_read_commands(argv, capture_client, tmp_path):
    rc = odoo.main(argv + _ro_config(tmp_path), client_factory=capture_client["factory"])
    assert rc == odoo.EXIT_OK


def test_writable_profile_still_writes(capture_client, tmp_path):
    rc = odoo.main(
        ["write", "res.partner", "--ids", "[1]", "--values", '{"name":"X"}',
         "--profile", "live"] + _ro_config(tmp_path),
        client_factory=capture_client["factory"],
    )
    assert rc == odoo.EXIT_OK
    assert capture_client["client"].calls[0][1] == "write"
