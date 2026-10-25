"""測試用的記憶體 Store，介面與 sync.store.Store 相同。"""


class FakeStore:
    def __init__(self):
        self.tables: dict[str, dict[tuple, dict]] = {}
        self.upserts: list[tuple[str, int]] = []
        self.runs: list = []
        self.rpc_calls: list[str] = []
        self.tracked: list[dict] = []

    def last_value(self, table, column, filters=None):
        rows = self.tables.get(table, {}).values()
        for k, v in (filters or {}).items():
            rows = [r for r in rows if r.get(k) == v]
        vals = [r[column] for r in rows if r.get(column) is not None]
        return max(vals) if vals else None

    def upsert(self, table, rows, on_conflict):
        if not rows:
            return 0
        cols = [c.strip() for c in on_conflict.split(",")]
        store = self.tables.setdefault(table, {})
        for r in rows:
            store[tuple(r.get(c) for c in cols)] = dict(r)
        self.upserts.append((table, len(rows)))
        return len(rows)

    def refresh_company_latest(self):
        self.rpc_calls.append("refresh_company_latest")

    def fill_ex_date_changes(self):
        self.rpc_calls.append("fill_ex_date_changes")

    def record_run(self, result):
        self.runs.append(result)

    def tracked_companies(self):
        return list(self.tracked)
