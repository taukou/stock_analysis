from flask import Flask, render_template, jsonify
from database import fetch_industry_chain, get_companies_by_node, get_all_industries, supabase 

app = Flask(__name__)

# ==========================================
# 網頁頁面路由 (Page Routes)
# ==========================================

@app.route('/')
def home():
    """首頁：渲染大產業選單"""
    return render_template('home.html', industries=get_all_industries())

@app.route('/industry/<major_id>')
def industry_view(major_id):
    """主戰情室網頁：渲染 D3.js 畫布"""
    return render_template('industry_d3.html', major_id=major_id)

@app.route('/shader-test')
def shader_test():
    """Shader 測試頁面"""
    return render_template('shader_test.html')


# ==========================================
# API 數據接口 (JSON Endpoints)
# ==========================================

@app.route('/api/industry_nodes/<major_id>')
def api_industry_nodes(major_id):
    """獲取特定產業的所有節點（D3 的初始大球）"""
    raw_data = fetch_industry_chain(major_id)
    nodes_summary = {}
    for item in raw_data:
        n_id = item['node_id']
        if n_id not in nodes_summary:
            nodes_summary[n_id] = {
                "id": n_id,
                "name": item['value_chain_nodes']['node_name'],
                "group": item['value_chain_nodes']['position_type'], 
                "type": "industry"
            }
    return jsonify(list(nodes_summary.values()))

@app.route('/api/node_companies/<node_id>')
def api_node_companies(node_id):
    """根據節點 ID 炸出該節點下的所有個股小球"""
    data = get_companies_by_node(node_id)
    companies = []
    for item in data:
        if not item.get('companies'):
            continue
        c = item['companies']
        # id 綁定純數字 stock_id，確保 D3 點擊時傳送給分析 API 的代號 100% 正確
        companies.append({
            "id": c['stock_id'], 
            "name": c['company_name'],
            "price": c.get('latest_price', '--'),     
            "change": c.get('latest_change', 0),      
            "has_cb": c.get('has_cb', False),
            "type": "company"
        })
    return jsonify(companies)

# ==========================================
# 💡 核心優化：深度分析 API (智慧歷史回溯版)
# ==========================================
@app.route('/api/company_analysis/<stock_id>')
def get_company_analysis(stock_id):
    try:
        # 1. 撈取基本資料與即時行情
        basic_res = supabase.table("companies").select("*").eq("stock_id", stock_id).single().execute()
        
        # 2. 💡 智慧營收：不硬撞當月，按月份降序(desc)排序，抓取已公告的最新一筆月份營收
        growth_res = supabase.table("growth_momentum")\
            .select("data_month, yoy_pct, mom_pct, acc_yoy_pct")\
            .eq("stock_id", stock_id)\
            .order("data_month", desc=True)\
            .limit(1).execute()
            
        # 3. 💡 智慧籌碼：不綁死今天，按交易日降序(desc)排序，自動抓取最近一個「真實開盤日」的法人數據
        money_res = supabase.table("smart_money_flow")\
            .select("trade_date, trust_net, foreign_net, total_net")\
            .eq("stock_id", stock_id)\
            .order("trade_date", desc=True)\
            .limit(1).execute()

        # 打包回傳，若新表完全沒資料，growth 或 smart_money 欄位會自動封裝為 None
        return jsonify({
            "success": True,
            "basic": basic_res.data,
            "growth": growth_res.data[0] if growth_res.data else None,
            "smart_money": money_res.data[0] if money_res.data else None
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# 確保主程式入口留在最底部
if __name__ == '__main__':
    app.run(debug=True)