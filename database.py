import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

_client = None


def get_client():
    """延遲建立 Supabase 連線（匯入模組時不需要網路或 .env）"""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("請確認 .env 檔案中包含 SUPABASE_URL 與 SUPABASE_KEY")
        _client = create_client(url, key)
    return _client


def get_all_industries():
    """獲取所有大產業清單（用於首頁選單）"""
    res = get_client().table("major_industries").select("*").execute()
    return res.data


def fetch_industry_nodes(major_id):
    """獲取特定產業的所有節點（含沒有公司的節點），依 display_order 排序"""
    res = get_client().table("value_chain_nodes")         .select("node_id, node_name, position_type, display_order")         .eq("major_id", major_id)         .order("display_order")         .execute()
    return res.data


def get_node_companies(node_id):
    """根據節點 ID 抓取該節點下的所有公司（用於點擊後炸出小球）"""
    res = get_client().table("company_node_mapping")         .select("stock_id, companies(company_name, latest_price, latest_change)")         .eq("node_id", node_id)         .execute()
    return res.data


def get_company_analysis(company_id):
    """根據 stock_id 或公司名稱抓取公司分析資料（基本資訊 + 成長動能 + 籌碼面）"""
    try:
        # company_id 可能是 stock_id（數字）或 company_name（中文）
        # 先嘗試按 stock_id 查詢
        basic_res = get_client().table("companies") \
            .select("*") \
            .eq("stock_id", company_id) \
            .limit(1) \
            .execute()
        
        # 如果沒找到，嘗試按 company_name 查詢
        if not basic_res.data or len(basic_res.data) == 0:
            basic_res = get_client().table("companies") \
                .select("*") \
                .eq("company_name", company_id) \
                .limit(1) \
                .execute()
        
        if not basic_res.data or len(basic_res.data) == 0:
            print(f"❌ Company not found: {company_id}")
            return None
        
        basic = basic_res.data[0]
        stock_id = basic.get("stock_id")
        
        if not stock_id:
            print(f"⚠️ {company_id} 沒有 stock_id")
            return None
        
        # 2. 獲取成長動能（最新月份資料）
        growth_res = get_client().table("growth_momentum") \
            .select("*") \
            .eq("stock_id", stock_id) \
            .order("data_month", desc=True) \
            .limit(1) \
            .execute()
        
        growth = growth_res.data[0] if growth_res.data else None
        
        # 3. 獲取籌碼面資訊（最新交易日資料）
        smart_money_res = get_client().table("smart_money_flow") \
            .select("*") \
            .eq("stock_id", stock_id) \
            .order("trade_date", desc=True) \
            .limit(1) \
            .execute()
        
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