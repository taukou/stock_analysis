import os
import time
from datetime import datetime
from dotenv import load_dotenv
from FinMind.data import DataLoader
from database import supabase 

load_dotenv()
# 從環境變數讀取 Token
token = os.getenv("FINMIND_TOKEN")

# 直接在初始化時傳入 Token
# 如果 token 為 None，它會自動進入匿名模式
dl = DataLoader(token=token) 

if token:
    print("✅ 已成功載入 FinMind Token")
else:
    print("⚠️ 未偵測到 Token，將以匿名模式執行（配額較少）")

def sync_stock_data():
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 1. 抓取名單
    res = supabase.table("companies").select("stock_id, company_name").execute()
    
    # 2. 先抓取今天已經更新過的代號，避免重複浪費配額
    history_res = supabase.table("stock_history").select("stock_id").eq("trade_date", today).execute()
    updated_ids = [h['stock_id'] for h in history_res.data]

    print(f"📊 總計需監控: {len(res.data)} 家 | 今日已更新: {len(updated_ids)} 家")
    
    for item in res.data:
        sid = item['stock_id']
        name = item['company_name']
        
        # 如果今天更新過了，直接跳過
        if sid in updated_ids:
            continue
            
        try:
            # 抓取最近 5 天
            df = dl.taiwan_stock_daily(stock_id=sid, start_date='2026-04-20')
            
            if df.empty or len(df) < 2:
                continue

            latest = df.iloc[-1]
            prev = df.iloc[-2]
            price = float(latest['close'])
            change = round(((price - prev['close']) / prev['close']) * 100, 2)

            # 更新歷史與快照
            supabase.table("stock_history").upsert({
                "company_id": sid, 
                "trade_date": latest['date'],
                "close_price": price,
                "change_percent": change,
                "volume": int(latest['Trading_Volume'])
            }).execute()

            supabase.table("companies").update({
                "latest_price": price,
                "latest_change": change
            }).eq("stock_id", sid).execute()

            print(f"📈 {name}({sid}): {price} ({change}%)")
            
            # --- 關鍵防護：每抓一家多休息一下 ---
            time.sleep(1.0) # 稍微加長到 1 秒，細水長流

        except Exception as e:
            err_msg = str(e)
            if "reach the upper limit" in err_msg:
                print("🚨 觸發 API 限制！請休息一小時後再繼續。")
                return # 直接中斷，剩下的下次再說
            print(f"⚠️ {sid} 錯誤: {e}")

if __name__ == "__main__":
    sync_stock_data()