import os
import time
from datetime import datetime
from dotenv import load_dotenv
from FinMind.data import DataLoader
from database import supabase 

# 1. 初始化與環境設定
load_dotenv()
token = os.getenv("FINMIND_TOKEN")

# FinMind 最新版：初始化時直接傳入 token
dl = DataLoader(token=token)

if token:
    print("✅ FinMind Token 載入成功，已啟用專業版配額")
else:
    print("⚠️ 未偵測到 Token，將使用匿名模式 (限制較多)")

def sync_stock_data():
    # 取得今天日期 (格式: 2026-04-29)
    today = datetime.now().strftime('%Y-%m-%d')
    print(f"📅 執行日期: {today} | 啟動雙重檢查機制")
    print("-" * 40)

    try:
        # 2. 從 companies 表讀取名單 (這裡欄位叫 stock_id)
        res = supabase.table("companies").select("stock_id, company_name").execute()
        
        if not res.data:
            print("❌ 資料庫中找不到任何公司名單，請確認 companies 表已有資料。")
            return

        all_companies = res.data
        print(f"📋 預計檢查: {len(all_companies)} 家公司")

        # 3. 開始逐一檢查與更新
        for item in all_companies:
            sid = item['stock_id']
            name = item['company_name']
            
            # 安全檢查：確保代號是數字
            if not str(sid).isdigit():
                print(f"⏩ 跳過 {name}: 代號仍為中文 '{sid}'，請先跑 get_stock_num.py")
                continue

            # --- 第一重檢查：資料庫是否已經存過今天的資料了？ ---
            # 根據你的 ER 圖，stock_history 關聯欄位叫 company_id
            check_db = supabase.table("stock_history") \
                .select("id") \
                .eq("company_id", sid) \
                .eq("trade_date", today) \
                .execute()

            if check_db.data:
                print(f"😴 已跳過 {name}({sid}): 資料庫已有今日紀錄，無需重複抓取。")
                continue

            # --- 第二重：資料庫沒資料，才去 FinMind 抓取 ---
            print(f"📡 搜尋中 {name}({sid})...")
            try:
                # 抓取最近 5 天資料 (為了計算漲跌幅)
                df = dl.taiwan_stock_daily(stock_id=sid, start_date='2026-04-20')
                
                if df.empty or len(df) < 2:
                    print(f"   ⚠️ 無法抓取資料或資料不足兩筆。")
                    continue

                latest = df.iloc[-1]   # 今日
                prev = df.iloc[-2]     # 昨日
                
                latest_price = float(latest['close'])
                prev_price = float(prev['close'])
                change_pct = round(((latest_price - prev_price) / prev_price) * 100, 2)
                volume = int(latest['Trading_Volume'])

                # 4. 執行寫入
                # A. 歷史表 (使用 upsert 並指定衝突處理作為雙重保險)
                supabase.table("stock_history").upsert({
                    "company_id": sid, 
                    "trade_date": latest['date'],
                    "close_price": latest_price,
                    "change_percent": change_pct,
                    "volume": volume
                }, on_conflict="company_id, trade_date").execute()

                # B. 公司快照表 (更新前端顯示用的欄位)
                supabase.table("companies").update({
                    "latest_price": latest_price,
                    "latest_change": change_pct
                }).eq("stock_id", sid).execute()

                print(f"   ✅ 更新成功: {latest_price} ({change_pct}%) | 交易量: {volume}")
                
                # 防禦性休息，避免被 API 封鎖
                time.sleep(0.8) 

            except Exception as e:
                err_msg = str(e)
                if "upper limit" in err_msg:
                    print("\n🚨 觸發 FinMind 流量限制！")
                    print("💡 建議：休息一小時後再執行，程式會自動跳過已完成的部分。")
                    return
                print(f"   ❌ {name}({sid}) 錯誤: {e}")

        print("-" * 40)
        print("✨ 任務完成！所有資料均已與資料庫同步。")

    except Exception as e:
        print(f"💥 程式執行中斷: {e}")

if __name__ == "__main__":
    sync_stock_data()