from datetime import date, datetime

from sync.http import SourceError
from sync.jobs import JobResult, dates_to_fetch, keep_row, sync_emerging, sync_institutional, sync_quotes
from sync.models import InstFlow, Quote
from tests.fakes import FakeStore


def q(sid, d, market="上市", close=10.0):
    return Quote(sid, "n", d, market, 1, 2, 0.5, close, 0, 0, 100)


def flow(sid, d):
    return InstFlow(sid, d, 1, 2, 3, 6)


D22, D23 = date(2026, 10, 22), date(2026, 10, 23)


# ---- dates_to_fetch ----
def test_dates_to_fetch_excludes_today_before_15():
    assert dates_to_fetch(date(2026, 10, 20), datetime(2026, 10, 22, 9, 0)) == [date(2026, 10, 21)]


def test_dates_to_fetch_includes_today_after_15_and_skips_weekend():
    assert dates_to_fetch(date(2026, 10, 23), datetime(2026, 10, 26, 16, 0)) == [date(2026, 10, 26)]


def test_dates_to_fetch_empty_table_backfills_95_days():
    ds = dates_to_fetch(None, datetime(2026, 10, 22, 16, 0))
    assert ds[0] >= date(2026, 7, 19) and ds[-1] == date(2026, 10, 22) and all(d.weekday() < 5 for d in ds)


# ---- keep_row ----
def test_keep_row_filter():
    tracked = {"00981A", "6488"}
    assert keep_row("2330", set())
    assert not keep_row("03001P", tracked)
    assert keep_row("00981A", tracked)
    assert not keep_row("00981A", set())
    assert not keep_row("23300", set())
    assert not keep_row("233", set())


# ---- sync_quotes ----
def make_fetchers(twse_by_day, tpex_by_day):
    def f(by_day):
        def fetch(d):
            v = by_day.get(d, [])
            if isinstance(v, Exception):
                raise v
            return v
        return fetch
    return f(twse_by_day), f(tpex_by_day)


def test_sync_quotes_skips_holiday():
    store = FakeStore()
    tw = {D22: [q("2330", D22)]}
    tp = {D22: [q("6488", D22, "上櫃")]}
    store.tables["daily_quotes"] = {("2330", "2026-10-21"): {"trade_date": "2026-10-21", "market": "上市"}}
    r = sync_quotes(store, datetime(2026, 10, 23, 16, 0), fetchers=make_fetchers(tw, tp))
    assert r.status == "ok" and r.last_date == "2026-10-22" and r.rows == 2 and r.dataset == "quotes"
    assert store.upserts == [("daily_quotes", 2)]


def test_sync_quotes_failure_keeps_written_days():
    store = FakeStore()
    store.tables["daily_quotes"] = {("2330", "2026-10-20"): {"trade_date": "2026-10-20", "market": "上市"}}
    tw = {D22: [q("2330", D22)], D23: SourceError("boom")}
    tp = {D22: [q("6488", D22, "上櫃")]}
    r = sync_quotes(store, datetime(2026, 10, 23, 16, 0), fetchers=make_fetchers(tw, tp))
    # 10/21 為空(假日)，10/22 寫入，10/23 失敗
    assert r.status == "failed" and r.last_date == "2026-10-22" and "boom" in r.message
    assert len(store.upserts) == 1


def test_sync_quotes_unexpected_exception_is_caught():
    store = FakeStore()
    tw = {D22: ValueError("bad")}
    r = sync_quotes(store, datetime(2026, 10, 22, 16, 0), fetchers=make_fetchers(tw, {}))
    assert r.status == "failed" and r.last_date is None


def test_sync_quotes_filters_and_dedupes():
    store = FakeStore()
    store.tracked = [{"stock_id": "00981A", "company_name": "x", "market_type": "上市"}]
    tw = {D22: [q("2330", D22), q("03001P", D22), q("00981A", D22), q("2330", D22, close=99)]}
    tp = {D22: [q("6488", D22, "上櫃")]}
    r = sync_quotes(store, datetime(2026, 10, 22, 16, 0), fetchers=make_fetchers(tw, tp))
    assert r.status == "ok" and r.rows == 3
    assert store.tables["daily_quotes"][("2330", "2026-10-22")]["close"] == 10.0
    assert ("03001P", "2026-10-22") not in store.tables["daily_quotes"]


# ---- sync_institutional ----
def test_sync_institutional_writes_per_day():
    store = FakeStore()
    store.tables["smart_money_flow"] = {("2330", "2026-10-21"): {"trade_date": "2026-10-21"}}
    tw = {D22: [flow("2330", D22), flow("03001P", D22)]}
    tp = {D22: [flow("6488", D22)]}
    r = sync_institutional(store, datetime(2026, 10, 22, 16, 0), fetchers=make_fetchers(tw, tp))
    assert r.dataset == "institutional" and r.status == "ok" and r.rows == 2 and r.last_date == "2026-10-22"
    assert store.upserts == [("smart_money_flow", 2)]


def test_sync_institutional_nothing_new_keeps_last():
    store = FakeStore()
    store.tables["smart_money_flow"] = {("2330", "2026-10-22"): {"trade_date": "2026-10-22"}}
    r = sync_institutional(store, datetime(2026, 10, 22, 16, 0), fetchers=make_fetchers({}, {}))
    assert r.status == "ok" and r.rows == 0 and r.last_date == "2026-10-22"


# ---- sync_emerging ----
def test_emerging_writes_response_day():
    store = FakeStore()
    rows = [q("1234", D22, "興櫃"), q("03001P", D22, "興櫃")]
    r = sync_emerging(store, datetime(2026, 10, 23, 10, 0), fetcher=lambda: rows)
    assert r.dataset == "emerging" and r.status == "ok" and r.rows == 1 and r.last_date == "2026-10-22"
    assert store.upserts == [("daily_quotes", 1)]


def test_emerging_today_before_15_writes_nothing():
    store = FakeStore()
    store.tables["daily_quotes"] = {("1234", "2026-10-21"): {"trade_date": "2026-10-21", "market": "興櫃"}}
    r = sync_emerging(store, datetime(2026, 10, 22, 10, 0), fetcher=lambda: [q("1234", D22, "興櫃")])
    assert r.status == "ok" and r.rows == 0 and r.last_date == "2026-10-21"
    assert store.upserts == []


def test_emerging_failure():
    def boom():
        raise SourceError("down")
    r = sync_emerging(FakeStore(), datetime(2026, 10, 22, 16, 0), fetcher=boom)
    assert r.status == "failed" and r.message == "down"


# ---- 部分公布（Ruling 12）----
def _seed_quotes(store):
    store.tables["daily_quotes"] = {("2330", "2026-10-21"): {"trade_date": "2026-10-21", "market": "上市"}}


def test_partial_tpex_missing_writes_nothing_for_day():
    store = FakeStore()
    _seed_quotes(store)
    tw = {D22: [q("2330", D22)]}
    r = sync_quotes(store, datetime(2026, 10, 22, 16, 0), fetchers=make_fetchers(tw, {}))
    assert r.status == "ok" and r.last_date == "2026-10-21" and r.rows == 0
    assert "上櫃" in r.message and "2026-10-22" in r.message
    assert store.upserts == []


def test_partial_twse_missing_writes_nothing_for_day():
    store = FakeStore()
    store.tables["smart_money_flow"] = {("2330", "2026-10-21"): {"trade_date": "2026-10-21"}}
    tp = {D22: [flow("6488", D22)]}
    r = sync_institutional(store, datetime(2026, 10, 22, 16, 0), fetchers=make_fetchers({}, tp))
    assert r.status == "ok" and r.last_date == "2026-10-21"
    assert "上市" in r.message and store.upserts == []


def test_partial_stops_later_days():
    store = FakeStore()
    _seed_quotes(store)
    tw = {D22: [q("2330", D22)], D23: [q("2330", D23)]}
    tp = {D23: [q("6488", D23, "上櫃")]}
    r = sync_quotes(store, datetime(2026, 10, 23, 16, 0), fetchers=make_fetchers(tw, tp))
    assert r.last_date == "2026-10-21" and store.upserts == []


def test_tpex_raises_after_twse_ok_day_unwritten():
    store = FakeStore()
    _seed_quotes(store)
    tw = {D22: [q("2330", D22)]}
    tp = {D22: SourceError("tpex down")}
    r = sync_quotes(store, datetime(2026, 10, 22, 16, 0), fetchers=make_fetchers(tw, tp))
    assert r.status == "failed" and r.last_date == "2026-10-21" and store.upserts == []
