"""最近一次同步的結果，存成本機檔案（reports/sync_status.json）。

資料庫連不上或金鑰失效時，sync_runs 也寫不進去，網站就看不出同步失敗；
本機檔案一定寫得進去，網站以它判斷「最近一次同步是否有問題」。
"""
import json
import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger("sync_status")

STATUS_PATH = Path(__file__).resolve().parent / "reports" / "sync_status.json"
MESSAGE_MAX = 200


def write(now: datetime, problems: list[dict], path: Path | None = None) -> None:
    """problems 為 [{"label": 項目, "message": 原因}]；空的代表全部成功。寫入失敗只記錄，不影響同步結果。"""
    path = path or STATUS_PATH
    doc = {"finished_at": now.strftime("%Y-%m-%d %H:%M"), "ok": not problems,
           "problems": [{"label": p["label"], "message": str(p.get("message") or "")[:MESSAGE_MAX]} for p in problems]}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.exception("同步狀態檔寫入失敗")


def read(path: Path | None = None) -> dict | None:
    """沒有或讀不到回 None。"""
    path = path or STATUS_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
