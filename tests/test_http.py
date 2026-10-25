import pytest
import requests

from sync import http


class FakeResp:
    def __init__(self, status=200, text="", payload=None, content=b""):
        self.status_code = status
        self.text = text
        self._payload = payload
        self.content = content or text.encode("utf-8")
        self.encoding = None

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture(autouse=True)
def fake_time(monkeypatch):
    state = {"now": 1000.0, "sleeps": []}

    def sleep(s):
        state["sleeps"].append(s)
        state["now"] += s

    monkeypatch.setattr(http.time, "sleep", sleep)
    monkeypatch.setattr(http.time, "monotonic", lambda: state["now"])
    monkeypatch.setattr(http, "_last_request", None)
    return state


def set_responses(monkeypatch, items):
    calls = []
    it = iter(items)

    def get(url, **kw):
        calls.append((url, kw))
        item = next(it)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(http._session, "get", get)
    return calls


def test_get_json_raises_on_html(monkeypatch):
    calls = set_responses(monkeypatch, [FakeResp(200, text="<html>slow down</html>")] * 3)
    with pytest.raises(http.SourceError):
        http.get_json("http://x/a")
    assert len(calls) == http.RETRIES


def test_get_json_retries_then_succeeds(monkeypatch, fake_time):
    calls = set_responses(monkeypatch, [FakeResp(503), FakeResp(503), FakeResp(200, payload={"a": 1})])
    assert http.get_json("http://x/a") == {"a": 1}
    assert len(calls) == 3
    assert fake_time["sleeps"] == [5, 15]
    assert calls[0][1]["timeout"] == 30
    assert calls[0][1]["headers"]["User-Agent"] == "Mozilla/5.0"


def test_retries_on_network_exception(monkeypatch):
    set_responses(monkeypatch, [requests.ConnectionError("x"), FakeResp(200, payload=[1])])
    assert http.get_json("http://x/a") == [1]


def test_requests_are_spaced(monkeypatch, fake_time):
    set_responses(monkeypatch, [FakeResp(200, payload={}), FakeResp(200, payload={})])
    http.get_json("http://x/1")
    fake_time["now"] += 1.0
    fake_time["sleeps"].clear()
    http.get_json("http://x/2")
    assert fake_time["sleeps"]
    assert fake_time["sleeps"][0] >= http.MIN_INTERVAL - 1.0 - 1e-9


def test_get_text_404_returns_none(monkeypatch):
    set_responses(monkeypatch, [FakeResp(404)])
    assert http.get_text("http://x/a", "cp950") is None


def test_get_text_decodes(monkeypatch):
    set_responses(monkeypatch, [FakeResp(200, content="營收".encode("cp950"))])
    assert http.get_text("http://x/a", "cp950") == "營收"


def test_error_message_truncates_body(monkeypatch):
    set_responses(monkeypatch, [FakeResp(200, text="<html>" + "x" * 5000)] * 3)
    with pytest.raises(http.SourceError) as e:
        http.get_json("http://x/a")
    assert len(str(e.value)) < 600
