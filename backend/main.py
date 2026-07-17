import os
import pickle
import numpy as np
import shap
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

app = FastAPI(title="Digital Twin Update Engine", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase credentials missing in .env")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Load ML Model & Scaler for Phase 4
MODEL_PATH = "ml/saved_models/model.pkl"
SCALER_PATH = "ml/saved_models/scaler.pkl"

ml_model = None
scaler = None
explainer = None

if os.path.exists(MODEL_PATH) and os.path.exists(SCALER_PATH):
    with open(MODEL_PATH, "rb") as f:
        ml_model = pickle.load(f)
    with open(SCALER_PATH, "rb") as f:
        scaler = pickle.load(f)
    explainer = shap.Explainer(ml_model)
    print("SUCCESS: ML Model and SHAP Explainer loaded successfully.")
else:
    print("WARNING: ML Model not found. Run train_model.py first.")

class SensorPayload(BaseModel):
    patient_id: str = Field(...)
    hr: float = Field(...)
    spo2: float = Field(...)
    temp: float = Field(...)
    bp_sys: int = Field(...)
    bp_dia: int = Field(...)

@app.post("/ingest")
async def ingest_sensor_data(payload: SensorPayload):
    try:
        payload_dict = payload.model_dump()
        patient_id = payload_dict.pop("patient_id")
        
        # Phase 5 Step 1: Fetch the PREVIOUS risk label before we do anything
        prev_twin_res = supabase.table("twin_states").select("risk_label").eq("patient_id", patient_id).execute()
        previous_risk_label = prev_twin_res.data[0]["risk_label"] if prev_twin_res.data else "low"
        
        # 1. Insert into sensor_events (Trigger computes rolling avg)
        db_res = supabase.table("sensor_events").insert({
            "patient_id": patient_id,
            "source": "fastapi_backend",
            "payload": payload_dict
        }).execute()
        
        event_id = db_res.data[0]["id"]

        # 2. Prepare Feature Vector for ML
        # For testing Phase 5 (Alerts), if HR > 130 we force a "high risk" feature vector
        # Otherwise normal feature vector
        is_spiking = payload.hr > 130 or payload.bp_sys > 150
        
        if is_spiking:
            # High risk mock (High Glucose, High BMI, etc.)
            features = np.array([[6, 180, payload.bp_sys, 35, 150, 35.0, 0.8, 50]])
        else:
            # Low risk mock
            features = np.array([[0, 110, payload.bp_sys, 20, 80, 25.0, 0.2, 30]])
        
        risk_label = "pending"
        risk_conf = 0.0
        shap_json = {}

        # 3. Predict using XGBoost & SHAP Explainability
        if ml_model and scaler:
            scaled_features = scaler.transform(features)
            pred = ml_model.predict(scaled_features)[0]
            prob = ml_model.predict_proba(scaled_features)[0][1]
            
            risk_label = "high" if pred == 1 else "low"
            risk_conf = round(float(prob), 2)
            
            shap_vals = explainer(scaled_features)
            shap_array = shap_vals.values[0]
            feature_names = ['Pregnancies', 'Glucose', 'BloodPressure', 'SkinThickness', 'Insulin', 'BMI', 'DPF', 'Age']
            top_idx = np.argmax(np.abs(shap_array))
            shap_json = {
                feature_names[top_idx]: round(float(shap_array[top_idx]), 3)
            }
            
        # Phase 5 Step 2: Alert Logic
        alert_generated = None
        if previous_risk_label == "low" and risk_label == "high":
            top_feature = list(shap_json.keys())[0] if shap_json else "Unknown"
            alert_generated = f"URGENT: Patient risk escalated to HIGH! Major contributing factor: {top_feature}."
            
            # Save alert to DB
            supabase.table("alerts").insert({
                "patient_id": patient_id,
                "alert_type": "Risk Escalation",
                "severity": "high",
                "message": alert_generated
            }).execute()

        # 4. Insert into risk_history
        supabase.table("risk_history").insert({
            "patient_id": patient_id,
            "risk_label": risk_label,
            "risk_confidence": risk_conf,
            "shap_top_features": shap_json
        }).execute()

        # 5. Update Twin State with risk
        supabase.table("twin_states").update({
            "risk_label": risk_label,
            "risk_confidence": risk_conf
        }).eq("patient_id", patient_id).execute()

        # 6. Fetch updated state
        twin_res = supabase.table("twin_states").select("*").eq("patient_id", patient_id).execute()
        
        return {
            "status": "success",
            "message": "Sensor data ingested, ML Risk predicted, and Twin updated.",
            "event_id": event_id,
            "alert": alert_generated,
            "risk_prediction": {
                "label": risk_label,
                "confidence": risk_conf,
                "top_risk_factors": shap_json
            },
            "current_twin_state": twin_res.data[0]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/twin/{patient_id}")
async def get_twin_state(patient_id: str):
    try:
        res = supabase.table("twin_states").select("*").eq("patient_id", patient_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Patient Twin not found")
        return res.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
