import logging
from datetime import datetime

import pytest

import run_sync
from sync.jobs import JobResult
from sync.logsetup import setup_logging
from tests.fakes import FakeStore

NOW = datetime(2026, 10, 25, 18, 0)


def _job(dataset, status="ok", rows=3):
    def job(store, now):
        return JobResult(dataset, status, "2026-10-23" if status == "ok" else None, rows, "")
    return job


def _five(statuses=None, rows=None):
    names = ["quotes", "emerging", "institutional", "ex_rights", "revenue"]
    statuses = statuses or {}
    rows = rows or {}
    return [_job(n, statuses.get(n, "ok"), rows.get(n, 3)) for n in names]


def test_run_continues_after_job_failure():
    store = FakeStore()
    calls = []

    def wrap(j):
        def w(s, n):
            r = j(s, n)
            calls.append(r.dataset)
            return r
        return w

    jobs = [wrap(j) for j in _five({"quotes": "failed"}, {"quotes": 0})]
    assert run_sync.run(store, NOW, jobs) == 1
    assert len(calls) == 5
    assert len(store.runs) == 5


def test_run_all_ok_returns_0_and_refreshes_latest():
    store = FakeStore()
    assert run_sync.run(store, NOW, _five()) == 0
    assert len(store.runs) == 5
    assert "refresh_company_latest" in store.rpc_calls


def test_fill_ex_date_before_refresh():
    store = FakeStore()
    run_sync.run(store, NOW, _five())
    assert store.rpc_calls == ["fill_ex_date_changes", "refresh_company_latest"]


def test_no_rpc_when_nothing_written():
    store = FakeStore()
    rows = {n: 0 for n in ["quotes", "emerging", "institutional", "ex_rights", "revenue"]}
    assert run_sync.run(store, NOW, _five(rows=rows)) == 0
    assert store.rpc_calls == []


def test_ex_rights_only_fills_without_refresh():
    store = FakeStore()
    rows = {"quotes": 0, "emerging": 0, "institutional": 5, "ex_rights": 2, "revenue": 0}
    run_sync.run(store, NOW, _five(rows=rows))
    assert store.rpc_calls == ["fill_ex_date_changes"]


def test_record_run_and_rpc_errors_count_as_failure():
    store = FakeStore()

    def boom(*a, **k):
        raise RuntimeError("x")

    store.record_run = boom
    store.fill_ex_date_changes = boom
    store.refresh_company_latest = boom
    assert run_sync.run(store, NOW, _five()) == 1


def test_job_exception_is_failure_and_continues():
    store = FakeStore()
    jobs = _five()

    def bad(s, n):
        raise RuntimeError("boom")

    jobs[0] = bad
    assert run_sync.run(store, NOW, jobs) == 1
    assert len(store.runs) == 5
    assert store.runs[0].status == "failed"


def test_main_returns_1_when_make_store_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(run_sync, "LOG_ROOT", tmp_path)

    def bad():
        raise RuntimeError("missing key")

    monkeypatch.setattr(run_sync, "make_store", bad)
    assert run_sync.main() == 1
    logging.getLogger().handlers.clear()


def test_setup_logging_idempotent_and_writes(tmp_path):
    root = logging.getLogger()
    root.handlers.clear()
    lg = setup_logging("t", base_dir=tmp_path)
    setup_logging("t", base_dir=tmp_path)
    n = len(root.handlers)
    assert n == 2
    logging.getLogger("sync.jobs").warning("中文 😀")
    for h in root.handlers:
        h.flush()
    assert "中文" in (tmp_path / "logs" / "t.log").read_text(encoding="utf-8")
    for h in list(root.handlers):
        h.close()
    root.handlers.clear()


def test_index_job_runs_after_daily_jobs():
    store = FakeStore()
    order = []

    def idx(s, n):
        order.append("index")
        return JobResult("industry_index", "ok", "2026-10-23", 2, "")

    def wrap(j):
        def w(s, n):
            order.append(j.__name__)
            return j(s, n)
        return w

    jobs = [wrap(j) for j in _five({"quotes": "failed"}, {"quotes": 0})]
    assert run_sync.run(store, NOW, jobs, post_jobs=[idx]) == 1
    assert order[-1] == "index" and len(order) == 6
    assert [r.dataset for r in store.runs][-1] == "industry_index"


def test_backfill_runs_right_after_sync_index_even_if_it_failed(monkeypatch):
    store = FakeStore()
    order = []
    monkeypatch.setattr(run_sync, "sync_index",
                        lambda s, n: (order.append("index"),
                                      JobResult("industry_index", "failed", None, 0, "x"))[1])
    monkeypatch.setattr(run_sync, "backfill_index",
                        lambda s, n: (order.append("backfill"),
                                      JobResult("index_backfill", "ok", None, 0, ""))[1])
    monkeypatch.setattr(run_sync, "_default_jobs", lambda: [])
    assert run_sync.run(store, NOW) == 1
    assert order == ["index", "backfill"]
    assert [r.dataset for r in store.runs] == ["industry_index", "index_backfill"]
