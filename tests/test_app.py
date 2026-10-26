from datetime import date

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_industry_nodes_shape(client, monkeypatch):
    rows = [
        {"node_id": "n1", "node_name": "晶圓代工", "position_type": "Midstream", "display_order": 1},
        {"node_id": "n2", "node_name": "封測", "position_type": "Downstream", "display_order": 2},
        {"node_id": "n3", "node_name": "無公司節點", "position_type": "Upstream", "display_order": 3},
    ]
    monkeypatch.setattr(app_module, "fetch_industry_nodes", lambda major_id: rows)
    res = client.get("/api/industry_nodes/semi")
    assert res.status_code == 200
    assert res.get_json() == [
        {"id": "n1", "name": "晶圓代工", "group": "Midstream", "type": "industry"},
        {"id": "n2", "name": "封測", "group": "Downstream", "type": "industry"},
        {"id": "n3", "name": "無公司節點", "group": "Upstream", "type": "industry"},
    ]


SNAP = {"dates": ["2026-10-22"], "latest_date": "2026-10-22",
        "returns": {"2330": {1: -1.45, 5: 2.0, 20: None}},
        "ex": {"2330": {1: None, 5: "除息", 20: "除息"}},
        "signals": {"2330": [{"code": "volume_spike", "label": "爆量", "detail": "x"}]}}


class FakeCache:
    def __init__(self, snap=SNAP, err=None):
        self.snap, self.err = snap, err

    def get(self):
        if self.err:
            raise self.err
        return self.snap


def test_node_companies_uses_period(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache())
    monkeypatch.setattr(app_module, "get_node_companies", lambda n: [
        {"stock_id": "2330", "companies": {"company_name": "台積電", "latest_price": 2385, "latest_change": -1.45}},
        {"stock_id": "6999", "companies": {"company_name": "無快照", "latest_price": None, "latest_change": None}}])
    d = client.get("/api/node_companies/N201?period=5").get_json()
    assert d[0] == {"id": "c_2330", "name": "台積電", "type": "company", "price": 2385,
                    "change": 2.0, "ex": "除息", "signals": SNAP["signals"]["2330"]}
    assert d[1]["change"] is None and d[1]["ex"] is None and d[1]["signals"] == []


def test_bad_period_400(client):
    res = client.get("/api/node_companies/N201?period=7")
    assert res.status_code == 400
    assert res.get_json() == {"error": "period 只能是 1、5、20"}


def test_snapshot_down_503(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache(err=RuntimeError("down")))
    monkeypatch.setattr(app_module, "get_node_companies", lambda n: [])
    res = client.get("/api/node_companies/N201")
    assert res.status_code == 503
    assert res.get_json() == {"error": "資料暫時無法讀取"}


def test_industry_heat(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache())
    monkeypatch.setattr(app_module, "fetch_industry_nodes", lambda m: [{"node_id": "N201"}, {"node_id": "N999"}])
    monkeypatch.setattr(app_module, "fetch_major_node_companies", lambda m: [
        {"node_id": "N201", "stock_id": "2330"}, {"node_id": "N201", "stock_id": "6999"}])
    assert client.get("/api/industry_heat/M01?period=1").get_json() == [
        {"node_id": "N201", "avg_change": -1.45, "count": 1},
        {"node_id": "N999", "avg_change": None, "count": 0}]


def test_company_trends_rejects_bad_id(client):
    assert client.get("/api/company_trends/23;30").status_code == 400
    assert client.get("/api/company_trends/2330%0A").status_code == 400


def test_company_trends_shape(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache())
    seen = {}

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 26)

    monkeypatch.setattr(app_module, "date", FixedDate)

    def quotes(ids, since):
        seen["quotes"] = since
        return [{"trade_date": "2026-10-22", "close": None, "volume": 5},
                {"trade_date": "2026-10-21", "close": 2400, "volume": 9}]

    def flows(ids, since):
        return [{"trade_date": "2026-10-22", "trust_net": 12345, "foreign_net": -1500},
                {"trade_date": "2026-10-21", "trust_net": None, "foreign_net": 0}]

    def revenue(ids, since):
        seen["revenue"] = since
        return [{"data_month": "115/09", "revenue": 100, "yoy_pct": None},
                {"data_month": "115/08", "revenue": 90, "yoy_pct": 5.5}]

    def ex(ids, since):
        return [{"ex_date": "2026-01-05", "kind": "息", "ref_price": 99, "prev_close": 100, "total_value": 1},
                {"ex_date": "2026-07-05", "kind": "息", "ref_price": 98, "prev_close": 100, "total_value": 2}]

    monkeypatch.setattr(app_module, "fetch_quotes_since", quotes)
    monkeypatch.setattr(app_module, "fetch_flows_since", flows)
    monkeypatch.setattr(app_module, "fetch_revenue_since", revenue)
    monkeypatch.setattr(app_module, "fetch_ex_rights_since", ex)
    d = client.get("/api/company_trends/2330").get_json()
    assert d["stock_id"] == "2330"
    assert d["returns"] == {"1": -1.45, "5": 2.0, "20": None}
    assert [q["date"] for q in d["quotes"]] == ["2026-10-21", "2026-10-22"]
    assert d["quotes"][1]["close"] is None
    assert [f["date"] for f in d["flows"]] == ["2026-10-21", "2026-10-22"]
    assert d["flows"][0]["trust_lots"] is None and d["flows"][0]["foreign_lots"] == 0
    assert d["flows"][1]["trust_lots"] == 12 and d["flows"][1]["foreign_lots"] == -1
    assert [r["month"] for r in d["revenue"]] == ["115/08", "115/09"]
    assert d["revenue"][1]["yoy_pct"] is None
    assert [e["ex_date"] for e in d["ex_rights"]] == ["2026-07-05", "2026-01-05"]
    assert d["signals"] == SNAP["signals"]["2330"]
    assert seen["quotes"] == "2026-07-18" and seen["revenue"] == "114/08"


def test_company_trends_unknown_stock_returns_null(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache())
    for name in ("fetch_quotes_since", "fetch_flows_since", "fetch_revenue_since", "fetch_ex_rights_since"):
        monkeypatch.setattr(app_module, name, lambda ids, since: [])
    d = client.get("/api/company_trends/9999").get_json()
    assert d["returns"] == {"1": None, "5": None, "20": None} and d["signals"] == []


def test_companies_ids_validation(client):
    assert client.get("/api/companies?ids=2330,abc!").status_code == 400
    too_many = ",".join(str(1000 + i) for i in range(51))
    assert client.get(f"/api/companies?ids={too_many}").status_code == 400


def test_companies_passthrough(client, monkeypatch):
    monkeypatch.setattr(app_module, "fetch_companies", lambda ids: [{"stock_id": i} for i in ids])
    assert client.get("/api/companies?ids=2330,3105").get_json() == [{"stock_id": "2330"}, {"stock_id": "3105"}]


def test_search_passthrough(client, monkeypatch):
    monkeypatch.setattr(app_module, "search_companies", lambda q: [{"stock_id": "2330"}] if q == "台積" else [])
    assert client.get("/api/search?q=台積").get_json() == [{"stock_id": "2330"}]


def test_freshness_and_links_passthrough(client, monkeypatch):
    monkeypatch.setattr(app_module, "fetch_sync_runs", lambda: [])
    monkeypatch.setattr(app_module, "freshness", lambda rows, now: {"ok": rows == [] and now is not None})
    monkeypatch.setattr(app_module, "fetch_industry_links", lambda m: [{"from": "a", "to": "b"}])
    assert client.get("/api/freshness").get_json() == {"ok": True}
    assert client.get("/api/industry_links/M01").get_json() == [{"from": "a", "to": "b"}]


def test_node_companies_missing_price_is_null(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache({"returns": {}, "ex": {}, "signals": {}}))
    rows = [
        {"stock_id": "2330", "companies": {"company_name": "台積電", "latest_price": None, "latest_change": None}},
        {"stock_id": "2317", "companies": {"company_name": "鴻海", "latest_price": 100.5, "latest_change": 0}},
        {"stock_id": "9999", "companies": None},
    ]
    monkeypatch.setattr(app_module, "get_node_companies", lambda node_id: rows)
    res = client.get("/api/node_companies/n1")
    assert res.status_code == 200
    data = res.get_json()
    assert data[0] == {"id": "c_2330", "name": "台積電", "type": "company", "price": None,
                       "change": None, "ex": None, "signals": []}
    assert data[1]["price"] == 100.5 and data[1]["change"] is None
    assert len(data) == 2  # 缺 companies 的列略過


def test_industry_page_escapes_major_id(client, monkeypatch):
    res = client.get("/industry/semi")
    assert res.status_code == 200
    assert 'const majorId = "semi";' in res.get_data(as_text=True)


def test_industry_page_has_trend_containers(client):
    html = client.get("/industry/M01").get_data(as_text=True)
    for needle in ('id="sb-chart-price"', 'id="sb-chart-yoy"', 'id="sb-chart-flow"',
                   'id="sb-signals"', 'id="sb-ex-list"', 'id="sb-star"', '/static/js/charts.js'):
        assert needle in html


def test_industry_page_has_period_switch(client):
    html = client.get("/industry/M01").get_data(as_text=True)
    assert 'id="period-switch"' in html
    for p in (1, 5, 20):
        assert f'data-period="{p}"' in html
