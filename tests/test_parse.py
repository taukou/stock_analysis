from datetime import date

from sync.parse import (
    change_pct,
    date_to_roc_month,
    months_back,
    parse_number,
    parse_twse_sign,
    roc_to_date,
)


def test_parse_number_missing_is_none():
    for raw in [None, "", "--", "—", "-", "X", "不適用", "無"]:
        assert parse_number(raw) is None


def test_parse_number_values():
    assert parse_number("29,796,590") == 29796590
    assert parse_number(" -1,231.50 ") == -1231.5
    assert parse_number("0") == 0
    assert parse_number("+0.24") == 0.24
    assert parse_number("+1,200") == 1200


def test_roc_to_date_formats():
    assert roc_to_date("115/10/22") == date(2026, 10, 22)
    assert roc_to_date("1151022") == date(2026, 10, 22)
    assert roc_to_date("115年07月01日") == date(2026, 7, 1)


def test_date_to_roc_month():
    assert date_to_roc_month(date(2026, 9, 1)) == "115/09"


def test_parse_twse_sign():
    assert parse_twse_sign("<p style= color:green>-</p>") == -1
    assert parse_twse_sign("<p style ='color:red'>+</p>") == 1
    assert parse_twse_sign("X") is None and parse_twse_sign("") is None


def test_change_pct():
    assert change_pct(-35.0, 2385.0) == -1.45
    assert change_pct(None, 10.0) is None and change_pct(1.0, None) is None


def test_months_back_crosses_year_boundaries():
    assert months_back(date(2026, 1, 15), 14) == "113/11"
    assert months_back(date(2026, 12, 10), 14) == "114/10"
    assert months_back(date(2026, 10, 26), 14) == "114/08"
