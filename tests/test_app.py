from datetime import date, timedelta

import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture(autouse=True)
def no_industry_names(monkeypatch):
    # 產業頁會讀產業名稱；測試不連資料庫
    monkeypatch.setattr(app_module, "get_all_industries", lambda: [])


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
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache(snap={}))
    monkeypatch.setattr(app_module, "fetch_companies", lambda ids: [{"stock_id": i} for i in ids])
    assert client.get("/api/companies?ids=2330,3105").get_json() == [
        {"stock_id": "2330", "signals": [], "ex_today": None}, {"stock_id": "3105", "signals": [], "ex_today": None}]


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


def test_pages_have_freshness_and_search(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_all_industries", lambda: [])
    for path in ("/", "/industry/M01"):
        html = client.get(path).get_data(as_text=True)
        assert 'id="freshness"' in html
        assert "/static/js/common.js" in html
        assert 'type="search"' in html
    assert 'id="watchlist"' in client.get("/").get_data(as_text=True)


def test_home_has_nav_tabs_and_no_view_industries_button(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_all_industries", lambda: [])
    html = client.get("/").get_data(as_text=True)
    for label, href in [("首頁", "#top"), ("自選股", "#watchlist"), ("產業列表", "#industries")]:
        assert f'href="{href}"' in html and f">{label}</a>" in html
    assert "查看產業" not in html
    assert 'id="top"' in html


def test_industry_page_shows_industry_name(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_all_industries",
                        lambda: [{"major_id": "M02", "major_name": "電腦及週邊設備"}])
    html = client.get("/industry/M02").get_data(as_text=True)
    assert "<strong>電腦及週邊設備</strong>" in html
    assert "<strong>M09</strong>" in client.get("/industry/M09").get_data(as_text=True)


def test_industry_page_survives_name_lookup_failure(client, monkeypatch):
    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(app_module, "get_all_industries", boom)
    res = client.get("/industry/M03")
    assert res.status_code == 200 and "<strong>M03</strong>" in res.get_data(as_text=True)


# ===== 趨勢 API =====
def _pts(n, start=100.0, step=1.0, end_date="2026-10-22"):
    from datetime import timedelta
    d0 = date.fromisoformat(end_date)
    return [((d0 - timedelta(days=n - 1 - i)).isoformat(), start + step * i) for i in range(n)]


def _index(series=None, **kw):
    base = {"series": series or {}, "first_date": {k: v[0][0] for k, v in (series or {}).items()},
            "changed": set(), "members": {}, "mapping": []}
    base.update(kw)
    return base


def _patch_index(monkeypatch, idx=None, err=None):
    monkeypatch.setattr(app_module, "index_cache", FakeCache(snap=idx, err=err))


def test_index_series_rebases_and_reports_first_date(client, monkeypatch):
    pts = _pts(30, 200.0, 2.0)
    _patch_index(monkeypatch, _index({"major:M02": pts}, changed={"major:M02"}))
    seen = {}

    def node_series(ids, since):
        seen["since"] = since
        return {"node:N1": _pts(5, 50.0, 5.0)}
    monkeypatch.setattr(app_module.index_data, "node_series", node_series)
    d = client.get("/api/index_series?keys=major:M02,node:N1&range=1M").get_json()
    assert d["series"]["major:M02"][0]["value"] == 100.0
    assert len(d["series"]["major:M02"]) == 22
    assert d["series"]["node:N1"][0]["value"] == 100.0
    assert d["first_date"]["major:M02"] == pts[0][0]
    assert d["changed"] == ["major:M02"]
    assert set(d["notes"]) == {"market", "survivor"}
    # 節點序列的 since 固定為 400 天前（與 load_index 同窗），不隨區間變動
    assert seen["since"] == (date.today() - timedelta(days=400)).isoformat()


def test_index_series_empty_table_is_200_with_empty_series(client, monkeypatch):
    _patch_index(monkeypatch, _index())
    d = client.get("/api/index_series?keys=major:M02").get_json()
    assert d["series"] == {"major:M02": []} and d["first_date"] == {"major:M02": None}


def test_index_series_rejects_bad_keys_and_range(client):
    for q in ["keys=foo", "keys=major:M02&range=2Y", "keys=" + ",".join(f"node:N{i}" for i in range(13))]:
        assert client.get(f"/api/index_series?{q}").status_code == 400


def test_index_series_503_when_load_fails(client, monkeypatch):
    _patch_index(monkeypatch, err=RuntimeError("no table"))
    res = client.get("/api/index_series?keys=major:M02")
    assert res.status_code == 503 and res.get_json() == {"error": "資料暫時無法讀取"}


def test_ranking_rows_and_market_with_note(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_all_industries",
                        lambda: [{"major_id": "M02", "major_name": "半導體"}])
    _patch_index(monkeypatch, _index({"major:M02": _pts(30, 100, 1), "market:TW": _pts(30, 100, 0.5)},
                                     members={("major", "M02"): frozenset({"2330", "2303"})}))
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache(snap={
        "flow_date": "2026-10-22",
        "flows": {"2330": {5: {"foreign": 3000, "trust": None}}, "2303": {5: {"foreign": 2000, "trust": 1000}}}}))
    d = client.get("/api/industry_ranking").get_json()
    r = d["rows"][0]
    assert r["major_id"] == "M02" and r["name"] == "半導體"
    assert r["r1"] is not None and r["r20"] is not None
    assert r["foreign5"] == 5 and r["trust5"] == 1 and r["flow_count"] == 2
    assert d["market"]["r5"] is not None and d["flow_date"] == "2026-10-22"
    assert "market" in d["notes"]


def test_rotation_omits_short_history(client, monkeypatch):
    monkeypatch.setattr(app_module, "get_all_industries", lambda: [
        {"major_id": "M02", "major_name": "半導體"}, {"major_id": "M03", "major_name": "短"}])
    _patch_index(monkeypatch, _index({"major:M02": _pts(120, 100, 0.3), "major:M03": _pts(10),
                                      "market:TW": _pts(120, 100, 0.2)}))
    d = client.get("/api/rotation").get_json()
    assert [p["major_id"] for p in d["points"]] == ["M02"]
    p = d["points"][0]
    assert p["quadrant"] in ("領先", "轉弱", "轉強", "落後") and p["trail"]
    assert d["as_of"] == "2026-10-22"


def test_node_flows_counts_only_present(client, monkeypatch):
    mapping = [{"major_id": "M02", "node_id": "N1", "stock_id": "2330", "position_type": "Upstream"},
               {"major_id": "M02", "node_id": "N1", "stock_id": "2303", "position_type": "Upstream"},
               {"major_id": "M09", "node_id": "N9", "stock_id": "1101", "position_type": "Upstream"}]
    _patch_index(monkeypatch, _index(mapping=mapping, members={
        ("node", "N1"): frozenset({"2330", "2303"}), ("node", "N9"): frozenset({"1101"})}))
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache(snap={
        "flow_date": "2026-10-22", "flows": {"2330": {5: {"foreign": 4000, "trust": 1000}}}}))
    d = client.get("/api/node_flows/M02?period=5").get_json()
    assert d["flow_date"] == "2026-10-22"
    assert d["nodes"] == [{"node_id": "N1", "foreign_lots": 4, "trust_lots": 1, "count": 1}]


# ===== 每日摘要頁 =====
def test_daily_page_renders_with_note(client, monkeypatch):
    from industry_trends import MARKET_NOTE
    snap = {"latest_date": "2026-10-22", "flow_date": "2026-10-22",
            "returns": {"2330": {1: 2.0}, "2303": {1: -1.0}},
            "flows": {"2330": {1: {"foreign": 1000, "trust": None}, 5: {"foreign": 5000, "trust": None}}},
            "signals": {"2330": [{"code": "trust_streak", "label": "投信連買 5 日", "detail": "x"}]}}
    idx = _index({"major:M01": _pts(5), "market:TW": _pts(5)},
                 members={("node", "N1"): frozenset({"2330", "2303"})},
                 mapping=[{"node_id": "N1", "stock_id": "2330", "major_id": "M01", "position_type": "Midstream"},
                          {"node_id": "N1", "stock_id": "2303", "major_id": "M01", "position_type": "Midstream"}])
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache(snap))
    _patch_index(monkeypatch, idx)
    monkeypatch.setattr(app_module, "get_all_industries", lambda: [{"major_id": "M01", "major_name": "半導體"}])
    monkeypatch.setattr(app_module, "fetch_industry_nodes", lambda m: [{"node_id": "N1", "node_name": "晶圓代工"}])
    monkeypatch.setattr(app_module, "fetch_companies", lambda ids: [{"stock_id": "2330", "company_name": "台積電"}])
    monkeypatch.setattr(app_module, "fetch_sync_runs", lambda: [])
    res = client.get("/daily")
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    assert MARKET_NOTE in html and "半導體" in html and "晶圓代工" in html and "台積電" in html
    assert "法人資料至 2026-10-22" in html
    assert "+5 張" in html and "+1 張" not in html and "近 5 日" in html   # 5 日合計（5000 股 = 5 張）
    from industry_trends import SURVIVOR_NOTE
    assert SURVIVOR_NOTE in html


def test_daily_page_shows_message_when_data_unavailable(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache(err=RuntimeError("down")))
    _patch_index(monkeypatch, err=RuntimeError("no table"))
    monkeypatch.setattr(app_module, "fetch_sync_runs", lambda: [])
    res = client.get("/daily")
    assert res.status_code == 200 and "資料暫時無法讀取" in res.get_data(as_text=True)


def test_home_has_ranking_and_rotation_sections(client):
    html = client.get("/").get_data(as_text=True)
    for label, href in [("產業排行", "#ranking"), ("輪動", "#rotation"), ("今日摘要", "/daily")]:
        assert f'href="{href}"' in html and f">{label}</a>" in html
    assert 'id="ranking"' in html and 'id="rotation"' in html
    from industry_trends import SURVIVOR_NOTE
    assert html.count(SURVIVOR_NOTE) == 2   # 排行表下、輪動圖下各一行（含錯誤／空狀態）


def test_companies_include_signals_and_ex_today(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache())
    monkeypatch.setattr(app_module, "fetch_companies", lambda ids: [{"stock_id": i} for i in ids])
    d = client.get("/api/companies?ids=2330,6999").get_json()
    assert d[0]["signals"] == SNAP["signals"]["2330"] and d[0]["ex_today"] is None
    assert d[1]["signals"] == [] and d[1]["ex_today"] is None


def test_companies_ex_today_value(client, monkeypatch):
    snap = {**SNAP, "ex": {"2330": {1: "除息", 5: "除息", 20: "除息"}}}
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache(snap))
    monkeypatch.setattr(app_module, "fetch_companies", lambda ids: [{"stock_id": i} for i in ids])
    assert client.get("/api/companies?ids=2330").get_json()[0]["ex_today"] == "除息"


def test_companies_still_ok_when_snapshot_fails(client, monkeypatch):
    monkeypatch.setattr(app_module, "snapshot_cache", FakeCache(err=RuntimeError("down")))
    monkeypatch.setattr(app_module, "fetch_companies", lambda ids: [{"stock_id": i, "latest_change": 1.0} for i in ids])
    res = client.get("/api/companies?ids=2330")
    assert res.status_code == 200
    assert res.get_json() == [{"stock_id": "2330", "latest_change": 1.0, "signals": [], "ex_today": None}]
