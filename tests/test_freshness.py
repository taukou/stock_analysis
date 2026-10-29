# tests/test_freshness.py
from datetime import datetime
from freshness import freshness, parse_finished_at, weekday_lag

# 2026-10-23（五）、2026-10-26（一）為休市日的情境
AFTER_CLOSE_MON = "2026-10-26T08:00:15+00:00"   # = 台北 16:00:15
BEFORE_CLOSE_MON = "2026-10-26T06:30:00+00:00"  # = 台北 14:30


def run(ds, last, status="ok", finished="2026-10-26T08:00:15+00:00", message=""):
    return {"dataset": ds, "last_date": last, "status": status, "finished_at": finished, "message": message}


def test_weekday_lag():
    assert weekday_lag("2026-10-22", datetime(2026, 10, 23, 10)) == 0   # 週五早上，應有日 = 週四
    assert weekday_lag("2026-10-22", datetime(2026, 10, 23, 16)) == 1
    assert weekday_lag("2026-10-22", datetime(2026, 10, 26, 16)) == 2   # 下週一傍晚


def test_ok_stale_failed():
    now = datetime(2026, 10, 26, 16)
    ok = [run("quotes", "2026-10-26"), run("institutional", "2026-10-26"), run("revenue", "115/09")]
    assert freshness(ok, now)["level"] == "ok"
    assert freshness(ok, now)["message"].startswith("資料更新至 2026-10-26")
    stale = [run("quotes", "2026-10-22", finished=BEFORE_CLOSE_MON), run("institutional", "2026-10-26")]
    f = freshness(stale, now)
    assert f["level"] == "stale" and f["message"].endswith("股價資料落後")
    failed = [run("revenue", None, "failed"), run("revenue", "115/09")] + ok[:2]
    f = freshness(failed, now)
    assert f["level"] == "failed" and "同步失敗：月營收" in f["message"]


def test_empty_runs():
    f = freshness([], datetime(2026, 10, 26, 16))
    assert f["message"].startswith("資料更新至 —")
    assert f["level"] == "stale" and "尚無股價同步紀錄" in f["message"]


def test_missing_dataset_and_null_last_date():
    now = datetime(2026, 10, 26, 16)
    only_quotes = [run("quotes", "2026-10-26")]
    f = freshness(only_quotes, now)
    assert f["level"] == "stale" and f["message"].endswith("尚無法人同步紀錄")
    null_last = [run("quotes", "2026-10-26"), run("institutional", None)]
    f = freshness(null_last, now)
    assert f["level"] == "stale" and f["message"].endswith("法人尚無資料")
    assert "缺少" not in f["message"]


def test_institutional_only_stale():
    now = datetime(2026, 10, 28, 16)   # 週三
    rows = [run("quotes", "2026-10-28", finished="2026-10-28T08:00:00+00:00"),
            run("institutional", "2026-10-22", finished="2026-10-27T06:00:00+00:00")]
    f = freshness(rows, now)
    assert f["level"] == "stale" and f["message"].endswith("法人資料落後")


def test_weekend_now():
    # 週六：應有日為週五；週四資料只落後 1 個工作日 → ok
    rows = [run("quotes", "2026-10-29"), run("institutional", "2026-10-29")]
    assert freshness(rows, datetime(2026, 10, 31, 12))["level"] == "ok"
    # 週日：週三資料落後 2 天，且週五收盤後沒有同步 → stale
    rows = [run("quotes", "2026-10-28", finished="2026-10-29T08:00:00+00:00"),
            run("institutional", "2026-10-28", finished="2026-10-29T08:00:00+00:00")]
    assert freshness(rows, datetime(2026, 11, 1, 12))["level"] == "stale"


def test_holiday_with_ok_run_after_close_is_ok():
    rows = [run("quotes", "2026-10-22", finished=AFTER_CLOSE_MON),
            run("emerging", "2026-10-22", finished=AFTER_CLOSE_MON),
            run("institutional", "2026-10-22", finished=AFTER_CLOSE_MON)]
    f = freshness(rows, datetime(2026, 10, 26, 22, 30))
    assert f["level"] == "ok" and f["message"] == "資料更新至 2026-10-22"


def test_holiday_but_run_before_close_is_stale():
    rows = [run("quotes", "2026-10-22", finished=BEFORE_CLOSE_MON),
            run("institutional", "2026-10-22", finished=BEFORE_CLOSE_MON)]
    assert freshness(rows, datetime(2026, 10, 26, 22, 30))["level"] == "stale"


def test_partial_message_is_stale():
    rows = [run("quotes", "2026-10-22", message="partial: 上櫃 not yet published for 2026-10-26"),
            run("institutional", "2026-10-22")]
    f = freshness(rows, datetime(2026, 10, 26, 22, 30))
    assert f["level"] == "stale" and f["message"].endswith("股價資料落後")


def test_lag_over_ceiling_is_stale_even_with_ok_run():
    # 10-16（五）→ 10-26（一）傍晚：落後 6 個工作日
    rows = [run("quotes", "2026-10-16"), run("institutional", "2026-10-16")]
    f = freshness(rows, datetime(2026, 10, 26, 22, 30))
    assert f["level"] == "stale" and "6 個工作日沒有新資料" in f["message"]


def test_emerging_ahead_of_quotes_is_stale():
    rows = [run("quotes", "2026-10-22"), run("emerging", "2026-10-26"), run("institutional", "2026-10-22")]
    f = freshness(rows, datetime(2026, 10, 26, 22, 30))
    assert f["level"] == "stale" and "興櫃已有 2026-10-26" in f["message"]


def test_parse_finished_at_utc_to_taipei():
    dt = parse_finished_at("2026-10-26T08:00:15+00:00")
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 10, 26, 16, 0)
    assert parse_finished_at("2026-10-26T08:00:15.123456Z").hour == 16
    assert parse_finished_at("2026-10-26T08:00:15").hour == 16   # 無時區視為 UTC
    assert parse_finished_at(None) is None and parse_finished_at("x") is None


def test_datasets_carry_chinese_labels():
    rows = [run("quotes", "2026-10-26"), run("ex_rights", "2026-10-20")]
    labels = {d["dataset"]: d["label"] for d in freshness(rows, datetime(2026, 10, 26, 16))["datasets"]}
    assert labels == {"quotes": "股價", "ex_rights": "除權息"}


def test_industry_index_failed_is_reported():
    rows = [run("quotes", "2026-10-26"), run("industry_index", None, "failed")]
    out = freshness(rows, datetime(2026, 10, 26, 16))
    assert out["level"] == "failed" and "產業指數" in out["message"]


def test_local_status_failure_wins_and_hints_cause():
    from freshness import local_failure
    now = datetime(2026, 10, 26, 16)
    ok = [run("quotes", "2026-10-26"), run("institutional", "2026-10-26")]
    assert freshness(ok, now, {"finished_at": "x", "ok": True, "problems": []})["level"] == "ok"
    local = {"finished_at": "2026-10-28 16:00", "ok": False, "problems": [
        {"label": "股價", "message": "{'code': 401, 'details': 'Invalid API key'}"},
        {"label": "股價同步紀錄", "message": "APIError"}]}
    f = freshness(ok, now, local)
    assert f["level"] == "failed"
    assert f["message"] == ("資料更新至 2026-10-26；最近一次同步（2026-10-28 16:00）失敗：股價、股價同步紀錄"
                            "（資料庫金鑰無效，請檢查 .env 的 SUPABASE 金鑰）")
    many = {"finished_at": "t", "ok": False, "problems": [{"label": str(i), "message": "boom"} for i in range(6)]}
    assert local_failure(many) == "最近一次同步（t）失敗：0、1、2、3 等 6 項；詳見 logs/sync.log"
    assert local_failure(None) is None
