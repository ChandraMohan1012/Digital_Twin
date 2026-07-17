Quick start

1) Create a Supabase service role DB URL and set it in the environment:

On Windows PowerShell:

```powershell
$env:DATABASE_URL = "postgresql://service_role:YOUR_SERVICE_KEY@dbhost:5432/postgres"
```

On Linux/macOS:

```bash
export DATABASE_URL="postgresql://service_role:YOUR_SERVICE_KEY@dbhost:5432/postgres"
```

2) Install deps and run

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

3) Ingest a test sensor event (replace patient_id)

```bash
curl -X POST http://localhost:8000/sensor -H "Content-Type: application/json" -d '{"patient_id":"<patient-uuid>","payload":{"hr":82,"spo2":97,"temp":36.7,"bp_sys":120,"bp_dia":78}}'
```

Notes
- This listener uses a dedicated connection to LISTEN on `sensor_event_received`. The DB trigger emits that NOTIFY when a new `sensor_events` row is inserted.
- Replace the placeholder ML update logic with your model invocation and SHAP computation.
- Use the Supabase service role DB URL (kept secret) to allow writes despite RLS.
