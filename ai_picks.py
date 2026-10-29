"""AI 推薦：把今日的產業排行與中長期走勢、輪動、強弱節點、法人流向、個股技術面／籌碼／月營收與訊號交給 Gemini，
挑出 3–5 個值得注意的產業或個股，結果存成本機 JSON（reports/ai_picks/<資料日>.json）。

- 金鑰只從環境變數 GEMINI_API_KEY（.env）讀取，不寫進任何檔案或紀錄。
- AI 只能從我們給的名單挑；名單外的代號一律丟掉，名稱與連結由我們的資料補上。
- 手動執行：.venv\\Scripts\\python.exe ai_picks.py
"""
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests

import ai_factors as F
from sync.jobs import JobResult

log = logging.getLogger("ai_picks")

PICKS_DIR = Path(__file__).resolve().parent / "reports" / "ai_picks"
DATASET = "ai_picks"
# 未指定 GEMINI_MODEL 時依序嘗試；別名會跟著 Google 的最新 Flash 版本走，404 才換下一個
DEFAULT_MODELS = ("gemini-flash-latest", "gemini-2.5-flash")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_PICKS = 5
FLOW_TOP = 15
DISCLAIMER = "AI 產生，僅供參考，非投資建議"

SYSTEM_PROMPT = """你是台股產業鏈的分析助理，使用繁體中文。
根據使用者提供的今日資料，寫一段 2–4 句的盤勢說明（資金往哪裡跑、哪些產業轉強或轉弱），
再挑 3–5 個「值得注意」的產業或個股，產業與個股都要有。
判斷時要綜合四個面向，不要只看單一數字：
- 趨勢與技術面：短中長期漲跌、均線位置與交叉、KD、MACD、RSI、是否創 20 日新高或新低、量能。
- 籌碼面：外資、投信、自營商的買賣超金額與連續性（10 日內買超幾天）。
- 基本面：月營收年增、月增、累計年增、年增連續月數、成長是否加速。
- 產業面：所屬產業的指數走勢、輪動象限與移動方向、在產業鏈的上中下游位置。
優先挑多個面向互相印證的對象；只有單一亮點、或各面向互相矛盾的，要在風險中說明。
規則：
1. 只能從資料裡的「產業」與「候選個股」名單挑，id 必須照抄名單上的代號。
2. reason 1–2 句，必須引用資料中的數字，並涵蓋至少兩個面向。
3. risk 1 句，寫出這個對象「不利」的地方並引用數字（例如 RSI 過熱、離均線太遠、外資在賣、營收衰退、產業轉弱）；真的找不到就寫最主要的不確定性。
4. evidence 放 1–3 個簡短標籤（每個 12 字以內），例如「外資 5 日 +4.2 萬張」「MA5/20 黃金交叉」。
5. 不要給買賣建議、目標價或保證，用「值得注意」「可留意」這類中性說法。
6. 股價只有約 3 個月，60 日均線與 MACD 參考就好；營收是月資料，沒有獲利或本益比資料，不要自行推測。
7. 引用數字時要連同資料上標示的期間一起寫（例如「外資 20 日累計 +5.7 萬張」），不要把一個期間的數字說成另一個期間。
8. 數字只能照抄資料（可四捨五入或改寫成「萬張」），不要自行加總、相減、換算，也不要寫門檻值；
   程式會逐一核對 reason、risk、evidence 裡的數字，對不上資料的推薦會被刪除。"""

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "overview": {"type": "STRING"},
        "picks": {"type": "ARRAY", "items": {
            "type": "OBJECT",
            "properties": {
                "kind": {"type": "STRING", "enum": ["industry", "stock"]},
                "id": {"type": "STRING"},
                "reason": {"type": "STRING"},
                "risk": {"type": "STRING"},
                "evidence": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["kind", "id", "reason", "risk", "evidence"],
        }},
    },
    "required": ["overview", "picks"],
}

PRICE_DAYS = 130       # 讀幾天的行情與法人（日曆天，約 3 個月交易日，資料庫目前也只有這麼多）
REVENUE_MONTHS = 14
MAX_STOCKS = 150


class AiPicksError(RuntimeError):
    pass


# ---------- 資料整理 ----------

def _lots(v):
    return None if v is None else round(v / 1000)


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["stock_id"], []).append(r)
    return out


def load_stock_history(ids: list[str], today) -> dict:
    """讀候選計算需要的原始資料（行情含高低點、法人含自營商、營收含月增與累計年增）。"""
    import database
    from datetime import timedelta
    from sync.parse import months_back
    since = (today - timedelta(days=PRICE_DAYS)).isoformat()
    return {
        "quotes": _group(database._fetch_by_ids("daily_quotes", "stock_id, trade_date, close, high, low, volume",
                                                ids, "trade_date", since)),
        "ex": _group(database._fetch_by_ids("ex_rights", "stock_id, ex_date, prev_close, ref_price",
                                            ids, "ex_date", since)),
        "flows": _group(database._fetch_by_ids("smart_money_flow",
                                               "stock_id, trade_date, foreign_net, trust_net, dealer_net",
                                               ids, "trade_date", since)),
        "revenue": _group(database._fetch_by_ids("growth_momentum",
                                                 "stock_id, data_month, yoy_pct, mom_pct, acc_yoy_pct",
                                                 ids, "data_month", months_back(today, REVENUE_MONTHS))),
    }


TIER_TEXT = {"Upstream": "上游", "Midstream": "中游", "Downstream": "下游"}


def build_context(app_module, history_loader=None) -> dict:
    """整理給 AI 的資料；app_module 為 app.py 模組（沿用網站的每日摘要、產業排行、輪動與指數計算）。"""
    from datetime import date
    history_loader = history_loader or load_stock_history
    client = app_module.app.test_client()
    ranking = client.get("/api/industry_ranking")
    rotation = client.get("/api/rotation")
    if ranking.status_code != 200 or rotation.status_code != 200:
        raise AiPicksError(f"產業排行或輪動資料讀取失敗（{ranking.status_code}/{rotation.status_code}）")
    with app_module.app.app_context():
        digest, snap = app_module.build_daily_digest()
    rank, rot = ranking.get_json(), rotation.get_json()
    series = app_module.index_cache.get()["series"]
    rot_by = {p["major_id"]: p for p in rot["points"]}
    industries = []
    for r in rank["rows"]:
        trend = F.industry_trend(series.get(f"major:{r['major_id']}", []))
        industries.append({**{k: r[k] for k in ("major_id", "name", "r1", "r5", "r20", "foreign5", "trust5")},
                           **trend, "quadrant": (rot_by.get(r["major_id"]) or {}).get("quadrant"),
                           "rotation": F.rotation_move(rot_by.get(r["major_id"]))})
    major_name = {r["major_id"]: r["name"] for r in industries}
    market = {**rank["market"], **F.industry_trend(series.get("market:TW", []))}

    mapping = app_module.mapping_cache.get()["mapping"]
    first = {}
    for r in mapping:
        first.setdefault(r["stock_id"], r)
    try:
        node_names = app_module.fetch_node_names()
    except Exception:
        log.exception("節點名稱讀取失敗，改用代號")
        node_names = {}
    sigs = snap.get("signals") or {}
    returns, flows5 = snap.get("returns") or {}, snap.get("flows") or {}
    today = date.fromisoformat(snap["latest_date"]) if snap.get("latest_date") else date.today()
    hist = history_loader(sorted(first), today)

    rows = []
    for sid, m in first.items():
        prices = F.adjusted_prices(hist["quotes"].get(sid, []), hist["ex"].get(sid, []))
        t = F.technicals(prices)
        f = F.flow_stats(hist["flows"].get(sid, []))
        rev = F.revenue_stats(hist["revenue"].get(sid, []))
        labels = [s.get("label") for s in sigs.get(sid) or []]
        r = returns.get(sid) or {}
        fl = (flows5.get(sid) or {}).get(5) or {}
        rows.append({"stock_id": sid, "major_id": m["major_id"], "node_id": m["node_id"],
                     "industry": major_name.get(m["major_id"], m["major_id"]),
                     "node": node_names.get(m["node_id"], m["node_id"]),
                     "tier": TIER_TEXT.get(m.get("position_type"), ""),
                     "r1": r.get(1), "r5": r.get(5), "r20": r.get(20),
                     "foreign5": _lots(fl.get("foreign")), "trust5": _lots(fl.get("trust")),
                     "signals": labels, "tech": t, "flow": f, "revenue": rev,
                     "score": F.score(t, f, rev, len(labels))})
    # 候選：分數高者優先（訊號、技術事件、法人連續買、營收成長），同分看法人 5 日合計
    rows.sort(key=lambda s: (-s["score"], -((s["foreign5"] or 0) + (s["trust5"] or 0))))
    chosen = [s for s in rows if s["score"] > 0][:MAX_STOCKS]
    picked = {s["stock_id"] for s in chosen}
    # 法人 5 日買超最多的公司一定列入（即使分數低）
    for key in ("foreign5", "trust5"):
        for s in sorted(rows, key=lambda s: -(s[key] or 0))[:FLOW_TOP]:
            if (s[key] or 0) > 0 and s["stock_id"] not in picked:
                chosen.append(s)
                picked.add(s["stock_id"])
    names = {}
    try:
        names = {c["stock_id"]: c["company_name"] for c in app_module.fetch_companies(sorted(picked))}
    except Exception:
        log.exception("候選公司名稱讀取失敗，改用代號")
    for s in chosen:
        s["name"] = names.get(s["stock_id"], s["stock_id"])
    return {
        "date": snap.get("latest_date"), "flow_date": snap.get("flow_date"),
        "market": market, "industries": industries,
        "strong_nodes": digest["strong_nodes"], "weak_nodes": digest["weak_nodes"],
        "flow_nodes": digest["flow_nodes"], "stocks": chosen,
    }


def _pct(v):
    return "—" if v is None else f"{v:+.2f}%"


def _lot(v):
    return "—" if v is None else f"{v:+,}張"


def _gap(v):
    return "—" if v is None else f"{v:+.1f}%"


def _header_lines(ctx: dict) -> list[str]:
    m = ctx["market"]
    return [f"資料日期：{ctx['date']}（法人資料至 {ctx['flow_date']}）",
            f"大盤（自行計算的等權指數）：今日 {_pct(m.get('r1'))}、5 日 {_pct(m.get('r5'))}、20 日 {_pct(m.get('r20'))}、"
            f"60 日 {_pct(m.get('r60'))}、一年 {_pct(m.get('r1y'))}；離 20 日均 {_gap(m.get('vs_ma20'))}、離 60 日均 {_gap(m.get('vs_ma60'))}"]


def _industry_line(r: dict) -> str:
    # 每欄都寫上名稱與期間，AI 不必對照表頭
    return (f"{r['major_id']}｜{r['name']}｜今日 {_pct(r['r1'])}｜5日 {_pct(r['r5'])}｜20日 {_pct(r['r20'])}｜"
            f"60日 {_pct(r.get('r60'))}｜一年 {_pct(r.get('r1y'))}｜離20日均 {_gap(r.get('vs_ma20'))}｜"
            f"離60日均 {_gap(r.get('vs_ma60'))}｜外資5日累計 {_lot(r['foreign5'])}｜投信5日累計 {_lot(r['trust5'])}｜"
            f"輪動（8週前→現在） {r.get('rotation') or r.get('quadrant') or '—'}")


def _node_lines(ctx: dict, major_name: str | None = None) -> list[str]:
    """強弱節點與法人買超節點；給 major_name 時只取該產業的。"""
    keep = lambda n: major_name is None or n["major_name"] == major_name
    return ([f"今日最強節點 {n['name']}（{n['major_name']}）{_pct(n['change'])}" for n in ctx["strong_nodes"] if keep(n)]
            + [f"今日最弱節點 {n['name']}（{n['major_name']}）{_pct(n['change'])}" for n in ctx["weak_nodes"] if keep(n)]
            + [f"法人買超節點 {n['name']}（{n['major_name']}）外資5日累計 {_lot(n['foreign_lots'])}、投信5日累計 {_lot(n['trust_lots'])}"
               for n in ctx["flow_nodes"] if keep(n)])


def _stock_line(s: dict) -> str:
    return (f"{s['stock_id']} {s['name']}｜{s['industry']}{'／' + s['node'] if s.get('node') else ''}"
            f"{'（' + s['tier'] + '）' if s.get('tier') else ''}｜"
            f"漲跌 今日{_pct(s['r1'])} 5日{_pct(s['r5'])} 20日{_pct(s['r20'])}｜"
            f"外資5日累計{_lot(s['foreign5'])} 投信5日累計{_lot(s['trust5'])}｜"
            f"{F.technicals_text(s['tech']) if s.get('tech') else '—'}｜{F.flow_text(s['flow']) if s.get('flow') else '—'}｜"
            f"{F.revenue_text(s.get('revenue'))}｜{'、'.join(s['signals']) or '—'}")


def build_prompt(ctx: dict) -> str:
    lines = _header_lines(ctx) + ["", "## 產業"] + [_industry_line(r) for r in ctx["industries"]]
    lines += ["", "## 節點"] + _node_lines(ctx)
    lines += ["", "## 候選個股",
              "格式：id 名稱｜產業／節點（上中下游）｜漲跌｜法人5日累計｜技術面｜法人連續性與20日累計｜月營收｜訊號"]
    lines += [_stock_line(s) for s in ctx["stocks"]]
    return "\n".join(lines)


# ---------- 數字核對 ----------

_NUM = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(萬|億)?")
_UNIT = {"萬": 10_000, "億": 100_000_000}
# RSI／KD 常見的門檻寫法，不算引用資料
COMMON_NUMBERS = (20, 30, 70, 80)


def _cited(text: str) -> list[tuple[str, float, float]]:
    """文字中的數字 → [(原文, 數值, 容許誤差)]。

    誤差為寫出的最後一位的一個單位（5.7萬 → 1000、57,000 → 1000、38.6 → 0.1），
    四捨五入或無條件捨去都算對得上（243,777 寫成 24.3 萬或 24.4 萬皆可）。
    """
    out = []
    for m in _NUM.finditer(text):
        raw, mult = m.group(1).replace(",", ""), _UNIT.get(m.group(2), 1)
        value = float(raw)
        if "." in raw:
            tol = 10 ** -len(raw.split(".")[1])
        elif value >= 1000:
            tol = 10 ** (len(raw) - len(raw.rstrip("0")))
        else:
            tol = 1
        out.append((m.group(0).strip(), value * mult, tol * mult))
    return out


def unverified_numbers(text: str, source: str) -> list[str]:
    """text 裡在 source 找不到（取整後也對不上）的數字；正負號不比對（「賣超 1,200 張」對 -1,200）。"""
    known = [v for _, v, _ in _cited(source)] + list(COMMON_NUMBERS)
    return [raw for raw, v, tol in _cited(text) if not any(abs(v - k) < tol - 1e-9 for k in known)]


def _source_text(kind: str, item: dict, ctx: dict) -> str:
    """這個推薦可以引用的資料：大盤、自己那一行、所屬產業那一行與該產業的節點。"""
    industry = next((r for r in ctx["industries"] if r["major_id"] == item["major_id"]), None)
    lines = _header_lines(ctx)
    if kind == "stock":
        lines.append(_stock_line(item))
    if industry:
        lines += [_industry_line(industry)] + _node_lines(ctx, industry["name"])
    return "\n".join(lines)


# ---------- 呼叫 Gemini ----------

class _Busy:
    """逾時／連線錯誤的替身回應，走和 503 相同的重試與換模型流程。"""
    status_code = 503

    def __init__(self, reason):
        self.reason = reason

    def json(self):
        return {"error": {"message": self.reason}}


RETRY_STATUS = (500, 503)          # 模型忙碌等暫時性錯誤：等一下重試，仍失敗就換下一個模型
RETRY_WAITS = (5, 15)


def call_gemini(prompt: str, api_key: str, models=None, post=requests.post,
                sleep=time.sleep) -> tuple[dict, str]:
    """回傳 (解析後的 JSON, 實際使用的模型)。

    模型不存在（404）或持續忙碌（500/503 重試後仍失敗）時換下一個模型；其他錯誤直接拋出。
    """
    models = models or ([os.environ["GEMINI_MODEL"]] if os.environ.get("GEMINI_MODEL") else list(DEFAULT_MODELS))
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json",
                             "responseSchema": RESPONSE_SCHEMA},
    }
    last = None
    for model in models:
        for wait in (*RETRY_WAITS, None):
            try:
                res = post(API_URL.format(model=model), json=body, timeout=180,
                           headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
            except (requests.Timeout, requests.ConnectionError) as e:
                # 逾時或連線中斷視同忙碌（只記錯誤種類，訊息可能含網址）
                res = _Busy(type(e).__name__)
            if res.status_code not in RETRY_STATUS or wait is None:
                break
            log.warning("Gemini %s 忙碌（%s），%s 秒後重試", model, res.status_code, wait)
            sleep(wait)
        if res.status_code == 404:
            last = f"找不到模型 {model}"
            continue
        if res.status_code != 200:
            # 錯誤內容只取 Google 回的訊息，避免把請求（含金鑰標頭）寫進紀錄
            try:
                msg = res.json().get("error", {}).get("message", "")
            except ValueError:
                msg = ""
            if res.status_code in RETRY_STATUS:
                last = f"模型 {model} 忙碌（{res.status_code}）"
                log.warning("%s，改試下一個模型", last)
                continue
            raise AiPicksError(f"Gemini 回應 {res.status_code}：{msg[:200]}")
        data = res.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError):
            raise AiPicksError("Gemini 沒有回傳內容（可能被安全機制擋下）")
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        try:
            return json.loads(text), model
        except ValueError:
            raise AiPicksError("Gemini 回傳的不是有效的 JSON")
    raise AiPicksError(f"{last}；稍後再試，或在 .env 設定 GEMINI_MODEL 指定其他模型")


# ---------- 檢查與存檔 ----------

def _short(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def validate(result: dict, ctx: dict) -> dict:
    """只留名單內、且引用的數字都對得上資料的推薦；去重、最多 MAX_PICKS 個；名稱與連結用我們的資料。"""
    industries = {r["major_id"]: r for r in ctx["industries"]}
    stocks = {s["stock_id"]: s for s in ctx["stocks"]}
    picks, seen, dropped = [], set(), 0
    for p in result.get("picks") or []:
        if not isinstance(p, dict):
            continue
        kind, pid = p.get("kind"), str(p.get("id") or "").strip()
        if (kind, pid) in seen:
            continue
        evidence = [_short(e, 20) for e in (p.get("evidence") or []) if str(e or "").strip()][:3]
        base = {"kind": kind, "id": pid, "reason": _short(p.get("reason"), 200),
                "risk": _short(p.get("risk"), 140), "evidence": evidence}
        item = industries.get(pid) if kind == "industry" else stocks.get(pid) if kind == "stock" else None
        if item is None:
            log.warning("丟棄名單外的推薦：%s %s", kind, pid)
            continue
        cited = " ".join([base["reason"], base["risk"], *evidence])
        bad = unverified_numbers(cited, _source_text(kind, item, ctx))
        if bad:
            log.warning("丟棄數字對不上資料的推薦：%s %s（%s）", kind, pid, "、".join(bad))
            dropped += 1
            continue
        if kind == "industry":
            picks.append({**base, "name": item["name"], "major_id": pid, "node_id": None})
        else:
            picks.append({**base, "name": item["name"], "major_id": item["major_id"], "node_id": item["node_id"]})
        seen.add((kind, pid))
        if len(picks) >= MAX_PICKS:
            break
    return {"overview": _short(result.get("overview"), 400), "picks": picks, "dropped": dropped}


def save(picks: dict, ctx: dict, model: str, now: datetime, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or PICKS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = {"date": ctx["date"], "generated_at": now.strftime("%Y-%m-%d %H:%M"), "model": model, **picks}
    path = out_dir / f"{ctx['date']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_latest(out_dir: Path | None = None) -> dict | None:
    """最新一份推薦；沒有或讀不到回 None。"""
    out_dir = out_dir or PICKS_DIR
    for path in sorted(out_dir.glob("????-??-??.json"), reverse=True):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.exception("AI 推薦檔讀取失敗：%s", path.name)
    return None


def load_all(out_dir: Path | None = None) -> list[dict]:
    """所有推薦檔（舊到新）；讀不到的檔略過。"""
    out_dir = out_dir or PICKS_DIR
    docs = []
    for path in sorted(out_dir.glob("????-??-??.json")):
        try:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            log.exception("AI 推薦檔讀取失敗：%s", path.name)
    return docs


def has_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


# ---------- 同步工作 ----------

def generate(now: datetime, app_module=None, post=requests.post) -> JobResult:
    if app_module is None:
        import app as app_module
    ctx = build_context(app_module)
    if not ctx["date"]:
        raise AiPicksError("沒有今日股價資料")
    prompt = build_prompt(ctx)
    for attempt in range(2):          # 全部被刪掉時重新請 AI 產生一次
        raw, model = call_gemini(prompt, os.environ["GEMINI_API_KEY"], post=post)
        picks = validate(raw, ctx)
        if picks["picks"]:
            break
        log.warning("AI 推薦全部不在名單內或數字對不上資料（第 %s 次）", attempt + 1)
    else:
        raise AiPicksError("AI 推薦全部不在名單內或數字對不上資料")
    save(picks, ctx, model, now)
    return JobResult(DATASET, "ok", ctx["date"], len(picks["picks"]))


def sync_ai_picks(store, now: datetime) -> JobResult:
    """run_sync 的後處理工作；store 不使用（結果存本機檔案）。"""
    return generate(now)


def main() -> int:
    from dotenv import load_dotenv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    if not has_key():
        print("尚未設定 GEMINI_API_KEY：請在 .env 加一行 GEMINI_API_KEY=你的金鑰")
        return 1
    try:
        result = generate(datetime.now())
    except Exception as e:
        print(f"產生失敗：{e}")
        return 1
    print(f"完成：{result.last_date} 共 {result.rows} 個推薦，存於 {PICKS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
