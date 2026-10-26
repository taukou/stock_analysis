import pytest
from snapshot import build_snapshot, SnapshotCache

def q(sid, d, close, pct=None, market="上市", vol=1000):
    return {"stock_id": sid, "trade_date": d, "market": market, "close": close, "change_pct": pct, "volume": vol}

def test_build_snapshot_returns_and_emerging():
    days = ["2026-09-22", "2026-09-19", "2026-09-18", "2026-09-17", "2026-09-16", "2026-09-15"]
    quotes = [q("2330", d, 100.0 + i, 0.5) for i, d in enumerate(reversed(days))]
    quotes.append(q("6999", "2026-09-22", 50.0, 1.2, market="興櫃"))
    s = build_snapshot(quotes, [], [], [])
    assert s["dates"][0] == "2026-09-22" and s["latest_date"] == "2026-09-22"
    assert s["returns"]["2330"][1] == 0.5
    assert s["returns"]["2330"][5] == 5.0      # 105 / 100 − 1
    assert s["returns"]["6999"] == {1: 1.2, 5: None, 20: None}

def test_cache_ttl_and_stale_on_error():
    t = [0.0]; calls = []
    def loader():
        calls.append(1)
        if len(calls) == 2: raise RuntimeError("down")
        return {"n": len(calls)}
    c = SnapshotCache(loader, ttl=600, clock=lambda: t[0])
    assert c.get() == {"n": 1}
    t[0] = 100; assert c.get() == {"n": 1} and len(calls) == 1
    t[0] = 700; assert c.get() == {"n": 1}            # loader 失敗 → 回舊值
    t[0] = 1400; assert c.get() == {"n": 3}

def test_cache_raises_without_stale():
    c = SnapshotCache(lambda: (_ for _ in ()).throw(RuntimeError("down")), clock=lambda: 0.0)
    with pytest.raises(RuntimeError):
        c.get()
