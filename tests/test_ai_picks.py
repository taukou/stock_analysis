import json
from datetime import datetime

import pytest

import ai_picks
import run_sync
from sync.jobs import JobResult
from tests.fakes import FakeStore

NOW = datetime(2026, 10, 27, 16, 40)


def _ctx():
    return {
        "date": "2026-10-27", "flow_date": "2026-10-27",
        "market": {"r1": -0.29, "r5": -2.3, "r20": -1.0},
        "industries": [{"major_id": "M01", "name": "半導體", "r1": -0.57, "r5": -4.05, "r20": -4.81,
                        "foreign5": -122599, "trust5": 34749, "quadrant": "落後"}],
        "strong_nodes": [{"name": "光碟機", "major_name": "電腦及週邊設備", "change": 2.23}],
        "weak_nodes": [], "flow_nodes": [],
        "stocks": [{"stock_id": "2330", "name": "台積電", "major_id": "M01", "node_id": "N1", "industry": "半導體",
                    "r1": 1.0, "r5": 2.0, "r20": None, "foreign5": 4200, "trust5": None, "signals": ["投信連買 5 日"]}],
    }


class Res:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _ok(obj, thought=None):
    parts = ([{"text": thought, "thought": True}] if thought else []) + [{"text": json.dumps(obj, ensure_ascii=False)}]
    return Res(200, {"candidates": [{"content": {"parts": parts}}]})


def test_validate_keeps_only_listed_ids_and_fills_names():
    raw = {"overview": " 資金  流向 半導體 ", "picks": [
        {"kind": "stock", "id": "2330", "reason": "外資買超", "risk": " RSI 過熱 ", "evidence": ["外資 5 日 +4,200 張", "", "a", "b"]},
        {"kind": "stock", "id": "2330", "reason": "重複", "evidence": []},
        {"kind": "stock", "id": "9999", "reason": "名單外", "evidence": []},
        {"kind": "industry", "id": "M01", "reason": "落後", "evidence": ["輪動：落後"]},
        {"kind": "industry", "id": "M99", "reason": "名單外", "evidence": []},
        "garbage",
    ]}
    out = ai_picks.validate(raw, _ctx())
    assert out["overview"] == "資金 流向 半導體"
    assert [(p["kind"], p["id"], p["name"]) for p in out["picks"]] == [("stock", "2330", "台積電"), ("industry", "M01", "半導體")]
    assert out["picks"][0]["evidence"] == ["外資 5 日 +4,200 張", "a", "b"]
    assert out["picks"][0]["risk"] == "RSI 過熱" and out["picks"][1]["risk"] == ""
    assert out["picks"][0]["node_id"] == "N1" and out["picks"][1]["node_id"] is None


def test_unverified_numbers_allows_rounding_and_units():
    src = "外資10日內買超9天、20日累計+57,414張 RSI 87 年增+38.6% 今日 -0.57%"
    assert ai_picks.unverified_numbers("外資 20 日累計 5.7 萬張、約 57,000 張，10 日買超 9 天", src) == []
    assert ai_picks.unverified_numbers("RSI 87，年增 39%，下跌 0.57%，RSI 超過 70", src) == []
    assert ai_picks.unverified_numbers("外資累計 6.2 萬張、年增 42%，RSI 88", src) == ["6.2 萬", "42", "88"]
    assert ai_picks.unverified_numbers("外資 24.3 萬張、24.4 萬張", "+243,777張") == []   # 捨去或四捨五入都可


def test_validate_drops_picks_citing_numbers_not_in_data():
    raw = {"overview": "o", "picks": [
        {"kind": "stock", "id": "2330", "reason": "外資 5 日買超 9,999 張", "risk": "", "evidence": []},
        {"kind": "industry", "id": "M01", "reason": "5 日跌 4.05%", "risk": "20 日跌 4.8%",
         "evidence": ["外資 5 日 -12.3 萬張"]},
        {"kind": "industry", "id": "M01", "reason": "重複不算刪除", "evidence": []},
    ]}
    out = ai_picks.validate(raw, _ctx())
    assert [p["id"] for p in out["picks"]] == ["M01"] and out["dropped"] == 1
    # 個股可以引用所屬產業與大盤的數字
    raw = {"overview": "o", "picks": [{"kind": "stock", "id": "2330", "reason": "外資 5 日 +4,200 張，產業 5 日 -4.05%，大盤 5 日 -2.3%",
                                       "risk": "", "evidence": []}]}
    assert ai_picks.validate(raw, _ctx())["dropped"] == 0


def test_validate_caps_picks():
    ctx = _ctx()
    ctx["stocks"] = [{**ctx["stocks"][0], "stock_id": str(1000 + i)} for i in range(8)]
    raw = {"overview": "x", "picks": [{"kind": "stock", "id": str(1000 + i), "reason": "r", "evidence": []} for i in range(8)]}
    assert len(ai_picks.validate(raw, ctx)["picks"]) == ai_picks.MAX_PICKS


def test_prompt_lists_ids_numbers_and_signals():
    text = ai_picks.build_prompt(_ctx())
    assert ("M01｜半導體｜今日 -0.57%｜5日 -4.05%｜20日 -4.81%｜60日 —｜一年 —｜離20日均 —｜離60日均 —｜"
            "外資5日累計 -122,599張｜投信5日累計 +34,749張｜輪動（8週前→現在） 落後") in text
    assert "2330 台積電｜半導體｜漲跌 今日+1.00% 5日+2.00% 20日—｜外資5日累計+4,200張 投信5日累計—｜—｜—｜—｜投信連買 5 日" in text
    assert "今日最強節點 光碟機（電腦及週邊設備）+2.23%" in text


def test_prompt_includes_all_factor_groups():
    import ai_factors as F
    ctx = _ctx()
    ctx["industries"][0].update({"r60": 5.0, "r1y": 30.0, "vs_ma20": 1.2, "vs_ma60": -0.5, "rotation": "落後→轉強"})
    ctx["stocks"][0].update({
        "node": "晶圓代工", "tier": "中游",
        "tech": {**dict.fromkeys(("ma20_gap", "above_ma60", "ma_cross", "ma_long_cross", "k", "d", "kd_cross",
                                  "macd_turn", "rsi", "breakout20", "vol_ratio")),
                 "ma20_gap": 3.2, "ma_cross": ("golden", 1), "rsi": 71},
        "flow": {"foreign_days10": 7, "trust_days10": 2, "dealer5": -50, "foreign20": 9000, "trust20": 10},
        "revenue": {"month": "115/09", "yoy": 25.0, "mom": -3.0, "acc_yoy": 18.0, "yoy_streak": 4, "accel": 6.0}})
    text = ai_picks.build_prompt(ctx)
    assert "60日 +5.00%｜一年 +30.00%｜離20日均 +1.2%｜離60日均 -0.5%" in text and "落後→轉強" in text
    assert "半導體／晶圓代工（中游）" in text
    assert "MA5/20黃金交叉（1日前）" in text and "RSI 71" in text
    assert "外資10日內買超7天、20日累計+9,000張" in text and "自營商5日累計-50張" in text
    assert "115/09 年增+25.0% 月增-3.0% 累計年增+18.0% 年增連4月為正" in text
    assert "risk" in str(ai_picks.RESPONSE_SCHEMA["properties"]["picks"]["items"]["required"])


def test_call_gemini_falls_back_on_404_and_skips_thought_parts():
    calls = []

    def post(url, json=None, timeout=None, headers=None):
        calls.append(url)
        assert headers["x-goog-api-key"] == "k"
        assert json["generationConfig"]["responseMimeType"] == "application/json"
        return Res(404, {}) if len(calls) == 1 else _ok({"overview": "o", "picks": []}, thought="thinking...")
    out, model = ai_picks.call_gemini("p", "k", post=post)
    assert out == {"overview": "o", "picks": []}
    assert model == ai_picks.DEFAULT_MODELS[1] and len(calls) == 2


def test_call_gemini_retries_busy_model_then_falls_back():
    seq = [Res(503, {}), Res(503, {}), Res(503, {}), _ok({"overview": "o", "picks": []})]
    waits, urls = [], []
    out, model = ai_picks.call_gemini("p", "k", post=lambda url, **kw: (urls.append(url), seq.pop(0))[1],
                                      sleep=waits.append)
    assert waits == list(ai_picks.RETRY_WAITS) and model == ai_picks.DEFAULT_MODELS[1]
    assert sum(ai_picks.DEFAULT_MODELS[0] in u for u in urls) == 3
    seq = [Res(503, {}), _ok({"overview": "o", "picks": []})]
    _, model = ai_picks.call_gemini("p", "k", post=lambda url, **kw: seq.pop(0), sleep=lambda s: None)
    assert model == ai_picks.DEFAULT_MODELS[0]
    with pytest.raises(ai_picks.AiPicksError, match="忙碌"):
        ai_picks.call_gemini("p", "k", post=lambda url, **kw: Res(503, {}), sleep=lambda s: None)


def test_call_gemini_treats_timeouts_as_busy():
    import requests
    seq = [requests.Timeout("x"), requests.ConnectionError("y"), requests.Timeout("z"),
           _ok({"overview": "o", "picks": []})]

    def post(url, **kw):
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    _, model = ai_picks.call_gemini("p", "k", post=post, sleep=lambda s: None)
    assert model == ai_picks.DEFAULT_MODELS[1]


def test_call_gemini_uses_env_model(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x")
    seen = []
    ai_picks.call_gemini("p", "k", post=lambda url, **kw: (seen.append(url), _ok({"overview": "", "picks": []}))[1])
    assert "models/gemini-x:generateContent" in seen[0]


def test_call_gemini_errors_are_readable_and_never_contain_the_key():
    with pytest.raises(ai_picks.AiPicksError) as e:
        ai_picks.call_gemini("p", "SECRET", post=lambda url, **kw: Res(429, {"error": {"message": "quota exceeded"}}))
    assert "429" in str(e.value) and "quota" in str(e.value) and "SECRET" not in str(e.value)
    with pytest.raises(ai_picks.AiPicksError, match="GEMINI_MODEL"):
        ai_picks.call_gemini("p", "k", post=lambda url, **kw: Res(404, {}))
    with pytest.raises(ai_picks.AiPicksError, match="JSON"):
        ai_picks.call_gemini("p", "k", post=lambda url, **kw: Res(200, {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}))
    with pytest.raises(ai_picks.AiPicksError, match="沒有回傳內容"):
        ai_picks.call_gemini("p", "k", post=lambda url, **kw: Res(200, {"candidates": []}))


def test_save_and_load_latest(tmp_path):
    assert ai_picks.load_latest(tmp_path) is None
    ctx = _ctx()
    ai_picks.save({"overview": "舊", "picks": []}, {**ctx, "date": "2026-10-26"}, "m", NOW, tmp_path)
    ai_picks.save({"overview": "新", "picks": []}, ctx, "m", NOW, tmp_path)
    doc = ai_picks.load_latest(tmp_path)
    assert doc["overview"] == "新" and doc["date"] == "2026-10-27" and doc["generated_at"] == "2026-10-27 16:40"


def test_generate_saves_validated_picks(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(ai_picks, "build_context", lambda app_module: _ctx())
    post = lambda url, **kw: _ok({"overview": "o", "picks": [{"kind": "stock", "id": "2330", "reason": "r", "evidence": []},
                                                              {"kind": "stock", "id": "0000", "reason": "x", "evidence": []}]})
    result = ai_picks.generate(NOW, app_module=object(), post=post)
    assert result == JobResult("ai_picks", "ok", "2026-10-27", 1)
    assert [p["id"] for p in ai_picks.load_latest()["picks"]] == ["2330"]


def test_generate_fails_when_nothing_valid(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(ai_picks, "build_context", lambda app_module: _ctx())
    post = lambda url, **kw: _ok({"overview": "o", "picks": [{"kind": "stock", "id": "0000", "reason": "x", "evidence": []}]})
    calls = []
    with pytest.raises(ai_picks.AiPicksError):
        ai_picks.generate(NOW, app_module=object(), post=lambda url, **kw: (calls.append(url), post(url))[1])
    assert ai_picks.load_latest() is None and len(calls) == 2      # 全部無效時重試一次


def _patch_index_jobs(monkeypatch, order):
    monkeypatch.setattr(run_sync, "_default_jobs", lambda: [])
    monkeypatch.setattr(run_sync, "sync_index", lambda s, n: (order.append("index"), JobResult("industry_index", "ok", None, 0))[1])
    monkeypatch.setattr(run_sync, "backfill_index", lambda s, n: (order.append("backfill"), JobResult("index_backfill", "ok", None, 0))[1])
    monkeypatch.setattr(run_sync, "sync_ai_picks", lambda s, n: (order.append("ai"), JobResult("ai_picks", "failed", None, 0, "x"))[1])


def test_run_sync_skips_ai_without_key(monkeypatch):
    order, store = [], FakeStore()
    _patch_index_jobs(monkeypatch, order)
    assert run_sync.run(store, NOW) == 0
    assert order == ["index", "backfill"] and "ai_picks" not in [r.dataset for r in store.runs]


def test_run_sync_runs_ai_last_with_key_and_failure_is_recorded(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    order, store = [], FakeStore()
    _patch_index_jobs(monkeypatch, order)
    assert run_sync.run(store, NOW) == 1
    assert order == ["index", "backfill", "ai"] and store.runs[-1].dataset == "ai_picks"
