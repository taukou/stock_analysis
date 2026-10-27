"""往前補抓產業指數：以交易所行情逐日往回延伸，每個交易日寫一次，中斷可續跑。"""
import logging
from datetime import date, datetime, timedelta
from typing import Callable

from industry_index import (MARKET_KEY, average_return, closes_by_stock,
                            index_row, is_market_stock, scope_members,
                            step_backward, stock_returns)
from sync.index_job import ON_CONFLICT, TABLE, _ex_by_date
from sync.jobs import JobResult
from sync.sources import tpex, twse

log = logging.getLogger(__name__)

DATASET = "index_backfill"
BACKFILL_DAYS = 365


class FetchError(Exception):
    """抓取失敗，或只有一個市場有資料（無法判斷是否休市）。"""


def fetch_day(fetchers, d: date) -> list[dict] | None:
    """抓某日兩市場行情；兩市場皆空（休市）回傳 None；一邊空或例外 raise FetchError。"""
    try:
        raw = [list(f(d)) for f in fetchers]
    except Exception as e:
        raise FetchError(f"{d.isoformat()} 抓取失敗：{type(e).__name__}: {e}") from e
    empty = [not r for r in raw]
    if all(empty):
        return None
    if any(empty):
        raise FetchError(f"{d.isoformat()} 只有一個市場有資料（版面可能變更）")
    return [q.to_row() for r in raw for q in r]


def prev_trading_day(fetchers, m: date, max_holiday_run: int) -> tuple[date, list[dict]]:
    """往前找 m 之前最近的交易日；回傳 (日期, 行情)。連續空太多個工作日則 raise。"""
    d, empty_run = m, 0
    while True:
        d -= timedelta(days=1)
        if d.weekday() >= 5:
            continue
        quotes = fetch_day(fetchers, d)
        if quotes is not None:
            return d, quotes
        empty_run += 1
        if empty_run > max_holiday_run:
            raise FetchError(f"{m.isoformat()} 之前連續 {empty_run} 個工作日無資料")


def backfill_index(store, now: datetime,
                   fetchers: tuple[Callable, Callable] = (twse.fetch_quotes, tpex.fetch_quotes),
                   max_days: int = 260, max_holiday_run: int = 15) -> JobResult:
    earliest: str | None = None
    written = 0
    try:
        first = store.first_value(TABLE, "trade_date", {"scope_kind": MARKET_KEY[0]})
        if first is None:
            return JobResult(DATASET, "ok", None, 0, "尚無指數，等每日更新先建立")
        m = date.fromisoformat(first)
        earliest = first
        target = now.date() - timedelta(days=BACKFILL_DAYS)
        if m <= target:
            return JobResult(DATASET, "ok", first, 0)

        mapping = scope_members(store.chain_mapping())
        m_quotes = store.quotes_between(m.isoformat(), m.isoformat())
        if not closes_by_stock(m_quotes):
            m_quotes = fetch_day(fetchers, m)
            if m_quotes is None:
                raise FetchError(f"{m.isoformat()} 沒有行情，無法接縫")

        for _ in range(max_days):
            if m <= target:
                break
            d, d_quotes = prev_trading_day(fetchers, m, max_holiday_run)
            m_iso, d_iso = m.isoformat(), d.isoformat()
            ex = _ex_by_date(store.ex_rights_between(m_iso, m_iso)).get(m_iso, {})
            rets = stock_returns(closes_by_stock(d_quotes), closes_by_stock(m_quotes), ex)
            rows, market_rows = [], []
            for r in store.index_rows_on(m_iso):
                key = (r["scope_kind"], r["scope_id"])
                if key == MARKET_KEY:
                    members = None
                elif key in mapping:
                    members = mapping[key]
                else:
                    continue   # 已不在成分表的範圍不延伸
                ret, n = average_return(rets, members)
                pair = [index_row(key, m_iso, r["level"], ret, n),
                        index_row(key, d_iso, step_backward(r["level"], ret), None, 0)]
                (market_rows if key == MARKET_KEY else rows).extend(pair)
            # 大盤放最後：分批寫入中斷時，大盤最早日不會超前其他範圍，續跑即可補齊
            rows += market_rows
            written += store.upsert(TABLE, rows, ON_CONFLICT)
            m, m_quotes, earliest = d, d_quotes, d_iso
        return JobResult(DATASET, "ok", earliest, written)
    except FetchError as e:
        log.error("指數補抓中止：%s", e)
        return JobResult(DATASET, "failed", earliest, written, str(e))
    except Exception as e:
        log.exception("指數補抓失敗")
        return JobResult(DATASET, "failed", earliest, written, f"{type(e).__name__}: {e}")
