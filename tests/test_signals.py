# tests/test_signals.py
from signals import trust_streak, yoy_turn_positive, revenue_12m_high, volume_spike, company_signals, month_index

DATES = [f"d{i:02d}" for i in range(25)]  # d00 最新

def test_month_index():
    assert month_index("115/09") - month_index("114/09") == 12

def test_trust_streak_needs_five_consecutive():
    t = {d: 100 for d in DATES[:5]}
    assert trust_streak(DATES, t)["label"] == "投信連買 5 日"
    t["d03"] = None
    assert trust_streak(DATES, t) is None
    assert trust_streak(DATES[:4], {d: 1 for d in DATES[:4]}) is None

def test_yoy_turn():
    rev = [{"data_month": "115/08", "yoy_pct": -3.2}, {"data_month": "115/09", "yoy_pct": 5.1}]
    assert yoy_turn_positive(rev)["code"] == "yoy_turn"
    assert yoy_turn_positive([{"data_month": "115/07", "yoy_pct": -3.2}, {"data_month": "115/09", "yoy_pct": 5.1}]) is None  # 不相鄰
    assert yoy_turn_positive([{"data_month": "115/08", "yoy_pct": None}, {"data_month": "115/09", "yoy_pct": 5.1}]) is None

def _months(vals):
    return [{"data_month": f"{114 + (8 + i) // 12}/{(8 + i) % 12 + 1:02d}", "revenue": v} for i, v in enumerate(vals)]

def test_revenue_12m_high():
    assert revenue_12m_high(_months([10] * 11 + [11]))["code"] == "revenue_high"   # 114/09…115/08
    assert revenue_12m_high(_months([10] * 11 + [10])) is None
    assert revenue_12m_high(_months([10] * 10 + [11])) is None                       # 不足 12 個月
    assert revenue_12m_high(_months([10] * 5 + [None] + [10] * 5 + [11])) is None

def test_volume_spike():
    vol = {d: 1000 for d in DATES[1:21]}
    vol["d00"] = 2000
    assert volume_spike(DATES, vol)["code"] == "volume_spike"
    vol["d00"] = 1999
    assert volume_spike(DATES, vol) is None
    vol["d00"] = 5000; vol["d10"] = None
    assert volume_spike(DATES, vol) is None

def test_company_signals_collects():
    assert company_signals(DATES, {}, [], {}) == []
