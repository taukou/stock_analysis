import database

class FakeQuery:
    def __init__(self, data): self.data_all = data; self.rng = None
    def range(self, a, b): self.rng = (a, b); return self
    def execute(self):
        a, b = self.rng
        return type("R", (), {"data": self.data_all[a:b + 1]})()

def test_fetch_all_pages_until_short_page():
    rows = list(range(2500))
    calls = []
    def build():
        calls.append(1); return FakeQuery(rows)
    assert database.fetch_all(build, page=1000) == rows
    assert len(calls) == 3

def test_chunks():
    assert database.chunks(["a", "b", "c"], 2) == [["a", "b"], ["c"]]

def test_search_strips_specials_and_empty(monkeypatch):
    monkeypatch.setattr(database, "get_client", lambda: (_ for _ in ()).throw(AssertionError("不應查詢")))
    assert database.search_companies("  ,()*% ") == []
    assert database.search_companies(' "_" ') == []   # ILIKE 萬用字元 _ 與引號也移除


def test_first_node_is_deterministic():
    m = [{"node_id": "N301", "value_chain_nodes": {"major_id": "M01"}},
         {"node_id": "N102", "value_chain_nodes": [{"major_id": "M01"}]}]
    assert database._first_node(m) == ("N102", "M01")
    assert database._first_node(list(reversed(m))) == ("N102", "M01")
    assert database._first_node([]) == (None, None)


def test_get_client_is_per_thread(monkeypatch):
    import threading
    monkeypatch.setenv("SUPABASE_URL", "http://fake.invalid")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")
    monkeypatch.setattr(database, "_local", threading.local())
    monkeypatch.setattr(database, "create_client", lambda *a, **k: object())
    main_a, main_b = database.get_client(), database.get_client()
    other = []
    t = threading.Thread(target=lambda: other.append(database.get_client()))
    t.start(); t.join()
    assert main_a is main_b
    assert other[0] is not main_a


def test_get_client_missing_env_message(monkeypatch):
    import threading
    import pytest
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.setattr(database, "_local", threading.local())
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        database.get_client()


def test_run_query_retries_once_on_read_error():
    import httpx
    import pytest

    class Flaky:
        def __init__(self, fails): self.fails, self.calls = fails, 0
        def execute(self):
            self.calls += 1
            if self.calls <= self.fails:
                raise httpx.ReadError("boom")
            return "ok"

    q = Flaky(1)
    assert database.run_query(q) == "ok" and q.calls == 2
    q2 = Flaky(2)
    with pytest.raises(httpx.ReadError):
        database.run_query(q2)
    assert q2.calls == 2


def test_run_query_retries_other_transient_errors():
    import httpx

    class Once:
        def __init__(self, exc): self.exc, self.calls = exc, 0
        def execute(self):
            self.calls += 1
            if self.calls == 1:
                raise self.exc
            return "ok"

    for exc in (httpx.ConnectError("x"), httpx.ReadTimeout("x"), httpx.PoolTimeout("x")):
        q = Once(exc)
        assert database.run_query(q) == "ok" and q.calls == 2
