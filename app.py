import math
import re
from datetime import date, datetime, timedelta

from flask import Flask, render_template, jsonify, request

from database import (
    fetch_companies, fetch_ex_rights_since, fetch_flows_since, fetch_industry_links,
    fetch_industry_nodes, fetch_major_node_companies, fetch_quotes_since,
    fetch_revenue_since, fetch_sync_runs, get_all_industries, get_company_analysis,
    get_node_companies, search_companies,
)
from freshness import freshness
from snapshot import snapshot_cache
from sync.parse import months_back

STOCK_ID_RE = re.compile(r"^[0-9A-Z]{4,6}$")
MAX_COMPANY_IDS = 50

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

class ApiError(Exception):
    """API 層的可預期錯誤，轉成 JSON 錯誤回應。"""

    def __init__(self, message, status):
        super().__init__(message)
        self.message, self.status = message, status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify({"error": err.message}), err.status


def parse_period():
    """解析 period 參數（只接受 1、5、20，預設 1）。"""
    raw = request.args.get("period", "1")
    if raw not in ("1", "5", "20"):
        raise ApiError("period 只能是 1、5、20", 400)
    return int(raw)


def get_snapshot_or_503():
    """讀快照；失敗回 503。"""
    try:
        return snapshot_cache.get()
    except Exception:
        app.logger.exception("快照讀取失敗")
        raise ApiError("資料暫時無法讀取", 503)


def check_stock_id(stock_id):
    if not STOCK_ID_RE.fullmatch(stock_id):
        raise ApiError("股票代號格式錯誤", 400)


def snap_value(snap, section, stock_id, period):
    """取快照 section[stock_id][period]；缺漏回 None。"""
    return (snap.get(section) or {}).get(stock_id, {}).get(period)


@app.route('/api/node_companies/<node_id>')
def api_node_companies(node_id):
    """獲取節點下的公司；change 為區間漲跌幅（快照），缺值回 null"""
    period = parse_period()
    snap = get_snapshot_or_503()
    companies = []
    for item in get_node_companies(node_id):
        c = item.get('companies')
        if not c:
            continue
        sid = item['stock_id']
        companies.append({
            "id": f"c_{sid}",
            "name": c['company_name'],
            "type": "company",
            "price": c.get('latest_price'),
            "change": snap_value(snap, "returns", sid, period),
            "ex": snap_value(snap, "ex", sid, period),
            "signals": (snap.get("signals") or {}).get(sid, []),
        })
    return jsonify(companies)


@app.route('/api/industry_heat/<major_id>')
def api_industry_heat(major_id):
    """各節點的區間平均漲跌幅；無資料的節點 avg_change 為 null、count 為 0"""
    period = parse_period()
    snap = get_snapshot_or_503()
    by_node = {}
    for row in fetch_major_node_companies(major_id):
        by_node.setdefault(row["node_id"], []).append(row["stock_id"])
    result = []
    for node in fetch_industry_nodes(major_id):
        nid = node["node_id"]
        vals = [v for v in (snap_value(snap, "returns", sid, period) for sid in by_node.get(nid, []))
                if v is not None]
        result.append({"node_id": nid,
                       "avg_change": round(sum(vals) / len(vals), 2) if vals else None,
                       "count": len(vals)})
    return jsonify(result)


def to_lots(shares):
    """股 → 張（四捨五入）；缺值保留 None。"""
    return None if shares is None else int(math.floor(shares / 1000 + 0.5))


@app.route('/api/company_trends/<stock_id>')
def api_company_trends(stock_id):
    """個股趨勢：區間漲跌（快照）、近 60 日收盤量、近 12 月營收、近 20 日法人、近一年除權息"""
    check_stock_id(stock_id)
    snap = get_snapshot_or_503()
    today = date.today()
    ids = [stock_id]
    since_100d = (today - timedelta(days=100)).isoformat()
    quotes = sorted(fetch_quotes_since(ids, since_100d), key=lambda r: r["trade_date"])[-60:]
    flows = sorted(fetch_flows_since(ids, since_100d), key=lambda r: r["trade_date"])[-20:]
    revenue = sorted(fetch_revenue_since(ids, months_back(today, 14)),
                     key=lambda r: r["data_month"])[-12:]
    ex_since = (today - timedelta(days=365)).isoformat()
    ex_rows = sorted((r for r in fetch_ex_rights_since(ids, ex_since) if r["ex_date"] >= ex_since),
                     key=lambda r: r["ex_date"], reverse=True)
    return jsonify({
        "stock_id": stock_id,
        "returns": {str(p): snap_value(snap, "returns", stock_id, p) for p in (1, 5, 20)},
        "quotes": [{"date": r["trade_date"], "close": r.get("close"), "volume": r.get("volume")}
                   for r in quotes],
        "revenue": [{"month": r["data_month"], "revenue": r.get("revenue"), "yoy_pct": r.get("yoy_pct")}
                    for r in revenue],
        "flows": [{"date": r["trade_date"], "trust_lots": to_lots(r.get("trust_net")),
                   "foreign_lots": to_lots(r.get("foreign_net"))} for r in flows],
        "ex_rights": [{"ex_date": r["ex_date"], "kind": r.get("kind"), "ref_price": r.get("ref_price"),
                       "prev_close": r.get("prev_close"), "total_value": r.get("total_value")}
                      for r in ex_rows],
        "signals": (snap.get("signals") or {}).get(stock_id, []),
    })


@app.route('/api/freshness')
def api_freshness():
    return jsonify(freshness(fetch_sync_runs(), datetime.now()))


@app.route('/api/search')
def api_search():
    return jsonify(search_companies(request.args.get("q", "")))


@app.route('/api/companies')
def api_companies():
    ids = [i for i in request.args.get("ids", "").split(",") if i]
    if len(ids) > MAX_COMPANY_IDS:
        raise ApiError(f"最多 {MAX_COMPANY_IDS} 個代號", 400)
    for i in ids:
        check_stock_id(i)
    return jsonify(fetch_companies(ids) if ids else [])


@app.route('/api/industry_links/<major_id>')
def api_industry_links(major_id):
    return jsonify(fetch_industry_links(major_id))

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
    import sys
    import serve
    sys.exit(serve.main())