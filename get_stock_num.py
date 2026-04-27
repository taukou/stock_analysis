import os
from dotenv import load_dotenv
from FinMind.data import DataLoader
from database import supabase

load_dotenv()

def debug_update():
    dl = DataLoader()
    print("📡 正在從 FinMind 抓取全台股對照表...")
    stock_info = dl.taiwan_stock_info()
    print(f"✅ 抓取成功！對照表內共有 {len(stock_info)} 筆資料")

    print("🔍 正在從 Supabase 抓取你的公司清單...")
    res = supabase.table("companies").select("company_name").execute()
    
    if not res.data:
        print("❌ 錯誤：Supabase 傳回空資料！請檢查資料表名稱是否為 'companies'")
        return

    print(f"📋 預計對齊 {len(res.data)} 家公司...")

    success_count = 0
    fail_count = 0

    for item in res.data:
        name = item['company_name']
        # 1. 精確匹配
        match = stock_info[stock_info['stock_name'] == name]
        
        if not match.empty:
            sid = match.iloc[0]['stock_id']
            # 更新 Supabase
            supabase.table("companies").update({"stock_id": sid}).eq("company_name", name).execute()
            print(f"  [OK] {name} -> {sid}")
            success_count += 1
        else:
            # 2. 模糊匹配 (試試看有沒有包含字眼)
            fuzzy = stock_info[stock_info['stock_name'].str.contains(name)]
            if not fuzzy.empty:
                sid = fuzzy.iloc[0]['stock_id']
                supabase.table("companies").update({"stock_id": sid}).eq("company_name", name).execute()
                print(f"  [!] 模糊匹配: {name} -> {sid}")
                success_count += 1
            else:
                print(f"  [FAIL] 找不到公司: {name}")
                fail_count += 1

    print("-" * 30)
    print(f"📊 執行結果：成功 {success_count} 家，失敗 {fail_count} 家")

if __name__ == "__main__":
    debug_update()