from datetime import date, datetime

from sync.jobs import months_to_fetch, month_chunks, sync_ex_rights, sync_revenue
from sync.models import ExRight, Revenue
from tests.fakes import FakeStore

NOW = datetime(2026, 10, 25, 16, 0)


def rev(sid, month):
    return Revenue(sid, month, 100, 1.0, 2.0, 3.0)


def exr(sid, d):
    return ExRight(sid, d, "除息", 10.0, 9.0, 1.0)


# ---- months_to_fetch ----
def test_months_to_fetch_refetches_last_two():
    assert months_to_fetch("115/08", date(2026, 10, 25)) == [(115, 7), (115, 8), (115, 9)]


def test_months_to_fetch_empty_backfills_13():
    ms = months_to_fetch(None, date(2026, 10, 25))
    assert len(ms) == 13 and ms[-1] == (115, 9) and ms[0] == (114, 9)


def test_months_to_fetch_year_boundary():
    assert months_to_fetch("114/12", date(2026, 2, 5)) == [(114, 11), (114, 12), (115, 1)]


# ---- sync_revenue ----
def test_sync_revenue_skips_unpublished_month():
    calls = []

    def fetcher(y, m, market):
        calls.append((y, m, market))
        if (y, m) == (115, 9):
            return []
        return [rev("2330", f"{y}/{m:02d}")] if market == "sii" else []

    s = FakeStore()
    s.tables["growth_momentum"] = {("2330", "115/08"): {"stock_id": "2330", "data_month": "115/08"}}
    r = sync_revenue(s, NOW, fetcher)
    assert r.status == "ok" and r.last_date == "115/08" and r.rows == 2
    assert (115, 9, "rotc") in calls


def test_sync_revenue_dedupes_across_markets_and_writes_once_per_month():
    def fetcher(y, m, market):
        return [rev("2330", f"{y}/{m:02d}"), rev(f"{market[0]}111", f"{y}/{m:02d}")]

    s = FakeStore()
    s.tables["growth_momentum"] = {("2330", "115/08"): {"stock_id": "2330", "data_month": "115/08"}}
    r = sync_revenue(s, NOW, fetcher)
    assert r.status == "ok" and r.last_date == "115/09"
    assert all(n == 4 for _, n in s.upserts)  # 2330 + s111/o111/r111
    assert len(s.upserts) == 3


def test_sync_revenue_failure_is_caught():
    def fetcher(y, m, market):
        raise RuntimeError("boom")

    r = sync_revenue(FakeStore(), NOW, fetcher)
    assert r.status == "failed" and r.message == "boom"


# ---- month_chunks ----
def test_month_chunks_split_by_calendar_month():
    assert month_chunks(date(2026, 8, 25), date(2026, 10, 25)) == [
        (date(2026, 8, 25), date(2026, 8, 31)),
        (date(2026, 9, 1), date(2026, 9, 30)),
        (date(2026, 10, 1), date(2026, 10, 25)),
    ]


# ---- sync_ex_rights ----
def test_sync_ex_rights_chunks_filters_and_dedupes():
    reqs = []

    def twse_f(a, b):
        reqs.append((a, b))
        return [exr("2330", a), exr("00878", a), exr("9999X", a)] if a == date(2026, 10, 1) else []

    def tpex_f(a, b):
        return [exr("2330", a)] if a == date(2026, 10, 1) else []

    s = FakeStore()
    s.tracked = [{"stock_id": "00878"}]
    s.tables["ex_rights"] = {("1101", "2026-09-20"): {"stock_id": "1101", "ex_date": "2026-09-20"}}
    r = sync_ex_rights(s, NOW, (twse_f, tpex_f))
    assert reqs == [(date(2026, 9, 13), date(2026, 9, 30)), (date(2026, 10, 1), date(2026, 10, 25))]
    assert r.status == "ok" and r.rows == 2 and r.last_date == "2026-10-01"


def test_sync_ex_rights_empty_table_starts_400_days_back():
    reqs = []

    def f(a, b):
        reqs.append((a, b))
        return []

    r = sync_ex_rights(FakeStore(), NOW, (f, f))
    assert reqs[0][0] == date(2025, 9, 20) and reqs[-1][1] == date(2026, 10, 25)
    assert r.status == "ok" and r.rows == 0 and r.last_date is None


def test_sync_ex_rights_failure_is_caught():
    def f(a, b):
        raise RuntimeError("down")

    r = sync_ex_rights(FakeStore(), NOW, (f, f))
    assert r.status == "failed" and r.message == "down"


def test_sync_ex_rights_keeps_same_stock_on_different_dates():
    def f(a, b):
        return [exr("2330", date(2026, 10, 2)), exr("2330", date(2026, 10, 9))] if a.day == 1 else []

    s = FakeStore()
    s.tables["ex_rights"] = {("1101", "2026-09-28"): {"stock_id": "1101", "ex_date": "2026-09-28"}}
    r = sync_ex_rights(s, NOW, (f, lambda a, b: []))
    assert r.rows == 2 and len(s.tables["ex_rights"]) == 3
