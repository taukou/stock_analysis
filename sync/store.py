"""同步管線唯一與 Supabase 溝通的模組（使用 service key）。"""
import os

from dotenv import load_dotenv

BATCH_SIZE = 500


class Store:
    def __init__(self, client):
        self.client = client

    def last_value(self, table: str, column: str,
                   filters: dict[str, str] | None = None) -> str | None:
        q = self.client.table(table).select(column)
        for k, v in (filters or {}).items():
            q = q.eq(k, v)
        res = q.order(column, desc=True, nullsfirst=False).limit(1).execute()
        data = res.data or []
        return data[0][column] if data else None

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> int:
        if not rows:
            return 0
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            self.client.table(table).upsert(batch, on_conflict=on_conflict).execute()
        return len(rows)

    def refresh_company_latest(self) -> None:
        self.client.rpc("refresh_company_latest").execute()

    def fill_ex_date_changes(self) -> None:
        self.client.rpc("fill_ex_date_changes").execute()

    def record_run(self, result) -> None:
        self.client.table("sync_runs").insert({
            "dataset": result.dataset,
            "status": result.status,
            "last_date": result.last_date,
            "rows": result.rows,
            "message": result.message,
        }).execute()

    def tracked_companies(self) -> list[dict]:
        res = self.client.table("companies").select(
            "stock_id, company_name, market_type").execute()
        return res.data or []

    def _paged(self, build, page: int = 1000) -> list[dict]:
        """分頁讀完：build() 每次回傳新的 query builder。"""
        rows: list[dict] = []
        start = 0
        while True:
            data = build().range(start, start + page - 1).execute().data or []
            rows.extend(data)
            if len(data) < page:
                return rows
            start += page

    def chain_mapping(self) -> list[dict]:
        rows = self._paged(lambda: self.client.table("company_node_mapping").select(
            "node_id, stock_id, value_chain_nodes(major_id, position_type)")
            .order("node_id").order("stock_id"))
        out = []
        for r in rows:
            node = r.get("value_chain_nodes")
            if isinstance(node, list):
                node = node[0] if node else None
            if not node:
                continue
            out.append({"node_id": r["node_id"], "stock_id": r["stock_id"],
                        "major_id": node["major_id"],
                        "position_type": node["position_type"]})
        return out

    def quotes_between(self, start: str, end: str,
                       ids: list[str] | None = None) -> list[dict]:
        def fetch(batch):
            def build():
                q = (self.client.table("daily_quotes")
                     .select("stock_id, trade_date, market, close")
                     .gte("trade_date", start).lte("trade_date", end))
                if batch is not None:
                    q = q.in_("stock_id", batch)
                return q.order("trade_date").order("stock_id")
            return self._paged(build)
        if ids is None:
            return fetch(None)
        out: list[dict] = []
        for i in range(0, len(ids), 150):
            out.extend(fetch(ids[i:i + 150]))
        return out

    def ex_rights_between(self, start: str, end: str) -> list[dict]:
        return self._paged(lambda: self.client.table("ex_rights")
                           .select("stock_id, ex_date, ref_price")
                           .gte("ex_date", start).lte("ex_date", end)
                           .order("ex_date").order("stock_id"))

    def index_rows_on(self, trade_date: str) -> list[dict]:
        return self._paged(lambda: self.client.table("industry_index_daily")
                           .select("scope_kind, scope_id, trade_date, level, ret_pct, members")
                           .eq("trade_date", trade_date)
                           .order("scope_kind").order("scope_id"))

    def index_scope_keys(self) -> set[tuple[str, str]]:
        rows = self._paged(lambda: self.client.table("industry_index_scopes")
                           .select("scope_kind, scope_id")
                           .order("scope_kind").order("scope_id"))
        return {(r["scope_kind"], r["scope_id"]) for r in rows}


def make_store() -> Store:
    load_dotenv()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url:
        raise RuntimeError("缺少 SUPABASE_URL")
    if not key:
        raise RuntimeError("缺少 SUPABASE_SERVICE_KEY")
    from supabase import create_client
    return Store(create_client(url, key))
