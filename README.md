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

## 維護供應關係線
總覽畫面節點間的箭頭線來自 `industry_links` 表，內容由你自己維護。在 Supabase SQL Editor 執行，例如新增 N101 → N201：

```sql
insert into industry_links (from_node_id, to_node_id) values ('N101', 'N201');
```

刪除則用 `delete from industry_links where from_node_id = 'N101' and to_node_id = 'N201';`。重新整理頁面即生效。

## 紀錄
`logs/`（`web.log`、`sync.log`，保留 30 天），不進 git。
