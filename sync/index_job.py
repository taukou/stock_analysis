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
# 每次執行重算最近 LOOKBACK 個交易日（晚到的除權息參考價、補進的報價都會被修正）
LOOKBACK = 10
# 讀報價的日曆天數：要涵蓋 LOOKBACK + 1 個交易日（含農曆年長假）
WINDOW_CALENDAR_DAYS = 45
LEVEL_TOL = 1e-5


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


def _same(a: dict, b: dict | None) -> bool:
    """重算列與資料庫既有列是否相同（點位容許四捨五入誤差）。"""
    if b is None:
        return False
    if a["ret_pct"] != b.get("ret_pct") or a["members"] != b.get("members"):
        return False
    lv = b.get("level")
    return lv is not None and abs(a["level"] - lv) <= LEVEL_TOL


def _resume_scope(store, key, members, today: str) -> list[dict]:
    """範圍在最新日沒有列時，由它自己最後一列的點位接續到今天。"""
    lr = store.index_last_row(key)
    if lr is None:
        log.warning("範圍 %s 已登錄但沒有任何指數列，略過", key)
        return []
    start = (date.fromisoformat(lr["trade_date"]) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    q = store.quotes_between(start, today)
    ds = sorted(trading_dates(q))
    old = [d for d in ds if d <= lr["trade_date"]]
    todo = [d for d in ds if d > lr["trade_date"]]
    if not todo:
        return []
    if not old:
        log.warning("範圍 %s 找不到 %s 的報價，無法接續", key, lr["trade_date"])
        return []
    return _chain(todo, _by_date(q), _ex_by_date(store.ex_rights_between(start, today)),
                  {key: members}, levels={key: lr["level"]},
                  prev=closes_by_stock(_by_date(q).get(old[-1], [])))


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
            date.fromisoformat(last) - timedelta(days=WINDOW_CALENDAR_DAYS)).isoformat()
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
            if todo and not old_dates:
                return JobResult(DATASET, "failed", None, 0,
                                 f"找不到 {last} 以前的報價，無法接續指數")
            # 重算視窗：最近 LOOKBACK 個已算交易日 + 新交易日，由視窗前一日（錨點）的點位接起
            anchor_i = max(0, len(old_dates) - LOOKBACK - 1)
            anchor = old_dates[anchor_i] if old_dates else None
            window = old_dates[anchor_i + 1:] + todo
            prev_levels = ({(r["scope_kind"], r["scope_id"]): r["level"]
                            for r in store.index_rows_on(anchor)} if anchor else {})
            if window and MARKET_KEY not in prev_levels:
                return JobResult(DATASET, "failed", None, 0,
                                 f"錨點 {anchor} 沒有大盤指數列，無法重算")
            normal = {k: m for k, m in mapping.items()
                      if k not in new_keys and k in prev_levels}
            # 已登錄但錨點日沒有列的範圍（曾移出成分表又回來等）：由各自最後一列接續
            stale = [k for k in mapping if k not in new_keys and k not in prev_levels]
            if window:
                scopes = {MARKET_KEY: None, **normal}
                fresh = _chain(window, by_date, ex_by_date, scopes, levels=prev_levels,
                               prev=closes_by_stock(by_date.get(anchor, [])))
                stored = {(r["scope_kind"], r["scope_id"], r["trade_date"]): r
                          for r in store.index_rows_between(window[0], today)}
                # 只寫有變動的列：重跑無新資料時不寫任何列（冪等）
                rows = [r for r in fresh if not _same(
                    r, stored.get((r["scope_kind"], r["scope_id"], r["trade_date"])))]
            for k in stale:
                rows += _resume_scope(store, k, mapping[k], today)
            if new_keys:   # 新範圍：用全市場交易日曆，從資料庫最早交易日以 100 起算到今天
                allq = store.quotes_between(EARLIEST, today)
                cal = sorted(trading_dates(allq))
                ids = set().union(*(mapping[k] for k in new_keys))
                mq = [q for q in allq if q["stock_id"] in ids]
                rows += _chain(cal, _by_date(mq),
                               _ex_by_date(store.ex_rights_between(EARLIEST, today)),
                               {k: mapping[k] for k in new_keys})

        written = store.upsert(TABLE, rows, ON_CONFLICT)
        if new_keys:
            store.upsert(SCOPE_TABLE, [
                {"scope_kind": k[0], "scope_id": k[1],
                 "members_hash": members_hash(mapping[k]),
                 "member_count": len(mapping[k])} for k in new_keys], SCOPE_CONFLICT)
        latest = max([r["trade_date"] for r in rows] + ([last] if last else []),
                     default=None)
        return JobResult(DATASET, "ok", latest, written)
    except Exception as e:
        log.exception("指數更新失敗")
        return JobResult(DATASET, "failed", None, 0, f"{type(e).__name__}: {e}")
