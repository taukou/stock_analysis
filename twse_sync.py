import requests
import datetime
from supabase import create_client, Client
from dotenv import load_dotenv
import os

load_dotenv()

# 初始化 Supabase 連線
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

def get_active_stock_ids():
    """從資料庫的 companies 表中撈出所有現有的股票代號，避免抓到不必要的股票"""
    try:
        response = supabase.table("companies").select("stock_id").execute()
        return [item['stock_id'] for item in response.data]
    except Exception as e:
        print(f"❌ 撈取本地股票清單失敗: {e}")
        return []

def clean_number(val):
    """清理 API 回傳的字串，移除逗號並轉換為整數或浮點數"""
    if not val:
        return 0
    try:
        return int(val.replace(',', '').strip())
    except ValueError:
        try:
            return float(val.replace(',', '').strip())
        except ValueError:
            return 0

# --- 2. 同步三大法人買賣超 (每日 15:30 後運行) ---
def sync_smart_money_flow():
    print("🚀 開始同步今日【三大法人買賣超】...")
    api_url = "https://openapi.twse.com.tw/v1/exchangeReport/TWTB4U"
    active_stocks = get_active_stock_ids()
    
    if not active_stocks:
        print("⚠️ 找不到任何有效的 stock_id，終止同步。")
        return

    try:
        response = requests.get(api_url)
        if response.status_code != 200:
            print(f"❌ 證交所 API 連線失敗, 狀態碼: {response.status_code}")
            return
            
        data = response.json()
        today_date = datetime.date.today().isoformat()
        records_to_upsert = []

        for item in data:
            stock_id = item.get('Code', '').strip()
            
            # 只篩選出存在於你 companies 表格中的個股
            if stock_id in active_stocks:
                record = {
                    "stock_id": stock_id,
                    "trade_date": today_date,
                    "trust_net": clean_number(item.get('InvestmentTrustNetBuy')),   # 投信買賣超股數
                    "foreign_net": clean_number(item.get('ForeignInvestorNetBuy')), # 外資買賣超股數
                    "total_net": clean_number(item.get('TotalNetBuy'))              # 法人合計買賣超
                }
                records_to_upsert.append(record)

        if records_to_upsert:
            # 分批寫入 (每批 500 筆)
            for i in range(0, len(records_to_upsert), 500):
                batch = records_to_upsert[i:i+500]
                supabase.table("smart_money_flow").upsert(batch).execute()
            print(f"✅ 成功同步 {len(records_to_upsert)} 筆今日籌碼資料！")
        else:
            print("ℹ️ 今日無對應的法人交易資料。")

    except Exception as e:
        print(f"❌ 籌碼同步發生錯誤: {e}")

# --- 3. 同步每月營運動能 (每月 10 號前運行) ---
def sync_growth_momentum():
    print("🚀 開始同步【每月營收動能】...")
    api_url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    active_stocks = get_active_stock_ids()

    try:
        response = requests.get(api_url)
        if response.status_code != 200:
            print(f"❌ 證交所 API 連線失敗, 狀態碼: {response.status_code}")
            return
            
        data = response.json()
        records_to_upsert = []

        for item in data:
            stock_id = item.get('公司代號', '').strip()
            
            if stock_id in active_stocks:
                # 處理民國曆月份，例如 "11304" 轉成 "113/04" 符合你的資料庫格式
                raw_month = item.get('資料年月', '').strip()
                if len(raw_month) == 5:
                    data_month = f"{raw_month[:3]}/{raw_month[3:]}"
                else:
                    data_month = raw_month

                record = {
                    "stock_id": stock_id,
                    "data_month": data_month,
                    "revenue": clean_number(item.get('當月營收')),
                    "yoy_pct": clean_number(item.get('去年同月增減(%)')),       # YoY 營收年增率
                    "mom_pct": clean_number(item.get('上月增減(%)')),         # MoM 營收月增率
                    "acc_yoy_pct": clean_number(item.get('前期累計營收增減(%)'))  # 累計年增率
                }
                records_to_upsert.append(record)

        if records_to_upsert:
            for i in range(0, len(records_to_upsert), 500):
                batch = records_to_upsert[i:i+500]
                supabase.table("growth_momentum").upsert(batch).execute()
            print(f"✅ 成功同步 {len(records_to_upsert)} 筆營收動能資料！")
        else:
            print("ℹ️ 無對應的營收資料。")

    except Exception as e:
        print(f"❌ 營收同步發生錯誤: {e}")

# --- 4. 執行主程式 ---
if __name__ == "__main__":
    # 你可以根據時間定時執行這兩個函式
    sync_smart_money_flow()
    sync_growth_momentum()