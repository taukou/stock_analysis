"""日資料工作：行情、興櫃、法人，含補跑日期規劃。"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Literal

from sync.sources import mops, tpex, twse

log = logging.getLogger(__name__)

ON_CONFLICT = "stock_id,trade_date"
MARKET_NAMES = ("上市", "上櫃")
_FOUR_DIGITS = re.compile(r"\d{4}")


@dataclass
class JobResult:
    dataset: str
    status: Literal["ok", "failed"]
    last_date: str | None
    rows: int
    message: str = ""


def keep_row(stock_id: str, tracked: set[str]) -> bool:
    """只存 4 位數字代號，或追蹤清單內的代號（如 ETF）。"""
    return bool(_FOUR_DIGITS.fullmatch(stock_id)) or stock_id in tracked


def dates_to_fetch(last: date | None, now: datetime, backfill_days: int = 95,
                   publish_hour: int = 15) -> list[date]:
    start = last + timedelta(days=1) if last else now.date() - timedelta(days=backfill_days)
    end = now.date() if now.hour >= publish_hour else now.date() - timedelta(days=1)
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _last(store, table, column, filters=None) -> date | None:
    v = store.last_value(table, column, filters)
    return date.fromisoformat(v) if v else None


def _prepare(items, tracked: set[str], date_field: str = "trade_date",
             filter_rows: bool = True) -> list[dict]:
    """轉成 row、套用過濾、同日（同月）重複只留第一筆。"""
    seen, out = set(), []
    for it in items:
        row = it.to_row()
        sid = row["stock_id"]
        if filter_rows and not keep_row(sid, tracked):
            continue
        key = (sid, row[date_field])
        if key in seen:
            log.warning("同日重複代號 %s (%s)，保留第一筆", sid, row[date_field])
            continue
        seen.add(key)
        out.append(row)
    return out


def _run_daily(store, now, dataset, table, last, fetchers) -> JobResult:
    last_iso = last.isoformat() if last else None
    total = 0
    try:
        tracked = {c["stock_id"] for c in store.tracked_companies()}
        for d in dates_to_fetch(last, now):
            raw = [list(fetch(d)) for fetch in fetchers]
            empty = [name for name, r in zip(MARKET_NAMES, raw) if not r]
            if empty and len(empty) < len(raw):
                # 只有部分市場已公布：整天不寫，下次再補
                msg = f"partial: {'、'.join(empty)} not yet published for {d.isoformat()}"
                log.warning("%s %s", dataset, msg)
                return JobResult(dataset, "ok", last_iso, total, msg)
            rows = _prepare([x for r in raw for x in r], tracked)
            if not rows:
                continue  # 休市日
            total += store.upsert(table, rows, ON_CONFLICT)
            last_iso = d.isoformat()
    except Exception as e:
        log.exception("%s 同步失敗", dataset)
        return JobResult(dataset, "failed", last_iso, total, str(e))
    return JobResult(dataset, "ok", last_iso, total)


def sync_quotes(store, now: datetime,
                fetchers: tuple[Callable, Callable] = (twse.fetch_quotes, tpex.fetch_quotes)) -> JobResult:
    try:
        last = _last(store, "daily_quotes", "trade_date", {"market": "上市"})
    except Exception as e:
        log.exception("quotes 同步失敗")
        return JobResult("quotes", "failed", None, 0, str(e))
    return _run_daily(store, now, "quotes", "daily_quotes", last, fetchers)


def sync_institutional(store, now: datetime,
                       fetchers: tuple[Callable, Callable] = (twse.fetch_institutional,
                                                              tpex.fetch_institutional)) -> JobResult:
    try:
        last = _last(store, "smart_money_flow", "trade_date")
    except Exception as e:
        log.exception("institutional 同步失敗")
        return JobResult("institutional", "failed", None, 0, str(e))
    return _run_daily(store, now, "institutional", "smart_money_flow", last, fetchers)


def sync_emerging(store, now: datetime, fetcher: Callable = tpex.fetch_emerging) -> JobResult:
    prev_iso = None  # 供失敗時回報
    try:
        prev_iso = store.last_value("daily_quotes", "trade_date", {"market": "興櫃"})
        quotes = fetcher()
        if not quotes:
            return JobResult("emerging", "ok", prev_iso, 0)
        day = max(x.trade_date for x in quotes)
        if day == now.date() and now.hour < 15:
            return JobResult("emerging", "ok", prev_iso, 0)  # 盤中資料不寫
        tracked = {c["stock_id"] for c in store.tracked_companies()}
        rows = _prepare([x for x in quotes if x.trade_date == day], tracked)
        n = store.upsert("daily_quotes", rows, ON_CONFLICT) if rows else 0
        return JobResult("emerging", "ok", day.isoformat(), n)
    except Exception as e:
        log.exception("emerging 同步失敗")
        return JobResult("emerging", "failed", prev_iso, 0, str(e))


# ---- 月營收與除權息 ----
def months_to_fetch(last: str | None, today: date, backfill_months: int = 13) -> list[tuple[int, int]]:
    """(民國年, 月) 清單：從 last 前一個月到今天的上個月；last 為 None 時回溯 backfill_months 個月。"""
    end = today.year * 12 + today.month - 2  # 上個月，以 年*12+(月-1) 表示
    if last:
        y, m = last.split("/")
        start = (int(y) + 1911) * 12 + int(m) - 1 - 1
    else:
        start = end - backfill_months + 1
    return [((i // 12) - 1911, i % 12 + 1) for i in range(start, end + 1)]


def month_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """切成每段都在同一個日曆月內的區間。"""
    out, d = [], start
    while d <= end:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        out.append((d, min(end, nxt - timedelta(days=1))))
        d = nxt
    return out


def sync_revenue(store, now: datetime, fetcher: Callable = mops.fetch_revenue) -> JobResult:
    last = None
    total = 0
    try:
        last = store.last_value("growth_momentum", "data_month")
        written = last
        for y, m in months_to_fetch(last, now.date()):
            items = [x for market in ("sii", "otc", "rotc") for x in fetcher(y, m, market)]
            if not items:
                continue  # 尚未公布
            rows = _prepare(items, set(), "data_month", filter_rows=False)
            total += store.upsert("growth_momentum", rows, "stock_id,data_month")
            written = f"{y}/{m:02d}"
    except Exception as e:
        log.exception("revenue 同步失敗")
        return JobResult("revenue", "failed", last, total, str(e))
    return JobResult("revenue", "ok", written, total)


def sync_ex_rights(store, now: datetime,
                   fetchers: tuple[Callable, Callable] = (twse.fetch_ex_rights, tpex.fetch_ex_rights)) -> JobResult:
    last_iso = None
    total = 0
    try:
        last_iso = store.last_value("ex_rights", "ex_date")
        today = now.date()
        start = date.fromisoformat(last_iso) - timedelta(days=7) if last_iso else today - timedelta(days=400)
        tracked = {c["stock_id"] for c in store.tracked_companies()}
        for a, b in month_chunks(start, today):
            rows = _prepare([x for f in fetchers for x in f(a, b)], tracked, "ex_date")
            if not rows:
                continue
            total += store.upsert("ex_rights", rows, "stock_id,ex_date")
            last_iso = max([last_iso or "", *(r["ex_date"] for r in rows)])
    except Exception as e:
        log.exception("ex_rights 同步失敗")
        return JobResult("ex_rights", "failed", last_iso, total, str(e))
    return JobResult("ex_rights", "ok", last_iso, total)
