"""每日產業指數更新：依資料庫報價把等權指數往後接到今天。"""
import logging
from datetime import date, datetime, timedelta

from industry_index import (MARKET_KEY, average_return, closes_by_stock,
                            index_row, members_hash, scope_members,
                            step_forward, stock_returns)
from sync.jobs import JobResult
from trends import trading_dates

log = logging.getLogger(__name__)

DATASET = "industry_index"
TABLE = "industry_index_daily"
ON_CONFLICT = "scope_kind,scope_id,trade_date"
SCOPE_TABLE = "industry_index_scopes"
SCOPE_CONFLICT = "scope_kind,scope_id"
EARLIEST = "2000-01-01"
LOOKBACK_DAYS = 14


def _by_date(quotes: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for q in quotes:
        out.setdefault(q["trade_date"], []).append(q)
    return out


def _ex_by_date(ex_rows: list[dict]) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for r in ex_rows:
        out.setdefault(r["ex_date"], {})[r["stock_id"]] = r.get("ref_price")
    return out


def _chain(dates: list[str], by_date, ex_by_date, scopes: dict, levels=None,
           prev=None) -> list[dict]:
    """逐日接指數。scopes: key -> 成分（None 為大盤）。

    levels 為前一日點位（None 代表從頭：第一個交易日 100）；prev 為前一日收盤價。
    """
    rows: list[dict] = []
    levels = dict(levels) if levels else None
    prev = prev or {}
    for d in dates:
        close = closes_by_stock(by_date.get(d, []))
        if levels is None:
            levels = {k: 100.0 for k in scopes}
            rows += [index_row(k, d, 100.0, None, 0) for k in scopes]
        else:
            rets = stock_returns(prev, close, ex_by_date.get(d, {}))
            for k, members in scopes.items():
                if k not in levels:
                    continue
                ret, n = average_return(rets, members)
                levels[k] = step_forward(levels[k], ret)
                rows.append(index_row(k, d, levels[k], ret, n))
        prev = close
    return rows


def sync_index(store, now: datetime) -> JobResult:
    try:
        today = now.date().isoformat()
        last = store.last_value(TABLE, "trade_date", {"scope_kind": MARKET_KEY[0]})
        mapping = scope_members(store.chain_mapping())
        if last is None:
            new_keys = list(mapping)   # 第一次執行：全部範圍都登錄
        else:
            registered = store.index_scope_keys()
            new_keys = [k for k in mapping if k not in registered]

        start = EARLIEST if last is None else (
            date.fromisoformat(last) - timedelta(days=LOOKBACK_DAYS)).isoformat()
        quotes = store.quotes_between(start, today)
        dates = sorted(trading_dates(quotes))
        by_date = _by_date(quotes)
        ex_by_date = _ex_by_date(store.ex_rights_between(start, today))

        rows: list[dict] = []
        if last is None:
            rows = _chain(dates, by_date, ex_by_date, {MARKET_KEY: None, **mapping})
        else:
            old_dates = [d for d in dates if d <= last]
            todo = [d for d in dates if d > last]
            if todo and old_dates:
                prev_levels = {(r["scope_kind"], r["scope_id"]): r["level"]
                               for r in store.index_rows_on(last)}
                scopes = {MARKET_KEY: None}
                scopes.update({k: m for k, m in mapping.items() if k not in new_keys})
                rows = _chain(todo, by_date, ex_by_date, scopes, levels=prev_levels,
                              prev=closes_by_stock(by_date.get(old_dates[-1], [])))
            if new_keys:   # 新範圍：從資料庫最早交易日以 100 起算到今天
                ids = sorted(set().union(*(mapping[k] for k in new_keys)))
                nq = store.quotes_between(EARLIEST, today, ids=ids)
                rows += _chain(sorted(trading_dates(nq)), _by_date(nq),
                               _ex_by_date(store.ex_rights_between(EARLIEST, today)),
                               {k: mapping[k] for k in new_keys})

        written = store.upsert(TABLE, rows, ON_CONFLICT)
        if new_keys:
            store.upsert(SCOPE_TABLE, [
                {"scope_kind": k[0], "scope_id": k[1],
                 "members_hash": members_hash(mapping[k]),
                 "member_count": len(mapping[k])} for k in new_keys], SCOPE_CONFLICT)
        latest = max((r["trade_date"] for r in rows), default=last)
        return JobResult(DATASET, "ok", latest, written)
    except Exception as e:
        log.exception("指數更新失敗")
        return JobResult(DATASET, "failed", None, 0, f"{type(e).__name__}: {e}")
