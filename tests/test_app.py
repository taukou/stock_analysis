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


def test_node_companies_missing_price_is_null(client, monkeypatch):
    rows = [
        {"stock_id": "2330", "companies": {"company_name": "台積電", "latest_price": None, "latest_change": None}},
        {"stock_id": "2317", "companies": {"company_name": "鴻海", "latest_price": 100.5, "latest_change": 0}},
        {"stock_id": "9999", "companies": None},
    ]
    monkeypatch.setattr(app_module, "get_node_companies", lambda node_id: rows)
    res = client.get("/api/node_companies/n1")
    assert res.status_code == 200
    data = res.get_json()
    assert data[0] == {"id": "c_2330", "name": "台積電", "type": "company", "price": None, "change": None}
    assert data[1]["price"] == 100.5 and data[1]["change"] == 0
    assert len(data) == 2  # 缺 companies 的列略過


def test_industry_page_escapes_major_id(client, monkeypatch):
    res = client.get("/industry/semi")
    assert res.status_code == 200
    assert 'const majorId = "semi";' in res.get_data(as_text=True)
