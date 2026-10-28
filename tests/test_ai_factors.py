from datetime import date, timedelta

import pytest

import ai_factors as F


def _days(n, start=date(2026, 7, 1)):
    return [(start + timedelta(days=i)).isoformat() for i in range(n)]


def _prices(closes, vols=None):
    ds = _days(len(closes))
    vols = vols or [1000] * len(closes)
    return [{"trade_date": d, "close": c, "high": c, "low": c, "volume": v} for d, c, v in zip(ds, closes, vols)]


def test_adjusted_prices_removes_ex_dividend_gap():
    rows = _prices([100, 100, 95, 95])
    rows[2]["high"] = 96
    out = F.adjusted_prices(list(reversed(rows)), [{"ex_date": rows[2]["trade_date"], "prev_close": 100, "ref_price": 95}])
    assert [r["close"] for r in out] == [95, 95, 95, 95]          # 除息前價格乘 0.95，缺口消失
    assert out[2]["high"] == 96 and rows[0]["close"] == 100        # 除息日起不變、原資料不被改
    assert F.adjusted_prices(rows, [{"ex_date": rows[2]["trade_date"], "prev_close": None, "ref_price": 95}])[0]["close"] == 100


def test_sma_ema_and_cross():
    assert F.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    assert F.ema([10, 10, 10], 5) == [10, 10, 10]
    assert F.last_cross([1, 1, 3], [2, 2, 2]) == ("golden", 0)
    assert F.last_cross([3, 1, 1, 1], [2, 2, 2, 2]) == ("death", 2)
    assert F.last_cross([3, 1, 1, 1, 1], [2, 2, 2, 2, 2]) is None    # 超過 3 日前不算
    assert F.last_cross([None, 3], [2, 2]) is None


def test_macd_hist_flat_is_zero_and_turns_positive_after_a_dip():
    assert F.macd_hist([50.0] * 40) == [0.0] * 40
    h = F.macd_hist([100.0] * 30 + [100.0 - i for i in range(1, 11)] + [91.0 + 3 * i for i in range(1, 6)])
    assert h[39] < 0 and h[-1] > 0


def test_rsi_extremes_and_short_data():
    assert F.rsi(list(range(1, 20))) == 100.0
    assert F.rsi(list(range(20, 1, -1))) == pytest.approx(0.0)
    assert F.rsi([1, 2, 3]) is None


def test_technicals_detects_breakout_golden_cross_and_volume():
    closes = [100.0] * 40 + [99.0] * 20 + [104.0]
    vols = [1000] * 60 + [3000]
    t = F.technicals(_prices(closes, vols))
    assert t["breakout20"] == "high" and t["vol_ratio"] == 3.0
    assert t["ma_cross"] == ("golden", 0)                          # MA5 由 99 升過 MA20
    assert t["ma20_gap"] == pytest.approx(round((104 / (99 * 19 + 104) * 20 - 1) * 100, 1))
    assert t["above_ma60"] is True and t["rsi"] is not None
    text = F.technicals_text(t)
    assert "MA5/20黃金交叉（今天）" in text and "創20日新高" in text and "量3.0倍" in text


def test_technicals_short_history_is_all_none():
    t = F.technicals(_prices([100.0] * 10))
    assert set(t.values()) == {None} and F.technicals_text(t) == "—"


def test_flow_stats():
    ds = _days(20)
    flows = [{"trade_date": d, "foreign_net": 1000 if i % 2 else -1000, "trust_net": 2000, "dealer_net": None if i < 18 else 500}
             for i, d in enumerate(ds)]
    f = F.flow_stats(list(reversed(flows)))
    assert f == {"foreign_days10": 5, "trust_days10": 10, "dealer5": 1, "foreign20": 0, "trust20": 40}
    assert F.flow_stats([])["foreign_days10"] is None
    assert F.flow_text(f) == "外資10日內買超5天、20日累計+0張；投信10日內買超10天、20日累計+40張；自營商5日累計+1張"


def test_revenue_stats_streak_and_acceleration():
    yoys = [-5, -2, 3, 5, 8, 10, 20, 30]
    rows = [{"data_month": f"115/{m:02d}", "yoy_pct": y, "mom_pct": 1.0, "acc_yoy_pct": 9.0} for m, y in zip(range(1, 9), yoys)]
    r = F.revenue_stats(rows)
    assert r["month"] == "115/08" and r["yoy"] == 30 and r["yoy_streak"] == 6
    assert r["accel"] == pytest.approx(round((10 + 20 + 30) / 3 - (3 + 5 + 8) / 3, 1))
    neg = F.revenue_stats([{"data_month": "115/01", "yoy_pct": -3}, {"data_month": "115/02", "yoy_pct": -4}])
    assert neg["yoy_streak"] == -2 and neg["accel"] is None
    assert "年增連2月為負" in F.revenue_text(neg)
    assert F.revenue_stats([]) is None and F.revenue_text(None) == "—"


def test_score_counts_events():
    t = {"ma_cross": ("golden", 0), "ma_long_cross": None, "kd_cross": None, "macd_turn": None,
         "breakout20": "high", "vol_ratio": 2.0}
    f = {"foreign_days10": 8, "trust_days10": 0}
    assert F.score(t, f, {"yoy": 25, "accel": 12}, 1) == 2 + 1 + 1 + 1 + 1 + 1 + 1


def test_industry_trend_and_rotation_move():
    pts = [(d, 100 + i) for i, d in enumerate(_days(250))]
    t = F.industry_trend(pts)
    assert t["r60"] == pytest.approx(round((349 / 289 - 1) * 100, 2))
    assert t["r1y"] == pytest.approx(round((349 / 100 - 1) * 100, 2))
    assert t["vs_ma20"] > 0 and t["vs_ma60"] > t["vs_ma20"]
    assert F.industry_trend(pts[:30])["r1y"] is None
    p = {"quadrant": "轉強", "x": 99, "y": 101, "trail": [{"x": 98, "y": 97}]}
    assert F.rotation_move(p) == "落後→轉強"
    assert F.rotation_move({**p, "trail": [{"x": 99, "y": 102}]}) == "轉強"
    assert F.rotation_move(None) is None
