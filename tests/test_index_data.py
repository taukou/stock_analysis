from datetime import date

import database
import index_data
from industry_index import members_hash


def row(kind, sid, d, level):
    return {"scope_kind": kind, "scope_id": sid, "trade_date": d, "level": level, "ret_pct": None, "members": 3}

MAPPING = [
    {"node_id": "N1", "stock_id": "2330", "major_id": "M02", "position_type": "Upstream"},
    {"node_id": "N1", "stock_id": "2303", "major_id": "M02", "position_type": "Upstream"},
]

def patch(monkeypatch, rows, scopes, mapping=MAPPING):
    monkeypatch.setattr(database, "fetch_index_rows", lambda kinds, since, scope_ids=None: rows)
    monkeypatch.setattr(database, "fetch_index_scopes", lambda: scopes)
    monkeypatch.setattr(database, "fetch_chain_mapping", lambda: mapping)

def test_changed_detects_member_hash_difference(monkeypatch):
    good = members_hash(frozenset({"2330", "2303"}))
    scopes = [{"scope_kind": "major", "scope_id": "M02", "members_hash": good},
              {"scope_kind": "tier", "scope_id": "M02:Upstream", "members_hash": "old"},
              {"scope_kind": "market", "scope_id": "TW", "members_hash": "whatever"}]
    patch(monkeypatch, [], scopes)
    r = index_data.load_index(date(2026, 10, 27))
    assert r["changed"] == {"tier:M02:Upstream"}
    assert r["mapping"] == MAPPING and ("node", "N1") in r["members"]

def test_first_date_per_key(monkeypatch):
    rows = [row("major", "M02", "2026-01-03", 102.0), row("major", "M02", "2026-01-02", 101.0),
            row("market", "TW", "2026-01-05", 100.0)]
    patch(monkeypatch, rows, [])
    r = index_data.load_index(date(2026, 10, 27))
    assert r["first_date"] == {"major:M02": "2026-01-02", "market:TW": "2026-01-05"}
    assert r["series"]["major:M02"][0] == ("2026-01-02", 101.0)

def test_empty_tables_give_empty_series(monkeypatch):
    patch(monkeypatch, [], [], [])
    r = index_data.load_index(date(2026, 10, 27))
    assert r == {"series": {}, "first_date": {}, "changed": set(), "members": {}, "mapping": []}

def test_node_series_reads_node_kind(monkeypatch):
    seen = {}
    def fake(kinds, since, scope_ids=None):
        seen.update(kinds=kinds, ids=scope_ids)
        return [row("node", "N1", "2026-01-01", 100.0)]
    monkeypatch.setattr(database, "fetch_index_rows", fake)
    assert index_data.node_series(["N1"], "2026-01-01") == {"node:N1": [("2026-01-01", 100.0)]}
    assert seen == {"kinds": ["node"], "ids": ["N1"]}
    assert index_data.node_series([], "2026-01-01") == {}


def test_load_mapping_does_not_touch_index_tables(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no index table")
    monkeypatch.setattr(database, "fetch_index_rows", boom)
    monkeypatch.setattr(database, "fetch_index_scopes", boom)
    monkeypatch.setattr(database, "fetch_chain_mapping", lambda: MAPPING)
    r = index_data.load_mapping()
    assert r["mapping"] == MAPPING
    assert r["members"][("node", "N1")] == frozenset({"2330", "2303"})
