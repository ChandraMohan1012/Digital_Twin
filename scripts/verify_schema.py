import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("Supabase credentials not found in .env")
    exit(1)

try:
    supabase: Client = create_client(url, key)
except Exception as e:
    print(f"FAILED: Could not initialize Supabase client: {e}")
    exit(1)

tables = [
    "patient_profiles",
    "twin_states",
    "sensor_events",
    "risk_history",
    "anomaly_flags",
    "alerts"
]

print("Verifying Supabase Schema...")
all_good = True

for table in tables:
    try:
        # We just try to select 0 rows to check if the table exists and is accessible
        res = supabase.table(table).select("id").limit(1).execute()
        print(f"SUCCESS: Table '{table}' exists and is accessible.")
    except Exception as e:
        print(f"FAILED: Table '{table}' check failed. Error: {e}")
        all_good = False

if all_good:
    print("\nALL TABLES FOUND! Schema execution looks complete.")
else:
    print("\nSOME TABLES ARE MISSING OR INACCESSIBLE. Please check if the SQL script ran completely.")
