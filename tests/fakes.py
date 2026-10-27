"""測試用的記憶體 Store，介面與 sync.store.Store 相同。"""


class FakeStore:
    def __init__(self):
        self.tables: dict[str, dict[tuple, dict]] = {}
        self.upserts: list[tuple[str, int]] = []
        self.runs: list = []
        self.rpc_calls: list[str] = []
        self.tracked: list[dict] = []
        self.mapping: list[dict] = []

    def last_value(self, table, column, filters=None):
        rows = self.tables.get(table, {}).values()
        for k, v in (filters or {}).items():
            rows = [r for r in rows if r.get(k) == v]
        vals = [r[column] for r in rows if r.get(column) is not None]
        return max(vals) if vals else None

    def upsert(self, table, rows, on_conflict):
        if not rows:
            return 0
        cols = on_conflict.split(",")
        if any(c != c.strip() or not c for c in cols):
            raise ValueError(f"on_conflict 格式錯誤: {on_conflict!r}")
        keys = [tuple(r.get(c) for c in cols) for r in rows]
        if len(set(keys)) != len(keys):
            raise ValueError("同一次 upsert 內有重複的衝突鍵")
        store = self.tables.setdefault(table, {})
        for k, r in zip(keys, rows):
            store[k] = {**store.get(k, {}), **r}
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

    def chain_mapping(self):
        return list(self.mapping)

    def quotes_between(self, start, end, ids=None):
        rows = self.tables.get("daily_quotes", {}).values()
        return [dict(r) for r in rows
                if start <= r["trade_date"] <= end
                and (ids is None or r["stock_id"] in ids)]

    def ex_rights_between(self, start, end):
        rows = self.tables.get("ex_rights", {}).values()
        return [dict(r) for r in rows if start <= r["ex_date"] <= end]

    def index_rows_on(self, trade_date):
        rows = self.tables.get("industry_index_daily", {}).values()
        return [dict(r) for r in rows if r["trade_date"] == trade_date]

    def index_scope_keys(self):
        return {(k[0], k[1]) for k in self.tables.get("industry_index_scopes", {})}
