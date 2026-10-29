import pytest

import ai_scorecard as S

DAYS = [f"2026-10-{d:02d}" for d in (1, 2, 5, 6, 7, 8, 9, 12)]


def _series(vals):
    return list(zip(DAYS, vals))


def test_evaluate_horizons_excess_and_summary():
    series = {"market:TW": _series([100, 101, 102, 103, 104, 105, 106, 107]),
              "major:M01": _series([50, 50, 51, 52, 53, 54, 55, 56])}
    stocks = {"2330": {DAYS[1]: 10.0, DAYS[6]: 11.0, DAYS[7]: 12.0}}
    docs = [{"date": DAYS[0], "picks": [{"kind": "industry", "id": "M01", "name": "半導體", "major_id": "M01"}]},
            {"date": DAYS[1], "picks": [{"kind": "stock", "id": "2330", "name": "台積電", "major_id": "M01", "node_id": "N1"}]},
            {"date": DAYS[7], "picks": [{"kind": "stock", "id": "2330", "name": "台積電"}]},
            {"date": "2026-10-03", "picks": [{"kind": "stock", "id": "2330"}]}]          # 非交易日略過
    out = S.evaluate(docs, stocks, series)
    assert out["latest"] == DAYS[-1]
    assert [(r["date"], r["id"], r["days"]) for r in out["rows"]] == [(DAYS[7], "2330", 0), (DAYS[1], "2330", 6), (DAYS[0], "M01", 7)]
    today, stock, ind = out["rows"]
    assert today["ret"] == {}                                           # 當天推薦還沒有後續
    assert stock["ret"] == {5: 10.0, "now": 20.0}                       # 第 5 個交易日 = 10-09
    assert stock["market"][5] == pytest.approx(round((106 / 101 - 1) * 100, 2))
    assert stock["excess"][5] == pytest.approx(round(10.0 - stock["market"][5], 2))
    assert ind["ret"][5] == pytest.approx(round((54 / 50 - 1) * 100, 2)) and 20 not in ind["ret"]
    assert out["summary"][5]["count"] == 2 and out["summary"][5]["beat"] == 100
    assert 20 not in out["summary"]


def test_missing_prices_are_none_and_not_counted():
    series = {"market:TW": _series([100] * 8)}
    out = S.evaluate([{"date": DAYS[0], "picks": [{"kind": "stock", "id": "9999"}]}], {}, series)
    assert out["rows"][0]["ret"] == {5: None, "now": None} and out["summary"] == {}
    assert S.evaluate([], {}, {})["latest"] is None


def test_stock_levels_adjusts_for_ex_rights():
    quotes = [{"stock_id": "A", "trade_date": DAYS[0], "close": 100}, {"stock_id": "A", "trade_date": DAYS[1], "close": 95}]
    ex = [{"stock_id": "A", "ex_date": DAYS[1], "prev_close": 100, "ref_price": 95}]
    assert S.stock_levels(quotes, ex) == {"A": {DAYS[0]: 95.0, DAYS[1]: 95}}   # 除息不算下跌
