"""股票代號稽核：比對 companies 與交易所官方名稱／市場，輸出 CSV 報告（唯讀，不改資料庫）。"""
import csv
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from sync.logsetup import setup_logging
from sync.sources import tpex, twse
from sync.store import make_store

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "reports" / "stock_id_audit.csv"
FIELDS = ["stock_id", "db_name", "official_name", "db_market", "official_market", "issue"]
log = logging.getLogger("audit")


def audit(companies: list[dict], official: dict[str, tuple[str, str]]) -> list[dict]:
    """每家公司最多回報一個問題：not_found > name_mismatch > market_mismatch。"""
    out = []
    for c in companies:
        sid = c["stock_id"]
        db_name = (c.get("company_name") or "").strip()
        db_market = c.get("market_type") or ""
        row = {"stock_id": sid, "db_name": db_name, "official_name": "",
               "db_market": db_market, "official_market": "", "issue": ""}
        if sid not in official:
            row["issue"] = "not_found"
        else:
            name, market = official[sid]
            row["official_name"], row["official_market"] = name, market
            if name.strip() != db_name:
                row["issue"] = "name_mismatch"
            elif market != db_market:
                row["issue"] = "market_mismatch"
        if row["issue"]:
            out.append(row)
    return out


def _candidate_dates(now: datetime, max_back: int = 7):
    d = now.date() if now.hour >= 15 else now.date() - timedelta(days=1)
    for _ in range(max_back + 1):
        if d.weekday() < 5:
            yield d
        d -= timedelta(days=1)


def latest_official(now: datetime, fetchers=None) -> dict[str, tuple[str, str]] | None:
    """找最近一個上市與上櫃都有資料的日期，並併入興櫃。找不到回傳 None。"""
    fetch_twse, fetch_tpex, fetch_emerging = fetchers or (
        twse.fetch_quotes, tpex.fetch_quotes, tpex.fetch_emerging)
    for d in _candidate_dates(now):
        try:
            a, b = fetch_twse(d), fetch_tpex(d)
        except Exception:
            log.exception("抓取 %s 行情失敗", d)
            continue
        if a and b:
            official = {q.stock_id: (q.name, q.market) for q in [*a, *b]}
            for q in fetch_emerging():
                official.setdefault(q.stock_id, (q.name, q.market))
            return official
    return None


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    setup_logging("audit", base_dir=ROOT)
    official = latest_official(datetime.now())
    if official is None:
        log.error("找不到近 7 天內上市與上櫃皆有資料的交易日")
        return 1
    companies = make_store().tracked_companies()
    rows = audit(companies, official)
    write_csv(rows, CSV_PATH)
    print(f"問題數: {len(rows)}")
    print(f"報告: {CSV_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
