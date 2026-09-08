"""
WearTwin Clinical Pipeline: CDC NHANES Ingestion & Preprocessing
Loads real de-identified human clinical data from the CDC NHANES 2017-2018 cycle:
  - GHB_J: Glycohemoglobin (HbA1c ground truth)
  - BPX_J: Blood pressure & resting pulse rate
  - BMX_J: Body mass index (BMI) & anthropometrics
  - DEMO_J: Demographics (Age, Gender)
  - PAQ_J: Physical activity questionnaire

All datasets merge on the participant sequence identifier 'SEQN'.
"""

import os
import json
import urllib.request
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.impute import KNNImputer

DATA_DIR = Path("ml/data")
RAW_DIR = DATA_DIR / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_DIR.mkdir(parents=True, exist_ok=True)

NHANES_URLS = {
    "ghb": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/GHB_J.xpt",
    "bpx": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/BPX_J.xpt",
    "bmx": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/BMX_J.xpt",
    "demo": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/DEMO_J.xpt",
    "paq": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/PAQ_J.xpt",
}

def download_file(url: str, dest_path: Path, max_retries: int = 4):
    """Download a file with User-Agent header and save to disk if not already cached, with retry on transient network errors."""
    if dest_path.exists() and dest_path.stat().st_size > 0:
        print(f"  [Cached] {dest_path.name} ({dest_path.stat().st_size / 1024:.1f} KB)")
        return
    print(f"  [Downloading] {url} -> {dest_path.name}...")
    import time
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "WearTwin-Research-Pipeline/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp, open(dest_path, "wb") as out_f:
                out_f.write(resp.read())
            print(f"  [Saved] {dest_path.name} ({dest_path.stat().st_size / 1024:.1f} KB)")
            return
        except Exception as e:
            if dest_path.exists():
                dest_path.unlink()
            if attempt == max_retries:
                raise RuntimeError(f"Failed to download {url} after {max_retries} attempts: {e}")
            print(f"  [Retry {attempt}/{max_retries}] Transient error: {e}. Retrying in 2s...")
            time.sleep(2)

def load_and_preprocess_nhanes():
    print("=" * 65)
    print("  WearTwin -- CDC NHANES Real Clinical Data Ingestion")
    print("=" * 65)

    # 1. Download / Verify Raw SAS Transport (.XPT) Files
    print("\n[1/5] Verifying & Downloading CDC NHANES Data Files...")
    raw_files = {}
    for key, url in NHANES_URLS.items():
        dest = RAW_DIR / f"{key.upper()}_J.XPT"
        download_file(url, dest)
        raw_files[key] = dest

    # 2. Load SAS Files into DataFrames
    print("\n[2/5] Parsing SAS XPORT Datasets...")
    dfs = {}
    for key, path in raw_files.items():
        df = pd.read_sas(path, format="xport")
        dfs[key] = df
        print(f"  Loaded {key.upper()}: {df.shape[0]} records, {df.shape[1]} columns")

    # 3. Extract & Merge Targeted Features
    print("\n[3/5] Extracting Clinical Features & Merging on SEQN...")
    
    # Ground Truth: Laboratory HbA1c (must not be null)
    ghb = dfs["ghb"][["SEQN", "LBXGH"]].dropna(subset=["LBXGH"])
    ghb.rename(columns={"LBXGH": "hba1c"}, inplace=True)

    # Blood Pressure & Resting 60s Pulse
    # Note: BPXSY1/BPXDI1 are first readings; fall back to BPXSY2/BPXDI2 if available
    bpx = dfs["bpx"][["SEQN", "BPXPLS", "BPXSY1", "BPXDI1"]].copy()
    bpx.rename(columns={
        "BPXPLS": "hr",
        "BPXSY1": "bp_sys",
        "BPXDI1": "bp_dia"
    }, inplace=True)

    # Anthropometrics: BMI
    bmx = dfs["bmx"][["SEQN", "BMXBMI"]].copy()
    bmx.rename(columns={"BMXBMI": "bmi"}, inplace=True)

    # Demographics: Age and Gender
    demo = dfs["demo"][["SEQN", "RIDAGEYR", "RIAGENDR"]].copy()
    demo.rename(columns={
        "RIDAGEYR": "age",
        "RIAGENDR": "gender"
    }, inplace=True)

    # Physical Activity (PAQ605: Vigorous work activity: 1 = Yes, 2 = No)
    paq = dfs["paq"][["SEQN", "PAQ605"]].copy()
    # Map to continuous activity scale 0.0 to 10.0 matching WearTwin wearable scale:
    # 1 (vigorous) -> 8.0, 2 (no vigorous) -> 3.5
    paq["activity_level"] = paq["PAQ605"].map({1.0: 8.0, 2.0: 3.5}).fillna(4.5)
    paq = paq[["SEQN", "activity_level"]]

    # Merge sequentially on SEQN
    merged = ghb.merge(bpx, on="SEQN", how="inner")
    merged = merged.merge(bmx, on="SEQN", how="inner")
    merged = merged.merge(demo, on="SEQN", how="inner")
    merged = merged.merge(paq, on="SEQN", how="left")
    print(f"  Merged Cohort Size: {len(merged)} clinical participants with lab-confirmed HbA1c")

    # 4. Outlier Filtering & Physiological Plausibility
    print("\n[4/5] Filtering Physiological Outliers & Imputing Missing Telemetry...")
    # Clinically plausible ranges:
    # HR: 30 - 200 bpm
    # BP Systolic: 60 - 240 mmHg
    # BP Diastolic: 40 - 130 mmHg
    # BMI: 12 - 75 kg/m^2
    # Age >= 18 (adult clinical cohort)
    adults = merged[merged["age"] >= 18].copy()
    print(f"  Adult cohort (age >= 18): {len(adults)} participants")

    # Invalidate impossible sensor zeroes (e.g. Diastolic = 0 in survey measurement)
    adults.loc[(adults["bp_dia"] < 35) | (adults["bp_dia"] > 140), "bp_dia"] = np.nan
    adults.loc[(adults["bp_sys"] < 65) | (adults["bp_sys"] > 250), "bp_sys"] = np.nan
    adults.loc[(adults["hr"] < 35) | (adults["hr"] > 180), "hr"] = np.nan
    adults.loc[(adults["bmi"] < 12) | (adults["bmi"] > 70), "bmi"] = np.nan

    # Target Definitions (ADA Clinical Standards):
    # 1) Clinical Type-2 Diabetes: HbA1c >= 6.5%
    # 2) Dysglycemia / High Risk (Prediabetes + Diabetes): HbA1c >= 5.7%
    adults["diabetes"] = (adults["hba1c"] >= 6.5).astype(int)
    adults["high_risk"] = (adults["hba1c"] >= 5.7).astype(int)

    # Impute missing physiological readings using KNNImputer
    impute_cols = ["hr", "bp_sys", "bp_dia", "bmi", "age", "gender", "activity_level"]
    imputer = KNNImputer(n_neighbors=5, weights="distance")
    adults[impute_cols] = imputer.fit_transform(adults[impute_cols])

    # Round continuous physiological metrics to clinically meaningful precision
    adults["hr"] = adults["hr"].round(1)
    adults["bp_sys"] = adults["bp_sys"].round(0).astype(int)
    adults["bp_dia"] = adults["bp_dia"].round(0).astype(int)
    adults["bmi"] = adults["bmi"].round(1)
    adults["age"] = adults["age"].astype(int)
    adults["activity_level"] = adults["activity_level"].round(1)

    # 5. Export Clean Parquet & CSV Datasets
    print("\n[5/5] Exporting Clean Clinical Datasets & Metadata...")
    parquet_path = DATA_DIR / "nhanes_diabetes.parquet"
    csv_path = DATA_DIR / "nhanes_diabetes.csv"
    meta_path = DATA_DIR / "nhanes_metadata.json"

    adults.to_parquet(parquet_path, index=False)
    adults.to_csv(csv_path, index=False)

    metadata = {
        "dataset_name": "CDC NHANES 2017-2018 Adult Clinical Diabetes Cohort",
        "source": "US Centers for Disease Control and Prevention (CDC) National Center for Health Statistics",
        "total_records": len(adults),
        "columns": list(adults.columns),
        "target_definitions": {
            "diabetes": "HbA1c >= 6.5% (ADA Clinical Diagnostic Threshold)",
            "high_risk": "HbA1c >= 5.7% (ADA Early Screening Prediabetes/Diabetes Threshold)"
        },
        "prevalence": {
            "diabetes_positive": int(adults["diabetes"].sum()),
            "diabetes_prevalence_pct": round(float(adults["diabetes"].mean() * 100), 2),
            "high_risk_positive": int(adults["high_risk"].sum()),
            "high_risk_prevalence_pct": round(float(adults["high_risk"].mean() * 100), 2)
        },
        "feature_summary": {
            col: {
                "mean": round(float(adults[col].mean()), 2),
                "std": round(float(adults[col].std()), 2),
                "min": round(float(adults[col].min()), 2),
                "max": round(float(adults[col].max()), 2)
            }
            for col in impute_cols + ["hba1c"]
        }
    }

    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"  Successfully exported:")
    print(f"    - Parquet: {parquet_path} ({parquet_path.stat().st_size / 1024:.1f} KB)")
    print(f"    - CSV:     {csv_path} ({csv_path.stat().st_size / 1024:.1f} KB)")
    print(f"    - Metadata:{meta_path}")
    print(f"\nCohort Summary:")
    print(f"  Total Patients:            {len(adults)}")
    print(f"  Clinical Diabetes (>=6.5): {adults['diabetes'].sum()} ({adults['diabetes'].mean()*100:.1f}%)")
    print(f"  Early Risk (>=5.7):        {adults['high_risk'].sum()} ({adults['high_risk'].mean()*100:.1f}%)")
    print("=" * 65)

    return adults

if __name__ == "__main__":
    load_and_preprocess_nhanes()
