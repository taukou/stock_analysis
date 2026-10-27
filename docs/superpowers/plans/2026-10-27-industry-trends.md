# 產業趨勢功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日自動計算並補抓一年的產業／上中下游／節點／大盤等權指數，並在網站上呈現走勢圖、強弱排行、輪動圖、法人流向、節點內強弱、每日摘要與自選股提醒。

**Architecture:** 同步端新增 `industry_index.py`（純計算）、`sync/index_job.py`（每日往後接）、`sync/index_backfill.py`（往前補抓一年），結果寫入 `industry_index_daily`／`industry_index_scopes` 兩張小表。網站端新增 `industry_trends.py`（純計算：換算、區間漲跌、輪動、法人加總、摘要）與 `index_data.py`（讀指數表＋快取），由 `app.py` 的新 API 與頁面使用；前端新增 `static/js/trend.js`（純函式＋圖表）。

**Tech Stack:** Python 3.13、Flask 3.1、supabase-py 2.29、waitress、pytest；D3 v7、Node 22 `node --test`。

**Spec:** `docs/superpowers/specs/2026-10-27-industry-trends-design.md`

## Global Constraints

- 網站只綁 127.0.0.1:8765；不可用 5000；不自動開瀏覽器。
- 缺值一律 None／null，絕不以 0 代替（不納入平均、不納入加總）。
- 測試一律不連 Supabase、不寫 Supabase（用 `tests/fakes.py` 的 FakeStore 或 monkeypatch）。
- 金鑰只在本機 `.env`；不得出現在程式、測試、報告、commit；不得印出 `.env`。
- 建表 SQL 由使用者貼到 Supabase SQL Editor 執行：整份包在單一 `do $tag$ ... $tag$;` 區塊，不用 begin/commit、不跨語句用暫存表。
- 新表要有 RLS 與 `anon_read` select policy（同 `db/001_pipeline.sql` 的做法），網站用匿名 key 讀。
- 指數只算 上市／上櫃；大盤＝4 位數代號且不以 `00` 開頭。
- 大盤出現處都要附 MARKET_NOTE（文字見 Task 4），可為 tooltip（title 屬性）或圖下小字，不能沒有。
- 新畫面沿用現有 Liquid Glass 樣式（`glass`、`glass-pill`、`refract` class 與 `:root` 色票），不重做美術。
- 程式風格：中文註解與訊息、照現有模組的寫法；commit 結尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 測試指令：`.venv\Scripts\python.exe -m pytest -q`、`node --test "tests/js/*.test.js"`。

## Review Focus

1. 某股某日沒有收盤價、或除權息日 `ref_price` 缺漏 → 該股當日不納入平均（不是 0%）；所有成分都缺時當日 `ret_pct` 為 None、指數持平。→ Task 1 測試。
2. 補抓時交易所只回一個市場（或抓取例外）→ 立即停止、這天不寫任何列、JobResult 為 failed。→ Task 3 測試。
3. 補抓中斷後重跑，結果要與一次跑完完全相同（不重複、不位移）。→ Task 3 測試。
4. 指數表空的（使用者還沒跑 SQL 或第一天）→ API 回 200 與空序列、頁面顯示「尚無指數資料」，不 500；讀取例外 → 503 JSON。→ Task 5 測試。
5. 選 1Y 但只有 3 個月資料 → 用現有資料換算、回傳 `first_date`，畫面標「指數資料從 X 起」。→ Task 4 測試。

---

### Task 1: 指數表 SQL 與指數純計算

**Files:**
- Create: `db/006_industry_index.sql`
- Create: `industry_index.py`
- Test: `tests/test_industry_index.py`

**Interfaces:**
- Produces（`industry_index.py`）：
  - `MARKET_KEY = ("market", "TW")`
  - `is_market_stock(stock_id: str) -> bool`
  - `scope_members(mapping: list[dict]) -> dict[tuple[str, str], frozenset[str]]`：mapping 列為 `{node_id, stock_id, major_id, position_type}`；鍵為 `("major", major_id)`、`("tier", f"{major_id}:{position_type}")`、`("node", node_id)`；不含大盤。
  - `members_hash(members: frozenset[str]) -> str`：排序後以 `,` 串接的 sha1 hex。
  - `closes_by_stock(quotes: list[dict]) -> dict[str, float]`：只取 market 為 上市／上櫃 且 close 非 None 且 > 0。
  - `stock_returns(prev_close: dict[str, float], close: dict[str, float], ex_ref: dict[str, float | None]) -> dict[str, float]`：小數報酬；`sid in ex_ref` 時以 `ex_ref[sid]` 為基準（None 或 ≤0 則略過該股），否則用 `prev_close`。
  - `average_return(returns: dict[str, float], members: Iterable[str] | None) -> tuple[float | None, int]`：members 為 None 代表大盤（以 `is_market_stock` 篩選 returns）。
  - `step_forward(level: float, ret: float | None) -> float`、`step_backward(next_level: float, next_ret: float | None) -> float`：ret 為 None 時持平。
  - `index_row(key: tuple[str, str], trade_date: str, level: float, ret: float | None, n: int) -> dict`：`{"scope_kind", "scope_id", "trade_date", "level": round(level, 6), "ret_pct": None or round(ret*100, 4), "members": n}`。
  - 資料表 `industry_index_daily(scope_kind text check in ('market','major','tier','node'), scope_id text, trade_date date, level numeric not null, ret_pct numeric, members int not null default 0, updated_at timestamptz default now(), primary key (scope_kind, scope_id, trade_date))`
  - 資料表 `industry_index_scopes(scope_kind text, scope_id text, members_hash text, member_count int, updated_at timestamptz default now(), primary key (scope_kind, scope_id))`

- [ ] **Step 1: Write the failing tests**

```python
import industry_index as ix

def test_market_stock_filter():
    assert ix.is_market_stock("2330") and not ix.is_market_stock("0050")
    assert not ix.is_market_stock("00878") and not ix.is_market_stock("2330A")

def test_scope_members_groups_and_dedupes():
    m = [{"node_id": "N1", "stock_id": "1111", "major_id": "M02", "position_type": "Upstream"},
         {"node_id": "N2", "stock_id": "1111", "major_id": "M02", "position_type": "Downstream"},
         {"node_id": "N2", "stock_id": "2222", "major_id": "M02", "position_type": "Downstream"}]
    s = ix.scope_members(m)
    assert s[("major", "M02")] == frozenset({"1111", "2222"})
    assert s[("tier", "M02:Downstream")] == frozenset({"1111", "2222"})
    assert s[("node", "N1")] == frozenset({"1111"})
    assert ix.MARKET_KEY not in s

def test_returns_skip_missing_and_use_ref_price_on_ex_date():
    r = ix.stock_returns({"A": 100, "B": 50, "C": 10}, {"A": 110, "B": 45, "D": 5, "E": 9},
                         {"B": 40, "E": None})
    assert r == {"A": 0.1, "B": 0.125}        # C 今天沒價、D 沒昨收、E 參考價缺 → 不納入

def test_average_excludes_missing_and_none_when_empty():
    assert ix.average_return({"1111": 0.1, "2222": -0.1}, {"1111", "2222", "3333"}) == (0.0, 2)
    assert ix.average_return({"1111": 0.1}, {"9999"}) == (None, 0)
    assert ix.average_return({"1111": 0.1, "0050": 0.5}, None) == (0.1, 1)   # 大盤排除 ETF

def test_steps_are_inverse_and_flat_on_none():
    assert ix.step_backward(ix.step_forward(100, 0.05), 0.05) == 100
    assert ix.step_forward(100, None) == 100 and ix.step_backward(100, None) == 100

def test_hash_is_order_independent():
    assert ix.members_hash(frozenset({"2", "1"})) == ix.members_hash(frozenset({"1", "2"}))

def test_index_row_shape():
    assert ix.index_row(("node", "N1"), "2026-10-27", 101.23456789, 0.0123456, 3) == {
        "scope_kind": "node", "scope_id": "N1", "trade_date": "2026-10-27",
        "level": 101.234568, "ret_pct": 1.2346, "members": 3}
    assert ix.index_row(ix.MARKET_KEY, "2026-10-27", 100, None, 0)["ret_pct"] is None

def test_sql_is_single_do_block_with_rls():
    sql = (ix.ROOT / "db" / "006_industry_index.sql").read_text(encoding="utf-8")
    assert sql.count("do $idx$") == 1 and sql.rstrip().endswith("$idx$;")
    assert "industry_index_daily" in sql and "industry_index_scopes" in sql
    assert "anon_read" in sql and "enable row level security" in sql
    assert "begin;" not in sql and "commit;" not in sql and "delete" not in sql.lower()
```

（`ix.ROOT = Path(__file__).resolve().parent`，與 `build_chain_sql.py` 相同寫法。）

- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_industry_index.py -q` — Expected: FAIL（module not found）
- [ ] **Step 3: Implement** `industry_index.py`（上列介面）與 `db/006_industry_index.sql`：`do $idx$ begin ... end $idx$;` 內用 `execute` 建兩張表（`create table if not exists`）、`alter table ... enable row level security`、policy 不存在時 `create policy anon_read ... for select to anon, authenticated using (true)`、`create index if not exists` on `industry_index_daily(trade_date)`。
- [ ] **Step 4: Run** 同 Step 2 — Expected: PASS；再跑全部 pytest 確認無回歸。
- [ ] **Step 5: Commit** `feat(index): 指數表 SQL 與等權指數純計算`

---

### Task 2: 每日指數更新工作

**Files:**
- Create: `sync/index_job.py`
- Modify: `sync/store.py`（新增讀取方法）、`tests/fakes.py`（同名方法）、`run_sync.py`、`freshness.py`（DATASET_ORDER／LABELS）
- Test: `tests/test_index_job.py`、`tests/test_run_sync.py`、`tests/test_freshness.py`

**Interfaces:**
- Consumes: Task 1 全部。
- Produces:
  - Store／FakeStore 新方法：
    - `chain_mapping() -> list[dict]`（`{node_id, stock_id, major_id, position_type}`，分頁讀完；Store 用 `company_node_mapping` 嵌入 `value_chain_nodes(major_id, position_type)`）
    - `quotes_between(start: str, end: str, ids: list[str] | None = None) -> list[dict]`（`stock_id, trade_date, market, close`）
    - `ex_rights_between(start: str, end: str) -> list[dict]`（`stock_id, ex_date, ref_price`）
    - `index_rows_on(trade_date: str) -> list[dict]`（該日所有範圍的列）
    - `index_scope_keys() -> set[tuple[str, str]]`（`industry_index_scopes` 現有鍵）
    - FakeStore 以 `self.tables` 實作，測試直接塞列。
  - `sync/index_job.py`：`DATASET = "industry_index"`、`TABLE = "industry_index_daily"`、`ON_CONFLICT = "scope_kind,scope_id,trade_date"`、`SCOPE_TABLE = "industry_index_scopes"`、`SCOPE_CONFLICT = "scope_kind,scope_id"`、`sync_index(store, now: datetime) -> JobResult`。

行為（`sync_index`）：
1. `last` = 大盤（`scope_kind="market"`）最新 trade_date。
2. 讀 `quotes_between(last − 14 天 或 "2000-01-01", today)`，交易日用 `trends.trading_dates`，由舊到新。
3. 沒有 `last`：第一個交易日所有範圍＋大盤寫 level 100、ret None、members 0，之後逐日往後接。
4. 有 `last`：從 `index_rows_on(last)` 取各範圍前值，對 `> last` 的交易日逐日 `step_forward`。
5. 範圍集合＝`scope_members(chain_mapping())` 加大盤。現有範圍中不在 `index_scope_keys()` 的是**新範圍**：另以 `quotes_between("2000-01-01", today, ids=該範圍成分)` 從資料庫最早交易日起（100）算到今天，並寫入 `industry_index_scopes`（hash、member_count）。第一次執行（無 last）時所有範圍都寫入 scopes。既有範圍**不更新** hash（用來偵測成分變動）。
6. 除權息參考價取 `ex_rights_between`，只對當日 `ex_date` 生效。
7. 回 `JobResult(DATASET, "ok", 最新寫入日或 last, 寫入列數)`；任何例外回 failed（訊息含例外）。

- [ ] **Step 1: Write the failing tests**（FakeStore 塞 `daily_quotes`、`ex_rights`、`company_node_mapping` 的等價資料；為了讓 FakeStore 回 `chain_mapping()`，測試直接設 `store.mapping = [...]`）

```python
def test_first_run_starts_at_100_and_chains_forward(): ...
    # 三個交易日 d1,d2,d3；1111: 10→11→11；2222: 20→18→18（d3 除權息，ref 15 → +20%）
    # assert 大盤 d1 level 100 ret None；d2 ret_pct == 0.0（+10%、−10% 平均）；
    # assert d3 ret_pct == 10.0（0%、+20% 平均）、level == 110.0；node 範圍同理
def test_second_run_appends_only_new_days(): ...
    # 跑兩次，第二次前加 d4 → 只多 d4 列，d1–d3 未被改寫（FakeStore.upserts 次數／列數）
def test_missing_close_not_counted_as_zero(): ...
    # d2 2222 無報價 → node 範圍 d2 members == 1、ret_pct == 10.0
def test_new_scope_backfilled_from_db_start_and_registered(): ...
    # 第二次執行前 mapping 加新節點 N9 → N9 從 d1 起有列；industry_index_scopes 有 N9；
    # 既有範圍的 members_hash 未被更新（mapping 改了 N1 成分也不更新）
def test_no_new_quotes_writes_nothing(): ...
def test_exception_returns_failed(): ...
```

另在 `tests/test_run_sync.py` 加：`test_index_job_runs_after_daily_jobs`（`sync_index` 在原本 jobs 與 fill/refresh 步驟之後執行，且即使前面 job 失敗也會執行、結果有 record_run）；在 `tests/test_freshness.py` 加：`industry_index` failed 時 level 為 failed、訊息含「產業指數」。

- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_index_job.py tests/test_run_sync.py tests/test_freshness.py -q` — Expected: FAIL
- [ ] **Step 3: Implement** 上列介面。`run_sync.run`：原本的 jobs 與 steps 跑完後，依序執行 `sync_index`、`backfill_index`（Task 3 才建立；本 Task 先只接 `sync_index`，`backfill_index` 在 Task 3 接上），各自 `record_run`。`freshness.py`：`DATASET_ORDER` 末尾加 `"industry_index", "index_backfill"`，`DATASET_LABELS` 加 `"industry_index": "產業指數", "index_backfill": "指數補抓"`；兩者都不列入 `STALE_CHECKED`。
- [ ] **Step 4: Run** 同 Step 2 與全部 pytest — Expected: PASS
- [ ] **Step 5: Commit** `feat(index): 每日產業指數更新並接上同步排程`

---

### Task 3: 往前補抓一年與重算指令

**Files:**
- Create: `sync/index_backfill.py`、`rebuild_index.py`
- Modify: `run_sync.py`、`README.md`
- Test: `tests/test_index_backfill.py`、`tests/test_run_sync.py`

**Interfaces:**
- Consumes: Task 1、Task 2 的 Store 方法與常數。
- Produces:
  - `sync/index_backfill.py`：`DATASET = "index_backfill"`、`BACKFILL_DAYS = 365`、`backfill_index(store, now: datetime, fetchers: tuple[Callable, Callable] = (twse.fetch_quotes, tpex.fetch_quotes), max_days: int = 260, max_holiday_run: int = 15) -> JobResult`
  - `rebuild_index.py`：`rebuild(store, now: datetime, fetchers=...) -> int`（回寫入列數）與 `main()`。

行為（`backfill_index`）：
1. `m` = 大盤最早 trade_date（`store` 新增 `first_value(table, column, filters)`，FakeStore 同名）；沒有 → ok、rows 0、message「尚無指數，等每日更新先建立」。
2. `target = now.date() − 365 天`；`m <= target` → ok、rows 0（已補完，不抓任何資料）。
3. `m` 當天收盤：資料庫有（`quotes_between(m, m)`）就用，否則用 fetchers 抓。
4. 只延伸 `index_rows_on(m)` 裡存在的範圍；成分用目前 `scope_members(chain_mapping())`，大盤用 `is_market_stock`。
5. 往前找前一個工作日 `d`：兩個市場都空 → 休市，再往前（連續超過 `max_holiday_run` 個工作日都空 → failed）；只有一個市場空、或抓取例外 → failed，不寫任何列。
6. 用 `closes_by_stock(d 的行情)` 當前收、`m` 的收盤與 `m` 當日除權息參考價算報酬：更新 `m` 列的 `ret_pct`／`members`，新增 `d` 列 `level = step_backward(level_m, avg)`、ret None、members 0。兩列同一次 upsert（每天寫一次，中斷可續跑）。
7. `m = d`，直到 `m <= target` 或已處理 `max_days` 個交易日。回 `JobResult(DATASET, "ok", 最早日期, 列數)`。

行為（`rebuild`）：從 `today − 365` 到今天逐日用 fetchers 抓兩市場（規則同上），全部在記憶體以 level 100 起往後算完所有範圍與大盤，最後一次 upsert 全部列，並 upsert 所有範圍的 `industry_index_scopes`（新 hash）。中途失敗則不寫任何列並回傳非 0。`main()` 照 `build_chain_sql.py` 的 logging 寫法。

- [ ] **Step 1: Write the failing tests**

```python
def test_backfill_extends_backwards_and_fills_seam(): ...
    # 指數已有 d3(100, ret None)、d4；fetchers 提供 d1、d2（d3 從 FakeStore daily_quotes）
    # 跑完：d3 ret_pct 有值、d2/d1 level = 反推值、最早列 ret None
def test_resume_equals_single_run(): ...
    # 同一份資料：max_days=1 跑兩次 vs max_days=2 跑一次 → industry_index_daily 內容完全相同
def test_one_market_missing_fails_without_writing(): ...
def test_fetch_exception_fails_without_writing(): ...
def test_holidays_skipped(): ...
    # d2 兩市場都空 → d3 的前一交易日是 d1
def test_done_when_reached_target_fetches_nothing(): ...
    # fetchers 被呼叫即 raise；最早日期已 ≤ today−365 → ok、rows 0
def test_rebuild_writes_all_or_nothing(): ...
    # 第二天抓取失敗 → FakeStore.upserts 為空、回傳非 0
```

`tests/test_run_sync.py`：`backfill_index` 緊接在 `sync_index` 之後執行，`sync_index` 失敗時仍會執行。

- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_index_backfill.py tests/test_run_sync.py -q` — Expected: FAIL
- [ ] **Step 3: Implement** 上列介面；`run_sync` 在 `sync_index` 之後接 `backfill_index`。README 新增「產業指數」一節：說明 `db/006_industry_index.sql` 要先執行、每日自動更新與補抓（第一次 20–40 分鐘）、成分變動後重算指令 `.venv\Scripts\python.exe rebuild_index.py`。
- [ ] **Step 4: Run** 同 Step 2 與全部 pytest — Expected: PASS
- [ ] **Step 5: Commit** `feat(index): 往前補抓一年的產業指數與重算指令`

---

### Task 4: 網站端趨勢計算與資料讀取

**Files:**
- Create: `industry_trends.py`、`index_data.py`
- Modify: `database.py`、`snapshot.py`、`app.py`（`to_lots` 改從 `industry_trends` 匯入）
- Test: `tests/test_industry_trends.py`、`tests/test_snapshot.py`、`tests/test_index_data.py`

**Interfaces:**
- Consumes: Task 1 的表結構與 `scope_members`、`members_hash`。
- Produces（`industry_trends.py`，純計算）：
  - `MARKET_NOTE = "此為自行計算的等權大盤（上市＋上櫃，排除 ETF，已還原除權息），與證交所公布的加權指數不同"`
  - `SURVIVOR_NOTE = "成分股以目前名單往回計算，不含已下市公司"`
  - `RANGES = {"1M": 21, "3M": 63, "6M": 126, "1Y": 250}`（交易日數）
  - `to_lots(shares) -> int | None`（自 app.py 移來，行為不變）
  - `key_str(kind: str, scope_id: str) -> str`（`"major:M02"`；tier 為 `"tier:M02:Upstream"`）
  - `series_by_key(rows: list[dict]) -> dict[str, list[tuple[str, float]]]`（日期由舊到新）
  - `rebase(points, n: int) -> list[dict]`：取最後 n+1 點，首點為 100，`{"date", "value": round(..., 2)}`；不足時用全部。
  - `period_change(points, n: int) -> float | None`：`(最後 ÷ 倒數第 n+1 點 − 1) × 100`，round 2；點數不足 None。
  - `rrg(ind, mkt, window=50, roc=10, trail_weeks=8, step=5) -> dict | None`：以日期交集對齊；`rs = ind/mkt`；`x_t = 100 × rs_t ÷ mean(rs 最近 window 點，含 t)`；`y_t = 100 × x_t ÷ x_{t−roc}`；需 t 之前至少 `window − 1 + roc` 點才有值。回 `{"x","y","quadrant","trail": [{"date","x","y"}...舊到新，每 step 點一個，最多 trail_weeks 個且只含可計算者]}`（x、y round 2）；最新點不可計算回 None。
  - `quadrant(x, y) -> str`：x≥100 且 y≥100「領先」、x≥100 且 y<100「轉弱」、x<100 且 y<100「落後」、x<100 且 y≥100「轉強」。
  - `flow_totals(flow_sums: dict, members: Iterable[str], n: int) -> dict`：`{"foreign_lots", "trust_lots", "count"}`；只加非 None 的股（股數），最後 `to_lots`；count 為有資料家數；全缺時兩者 None。
  - `daily_digest(...)`（Task 8 定義，此處不做）。
- Produces（`snapshot.py`）：快照新增 `"flows": {sid: {1|5|20: {"foreign": int|None, "trust": int|None}}}` 與 `"flow_date": str|None`。視窗＝法人資料自己的交易日（新到舊）前 n 個；股在視窗內沒有列 → None；有列則加總非 None 值，全 None → None。
- Produces（`database.py`）：
  - `fetch_chain_mapping() -> list[dict]`（同 Task 2 的欄位，網站端用匿名 key）
  - `fetch_index_rows(kinds: list[str], since: str, scope_ids: list[str] | None = None) -> list[dict]`
  - `fetch_index_scopes() -> list[dict]`
- Produces（`index_data.py`）：
  - `load_index(today: date | None = None) -> dict`：讀 market／major／tier 近 400 天列、`fetch_index_scopes()`、`fetch_chain_mapping()`（三者並行，照 `snapshot.load_snapshot` 的 ThreadPoolExecutor 寫法），回 `{"series": series_by_key(...), "first_date": {key: 最早日期}, "changed": set[key]（hash 與目前成分不同者）, "members": scope_members(...), "mapping": [...]}`。
  - `index_cache = SnapshotCache(load_index)`
  - `node_series(node_ids: list[str], since: str) -> dict[str, list[tuple]]`（即時讀，不快取）

- [ ] **Step 1: Write the failing tests**

```python
import industry_trends as t

def pts(vals, start=1):
    return [(f"2026-01-{i + start:02d}", v) for i, v in enumerate(vals)]

def test_rebase_uses_available_history_when_range_longer():
    assert t.rebase(pts([50, 55, 60]), 250) == [
        {"date": "2026-01-01", "value": 100.0}, {"date": "2026-01-02", "value": 110.0},
        {"date": "2026-01-03", "value": 120.0}]
    assert t.rebase(pts([50, 55, 60]), 1)[0] == {"date": "2026-01-02", "value": 100.0}

def test_period_change():
    assert t.period_change(pts([100, 105, 110]), 2) == 10.0
    assert t.period_change(pts([100]), 1) is None

def test_quadrants():
    assert [t.quadrant(*p) for p in [(101, 101), (101, 99), (99, 99), (99, 101)]] == ["領先", "轉弱", "落後", "轉強"]

def test_rrg_flat_relative_is_centre_and_short_history_none():
    mkt = [(f"d{i:03d}", 100 + i) for i in range(80)]
    ind = [(d, v * 2) for d, v in mkt]
    r = t.rrg(ind, mkt)
    assert (r["x"], r["y"], r["quadrant"]) == (100.0, 100.0, "領先")
    assert 1 <= len(r["trail"]) <= 8 and r["trail"][-1]["date"] == "d079"
    assert t.rrg(ind[:55], mkt[:55]) is None   # 不足 50−1+10 點

def test_rrg_outperformer_is_right_of_centre():
    mkt = [(f"d{i:03d}", 100.0) for i in range(80)]
    ind = [(d, 100.0 * 1.0005 ** (i * i)) for i, (d, _) in enumerate(mkt)]   # 加速走強：相對強弱與其變化都向上
    r = t.rrg(ind, mkt)
    assert r["x"] > 100 and r["y"] > 100

def test_flow_totals_skip_missing():
    sums = {"A": {5: {"foreign": 1500, "trust": None}}, "B": {5: {"foreign": None, "trust": None}},
            "C": {5: {"foreign": 2500, "trust": 4000}}}
    assert t.flow_totals(sums, ["A", "B", "C", "D"], 5) == {"foreign_lots": 4, "trust_lots": 4, "count": 2}
    assert t.flow_totals(sums, ["B", "D"], 5) == {"foreign_lots": None, "trust_lots": None, "count": 0}
```

`tests/test_snapshot.py`：`test_flow_sums_use_flow_dates_and_keep_none`（法人日期比股價少兩天時，5 日視窗仍是法人自己的最近 5 天；無列的股為 None）。
`tests/test_index_data.py`：monkeypatch 三個 database 函式；`test_changed_detects_member_hash_difference`、`test_first_date_per_key`、`test_empty_tables_give_empty_series`。

- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_industry_trends.py tests/test_snapshot.py tests/test_index_data.py -q` — Expected: FAIL
- [ ] **Step 3: Implement** 上列介面。
- [ ] **Step 4: Run** 同 Step 2 與全部 pytest — Expected: PASS
- [ ] **Step 5: Commit** `feat(trends): 網站端指數換算、輪動、法人加總與資料快取`

---

### Task 5: 趨勢 API

**Files:**
- Modify: `app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: Task 4 全部。
- Produces（JSON）：
  - `GET /api/index_series?keys=<逗號分隔 key_str，最多 12 個>&range=1M|3M|6M|1Y`（預設 3M）→ `{"series": {key: [{date, value}]}, "first_date": {key: date|null}, "changed": [key...], "notes": {"market": MARKET_NOTE, "survivor": SURVIVOR_NOTE}}`。node key 用 `index_data.node_series` 即時讀，其他取 `index_cache`。key 格式不符、未知 kind、超過 12 個、range 不合法 → 400。
  - `GET /api/industry_ranking` → `{"rows": [{"major_id", "name", "r1", "r5", "r20", "foreign5", "trust5", "flow_count"}], "market": {"r1", "r5", "r20"}, "flow_date", "notes": {...}}`；r* 由 `period_change`（n=1/5/20），法人由快照 `flow_totals(..., 5)`。
  - `GET /api/rotation` → `{"points": [{"major_id", "name", "x", "y", "quadrant", "trail"}], "as_of", "notes": {...}}`；rrg 為 None 的產業不列入。
  - `GET /api/node_flows/<major_id>?period=1|5|20` → `{"flow_date", "nodes": [{"node_id", "foreign_lots", "trust_lots", "count"}]}`（沿用 `parse_period`）。
  - 讀取失敗一律 `ApiError("資料暫時無法讀取", 503)`（同 `get_snapshot_or_503` 寫法，新增 `get_index_or_503()`）。

- [ ] **Step 1: Write the failing tests**（monkeypatch `app.index_cache.get`、`app.snapshot_cache.get`、`app.index_data.node_series`、`get_all_industries`）

```python
def test_index_series_rebases_and_reports_first_date(client, ...): ...
def test_index_series_empty_table_is_200_with_empty_series(client, ...): ...
def test_index_series_rejects_bad_keys_and_range(client):
    for q in ["keys=foo", "keys=major:M02&range=2Y", "keys=" + ",".join(f"node:N{i}" for i in range(13))]:
        assert client.get(f"/api/index_series?{q}").status_code == 400
def test_index_series_503_when_load_fails(client, ...): ...
def test_ranking_rows_and_market_with_note(client, ...): ...
def test_rotation_omits_short_history(client, ...): ...
def test_node_flows_counts_only_present(client, ...): ...
```

- [ ] **Step 2: Run** `.venv\Scripts\python.exe -m pytest tests/test_app.py -q` — Expected: FAIL
- [ ] **Step 3: Implement** 上列路由。
- [ ] **Step 4: Run** 全部 pytest — Expected: PASS
- [ ] **Step 5: Commit** `feat(api): 指數走勢、產業排行、輪動與節點法人 API`

---

### Task 6: 產業頁走勢面板（功能 1、4）

**Files:**
- Create: `static/js/trend.js`
- Modify: `templates/industry_d3.html`、`static/js/industry.js`（只加開關與節點清單資料來源）
- Test: `tests/js/trend.test.js`

**Interfaces:**
- Consumes: `/api/index_series`。
- Produces（`trend.js`，瀏覽器 `window.Trend`、node 用 `module.exports`，同 `layout.js` 寫法）：
  - `seriesKeys(majorId: string, mode: "industry"|"tiers", nodeIds: string[]) -> string[]`：industry → `["market:TW", "major:<id>"]`；tiers → `["market:TW", "tier:<id>:Upstream", "tier:<id>:Midstream", "tier:<id>:Downstream"]`；再接 `node:<id>`（最多 5 個節點）。
  - `firstDateNote(firstDates: object, rangeStart: string) -> string | null`：任一序列的最早日期晚於所選區間應有的起點時，回「指數資料從 YYYY-MM-DD 起」（取最晚的那個），否則 null。
  - `lineChart(container, series: {key, label, points:[{date,value}], dashed?}[], opts)`：D3 多線圖，滑鼠移上顯示當日各線值；大盤線用虛線，圖例的大盤項目附 `title=MARKET_NOTE`。
- 面板：產業頁右下（避開現有 freshness／legend 位置）一個 glass 按鈕「走勢」開關一個可收合 glass 面板；內含區間 1M/3M/6M/1Y、模式「產業 vs 大盤」／「上中下游」、節點勾選清單（從已載入的節點資料取；最多 5 個）。Ruling：spec 寫「點一個節點加入它的線」，但點節點目前是進入聚焦模式，改用面板內勾選清單，避免改變既有操作。面板底部固定兩行小字：MARKET_NOTE 與 SURVIVOR_NOTE；`changed` 含目前任一 key 時加一行「成分已變動，指數為舊名單」；`firstDateNote` 有值時顯示。序列全空時顯示「尚無指數資料」。上中下游模式只畫該產業實際存在的層（沒有的層不顯示、也不報錯）。

- [ ] **Step 1: Write the failing tests**

```js
const T = require("../../static/js/trend.js");
test("series keys per mode and node cap", () => {
  assert.deepStrictEqual(T.seriesKeys("M02", "industry", []), ["market:TW", "major:M02"]);
  assert.strictEqual(T.seriesKeys("M02", "tiers", ["a","b","c","d","e","f"]).length, 4 + 5);
});
test("first date note only when history is shorter than range", () => {
  assert.strictEqual(T.firstDateNote({ "major:M02": "2026-07-23" }, "2025-10-27"), "指數資料從 2026-07-23 起");
  assert.strictEqual(T.firstDateNote({ "major:M02": "2025-10-01" }, "2026-07-27"), null);
});
```

- [ ] **Step 2: Run** `node --test "tests/js/*.test.js"` — Expected: FAIL
- [ ] **Step 3: Implement**；前端區間起點以「今天往前 RANGES 天數 × 7/5 個日曆日」估算即可（只用來決定是否顯示提示）。
- [ ] **Step 4: Run** JS 測試與全部 pytest — Expected: PASS；重啟網站（`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/restart_web.ps1`），用 Edge headless 截 M01、M05 產業頁開啟面板的畫面確認（指數表為空時應顯示「尚無指數資料」）。
- [ ] **Step 5: Commit** `feat(ui): 產業頁走勢面板（產業 vs 大盤、上中下游、節點）`

---

### Task 7: 節點法人顯示切換與節點內強弱（功能 6、7）

**Files:**
- Modify: `static/js/trend.js`、`static/js/industry.js`、`templates/industry_d3.html`
- Test: `tests/js/trend.test.js`

**Interfaces:**
- Consumes: `/api/node_flows/<major_id>`、既有 `/api/node_companies`。
- Produces（`trend.js`）：
  - `relativeRanks(companies: {id, change}[]) -> Map<id, {diff: number|null, tag: "lead"|"lag"|null}>`：平均只取非 null；`diff = round2(change − 平均)`；k 為有值家數，`m = min(3, floor(k/2))`，前 m 名 lead、後 m 名 lag；change 為 null 的 diff 與 tag 都是 null。
  - `formatLots(v: number|null) -> string`：null →「—」，其餘加正負號與千分位＋「張」。
- 總覽：在區間切換旁加 glass 切換「漲跌｜外資｜投信」；外資／投信時節點副標改為「外資 +1,234 張（n 家）」，區間沿用目前 1/5/20，並在副標或 legend 顯示「法人資料至 <flow_date>」。顏色沿用漲跌色（正紅負綠，同現有 heatColor 慣例）。
- 聚焦：公司標籤第二行改為「+1.2%（較節點 +0.8）」，lead 加「領漲」小標、lag 加「落後」小標；compact／none 標籤模式下不加差距文字（避免擠）。

- [ ] **Step 1: Write the failing tests**

```js
test("relative ranks: diff vs node average, lead/lag counts, nulls untouched", () => {
  const cs = [1, 2, 3, 4, 5, 6, 7].map((v, i) => ({ id: `c${i}`, change: v })).concat([{ id: "n", change: null }]);
  const r = T.relativeRanks(cs);
  assert.deepStrictEqual(r.get("c6"), { diff: 3, tag: "lead" });
  assert.strictEqual(r.get("c0").tag, "lag");
  assert.strictEqual([...r.values()].filter(v => v.tag === "lead").length, 3);
  assert.deepStrictEqual(r.get("n"), { diff: null, tag: null });
  assert.strictEqual(T.relativeRanks([{ id: "a", change: 1 }]).get("a").tag, null);
});
test("formatLots", () => {
  assert.strictEqual(T.formatLots(null), "—");
  assert.strictEqual(T.formatLots(1234), "+1,234 張");
  assert.strictEqual(T.formatLots(-5), "-5 張");
});
```

- [ ] **Step 2–4:** 跑 JS 測試（FAIL → 實作 → PASS）；重啟網站並截圖 M04 總覽（外資模式）與一個節點聚焦畫面確認。
- [ ] **Step 5: Commit** `feat(ui): 節點法人流向切換與節點內領漲／落後標示`

---

### Task 8: 首頁產業排行與輪動圖、每日摘要頁（功能 2、3、8）

**Files:**
- Create: `templates/daily.html`
- Modify: `templates/home.html`、`static/js/trend.js`、`industry_trends.py`、`app.py`
- Test: `tests/test_industry_trends.py`、`tests/test_app.py`、`tests/js/trend.test.js`

**Interfaces:**
- Consumes: `/api/industry_ranking`、`/api/rotation`、Task 4 的快照與 index_cache。
- Produces:
  - `industry_trends.daily_digest(majors: list[dict], nodes: list[dict], node_flows: list[dict], signal_companies: list[dict]) -> dict`：
    - majors 列 `{major_id, name, r1}` → `strong_majors`／`weak_majors`：r1 非 None 者依 r1 排序取前／後 3。
    - nodes 列 `{node_id, name, major_id, change}` → `strong_nodes`／`weak_nodes` 各 5。
    - node_flows 列 `{node_id, name, major_id, foreign_lots, trust_lots}` → `flow_nodes`：`net = 非 None 者相加`，兩者皆 None 的節點排除，取 net 前 5。
    - signal_companies 列 `{stock_id, name, node_id, major_id, signals:[{code,label,detail}]}` → `signal_groups`：依 code 分組，順序 `trust_streak, yoy_turn, revenue_high, volume_spike`，每組 `{"code", "label", "companies": [...]}`；空組不列。
  - `GET /daily` → render `daily.html`（`digest`、`freshness` 訊息、`MARKET_NOTE`、`flow_date`、`latest_date`）。節點今日漲跌用快照 returns 對 `index_data` mapping 的節點成分取平均（同 `api_industry_heat` 算法）；只列產業鏈公司（mapping 內）的訊號。讀取失敗時頁面顯示「資料暫時無法讀取」而不是 500。
  - `trend.js`：`sortRows(rows, key, desc) -> rows`（null 一律排最後，不論升降冪）；`rotationChart(container, points, notes)`（D3 散點＋軌跡＋四象限標字＋軸標題「相對大盤強弱」「強弱變化速度」，軸標題附 `title=MARKET_NOTE`，圖下小字 MARKET_NOTE）。
  - 首頁：導覽列在「產業列表」後加「產業排行」「輪動」兩個 nav-tab（沿用現有 scroll-spy），再加一個連到 `/daily` 的「今日摘要」連結。排行表欄位：產業、今日、5 日、20 日、外資 5 日、投信 5 日；點標題排序；點產業名進產業頁；表上方一列「大盤」附 MARKET_NOTE（title）並在表下小字列出 MARKET_NOTE 與「法人資料至 <flow_date>」。輪動圖沒有點時顯示「指數資料不足 60 個交易日，暫無輪動圖」。

- [ ] **Step 1: Write the failing tests**

```python
def test_digest_ranks_skip_none_and_group_signals():
    d = t.daily_digest(
        majors=[{"major_id": "M01", "name": "半導體", "r1": 1.0}, {"major_id": "M02", "name": "電腦", "r1": None},
                {"major_id": "M03", "name": "通信", "r1": -2.0}],
        nodes=[], node_flows=[{"node_id": "N1", "name": "a", "major_id": "M01", "foreign_lots": None, "trust_lots": None},
                              {"node_id": "N2", "name": "b", "major_id": "M01", "foreign_lots": 10, "trust_lots": None}],
        signal_companies=[{"stock_id": "2330", "name": "台積電", "node_id": "N1", "major_id": "M01",
                           "signals": [{"code": "volume_spike", "label": "爆量", "detail": ""},
                                       {"code": "trust_streak", "label": "投信連買 5 日", "detail": ""}]}])
    assert [m["major_id"] for m in d["strong_majors"]] == ["M01", "M03"]
    assert d["weak_majors"][0]["major_id"] == "M03"
    assert [f["node_id"] for f in d["flow_nodes"]] == ["N2"]
    assert [g["code"] for g in d["signal_groups"]] == ["trust_streak", "volume_spike"]
```

`tests/test_app.py`：`test_daily_page_renders_with_note`（含 MARKET_NOTE 文字）、`test_daily_page_shows_message_when_data_unavailable`（status 200、含「資料暫時無法讀取」）。
`tests/js/trend.test.js`：`sortRows` 升降冪皆把 null 放最後。

- [ ] **Step 2–4:** FAIL → 實作 → 全部 pytest 與 JS 測試 PASS；重啟網站，截首頁排行、輪動區塊與 `/daily`。
- [ ] **Step 5: Commit** `feat(ui): 首頁產業排行與輪動圖、每日摘要頁`

---

### Task 9: 自選股提醒（功能 9）

**Files:**
- Modify: `app.py`（`/api/companies` 加欄位）、`templates/home.html`、`static/js/trend.js`
- Test: `tests/test_app.py`、`tests/js/trend.test.js`

**Interfaces:**
- Consumes: 快照 `signals`、`ex`。
- Produces:
  - `/api/companies` 每列加 `"signals": [...]` 與 `"ex_today": str|null`（快照 `ex[sid][1]`，即今日除權息種類）；快照讀取失敗時這兩欄為 `[]`／null，其餘照舊（不可因此 503）。
  - `trend.js`：`alertsFor(company, threshold: number) -> string[]`：`|latest_change| ≥ threshold` →「大漲 +x.xx%」或「大跌 -x.xx%」；每個訊號的 label；`ex_today` 有值 →「今日除權息」。latest_change 為 null 不觸發。
  - `THRESHOLD_KEY = "stockchain.alertThreshold"`，預設 5；讀寫用 `Format.safeStorage`（try/catch，讀不到用預設）；首頁自選股標題旁一個小輸入框（1–20，步進 0.5）。有提醒的自選股列顯示 glass 小標籤。

- [ ] **Step 1: Write the failing tests**

```js
test("alerts: threshold, signals, ex today; null change ignored", () => {
  const c = { latest_change: -6.2, signals: [{ label: "爆量" }], ex_today: "息" };
  assert.deepStrictEqual(T.alertsFor(c, 5), ["大跌 -6.20%", "爆量", "今日除權息"]);
  assert.deepStrictEqual(T.alertsFor({ latest_change: null, signals: [], ex_today: null }, 5), []);
  assert.deepStrictEqual(T.alertsFor({ latest_change: 4.99, signals: [], ex_today: null }, 5), []);
});
```

`tests/test_app.py`：`test_companies_include_signals_and_ex_today`、`test_companies_still_ok_when_snapshot_fails`。

- [ ] **Step 2–4:** FAIL → 實作 → 全部測試 PASS；重啟網站，用 curl 確認 `/api/companies?ids=2330` 含 `signals`、`ex_today`。自選股存在使用者瀏覽器的 localStorage，headless 截圖看不到，報告中註明此項請使用者目視確認。
- [ ] **Step 5: Commit** `feat(ui): 自選股提醒標記與門檻設定`

---

## 部署備註（不是 Task，給執行者與使用者）

- Task 1 完成後請使用者把 `db/006_industry_index.sql` 貼到 Supabase SQL Editor 執行，回覆「好了」後再驗證 Task 2 之後的實際資料。
- 之後使用者執行一次 `.venv\Scripts\python.exe run_sync.py`（或等 16:00 排程），第一次會建立指數並開始補抓一年。
- 不 push、不改 main，除非使用者要求。
