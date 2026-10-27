"""AI 推薦用的因子計算（純函式，不碰資料庫）。

技術面：以除權息還原後的價格計算均線、均線交叉、KD、MACD、RSI、20 日突破與量比。
籌碼面：外資／投信近 10 日買超天數、自營商 5 日與外資 20 日買賣超。
基本面：月營收年增、月增、累計年增、年增連續月數與加速度。
產業：指數 60 日、一年漲跌與均線位置、輪動象限的移動。
價格只有約 3 個月，60 日均線與 MACD 是可算的上限；資料不足的欄位回 None。
"""
from industry_trends import period_change, quadrant

CROSS_LOOKBACK = 3     # 「最近交叉」：最近幾個交易日內發生


# ---------- 價格還原與基本指標 ----------

def adjusted_prices(rows: list[dict], ex_events: list[dict]) -> list[dict]:
    """rows 為單一股票的日行情（任意順序，含 trade_date/close/high/low/volume）。

    除權息日之前的價格乘上 ref_price / prev_close，讓均線與高低點不會被除息缺口誤判；回傳依日期排序的新列。
    """
    out = sorted(({**r} for r in rows if r.get("close") is not None), key=lambda r: r["trade_date"])
    for ev in ex_events:
        prev, ref = ev.get("prev_close"), ev.get("ref_price")
        if not prev or not ref or prev <= 0 or ref <= 0:
            continue
        f = float(ref) / float(prev)
        for r in out:
            if r["trade_date"] < ev["ex_date"]:
                for k in ("close", "high", "low"):
                    if r.get(k) is not None:
                        r[k] = float(r[k]) * f
    return out


def sma(vals: list[float], n: int) -> list[float | None]:
    out, s = [], 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def ema(vals: list[float], n: int) -> list[float]:
    k, out = 2 / (n + 1), []
    for v in vals:
        out.append(v if not out else out[-1] + k * (v - out[-1]))
    return out


def last_cross(fast: list, slow: list, lookback: int = CROSS_LOOKBACK) -> tuple[str, int] | None:
    """最近 lookback 個交易日內 fast 由下往上（golden）或由上往下（death）穿越 slow；回傳 (種類, 幾日前)。"""
    n = len(fast)
    for back in range(lookback):
        i = n - 1 - back
        if i < 1 or None in (fast[i], slow[i], fast[i - 1], slow[i - 1]):
            continue
        if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
            return "golden", back
        if fast[i - 1] >= slow[i - 1] and fast[i] < slow[i]:
            return "death", back
    return None


def kd(highs: list[float], lows: list[float], closes: list[float], n: int = 9) -> tuple[list[float], list[float]]:
    """台灣常用的 KD(9,3,3)：K、D 由 50 起算。"""
    ks, ds, k, d = [], [], 50.0, 50.0
    for i in range(len(closes)):
        lo, hi = min(lows[max(0, i - n + 1):i + 1]), max(highs[max(0, i - n + 1):i + 1])
        rsv = 50.0 if hi == lo else (closes[i] - lo) / (hi - lo) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        ks.append(k)
        ds.append(d)
    return ks, ds


def macd_hist(closes: list[float]) -> list[float]:
    dif = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
    return [a - b for a, b in zip(dif, ema(dif, 9))]


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder RSI；資料不足回 None。"""
    if len(closes) < n + 1:
        return None
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l) / n
    return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)


# ---------- 個股因子 ----------

def technicals(prices: list[dict]) -> dict:
    """prices 為 adjusted_prices 的結果。回傳技術面摘要；資料不足的欄位為 None。"""
    closes = [float(r["close"]) for r in prices]
    out = {"ma20_gap": None, "above_ma60": None, "ma_cross": None, "ma_long_cross": None,
           "k": None, "d": None, "kd_cross": None, "macd_turn": None, "rsi": None,
           "breakout20": None, "vol_ratio": None}
    if len(closes) < 21:
        return out
    c = closes[-1]
    ma5, ma20, ma60 = sma(closes, 5), sma(closes, 20), sma(closes, 60)
    out["ma20_gap"] = round((c / ma20[-1] - 1) * 100, 1)
    out["above_ma60"] = None if ma60[-1] is None else c > ma60[-1]
    out["ma_cross"] = last_cross(ma5, ma20)
    out["ma_long_cross"] = last_cross(ma20, ma60)
    highs = [float(r.get("high") or r["close"]) for r in prices]
    lows = [float(r.get("low") or r["close"]) for r in prices]
    ks, ds = kd(highs, lows, closes)
    out["k"], out["d"] = round(ks[-1]), round(ds[-1])
    out["kd_cross"] = last_cross(ks, ds)
    if len(closes) >= 35:
        h = macd_hist(closes)
        turn = last_cross(h, [0.0] * len(h))
        out["macd_turn"] = turn
    r = rsi(closes)
    out["rsi"] = None if r is None else round(r)
    prior = closes[-21:-1]
    out["breakout20"] = "high" if c > max(prior) else ("low" if c < min(prior) else None)
    vols = [r.get("volume") for r in prices[-21:]]
    if None not in vols and sum(vols[:-1]) > 0:
        out["vol_ratio"] = round(vols[-1] / (sum(vols[:-1]) / 20), 1)
    return out


def flow_stats(flows: list[dict]) -> dict:
    """flows 為單一股票的法人日資料（含 trade_date/foreign_net/trust_net/dealer_net，單位股）。"""
    rows = sorted(flows, key=lambda r: r["trade_date"])

    def buy_days(key, n=10):
        vals = [r.get(key) for r in rows[-n:]]
        return sum(1 for v in vals if v is not None and v > 0) if vals else None

    def lots(key, n):
        vals = [r.get(key) for r in rows[-n:] if r.get(key) is not None]
        return round(sum(vals) / 1000) if vals else None

    return {"foreign_days10": buy_days("foreign_net"), "trust_days10": buy_days("trust_net"),
            "dealer5": lots("dealer_net", 5), "foreign20": lots("foreign_net", 20),
            "trust20": lots("trust_net", 20)}


def revenue_stats(revenue: list[dict]) -> dict | None:
    """revenue 為單一股票的月營收（data_month 如 '115/09'）。"""
    rows = sorted((r for r in revenue if r.get("yoy_pct") is not None), key=lambda r: r["data_month"])
    if not rows:
        return None
    last = rows[-1]
    streak = 0
    sign = last["yoy_pct"] > 0
    for r in reversed(rows):
        if (r["yoy_pct"] > 0) != sign:
            break
        streak += 1
    yoys = [r["yoy_pct"] for r in rows]
    accel = round(sum(yoys[-3:]) / 3 - sum(yoys[-6:-3]) / 3, 1) if len(yoys) >= 6 else None
    return {"month": last["data_month"], "yoy": last["yoy_pct"], "mom": last.get("mom_pct"),
            "acc_yoy": last.get("acc_yoy_pct"), "yoy_streak": streak if sign else -streak, "accel": accel}


def score(t: dict, f: dict, rev: dict | None, n_signals: int) -> float:
    """挑候選個股用的粗略分數：好壞事件都算「值得注意」，交給 AI 判斷方向。"""
    s = n_signals * 2.0
    for key in ("ma_cross", "ma_long_cross", "kd_cross", "macd_turn"):
        s += 1 if t.get(key) else 0
    s += 1 if t.get("breakout20") else 0
    s += 1 if (t.get("vol_ratio") or 0) >= 1.8 else 0
    s += 1 if (f.get("foreign_days10") or 0) >= 7 or (f.get("trust_days10") or 0) >= 6 else 0
    if rev:
        s += 1 if rev["yoy"] >= 20 else 0
        s += 1 if (rev.get("accel") or 0) >= 10 else 0
    return s


# ---------- 文字化（給 AI 讀） ----------

CROSS_TEXT = {"golden": "黃金交叉", "death": "死亡交叉"}


def _cross(label: str, c) -> str | None:
    if not c:
        return None
    kind, back = c
    return f"{label}{CROSS_TEXT[kind]}（{'今天' if back == 0 else f'{back}日前'}）"


def technicals_text(t: dict) -> str:
    parts = []
    if t["ma20_gap"] is not None:
        parts.append(f"離MA20 {t['ma20_gap']:+.1f}%")
    if t["above_ma60"] is not None:
        parts.append("站上MA60" if t["above_ma60"] else "跌破MA60")
    parts += [p for p in (_cross("MA5/20", t["ma_cross"]), _cross("MA20/60", t["ma_long_cross"]),
                          _cross("KD", t["kd_cross"])) if p]
    if t["k"] is not None:
        parts.append(f"KD {t['k']}/{t['d']}")
    if t["macd_turn"]:
        kind, back = t["macd_turn"]
        parts.append(f"MACD柱{'翻正' if kind == 'golden' else '翻負'}（{'今天' if back == 0 else f'{back}日前'}）")
    if t["rsi"] is not None:
        parts.append(f"RSI {t['rsi']}")
    if t["breakout20"]:
        parts.append("創20日新高" if t["breakout20"] == "high" else "創20日新低")
    if t["vol_ratio"] is not None:
        parts.append(f"量{t['vol_ratio']}倍")
    return " ".join(parts) or "—"


def _lot(v):
    return "—" if v is None else f"{v:+,}張"


def flow_text(f: dict) -> str:
    return (f"外資10日買{f['foreign_days10'] if f['foreign_days10'] is not None else '—'}天 20日{_lot(f['foreign20'])} "
            f"投信10日買{f['trust_days10'] if f['trust_days10'] is not None else '—'}天 20日{_lot(f['trust20'])} "
            f"自營5日{_lot(f['dealer5'])}")


def revenue_text(rev: dict | None) -> str:
    if not rev:
        return "—"
    parts = [f"{rev['month']} 年增{rev['yoy']:+.1f}%"]
    if rev.get("mom") is not None:
        parts.append(f"月增{rev['mom']:+.1f}%")
    if rev.get("acc_yoy") is not None:
        parts.append(f"累計年增{rev['acc_yoy']:+.1f}%")
    k = rev["yoy_streak"]
    parts.append(f"年增連{k}月為正" if k > 0 else f"年增連{-k}月為負")
    if rev.get("accel") is not None:
        parts.append(f"近3月年增較前3月{rev['accel']:+.1f}個百分點")
    return " ".join(parts)


# ---------- 產業因子 ----------

def industry_trend(points: list) -> dict:
    """points 為產業指數 [(date, level)]（舊到新）。"""
    levels = [v for _, v in points if v is not None]
    out = {"r60": period_change(points, 60), "r1y": None, "vs_ma20": None, "vs_ma60": None}
    if len(points) > 200:
        out["r1y"] = round((levels[-1] / levels[0] - 1) * 100, 2)
    for n, key in ((20, "vs_ma20"), (60, "vs_ma60")):
        m = sma(levels, n)[-1] if len(levels) >= n else None
        if m:
            out[key] = round((levels[-1] / m - 1) * 100, 1)
    return out


def rotation_move(point: dict | None) -> str | None:
    """輪動軌跡最舊一點的象限 → 目前象限，例如「落後→轉強」；沒動回目前象限。"""
    if not point:
        return None
    trail = point.get("trail") or []
    if not trail:
        return point.get("quadrant")
    start = quadrant(trail[0]["x"], trail[0]["y"])
    now = point.get("quadrant") or quadrant(point["x"], point["y"])
    return now if start == now else f"{start}→{now}"
