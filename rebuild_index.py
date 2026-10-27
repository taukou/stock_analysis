"""重算所有產業指數：成分股變動後執行，從一年前以 100 起算。

全部算完才開始寫入（分批）；抓取失敗不寫任何列，寫入中斷則重跑一次即可修復。
"""
import logging
import sys
from datetime import datetime, timedelta

from industry_index import MARKET_KEY, members_hash, scope_members, step_backward
from sync.index_backfill import BACKFILL_DAYS, FetchError, fetch_day
from sync.index_job import (ON_CONFLICT, SCOPE_CONFLICT, SCOPE_TABLE, TABLE,
                            _by_date, _chain, _ex_by_date)
from sync.logsetup import setup_logging
from sync.sources import tpex, twse
from sync.store import make_store

ROOT = __import__("pathlib").Path(__file__).resolve().parent
log = logging.getLogger("rebuild_index")


def _rescale_older(store, first: str, keys: set, rows: list[dict]) -> list[dict]:
    """重算起點之前的舊列（不刪除）：由新起點 100 起，依各列自己的 ret_pct 往回推。

    只用不隨點位改變的 ret_pct 推算，所以重跑（含寫入中斷後）結果完全相同。
    起點日的 ret_pct／members 沿用舊列（新鏈沒有前一日收盤可算）。
    """
    older = [r for r in store.index_rows_between("2000-01-01", first)
             if (r["scope_kind"], r["scope_id"]) in keys]
    by_key: dict[tuple, list[dict]] = {}
    for r in older:
        by_key.setdefault((r["scope_kind"], r["scope_id"]), []).append(r)
    out = []
    carried = {}
    for k, lst in by_key.items():
        lst.sort(key=lambda r: r["trade_date"], reverse=True)
        if lst[0]["trade_date"] != first:
            log.warning("範圍 %s 在 %s 沒有舊列，無法接上舊歷史，略過", k, first)
            continue
        carried[k] = lst[0]
        level, ret = 100.0, lst[0]["ret_pct"]
        for r in lst[1:]:
            level = step_backward(level, None if ret is None else ret / 100)
            out.append({**r, "level": round(level, 6)})
            ret = r["ret_pct"]
    for row in rows:
        k = (row["scope_kind"], row["scope_id"])
        if k in carried and row["trade_date"] == first:
            row["ret_pct"] = carried[k]["ret_pct"]
            row["members"] = carried[k]["members"]
    return out


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
        scopes = {MARKET_KEY: None, **mapping}
        rows = _chain(dates, _by_date(quotes), ex, scopes)
        rows += _rescale_older(store, dates[0], set(scopes), rows)
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
