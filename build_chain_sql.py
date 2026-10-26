"""從櫃買中心產業價值鏈平台抓產業節點與公司，產生可在 Supabase SQL Editor 執行的 SQL（本程式不寫資料庫）。

SQL 只會新增或更新，不刪除：既有公司、節點對應與手動維護的供應關係線（industry_links）都保留。
可重複執行；重跑會補上平台新列入的公司。
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

import database
from audit_stock_ids import latest_official
from sync.logsetup import setup_logging
from sync.sources.tpex_chain import Chain, fetch_chain

ROOT = Path(__file__).resolve().parent
SQL_PATH = ROOT / "db" / "004_tpex_chains.sql"
REPORT_PATH = ROOT / "reports" / "chain_import.txt"
log = logging.getLogger("build_chain_sql")

# (major_id, 平台產業代碼, 名稱)；M02–M06 原本是沒有節點的佔位產業，直接沿用代號
INDUSTRIES = [
    ("M01", "D000", "半導體"),
    ("M02", "F000", "電腦及週邊設備"),
    ("M03", "I000", "通信網路"),
    ("M04", "L000", "印刷電路板"),
    ("M05", "J000", "被動元件"),
    ("M06", "K000", "連接器"),
    ("M07", "G000", "平面顯示器"),
    ("M08", "H000", "觸控面板"),
    ("M09", "A200", "LED照明"),
    ("M10", "5300", "人工智慧"),
    ("M11", "R000", "軟體服務"),
]

# 既有半導體節點：沿用原本的 node_id、名稱與排序（供應關係線指向這些 id），只補公司
LEGACY_NODES = {
    "M01": {"DC00": "N101", "D100": "N102", "D300": "N201", "D400": "N202", "D200": "N203",
            "D500": "N204", "D900": "N301", "D600": "N302", "D700": "N303", "D800": "N304",
            "DA00": "N305", "DB00": "N306"},
}
TIER_LETTER = {"Upstream": "U", "Midstream": "M", "Downstream": "D"}


def q(v) -> str:
    """SQL 字串常值。"""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _values(rows: list[tuple]) -> str:
    return ",\n  ".join("(" + ", ".join(q(v) for v in r) + ")" for r in rows)


def node_rows(major_id: str, chain: Chain) -> list[tuple]:
    """(node_id, major_id, node_name, position_type, display_order, 平台節點代碼)。"""
    legacy = LEGACY_NODES.get(major_id)
    out, seq = [], {}
    for order, n in enumerate(chain.nodes, start=1):
        if legacy is not None:
            if n.code not in legacy:
                raise ValueError(f"{major_id} 出現未對應的平台節點 {n.code} {n.name}")
            node_id = legacy[n.code]
        else:
            letter = TIER_LETTER[n.tier]
            seq[letter] = seq.get(letter, 0) + 1
            node_id = f"{major_id}{letter}{seq[letter]:02d}"
        out.append((node_id, major_id, n.name, n.tier, order, n.code))
    return out


def build(chains: dict[str, Chain], official: dict[str, tuple[str, str]],
          existing_companies: set[str], existing_pairs: set[tuple[str, str]]) -> tuple[str, list[str]]:
    """回傳 (SQL, 報告行)。chains 以 major_id 為鍵。"""
    majors, nodes, companies, pairs = [], [], {}, []
    report: list[str] = []
    for major_id, code, name in INDUSTRIES:
        chain = chains[major_id]
        rows = node_rows(major_id, chain)
        if major_id not in LEGACY_NODES:
            majors.append((major_id, name, f"資料來源：櫃買中心產業價值鏈資訊平台（{code}）"))
            nodes.extend(r[:5] for r in rows)
        node_of = {r[5]: r[0] for r in rows}
        ids, skipped = set(), set()
        new_pairs = 0
        for ncode, cos in chain.companies.items():
            if ncode not in node_of:
                continue
            for c in cos:
                if c.stock_id not in official:
                    skipped.add(f"{c.stock_id} {c.name}")
                    continue
                ids.add(c.stock_id)
                off_name, market = official[c.stock_id]
                companies.setdefault(c.stock_id, (c.stock_id, off_name, market, False))
                pair = (node_of[ncode], c.stock_id)
                pairs.append(pair)
                new_pairs += pair not in existing_pairs
        new_cos = len(ids - existing_companies)
        report.append(f"{major_id} {name}：{len(rows)} 個節點、{len(ids)} 家公司"
                      f"（新公司 {new_cos}、新對應 {new_pairs}）")
        if skipped:
            report.append(f"  略過（目前不在上市櫃／興櫃行情中）：{'、'.join(sorted(skipped))}")
        existing_here = {p for p in existing_pairs if p[0] in node_of.values()}
        gone = sorted(existing_here - set(pairs))
        if gone:
            report.append(f"  資料庫有、平台已沒列（保留不刪）：{len(gone)} 筆，例如 "
                          + "、".join(f"{n}/{s}" for n, s in gone[:10]))

    pairs = sorted(set(pairs))
    company_rows = sorted(companies.values())
    sql = f"""-- 由 build_chain_sql.py 於 {datetime.now():%Y-%m-%d %H:%M} 產生；資料來源：https://ic.tpex.org.tw
-- 只新增／更新、不刪除，可重複執行。請整份貼到 Supabase SQL Editor 執行。
begin;

-- 暫存表直接複製目標表的欄位型別（例如 position_type 是 enum），值寫進來時就轉好型別
create temp table _majors on commit drop as
  select major_id, major_name, description from major_industries with no data;
create temp table _nodes on commit drop as
  select node_id, major_id, node_name, position_type, display_order from value_chain_nodes with no data;
create temp table _companies on commit drop as
  select stock_id, company_name, market_type, has_cb from companies with no data;
create temp table _pairs on commit drop as
  select node_id, stock_id from company_node_mapping with no data;

-- 1. 大產業（沿用 M02–M06 佔位代號並改名）
insert into _majors (major_id, major_name, description) values
  {_values(majors)};

update major_industries m set major_name = v.major_name, description = v.description
from _majors v where m.major_id = v.major_id;

insert into major_industries (major_id, major_name, description)
select v.major_id, v.major_name, v.description from _majors v
where not exists (select 1 from major_industries m where m.major_id = v.major_id);

-- 2. 產業節點
insert into _nodes (node_id, major_id, node_name, position_type, display_order) values
  {_values(nodes)};

update value_chain_nodes n set node_name = v.node_name, position_type = v.position_type,
       display_order = v.display_order
from _nodes v where n.node_id = v.node_id;

insert into value_chain_nodes (node_id, major_id, node_name, position_type, display_order)
select v.node_id, v.major_id, v.node_name, v.position_type, v.display_order from _nodes v
where not exists (select 1 from value_chain_nodes n where n.node_id = v.node_id);

-- 3. 公司（名稱與市場取自交易所最新行情；已存在的公司不更動）
insert into _companies (stock_id, company_name, market_type, has_cb) values
  {_values(company_rows)};

insert into companies (stock_id, company_name, market_type, has_cb)
select v.stock_id, v.company_name, v.market_type, v.has_cb from _companies v
where not exists (select 1 from companies c where c.stock_id = v.stock_id);

-- 4. 節點與公司對應
insert into _pairs (node_id, stock_id) values
  {_values(pairs)};

insert into company_node_mapping (node_id, stock_id)
select v.node_id, v.stock_id from _pairs v
where not exists (select 1 from company_node_mapping m
                  where m.node_id = v.node_id and m.stock_id = v.stock_id);

-- 5. 新公司的最新股價（歷史行情原本就已整個市場同步）
select refresh_company_latest();

commit;
"""
    return sql, report


def main() -> int:
    setup_logging("build_chain_sql", base_dir=ROOT)
    official = latest_official(datetime.now())
    if official is None:
        log.error("找不到近 7 天內上市與上櫃皆有資料的交易日")
        return 1
    chains = {}
    for major_id, code, name in INDUSTRIES:
        log.info("抓取 %s %s (%s)", major_id, name, code)
        chains[major_id] = fetch_chain(code)
    existing_companies = set(database.fetch_all_company_ids())
    existing_pairs = {(r["node_id"], r["stock_id"]) for r in database.fetch_all(
        lambda: database.get_client().table("company_node_mapping")
        .select("node_id, stock_id").order("node_id").order("stock_id"))}
    sql, report = build(chains, official, existing_companies, existing_pairs)
    SQL_PATH.write_text(sql, encoding="utf-8")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(f"SQL: {SQL_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
