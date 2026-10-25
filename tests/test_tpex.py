from datetime import date

from sync.models import ExRight, InstFlow
from sync.sources.tpex import (
    parse_emerging,
    parse_ex_rights,
    parse_institutional,
    parse_quotes,
)
from tests.helpers import load

D = date(2026, 10, 22)


def quotes():
    return {x.stock_id: x for x in parse_quotes(load("tpex_daily.json"), D)}


def test_parse_tpex_quotes():
    q = quotes()["6488"]
    assert (q.market, q.close, q.change, q.volume) == ("上櫃", 826.0, -54.0, 10520541)
    assert (q.open, q.high, q.low, q.trade_date, q.name) == (896.0, 898.0, 815.0, D, "環球晶")
    assert q.change_pct == -6.14


def test_parse_tpex_quotes_signs_and_trailing_space():
    qs = quotes()
    assert qs["006201"].change == -1.69
    assert qs["3293"].change == 5.0 and qs["3293"].market == "上櫃"


def test_parse_tpex_quotes_ex_dividend_text_is_none():
    q = quotes()["00719B"]
    assert q.close == 31.49 and q.open == 31.41
    assert q.change is None and q.change_pct is None


def test_parse_tpex_quotes_no_close_is_none():
    q = quotes()["2073"]
    assert q.close is None and q.open is None and q.high is None and q.low is None
    assert q.change is None and q.change_pct is None and q.volume == 0


def test_parse_tpex_quotes_holiday_empty():
    assert parse_quotes(load("tpex_daily_holiday.json"), date(2026, 10, 23)) == []


def test_parse_tpex_institutional_columns():
    r = {x.stock_id: x for x in parse_institutional(load("tpex_insti.json"), D)}
    assert r["6488"] == InstFlow("6488", D, -2099506, -204000, -284922, -2588428)
    assert r["3293"] == InstFlow("3293", D, 633770, 11000, 6597, 651367)


def test_parse_tpex_institutional_holiday_empty():
    assert parse_institutional({"tables": []}, D) == []


def test_parse_tpex_ex_rights():
    r = {x.stock_id: x for x in parse_ex_rights(load("tpex_ex.json"))}
    assert r["2230"] == ExRight("2230", date(2026, 7, 1), "除息", 25.55, 24.94, 0.608951)


def test_parse_emerging():
    q = {x.stock_id: x for x in parse_emerging(load("tpex_esb.json"))}["1260"]
    assert (q.market, q.trade_date, q.close) == ("興櫃", date(2026, 10, 22), 32.0)
    assert (q.change, q.change_pct, q.open, q.volume) == (0.33, 1.04, None, 43300)
    assert q.name == "富味鄉"


def test_parse_emerging_missing_price_is_none():
    row = dict(load("tpex_esb.json")[0], LatestPrice="", Highest="")
    q = parse_emerging([row])[0]
    assert q.close is None and q.change is None and q.change_pct is None
