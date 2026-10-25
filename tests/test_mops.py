from sync.models import Revenue
from sync.sources.mops import parse_revenue
from tests.helpers import FIXTURES


def fixture_html() -> str:
    return FIXTURES.joinpath("mops_sii_115_9.html").read_bytes().decode("cp950")


def test_parse_revenue_2330():
    r = {x.stock_id: x for x in parse_revenue(fixture_html(), 115, 9)}["2330"]
    assert (r.data_month, r.revenue, r.mom_pct, r.yoy_pct, r.acc_yoy_pct) == (
        "115/09", 511857399, -0.57, 54.64, 41.10)


def test_parse_revenue_ignores_header_and_total_rows():
    html = fixture_html()
    assert "合計" in html  # fixture 確實含合計列
    out = parse_revenue(html, 115, 9)
    assert len(out) == 3
    assert all(x.stock_id.isdigit() for x in out)


def test_parse_revenue_missing_pct_is_none():
    html = (
        "<table><tr align=right><td align=center>9999</td><td>測試</td>"
        "<td nowrap>&nbsp;   1,000</td><td nowrap>0</td><td nowrap>0</td>"
        "<td nowrap>N/A</td><Td nowrap>&nbsp;</Td><td nowrap>5</td>"
        "<td nowrap>1</td><td nowrap>-3.50</td><td>-</td></tr></table>"
    )
    r = parse_revenue(html, 115, 9)[0]
    assert r == Revenue("9999", "115/09", 1000, None, None, -3.5)
