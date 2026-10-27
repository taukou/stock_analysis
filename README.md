# 台股產業鏈分析

Flask + Supabase + D3 的台灣科技產業鏈地圖（個人使用）：資料管線每日同步股價、法人、除權息與月營收，網站只綁 127.0.0.1 顯示。

## 安裝
1. 建立虛擬環境：`python -m venv .venv`
2. `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`
3. 複製 `.env.example` 為 `.env` 並填入 Supabase 金鑰（`APP_PORT` 預設 8765，不可用 5000）。
4. 在 Supabase SQL Editor 依序執行 `db/001_pipeline.sql`、`db/002_ex_date_changes.sql`、`db/003_drop_company_fks.sql`（003 移除外鍵，全市場的法人／營收資料才存得進去）。

## 使用
- 同步資料：`.venv\Scripts\python.exe run_sync.py`
- 稽核股票代號：`.venv\Scripts\python.exe audit_stock_ids.py`
- 註冊排程（網站登入時啟動、每天 16:00 同步）：雙擊 `scripts\install_tasks.cmd`（或 `powershell -ExecutionPolicy Bypass -File scripts\install_tasks.ps1`）
- 重啟網站：雙擊 `scripts\restart_web.cmd`（會確認埠號有在監聽並顯示 OK／FAIL）
- 網站：http://127.0.0.1:8765/
- 測試：`.venv\Scripts\python.exe -m pytest -q`

## 更新產業與公司清單
產業節點與各節點公司取自櫃買中心「產業價值鏈資訊平台」(https://ic.tpex.org.tw)。要抓的產業列在 `build_chain_sql.py` 的 `INDUSTRIES`。

1. `.venv\Scripts\python.exe build_chain_sql.py`：抓平台資料、以交易所最新行情核對代號，產生 `db/004_tpex_chains.sql`，摘要寫在 `reports/chain_import.txt`
2. 把 SQL 整份貼到 Supabase SQL Editor 執行

SQL 只新增／更新、不刪除（手動維護的供應關係線會保留），可重複執行。新節點代號格式為 `M05U01`（大產業＋上中下游 U/M/D＋序號）。

## 維護供應關係線
總覽畫面節點間的箭頭線來自 `industry_links` 表，內容由你自己維護。在 Supabase SQL Editor 執行，例如新增 N101 → N201：

```sql
insert into industry_links (from_node_id, to_node_id) values ('N101', 'N201');
```

刪除則用 `delete from industry_links where from_node_id = 'N101' and to_node_id = 'N201';`。重新整理頁面即生效。

## 產業指數
各產業／階層／節點與大盤的等權指數（只算上市、上櫃）。

1. 先在 Supabase SQL Editor 執行 `db/006_industry_index.sql`。
2. `run_sync.py` 每日自動更新指數，並從最早的指數日往前補抓交易所行情，直到滿一年（第一次約 20–40 分鐘，可中斷，下次接續）。
3. 成分股（節點公司）變動後要重算：`.venv\Scripts\python.exe rebuild_index.py`（從一年前以 100 起算，全部算完才開始寫入；抓取失敗不寫任何列，寫入中斷則重跑一次即可修復）。
   新增節點後也請執行重算：補抓後才新增的範圍，歷史只有資料庫最早報價日起，重算後才會有完整一年。

## 紀錄
`logs/`（`web.log`、`sync.log`，保留 30 天），不進 git。
