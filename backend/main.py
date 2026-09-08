import os
import uuid
import pickle
import logging
import datetime
import numpy as np
import pandas as pd
import shap
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# ---------------------------------------------------------------
# Structured Logging
# ---------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)
logger = logging.getLogger("weartwin")

app = FastAPI(
    title="WearTwin — Healthcare Digital Twin Engine",
    version="4.0.0",
    description="Real-time physiological monitoring, LightGBM/XGBoost risk classification, and SHAP explainability."
)

# ---------------------------------------------------------------
# API Key Authentication
# Reads API_KEY from .env. If empty, auth is BYPASSED (dev mode).
# Set a strong key in production: API_KEY=your-secret-key-here
# ---------------------------------------------------------------
API_KEY = os.environ.get("API_KEY", "")

async def verify_api_key(x_api_key: str | None = Header(default=None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: invalid or missing X-API-Key header."
        )
    return x_api_key

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, patient_id: str):
        await websocket.accept()
        if patient_id not in self.active_connections:
            self.active_connections[patient_id] = []
        self.active_connections[patient_id].append(websocket)
        print(f"INFO: WebSocket connected for patient {patient_id}")

    def disconnect(self, websocket: WebSocket, patient_id: str):
        if patient_id in self.active_connections:
            if websocket in self.active_connections[patient_id]:
                self.active_connections[patient_id].remove(websocket)
        print(f"INFO: WebSocket disconnected for patient {patient_id}")

    async def broadcast_patient_update(self, patient_id: str, data: dict):
        if patient_id in self.active_connections:
            disconnected = []
            for connection in self.active_connections[patient_id]:
                try:
                    await connection.send_json(data)
                except Exception:
                    disconnected.append(connection)
            for conn in disconnected:
                self.disconnect(conn, patient_id)

manager = ConnectionManager()

# ---------------------------------------------------------------
# CORS — restricted to known origins only.
# Add your deployment domain to CORS_ORIGINS in .env.
# ---------------------------------------------------------------
_raw_origins = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:5500,http://127.0.0.1:5500"
)
CORS_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
logger.info(f"CORS allowed origins: {CORS_ORIGINS}")

# ---------------------------------------------------------------
# Supabase Initialization
# Uses SUPABASE_SERVICE_KEY (service role) when available —
# this bypasses RLS and allows server-side writes.
# Falls back to SUPABASE_KEY (anon key) for read-only queries.
# ---------------------------------------------------------------
SUPABASE_URL         = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")   # preferred
SUPABASE_ANON_KEY    = os.environ.get("SUPABASE_KEY")           # fallback
SUPABASE_KEY         = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY
supabase: Client     = None

if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        key_type = "service_role" if SUPABASE_SERVICE_KEY else "anon (limited — RLS active)"
        logger.info(f"Supabase client initialized [{key_type}].")
        if not SUPABASE_SERVICE_KEY:
            logger.warning("NOTICE: SUPABASE_SERVICE_KEY is empty in .env. Server writes will be blocked by Supabase RLS policies unless the service_role key is supplied. In-memory fallback will handle state updates.")
    except Exception as e:
        logger.warning(f"Supabase init failed: {e}. Running in local-only mode.")
else:
    logger.warning("SUPABASE_URL or key not set. Running in local-only mode.")

# Local In-Memory Twin Store (fallback when Supabase is unreachable/offline)
local_twin_store = {
    "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2": {
        "patient_id": "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2",
        "status": "active",
        "risk_label": "low",
        "risk_confidence": 0.15,
        "latest_hr": 76.0,
        "latest_spo2": 98.0,
        "latest_temp": 36.7,
        "latest_bp_systolic": 118,
        "latest_bp_diastolic": 76,
        "rolling_avg_24h": {
            "hr": 75.2,
            "spo2": 98.1,
            "temp": 36.6
        },
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
}

local_history_store = {
    "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2": [
        {"hr": 76.0, "spo2": 98.0, "temp": 36.7, "bp_sys": 118, "bp_dia": 76}
    ]
}

# Load ML Model, Scaler, Feature Names & Drift Stats
MODEL_PATH       = "ml/saved_models/model.pkl"
SCALER_PATH      = "ml/saved_models/scaler.pkl"
FEATURES_PATH    = "ml/saved_models/feature_names.pkl"
DRIFT_STATS_PATH = "ml/saved_models/drift_stats.pkl"

ml_model    = None
scaler      = None
explainer   = None
drift_stats = None
feature_names_loaded = ['hr', 'spo2', 'temp', 'bp_sys', 'bp_dia', 'activity_level']

if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
    with open(MODEL_PATH, "rb") as f:
        ml_model = pickle.load(f)
    with open(SCALER_PATH, "rb") as f:
        scaler = pickle.load(f)
    if os.path.exists(FEATURES_PATH):
        with open(FEATURES_PATH, "rb") as f:
            feature_names_loaded = pickle.load(f)
    if os.path.exists(DRIFT_STATS_PATH):
        with open(DRIFT_STATS_PATH, "rb") as f:
            drift_stats = pickle.load(f)
        print(f"INFO: Drift baseline loaded for {len(drift_stats)} features.")
    try:
        explainer = shap.TreeExplainer(ml_model)
        print(f"SUCCESS: ML Model ({len(feature_names_loaded)} features) and SHAP TreeExplainer loaded.")
    except Exception as e:
        try:
            n_feat = len(feature_names_loaded)
            explainer = shap.Explainer(ml_model.predict, np.zeros((1, n_feat)))
            print(f"INFO: TreeExplainer fallback to generic Explainer: {e}")
        except Exception as se:
            print(f"WARNING: SHAP Explainer initialization failed: {se}")
else:
    print("WARNING: ML Model not found. Run train_model.py first.")

def check_drift(sample_dict, stats, z_threshold=3.5):
    """Flag features where the incoming value is far from the training distribution."""
    alerts = []
    if not stats:
        return alerts
    for feat, val in sample_dict.items():
        if feat not in stats or stats[feat]["std"] == 0:
            continue
        z = abs((val - stats[feat]["mean"]) / stats[feat]["std"])
        if z > z_threshold:
            alerts.append({"feature": feat, "value": val,
                           "z_score": round(z, 2),
                           "train_mean": stats[feat]["mean"]})
    return alerts

class SensorPayload(BaseModel):
    patient_id: str = Field(...)
    hr: float = Field(...)
    spo2: float = Field(...)
    temp: float = Field(...)
    bp_sys: int = Field(...)
    bp_dia: int = Field(...)
    activity_level: float = Field(default=5.0, ge=0.0, le=10.0,
                                  description="MPU6050 activity intensity 0=sedentary 10=vigorous")
    device_id: str | None = Field(default=None, description="Hardware BLE Smart Band MAC or Device UUID")
    battery_level: int | None = Field(default=None)
    device_timestamp: str | None = Field(default=None)

class BLEHardwarePayload(BaseModel):
    device_id: str = Field(..., description="Hardware BLE Smart Band MAC or Device UUID")
    patient_id: str = Field(default="3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2")
    hr: float = Field(...)
    spo2: float = Field(...)
    temp: float = Field(...)
    bp_sys: int = Field(default=118)
    bp_dia: int = Field(default=76)
    activity_level: float = Field(default=5.0, ge=0.0, le=10.0,
                                  description="MPU6050 activity intensity 0-10")
    battery_level: int = Field(default=100)
    device_timestamp: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

class BatchIngestPayload(BaseModel):
    patient_id: str | None = Field(default=None)
    events: list[SensorPayload] = Field(...)

class PatientCreatePayload(BaseModel):
    full_name: str = Field(...)
    age: int = Field(..., ge=0, le=130)
    gender: str = Field(default="unknown")
    bmi: float | None = Field(default=24.0)
    medical_notes: str | None = Field(default="")
    device_id: str | None = Field(default=None)

DEFAULT_PATIENTS = [
    {
        "id": "3f0f57a9-2c05-4e3a-97bf-d9bb6c24cbc2",
        "full_name": "Sample Patient",
        "age": 38,
        "gender": "female",
        "bmi": 27.4,
        "medical_notes": "Prototype patient for digital twin testing",
        "device_id": "device-001"
    },
    {
        "id": "a1b2c3d4-e5f6-4a5b-8c7d-9e0f1a2b3c4d",
        "full_name": "John Doe (ICU Bed 04)",
        "age": 62,
        "gender": "male",
        "bmi": 31.2,
        "medical_notes": "Post-cardiac monitoring & elevated BP",
        "device_id": "device-002"
    },
    {
        "id": "e5f6a7b8-c9d0-4e1f-2a3b-4c5d6e7f8a9b",
        "full_name": "Sarah Jenkins (Ward 2B)",
        "age": 45,
        "gender": "female",
        "bmi": 24.1,
        "medical_notes": "Routine telemetry observation",
        "device_id": "device-003"
    }
]

@app.get("/health")
async def health_check():
    return {
        "status": "online",
        "mode": "supabase_cloud" if supabase else "local_fallback",
        "ml_model_loaded": ml_model is not None,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

async def process_async_ml_and_twin_update(patient_id: str, payload: SensorPayload, event_id: str, previous_risk_label: str):
    """
    Async Task Worker: Executes ML inference, SHAP calculations, DB writes, and WebSocket broadcasts
    asynchronously off the main ingestion thread for ultra-high throughput telemetry.
    """
    try:
        payload_dict = payload.model_dump()
        payload_dict.pop("patient_id", None)
        
        # 1. Insert raw telemetry into sensor_events DB
        if supabase:
            try:
                supabase.table("sensor_events").insert({
                    "patient_id": patient_id,
                    "source": "ble_hardware" if payload.device_id else "fastapi_backend",
                    "payload": payload_dict
                }).execute()
            except Exception as e:
                print(f"INFO: Supabase DB insert skipped: {e}")

        # 2. Prepare Feature Vector for ML (6 features)
        feat_names = feature_names_loaded
        feat_values = [
            payload.hr, payload.spo2, payload.temp,
            payload.bp_sys, payload.bp_dia, payload.activity_level
        ]
        # Align to exactly the features the model was trained on
        if len(feat_names) < 6:
            feat_names  = ['hr', 'spo2', 'temp', 'bp_sys', 'bp_dia', 'activity_level']
            feat_values = feat_values[:len(feat_names)]

        features_df = pd.DataFrame([feat_values[:len(feat_names)]], columns=feat_names)

        risk_label = "low"
        risk_conf  = 0.15
        shap_json  = {}
        drift_warnings = []

        # Drift Detection: check if incoming vitals are out-of-distribution
        if drift_stats:
            raw_sample = dict(zip(feat_names, feat_values))
            drift_warnings = check_drift(raw_sample, drift_stats, z_threshold=3.5)
            if drift_warnings:
                print(f"INFO: Drift detected for patient {patient_id}: {drift_warnings}")

        # 3. Predict using best ML model (LightGBM) & SHAP Explainability
        if ml_model and scaler:
            scaled_features = scaler.transform(features_df)
            pred = ml_model.predict(scaled_features)[0]
            prob = ml_model.predict_proba(scaled_features)[0][1]

            risk_label = "high" if pred == 1 else "low"
            risk_conf  = round(float(prob), 2)

            try:
                if hasattr(explainer, "shap_values"):
                    shap_vals  = explainer.shap_values(scaled_features)
                    if isinstance(shap_vals, list):
                        # For binary classifiers returning [class_0, class_1], extract class 1 (high-risk)
                        shap_array = shap_vals[1][0] if len(shap_vals) > 1 and hasattr(shap_vals[1], "__getitem__") else shap_vals[0]
                    elif isinstance(shap_vals, np.ndarray):
                        shap_array = shap_vals[0] if shap_vals.ndim > 1 else shap_vals
                    else:
                        shap_array = shap_vals
                else:
                    shap_res   = explainer(scaled_features)
                    shap_array = shap_res.values[0]
            except Exception as se:
                shap_array = [0.0] * len(feat_names)

            for name, val in zip(feat_names, np.ravel(shap_array)):
                shap_json[name] = round(float(val), 3)
            
        # 4. Alert Logic — Risk Escalation
        alert_generated = None
        if previous_risk_label == "low" and risk_label == "high":
            top_feature = max(shap_json, key=shap_json.get) if shap_json else "UNKNOWN"
            alert_generated = f"URGENT: Risk escalated to HIGH! Major factor: {top_feature.upper()}."
            if supabase:
                try:
                    supabase.table("alerts").insert({
                        "patient_id": patient_id,
                        "alert_type": "Risk Escalation",
                        "severity": "high",
                        "message": alert_generated
                    }).execute()
                except Exception as e:
                    logger.warning(f"Supabase alerts insert failed: {e}")

        # 4b. Anomaly Detection — writes to anomaly_flags (mirrors SQL trigger logic
        #     for when Supabase is unreachable and backend operates in local mode)
        detected_anomalies = []
        p = payload
        if p.hr > 130:
            detected_anomalies.append({"flag_type": "tachycardia",
                "severity": "high" if p.hr > 150 else "medium",
                "description": f"Heart rate {p.hr:.1f} bpm > 130 bpm threshold"})
        if p.hr < 45:
            detected_anomalies.append({"flag_type": "bradycardia", "severity": "high",
                "description": f"Heart rate {p.hr:.1f} bpm < 45 bpm threshold"})
        if p.spo2 < 92:
            detected_anomalies.append({"flag_type": "hypoxia",
                "severity": "high" if p.spo2 < 88 else "medium",
                "description": f"SpO2 {p.spo2:.1f}% < 92% threshold"})
        if p.temp > 38.3:
            detected_anomalies.append({"flag_type": "fever",
                "severity": "high" if p.temp > 39.5 else "medium",
                "description": f"Temperature {p.temp:.1f}°C indicates fever"})
        if p.bp_sys > 170:
            detected_anomalies.append({"flag_type": "hypertension",
                "severity": "high" if p.bp_sys > 190 else "medium",
                "description": f"Systolic BP {p.bp_sys} mmHg > 170 mmHg threshold"})
        if p.activity_level < 1.5:
            detected_anomalies.append({"flag_type": "sedentary", "severity": "low",
                "description": f"Activity level {p.activity_level:.1f}/10 — prolonged sedentary state"})

        if detected_anomalies and supabase:
            try:
                supabase.table("anomaly_flags").insert([
                    {"patient_id": patient_id, **a} for a in detected_anomalies
                ]).execute()
            except Exception as e:
                logger.warning(f"Supabase anomaly_flags insert failed: {e}")

        # 5. Insert into risk_history DB
        if supabase:
            try:
                supabase.table("risk_history").insert({
                    "patient_id": patient_id,
                    "risk_label": risk_label,
                    "risk_confidence": risk_conf,
                    "shap_top_features": shap_json
                }).execute()
            except Exception as e:
                logger.warning(f"Supabase risk_history insert failed: {e}")

        # 6. Dynamic Rolling Average Calculation for Local Storage
        if patient_id not in local_history_store:
            local_history_store[patient_id] = []
        local_history_store[patient_id].append({
            "hr": payload.hr,
            "spo2": payload.spo2,
            "temp": payload.temp
        })
        if len(local_history_store[patient_id]) > 100:
            local_history_store[patient_id].pop(0)

        hist = local_history_store[patient_id]
        avg_hr = round(sum(item["hr"] for item in hist) / len(hist), 1)
        avg_spo2 = round(sum(item["spo2"] for item in hist) / len(hist), 1)
        avg_temp = round(sum(item["temp"] for item in hist) / len(hist), 1)

        # 7. Update Twin State
        updated_state = {
            "patient_id": patient_id,
            "status": "active",
            "risk_label": risk_label,
            "risk_confidence": risk_conf,
            "latest_hr": payload.hr,
            "latest_spo2": payload.spo2,
            "latest_temp": payload.temp,
            "latest_bp_systolic": payload.bp_sys,
            "latest_bp_diastolic": payload.bp_dia,
            "rolling_avg_24h": {
                "hr": avg_hr,
                "spo2": avg_spo2,
                "temp": avg_temp
            },
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        if supabase:
            try:
                supabase.table("twin_states").update({
                    "risk_label": risk_label,
                    "risk_confidence": risk_conf
                }).eq("patient_id", patient_id).execute()
                twin_res = supabase.table("twin_states").select("*").eq("patient_id", patient_id).execute()
                if twin_res.data:
                    updated_state = twin_res.data[0]
            except Exception:
                pass

        local_twin_store[patient_id] = updated_state

        response_payload = {
            "status": "success",
            "message": "Sensor data ingested, ML Risk predicted, and Twin updated.",
            "event_id": event_id,
            "alert": alert_generated,
            "anomalies_detected": len(detected_anomalies),
            "anomaly_types": [a["flag_type"] for a in detected_anomalies],
            "risk_prediction": {
                "label": risk_label,
                "confidence": risk_conf,
                "top_risk_factors": shap_json
            },
            "drift_warnings": drift_warnings,
            "current_twin_state": updated_state
        }

        # Real-time WebSocket Push Broadcast
        await manager.broadcast_patient_update(patient_id, {
            "event": "twin_update",
            **response_payload
        })
    except Exception as e:
        print(f"ERROR in Async ML Task Worker: {e}")

@app.post("/ingest", dependencies=[Depends(verify_api_key)])
async def ingest_sensor_data(payload: SensorPayload, background_tasks: BackgroundTasks):
    try:
        patient_id = payload.patient_id
        previous_risk_label = "low"
        if patient_id in local_twin_store:
            previous_risk_label = local_twin_store[patient_id].get("risk_label", "low")

        event_id = "evt_" + str(uuid.uuid4()).replace("-", "")[:16]

        # High-Throughput Async Queue: Offload ML & DB processing to background task
        background_tasks.add_task(
            process_async_ml_and_twin_update,
            patient_id, payload, event_id, previous_risk_label
        )

        return {
            "status": "queued",
            "message": "Telemetry received and queued for high-throughput async ML risk calculation.",
            "event_id": event_id
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.websocket("/ws/twin/{patient_id}")
async def websocket_twin_endpoint(websocket: WebSocket, patient_id: str):
    await manager.connect(websocket, patient_id)
    # Send initial twin state upon connection
    initial_state = await get_twin_state(patient_id)
    await websocket.send_json({
        "event": "initial_state",
        "data": initial_state
    })
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, patient_id)

@app.get("/twin/{patient_id}")
async def get_twin_state(patient_id: str):
    if supabase:
        try:
            res = supabase.table("twin_states").select("*").eq("patient_id", patient_id).execute()
            if res.data:
                return res.data[0]
        except Exception as e:
            logger.warning(f"Supabase twin_states fetch failed for {patient_id}: {e}")

    if patient_id in local_twin_store:
        return local_twin_store[patient_id]
    
    # Return default dynamic state for any requested patient_id
    default_state = {
        "patient_id": patient_id,
        "status": "active",
        "risk_label": "low",
        "risk_confidence": 0.15,
        "latest_hr": 76.0,
        "latest_spo2": 98.0,
        "latest_temp": 36.7,
        "latest_bp_systolic": 118,
        "latest_bp_diastolic": 76,
        "rolling_avg_24h": {
            "hr": 75.0,
            "spo2": 98.0,
            "temp": 36.7
        },
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    local_twin_store[patient_id] = default_state
    return default_state

@app.get("/patients")
async def get_patient_list():
    """
    Returns list of all active patient profiles for doctor selection.
    """
    if supabase:
        try:
            res = supabase.table("patient_profiles").select("*").order("created_at", desc=True).execute()
            if res.data and len(res.data) > 0:
                return {"status": "success", "patients": res.data}
        except Exception as e:
            logger.warning(f"Supabase patient fetch failed: {e}")

    return {"status": "success", "patients": DEFAULT_PATIENTS}

@app.post("/patients", dependencies=[Depends(verify_api_key)])
async def create_patient_profile(payload: PatientCreatePayload):
    """
    Registers a new patient profile into Supabase / local twin store.
    """
    new_id = "patient_" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    patient_data = {
        "id": new_id,
        "full_name": payload.full_name,
        "age": payload.age,
        "gender": payload.gender,
        "bmi": payload.bmi,
        "medical_notes": payload.medical_notes,
        "device_id": payload.device_id or f"device-{new_id[-4:]}"
    }

    if supabase:
        try:
            db_res = supabase.table("patient_profiles").insert({
                "full_name": payload.full_name,
                "age": payload.age,
                "gender": payload.gender,
                "bmi": payload.bmi,
                "medical_notes": payload.medical_notes,
                "device_id": payload.device_id
            }).execute()
            if db_res.data:
                patient_data = db_res.data[0]
                new_id = patient_data["id"]

                # Initialize Twin State
                supabase.table("twin_states").insert({
                    "patient_id": new_id,
                    "latest_hr": 78.0,
                    "latest_spo2": 98.0,
                    "latest_temp": 36.8,
                    "latest_bp_systolic": 120,
                    "latest_bp_diastolic": 80,
                    "risk_label": "low",
                    "risk_confidence": 0.15,
                    "status": "active"
                }).execute()
        except Exception as e:
            logger.warning(f"Supabase patient insert failed: {e}")

    DEFAULT_PATIENTS.append(patient_data)
    return {"status": "success", "message": "Patient registered successfully.", "patient": patient_data}

@app.post("/ingest/ble", dependencies=[Depends(verify_api_key)])
async def ingest_ble_hardware_data(payload: BLEHardwarePayload, background_tasks: BackgroundTasks):
    """
    Dedicated endpoint for Hardware Smart Bands (ESP32 / BLE / Wearables).
    Receives raw hardware telemetry, logs device metadata, and updates digital twin asynchronously.
    """
    sensor_payload = SensorPayload(
        patient_id=payload.patient_id,
        hr=payload.hr,
        spo2=payload.spo2,
        temp=payload.temp,
        bp_sys=payload.bp_sys,
        bp_dia=payload.bp_dia,
        activity_level=payload.activity_level,
        device_id=payload.device_id,
        battery_level=payload.battery_level,
        device_timestamp=payload.device_timestamp
    )
    result = await ingest_sensor_data(sensor_payload, background_tasks)
    result["ble_metadata"] = {
        "device_id": payload.device_id,
        "battery_level": payload.battery_level,
        "hardware_timestamp": payload.device_timestamp
    }
    return result

@app.post("/ingest/batch", dependencies=[Depends(verify_api_key)])
async def batch_sync_offline_telemetry(batch: BatchIngestPayload, background_tasks: BackgroundTasks):
    """
    Offline-First Synchronization Endpoint.
    Flushes buffered offline telemetry items accumulated while internet/backend was unreachable.
    """
    results = []
    for event in batch.events:
        res = await ingest_sensor_data(event, background_tasks)
        if event.device_id:
            res["ble_metadata"] = {
                "device_id": event.device_id,
                "battery_level": event.battery_level,
                "hardware_timestamp": event.device_timestamp
            }
        results.append(res)
    
    return {
        "status": "success",
        "synced_count": len(results),
        "message": f"Successfully queued {len(results)} offline telemetry items to async task worker.",
        "latest_result": results[-1] if results else None
    }

if __name__ == "__main__":
    import uvicorn
    import socket

    port = 8000
    for p in [8000, 8080, 8001]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', p))
                port = p
                break
        except OSError:
            continue

    print(f"Starting Healthcare Digital Twin Backend Server on http://127.0.0.1:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port)

