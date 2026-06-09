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
