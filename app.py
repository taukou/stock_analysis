import re
from datetime import date, datetime, timedelta

from flask import Flask, render_template, jsonify, request

from database import (
    fetch_companies, fetch_ex_rights_since, fetch_flows_since, fetch_industry_links,
    fetch_industry_nodes, fetch_major_node_companies, fetch_node_names, fetch_quotes_since,
    fetch_revenue_since, fetch_sync_runs, get_all_industries, get_company_analysis,
    get_node_companies, search_companies,
)
import ai_picks
from freshness import freshness
import index_data
from index_data import index_cache, mapping_cache
from industry_trends import (
    MARKET_NOTE, RANGES, SURVIVOR_NOTE, daily_digest, flow_totals, key_str, period_change, rebase, rrg, to_lots,
)
from snapshot import snapshot_cache
from sync.parse import months_back

STOCK_ID_RE = re.compile(r"^[0-9A-Z]{4,6}$")
MAX_COMPANY_IDS = 50
MAX_INDEX_KEYS = 12
INDEX_KEY_RE = re.compile(r"^(market|major|tier|node):[0-9A-Za-z_:\-]{1,40}$")
NOTES = {"market": MARKET_NOTE, "survivor": SURVIVOR_NOTE}

app = Flask(__name__)

# ==========================================
# 網頁頁面路由 (Page Routes)
# ==========================================

@app.route('/')
def home():
    """首頁：渲染大產業選單"""
    return render_template('home.html', industries=get_all_industries(), SURVIVOR_NOTE=SURVIVOR_NOTE)

@app.route('/industry/<major_id>')
def industry_view(major_id):
    """主戰情室網頁：渲染 D3.js 畫布"""
    try:
        names = {m["major_id"]: m["major_name"] for m in get_all_industries()}
    except Exception:
        app.logger.exception("讀取產業名稱失敗，改顯示代號")
        names = {}
    return render_template('industry_d3.html', major_id=major_id,
                           major_name=names.get(major_id, major_id))

def build_daily_digest():
    """組每日摘要所需資料；快照或節點對應讀取失敗由呼叫端處理。

    指數、產業名稱、節點名稱讀不到時只影響各自的區塊（強弱產業顯示提示、名稱改顯示代號）。
    """
    snap = get_snapshot_or_503()
    m = get_mapping_or_503()
    try:
        idx = index_cache.get()
    except Exception:
        app.logger.exception("每日摘要：指數讀取失敗，強弱產業改顯示提示")
        idx = None
    try:
        industries = get_all_industries()
    except Exception:
        app.logger.exception("每日摘要：產業名稱讀取失敗，改顯示代號")
        industries = None
    try:
        node_names = fetch_node_names()
    except Exception:
        app.logger.exception("每日摘要：節點名稱讀取失敗，改顯示代號")
        node_names = {}
    returns, flows, sigs = snap.get("returns") or {}, snap.get("flows") or {}, snap.get("signals") or {}
    major_name = {i["major_id"]: i["major_name"] for i in industries or []}
    majors = [] if idx is None or industries is None else [
        {"major_id": i["major_id"], "name": i["major_name"],
         "r1": period_change(idx["series"].get(key_str("major", i["major_id"]), []), 1)}
        for i in industries]
    mapping = m["mapping"]
    node_major = {}
    for r in mapping:
        node_major.setdefault(r["node_id"], r["major_id"])
    nodes, node_flows = [], []
    for nid, mid in node_major.items():
        members = m["members"].get(("node", nid), ())
        vals = [v for v in (returns.get(sid, {}).get(1) for sid in members) if v is not None]
        name = node_names.get(nid, nid)
        nodes.append({"node_id": nid, "name": name, "major_id": mid, "major_name": major_name.get(mid, mid),
                      "change": round(sum(vals) / len(vals), 2) if vals else None})
        ft = flow_totals(flows, members, 5)
        node_flows.append({"node_id": nid, "name": name, "major_id": mid, "major_name": major_name.get(mid, mid),
                           "foreign_lots": ft["foreign_lots"], "trust_lots": ft["trust_lots"]})
    # 只列產業鏈公司（mapping 內）的訊號；每檔股票取第一個對應節點
    first = {}
    for r in mapping:
        first.setdefault(r["stock_id"], r)
    with_sig = [sid for sid in first if sigs.get(sid)]
    try:
        names = {c["stock_id"]: c["company_name"] for c in fetch_companies(with_sig)} if with_sig else {}
    except Exception:
        app.logger.exception("公司名稱讀取失敗，改顯示代號")
        names = {}
    signal_companies = [{"stock_id": sid, "name": names.get(sid, sid), "node_id": first[sid]["node_id"],
                         "major_id": first[sid]["major_id"], "signals": sigs[sid]}
                        for sid in with_sig]
    digest = daily_digest(majors, nodes, node_flows, signal_companies)
    digest["majors_unavailable"] = idx is None or industries is None
    return digest, snap


@app.route('/daily')
def daily_view():
    """每日摘要頁：AI 推薦、強弱產業與節點、法人流向；資料讀不到時顯示提示而非 500。"""
    try:
        fresh = freshness(fetch_sync_runs(), datetime.now())["message"]
    except Exception:
        app.logger.exception("新鮮度讀取失敗")
        fresh = "資料狀態未知"
    digest, snap = None, {}
    try:
        digest, snap = build_daily_digest()
    except Exception:
        app.logger.exception("每日摘要讀取失敗")
    try:
        ai = ai_picks.load_latest()
    except Exception:
        app.logger.exception("AI 推薦讀取失敗")
        ai = None
    return render_template('daily.html', digest=digest, freshness=fresh, MARKET_NOTE=MARKET_NOTE, SURVIVOR_NOTE=SURVIVOR_NOTE,
                           flow_date=snap.get("flow_date"), latest_date=snap.get("latest_date"),
                           ai=ai, ai_key=ai_picks.has_key(), AI_DISCLAIMER=ai_picks.DISCLAIMER)

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


def get_index_or_503():
    """讀產業指數快取；資料表不存在或讀取失敗回 503。"""
    try:
        return index_cache.get()
    except Exception:
        app.logger.exception("指數讀取失敗")
        raise ApiError("資料暫時無法讀取", 503)


def get_mapping_or_503():
    """讀節點對應快取（不依賴指數表）；失敗回 503。"""
    try:
        return mapping_cache.get()
    except Exception:
        app.logger.exception("節點對應讀取失敗")
        raise ApiError("資料暫時無法讀取", 503)


def get_industries_or_503():
    try:
        return get_all_industries()
    except Exception:
        app.logger.exception("產業名稱讀取失敗")
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


@app.route('/api/index_series')
def api_index_series():
    """指數走勢：每條序列以區間首點為 100；node 即時讀，其餘取快取。"""
    rng = request.args.get("range", "3M")
    if rng not in RANGES:
        raise ApiError("range 只能是 1M、3M、6M、1Y", 400)
    keys = [k for k in request.args.get("keys", "").split(",") if k]
    if len(keys) > MAX_INDEX_KEYS:
        raise ApiError(f"最多 {MAX_INDEX_KEYS} 條", 400)
    for k in keys:
        if not INDEX_KEY_RE.fullmatch(k):
            raise ApiError("key 格式錯誤", 400)
    n = RANGES[rng]
    idx = get_index_or_503()
    node_ids = [k.split(":", 1)[1] for k in keys if k.startswith("node:")]
    node_pts = {}
    if node_ids:
        since = (date.today() - timedelta(days=400)).isoformat()   # 與 index_data.load_index 同一個固定視窗
        try:
            node_pts = index_data.node_series(node_ids, since)
        except Exception:
            app.logger.exception("節點指數讀取失敗")
            raise ApiError("資料暫時無法讀取", 503)
    series, first_date = {}, {}
    for k in dict.fromkeys(keys):
        pts = node_pts.get(k, []) if k.startswith("node:") else idx["series"].get(k, [])
        series[k] = rebase(pts, n)
        first_date[k] = pts[0][0] if pts else None
    return jsonify({"series": series, "first_date": first_date,
                    "changed": sorted(k for k in series if k in idx["changed"]),
                    "notes": NOTES})


@app.route('/api/industry_ranking')
def api_industry_ranking():
    """產業排行：區間漲跌（指數）與近 5 日法人買賣超（快照）。"""
    idx = get_index_or_503()
    snap = get_snapshot_or_503()
    industries = get_industries_or_503()
    flows = snap.get("flows") or {}
    rows = []
    for m in industries:
        mid = m["major_id"]
        pts = idx["series"].get(key_str("major", mid), [])
        ft = flow_totals(flows, idx["members"].get(("major", mid), ()), 5)
        rows.append({"major_id": mid, "name": m["major_name"],
                     "r1": period_change(pts, 1), "r5": period_change(pts, 5),
                     "r20": period_change(pts, 20),
                     "foreign5": ft["foreign_lots"], "trust5": ft["trust_lots"],
                     "flow_count": ft["count"]})
    mkt = idx["series"].get(key_str("market", "TW"), [])
    return jsonify({"rows": rows,
                    "market": {"r1": period_change(mkt, 1), "r5": period_change(mkt, 5),
                               "r20": period_change(mkt, 20)},
                    "flow_date": snap.get("flow_date"), "notes": NOTES})


@app.route('/api/rotation')
def api_rotation():
    """相對輪動：各產業相對大盤的 RRG 座標；歷史不足者不列入。"""
    idx = get_index_or_503()
    industries = get_industries_or_503()
    mkt = idx["series"].get(key_str("market", "TW"), [])
    points = []
    for m in industries:
        r = rrg(idx["series"].get(key_str("major", m["major_id"]), []), mkt)
        if r is None:
            continue
        points.append({"major_id": m["major_id"], "name": m["major_name"], **r})
    return jsonify({"points": points, "as_of": mkt[-1][0] if mkt else None, "notes": NOTES})


@app.route('/api/node_flows/<major_id>')
def api_node_flows(major_id):
    """產業內各節點的法人買賣超加總（張）；count 為有資料家數。"""
    period = parse_period()
    m = get_mapping_or_503()
    snap = get_snapshot_or_503()
    flows = snap.get("flows") or {}
    node_ids = list(dict.fromkeys(r["node_id"] for r in m["mapping"] if r["major_id"] == major_id))
    nodes = []
    for nid in node_ids:
        ft = flow_totals(flows, m["members"].get(("node", nid), ()), period)
        nodes.append({"node_id": nid, "foreign_lots": ft["foreign_lots"],
                      "trust_lots": ft["trust_lots"], "count": ft["count"]})
    return jsonify({"flow_date": snap.get("flow_date"), "nodes": nodes})


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
    rows = fetch_companies(ids) if ids else []
    # 快照只用來補提醒欄位；讀取失敗不影響主要資料（signals 空、ex_today null）
    try:
        snap = snapshot_cache.get()
    except Exception:
        app.logger.exception("自選股提醒：快照讀取失敗")
        snap = {}
    signals, ex = snap.get("signals") or {}, snap.get("ex") or {}
    out = []
    for r in rows:
        sid = r.get("stock_id")
        out.append({**r, "signals": signals.get(sid, []), "ex_today": (ex.get(sid) or {}).get(1)})
    return jsonify(out)


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