"""單一入口：依序執行所有同步工作、記錄結果、以結束碼回報。"""
import logging
import sys
from datetime import datetime
from pathlib import Path

from sync.jobs import (JobResult, sync_emerging, sync_ex_rights,
                       sync_institutional, sync_quotes, sync_revenue)
from sync.logsetup import setup_logging
from sync.store import make_store

LOG_ROOT = Path(__file__).resolve().parent
log = logging.getLogger("run_sync")


def _default_jobs():
    return [sync_quotes, sync_emerging, sync_institutional, sync_ex_rights, sync_revenue]


def run(store, now: datetime, jobs=None) -> int:
    failed = False
    wrote: set[str] = set()
    for job in (jobs if jobs is not None else _default_jobs()):
        name = getattr(job, "__name__", "job")
        try:
            result = job(store, now)
        except Exception as e:
            log.exception("job %s 例外", name)
            result = JobResult(name, "failed", None, 0, f"{type(e).__name__}: {e}")
        log.info("%s status=%s rows=%s last_date=%s message=%s", result.dataset,
                 result.status, result.rows, result.last_date, result.message)
        if result.status != "ok":
            failed = True
        if result.rows > 0:
            wrote.add(result.dataset)
        try:
            store.record_run(result)
        except Exception:
            log.exception("record_run 失敗: %s", result.dataset)
            failed = True

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
