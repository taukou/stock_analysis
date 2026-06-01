import requests
import datetime
from datetime import timedelta
import re
import os
from supabase import create_client, Client
from dotenv import load_dotenv

# 讀取 .env 檔案中的環境變數
load_dotenv()

# 初始化 Supabase 連線
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise ValueError("❌ 錯誤：請確認你的 .env 檔案中包含 SUPABASE_URL 與 SUPABASE_KEY")

supabase: Client = create_client(url, key)

def get_active_stock_ids():
    """從資料庫的 companies 表中撈出所有現有的股票代號，精準過濾目標"""
    try:
        response = supabase.table("companies").select("stock_id").execute()
        return [item['stock_id'] for item in response.data]
    except Exception as e:
        print(f"❌ 撈取本地股票清單失敗: {e}")
        return []

def clean_number(val):
    """清理 API 回傳的字串，移除千分位逗號並轉換為整數或浮點數，支持負數與浮點數"""
    if val is None:
        return 0
    s = str(val).strip().replace(',', '') # 拔掉千分位逗號
    if s == '' or s in ['—', '--', '-', '無', '不適用']:
        return 0
    
    # 使用正規表達式抽取數字、小數點和負號
    match = re.search(r"[-0-9.]+", s)
    if not match:
        return 0
    
    s_clean = match.group(0)
    try:
        if '.' in s_clean:
            return float(s_clean)
        return int(s_clean)
    except ValueError:
        return 0

# --- 2. 同步三大法人買賣超 (具備智慧回溯交易日機制) ---
def sync_smart_money_flow(days_ago=0):
    """
    同步三大法人買賣超資料
    :param days_ago: 想要回溯的天數，0 代表今天。
    """
    print(f"🚀 開始同步【三大法人買賣超】...")
    
    active_stocks = get_active_stock_ids()
    if not active_stocks:
        print("⚠️ 找不到任何有效的 stock_id，終止同步。")
        return

    # 計算目標日期
    target_date = datetime.date.today() - timedelta(days=days_ago)
    
    # 智慧判定：如果是查今天(0)且目前時間還沒到下午 15:00（盤後資料未產出），自動先往前推一天
    current_hour = datetime.datetime.now().hour
    if days_ago == 0 and current_hour < 15:
        print("⏰ 目前尚未過下午 15:00，今日盤後資料尚未公告，自動切換至前一天開始查詢...")
        target_date = target_date - timedelta(days=1)

    max_attempts = 7  # 防止假日時陷入死循環
    attempts = 0
    raw_data = None
    iso_date = ""

    while attempts < max_attempts:
        date_str = target_date.strftime("%Y%m%d")
        iso_date = target_date.isoformat()
        print(f"🔍 嘗試抓取日期: {iso_date} 的籌碼資料...")
        
        api_url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&selectType=ALL&response=json"
        
        try:
            response = requests.get(api_url)
            if response.status_code == 200:
                res_json = response.json()
                if "data" in res_json:
                    raw_data = res_json
                    print(f"🎉 成功找到 {iso_date} (真實交易日) 的有效法人資料！")
                    break
            
            print(f"ℹ️ {iso_date} 查無資料（休市或資料未產出），嘗試再往前推一天...")
            target_date = target_date - timedelta(days=1)
            attempts += 1
            
        except Exception as e:
            print(f"❌ 連線證交所伺服器發生錯誤: {e}")
            return

    if not raw_data:
        print("❌ 錯誤：無法取得任何法人交易日資料，終止籌碼同步。")
        return

    try:
        records_to_upsert = []
        for row in raw_data["data"]:
            stock_id = row[0].strip()
            
            if stock_id in active_stocks:
                foreign_net = clean_number(row[4])   # 外陸資買賣超股數
                trust_net = clean_number(row[10])   # 投信買賣超股數
                dealer_net = clean_number(row[11])   # 自營商買賣超股數
                total_net = foreign_net + trust_net + dealer_net # 三大法人合計

                record = {
                    "stock_id": stock_id,
                    "trade_date": iso_date,
                    "trust_net": trust_net,
                    "foreign_net": foreign_net,
                    "total_net": total_net
                }
                records_to_upsert.append(record)

        if records_to_upsert:
            for i in range(0, len(records_to_upsert), 500):
                batch = records_to_upsert[i:i+500]
                supabase.table("smart_money_flow").upsert(
                    batch, 
                    on_conflict="stock_id, trade_date"
                ).execute()
            print(f"✅ 成功同步 {len(records_to_upsert)} 筆【{iso_date}】的籌碼資料！")
        else:
            print(f"ℹ️ 【{iso_date}】的交易資料中，沒有包含你 companies 表格內的目標個股。")

    except Exception as e:
        print(f"❌ 籌碼寫入資料庫失敗: {e}")


# --- 3. 同步每月營運動能 (對齊證交所真實實測欄位版) ---
def sync_growth_momentum():
    print("🚀 開始同步【每月營收動能】...")
    api_url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    active_stocks = get_active_stock_ids()

    if not active_stocks:
        print("⚠️ 找不到任何有效的 stock_id，終止同步。")
        return

    try:
        response = requests.get(api_url)
        if response.status_code != 200:
            print(f"❌ 證交所營收 API 連線失敗, 狀態碼: {response.status_code}")
            return
            
        data = response.json()
        records_to_upsert = []

        for item in data:
            stock_id = item.get('公司代號', '').strip()
            
            if stock_id in active_stocks:
                # 處理民國曆月份，將 "11504" 格式化為 "115/04"
                raw_month = item.get('資料年月', '').strip()
                if len(raw_month) == 5:
                    data_month = f"{raw_month[:3]}/{raw_month[3:]}"
                else:
                    data_month = raw_month

                # 💡 依據實際攔截到的 JSON 結構，精確映射帶有前綴的欄位名稱
                record = {
                    "stock_id": stock_id,
                    "data_month": data_month,
                    "revenue": clean_number(item.get('營業收入-當月營收')),
                    "yoy_pct": clean_number(item.get('營業收入-去年同月增減(%)')),       # YoY 年增率
                    "mom_pct": clean_number(item.get('營業收入-上月比較增減(%)')),       # MoM 月增率
                    "acc_yoy_pct": clean_number(item.get('累計營業收入-前期比較增減(%)'))  # 累計年增率
                }
                records_to_upsert.append(record)

        if records_to_upsert:
            for i in range(0, len(records_to_upsert), 500):
                batch = records_to_upsert[i:i+500]
                supabase.table("growth_momentum").upsert(
                    batch, 
                    on_conflict="stock_id, data_month"
                ).execute()
            print(f"✅ 成功同步 {len(records_to_upsert)} 筆營收動能歷史資料！")
        else:
            print("ℹ️ 本次未發現對應的營收資料。")

    except Exception as e:
        print(f"❌ 營收同步發生錯誤: {e}")

# --- 4. 程式執行入口 ---
if __name__ == "__main__":
    # 自動判定。若在放假日或下午 15:00 盤前，會智慧回溯至上一個有真實交易數據的開盤日
    sync_smart_money_flow(days_ago=0)
    
    # 同步營收歷史資料
    sync_growth_momentum()