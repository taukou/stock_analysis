import requests

def debug_revenue_api():
    print("🔍 正在攔截證交所營收 API 的真實欄位結構...")
    api_url = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    
    try:
        response = requests.get(api_url)
        data = response.json()
        
        if isinstance(data, list) and len(data) > 0:
            print("\n💡 【找到資料了！】第一筆資料的完整外觀如下：")
            import json
            print(json.dumps(data[0], ensure_ascii=False, indent=2))
        else:
            print("⚠️ API 回傳格式不是預期的陣列，或裡面沒有資料。")
            
    except Exception as e:
        print(f"❌ 連線失敗: {e}")

if __name__ == "__main__":
    debug_revenue_api()