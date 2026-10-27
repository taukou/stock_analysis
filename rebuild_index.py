"""重算所有產業指數：成分股變動後執行，從一年前以 100 起算，全部算完才一次寫入。"""
import logging
import sys
from datetime import datetime, timedelta

from industry_index import MARKET_KEY, members_hash, scope_members
from sync.index_backfill import BACKFILL_DAYS, FetchError, fetch_day
from sync.index_job import (ON_CONFLICT, SCOPE_CONFLICT, SCOPE_TABLE, TABLE,
                            _by_date, _chain, _ex_by_date)
from sync.logsetup import setup_logging
from sync.sources import tpex, twse
from sync.store import make_store

ROOT = __import__("pathlib").Path(__file__).resolve().parent
log = logging.getLogger("rebuild_index")


def rebuild(store, now: datetime, fetchers=(twse.fetch_quotes, tpex.fetch_quotes)) -> int:
    """回傳寫入列數；失敗（不寫任何列）回傳 -1。"""
    try:
        today = now.date()
        start = today - timedelta(days=BACKFILL_DAYS)
        quotes: list[dict] = []
        dates: list[str] = []
        d = start
        while d <= today:
            if d.weekday() < 5:
                day = fetch_day(fetchers, d)
                if day is not None:
                    quotes += day
                    dates.append(d.isoformat())
            d += timedelta(days=1)
        if not dates:
            log.error("一年內抓不到任何行情")
            return -1
        mapping = scope_members(store.chain_mapping())
        ex = _ex_by_date(store.ex_rights_between(start.isoformat(), today.isoformat()))
        rows = _chain(dates, _by_date(quotes), ex, {MARKET_KEY: None, **mapping})
        written = store.upsert(TABLE, rows, ON_CONFLICT)
        store.upsert(SCOPE_TABLE, [
            {"scope_kind": k[0], "scope_id": k[1], "members_hash": members_hash(m),
             "member_count": len(m)} for k, m in mapping.items()], SCOPE_CONFLICT)
        return written
    except FetchError as e:
        log.error("重算中止，未寫入任何列：%s", e)
        return -1
    except Exception:
        log.exception("重算失敗")
        return -1


def main() -> int:
    setup_logging("rebuild_index", base_dir=ROOT)
    try:
        store = make_store()
    except Exception:
        log.exception("無法建立資料庫連線")
        return 1
    n = rebuild(store, datetime.now())
    if n < 0:
        return 1
    log.info("重算完成，寫入 %d 列", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
