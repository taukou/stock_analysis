# 資料地基（階段 0＋1）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 資料每天自動、完整（上市＋上櫃＋興櫃）進入 Supabase，網站登入即在背景啟動；金鑰不再在 git 中。

**Architecture:** 新增 `sync/` 套件：`sources/` 只負責「抓＋解析」成 dataclass（純函式解析，用錄製的樣本測試），`store.py` 是唯一碰 Supabase 寫入的地方，`jobs.py` 決定要補哪些日期／月份並串起兩者。`run_sync.py` 是唯一入口，Windows 工作排程器呼叫它；之後搬 GitHub Actions 只需呼叫同一指令。網站改由 `serve.py`（waitress）啟動。

**Tech Stack:** Python 3.13（`.venv`）、Flask 3.1、supabase-py 2.29、requests、waitress、pytest；PostgreSQL（Supabase）；Windows 工作排程器（PowerShell `Register-ScheduledTask`）。

**Spec:** `docs/superpowers/specs/2026-10-25-data-pipeline-and-trends-design.md`（本計畫涵蓋 §6 階段 0、階段 1、網站自動啟動；階段 2 趨勢呈現另立計畫）

## Global Constraints

- 缺值一律存 `NULL`／Python `None`，絕不以 0 代替。
- 股票代號只接受精確比對；不自動改 `companies` 的代號。
- 金鑰只放 `.env`（不進 git）；Flask 用匿名 key `SUPABASE_KEY`（只讀），同步用 `SUPABASE_SERVICE_KEY`，service key 絕不送到瀏覽器。
- 網站只綁 `127.0.0.1`，埠號讀 `.env` 的 `APP_PORT`，預設 `8765`，**不得使用 5000**；埠被佔用時寫紀錄並以非零碼結束，不改用其他埠。
- 不自動打開瀏覽器。
- 回填範圍：股價與法人 ≥ 60 個交易日（以 95 個日曆天實作），月營收 ≥ 13 個月。
- 紀錄寫 `logs/`，保留 30 天；`logs/`、`reports/` 加入 `.gitignore`。
- 對證交所／櫃買／公開資訊觀測站請求間隔 ≥ 3 秒，帶 `User-Agent: Mozilla/5.0`。
- 不改寫 git 歷史。
- 每個 task 結束時 `.venv/Scripts/python.exe -m pytest -q` 全綠。

## 已實測的資料來源（2026-10-25，最新交易日 2026-10-22）

| 用途 | URL | 解析重點 |
|---|---|---|
| 上市日行情 | `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999&response=json` | `tables[]` 中 `fields` 長度 16 且首欄為「證券代號」的那張；欄 0 代號、1 名稱、2 成交股數、5 開、6 高、7 低、8 收、9 漲跌符號（HTML，含 `+`/`-`，或 `X`/空白）、10 漲跌價差（絕對值）。休市回 `{"stat":"很抱歉，沒有符合條件的資料!"}` |
| 上市三大法人 | `https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD&selectType=ALL&response=json` | `data[]`；欄 0 代號、4 外陸資買賣超(不含外資自營商)、10 投信買賣超、11 自營商買賣超、18 三大法人合計（單位：股） |
| 上市除權息 | `https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=YYYYMMDD&endDate=YYYYMMDD&response=json` | `data[]`；欄 0 日期 `115年07月01日`、1 代號、3 除權息前收盤、4 參考價、5 權值+息值、6 `權`/`息`/`權息` |
| 上櫃日行情 | `https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=YYYY/MM/DD&response=json` | `tables[0].data`；欄 0 代號、1 名稱、2 收、3 漲跌（帶正負號字串）、4 開、5 高、6 低、8 成交股數。休市時 `data` 為空 |
| 上櫃三大法人 | `https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=AL&date=YYYY/MM/DD&response=json` | `tables[0].data`；欄 0 代號、4 外資及陸資(不含外資自營商)買賣超、13 投信買賣超、22 自營商合計買賣超、23 三大法人合計 |
| 上櫃除權息 | `https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate=YYYY/MM/DD&endDate=YYYY/MM/DD&response=json` | `tables[0].data`；欄 0 日期 `115/07/01`、1 代號、3 前收盤、4 參考價、7 權值+息值、8 `除權`/`除息`/`除權息` |
| 興櫃當日行情 | `https://www.tpex.org.tw/openapi/v1/tpex_esb_latest_statistics` | JSON 陣列；`Date`(`1151022`)、`SecuritiesCompanyCode`、`CompanyName`、`LatestPrice`、`PreviousAveragePrice`、`TransactionVolume`、`Highest`、`Lowest`。**只有最新一日，無歷史** |
| 月營收（上市／上櫃／興櫃） | `https://mopsov.twse.com.tw/nas/t21/{sii|otc|rotc}/t21sc03_{民國年}_{月}_0.html` | cp950 編碼 HTML；每列 `<td>`：代號、名稱、當月營收、上月營收、去年當月、上月比較增減(%)、去年同月增減(%)、當月累計、去年累計、前期比較增減(%)、備註。單位千元。未公布月份回 404 或無資料列 |

**實作者在 Task 2–4 先用上述 URL（日期 2026-10-22／除權息 2026-07-01~07-31／營收 115 年 9 月）抓真實回應，裁成每份 3–5 列（務必含 `2330` 或一筆上櫃大型股、一筆 `--` 無成交列若有）存到 `tests/fixtures/`，再寫解析。**

## 決定（本計畫層級，規格未指定）

- 不再使用 FinMind：上述來源已涵蓋所有歷史需求。移除 `finmind`、`pandas`、`plotly`、`networkx`。
- 日漲跌幅 = 漲跌價差 ÷ (收盤 − 漲跌價差) × 100。交易所的漲跌價差在除權息日即相對參考價計算，因此日漲跌已是「還原」報酬；區間報酬（階段 2）以日報酬連乘即可，不另存還原股價。
- 新表 `daily_quotes` 取代 `stock_history`（舊表 2026-04~05 的 777 筆在回填範圍外；不刪除，交由使用者日後決定）。
- `growth_momentum.data_month` 維持民國 `115/09` 格式，避免破壞既有前端。
- 興櫃只能每日累積（無歷史 API），且交易所不公布興櫃法人資料 → 興櫃公司法人欄位永遠「無資料」。
- 只抓平日；休市日由「回應無資料」自然略過。
- `companies.latest_price/latest_change` 由 SQL 函式 `refresh_company_latest()` 從 `daily_quotes` 一次更新。

## Review Focus

1. **補跑區間內遇到颱風假／國定假日**：該日回應無資料 → 該日略過、工作仍為成功，不寫入任何列。（Task 7 `test_sync_quotes_skips_holiday`）
2. **早上登入觸發同步（資料未公布）**：15:00 前不抓當日；15:00 後抓到空資料也不算失敗，下次再補。（Task 7 `test_dates_to_fetch_excludes_today_before_15`、`test_sync_quotes_skips_holiday`）
3. **交易所回 HTML 錯誤頁／被限流**：該資料集記為失敗、其他資料集照跑、`run_sync` 結束碼 1、`sync_runs` 有紀錄。（Task 5 `test_get_json_raises_on_html`、Task 9 `test_run_continues_after_job_failure`）
4. **停牌或無成交（收盤 `--`）**：存 `None`，不存 0，也不算漲跌。（Task 2 `test_parse_twse_quotes_no_trade_is_none`）
5. **月營收晚報／當月未公布**：404 或缺列 → 略過；每次重抓最近 2 個月，晚報的公司下次會補上。（Task 8 `test_months_to_fetch_refetches_last_two`、`test_sync_revenue_skips_unpublished_month`）

---

### Task 0: 金鑰與資料庫結構（需使用者操作）

**Files:**
- Create: `.env.example`、`db/001_pipeline.sql`、`scripts/check_rls.py`
- Modify: `.gitignore`、`database.py:7-10`
- Remove from index: `.env`、`__pycache__/`

**Interfaces:**
- Produces: 環境變數 `SUPABASE_URL`、`SUPABASE_KEY`（匿名）、`SUPABASE_SERVICE_KEY`、`APP_PORT`；資料表 `daily_quotes`、`ex_rights`、`sync_runs`；`smart_money_flow.dealer_net`；SQL 函式 `refresh_company_latest()`。

- [ ] **Step 1: `.gitignore` 加入 `.env`、`__pycache__/`、`.venv/`、`logs/`、`reports/`；`git rm -r --cached .env __pycache__`；新增 `.env.example`（四個鍵名，值留空，`APP_PORT=8765`）**

- [ ] **Step 2: 寫 `db/001_pipeline.sql`**，內容需包含：
  - `daily_quotes(stock_id text, trade_date date, market text check in ('上市','上櫃','興櫃'), open numeric, high numeric, low numeric, close numeric, change numeric, change_pct numeric, volume bigint, updated_at timestamptz default now(), primary key(stock_id, trade_date))`，`trade_date desc` 索引。
  - `ex_rights(stock_id text, ex_date date, kind text, prev_close numeric, ref_price numeric, total_value numeric, primary key(stock_id, ex_date))`。
  - `sync_runs(id bigserial primary key, dataset text not null, status text not null check in ('ok','failed'), last_date text, rows int, message text, finished_at timestamptz default now())`。
  - `alter table smart_money_flow add column if not exists dealer_net bigint`；`smart_money_flow`、`growth_momentum` 的數值欄位 `drop not null`；確認 `(stock_id, trade_date)`、`(stock_id, data_month)` 唯一約束存在（不存在就建）。
  - `truncate smart_money_flow, growth_momentum;`（規格：既有假 0 資料全刪）。
  - `refresh_company_latest()`：`update companies c set latest_price = q.close, latest_change = q.change_pct from (select distinct on (stock_id) stock_id, close, change_pct from daily_quotes where close is not null order by stock_id, trade_date desc) q where c.stock_id = q.stock_id;` 以 `security definer` 建立。
  - RLS：對 public schema 所有表 `enable row level security`；以 `DO` 區塊刪除 `pg_policies` 中 schemaname='public' 且 `cmd <> 'SELECT'` 的既有政策；每張表建 `for select to anon, authenticated using (true)`。

- [ ] **Step 3: 帶使用者操作（逐步說明，等使用者回報完成）**
  1. Supabase → SQL Editor 執行 `db/001_pipeline.sql`。
  2. Supabase → Settings → API Keys：建立新的 publishable key 與 secret key，刪除舊 publishable key；新值填入本機 `.env` 的 `SUPABASE_KEY`、`SUPABASE_SERVICE_KEY`。
  3. FinMind 會員頁重設 token（之後不再使用，只為讓外洩的失效）；從 `.env` 刪除 `FINMIND_TOKEN`。

- [ ] **Step 4: 寫 `scripts/check_rls.py`**：用 `SUPABASE_KEY` 對 `sync_runs` insert 一筆，預期失敗；對 `companies` select 1 筆，預期成功；分別印 `anon write blocked: OK`、`anon read: OK`，任一不符結束碼 1。

- [ ] **Step 5: 驗證**
  Run: `.venv/Scripts/python.exe scripts/check_rls.py`
  Expected: 兩行 OK，結束碼 0。另跑 `git ls-files | grep -E "^\.env$|__pycache__"` 無輸出。

- [ ] **Step 6: Commit**（`.gitignore`、`.env.example`、`db/`、`scripts/check_rls.py`、索引移除）`chore: stop tracking secrets, add pipeline schema and RLS`

---

### Task 1: 數值與日期解析

**Files:**
- Create: `sync/__init__.py`、`sync/parse.py`、`tests/__init__.py`、`tests/test_parse.py`、`pytest.ini`（`testpaths = tests`）

**Interfaces:**
- Produces:
  - `parse_number(raw: str | None) -> int | float | None`
  - `roc_to_date(s: str) -> datetime.date`（接受 `115/10/22`、`1151022`、`115年07月01日`）
  - `date_to_roc_month(d: date) -> str`（→ `115/09`）
  - `parse_twse_sign(raw: str) -> int | None`（`+`→1、`-`→−1、`X`/空白→None）
  - `change_pct(change: float | None, close: float | None) -> float | None`（四捨五入 2 位；分母 ≤ 0 或任一 None → None）

- [ ] **Step 1: 寫失敗測試**

```python
def test_parse_number_missing_is_none():
    for raw in [None, "", "--", "—", "-", "X", "不適用", "無"]:
        assert parse_number(raw) is None

def test_parse_number_values():
    assert parse_number("29,796,590") == 29796590
    assert parse_number(" -1,231.50 ") == -1231.5
    assert parse_number("0") == 0

def test_roc_to_date_formats():
    assert roc_to_date("115/10/22") == date(2026, 10, 22)
    assert roc_to_date("1151022") == date(2026, 10, 22)
    assert roc_to_date("115年07月01日") == date(2026, 7, 1)

def test_date_to_roc_month():
    assert date_to_roc_month(date(2026, 9, 1)) == "115/09"

def test_parse_twse_sign():
    assert parse_twse_sign("<p style= color:green>-</p>") == -1
    assert parse_twse_sign("<p style ='color:red'>+</p>") == 1
    assert parse_twse_sign("X") is None and parse_twse_sign("") is None

def test_change_pct():
    assert change_pct(-35.0, 2385.0) == -1.45
    assert change_pct(None, 10.0) is None and change_pct(1.0, None) is None
```

- [ ] **Step 2: 執行確認失敗** `.venv/Scripts/python.exe -m pytest tests/test_parse.py -q` → ImportError
- [ ] **Step 3: 實作 `sync/parse.py`**（`parse_number` 先去逗號空白，再整串比對 `^-?\d+(\.\d+)?$`，不符者 None——不要沿用舊 `clean_number` 的「抓第一段數字」）
- [ ] **Step 4: 執行確認通過**
- [ ] **Step 5: Commit** `feat(sync): add number/date parsing that keeps missing values as None`

---

### Task 2: 證交所來源（上市）

**Files:**
- Create: `sync/models.py`、`sync/sources/__init__.py`、`sync/sources/twse.py`、`tests/fixtures/twse_mi_index.json`、`tests/fixtures/twse_mi_index_holiday.json`、`tests/fixtures/twse_t86.json`、`tests/fixtures/twse_twt49u.json`、`tests/test_twse.py`

**Interfaces:**
- Consumes: Task 1 全部函式。
- Produces（`sync/models.py`，皆 `@dataclass(frozen=True)`，並各有 `to_row() -> dict` 對應資料表欄位）：
  - `Quote(stock_id: str, name: str, trade_date: date, market: str, open, high, low, close, change, change_pct, volume)`（數值皆 `float|int|None`）→ `daily_quotes`
  - `InstFlow(stock_id: str, trade_date: date, foreign_net, trust_net, dealer_net, total_net)` → `smart_money_flow`
  - `ExRight(stock_id: str, ex_date: date, kind: str, prev_close, ref_price, total_value)` → `ex_rights`
  - `Revenue(stock_id: str, data_month: str, revenue, mom_pct, yoy_pct, acc_yoy_pct)` → `growth_momentum`
  - `to_row()` 把 `date` 轉 ISO 字串。
- Produces（`sync/sources/twse.py`）：`parse_quotes(payload: dict, d: date) -> list[Quote]`、`parse_institutional(payload: dict, d: date) -> list[InstFlow]`、`parse_ex_rights(payload: dict) -> list[ExRight]`；`fetch_quotes(d: date) -> list[Quote]`、`fetch_institutional(d: date) -> list[InstFlow]`、`fetch_ex_rights(start: date, end: date) -> list[ExRight]`（fetch 用 Task 5 的 `http.get_json`；Task 2 先只寫 parse，fetch 在 Task 5 補上）。

- [ ] **Step 1: 依「已實測的資料來源」抓真實回應並裁成 fixtures**（MI_INDEX 保留整個 `tables` 結構但行情表只留 3–5 列，含 2330；holiday 用 2026-10-23 的回應）
- [ ] **Step 2: 寫失敗測試**

```python
def test_parse_twse_quotes_2330():
    q = {x.stock_id: x for x in parse_quotes(load("twse_mi_index.json"), date(2026,10,22))}["2330"]
    assert (q.market, q.close, q.change, q.volume) == ("上市", 2385.0, -35.0, 29796590)
    assert q.change_pct == -1.45 and q.name == "台積電"

def test_parse_twse_quotes_no_trade_is_none():
    # fixture 內手動加一列收盤 "--"、漲跌符號 " "
    q = next(x for x in parse_quotes(load("twse_mi_index.json"), date(2026,10,22)) if x.close is None)
    assert q.change is None and q.change_pct is None

def test_parse_twse_quotes_holiday_empty():
    assert parse_quotes(load("twse_mi_index_holiday.json"), date(2026,10,23)) == []

def test_parse_twse_institutional_columns():
    f = {x.stock_id: x for x in parse_institutional(load("twse_t86.json"), date(2026,10,22))}["1101"]
    assert (f.foreign_net, f.trust_net, f.dealer_net) == (25549325, 4726000, 3083688)  # 2026-10-22 實測值
    assert f.total_net == parse_number(<fixture 中 1101 那列的欄 18>)

def test_parse_twse_ex_rights():
    e = next(x for x in parse_ex_rights(load("twse_twt49u.json")) if x.stock_id == "1101")
    assert (e.ex_date, e.kind, e.prev_close, e.ref_price, e.total_value) == (date(2026,7,1), "除息", 24.05, 23.25, 0.8)
```
  （`kind` 正規化：`息`→`除息`、`權`→`除權`、`權息`→`除權息`；代號與名稱一律 `strip()`。）
- [ ] **Step 3: 執行確認失敗**
- [ ] **Step 4: 實作 models 與 parse 函式**（行情表以「`fields[0] == '證券代號'` 且 `len(fields) == 16`」定位，不用索引位置；change = sign × 價差，sign 為 None 時 change None）
- [ ] **Step 5: 執行確認通過**
- [ ] **Step 6: Commit** `feat(sync): parse TWSE quotes, institutional flow and ex-rights`

---

### Task 3: 櫃買來源（上櫃＋興櫃）

**Files:**
- Create: `sync/sources/tpex.py`、`tests/fixtures/tpex_daily.json`、`tests/fixtures/tpex_daily_holiday.json`、`tests/fixtures/tpex_insti.json`、`tests/fixtures/tpex_ex.json`、`tests/fixtures/tpex_esb.json`、`tests/test_tpex.py`

**Interfaces:**
- Consumes: Task 1、Task 2 的 models。
- Produces：`parse_quotes(payload, d) -> list[Quote]`（market=`上櫃`）、`parse_institutional(payload, d) -> list[InstFlow]`（欄 4/13/22/23）、`parse_ex_rights(payload) -> list[ExRight]`、`parse_emerging(payload: list) -> list[Quote]`（market=`興櫃`，trade_date 取 `Date`，close=`LatestPrice`，change=`LatestPrice − PreviousAveragePrice`，change_pct 以 `PreviousAveragePrice` 為分母，open=None，volume=`TransactionVolume`）；對應 `fetch_*`（日期參數格式 `YYYY/MM/DD`）與 `fetch_emerging() -> list[Quote]`。

- [ ] **Step 1: 抓真實回應裁成 fixtures**（2026-10-22；holiday 用 2026-10-23；除權息 2026-07-01~07-31；興櫃留 3 筆）
- [ ] **Step 2: 寫失敗測試**：
  - `test_parse_tpex_quotes`：一筆已知代號的 close/change/volume 與 fixture 相符、market 為 `上櫃`、change 解析 `"-0.11 "` 為 −0.11。
  - `test_parse_tpex_quotes_holiday_empty` → `[]`。
  - `test_parse_tpex_institutional_columns`：用 fixture 中一筆，斷言 foreign_net=欄4、trust_net=欄13、dealer_net=欄22、total_net=欄23 的數值。
  - `test_parse_tpex_ex_rights`：`2230` → `(date(2026,7,1), "除息", 25.55, 24.94, 0.608951)`。
  - `test_parse_emerging`：`1260` → market `興櫃`、trade_date `date(2026,10,22)`、close 32.0、change 0.33、change_pct 1.04。
- [ ] **Step 3: 執行確認失敗**
- [ ] **Step 4: 實作**（ex 的 kind 已是 `除權`/`除息`/`除權息`，僅 strip）
- [ ] **Step 5: 執行確認通過**
- [ ] **Step 6: Commit** `feat(sync): parse TPEx quotes, institutional flow, ex-rights and emerging`

---

### Task 4: 公開資訊觀測站月營收

**Files:**
- Create: `sync/sources/mops.py`、`tests/fixtures/mops_sii_115_9.html`（保留表頭與 3 列，cp950 原始位元組）、`tests/test_mops.py`

**Interfaces:**
- Consumes: Task 1、Task 2 的 `Revenue`。
- Produces：`parse_revenue(html: str, roc_year: int, month: int) -> list[Revenue]`、`fetch_revenue(roc_year: int, month: int, market: Literal["sii","otc","rotc"]) -> list[Revenue]`（404 → `[]`）。

- [ ] **Step 1: 抓 `sii/t21sc03_115_9_0.html` 裁成 fixture**
- [ ] **Step 2: 寫失敗測試**

```python
def test_parse_revenue_2330():
    html = FIXTURES.joinpath("mops_sii_115_9.html").read_bytes().decode("cp950")
    r = {x.stock_id: x for x in parse_revenue(html, 115, 9)}["2330"]
    assert (r.data_month, r.revenue, r.mom_pct, r.yoy_pct, r.acc_yoy_pct) == ("115/09", 511857399, -0.57, 54.64, 41.10)

def test_parse_revenue_ignores_header_and_total_rows():
    assert all(x.stock_id.isdigit() for x in parse_revenue(html, 115, 9))
```
- [ ] **Step 3: 執行確認失敗**
- [ ] **Step 4: 實作**（標準庫 `html.parser` 或 regex 抓 `<tr>` 內 `<td>`；代號欄需 4–6 碼數字才收；欄位對應：2 當月、5 上月比較%、6 去年同月%、9 前期比較%）
- [ ] **Step 5: 執行確認通過**
- [ ] **Step 6: Commit** `feat(sync): parse MOPS monthly revenue for all markets`

---

### Task 5: HTTP 用戶端（節流＋重試）並接上 fetch

**Files:**
- Create: `sync/http.py`、`tests/test_http.py`
- Modify: `sync/sources/twse.py`、`sync/sources/tpex.py`、`sync/sources/mops.py`（補 `fetch_*`）

**Interfaces:**
- Produces：`class SourceError(Exception)`；`get_json(url: str) -> Any`、`get_text(url: str, encoding: str) -> str | None`（404 回 None）；模組層 `MIN_INTERVAL = 3.0`、`RETRIES = 3`；內部 `_session: requests.Session`（測試可 monkeypatch）。

- [ ] **Step 1: 寫失敗測試**（以 monkeypatch 假的 session.get 與 `time.sleep`）
  - `test_get_json_raises_on_html`：回應 200 但內容 `<html>…` → 重試 3 次後 `SourceError`。
  - `test_get_json_retries_then_succeeds`：前兩次 503、第三次 200 JSON → 回傳 dict。
  - `test_requests_are_spaced`：連續兩次呼叫，第二次前 `sleep` 被呼叫且參數 ≥ 剩餘間隔。
  - `test_get_text_404_returns_none`。
- [ ] **Step 2: 執行確認失敗**
- [ ] **Step 3: 實作**（timeout 30 秒；退避 5、15、45 秒；header `User-Agent: Mozilla/5.0`）
- [ ] **Step 4: 執行確認通過**
- [ ] **Step 5: 手動煙霧測試** `.venv/Scripts/python.exe -c "from datetime import date; from sync.sources import twse, tpex; print(len(twse.fetch_quotes(date(2026,10,22))), len(tpex.fetch_quotes(date(2026,10,22))))"` → 兩個數字皆 > 800
- [ ] **Step 6: Commit** `feat(sync): add throttled HTTP client and wire up fetchers`

---

### Task 6: 資料庫寫入層

**Files:**
- Create: `sync/store.py`、`tests/fakes.py`、`tests/test_store.py`

**Interfaces:**
- Produces：
  - `class Store`：`__init__(client)`；`last_value(table: str, column: str) -> str | None`（該欄最大值）；`upsert(table: str, rows: list[dict], on_conflict: str) -> int`（每批 500，回傳列數，空清單不呼叫 API）；`refresh_company_latest() -> None`（`client.rpc("refresh_company_latest")`）；`record_run(result: "JobResult") -> None`（寫 `sync_runs`）；`tracked_companies() -> list[dict]`（`companies` 的 `stock_id, company_name, market_type`）。
  - `make_store() -> Store`：用 `SUPABASE_URL`＋`SUPABASE_SERVICE_KEY` 建 client；缺值時 `RuntimeError("缺少 SUPABASE_SERVICE_KEY")`。
  - `tests/fakes.py`：`class FakeStore`（同介面，資料存在 dict，`upserts` 屬性記錄每次呼叫）——Task 7–9 共用。
- [ ] **Step 1: 寫失敗測試**：`test_upsert_batches_by_500`（1201 列 → 3 次 execute）、`test_upsert_empty_skips_api`、`test_make_store_requires_service_key`（monkeypatch 移除環境變數）。用簡單的假 client 記錄鏈式呼叫。
- [ ] **Step 2–4: 失敗 → 實作 → 通過**
- [ ] **Step 5: Commit** `feat(sync): add Supabase store with batched upserts`

---

### Task 7: 日資料工作（行情、興櫃、法人）與補跑日期

**Files:**
- Create: `sync/jobs.py`、`tests/test_jobs_daily.py`

**Interfaces:**
- Consumes: Task 2/3 `fetch_*`、Task 6 `Store`/`FakeStore`。
- Produces：
  - `@dataclass JobResult(dataset: str, status: Literal["ok","failed"], last_date: str | None, rows: int, message: str = "")`
  - `dates_to_fetch(last: date | None, now: datetime, backfill_days: int = 95, publish_hour: int = 15) -> list[date]`：從 `last+1`（或 `now.date() − backfill_days`）到今天的平日；`now.hour < publish_hour` 時不含今天。
  - `sync_quotes(store, now: datetime, fetchers=(twse.fetch_quotes, tpex.fetch_quotes)) -> JobResult`（dataset `quotes`；last 取 `daily_quotes.trade_date` 中 market 為上市的最大值——上市與上櫃同日公布，實作者可改為兩者取小）
  - `sync_emerging(store, now, fetcher=tpex.fetch_emerging) -> JobResult`（dataset `emerging`；只寫回應裡那一天）
  - `sync_institutional(store, now, fetchers=(twse.fetch_institutional, tpex.fetch_institutional)) -> JobResult`（dataset `institutional`，on_conflict `stock_id,trade_date`）
  - 每個工作：逐日抓、逐日 upsert（中途失敗時已寫入的日子保留）；任何 `SourceError`／例外 → 回傳 `status="failed"`、`message=str(e)`，不往外拋；`last_date` 為實際寫入的最後一日（無寫入則為原值）。
- [ ] **Step 1: 寫失敗測試**

```python
def test_dates_to_fetch_excludes_today_before_15():
    assert dates_to_fetch(date(2026,10,20), datetime(2026,10,22,9,0)) == [date(2026,10,21)]

def test_dates_to_fetch_includes_today_after_15_and_skips_weekend():
    assert dates_to_fetch(date(2026,10,23), datetime(2026,10,26,16,0)) == [date(2026,10,26)]

def test_dates_to_fetch_empty_table_backfills_95_days():
    ds = dates_to_fetch(None, datetime(2026,10,22,16,0))
    assert ds[0] >= date(2026,7,19) and ds[-1] == date(2026,10,22) and all(d.weekday() < 5 for d in ds)

def test_sync_quotes_skips_holiday():
    # fetchers 在 10/23 回 []、10/22 回兩筆
    r = sync_quotes(fake_store, datetime(2026,10,23,16,0), fetchers=(fake_twse, fake_tpex))
    assert r.status == "ok" and r.last_date == "2026-10-22"

def test_sync_quotes_failure_keeps_written_days():
    # 第二天 raise SourceError
    assert r.status == "failed" and r.last_date == "<第一天>" and len(fake_store.upserts) == 1
```
- [ ] **Step 2–4: 失敗 → 實作 → 通過**
- [ ] **Step 5: Commit** `feat(sync): daily jobs with gap backfill`

---

### Task 8: 除權息與月營收工作

**Files:**
- Modify: `sync/jobs.py`
- Create: `tests/test_jobs_monthly.py`

**Interfaces:**
- Produces：
  - `months_to_fetch(last: str | None, today: date, backfill_months: int = 13) -> list[tuple[int, int]]`：回傳 `(民國年, 月)`；從 `last` 往前 1 個月（即重抓最近 2 個已存月份中的較新者與 last 本身）到「今天的上個月」；`last` 為 None 時從上個月往回 13 個月。
  - `sync_revenue(store, now, fetcher=mops.fetch_revenue) -> JobResult`（dataset `revenue`；每月抓 `sii`、`otc`、`rotc`；on_conflict `stock_id,data_month`）
  - `sync_ex_rights(store, now, fetchers=(twse.fetch_ex_rights, tpex.fetch_ex_rights)) -> JobResult`（dataset `ex_rights`；區間：表空時 `today − 400 天` 起，否則 `last_ex_date − 7 天` 起，至 `today`；以每月一段請求；on_conflict `stock_id,ex_date`）
- [ ] **Step 1: 寫失敗測試**

```python
def test_months_to_fetch_refetches_last_two():
    assert months_to_fetch("115/08", date(2026,10,25)) == [(115,7),(115,8),(115,9)]

def test_months_to_fetch_empty_backfills_13():
    ms = months_to_fetch(None, date(2026,10,25))
    assert len(ms) == 13 and ms[-1] == (115,9) and ms[0] == (114,9)

def test_months_to_fetch_year_boundary():
    assert months_to_fetch("114/12", date(2026,2,5)) == [(114,11),(114,12),(115,1)]

def test_sync_revenue_skips_unpublished_month():
    # fetcher 對 (115,9) 回 [] → 仍 ok，last_date 為最後有資料的月份
```
- [ ] **Step 2–4: 失敗 → 實作 → 通過**
- [ ] **Step 5: Commit** `feat(sync): revenue and ex-rights jobs`

---

### Task 9: 單一入口 `run_sync.py`

**Files:**
- Create: `run_sync.py`、`sync/logsetup.py`、`tests/test_run_sync.py`
- Delete: `sync_stock.py`、`twse_sync.py`

**Interfaces:**
- Consumes: Task 6 `make_store`、Task 7/8 所有 `sync_*`。
- Produces：`sync/logsetup.py`：`setup_logging(name: str) -> logging.Logger`（`logs/{name}.log`，`TimedRotatingFileHandler(when="midnight", backupCount=30, encoding="utf-8")`＋主控台）；`run_sync.py`：`run(store, now: datetime, jobs: list[Callable] | None = None) -> int`（依序 quotes、emerging、institutional、ex_rights、revenue；每個結果 `store.record_run`；quotes 或 emerging 有寫入時呼叫 `refresh_company_latest()`；任一 failed 回 1，否則 0）、`main() -> int`。
- [ ] **Step 1: 寫失敗測試**：
  - `test_run_continues_after_job_failure`：第一個 job 回 failed，其餘仍被呼叫，回傳 1，`sync_runs` 有 5 筆。
  - `test_run_all_ok_returns_0_and_refreshes_latest`。
- [ ] **Step 2–4: 失敗 → 實作 → 通過**
- [ ] **Step 5: Commit** `feat: single sync entry point with logging and run records`

---

### Task 10: 股票代號稽核

**Files:**
- Create: `audit_stock_ids.py`、`tests/test_audit.py`
- Delete: `get_stock_num.py`

**Interfaces:**
- Consumes: Task 2/3 `fetch_quotes`、`fetch_emerging`；Task 6 `tracked_companies`。
- Produces：`audit(companies: list[dict], official: dict[str, tuple[str, str]]) -> list[dict]`（official：`stock_id → (名稱, 市場)`；每筆問題 `{"stock_id","db_name","official_name","db_market","official_market","issue"}`，issue ∈ `not_found`、`name_mismatch`、`market_mismatch`；名稱比對前兩邊 `strip()`）；`main()` 寫 `reports/stock_id_audit.csv`（UTF-8 BOM，Excel 可直接開）並印問題數。
- [ ] **Step 1: 寫失敗測試**：三種 issue 各一筆、完全相符者不出現。
- [ ] **Step 2–4: 失敗 → 實作 → 通過**
- [ ] **Step 5: Commit** `feat: stock id audit report replaces fuzzy matching`

---

### Task 11: 網站修正與清理

**Files:**
- Modify: `database.py`、`app.py`、`templates/industry_d3.html`、`requirements.txt`
- Delete: `templates/industry.html`、`test.py`、`check_supa_api.py`
- Create: `tests/test_app.py`

**Interfaces:**
- Produces（`database.py`）：`fetch_industry_nodes(major_id: str) -> list[dict]`（改從 `value_chain_nodes` 查 `node_id, node_name, position_type, display_order`，`eq("major_id", …)`，依 `display_order` 排序——沒有公司的節點也會出現）、`get_node_companies(node_id: str) -> list[dict]`（搬自 `app.py:50-53`）；刪除 `fetch_industry_chain`、`get_companies_by_node`。`app.py` 路由回傳結構不變，`price` 缺值回 `None`（不再回字串 `"---"`），`change` 缺值回 `None`（不再回 0）。
- [ ] **Step 1: 寫失敗測試**（monkeypatch `database` 函式，用 Flask test client）：
  - `test_industry_nodes_shape`：回傳 `id/name/group/type`，順序依 display_order。
  - `test_node_companies_missing_price_is_null`：`price` 與 `change` 為 `null`。
- [ ] **Step 2–4: 失敗 → 實作 → 通過**
- [ ] **Step 5: 前端**：`industry_d3.html` 中 price/change 為 null 時顯示 `—`（節點標籤 `:306`、側邊欄 `:176-181`、營收與法人欄位），null 不著漲跌色（用 stable）；`d3.json`／`fetch` 加 `.catch` 顯示頁面上方一條錯誤提示，請求中顯示「載入中…」。
- [ ] **Step 6: `requirements.txt`**：`flask==3.1.3`、`supabase==2.29.0`、`python-dotenv`、`requests==2.33.1`、`waitress`（鎖目前安裝版本），另建 `requirements-dev.txt`：`-r requirements.txt`、`pytest==9.0.3`。`pip install -r requirements-dev.txt`。
- [ ] **Step 7: 驗證** `pytest -q` 全綠；`python serve.py` 尚未存在，先 `python -c "import app"` 無錯。
- [ ] **Step 8: Commit** `fix: node query without !inner bug, null-safe UI, remove dead files`

---

### Task 12: 網站背景啟動與排程

**Files:**
- Create: `serve.py`、`scripts/install_tasks.ps1`、`scripts/restart_web.ps1`、`tests/test_serve.py`
- Modify: `app.py:83-84`（移除 `debug=True`，`__main__` 改呼叫 `serve.main()`）

**Interfaces:**
- Produces：`serve.py`：`port_available(port: int, host: str = "127.0.0.1") -> bool`、`get_port() -> int`（`APP_PORT`，預設 8765；值為 5000 時 `ValueError`）、`main() -> int`（紀錄 `logs/web.log`；埠被佔用 → 記錄錯誤、回 1；否則 `waitress.serve(app, host="127.0.0.1", port=port)`）。
- [ ] **Step 1: 寫失敗測試**：`test_port_available_false_when_bound`（測試內先 bind 一個 socket）、`test_get_port_default_8765`、`test_get_port_rejects_5000`、`test_main_exits_1_when_port_busy`（monkeypatch `waitress.serve` 確認未被呼叫）。
- [ ] **Step 2–4: 失敗 → 實作 → 通過**
- [ ] **Step 5: `scripts/install_tasks.ps1`**：以專案路徑註冊兩個工作（目前使用者、僅在登入時執行、不需系統管理員）：
  - `StockChain-Sync`：觸發「每天 16:00」＋「登入時（延遲 2 分鐘）」；動作 `.venv\Scripts\python.exe run_sync.py`，工作目錄為專案根；設定「錯過排程時盡快執行」（`-StartWhenAvailable`）。
  - `StockChain-Web`：觸發「登入時」；動作 `.venv\Scripts\pythonw.exe serve.py`。
  - 重複執行時先移除同名工作再建立。
  - `scripts/restart_web.ps1`：`Stop-ScheduledTask` + `Start-ScheduledTask StockChain-Web`。
- [ ] **Step 6: 驗證**：執行 `powershell -ExecutionPolicy Bypass -File scripts/install_tasks.ps1`；`Start-ScheduledTask StockChain-Web` 後 `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/` → `200`；`Get-ScheduledTask StockChain-*` 列出兩個工作。
- [ ] **Step 7: Commit** `feat: background web server on port 8765 and scheduled sync`

---

### Task 13: 首次回填與驗收

**Files:** 無新增（只執行）

- [ ] **Step 1: 執行** `.venv/Scripts/python.exe run_sync.py`（預期約 15–20 分鐘，受 3 秒間隔限制）→ 結束碼 0
- [ ] **Step 2: 驗證資料量**（用 service key 查詢，或 Supabase Table Editor）：
  - `daily_quotes` 中 `2330` 與任一上櫃追蹤公司各 ≥ 60 筆。
  - `smart_money_flow` 最新交易日的筆數 ≥ 上市＋上櫃追蹤公司數（248 家中有資料者）。
  - `growth_momentum` 有 13 個不同 `data_month`，上櫃公司有資料。
  - `companies` 中 `latest_price` 為 null 的只剩無行情者。
  - `sync_runs` 有 5 筆 ok。
- [ ] **Step 3: 立即再跑一次** `run_sync.py` → 結束碼 0，且各 `upsert` 列數只有「重抓的最近月份／當日」，不重複回填。
- [ ] **Step 4: 執行** `audit_stock_ids.py` → 把 `reports/stock_id_audit.csv` 的問題清單交給使用者確認（不自動修改）。
- [ ] **Step 5: 開瀏覽器** `http://127.0.0.1:8765/`，點進產業→節點→一家上櫃公司，側邊欄營收與法人有數字；無資料欄位顯示 `—`。
- [ ] **Step 6: 若 `stock_history` 不再被任何程式引用**，向使用者回報可刪除（不自行刪）。
