"""等權產業指數的純計算模組（不含資料庫或 Supabase 相依）。

缺值一律略過或回傳 None，絕不以 0 代替。指數只算 上市／上櫃。
"""
import hashlib
import re
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent

MARKET_KEY = ("market", "TW")
LISTED_MARKETS = ("上市", "上櫃")

_MARKET_STOCK = re.compile(r"^(?!00)\d{4}$")


def is_market_stock(stock_id: str) -> bool:
    """大盤成分：4 位數代號且不以 00 開頭（排除 ETF、權證、特別股等）。"""
    return bool(_MARKET_STOCK.match(stock_id or ""))


def scope_members(mapping: list[dict]) -> dict[tuple[str, str], frozenset[str]]:
    """依節點對應產生各範圍（產業／階層／節點）的成分股集合，不含大盤。"""
    acc: dict[tuple[str, str], set[str]] = {}
    for r in mapping:
        sid = r["stock_id"]
        keys = (
            ("major", r["major_id"]),
            ("tier", f"{r['major_id']}:{r['position_type']}"),
            ("node", r["node_id"]),
        )
        for k in keys:
            acc.setdefault(k, set()).add(sid)
    return {k: frozenset(v) for k, v in acc.items()}


def members_hash(members: frozenset[str]) -> str:
    """成分股集合的雜湊（與順序無關）。"""
    return hashlib.sha1(",".join(sorted(members)).encode("utf-8")).hexdigest()


def closes_by_stock(quotes: list[dict]) -> dict[str, float]:
    """取 上市／上櫃 且收盤價非 None 且 > 0 的收盤價。"""
    out: dict[str, float] = {}
    for q in quotes:
        c = q.get("close")
        if q.get("market") in LISTED_MARKETS and c is not None and c > 0:
            out[q["stock_id"]] = c
    return out


def stock_returns(
    prev_close: dict[str, float],
    close: dict[str, float],
    ex_ref: dict[str, float | None],
) -> dict[str, float]:
    """個股單日報酬（小數）；除權息日以參考價為基準，缺價則略過該股。"""
    out: dict[str, float] = {}
    for sid, c in close.items():
        if sid in ex_ref:
            base = ex_ref[sid]
            if base is None or base <= 0:
                continue
        else:
            base = prev_close.get(sid)
            if base is None or base <= 0:
                continue
        out[sid] = c / base - 1
    return out


def average_return(
    returns: dict[str, float], members: Iterable[str] | None
) -> tuple[float | None, int]:
    """成分股等權平均報酬與納入檔數；members 為 None 代表大盤。無資料回傳 (None, 0)。"""
    if members is None:
        vals = [r for sid, r in returns.items() if is_market_stock(sid)]
    else:
        vals = [returns[sid] for sid in set(members) if sid in returns]
    if not vals:
        return None, 0
    return sum(vals) / len(vals), len(vals)


def step_forward(level: float, ret: float | None) -> float:
    """由前一日點位推下一日點位；ret 為 None 時持平。"""
    return level if ret is None else level * (1 + ret)


def step_backward(next_level: float, next_ret: float | None) -> float:
    """由下一日點位回推前一日點位；ret 為 None 時持平。"""
    return next_level if next_ret is None else next_level / (1 + next_ret)


def index_row(key: tuple[str, str], trade_date: str, level: float,
              ret: float | None, n: int) -> dict:
    """組成 industry_index_daily 的一列。"""
    return {
        "scope_kind": key[0],
        "scope_id": key[1],
        "trade_date": trade_date,
        "level": round(level, 6),
        "ret_pct": None if ret is None else round(ret * 100, 4),
        "members": n,
    }
