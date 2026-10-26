# tests/test_freshness.py
from datetime import datetime
from freshness import freshness, weekday_lag

def run(ds, last, status="ok"):
    return {"dataset": ds, "last_date": last, "status": status, "finished_at": "x"}

def test_weekday_lag():
    assert weekday_lag("2026-10-22", datetime(2026, 10, 23, 10)) == 0   # 週五早上，應有日 = 週四
    assert weekday_lag("2026-10-22", datetime(2026, 10, 23, 16)) == 1
    assert weekday_lag("2026-10-22", datetime(2026, 10, 26, 16)) == 2   # 下週一傍晚

def test_ok_stale_failed():
    now = datetime(2026, 10, 26, 16)
    ok = [run("quotes", "2026-10-26"), run("institutional", "2026-10-26"), run("revenue", "115/09")]
    assert freshness(ok, now)["level"] == "ok"
    assert freshness(ok, now)["message"].startswith("資料更新至 2026-10-26")
    stale = [run("quotes", "2026-10-22"), run("institutional", "2026-10-26")]
    assert freshness(stale, now)["level"] == "stale"
    failed = [run("revenue", None, "failed"), run("revenue", "115/09")] + ok[:2]
    f = freshness(failed, now)
    assert f["level"] == "failed" and "revenue" in f["message"]

def test_empty_runs():
    f = freshness([], datetime(2026, 10, 26, 16))
    assert f["message"].startswith("資料更新至 —")
