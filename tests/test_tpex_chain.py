import pytest

from sync.sources.tpex_chain import ChainCompany, ChainNode, parse_chain
from tests.helpers import FIXTURES


def chain():
    return parse_chain((FIXTURES / "tpex_chain.html").read_text(encoding="utf-8"))


def test_nodes_names_and_tiers():
    assert chain().nodes == [
        ChainNode("X100", "電阻器材料", "Upstream"),          # 去掉灰色註解
        ChainNode("X200", "生產製程及檢測設備(上)", "Upstream"),  # 同名加分層字尾
        ChainNode("X300", "生產製程及檢測設備(下)", "Downstream"),  # 空白標題依順序判斷
        ChainNode("X400", "IC&模組", "Downstream"),
    ]


def test_companies_only_listed_in_taiwan_and_deduped():
    cos = chain().companies
    assert cos["X100"] == [ChainCompany("2327", "國巨"), ChainCompany("4741", "泓瀚"),
                           ChainCompany("6890", "來億-KY")]
    assert cos["X300"] == [ChainCompany("3131", "弘塑")]   # 6 碼代號不收


def test_noscript_copy_ignored_and_missing_list_absent():
    cos = chain().companies
    assert "9999" not in {c.stock_id for v in cos.values() for c in v}
    assert "X200" not in cos


def test_tier_names_for_ai_page():
    page = ('<div class="chain-title-panel">應用與服務</div><div id="ic_link_A1" class="x">系統整合</div>'
            '<div class="chain-title-panel">運算資源</div><div id="ic_link_A2" class="x">雲端平台</div>')
    assert [n.tier for n in parse_chain(page).nodes] == ["Downstream", "Upstream"]


def test_no_tier_titles_means_midstream():
    page = '<div id="ic_link_R1" class="x">系統整合服務</div>'
    assert parse_chain(page).nodes == [ChainNode("R1", "系統整合服務", "Midstream")]


def test_layout_change_raises():
    with pytest.raises(ValueError):
        parse_chain("<html>改版了</html>")
