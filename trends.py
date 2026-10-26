"""區間漲跌與節點平均的純計算模組（不含資料庫或 Supabase 相依）。

缺值一律回傳 None，絕不以 0 代替。
"""

PERIODS: tuple[int, ...] = (1, 5, 20)

LISTED_MARKETS = ("上市", "上櫃")


def trading_dates(rows: list[dict]) -> list[str]:
    """回傳 上市／上櫃 且收盤價非 None 的不重複交易日，新到舊。"""
    dates = {
        r["trade_date"]
        for r in rows
        if r.get("market") in LISTED_MARKETS and r.get("close") is not None
    }
    return sorted(dates, reverse=True)


def period_return(
    n: int,
    dates: list[str],
    closes: dict[str, float | None],
    latest_change_pct: float | None,
    ex_events: list[dict],
) -> float | None:
    """計算 n 個交易日區間漲跌幅（%），使用還原股價。

    n == 1 直接回傳最新交易日的 change_pct（已由 fill_ex_date_changes 處理除權息）。
    n > 1 以 dates[0] 的收盤 ÷ dates[n] 的收盤，並乘上視窗 (dates[n], dates[0]]
    內除權息事件的還原因子 prev_close ÷ ref_price 連乘。
    """
    if n == 1:
        return latest_change_pct
    if len(dates) <= n:
        return None

    last, base = dates[0], dates[n]
    close_last = closes.get(last)
    close_base = closes.get(base)
    if close_last is None or close_base is None or close_last <= 0 or close_base <= 0:
        return None

    factor = 1.0
    for ev in ex_events:
        if not (base < ev["ex_date"] <= last):
            continue
        prev_close, ref_price = ev.get("prev_close"), ev.get("ref_price")
        if prev_close is None or ref_price is None or prev_close <= 0 or ref_price <= 0:
            continue
        factor *= prev_close / ref_price

    return round((close_last / close_base * factor - 1) * 100, 2)


def ex_kind_in_period(n: int, dates: list[str], ex_events: list[dict]) -> str | None:
    """回傳區間視窗 (dates[n], dates[0]] 內最新一筆除權息事件的 kind，無則 None。"""
    if len(dates) <= n:
        return None

    base, last = dates[n], dates[0]
    in_window = [ev for ev in ex_events if base < ev["ex_date"] <= last]
    if not in_window:
        return None
    return max(in_window, key=lambda ev: ev["ex_date"])["kind"]


def node_average(values: list[float | None]) -> tuple[float | None, int]:
    """排除 None 後的等權平均，回傳 (平均或 None, 納入家數)。"""
    present = [v for v in values if v is not None]
    if not present:
        return None, 0
    return round(sum(present) / len(present), 2), len(present)
