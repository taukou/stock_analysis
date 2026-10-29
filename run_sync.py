"""單一入口：依序執行所有同步工作、記錄結果、以結束碼回報。"""
import logging
import sys
from datetime import datetime
from pathlib import Path

import ai_picks
import sync_status
from freshness import label
from sync.index_backfill import backfill_index
from sync.index_job import sync_index
from sync.jobs import (JobResult, sync_emerging, sync_ex_rights,
                       sync_institutional, sync_quotes, sync_revenue)
from sync.logsetup import setup_logging
from sync.store import make_store

sync_ai_picks = ai_picks.sync_ai_picks
LOG_ROOT = Path(__file__).resolve().parent
log = logging.getLogger("run_sync")


def _default_jobs():
    return [sync_quotes, sync_emerging, sync_institutional, sync_ex_rights, sync_revenue]


def _run_one(store, now: datetime, job, problems: list[dict]) -> JobResult:
    """執行單一工作並記錄；失敗（含寫不進 sync_runs）加入 problems。"""
    name = getattr(job, "__name__", "job")
    try:
        result = job(store, now)
    except Exception as e:
        log.exception("job %s 例外", name)
        result = JobResult(name, "failed", None, 0, f"{type(e).__name__}: {e}")
    log.info("%s status=%s rows=%s last_date=%s message=%s", result.dataset,
             result.status, result.rows, result.last_date, result.message)
    if result.status != "ok":
        problems.append({"label": label(result.dataset), "message": result.message})
    try:
        store.record_run(result)
    except Exception as e:
        log.exception("record_run 失敗: %s", result.dataset)
        problems.append({"label": f"{label(result.dataset)}同步紀錄", "message": f"{type(e).__name__}: {e}"})
    return result


def run(store, now: datetime, jobs=None, post_jobs=None) -> int:
    problems: list[dict] = []
    wrote: set[str] = set()
    # 指數更新排在日常工作與後處理之後，AI 推薦再排在指數之後（要用最新指數）；
    # 沒設定 GEMINI_API_KEY 就不跑 AI 推薦，也不記錄（不算失敗）。明確傳入 jobs（測試）時預設都不跑
    if post_jobs is None:
        post_jobs = [] if jobs is not None else [sync_index, backfill_index]
        if jobs is None:
            if ai_picks.has_key():
                post_jobs.append(sync_ai_picks)
            else:
                log.info("未設定 GEMINI_API_KEY，略過 AI 推薦")
    for job in (jobs if jobs is not None else _default_jobs()):
        result = _run_one(store, now, job, problems)
        if result.rows > 0:
            wrote.add(result.dataset)

    steps = []
    if wrote & {"quotes", "emerging", "ex_rights"}:
        steps.append(("除權息漲跌補算", store.fill_ex_date_changes))
    if wrote & {"quotes", "emerging"}:
        steps.append(("公司最新資料更新", store.refresh_company_latest))
    for step, fn in steps:
        try:
            fn()
        except Exception as e:
            log.exception("%s 失敗", step)
            problems.append({"label": step, "message": f"{type(e).__name__}: {e}"})

    for job in post_jobs:
        _run_one(store, now, job, problems)
    sync_status.write(now, problems)
    return 1 if problems else 0


def main() -> int:
    setup_logging("sync", base_dir=LOG_ROOT)
    try:
        store = make_store()
    except Exception as e:
        log.exception("無法建立資料庫連線")
        sync_status.write(datetime.now(), [{"label": "資料庫連線", "message": f"{type(e).__name__}: {e}"}])
        return 1
    return run(store, datetime.now())


if __name__ == "__main__":
    sys.exit(main())
