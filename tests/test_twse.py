from datetime import date

from sync.models import ExRight, InstFlow, Quote
from sync.parse import parse_number
from sync.sources.twse import parse_ex_rights, parse_institutional, parse_quotes
from tests.helpers import load

D = date(2026, 10, 22)


def quotes():
    return {x.stock_id: x for x in parse_quotes(load("twse_mi_index.json"), D)}


def test_parse_twse_quotes_2330():
    q = quotes()["2330"]
    assert (q.market, q.close, q.change, q.volume) == ("上市", 2385.0, -35.0, 29796590)
    assert q.change_pct == -1.45 and q.name == "台積電"
    assert (q.open, q.high, q.low, q.trade_date) == (2435.0, 2435.0, 2385.0, D)


def test_parse_twse_quotes_no_trade_is_none():
    q = quotes()["1341"]
    assert q.close is None and q.open is None
    assert q.change is None and q.change_pct is None


def test_parse_twse_quotes_ex_dividend_x_is_none():
    q = quotes()["0056"]
    assert q.close == 56.3
    assert q.change is None and q.change_pct is None


def test_parse_twse_quotes_holiday_empty():
    assert parse_quotes(load("twse_mi_index_holiday.json"), date(2026, 10, 23)) == []


def test_quote_to_row_excludes_name_and_iso_date():
    row = quotes()["2330"].to_row()
    assert "name" not in row
    assert row["trade_date"] == "2026-10-22"
    assert set(row) == {"stock_id", "trade_date", "market", "open", "high", "low",
                        "close", "change", "change_pct", "volume"}


def test_parse_twse_institutional_columns():
    f = {x.stock_id: x for x in parse_institutional(load("twse_t86.json"), D)}["1101"]
    assert (f.foreign_net, f.trust_net, f.dealer_net) == (25549325, 4726000, 3083688)
    assert f.total_net == 33359013
    assert f.total_net == parse_number("33,359,013")
    assert f.to_row() == {"stock_id": "1101", "trade_date": "2026-10-22",
                          "foreign_net": 25549325, "trust_net": 4726000,
                          "dealer_net": 3083688, "total_net": 33359013}


def test_parse_twse_ex_rights():
    e = next(x for x in parse_ex_rights(load("twse_twt49u.json")) if x.stock_id == "1101")
    assert (e.ex_date, e.kind, e.prev_close, e.ref_price, e.total_value) == (
        date(2026, 7, 1), "除息", 24.05, 23.25, 0.8)
    assert e.to_row()["ex_date"] == "2026-07-01"


def test_parse_twse_ex_rights_kind_rights():
    kinds = {x.kind for x in parse_ex_rights(load("twse_twt49u.json"))}
    assert kinds <= {"除息", "除權", "除權息"} and "除權" in kinds


def test_parse_ex_rights_empty_payload():
    assert parse_ex_rights({"stat": "很抱歉，沒有符合條件的資料!"}) == []


def test_parse_twse_quotes_flat_blank_sign_is_zero():
    payload = {"tables": [{"fields": ["證券代號"] + ["f"] * 15, "data": [
        ["1234 ", "某股 ", "1,000", "1", "1", "10.00", "10.00", "10.00", "10.00",
         "<p> </p>", "0.00", "10.00", "1", "10.05", "1", "0.00"]]}]}
    q = parse_quotes(payload, D)[0]
    assert q.stock_id == "1234" and q.change == 0 and q.change_pct == 0
