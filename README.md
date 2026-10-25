# 台股產業鏈分析

Flask + Supabase + D3 的台灣科技產業鏈地圖（個人使用）：資料管線每日同步股價、法人、除權息與月營收，網站只綁 127.0.0.1 顯示。

## 安裝
1. 建立虛擬環境：`python -m venv .venv`
2. `.venv\Scripts\python.exe -m pip install -r requirements-dev.txt`
3. 複製 `.env.example` 為 `.env` 並填入 Supabase 金鑰（`APP_PORT` 預設 8765，不可用 5000）。
4. 在 Supabase SQL Editor 依序執行 `db/001_pipeline.sql`、`db/002_ex_date_changes.sql`。

## 使用
- 同步資料：`.venv\Scripts\python.exe run_sync.py`
- 稽核股票代號：`.venv\Scripts\python.exe audit_stock_ids.py`
- 註冊排程（網站登入時啟動、每天 16:00 同步）：`powershell -ExecutionPolicy Bypass -File scripts\install_tasks.ps1`
- 重啟網站：`scripts\restart_web.ps1`
- 網站：http://127.0.0.1:8765/
- 測試：`.venv\Scripts\python.exe -m pytest -q`

## 紀錄
`logs/`（`web.log`、`sync.log`，保留 30 天），不進 git。
