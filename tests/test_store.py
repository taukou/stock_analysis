from types import SimpleNamespace

import pytest

from sync.store import Store, make_store
from tests.fakes import FakeStore


class FakeQuery:
    def __init__(self, client, name):
        self.client, self.name = client, name
        self.calls = []

    def __getattr__(self, method):
        def chain(*a, **kw):
            self.calls.append((method, a, kw))
            return self
        return chain

    def execute(self):
        self.client.executed.append((self.name, self.calls))
        return SimpleNamespace(data=self.client.data)


class FakeClient:
    def __init__(self, data=None):
        self.data = data or []
        self.executed = []

    def table(self, name):
        return FakeQuery(self, name)

    def rpc(self, name):
        return FakeQuery(self, "rpc:" + name)


def test_upsert_batches_by_500():
    c = FakeClient()
    n = Store(c).upsert("t", [{"a": i} for i in range(1201)], "a")
    assert n == 1201
    assert len(c.executed) == 3
    sizes = [len(e[1][0][1][0]) for e in c.executed]
    assert sizes == [500, 500, 201]
    assert all(e[1][0][2] == {"on_conflict": "a"} for e in c.executed)


def test_upsert_empty_skips_api():
    c = FakeClient()
    assert Store(c).upsert("t", [], "a") == 0
    assert c.executed == []


def test_last_value_with_filters():
    c = FakeClient([{"d": "2026-01-02"}])
    assert Store(c).last_value("t", "d", {"market": "上市"}) == "2026-01-02"
    methods = [m for m, _, _ in c.executed[0][1]]
    assert methods == ["select", "eq", "order", "limit"]
    order = c.executed[0][1][2]
    assert order[2] == {"desc": True, "nullsfirst": False}


def test_last_value_none():
    assert Store(FakeClient([])).last_value("t", "d") is None


def test_rpc_and_runs_and_tracked():
    c = FakeClient([{"stock_id": "2330"}])
    s = Store(c)
    s.refresh_company_latest()
    s.fill_ex_date_changes()
    assert [e[0] for e in c.executed] == ["rpc:refresh_company_latest", "rpc:fill_ex_date_changes"]
    s.record_run(SimpleNamespace(dataset="x", status="ok", last_date="2026-01-01", rows=3, message=None))
    name, calls = c.executed[-1]
    assert name == "sync_runs" and calls[0][0] == "insert"
    assert calls[0][1][0] == {"dataset": "x", "status": "ok", "last_date": "2026-01-01", "rows": 3, "message": None}
    assert s.tracked_companies() == [{"stock_id": "2330"}]


def test_make_store_requires_service_key(monkeypatch):
    monkeypatch.setattr("sync.store.load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(RuntimeError, match="缺少 SUPABASE_SERVICE_KEY"):
        make_store()
    monkeypatch.delenv("SUPABASE_URL")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    with pytest.raises(RuntimeError, match="缺少 SUPABASE_URL"):
        make_store()


def test_fake_store_dedupes_and_filters():
    f = FakeStore()
    f.upsert("p", [{"id": "1", "d": "2026-01-01", "m": "上市"}], "id,d")
    f.upsert("p", [{"id": "1", "d": "2026-01-01", "m": "上市"},
                   {"id": "2", "d": "2026-02-01", "m": "上櫃"}], "id,d")
    assert len(f.tables["p"]) == 2
    assert f.upserts == [("p", 1), ("p", 2)]
    assert f.last_value("p", "d") == "2026-02-01"
    assert f.last_value("p", "d", {"m": "上市"}) == "2026-01-01"
    assert f.last_value("nope", "d") is None
    assert f.upsert("p", [], "id,d") == 0


def test_fake_store_upsert_merges_and_rejects_bad_input():
    f = FakeStore()
    f.upsert("p", [{"id": "1", "a": 1}], "id")
    f.upsert("p", [{"id": "1", "b": 2}], "id")
    assert f.tables["p"][("1",)] == {"id": "1", "a": 1, "b": 2}
    with pytest.raises(ValueError):
        f.upsert("p", [{"id": "1"}], "id, d")
    with pytest.raises(ValueError):
        f.upsert("p", [{"id": "1"}, {"id": "1"}], "id")
