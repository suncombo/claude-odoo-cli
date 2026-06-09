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
