"""櫃買中心「產業價值鏈資訊平台」(ic.tpex.org.tw) 產業頁解析：節點（含上中下游）與各節點的台灣掛牌公司。"""

import html as html_lib
import re
from dataclasses import dataclass, field

from sync import http

URL = "https://ic.tpex.org.tw/introduce.php?ic={code}"

# 平台的分層標題 → 本專案的 position_type；不認得的標題依出現順序決定
TIER_NAMES = {
    "上游": "Upstream", "中游": "Midstream", "下游": "Downstream",
    # 人工智慧頁由下往上排：運算資源 → 核心技術 → 應用與服務
    "運算資源": "Upstream", "核心技術": "Midstream", "應用與服務": "Downstream",
}
TIER_BY_COUNT = {1: ["Midstream"], 2: ["Upstream", "Downstream"],
                 3: ["Upstream", "Midstream", "Downstream"]}
TIER_SUFFIX = {"Upstream": "(上)", "Midstream": "(中)", "Downstream": "(下)"}

# 只收在台灣交易所掛牌的區塊（創櫃不交易、知名外國企業沒有代號）
LISTED_SECTIONS = re.compile(r"(本國|外國)(上市|上櫃|興櫃)公司")
SECTION_RE = re.compile(r"(本國|外國)?(上市|上櫃|興櫃|創櫃)公司|知名外國企業")

_TITLE_RE = re.compile(r'class="chain-title-panel"[^>]*>(.*?)</div>', re.S)
_NODE_RE = re.compile(r'<div id="ic_link_(\w+)"[^>]*>(.*?)</div>', re.S)
_LIST_RE = re.compile(r'<div id="companyList_(\w+)"(.*?)<span class="company-number">', re.S)
_TOKEN_RE = re.compile(r'<b>(.*?)</b>|<a href="company_basic\.php\?stk_code=(\w+)"[^>]*title="([^"]*)"', re.S)
_SPAN_RE = re.compile(r"<span\b.*?</span>", re.S)
_TAG_RE = re.compile(r"<[^>]*>")
_STOCK_ID_RE = re.compile(r"\d{4}")


@dataclass(frozen=True)
class ChainNode:
    code: str
    name: str
    tier: str


@dataclass(frozen=True)
class ChainCompany:
    stock_id: str
    name: str


@dataclass
class Chain:
    nodes: list[ChainNode]
    companies: dict[str, list[ChainCompany]] = field(default_factory=dict)


def _text(s: str) -> str:
    return re.sub(r"\s+", "", html_lib.unescape(_TAG_RE.sub("", s)))


def _node_name(raw: str) -> str:
    """去掉灰色小字註解（<span>…</span>）與換行標籤。"""
    return _text(_SPAN_RE.sub("", raw))


def _tiers(titles: list[str]) -> list[str]:
    by_count = TIER_BY_COUNT.get(len(titles), TIER_BY_COUNT[3])
    return [TIER_NAMES.get(t, by_count[min(i, len(by_count) - 1)]) for i, t in enumerate(titles)]


def parse_chain(page: str) -> Chain:
    """解析產業頁。公司清單在頁面中出現兩次（第二份在 <noscript>），只取第一份。"""
    first_list = page.find('id="companyList_')
    panel = page[:first_list] if first_list >= 0 else page

    titles = [(m.start(), _text(m.group(1))) for m in _TITLE_RE.finditer(panel)]
    tiers = _tiers([t for _, t in titles])
    nodes, seen = [], set()
    for m in _NODE_RE.finditer(panel):
        if m.group(1) in seen:
            continue
        seen.add(m.group(1))
        idx = sum(1 for pos, _ in titles if pos < m.start()) - 1
        tier = tiers[idx] if idx >= 0 else "Midstream"
        nodes.append(ChainNode(m.group(1), _node_name(m.group(2)), tier))
    if not nodes:
        raise ValueError("找不到任何產業節點（版面可能變更）")

    # 同名節點（如半導體的兩個「生產製程及檢測設備」）加上分層字尾區分
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n.name] = counts.get(n.name, 0) + 1
    nodes = [ChainNode(n.code, n.name + TIER_SUFFIX[n.tier], n.tier) if counts[n.name] > 1 else n
             for n in nodes]

    companies: dict[str, list[ChainCompany]] = {}
    for m in _LIST_RE.finditer(page):
        code = m.group(1)
        if code in companies:
            continue
        section, out, ids = "", [], set()
        for tok in _TOKEN_RE.finditer(m.group(2)):
            if tok.group(1) is not None:
                head = _text(tok.group(1))
                if SECTION_RE.match(head):
                    section = head
                continue
            sid = tok.group(2)
            if LISTED_SECTIONS.match(section) and _STOCK_ID_RE.fullmatch(sid) and sid not in ids:
                ids.add(sid)
                out.append(ChainCompany(sid, html_lib.unescape(tok.group(3)).strip()))
        companies[code] = out
    return Chain(nodes, companies)


def fetch_chain(code: str) -> Chain:
    url = URL.format(code=code)
    page = http.get_text(url, "utf-8")
    if page is None:
        raise http.SourceError(f"找不到產業頁 {url}")
    return http.parse_with(url, parse_chain, page)
