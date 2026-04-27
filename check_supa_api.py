# check_supabase.py
import os
from supabase import create_client
from dotenv import load_dotenv

def test_connection():
    # 1. 檢查 .env 檔案讀取
    print("--- [Step 1] 檢查 .env 讀取狀態 ---")
    if not os.path.exists(".env"):
        print("❌ 錯誤：找不到 .env 檔案！請確認檔案存在於專案根目錄。")
        return

    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        print("❌ 錯誤：.env 內找不到 SUPABASE_URL 或 SUPABASE_KEY。")
        print(f"目前讀取到的 URL: {url}")
        return
    else:
        print(f"✅ 已成功讀取環境變數 (URL 前綴: {url[:20]}...)")

    # 2. 嘗試建立 Client
    print("\n--- [Step 2] 嘗試連線至 Supabase ---")
    try:
        supabase = create_client(url, key)
        # 嘗試做一個最簡單的查詢
        response = supabase.table("major_industries").select("count", count="exact").execute()
        print("✅ 連線成功！")
        print(f"📊 目前資料庫中大產業數量: {response.count}")
    except Exception as e:
        print("❌ 連線失敗！發生以下錯誤：")
        print(str(e))

if __name__ == "__main__":
    test_connection()