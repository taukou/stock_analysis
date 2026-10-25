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
        res = q.order(column, desc=True).limit(1).execute()
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
