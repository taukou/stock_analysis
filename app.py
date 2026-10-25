from flask import Flask, render_template, jsonify
from database import fetch_industry_nodes, get_node_companies, get_all_industries, get_company_analysis

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
    nodes = [
        {
            "id": row["node_id"],
            "name": row["node_name"],
            "group": row["position_type"],
            "type": "industry",
        }
        for row in fetch_industry_nodes(major_id)
    ]
    return jsonify(nodes)

@app.route('/api/node_companies/<node_id>')
def api_node_companies(node_id):
    """獲取節點下的公司；price/change 缺值時回 null"""
    companies = []
    for item in get_node_companies(node_id):
        c = item.get('companies')
        if not c:
            continue
        companies.append({
            "id": f"c_{item['stock_id']}",
            "name": c['company_name'],
            "type": "company",
            "price": c.get('latest_price'),
            "change": c.get('latest_change')
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