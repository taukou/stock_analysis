"""AI 推薦：把今日的產業排行、輪動、強弱節點、法人流向與個股訊號交給 Gemini，
挑出 3–5 個值得注意的產業或個股，結果存成本機 JSON（reports/ai_picks/<資料日>.json）。

- 金鑰只從環境變數 GEMINI_API_KEY（.env）讀取，不寫進任何檔案或紀錄。
- AI 只能從我們給的名單挑；名單外的代號一律丟掉，名稱與連結由我們的資料補上。
- 手動執行：.venv\\Scripts\\python.exe ai_picks.py
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

import requests

from sync.jobs import JobResult

log = logging.getLogger("ai_picks")

PICKS_DIR = Path(__file__).resolve().parent / "reports" / "ai_picks"
DATASET = "ai_picks"
# 未指定 GEMINI_MODEL 時依序嘗試；別名會跟著 Google 的最新 Flash 版本走，404 才換下一個
DEFAULT_MODELS = ("gemini-flash-latest", "gemini-2.5-flash")
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_PICKS = 5
MAX_SIGNAL_STOCKS = 120
FLOW_TOP = 15
DISCLAIMER = "AI 產生，僅供參考，非投資建議"

SYSTEM_PROMPT = """你是台股產業鏈的分析助理，使用繁體中文。
根據使用者提供的今日資料，寫一段 2–4 句的盤勢說明（資金往哪裡跑、哪些產業轉強或轉弱），
再挑 3–5 個「值得注意」的產業或個股，產業與個股都要有。
規則：
1. 只能從資料裡的「產業」與「候選個股」名單挑，id 必須照抄名單上的代號。
2. 每個理由 1–2 句，必須引用資料中的數字（例如 5 日漲跌、外資或投信 5 日買賣超張數、輪動象限、訊號）。
3. evidence 放 1–3 個簡短標籤（每個 12 字以內），例如「外資 5 日 +4.2 萬張」「輪動：轉強」。
4. 不要給買賣建議、目標價或保證，用「值得注意」「可留意」這類中性說法。"""

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
                "evidence": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["kind", "id", "reason", "evidence"],
        }},
    },
    "required": ["overview", "picks"],
}


class AiPicksError(RuntimeError):
    pass


# ---------- 資料整理 ----------

def _lots(v):
    return None if v is None else round(v / 1000)


def build_context(app_module) -> dict:
    """用網站本身的計算（每日摘要、產業排行、輪動）整理給 AI 的資料；app_module 為 app.py 模組。"""
    client = app_module.app.test_client()
    ranking = client.get("/api/industry_ranking")
    rotation = client.get("/api/rotation")
    if ranking.status_code != 200 or rotation.status_code != 200:
        raise AiPicksError(f"產業排行或輪動資料讀取失敗（{ranking.status_code}/{rotation.status_code}）")
    with app_module.app.app_context():
        digest, snap = app_module.build_daily_digest()
    rank, rot = ranking.get_json(), rotation.get_json()
    quadrant = {p["major_id"]: p["quadrant"] for p in rot["points"]}
    industries = [{**{k: r[k] for k in ("major_id", "name", "r1", "r5", "r20", "foreign5", "trust5")},
                   "quadrant": quadrant.get(r["major_id"])} for r in rank["rows"]]
    major_name = {r["major_id"]: r["name"] for r in industries}

    returns, flows = snap.get("returns") or {}, snap.get("flows") or {}
    stocks: dict[str, dict] = {}
    for g in digest["signal_groups"]:
        for c in g["companies"]:
            s = stocks.setdefault(c["stock_id"], {"stock_id": c["stock_id"], "name": c["name"],
                                                  "major_id": c["major_id"], "node_id": c["node_id"],
                                                  "signals": []})
            s["signals"].append(c["label"])
    mapping = app_module.mapping_cache.get()["mapping"]
    first = {}
    for r in mapping:
        first.setdefault(r["stock_id"], r)

    def flow5(sid, who):
        return _lots(((flows.get(sid) or {}).get(5) or {}).get(who))

    def enrich(s):
        r = returns.get(s["stock_id"]) or {}
        return {**s, "industry": major_name.get(s["major_id"], s["major_id"]),
                "r1": r.get(1), "r5": r.get(5), "r20": r.get(20),
                "foreign5": flow5(s["stock_id"], "foreign"), "trust5": flow5(s["stock_id"], "trust")}

    signal_stocks = sorted((enrich(s) for s in stocks.values()),
                           key=lambda s: (-len(s["signals"]),
                                          -((s["foreign5"] or 0) + (s["trust5"] or 0))))[:MAX_SIGNAL_STOCKS]
    chosen = {s["stock_id"]: s for s in signal_stocks}
    # 法人 5 日買超最多的公司（即使沒有訊號）也列入候選
    for who in ("foreign", "trust"):
        tops = sorted((sid for sid in first if flow5(sid, who)), key=lambda sid: -flow5(sid, who))[:FLOW_TOP]
        missing = [sid for sid in tops if sid not in chosen]
        names = {}
        if missing:
            try:
                names = {c["stock_id"]: c["company_name"] for c in app_module.fetch_companies(missing)}
            except Exception:
                log.exception("候選公司名稱讀取失敗，改用代號")
        for sid in missing:
            r = first[sid]
            chosen[sid] = enrich({"stock_id": sid, "name": names.get(sid, sid), "major_id": r["major_id"],
                                  "node_id": r["node_id"], "signals": []})
    return {
        "date": snap.get("latest_date"),
        "flow_date": snap.get("flow_date"),
        "market": rank["market"],
        "industries": industries,
        "strong_nodes": digest["strong_nodes"], "weak_nodes": digest["weak_nodes"],
        "flow_nodes": digest["flow_nodes"],
        "stocks": list(chosen.values()),
    }


def _pct(v):
    return "—" if v is None else f"{v:+.2f}%"


def _lot(v):
    return "—" if v is None else f"{v:+,}張"


def build_prompt(ctx: dict) -> str:
    m = ctx["market"]
    lines = [f"資料日期：{ctx['date']}（法人資料至 {ctx['flow_date']}）",
             f"大盤（自行計算的等權指數）：今日 {_pct(m.get('r1'))}、5 日 {_pct(m.get('r5'))}、20 日 {_pct(m.get('r20'))}",
             "", "## 產業（id｜名稱｜今日｜5日｜20日｜外資5日｜投信5日｜輪動象限）"]
    for r in ctx["industries"]:
        lines.append(f"{r['major_id']}｜{r['name']}｜{_pct(r['r1'])}｜{_pct(r['r5'])}｜{_pct(r['r20'])}｜"
                     f"{_lot(r['foreign5'])}｜{_lot(r['trust5'])}｜{r['quadrant'] or '—'}")
    lines += ["", "## 今日最強節點"] + [f"{n['name']}（{n['major_name']}）{_pct(n['change'])}" for n in ctx["strong_nodes"]]
    lines += ["", "## 今日最弱節點"] + [f"{n['name']}（{n['major_name']}）{_pct(n['change'])}" for n in ctx["weak_nodes"]]
    lines += ["", "## 法人 5 日買超最多的節點"] + [
        f"{n['name']}（{n['major_name']}）外資 {_lot(n['foreign_lots'])}、投信 {_lot(n['trust_lots'])}"
        for n in ctx["flow_nodes"]]
    lines += ["", "## 候選個股（id｜名稱｜產業｜今日｜5日｜20日｜外資5日｜投信5日｜訊號）"]
    for s in ctx["stocks"]:
        lines.append(f"{s['stock_id']}｜{s['name']}｜{s['industry']}｜{_pct(s['r1'])}｜{_pct(s['r5'])}｜"
                     f"{_pct(s['r20'])}｜{_lot(s['foreign5'])}｜{_lot(s['trust5'])}｜{'、'.join(s['signals']) or '—'}")
    return "\n".join(lines)


# ---------- 呼叫 Gemini ----------

def call_gemini(prompt: str, api_key: str, models=None, post=requests.post) -> tuple[dict, str]:
    """回傳 (解析後的 JSON, 實際使用的模型)。模型不存在（404）時換下一個；其他錯誤直接拋出。"""
    models = models or ([os.environ["GEMINI_MODEL"]] if os.environ.get("GEMINI_MODEL") else list(DEFAULT_MODELS))
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json",
                             "responseSchema": RESPONSE_SCHEMA},
    }
    last = None
    for model in models:
        res = post(API_URL.format(model=model), json=body, timeout=120,
                   headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
        if res.status_code == 404:
            last = f"找不到模型 {model}"
            continue
        if res.status_code != 200:
            # 錯誤內容只取 Google 回的訊息，避免把請求（含金鑰標頭）寫進紀錄
            try:
                msg = res.json().get("error", {}).get("message", "")
            except ValueError:
                msg = ""
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
    raise AiPicksError(f"{last}；可在 .env 設定 GEMINI_MODEL 指定模型")


# ---------- 檢查與存檔 ----------

def _short(s, n):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def validate(result: dict, ctx: dict) -> dict:
    """只留名單內的推薦、去重、最多 MAX_PICKS 個；名稱與連結用我們的資料。"""
    industries = {r["major_id"]: r for r in ctx["industries"]}
    stocks = {s["stock_id"]: s for s in ctx["stocks"]}
    picks, seen = [], set()
    for p in result.get("picks") or []:
        if not isinstance(p, dict):
            continue
        kind, pid = p.get("kind"), str(p.get("id") or "").strip()
        if (kind, pid) in seen:
            continue
        evidence = [_short(e, 20) for e in (p.get("evidence") or []) if str(e or "").strip()][:3]
        base = {"kind": kind, "id": pid, "reason": _short(p.get("reason"), 160), "evidence": evidence}
        if kind == "industry" and pid in industries:
            picks.append({**base, "name": industries[pid]["name"], "major_id": pid, "node_id": None})
        elif kind == "stock" and pid in stocks:
            s = stocks[pid]
            picks.append({**base, "name": s["name"], "major_id": s["major_id"], "node_id": s["node_id"]})
        else:
            log.warning("丟棄名單外的推薦：%s %s", kind, pid)
            continue
        seen.add((kind, pid))
        if len(picks) >= MAX_PICKS:
            break
    return {"overview": _short(result.get("overview"), 400), "picks": picks}


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


def has_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


# ---------- 同步工作 ----------

def generate(now: datetime, app_module=None, post=requests.post) -> JobResult:
    if app_module is None:
        import app as app_module
    ctx = build_context(app_module)
    if not ctx["date"]:
        raise AiPicksError("沒有今日股價資料")
    raw, model = call_gemini(build_prompt(ctx), os.environ["GEMINI_API_KEY"], post=post)
    picks = validate(raw, ctx)
    if not picks["picks"]:
        raise AiPicksError("AI 推薦的項目都不在名單內")
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
