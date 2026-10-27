"""資料新鮮度判斷的純計算模組（不含資料庫或 Supabase 相依）。

以 sync_runs 最新一筆判斷各資料集是否失敗或落後。
休市日判斷（Ruling 6）：同步程式會逐日抓到今天、兩市場都無資料即視為休市，
因此「落後超過 1 個工作日」時，若最新一次同步在應有日 15:00 之後成功完成且沒有訊息，
代表資料已是最新（中間是休市日），不算落後。
"""

from datetime import date, datetime, time, timedelta, timezone

DATASET_ORDER = ("quotes", "emerging", "institutional", "ex_rights", "revenue",
                 "industry_index", "index_backfill", "ai_picks")
DATASET_LABELS = {"quotes": "股價", "emerging": "興櫃", "institutional": "法人",
                  "ex_rights": "除權息", "revenue": "月營收",
                  "industry_index": "產業指數", "index_backfill": "指數補抓",
                  "ai_picks": "AI 推薦"}
STALE_CHECKED = ("quotes", "institutional")
CUTOFF_HOUR = 15
# 連續休市不會超過這麼多個工作日（春節例外，會短暫誤報，可接受）
MAX_HOLIDAY_LAG = 5
# 台灣沒有日光節約時間，用固定 UTC+8（不用 zoneinfo，Windows 需另裝 tzdata）
TAIPEI = timezone(timedelta(hours=8))


def label(name: str) -> str:
    return DATASET_LABELS.get(name, name)


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


def parse_finished_at(value) -> datetime | None:
    """sync_runs.finished_at（UTC timestamptz 字串）→ 台北時間的 aware datetime；無法解析回 None。"""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)   # 資料庫存的是 UTC
    return dt.astimezone(TAIPEI)


def _stale_reason(name: str, run: dict | None, latest: dict, now: datetime) -> str | None:
    """回傳落後原因（中文），沒問題回 None。"""
    lbl = label(name)
    if run is None:
        return f"尚無{lbl}同步紀錄"
    last = run.get("last_date")
    if not last:
        return f"{lbl}尚無資料"
    lag = weekday_lag(last, now)
    if lag <= 1:
        return None
    if lag > MAX_HOLIDAY_LAG:
        return f"{lbl}已 {lag} 個工作日沒有新資料（長假或來源異常）"
    if name == "quotes":
        emerging = (latest.get("emerging") or {}).get("last_date")
        if emerging and emerging > last:
            return f"{lbl}資料落後（興櫃已有 {emerging}）"
    expected = _expected_date(now)
    finished = parse_finished_at(run.get("finished_at"))
    checked_after_close = finished is not None and finished >= datetime.combine(expected, time(CUTOFF_HOUR), TAIPEI)
    if not checked_after_close or run.get("message"):
        return f"{lbl}資料落後"
    return None   # 收盤後已同步且無訊息：中間是休市日


def freshness(rows: list[dict], now: datetime) -> dict:
    """回傳 {"level", "message", "datasets"}；failed > stale > ok。now 為台北本地時間（naive）。"""
    latest = latest_runs(rows)
    quotes_date = latest.get("quotes", {}).get("last_date")
    head = f"資料更新至 {quotes_date or '—'}"

    datasets = [
        {
            "dataset": name,
            "label": label(name),
            "last_date": latest[name].get("last_date"),
            "status": latest[name]["status"],
            "finished_at": latest[name].get("finished_at"),
        }
        for name in DATASET_ORDER
        if name in latest
    ]

    failed = [d["label"] for d in datasets if d["status"] == "failed"]
    if failed:
        return {
            "level": "failed",
            "message": f"{head}；同步失敗：{'、'.join(failed)}",
            "datasets": datasets,
        }

    for name in STALE_CHECKED:
        reason = _stale_reason(name, latest.get(name), latest, now)
        if reason:
            return {"level": "stale", "message": f"{head}；{reason}", "datasets": datasets}

    return {"level": "ok", "message": head, "datasets": datasets}
