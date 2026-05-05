from flask import Flask, render_template, jsonify
from database import fetch_industry_chain, get_companies_by_node, get_all_industries, supabase

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('home.html', industries=get_all_industries())

# 這是主網頁，渲染 D3 畫布
@app.route('/industry/<major_id>')
def industry_view(major_id):
    return render_template('industry_d3.html', major_id=major_id)

# --- 以下是 API 接口，回傳 JSON ---

@app.route('/api/industry_nodes/<major_id>')
def api_industry_nodes(major_id):
    raw_data = fetch_industry_chain(major_id)
    nodes_summary = {}
    for item in raw_data:
        n_id = item['node_id']
        if n_id not in nodes_summary:
            # 關鍵點：這裡一定要抓到 position_type 並傳給 group
            nodes_summary[n_id] = {
                "id": n_id,
                "name": item['value_chain_nodes']['node_name'],
                "group": item['value_chain_nodes']['position_type'], # <--- 就是這一行
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
if __name__ == '__main__':
    app.run(debug=True)