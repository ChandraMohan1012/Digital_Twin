import os
import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "http://127.0.0.1:8000"
PATIENT_ID = "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2"

# 1. Health Check
print(f"[TEST 1] Testing Health Check ({BASE_URL}/health)...")
try:
    res = requests.get(f"{BASE_URL}/health")
    print(f"Status Code: {res.status_code}")
    print("Response:", res.json())
except Exception as e:
    print(f"FAILED: {e}")

print("\n" + "="*50 + "\n")

# 2. Test Normal Telemetry Ingest
normal_payload = {
    "patient_id": PATIENT_ID,
    "hr": 76.0,
    "spo2": 98.0,
    "temp": 36.7,
    "bp_sys": 118,
    "bp_dia": 76
}

print(f"[TEST 2] Sending Normal Telemetry Payload to {BASE_URL}/ingest ...")
try:
    res = requests.post(f"{BASE_URL}/ingest", json=normal_payload)
    print(f"Status Code: {res.status_code}")
    print("Response JSON:", res.json())
except Exception as e:
    print(f"FAILED: {e}")

print("\n" + "="*50 + "\n")

# 3. Test BLE Hardware Smart Band Ingest
ble_payload = {
    "device_id": "esp32-band-001",
    "patient_id": PATIENT_ID,
    "hr": 142.5,
    "spo2": 88.0,
    "temp": 39.2,
    "bp_sys": 165,
    "bp_dia": 102,
    "battery_level": 92
}

print(f"[TEST 3] Sending Hardware Smart Band BLE Payload to {BASE_URL}/ingest/ble ...")
try:
    res = requests.post(f"{BASE_URL}/ingest/ble", json=ble_payload)
    print(f"Status Code: {res.status_code}")
    print("Response JSON:", res.json())
except Exception as e:
    print(f"FAILED: {e}")

print("\n" + "="*50 + "\n")

# 4. Test Offline Batch Queue Sync
batch_payload = {
    "patient_id": PATIENT_ID,
    "events": [
        {"patient_id": PATIENT_ID, "hr": 78.0, "spo2": 98.5, "temp": 36.8, "bp_sys": 120, "bp_dia": 78},
        {"patient_id": PATIENT_ID, "hr": 135.0, "spo2": 90.0, "temp": 38.6, "bp_sys": 150, "bp_dia": 95}
    ]
}

print(f"[TEST 4] Flushing Offline Queue to {BASE_URL}/ingest/batch ...")
try:
    res = requests.post(f"{BASE_URL}/ingest/batch", json=batch_payload)
    print(f"Status Code: {res.status_code}")
    print("Response JSON:", res.json())
except Exception as e:
    print(f"FAILED: {e}")
