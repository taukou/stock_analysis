from datetime import datetime

import pytest

from sync import index_job
from sync.index_job import sync_index
from tests.fakes import FakeStore

NOW = datetime(2026, 10, 30, 18, 0)
D1, D2, D3, D4 = "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"
MKT = ("market", "TW")


def _q(store, sid, d, close, market="上市"):
    store.tables.setdefault("daily_quotes", {})[(sid, d)] = {
        "stock_id": sid, "trade_date": d, "market": market, "close": close}


def _mapping(node="N1"):
    return [{"node_id": node, "stock_id": s, "major_id": "M1", "position_type": "up"}
            for s in ("1111", "2222")]


def _seed(store):
    store.mapping = _mapping()
    for d, a, b in ((D1, 10, 20), (D2, 11, 18), (D3, 11, 18)):
        _q(store, "1111", d, a)
        _q(store, "2222", d, b)
    store.tables["ex_rights"] = {("2222", D3): {"stock_id": "2222", "ex_date": D3, "ref_price": 15}}


def _row(store, kind, sid, d):
    return store.tables["industry_index_daily"][(kind, sid, d)]


def test_first_run_starts_at_100_and_chains_forward():
    s = FakeStore()
    _seed(s)
    r = sync_index(s, NOW)
    assert r.status == "ok" and r.last_date == D3 and r.rows > 0
    for key in (("market", "TW"), ("node", "N1"), ("major", "M1"), ("tier", "M1:up")):
        r1 = _row(s, *key, D1)
        assert r1["level"] == 100 and r1["ret_pct"] is None and r1["members"] == 0
        assert _row(s, *key, D2)["ret_pct"] == pytest.approx(0.0)
        r3 = _row(s, *key, D3)
        assert r3["ret_pct"] == pytest.approx(10.0)
        assert r3["level"] == pytest.approx(110.0)
    assert ("node", "N1") in {k[:2] for k in s.tables["industry_index_scopes"]}
    assert ("market", "TW") not in s.tables["industry_index_scopes"]


def test_second_run_appends_only_new_days():
    s = FakeStore()
    _seed(s)
    sync_index(s, NOW)
    before = {k: dict(v) for k, v in s.tables["industry_index_daily"].items()}
    n = len(s.upserts)
    _q(s, "1111", D4, 12.1)
    _q(s, "2222", D4, 19.8)
    r = sync_index(s, NOW)
    assert r.last_date == D4 and r.rows == 4
    assert len(s.upserts) == n + 1
    for k, v in before.items():
        assert s.tables["industry_index_daily"][k] == v
    assert _row(s, "node", "N1", D4)["level"] == pytest.approx(110.0 * 1.1)


def test_missing_close_not_counted_as_zero():
    s = FakeStore()
    _seed(s)
    del s.tables["daily_quotes"][("2222", D2)]
    sync_index(s, NOW)
    r2 = _row(s, "node", "N1", D2)
    assert r2["members"] == 1 and r2["ret_pct"] == pytest.approx(10.0)


def test_new_scope_backfilled_from_db_start_and_registered():
    s = FakeStore()
    _seed(s)
    sync_index(s, NOW)
    h = dict(s.tables["industry_index_scopes"][("node", "N1")])
    s.mapping = [{"node_id": "N1", "stock_id": "1111", "major_id": "M1", "position_type": "up"},
                 {"node_id": "N9", "stock_id": "2222", "major_id": "M9", "position_type": "mid"}]
    _q(s, "1111", D4, 12)
    _q(s, "2222", D4, 18)
    sync_index(s, NOW)
    assert _row(s, "node", "N9", D1)["level"] == 100
    assert ("node", "N9", D4) in s.tables["industry_index_daily"]
    assert ("node", "N9") in s.tables["industry_index_scopes"]
    assert s.tables["industry_index_scopes"][("node", "N1")] == h
    assert ("node", "N1", D4) in s.tables["industry_index_daily"]


def test_no_new_quotes_writes_nothing():
    s = FakeStore()
    _seed(s)
    sync_index(s, NOW)
    n = len(s.upserts)
    r = sync_index(s, NOW)
    assert r.status == "ok" and r.rows == 0 and r.last_date == D3
    assert len(s.upserts) == n


def test_exception_returns_failed():
    s = FakeStore()

    def boom(*a, **k):
        raise RuntimeError("壞了")
    s.quotes_between = boom
    r = sync_index(s, NOW)
    assert r.status == "failed" and "壞了" in r.message


def test_new_scope_with_member_missing_on_last_keeps_going():
    s = FakeStore()
    _seed(s)
    sync_index(s, NOW)
    s.mapping = _mapping() + [{"node_id": "N9", "stock_id": "2222",
                               "major_id": "M1", "position_type": "up"}]
    _q(s, "1111", D4, 12)   # 2222 在 D4 停牌
    sync_index(s, NOW)
    assert _row(s, "node", "N9", D4)["ret_pct"] is None
    _q(s, "1111", "2026-10-30", 12)
    _q(s, "2222", "2026-10-30", 19)
    r = sync_index(s, datetime(2026, 11, 2, 18))
    assert ("node", "N9", "2026-10-30") in s.tables["industry_index_daily"]
    assert r.last_date == "2026-10-30"


def test_registered_scope_without_last_row_resumes_from_own_last_row():
    s = FakeStore()
    _seed(s)
    sync_index(s, NOW)
    for sid, d in [("1111", D4), ("2222", D4)]:
        _q(s, sid, d, 11 if sid == "1111" else 18)
    s.mapping = []          # 節點暫時移出
    sync_index(s, NOW)
    assert ("node", "N1", D4) not in s.tables["industry_index_daily"]
    s.mapping = _mapping()
    sync_index(s, NOW)
    assert ("node", "N1", D4) in s.tables["industry_index_daily"]
