import pytest

import industry_index as ix


def test_market_stock_filter():
    assert ix.is_market_stock("2330") and not ix.is_market_stock("0050")
    assert not ix.is_market_stock("00878") and not ix.is_market_stock("2330A")


def test_scope_members_groups_and_dedupes():
    m = [{"node_id": "N1", "stock_id": "1111", "major_id": "M02", "position_type": "Upstream"},
         {"node_id": "N2", "stock_id": "1111", "major_id": "M02", "position_type": "Downstream"},
         {"node_id": "N2", "stock_id": "2222", "major_id": "M02", "position_type": "Downstream"}]
    s = ix.scope_members(m)
    assert s[("major", "M02")] == frozenset({"1111", "2222"})
    assert s[("tier", "M02:Downstream")] == frozenset({"1111", "2222"})
    assert s[("node", "N1")] == frozenset({"1111"})
    assert ix.MARKET_KEY not in s


def test_returns_skip_missing_and_use_ref_price_on_ex_date():
    r = ix.stock_returns({"A": 100, "B": 50, "C": 10}, {"A": 110, "B": 45, "D": 5, "E": 9},
                         {"B": 40, "E": None})
    assert r == {"A": pytest.approx(0.1), "B": pytest.approx(0.125)}  # C 今天沒價、D 沒昨收、E 參考價缺 → 不納入


def test_average_excludes_missing_and_none_when_empty():
    assert ix.average_return({"1111": 0.1, "2222": -0.1}, {"1111", "2222", "3333"}) == (0.0, 2)
    assert ix.average_return({"1111": 0.1}, {"9999"}) == (None, 0)
    assert ix.average_return({"1111": 0.1, "0050": 0.5}, None) == (0.1, 1)   # 大盤排除 ETF


def test_steps_are_inverse_and_flat_on_none():
    assert ix.step_backward(ix.step_forward(100, 0.05), 0.05) == pytest.approx(100)
    assert ix.step_forward(100, None) == 100 and ix.step_backward(100, None) == 100


def test_hash_is_order_independent():
    assert ix.members_hash(frozenset({"2", "1"})) == ix.members_hash(frozenset({"1", "2"}))


def test_index_row_shape():
    assert ix.index_row(("node", "N1"), "2026-10-27", 101.23456789, 0.0123456, 3) == {
        "scope_kind": "node", "scope_id": "N1", "trade_date": "2026-10-27",
        "level": 101.234568, "ret_pct": 1.2346, "members": 3}
    assert ix.index_row(ix.MARKET_KEY, "2026-10-27", 100, None, 0)["ret_pct"] is None


def test_sql_is_single_do_block_with_rls():
    sql = (ix.ROOT / "db" / "006_industry_index.sql").read_text(encoding="utf-8")
    assert sql.count("do $idx$") == 1 and sql.rstrip().endswith("$idx$;")
    assert "industry_index_daily" in sql and "industry_index_scopes" in sql
    assert "anon_read" in sql and "enable row level security" in sql
    assert "begin;" not in sql and "commit;" not in sql and "delete" not in sql.lower()
