"""AI 推薦成績單：推薦日收盤之後 N 個交易日的漲跌，和大盤（自行計算的等權指數）同期比較。

- 個股用除權息還原後的收盤價（含息），產業用產業等權指數。
- 交易日以大盤指數的日期為準；推薦日或到期日沒有價格（停牌、資料缺）時該欄為 None。
"""
import ai_factors as F

HORIZONS = (5, 20)          # 推薦後第幾個交易日
NOW = "now"                 # 推薦日到最新資料日
RECENT_ROWS = 30


def _ret(a, b):
    return None if not a or b is None else round((b / a - 1) * 100, 2)


def stock_levels(quotes: list[dict], ex_events: list[dict]) -> dict[str, dict[str, float]]:
    """daily_quotes + ex_rights（多檔混在一起）→ {stock_id: {日期: 還原收盤價}}。"""
    by_q, by_ex = {}, {}
    for r in quotes:
        by_q.setdefault(r["stock_id"], []).append(r)
    for r in ex_events:
        by_ex.setdefault(r["stock_id"], []).append(r)
    return {sid: {r["trade_date"]: r["close"] for r in F.adjusted_prices(rows, by_ex.get(sid, []))}
            for sid, rows in by_q.items()}


def _levels(points) -> dict[str, float]:
    return {d: v for d, v in points or [] if v is not None}


def evaluate(docs: list[dict], stocks: dict[str, dict[str, float]], series: dict) -> dict:
    """docs 為各日推薦檔；回傳 {"rows": 新到舊的每則推薦, "summary": {期間: 統計}, "latest": 最新資料日}。"""
    market = _levels(series.get("market:TW"))
    cal = sorted(market)
    pos = {d: i for i, d in enumerate(cal)}
    rows = []
    for doc in sorted(docs, key=lambda d: d.get("date") or "", reverse=True):
        start = doc.get("date")
        if start not in pos:
            continue
        i = pos[start]
        for p in doc.get("picks") or []:
            lv = _levels(series.get(f"major:{p['id']}")) if p.get("kind") == "industry" else stocks.get(p.get("id"), {})
            base = lv.get(start)
            ends = {h: cal[i + h] for h in HORIZONS if i + h < len(cal)}
            if i < len(cal) - 1:
                ends[NOW] = cal[-1]
            ret, mkt, excess = {}, {}, {}
            for key, end in ends.items():
                ret[key] = _ret(base, lv.get(end))
                mkt[key] = _ret(market[start], market[end])
                excess[key] = None if ret[key] is None else round(ret[key] - mkt[key], 2)
            rows.append({"date": start, "kind": p.get("kind"), "id": p.get("id"), "name": p.get("name"),
                         "major_id": p.get("major_id"), "node_id": p.get("node_id"),
                         "days": len(cal) - 1 - i, "ret": ret, "market": mkt, "excess": excess})
    summary = {}
    for key in (*HORIZONS, NOW):
        done = [r for r in rows if r["ret"].get(key) is not None]
        if done:
            summary[key] = {"count": len(done),
                            "avg": round(sum(r["ret"][key] for r in done) / len(done), 2),
                            "avg_excess": round(sum(r["excess"][key] for r in done) / len(done), 2),
                            "beat": round(sum(r["excess"][key] > 0 for r in done) / len(done) * 100)}
    return {"rows": rows, "summary": summary, "latest": cal[-1] if cal else None}
