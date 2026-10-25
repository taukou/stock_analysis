import csv
from datetime import datetime

import audit_stock_ids as a
from sync.models import Quote


def _q(sid, name, market):
    return Quote(sid, name, None, market, None, None, None, None, None, None, None)


OFFICIAL = {"2330": ("台積電", "上市"), "3008": ("大立光", "上市"), "6488": ("環球晶", "上櫃")}


def co(sid, name, market):
    return {"stock_id": sid, "company_name": name, "market_type": market}


def test_audit_three_issues_and_clean():
    comps = [
        co("2330", "台積電 ", "上市"),      # 相符（strip）
        co("9999", "不存在", "上市"),        # not_found
        co("3008", "大立", "上市"),          # name_mismatch
        co("6488", "環球晶", "上市"),        # market_mismatch
    ]
    res = {r["stock_id"]: r for r in a.audit(comps, OFFICIAL)}
    assert set(res) == {"9999", "3008", "6488"}
    assert res["9999"]["issue"] == "not_found" and res["9999"]["official_name"] == ""
    assert res["3008"]["issue"] == "name_mismatch"
    assert res["3008"]["official_name"] == "大立光"
    assert res["6488"]["issue"] == "market_mismatch"
    assert res["6488"]["official_market"] == "上櫃" and res["6488"]["db_market"] == "上市"


def test_name_beats_market():
    r = a.audit([co("6488", "X", "上市")], OFFICIAL)
    assert len(r) == 1 and r[0]["issue"] == "name_mismatch"


def test_latest_official_walks_back():
    calls = []

    def tw(d):
        calls.append(d)
        return [_q("2330", "台積電", "上市")] if d.isoformat() == "2026-10-22" else []

    def tp(d):
        return [_q("6488", "環球晶", "上櫃")] if d.isoformat() == "2026-10-22" else []

    now = datetime(2026, 10, 25, 16)  # 週日
    off = a.latest_official(now, fetchers=(tw, tp, lambda: [_q("1234", "興", "興櫃")]))
    assert off == {"2330": ("台積電", "上市"), "6488": ("環球晶", "上櫃"), "1234": ("興", "興櫃")}
    assert all(d.weekday() < 5 for d in calls)
    assert calls[0].isoformat() == "2026-10-23"


def test_latest_official_skips_today_before_15():
    seen = []

    def tw(d):
        seen.append(d)
        return [_q("1", "a", "上市")]

    a.latest_official(datetime(2026, 10, 23, 10),
                      fetchers=(tw, lambda d: [_q("2", "b", "上櫃")], lambda: []))
    assert seen[0].isoformat() == "2026-10-22"


def test_latest_official_none_found():
    assert a.latest_official(datetime(2026, 10, 23, 16),
                             fetchers=(lambda d: [], lambda d: [], lambda: [])) is None


def test_write_csv_header_and_bom(tmp_path):
    p = tmp_path / "sub" / "x.csv"
    a.write_csv([], p)
    assert p.read_bytes().startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert rows == [["stock_id", "db_name", "official_name", "db_market", "official_market", "issue"]]
