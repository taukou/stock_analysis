from datetime import date

import pytest

from sync import http
from sync.sources import mops, tpex, twse


def test_twse_fetch_urls(monkeypatch):
    urls = []
    monkeypatch.setattr(http, "get_json", lambda u: urls.append(u) or {})
    assert twse.fetch_quotes(date(2026, 10, 22)) == []
    assert twse.fetch_institutional(date(2026, 10, 22)) == []
    assert twse.fetch_ex_rights(date(2026, 7, 1), date(2026, 7, 31)) == []
    assert "date=20261022" in urls[0] and "type=ALLBUT0999" in urls[0]
    assert "T86?date=20261022&selectType=ALL" in urls[1]
    assert "startDate=20260701&endDate=20260731" in urls[2]


def test_tpex_fetch_urls(monkeypatch):
    urls = []
    monkeypatch.setattr(http, "get_json", lambda u: urls.append(u) or ([] if "openapi" in u else {}))
    assert tpex.fetch_quotes(date(2026, 10, 22)) == []
    assert tpex.fetch_institutional(date(2026, 10, 22)) == []
    assert tpex.fetch_ex_rights(date(2026, 7, 1), date(2026, 7, 31)) == []
    assert tpex.fetch_emerging() == []
    assert "date=2026/10/22" in urls[0]
    assert "type=Daily&sect=AL&date=2026/10/22" in urls[1]
    assert "startDate=2026/07/01&endDate=2026/07/31" in urls[2]
    assert urls[3].endswith("tpex_esb_latest_statistics")


def test_parser_error_wrapped(monkeypatch):
    bad = {"data": [["only one"]]}
    monkeypatch.setattr(http, "get_json", lambda u: bad)
    with pytest.raises(http.SourceError) as e:
        twse.fetch_institutional(date(2026, 10, 22))
    assert "T86" in str(e.value)
    assert isinstance(e.value.__cause__, IndexError)


def test_mops_404_empty_and_url(monkeypatch):
    seen = []
    monkeypatch.setattr(http, "get_text", lambda u, enc: seen.append((u, enc)) or None)
    assert mops.fetch_revenue(115, 9, "sii") == []
    assert seen == [("https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_115_9_0.html", "cp950")]
