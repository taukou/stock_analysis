from flask import Flask, render_template, jsonify
from database import fetch_industry_chain, get_companies_by_node, get_all_industries, get_company_analysis, supabase 

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
    # 這裡要確保 select 裡面有包含最新股價的欄位
    # 根據你的 ER 圖，欄位是 latest_price 和 latest_change
    res = supabase.table("company_node_mapping") \
        .select("stock_id, companies(company_name, latest_price, latest_change)") \
        .eq("node_id", node_id) \
        .execute()

    companies = []
    for item in res.data:
        c = item['companies']
        # --- 關鍵對齊處 ---
        companies.append({
            "id": f"c_{item['stock_id']}",
            "name": c['company_name'],
            "type": "company",
            # 將資料庫的 latest_price 對應到前端的 price
            "price": c.get('latest_price') if c.get('latest_price') is not None else "---",
            # 將資料庫的 latest_change 對應到前端的 change
            "change": c.get('latest_change') if c.get('latest_change') is not None else 0
        })
    
    return jsonify(companies)

@app.route('/api/company_analysis/<company_id>')
def api_company_analysis(company_id):
    """獲取公司分析資料（company_id 去掉 c_ 前綴後查詢 stock_id）"""
    # company_id format: c_4919, remove the 'c_' prefix
    lookup_id = company_id.replace('c_', '', 1) if company_id.startswith('c_') else company_id
    result = get_company_analysis(lookup_id)
    
    if result is None:
        return jsonify({"success": False, "error": "Company not found"}), 404
    
    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)