from flask import Flask, render_template, jsonify
from database import fetch_industry_chain, get_companies_by_node, get_all_industries

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
    data = get_companies_by_node(node_id)
    companies = []
    for item in data:
        c = item['companies']
        companies.append({
            "id": f"c_{c['company_name']}",
            "name": c['company_name'],
            "has_cb": c.get('has_cb', False),
            "type": "company"
        })
    return jsonify(companies)

if __name__ == '__main__':
    app.run(debug=True)