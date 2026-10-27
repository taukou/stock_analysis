"""產業指數資料讀取與快取（網站端，匿名 key 只讀）。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import database
from industry_index import members_hash, scope_members
from industry_trends import key_str, series_by_key
from snapshot import SnapshotCache

KINDS = ["market", "major", "tier"]


def load_index(today: date | None = None) -> dict:
    today = today or date.today()
    since = (today - timedelta(days=400)).isoformat()
    # 三個讀取同時進行（每個執行緒有自己的連線）
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = pool.submit(database.fetch_index_rows, KINDS, since)
        scopes = pool.submit(database.fetch_index_scopes)
        mapping = pool.submit(database.fetch_chain_mapping)
        rows, scopes, mapping = rows.result(), scopes.result(), mapping.result()
    series = series_by_key(rows)
    first_date = {k: pts[0][0] for k, pts in series.items() if pts}
    members = scope_members(mapping)
    changed = set()
    for s in scopes:
        kind, sid = s["scope_kind"], s["scope_id"]
        if kind == "market":
            continue    # 大盤不登記成分，不會有變動
        cur = members.get((kind, sid))
        if cur is not None and members_hash(cur) != s.get("members_hash"):
            changed.add(key_str(kind, sid))
    return {"series": series, "first_date": first_date, "changed": changed,
            "members": members, "mapping": mapping}


index_cache = SnapshotCache(load_index)


def node_series(node_ids: list[str], since: str) -> dict[str, list[tuple]]:
    """節點指數即時讀取（不快取）。"""
    if not node_ids:
        return {}
    return series_by_key(database.fetch_index_rows(["node"], since, node_ids))
