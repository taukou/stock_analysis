"""資料新鮮度判斷的純計算模組（不含資料庫或 Supabase 相依）。

以 sync_runs 最新一筆判斷各資料集是否失敗或落後。
"""

from datetime import date, datetime, timedelta

DATASET_ORDER = ("quotes", "emerging", "institutional", "ex_rights", "revenue")
STALE_CHECKED = ("quotes", "institutional")
CUTOFF_HOUR = 15


def latest_runs(rows: list[dict]) -> dict[str, dict]:
    """rows 為 sync_runs（新到舊），每個 dataset 只取第一筆。"""
    latest: dict[str, dict] = {}
    for row in rows:
        latest.setdefault(row["dataset"], row)
    return latest


def _expected_date(now: datetime) -> date:
    """收盤後（15 點以後）應有當日資料，否則應有前一日；週末往前推到週五。"""
    target = now.date() if now.hour >= CUTOFF_HOUR else now.date() - timedelta(days=1)
    while target.weekday() >= 5:
        target -= timedelta(days=1)
    return target


def weekday_lag(last_date: str, now: datetime) -> int:
    """last_date 之後到應有日（含）之間的週一至週五天數。"""
    start = date.fromisoformat(last_date)
    end = _expected_date(now)
    lag = 0
    day = start + timedelta(days=1)
    while day <= end:
        if day.weekday() < 5:
            lag += 1
        day += timedelta(days=1)
    return lag


def freshness(rows: list[dict], now: datetime) -> dict:
    """回傳 {"level", "message", "datasets"}；failed > stale > ok。"""
    latest = latest_runs(rows)
    quotes_date = latest.get("quotes", {}).get("last_date")
    head = f"資料更新至 {quotes_date or '—'}"

    datasets = [
        {
            "dataset": name,
            "last_date": latest[name].get("last_date"),
            "status": latest[name]["status"],
            "finished_at": latest[name].get("finished_at"),
        }
        for name in DATASET_ORDER
        if name in latest
    ]

    failed = [d["dataset"] for d in datasets if d["status"] == "failed"]
    if failed:
        return {
            "level": "failed",
            "message": f"{head}；同步失敗：{', '.join(failed)}",
            "datasets": datasets,
        }

    for name in STALE_CHECKED:
        run = latest.get(name)
        if run is None or not run.get("last_date"):
            return {"level": "stale", "message": f"{head}；缺少 {name} 資料", "datasets": datasets}
        if weekday_lag(run["last_date"], now) > 1:
            return {"level": "stale", "message": f"{head}；{name} 資料落後", "datasets": datasets}

    return {"level": "ok", "message": head, "datasets": datasets}
