"""個股訊號規則的純計算模組（不含資料庫或 Supabase 相依）。

訊號格式一律為 {"code": str, "label": str, "detail": str}。
資料不足時訊號不觸發，缺值不以 0 代替。
"""


def month_index(data_month: str) -> int:
    """ROC 年月 'YYY/MM' 轉為可比較、可相減的整數索引。"""
    year, month = data_month.split("/")
    return int(year) * 12 + int(month)


def _signal(code: str, label: str, detail: str) -> dict:
    return {"code": code, "label": label, "detail": detail}


def trust_streak(
    dates: list[str],
    trust_by_date: dict[str, int | None],
    min_days: int = 5,
) -> dict | None:
    """從最新交易日（dates[0]）往回數投信買超（trust_net > 0）的連續日數。"""
    if len(dates) < min_days:
        return None
    k = 0
    for d in dates:
        net = trust_by_date.get(d)
        if net is None or net <= 0:
            break
        k += 1
    if k < min_days:
        return None
    return _signal(
        "trust_streak",
        f"投信連買 {k} 日",
        f"近 {k} 個交易日投信皆買超",
    )


def _latest_revenue_first(revenue: list[dict]) -> list[dict]:
    return sorted(revenue, key=lambda r: month_index(r["data_month"]), reverse=True)


def yoy_turn_positive(revenue: list[dict]) -> dict | None:
    """最新兩個月相鄰、皆有年增率，且由 ≤0 轉為 >0。"""
    rows = _latest_revenue_first(revenue)
    if len(rows) < 2:
        return None
    cur, prev = rows[0], rows[1]
    if month_index(cur["data_month"]) - month_index(prev["data_month"]) != 1:
        return None
    if cur["yoy_pct"] is None or prev["yoy_pct"] is None:
        return None
    if not (cur["yoy_pct"] > 0 and prev["yoy_pct"] <= 0):
        return None
    return _signal(
        "yoy_turn",
        "營收年增轉正",
        f"{prev['data_month']} {prev['yoy_pct']:+.2f}% → "
        f"{cur['data_month']} {cur['yoy_pct']:+.2f}%",
    )


def revenue_12m_high(revenue: list[dict]) -> dict | None:
    """最新月營收大於其前 11 個連續月份的最大值（需 12 個連續月份皆非 null）。"""
    rows = _latest_revenue_first(revenue)
    if len(rows) < 12:
        return None
    latest = rows[0]
    base = month_index(latest["data_month"])
    by_index = {month_index(r["data_month"]): r["revenue"] for r in rows}
    window = [by_index.get(base - i) for i in range(12)]
    if any(v is None for v in window):
        return None
    if latest["revenue"] is None or latest["revenue"] <= max(window[1:]):
        return None
    return _signal(
        "revenue_high",
        "營收創 12 個月新高",
        f"{latest['data_month']} 營收 {latest['revenue']:,} 千元",
    )


def volume_spike(
    dates: list[str],
    volume_by_date: dict[str, int | None],
    mult: float = 2.0,
    window: int = 20,
) -> dict | None:
    """今日成交量 ≥ 前 window 個交易日均量 × mult。"""
    if len(dates) < window + 1:
        return None
    today = volume_by_date.get(dates[0])
    prior = [volume_by_date.get(d) for d in dates[1:window + 1]]
    if today is None or any(v is None for v in prior):
        return None
    avg = sum(prior) / window
    if avg <= 0 or today < avg * mult:
        return None
    return _signal(
        "volume_spike",
        "爆量",
        f"成交量 {today:,} 股，為 {window} 日均量 {today / avg:.1f} 倍",
    )


def company_signals(
    dates: list[str],
    trust_by_date: dict[str, int | None],
    revenue: list[dict],
    volume_by_date: dict[str, int | None],
) -> list[dict]:
    """依序套用四條規則，收集觸發的訊號。"""
    candidates = [
        trust_streak(dates, trust_by_date),
        yoy_turn_positive(revenue),
        revenue_12m_high(revenue),
        volume_spike(dates, volume_by_date),
    ]
    return [s for s in candidates if s is not None]
