from datetime import date, datetime

import pytest

import rebuild_index
from sync.index_backfill import DATASET, backfill_index
from sync.models import Quote
from tests.fakes import FakeStore

D1, D2, D3, D4 = "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"
NOW = datetime(2027, 10, 26, 18, 0)   # 目標日 = D1
MKT = ("market", "TW")
KEYS = (MKT, ("node", "N1"), ("major", "M1"), ("tier", "M1:up"))


def _quote(sid, d, close, market):
    return Quote(sid, sid, date.fromisoformat(d), market, None, None, None, close,
                 None, None, None)


def _fetchers(data, raise_on=None):
    """data: {日期: (上市 {id: close}, 上櫃 {id: close})}；沒列的日期兩市場皆空。"""
    calls = []

    def make(i, market):
        def fetch(d):
            iso = d.isoformat()
            calls.append(iso)
            if iso == raise_on:
                raise RuntimeError("連線失敗")
            return [_quote(s, iso, c, market) for s, c in data.get(iso, ({}, {}))[i].items()]
        return fetch
    return (make(0, "上市"), make(1, "上櫃")), calls


def _seed(store, with_d4=True):
    store.mapping = [{"node_id": "N1", "stock_id": s, "major_id": "M1", "position_type": "up"}
                     for s in ("1111", "2222")]
    for sid, c in (("1111", 11), ("2222", 18)):
        store.tables.setdefault("daily_quotes", {})[(sid, D3)] = {
            "stock_id": sid, "trade_date": D3, "market": "上市", "close": c}
    rows = {}
    for k in KEYS:
        rows[(*k, D3)] = {"scope_kind": k[0], "scope_id": k[1], "trade_date": D3,
                          "level": 100.0, "ret_pct": None, "members": 0}
        if with_d4:
            rows[(*k, D4)] = {"scope_kind": k[0], "scope_id": k[1], "trade_date": D4,
                              "level": 110.0, "ret_pct": 10.0, "members": 2}
    store.tables["industry_index_daily"] = rows


DATA = {D2: ({"1111": 10}, {"2222": 12}), D1: ({"1111": 5}, {"2222": 12})}


def _daily(s):
    return s.tables["industry_index_daily"]


def test_backfill_extends_backwards_and_fills_seam():
    s = FakeStore()
    _seed(s)
    f, _ = _fetchers(DATA)
    r = backfill_index(s, NOW, f)
    assert r.dataset == DATASET and r.status == "ok" and r.last_date == D1
    for k in KEYS:
        d3 = _daily(s)[(*k, D3)]
        assert d3["ret_pct"] == pytest.approx(30.0)   # (11/10-1 + 18/12-1)/2
        assert d3["members"] == 2 and d3["level"] == 100.0
        d2 = _daily(s)[(*k, D2)]
        assert d2["level"] == pytest.approx(100 / 1.3, abs=1e-5)
        assert d2["ret_pct"] == pytest.approx(50.0) and d2["members"] == 2
        d1 = _daily(s)[(*k, D1)]
        assert d1["level"] == pytest.approx(100 / 1.3 / 1.5, abs=1e-5)
        assert d1["ret_pct"] is None and d1["members"] == 0
        assert _daily(s)[(*k, D4)]["level"] == 110.0   # 後面的列不動
    assert _daily(s)[(*MKT, D2)]["ret_pct"] == pytest.approx(50.0)
    assert ("market", "TW") not in s.tables.get("industry_index_scopes", {})


def test_resume_equals_single_run():
    a, b = FakeStore(), FakeStore()
    _seed(a)
    _seed(b)
    f, _ = _fetchers(DATA)
    backfill_index(a, NOW, f, max_days=1)
    assert min(r["trade_date"] for r in _daily(a).values()) == D2
    backfill_index(a, NOW, f, max_days=1)
    backfill_index(b, NOW, f, max_days=2)
    assert _daily(a) == _daily(b)


def test_one_market_missing_fails_without_writing():
    s = FakeStore()
    _seed(s)
    before = {k: dict(v) for k, v in _daily(s).items()}
    n = len(s.upserts)
    # 上市有、上櫃無 -> 無法判斷是否休市
    f2, _ = _fetchers({D2: ({"1111": 10}, {}), D1: ({}, {})})
    r = backfill_index(s, NOW, f2)
    assert r.status == "failed" and len(s.upserts) == n and _daily(s) == before


def test_fetch_exception_fails_without_writing():
    s = FakeStore()
    _seed(s)
    f, _ = _fetchers(DATA, raise_on=D2)
    n = len(s.upserts)
    r = backfill_index(s, NOW, f)
    assert r.status == "failed" and len(s.upserts) == n and r.rows == 0


def test_holidays_skipped():
    s = FakeStore()
    _seed(s)
    # D2 兩市場皆空（休市）-> D3 的前一交易日是 D1
    f, _ = _fetchers({D1: ({"1111": 10}, {"2222": 12})})
    r = backfill_index(s, NOW, f)
    assert r.status == "ok" and r.last_date == D1
    assert (*MKT, D2) not in _daily(s)
    assert _daily(s)[(*MKT, D3)]["ret_pct"] == pytest.approx(30.0)


def test_too_many_holidays_fails():
    s = FakeStore()
    _seed(s)
    f, _ = _fetchers({})
    r = backfill_index(s, NOW, f, max_holiday_run=3)
    assert r.status == "failed"


def test_done_when_reached_target_fetches_nothing():
    s = FakeStore()
    _seed(s)

    def boom(d):
        raise AssertionError("不該抓取")
    r = backfill_index(s, datetime(2027, 10, 28, 18, 0), (boom, boom))   # 目標 D3 = 最早日
    assert r.status == "ok" and r.rows == 0


def test_no_index_yet():
    s = FakeStore()
    r = backfill_index(s, NOW, (None, None))
    assert r.status == "ok" and r.rows == 0 and "尚無指數" in r.message


def test_rebuild_writes_all_levels_from_100():
    s = FakeStore()
    _seed(s)
    f, _ = _fetchers({D1: ({"1111": 10}, {"2222": 20}), D2: ({"1111": 11}, {"2222": 20})})
    n = rebuild_index.rebuild(s, NOW, f)
    assert n > 0
    for k in KEYS:
        assert _daily(s)[(*k, D1)]["level"] == 100.0
        assert _daily(s)[(*k, D2)]["level"] == pytest.approx(105.0)
    scopes = {k[:2] for k in s.tables["industry_index_scopes"]}
    assert scopes == {("node", "N1"), ("major", "M1"), ("tier", "M1:up")}


def test_rebuild_writes_all_or_nothing():
    s = FakeStore()
    _seed(s)
    f, _ = _fetchers({D1: ({"1111": 10}, {"2222": 20})}, raise_on=D2)
    s.upserts.clear()
    assert rebuild_index.rebuild(s, NOW, f) < 0
    assert s.upserts == []
