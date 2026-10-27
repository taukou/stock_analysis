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


def test_cache_backs_off_after_failure():
    t = [0.0]; calls = []
    def loader():
        calls.append(1)
        if len(calls) >= 2: raise RuntimeError("down")
        return {"n": 1}
    c = SnapshotCache(loader, ttl=600, clock=lambda: t[0], backoff=60)
    c.get()
    t[0] = 700; assert c.get() == {"n": 1} and len(calls) == 2   # 失敗 → 舊值
    t[0] = 730; assert c.get() == {"n": 1} and len(calls) == 2   # backoff 內不重試
    t[0] = 761; assert c.get() == {"n": 1} and len(calls) == 3   # backoff 過後再試一次


def test_cold_failure_backs_off_and_reraises():
    t = [0.0]; calls = []
    def loader():
        calls.append(1)
        raise RuntimeError("down")
    c = SnapshotCache(loader, clock=lambda: t[0], backoff=60)
    with pytest.raises(RuntimeError): c.get()
    t[0] = 30
    with pytest.raises(RuntimeError): c.get()
    assert len(calls) == 1
    t[0] = 61
    with pytest.raises(RuntimeError): c.get()
    assert len(calls) == 2


def test_stale_served_while_reload_in_flight():
    import threading
    t = [0.0]; started = threading.Event(); release = threading.Event(); calls = []
    def loader():
        calls.append(1)
        if len(calls) == 2:
            started.set(); release.wait(5)
        return {"n": len(calls)}
    c = SnapshotCache(loader, ttl=600, clock=lambda: t[0])
    c.get()
    t[0] = 700
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("a", c.get()))
    th.start()
    assert started.wait(5)
    assert c.get() == {"n": 1}            # 重載進行中：第二個呼叫者立刻拿舊值
    assert len(calls) == 2                # 沒有重複重載
    release.set(); th.join(5)
    assert out["a"] == {"n": 2} and c.get() == {"n": 2}


def test_cold_start_single_flight():
    import threading
    started = threading.Event(); release = threading.Event(); calls = []
    def loader():
        calls.append(1)
        started.set(); release.wait(5)
        return {"n": len(calls)}
    c = SnapshotCache(loader, clock=lambda: 0.0)
    results = []
    ths = [threading.Thread(target=lambda: results.append(c.get())) for _ in range(3)]
    for th in ths: th.start()
    assert started.wait(5)
    release.set()
    for th in ths: th.join(5)
    assert results == [{"n": 1}] * 3 and len(calls) == 1

def test_flow_sums_use_flow_dates_and_keep_none():
    # 股價有 7 天，法人只有較早 5 天（比股價少最近兩天）
    quotes = [q("2330", f"2026-09-{d:02d}", 100.0) for d in range(10, 17)]
    fl = lambda sid, d, tr, fo: {"stock_id": sid, "trade_date": d, "trust_net": tr, "foreign_net": fo}
    flows = [fl("2330", f"2026-09-{d:02d}", 1000, 2000) for d in range(10, 15)]
    flows.append(fl("2317", "2026-09-14", None, None))
    flows.append(fl("2454", "2026-09-10", 500, None))
    s = build_snapshot(quotes, [], flows, [])
    assert s["flow_date"] == "2026-09-14"
    assert s["flows"]["2330"][1] == {"foreign": 2000, "trust": 1000}
    assert s["flows"]["2330"][5] == {"foreign": 10000, "trust": 5000}
    assert s["flows"]["2317"][5] == {"foreign": None, "trust": None}
    assert s["flows"]["2454"][1] == {"foreign": None, "trust": None}   # 視窗內無列
    assert s["flows"]["2454"][5] == {"foreign": None, "trust": 500}
