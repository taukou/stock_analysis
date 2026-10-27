"""產業指數的網站端純計算：換算、區間漲跌、相對輪動（RRG）與法人加總（不含資料庫相依）。

缺值一律 None，絕不以 0 代替。
"""
import math
from typing import Iterable

MARKET_NOTE = "此為自行計算的等權大盤（上市＋上櫃，排除 ETF，已還原除權息），與證交所公布的加權指數不同"
SURVIVOR_NOTE = "成分股以目前名單往回計算，不含已下市公司"
RANGES = {"1M": 21, "3M": 63, "6M": 126, "1Y": 250}   # 交易日數


def to_lots(shares):
    """股 → 張（四捨五入）；缺值保留 None。"""
    return None if shares is None else int(math.floor(shares / 1000 + 0.5))


def key_str(kind: str, scope_id: str) -> str:
    return f"{kind}:{scope_id}"


def series_by_key(rows: list[dict]) -> dict[str, list[tuple[str, float]]]:
    """資料列 → {key: [(日期, 指數)...]}，日期由舊到新；指數缺值的列略過。"""
    out: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        if r.get("level") is None:
            continue
        out.setdefault(key_str(r["scope_kind"], r["scope_id"]), []).append(
            (r["trade_date"], r["level"]))
    for pts in out.values():
        pts.sort(key=lambda p: p[0])
    return out


def rebase(points, n: int) -> list[dict]:
    """取最後 n+1 點並以首點為 100；點數不足時用全部。"""
    pts = list(points)[-(n + 1):]
    if not pts or not pts[0][1]:
        return []
    base = pts[0][1]
    return [{"date": d, "value": round(v / base * 100, 2)} for d, v in pts]


def period_change(points, n: int) -> float | None:
    """最後一點相對倒數第 n+1 點的漲跌百分比；點數不足回 None。"""
    pts = list(points)
    if n < 1 or len(pts) < n + 1 or not pts[-(n + 1)][1]:
        return None
    return round((pts[-1][1] / pts[-(n + 1)][1] - 1) * 100, 2)


def quadrant(x: float, y: float) -> str:
    if x >= 100:
        return "領先" if y >= 100 else "轉弱"
    return "轉強" if y >= 100 else "落後"


def rrg(ind, mkt, window: int = 50, roc: int = 10, trail_weeks: int = 8, step: int = 5) -> dict | None:
    """相對輪動：以日期交集對齊，rs = 產業/大盤；x 為 rs 相對近 window 點均值，y 為 x 相對 roc 點前的比值。"""
    m = dict(mkt)
    common = [(d, v / m[d]) for d, v in ind if d in m and v is not None and m[d]]
    common.sort(key=lambda p: p[0])
    dates = [d for d, _ in common]
    rs = [v for _, v in common]
    n = len(rs)
    if n == 0:
        return None
    xs: list[float | None] = [None] * n
    for t in range(window - 1, n):
        avg = sum(rs[t - window + 1:t + 1]) / window
        xs[t] = 100 * rs[t] / avg if avg else None

    def y_at(t: int) -> float | None:
        if t - roc < 0 or xs[t] is None or not xs[t - roc]:
            return None
        return 100 * xs[t] / xs[t - roc]

    last_y = y_at(n - 1)
    if xs[-1] is None or last_y is None:
        return None
    trail = []
    for k in range(trail_weeks):
        t = n - 1 - k * step
        if t < 0:
            break
        y = y_at(t)
        if xs[t] is None or y is None:
            break
        trail.append({"date": dates[t], "x": round(xs[t], 2), "y": round(y, 2)})
    trail.reverse()
    x, y = round(xs[-1], 2), round(last_y, 2)
    return {"x": x, "y": y, "quadrant": quadrant(x, y), "trail": trail}


def flow_totals(flow_sums: dict, members: Iterable[str], n: int) -> dict:
    """成分股法人買賣超加總（股→張）；只加有資料者，count 為有資料家數。"""
    fo = tr = None
    count = 0
    for sid in members:
        s = (flow_sums.get(sid) or {}).get(n)
        if not s:
            continue
        f, t = s.get("foreign"), s.get("trust")
        if f is None and t is None:
            continue
        count += 1
        if f is not None:
            fo = (fo or 0) + f
        if t is not None:
            tr = (tr or 0) + t
    return {"foreign_lots": to_lots(fo), "trust_lots": to_lots(tr), "count": count}


SIGNAL_ORDER = (("trust_streak", "投信連買"), ("yoy_turn", "營收年增轉正"),
                ("revenue_high", "營收創高"), ("volume_spike", "爆量"))


def daily_digest(majors: list[dict], nodes: list[dict], node_flows: list[dict],
                 signal_companies: list[dict]) -> dict:
    """每日摘要：強弱產業（前／後 3）、強弱節點（前／後 5）、法人淨買節點（前 5）與訊號分組；缺值不列入排名。"""
    def ranked(rows, key):
        return sorted((r for r in rows if r.get(key) is not None), key=lambda r: r[key], reverse=True)

    rm = ranked(majors, "r1")
    rn = ranked(nodes, "change")
    flow_nodes = []
    for f in node_flows:
        vals = [v for v in (f.get("foreign_lots"), f.get("trust_lots")) if v is not None]
        if vals:
            flow_nodes.append({**f, "net": sum(vals)})
    flow_nodes.sort(key=lambda r: r["net"], reverse=True)
    groups = []
    for code, label in SIGNAL_ORDER:
        companies = []
        for c in signal_companies:
            for s in c.get("signals") or []:
                if s.get("code") == code:
                    companies.append({"stock_id": c["stock_id"], "name": c["name"], "node_id": c.get("node_id"),
                                      "major_id": c.get("major_id"), "label": s.get("label"),
                                      "detail": s.get("detail")})
        if companies:
            groups.append({"code": code, "label": label, "companies": companies})
    return {"strong_majors": rm[:3], "weak_majors": rm[::-1][:3],
            "strong_nodes": rn[:5], "weak_nodes": rn[::-1][:5],
            "flow_nodes": flow_nodes[:5], "signal_groups": groups}
