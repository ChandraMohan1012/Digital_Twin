import requests

BASE_URL = "http://127.0.0.1:8000"

def test_patients():
    print("[TEST 1] Fetching all registered patient profiles...")
    res = requests.get(f"{BASE_URL}/patients")
    print(f"Status: {res.status_code}")
    patients = res.json().get("patients", [])
    print(f"Found {len(patients)} patient profiles:")
    for p in patients:
        print(f" - {p.get('full_name')} (ID: {p.get('id')})")

    print("\n[TEST 2] Registering a new patient profile...")
    new_patient_payload = {
        "full_name": "Test Patient - ICU Ward 3",
        "age": 58,
        "gender": "male",
        "bmi": 28.5,
        "medical_notes": "Hypertension observation",
        "device_id": "device-icu-99"
    }
    res_reg = requests.post(f"{BASE_URL}/patients", json=new_patient_payload)
    print(f"Status: {res_reg.status_code}")
    print(f"Response: {res_reg.json()}")

    print("\n[TEST 3] Re-fetching patient list...")
    res_list2 = requests.get(f"{BASE_URL}/patients")
    patients2 = res_list2.json().get("patients", [])
    print(f"Updated Patient Count: {len(patients2)}")

if __name__ == "__main__":
    test_patients()
