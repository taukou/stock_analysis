"""日資料工作：行情、興櫃、法人，含補跑日期規劃。"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Literal

from sync.sources import tpex, twse

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


def _prepare(items, tracked: set[str]) -> list[dict]:
    """轉成 row、套用過濾、同日重複只留第一筆。"""
    seen, out = set(), []
    for it in items:
        row = it.to_row()
        sid = row["stock_id"]
        if not keep_row(sid, tracked):
            continue
        if sid in seen:
            log.warning("同日重複代號 %s (%s)，保留第一筆", sid, row["trade_date"])
            continue
        seen.add(sid)
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
