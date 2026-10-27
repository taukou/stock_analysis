"""單一入口：依序執行所有同步工作、記錄結果、以結束碼回報。"""
import logging
import sys
from datetime import datetime
from pathlib import Path

from sync.index_job import sync_index
from sync.jobs import (JobResult, sync_emerging, sync_ex_rights,
                       sync_institutional, sync_quotes, sync_revenue)
from sync.logsetup import setup_logging
from sync.store import make_store

LOG_ROOT = Path(__file__).resolve().parent
log = logging.getLogger("run_sync")


def _default_jobs():
    return [sync_quotes, sync_emerging, sync_institutional, sync_ex_rights, sync_revenue]


def _run_one(store, now: datetime, job) -> tuple[JobResult, bool]:
    """執行單一工作並記錄；回傳 (結果, 是否有失敗)。"""
    name = getattr(job, "__name__", "job")
    failed = False
    try:
        result = job(store, now)
    except Exception as e:
        log.exception("job %s 例外", name)
        result = JobResult(name, "failed", None, 0, f"{type(e).__name__}: {e}")
    log.info("%s status=%s rows=%s last_date=%s message=%s", result.dataset,
             result.status, result.rows, result.last_date, result.message)
    if result.status != "ok":
        failed = True
    try:
        store.record_run(result)
    except Exception:
        log.exception("record_run 失敗: %s", result.dataset)
        failed = True
    return result, failed


def run(store, now: datetime, jobs=None, post_jobs=None) -> int:
    failed = False
    wrote: set[str] = set()
    # 指數更新排在日常工作與後處理之後；明確傳入 jobs（測試）時預設不跑指數
    if post_jobs is None:
        post_jobs = [sync_index] if jobs is None else []
    for job in (jobs if jobs is not None else _default_jobs()):
        result, bad = _run_one(store, now, job)
        failed = failed or bad
        if result.rows > 0:
            wrote.add(result.dataset)

    steps = []
    if wrote & {"quotes", "emerging", "ex_rights"}:
        steps.append(("fill_ex_date_changes", store.fill_ex_date_changes))
    if wrote & {"quotes", "emerging"}:
        steps.append(("refresh_company_latest", store.refresh_company_latest))
    for label, fn in steps:
        try:
            fn()
        except Exception:
            log.exception("%s 失敗", label)
            failed = True

    for job in post_jobs:
        _, bad = _run_one(store, now, job)
        failed = failed or bad
    return 1 if failed else 0


def main() -> int:
    setup_logging("sync", base_dir=LOG_ROOT)
    try:
        store = make_store()
    except Exception:
        log.exception("無法建立資料庫連線")
        return 1
    return run(store, datetime.now())


if __name__ == "__main__":
    sys.exit(main())
