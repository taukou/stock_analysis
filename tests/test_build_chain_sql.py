import pytest

import build_chain_sql as b
from sync.sources.tpex_chain import Chain, ChainCompany, ChainNode


def legacy_chain():
    nodes = [ChainNode(code, f"n{code}", "Upstream") for code in b.LEGACY_NODES["M01"]]
    return Chain(nodes, {"D100": [ChainCompany("2330", "台積電"), ChainCompany("1111", "下市了")]})


def new_chain():
    return Chain([ChainNode("J100", "電阻器材料", "Upstream"), ChainNode("J200", "電容器材料", "Upstream"),
                  ChainNode("J500", "O'Brien 電阻", "Midstream")],
                 {"J100": [ChainCompany("2327", "國巨舊名")], "J500": [ChainCompany("2327", "國巨"),
                                                                   ChainCompany("6890", "來億")]})


@pytest.fixture
def chains(monkeypatch):
    monkeypatch.setattr(b, "INDUSTRIES", [("M01", "D000", "半導體"), ("M05", "J000", "被動元件")])
    return {"M01": legacy_chain(), "M05": new_chain()}


OFFICIAL = {"2330": ("台積電", "上市"), "2327": ("國巨*", "上市"), "6890": ("來億-KY", "興櫃")}


def test_node_ids_per_tier():
    rows = b.node_rows("M05", new_chain())
    assert [r[:5] for r in rows] == [("M05U01", "M05", "電阻器材料", "Upstream", 1),
                                     ("M05U02", "M05", "電容器材料", "Upstream", 2),
                                     ("M05M01", "M05", "O'Brien 電阻", "Midstream", 3)]


def test_legacy_nodes_keep_ids_and_unknown_node_fails():
    assert b.node_rows("M01", legacy_chain())[1][0] == "N102"
    bad = Chain([ChainNode("DZ00", "新節點", "Upstream")])
    with pytest.raises(ValueError):
        b.node_rows("M01", bad)


def test_build_sql_contents(chains):
    sql, report = b.build(chains, OFFICIAL, existing_companies={"2330"},
                          existing_pairs={("N102", "2330")})
    assert "('M05', '被動元件'" in sql
    assert "('M05M01', 'M05', 'O''Brien 電阻', 'Midstream', 3)" in sql   # 單引號跳脫
    assert "('2327', '國巨*', '上市', false)" in sql                     # 名稱與市場取官方
    assert "('M05U01', '2327')" in sql and "('N102', '2330')" in sql
    assert "1111" not in sql                                             # 不在行情中的略過
    assert "('M01'," not in sql and "('N102', 'M01'" not in sql          # 半導體不改大產業與節點
    assert "delete" not in sql.lower() and "on commit" not in sql
    assert "drop table if exists pg_temp._majors" in sql
    assert "from value_chain_nodes with no data" in sql   # 暫存表沿用目標欄位型別
    assert sql.count("do $import$") == 1 and sql.rstrip().endswith("$import$;")
    assert "begin;" not in sql and "commit;" not in sql and "$import$" not in sql.split("do $import$")[1][:-12]
    assert report[0] == "M01 半導體：12 個節點、1 家公司（新公司 0、新對應 0）"
    assert "1111 下市了" in report[1]
    assert report[2] == "M05 被動元件：3 個節點、2 家公司（新公司 2、新對應 3）"


def test_report_lists_mappings_dropped_by_platform(chains):
    _, report = b.build(chains, OFFICIAL, set(), {("N102", "2330"), ("N303", "3037")})
    assert any("平台已沒列" in line and "N303/3037" in line for line in report)
