from trends import trading_dates, period_return, ex_kind_in_period, node_average

D = ["2026-09-22", "2026-09-19", "2026-09-18", "2026-09-17", "2026-09-16", "2026-09-15"]  # 新到舊

def test_trading_dates_listed_only_desc():
    rows = [
        {"trade_date": "2026-09-15", "market": "上市", "close": 1.0},
        {"trade_date": "2026-09-16", "market": "上櫃", "close": 2.0},
        {"trade_date": "2026-09-17", "market": "興櫃", "close": 3.0},
        {"trade_date": "2026-09-18", "market": "上市", "close": None},
        {"trade_date": "2026-09-16", "market": "上市", "close": 4.0},
    ]
    assert trading_dates(rows) == ["2026-09-16", "2026-09-15"]

def test_today_uses_latest_change_pct():
    assert period_return(1, D, {}, -0.42, []) == -0.42
    assert period_return(1, D, {}, None, []) is None

def test_five_day_plain():
    closes = {"2026-09-22": 110.0, "2026-09-15": 100.0}
    assert period_return(5, D, closes, None, []) == 10.0

def test_five_day_adjusts_for_ex_dividend():
    # 2330：09-15 收 2385，09-16 除息 7 元參考價 2377.99；09-22 收 2377.99 → 還原後持平
    closes = {"2026-09-22": 2377.99, "2026-09-15": 2385.0}
    ex = [{"ex_date": "2026-09-16", "kind": "除息", "prev_close": 2385.0, "ref_price": 2377.99}]
    assert period_return(5, D, closes, None, ex) == 0.0

def test_ex_event_outside_window_ignored():
    closes = {"2026-09-22": 110.0, "2026-09-15": 100.0}
    ex = [{"ex_date": "2026-09-15", "kind": "除息", "prev_close": 105.0, "ref_price": 100.0}]
    assert period_return(5, D, closes, None, ex) == 10.0

def test_missing_close_or_short_history_is_none():
    assert period_return(5, D, {"2026-09-22": 110.0}, None, []) is None          # 起點缺
    assert period_return(5, D, {"2026-09-15": 100.0}, None, []) is None          # 最新日停牌
    assert period_return(20, D, {"2026-09-22": 1.0, "2026-09-15": 1.0}, None, []) is None  # 歷史不足（興櫃）

def test_ex_kind_in_period():
    ex = [{"ex_date": "2026-09-16", "kind": "除息"}, {"ex_date": "2026-09-01", "kind": "除權"}]
    assert ex_kind_in_period(1, D, ex) is None
    assert ex_kind_in_period(5, D, ex) == "除息"
    assert ex_kind_in_period(1, ["2026-09-16", "2026-09-15"], ex) == "除息"

def test_node_average_excludes_missing():
    assert node_average([1.0, None, 2.0]) == (1.5, 2)
    assert node_average([None, None]) == (None, 0)
    assert node_average([]) == (None, 0)
