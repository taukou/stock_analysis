import os
import time
from datetime import datetime
from dotenv import load_dotenv
from FinMind.data import DataLoader
from database import supabase 

# 1. 初始化設定
load_dotenv()
token = os.getenv("FINMIND_TOKEN")

# FinMind 最新版：直接在初始化時傳入 token
dl = DataLoader(token=token)

if token:
    print("✅ FinMind Token 載入成功，已啟用專業版配額")
else:
    print("⚠️ 未偵測到 Token，將使用匿名模式 (限制較多)")

def sync_stock_data():
    # 取得今天日期字串 (格式: 2026-04-29)
    today = datetime.now().strftime('%Y-%m-%d')
    
    print(f"📅 執行日期: {today}")
    print("🔍 正在讀取資料庫狀態...")

    try:
        # 2. 抓取名單 (從 companies 表抓，主鍵叫 stock_id)
        res = supabase.table("companies").select("stock_id, company_name").execute()
        
        all_companies = res.data
        print(f"📊 開始同步 {len(all_companies)} 家公司的資料...")
        print("-" * 30)

        # 3. 開始循環抓取
        for item in all_companies:
            sid = item['stock_id']
            name = item['company_name']
            
            # 如果 stock_id 還是中文，這行會擋住它
            if not str(sid).isdigit():
                print(f"⏩ 跳過 {name}: 代號仍為中文 '{sid}'，請先跑 get_stock_num.py")
                continue

            try:
                start_date = '2026-04-21'
                
                # ⚠️ 先檢查該公司是否已經有 start_date 之後的資料
                check_res = supabase.table("stock_history").select("company_id").eq("company_id", sid).gte("trade_date", start_date).execute()
                if check_res.data:
                    print(f"⏭️  跳過 {name}({sid}): 已有 {start_date} 之後的資料")
                    continue
                
                # 抓取最近 5 天資料 (為了計算今日與昨日的價差)
                # 注意：如果今天是週一，start_date 必須往前推到上週五之前
                df = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
                
                if df.empty or len(df) < 2:
                    print(f"❓ {name}({sid}): 資料不足，無法計算漲跌")
                    continue

                # 取得最新兩筆資料
                latest = df.iloc[-1]   # 最新交易日
                prev = df.iloc[-2]     # 前一交易日
                
                latest_price = float(latest['close'])
                prev_price = float(prev['close'])
                trade_date = latest['date']  # ⚠️ 從資料中取得交易日期（不是今天）
                
                # 計算漲跌幅公式
                # $$ \text{change_pct} = \frac{\text{今日} - \text{昨日}}{\text{昨日}} \times 100 $$
                change_pct = round(((latest_price - prev_price) / prev_price) * 100, 2)
                volume = int(latest['Trading_Volume'])

                # 寫入資料庫
                # A. 歷史表 (欄位對齊 ER 圖: company_id, trade_date, close_price, change_percent, volume)
                supabase.table("stock_history").upsert({
                    "company_id": sid, 
                    "trade_date": trade_date,
                    "close_price": latest_price,
                    "change_percent": change_pct,
                    "volume": volume
                }).execute()

                # B. 公司快照表 (欄位對齊 ER 圖: latest_price, latest_change)
                supabase.table("companies").update({
                    "latest_price": latest_price,
                    "latest_change": change_pct
                }).eq("stock_id", sid).execute()

                print(f"📈 {name}({sid}) [{trade_date}]: {latest_price} ({change_pct}%) | 量: {volume}")
                
                # 防禦性休息，避免觸發 API 流量限制
                time.sleep(0.8) 

            except Exception as e:
                err_text = str(e)
                if "upper limit" in err_text:
                    print("\n🚨 觸發 FinMind 流量限制！")
                    print("💡 建議：休息 1 小時後再執行，程式會自動跳過已完成的股票。")
                    return
                else:
                    print(f"❌ {name}({sid}) 發生錯誤: {e}")

    except Exception as e:
        print(f"💥 程式執行中斷: {e}")

if __name__ == "__main__":
    sync_stock_data()