import os
import requests
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

API_URL = "http://127.0.0.1:8000/ingest"

# Get the sample patient ID
patient_res = supabase.table("patient_profiles").select("id").limit(1).execute()
if not patient_res.data:
    print("No patient found.")
    exit(1)

patient_id = patient_res.data[0]['id']

payload = {
    "patient_id": patient_id,
    "hr": 85.5,
    "spo2": 98.2,
    "temp": 36.6,
    "bp_sys": 120,
    "bp_dia": 80
}

print(f"Sending payload to {API_URL} ...\n")
try:
    response = requests.post(API_URL, json=payload)
    print(f"Status Code: {response.status_code}")
    print("Response JSON:")
    print(response.json())
except Exception as e:
    print(f"FAILED: Could not connect to API: {e}")
