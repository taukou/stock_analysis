import industry_trends as t

def pts(vals, start=1):
    return [(f"2026-01-{i + start:02d}", v) for i, v in enumerate(vals)]

def test_rebase_uses_available_history_when_range_longer():
    assert t.rebase(pts([50, 55, 60]), 250) == [
        {"date": "2026-01-01", "value": 100.0}, {"date": "2026-01-02", "value": 110.0},
        {"date": "2026-01-03", "value": 120.0}]
    assert t.rebase(pts([50, 55, 60]), 1)[0] == {"date": "2026-01-02", "value": 100.0}

def test_period_change():
    assert t.period_change(pts([100, 105, 110]), 2) == 10.0
    assert t.period_change(pts([100]), 1) is None

def test_quadrants():
    assert [t.quadrant(*p) for p in [(101, 101), (101, 99), (99, 99), (99, 101)]] == ["領先", "轉弱", "落後", "轉強"]

def test_rrg_flat_relative_is_centre_and_short_history_none():
    mkt = [(f"d{i:03d}", 100 + i) for i in range(80)]
    ind = [(d, v * 2) for d, v in mkt]
    r = t.rrg(ind, mkt)
    assert (r["x"], r["y"], r["quadrant"]) == (100.0, 100.0, "領先")
    assert 1 <= len(r["trail"]) <= 8 and r["trail"][-1]["date"] == "d079"
    assert t.rrg(ind[:55], mkt[:55]) is None   # 不足 50-1+10 點

def test_rrg_outperformer_is_right_of_centre():
    mkt = [(f"d{i:03d}", 100.0) for i in range(80)]
    ind = [(d, 100.0 * 1.0005 ** (i * i)) for i, (d, _) in enumerate(mkt)]   # 加速走強
    r = t.rrg(ind, mkt)
    assert r["x"] > 100 and r["y"] > 100

def test_flow_totals_skip_missing():
    sums = {"A": {5: {"foreign": 1500, "trust": None}}, "B": {5: {"foreign": None, "trust": None}},
            "C": {5: {"foreign": 2500, "trust": 4000}}}
    assert t.flow_totals(sums, ["A", "B", "C", "D"], 5) == {"foreign_lots": 4, "trust_lots": 4, "count": 2}
    assert t.flow_totals(sums, ["B", "D"], 5) == {"foreign_lots": None, "trust_lots": None, "count": 0}

def test_key_str_and_series_sorted_and_skip_none():
    assert t.key_str("tier", "M02:Upstream") == "tier:M02:Upstream"
    rows = [{"scope_kind": "major", "scope_id": "M02", "trade_date": "2026-01-02", "level": 101.0},
            {"scope_kind": "major", "scope_id": "M02", "trade_date": "2026-01-01", "level": 100.0},
            {"scope_kind": "major", "scope_id": "M02", "trade_date": "2026-01-03", "level": None}]
    assert t.series_by_key(rows) == {"major:M02": [("2026-01-01", 100.0), ("2026-01-02", 101.0)]}
