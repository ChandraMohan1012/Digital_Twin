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
    # Check if patient_profiles table exists by querying it
    response = supabase.table("patient_profiles").select("*").limit(1).execute()
    print("SUCCESS: Supabase connection successful! We are able to reach the patient_profiles table.")
    print(f"Data in patient_profiles: {response.data}")
except Exception as e:
    print(f"FAILED: Connection failed: {e}")
