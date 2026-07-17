import os
import random
import time
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("Supabase credentials not found in .env")
    exit(1)

supabase: Client = create_client(url, key)

def generate_vitals(is_anomaly=False):
    if is_anomaly:
        # Generate a sudden spike (Anomaly)
        return {
            "hr": round(random.uniform(130.0, 160.0), 1),
            "spo2": round(random.uniform(85.0, 90.0), 1),
            "temp": round(random.uniform(38.5, 40.0), 1),
            "bp_sys": random.randint(140, 180),
            "bp_dia": random.randint(90, 110)
        }
    else:
        # Normal healthy ranges
        return {
            "hr": round(random.uniform(60.0, 100.0), 1),
            "spo2": round(random.uniform(95.0, 100.0), 1),
            "temp": round(random.uniform(36.1, 37.2), 1),
            "bp_sys": random.randint(110, 120),
            "bp_dia": random.randint(70, 80)
        }

print("Starting Synthetic Data Generator...")

# 1. Fetch the first available patient from Supabase
patient_res = supabase.table("patient_profiles").select("id").limit(1).execute()
if not patient_res.data:
    print("No patient found. Check your Supabase database.")
    exit(1)

patient_id = patient_res.data[0]['id']
print(f"Target Patient ID: {patient_id}\n")

# 2. Simulate 5 normal readings
print("Simulating Normal Readings...")
for i in range(5):
    payload = generate_vitals(is_anomaly=False)
    res = supabase.table("sensor_events").insert({
        "patient_id": patient_id,
        "source": "synthetic_generator",
        "payload": payload
    }).execute()
    print(f"[{i+1}/5] Inserted Normal: HR={payload['hr']}, SpO2={payload['spo2']}, Temp={payload['temp']}")
    time.sleep(1)

# 3. Simulate 1 anomaly (sudden spike)
print("\nSimulating Anomaly (Spike)...")
anomaly_payload = generate_vitals(is_anomaly=True)
supabase.table("sensor_events").insert({
    "patient_id": patient_id,
    "source": "synthetic_generator",
    "payload": anomaly_payload
}).execute()
print(f"Inserted Anomaly: HR={anomaly_payload['hr']}, SpO2={anomaly_payload['spo2']}, Temp={anomaly_payload['temp']}\n")

# 4. Verify that Twin State automatically updated via Supabase Trigger
print("Verifying if Digital Twin State updated successfully...")
time.sleep(1)
twin_res = supabase.table("twin_states").select("*").eq("patient_id", patient_id).execute()

if twin_res.data:
    state = twin_res.data[0]
    print("\nSUCCESS: DIGITAL TWIN STATE VERIFIED!")
    print(f"Latest HR:   {state['latest_hr']} (Expected: {anomaly_payload['hr']})")
    print(f"Latest SpO2: {state['latest_spo2']} (Expected: {anomaly_payload['spo2']})")
    print(f"Latest Temp: {state['latest_temp']} (Expected: {anomaly_payload['temp']})")
    print(f"Latest BP:   {state['latest_bp_systolic']}/{state['latest_bp_diastolic']} (Expected: {anomaly_payload['bp_sys']}/{anomaly_payload['bp_dia']})")
    print(f"\n24H Rolling Averages Auto-Computed by Trigger:")
    print(state['rolling_avg_24h'])
else:
    print("FAILED: Failed to fetch Twin State.")
