# Supabase setup guide

1. Open your Supabase project.
2. Go to SQL Editor.
3. Open the file [digital_twin_schema.sql](digital_twin_schema.sql).
4. Copy all content and paste it into the SQL Editor.
5. Click Run.

## What this creates
- patient_profiles
- twin_states
- sensor_events
- risk_history
- anomaly_flags
- alerts

## Next step after DB setup
Use your FastAPI backend to send data into the tables.

Recommended first API flow:
1. Insert a patient profile.
2. Insert a twin state.
3. Insert sensor events.
4. Compute rolling averages and risk score in backend.
5. Save risk history and alerts.

If you want, I can next help you create the FastAPI backend code that connects to this database.
