"""全市場趨勢快照：把資料庫讀回的列整理成各股區間漲跌、除權息標記與訊號，並做記憶體快取。"""
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable

import database
from signals import company_signals
from sync.parse import months_back
from trends import PERIODS, ex_kind_in_period, period_return, trading_dates


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        grouped[r["stock_id"]].append(r)
    return grouped


def build_snapshot(quotes: list[dict], ex_rows: list[dict],
                   flows: list[dict], revenue: list[dict]) -> dict:
    dates = trading_dates(quotes)
    latest = dates[0] if dates else None
    quotes_by = _group(quotes)
    ex_by = _group(ex_rows)
    flows_by = _group(flows)
    rev_by = _group(revenue)

    returns: dict = {}
    ex: dict = {}
    signals: dict = {}
    for sid, rows in quotes_by.items():
        closes = {r["trade_date"]: r.get("close") for r in rows}
        volumes = {r["trade_date"]: r.get("volume") for r in rows}
        today_pct = next((r.get("change_pct") for r in rows if r["trade_date"] == latest), None)
        events = ex_by.get(sid, [])
        returns[sid] = {n: period_return(n, dates, closes, today_pct, events) for n in PERIODS}
        ex[sid] = {n: ex_kind_in_period(n, dates, events) for n in PERIODS}
        trust = {r["trade_date"]: r.get("trust_net") for r in flows_by.get(sid, [])}
        signals[sid] = company_signals(dates, trust, rev_by.get(sid, []), volumes)

    return {"dates": dates, "latest_date": latest,
            "returns": returns, "ex": ex, "signals": signals}


class SnapshotCache:
    """TTL 快取；過期後重載失敗時回舊值，沒有舊值才把例外丟出。"""

    def __init__(self, loader: Callable[[], dict], ttl: float = 600,
                 clock: Callable[[], float] = time.monotonic):
        self._loader = loader
        self._ttl = ttl
        self._clock = clock
        self._value: dict | None = None
        self._loaded_at = 0.0

    def get(self) -> dict:
        now = self._clock()
        if self._value is not None and now - self._loaded_at < self._ttl:
            return self._value
        try:
            self._value = self._loader()
            self._loaded_at = now
        except Exception:
            if self._value is None:
                raise
        return self._value


def load_snapshot(today: date | None = None) -> dict:
    today = today or date.today()
    since = (today - timedelta(days=45)).isoformat()
    # 營收讀近 14 個月（本月往回推 14 個月的月初）
    since_month = months_back(today, 14)
    ids = database.fetch_all_company_ids()
    return build_snapshot(
        database.fetch_quotes_since(ids, since),
        database.fetch_ex_rights_since(ids, since),
        database.fetch_flows_since(ids, since),
        database.fetch_revenue_since(ids, since_month),
    )


snapshot_cache = SnapshotCache(load_snapshot)
