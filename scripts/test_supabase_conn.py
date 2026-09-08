import os
import urllib.request
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

print(f"Testing Supabase URL: {SUPABASE_URL}")

try:
    # Test HTTP GET directly
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/", headers={"apikey": SUPABASE_KEY})
    with urllib.request.urlopen(req, timeout=5) as response:
        print(f"HTTP Status: {response.status}")
except Exception as e:
    print(f"HTTP Connection Exception: {e}")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    res = supabase.table("patient_profiles").select("*").execute()
    print(f"Supabase Table 'patient_profiles' Query Success! Found {len(res.data)} rows:")
    for row in res.data:
        print(row)
except Exception as e:
    print(f"Supabase Client Exception: {e}")
