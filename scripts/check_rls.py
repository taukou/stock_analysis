"""驗證匿名 key 只能讀、不能寫。"""
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
if not url or not key:
    print("缺少 SUPABASE_URL 或 SUPABASE_KEY")
    sys.exit(1)

sb = create_client(url, key)
ok = True

try:
    sb.table("sync_runs").insert({"dataset": "rls_check", "status": "ok"}).execute()
    print("anon write blocked: FAIL (insert succeeded)")
    ok = False
except Exception:
    print("anon write blocked: OK")

try:
    res = sb.table("companies").select("stock_id").limit(1).execute()
    if res.data:
        print("anon read: OK")
    else:
        print("anon read: FAIL (no rows)")
        ok = False
except Exception as e:
    print(f"anon read: FAIL ({type(e).__name__})")
    ok = False

sys.exit(0 if ok else 1)
