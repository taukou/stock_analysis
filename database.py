import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# 初始化 Supabase 連線
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

def get_all_industries():
    """獲取所有大產業清單（用於首頁選單）"""
    res = supabase.table("major_industries").select("*").execute()
    return res.data

def fetch_industry_chain(major_id):
    """獲取特定產業的所有節點（用於 D3 的初始大球）"""
    res = supabase.table("company_node_mapping") \
        .select("node_id, value_chain_nodes(node_name, position_type)") \
        .eq("value_chain_nodes.major_id", major_id) \
        .execute()
    return res.data

# --- 就是少了這一段，補上它就能修復錯誤 ---
def get_companies_by_node(node_id):
    """根據節點 ID 抓取該節點下的所有公司（用於點擊後炸出小球）"""
    res = supabase.table("company_node_mapping") \
        .select("""
            companies(company_name, market_type, has_cb),
            value_chain_nodes(node_name)
        """) \
        .eq("node_id", node_id) \
        .execute()
    return res.data