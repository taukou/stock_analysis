import os
import threading

import httpx
from supabase import ClientOptions, create_client
from dotenv import load_dotenv

load_dotenv()

_local = threading.local()
# 網站讀取逾時（秒）：預設 120 秒會讓網路卡住時佔滿所有 worker；逾時就改回快取的舊快照
READ_TIMEOUT = 15


def get_client():
    """延遲建立 Supabase 連線（匯入模組時不需要網路或 .env）。

    每個執行緒各用一個 client：共用的 httpx HTTP/2 連線在閒置後被多執行緒同時重用，
    會間歇出現 ReadError（WinError 10035），所以不跨執行緒共用。
    """
    client = getattr(_local, "client", None)
    if client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("請確認 .env 檔案中包含 SUPABASE_URL 與 SUPABASE_KEY")
        client = _local.client = create_client(
            url, key, options=ClientOptions(postgrest_client_timeout=READ_TIMEOUT))
    return client


_TRANSIENT = (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError,
              httpx.ReadTimeout, httpx.PoolTimeout)


def run_query(query):
    """執行查詢；暫時性連線錯誤（ReadError／RemoteProtocolError／ConnectError／ReadTimeout／PoolTimeout，讀取可安全重送）只重試一次。"""
    try:
        return query.execute()
    except _TRANSIENT:
        return query.execute()


def get_all_industries():
    """獲取所有大產業清單（用於首頁選單）"""
    res = run_query(get_client().table("major_industries").select("*"))
    return res.data


def fetch_industry_nodes(major_id):
    """獲取特定產業的所有節點（含沒有公司的節點），依 display_order 排序"""
    res = run_query(get_client().table("value_chain_nodes")
           .select("node_id, node_name, position_type, display_order")
           .eq("major_id", major_id)
           .order("display_order"))
    return res.data


def get_node_companies(node_id):
    """根據節點 ID 抓取該節點下的所有公司（用於點擊後炸出小球）"""
    res = run_query(get_client().table("company_node_mapping")
           .select("stock_id, companies(company_name, latest_price, latest_change)")
           .eq("node_id", node_id))
    return res.data


def get_company_analysis(company_id):
    """根據 stock_id 或公司名稱抓取公司分析資料（基本資訊 + 成長動能 + 籌碼面）"""
    try:
        # company_id 可能是 stock_id（數字）或 company_name（中文）
        # 先嘗試按 stock_id 查詢
        basic_res = run_query(get_client().table("companies") \
            .select("*") \
            .eq("stock_id", company_id) \
            .limit(1))
        
        # 如果沒找到，嘗試按 company_name 查詢
        if not basic_res.data or len(basic_res.data) == 0:
            basic_res = run_query(get_client().table("companies") \
                .select("*") \
                .eq("company_name", company_id) \
                .limit(1))
        
        if not basic_res.data or len(basic_res.data) == 0:
            print(f"❌ Company not found: {company_id}")
            return None
        
        basic = basic_res.data[0]
        stock_id = basic.get("stock_id")
        
        if not stock_id:
            print(f"⚠️ {company_id} 沒有 stock_id")
            return None
        
        # 2. 獲取成長動能（最新月份資料）
        growth_res = run_query(get_client().table("growth_momentum") \
            .select("*") \
            .eq("stock_id", stock_id) \
            .order("data_month", desc=True) \
            .limit(1))
        
        growth = growth_res.data[0] if growth_res.data else None
        
        # 3. 獲取籌碼面資訊（最新交易日資料）
        smart_money_res = run_query(get_client().table("smart_money_flow") \
            .select("*") \
            .eq("stock_id", stock_id) \
            .order("trade_date", desc=True) \
            .limit(1))
        
        smart_money = smart_money_res.data[0] if smart_money_res.data else None
        
        return {
            "success": True,
            "basic": {
                "company_name": basic.get("company_name"),
                "stock_id": basic.get("stock_id"),
                "market_type": basic.get("market_type", "上市"),
                "latest_price": basic.get("latest_price"),
                "latest_change": basic.get("latest_change")
            },
            "growth": {
                "data_month": growth.get("data_month"),
                "yoy_pct": growth.get("yoy_pct"),
                "mom_pct": growth.get("mom_pct"),
                "acc_yoy_pct": growth.get("acc_yoy_pct")
            } if growth else None,
            "smart_money": {
                "trade_date": smart_money.get("trade_date"),
                "trust_net": smart_money.get("trust_net"),
                "foreign_net": smart_money.get("foreign_net")
            } if smart_money else None
        }
    except Exception as e:
        print(f"❌ Error fetching company analysis for {company_id}: {e}")
        return None

# ---------------------------------------------------------------------------
# 趨勢讀取層（全部使用匿名 client，只讀）
# ---------------------------------------------------------------------------

def fetch_all(build, page: int = 1000) -> list[dict]:
    """分頁讀完整個查詢：build() 每次回傳新的 query builder，讀到不足一頁為止。"""
    rows: list = []
    start = 0
    while True:
        data = run_query(build().range(start, start + page - 1)).data or []
        rows.extend(data)
        if len(data) < page:
            return rows
        start += page


def chunks(ids: list[str], size: int = 150) -> list[list[str]]:
    """把代號清單切成固定大小的批次（避免 in_ 條件過長）。"""
    return [ids[i:i + size] for i in range(0, len(ids), size)]


def fetch_all_company_ids() -> list[str]:
    rows = fetch_all(lambda: get_client().table("companies")
                     .select("stock_id").order("stock_id"))
    return [r["stock_id"] for r in rows]


def _fetch_by_ids(table: str, columns: str, ids: list[str], date_col: str, since: str) -> list[dict]:
    rows: list[dict] = []
    for batch in chunks(ids):
        rows.extend(fetch_all(lambda b=batch: get_client().table(table)
                              .select(columns)
                              .in_("stock_id", b)
                              .gte(date_col, since)
                              .order(date_col)
                              .order("stock_id")))
    return rows


def fetch_quotes_since(ids: list[str], since: str) -> list[dict]:
    return _fetch_by_ids("daily_quotes",
                         "stock_id, trade_date, market, close, change_pct, volume",
                         ids, "trade_date", since)


def fetch_ex_rights_since(ids: list[str], since: str) -> list[dict]:
    return _fetch_by_ids("ex_rights",
                         "stock_id, ex_date, kind, prev_close, ref_price, total_value",
                         ids, "ex_date", since)


def fetch_flows_since(ids: list[str], since: str) -> list[dict]:
    return _fetch_by_ids("smart_money_flow",
                         "stock_id, trade_date, trust_net, foreign_net",
                         ids, "trade_date", since)


def fetch_revenue_since(ids: list[str], since_month: str) -> list[dict]:
    return _fetch_by_ids("growth_momentum",
                         "stock_id, data_month, revenue, yoy_pct",
                         ids, "data_month", since_month)


def fetch_sync_runs(limit: int = 50) -> list[dict]:
    res = run_query(get_client().table("sync_runs")
           .select("id, dataset, status, last_date, rows, message, finished_at")
           .order("finished_at", desc=True)
           .limit(limit))
    return res.data or []


def fetch_major_node_companies(major_id) -> list[dict]:
    """該大產業所有節點的公司對應：[{node_id, stock_id}]。"""
    node_ids = [n["node_id"] for n in fetch_industry_nodes(major_id)]
    if not node_ids:
        return []
    return fetch_all(lambda: get_client().table("company_node_mapping")
                     .select("node_id, stock_id")
                     .in_("node_id", node_ids)
                     .order("node_id").order("stock_id"))


def _first_node(mapping) -> tuple:
    """取嵌入的 company_node_mapping 中 node_id 最小的一筆 (node_id, major_id)。

    嵌入結果沒有固定順序，一家公司屬於多個節點時要排序才穩定。
    """
    if not mapping:
        return None, None
    first = min(mapping, key=lambda m: m.get("node_id") or "")
    node = first.get("value_chain_nodes") or {}
    if isinstance(node, list):
        node = node[0] if node else {}
    return first.get("node_id"), node.get("major_id")


def fetch_companies(ids: list[str]) -> list[dict]:
    rows: list[dict] = []
    for batch in chunks(ids):
        res = run_query(get_client().table("companies")
               .select("stock_id, company_name, market_type, latest_price, latest_change, "
                       "company_node_mapping(node_id, value_chain_nodes(major_id))")
               .in_("stock_id", batch))
        for r in res.data or []:
            node_id, major_id = _first_node(r.pop("company_node_mapping", None))
            r["node_id"], r["major_id"] = node_id, major_id
            rows.append(r)
    return rows


def search_companies(q: str, limit: int = 20) -> list[dict]:
    """代號前綴或名稱包含（不分大小寫）；先移除 PostgREST 篩選語法的特殊字元與 ILIKE 萬用字元。"""
    for ch in ',()*%\\"_':
        q = q.replace(ch, "")
    q = q.strip()
    if not q:
        return []
    res = run_query(get_client().table("companies")
           .select("stock_id, company_name, company_node_mapping(node_id, value_chain_nodes(major_id))")
           .or_(f"stock_id.ilike.{q}*,company_name.ilike.*{q}*")
           .order("stock_id")
           .limit(limit))
    out = []
    for r in res.data or []:
        node_id, major_id = _first_node(r.get("company_node_mapping"))
        out.append({"stock_id": r["stock_id"], "company_name": r["company_name"],
                    "node_id": node_id, "major_id": major_id})
    return out


def fetch_industry_links(major_id) -> list[dict]:
    """兩端都屬於該大產業節點的產業鏈連線：[{from, to}]。"""
    node_ids = {n["node_id"] for n in fetch_industry_nodes(major_id)}
    if not node_ids:
        return []
    rows = fetch_all(lambda: get_client().table("industry_links")
                     .select("link_id, from_node_id, to_node_id")
                     .in_("from_node_id", list(node_ids))
                     .order("link_id"))
    return [{"from": r["from_node_id"], "to": r["to_node_id"]}
            for r in rows if r["to_node_id"] in node_ids]
