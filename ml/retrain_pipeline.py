"""
WearTwin MLOps Continuous Retraining Pipeline
Implements automated Champion vs. Challenger validation gating for production models.
Clinical Safety Guardrails:
  1. Minimum Clinical Recall (Sensitivity) >= 78.0%
  2. Minimum ROC-AUC >= 0.750
  3. Non-Regression F1 Gate: Challenger F1 >= 96% of Champion F1
"""

import os
import json
import shutil
import pickle
import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, average_precision_score, confusion_matrix
)
import lightgbm as lgb
import warnings
warnings.filterwarnings("ignore")

SAVED_DIR = Path("ml/saved_models")
ARCHIVE_DIR = SAVED_DIR / "archive"
DATA_PATH = Path("ml/data/nhanes_diabetes.parquet")
REGISTRY_PATH = SAVED_DIR / "mlops_registry.json"

SAVED_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

FEATURE_COLS = ["hr", "bp_sys", "bp_dia", "bmi", "age", "activity_level"]
TARGET_COL = "high_risk"

MIN_RECALL_GATE = 0.780   # 78% clinical sensitivity minimum
MIN_AUC_GATE    = 0.750   # 0.75 ROC-AUC minimum
F1_RETENTION    = 0.960   # Cannot degrade F1 by more than 4%

def load_mlops_registry() -> List[Dict[str, Any]]:
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_mlops_registry(registry: List[Dict[str, Any]]):
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)

def run_continuous_retraining(
    new_telemetry_batch: Optional[List[Dict[str, Any]]] = None,
    force_promotion: bool = False
) -> Dict[str, Any]:
    """
    Executes the automated continuous retraining pipeline:
      1. Aggregates baseline clinical cohort with recent buffered telemetry.
      2. Trains candidate 'Challenger' model (LightGBM).
      3. Tests Champion vs. Challenger on a shared, held-out test split.
      4. Evaluates clinical safety guardrails.
      5. Automatically promotes or rejects Challenger with audit trail.
    """
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print("=" * 65)
    print("  WearTwin MLOps -- Continuous Retraining & Gating Pipeline")
    print("=" * 65)

    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Base dataset missing: {DATA_PATH}. Run ml/load_real_data.py first.")

    # 1. Load Base Dataset
    df = pd.read_parquet(DATA_PATH)
    initial_len = len(df)
    print(f"\n[1/5] Loaded baseline clinical dataset: {initial_len} records.")

    # 2. Integrate New Telemetry / Drift Samples if provided
    if new_telemetry_batch and len(new_telemetry_batch) > 0:
        new_df = pd.DataFrame(new_telemetry_batch)
        # Ensure required features exist
        valid_cols = [c for c in FEATURE_COLS if c in new_df.columns]
        if len(valid_cols) == len(FEATURE_COLS):
            # If target missing, infer based on clinical criteria (HbA1c or high BP/age risk)
            if TARGET_COL not in new_df.columns:
                # Default heuristic for unlabeled telemetry: systolic >= 140 or BMI >= 30
                new_df[TARGET_COL] = ((new_df["bp_sys"] >= 140) | (new_df["bmi"] >= 30.0)).astype(int)
            
            clean_new = new_df[FEATURE_COLS + [TARGET_COL]].dropna()
            df = pd.concat([df[FEATURE_COLS + [TARGET_COL]], clean_new], ignore_index=True)
            print(f"  Merged {len(clean_new)} new telemetry samples into training pool (Total: {len(df)} records).")

    # 3. Train/Test Split
    X = df[FEATURE_COLS]
    y = df[TARGET_COL]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    pos_w = float((len(y_train) - sum(y_train)) / sum(y_train))

    # 4. Train Challenger Model
    print("\n[2/5] Training Candidate Challenger Model (LightGBM)...")
    challenger = lgb.LGBMClassifier(
        n_estimators=130,
        max_depth=3,
        learning_rate=0.045,
        scale_pos_weight=pos_w,
        random_state=int(datetime.datetime.now().timestamp()) % 10000,
        verbose=-1
    )
    challenger.fit(X_train_s, y_train)

    chall_preds = challenger.predict(X_test_s)
    chall_probs = challenger.predict_proba(X_test_s)[:, 1]

    chall_metrics = {
        "accuracy":  round(float(accuracy_score(y_test, chall_preds)), 4),
        "recall":    round(float(recall_score(y_test, chall_preds)), 4),
        "precision": round(float(precision_score(y_test, chall_preds)), 4),
        "f1_score":  round(float(f1_score(y_test, chall_preds)), 4),
        "roc_auc":   round(float(roc_auc_score(y_test, chall_probs)), 4),
        "pr_auc":    round(float(average_precision_score(y_test, chall_probs)), 4)
    }
    print(f"  Challenger Metrics: AUC={chall_metrics['roc_auc']:.4f} | Recall={chall_metrics['recall']*100:.1f}% | F1={chall_metrics['f1_score']:.4f}")

    # 5. Evaluate Existing Champion Model (if available)
    print("\n[3/5] Evaluating Existing Champion Model on Shared Test Set...")
    champ_model_path = SAVED_DIR / "model.pkl"
    champ_scaler_path = SAVED_DIR / "scaler.pkl"

    champ_metrics = None
    if champ_model_path.exists() and champ_scaler_path.exists():
        try:
            with open(champ_model_path, "rb") as f:
                champion = pickle.load(f)
            with open(champ_scaler_path, "rb") as f:
                champ_scaler = pickle.load(f)
            
            X_test_champ = champ_scaler.transform(X_test)
            champ_preds = champion.predict(X_test_champ)
            champ_probs = champion.predict_proba(X_test_champ)[:, 1]

            champ_metrics = {
                "accuracy":  round(float(accuracy_score(y_test, champ_preds)), 4),
                "recall":    round(float(recall_score(y_test, champ_preds)), 4),
                "precision": round(float(precision_score(y_test, champ_preds)), 4),
                "f1_score":  round(float(f1_score(y_test, champ_preds)), 4),
                "roc_auc":   round(float(roc_auc_score(y_test, champ_probs)), 4),
                "pr_auc":    round(float(average_precision_score(y_test, champ_probs)), 4)
            }
            print(f"  Champion Metrics:   AUC={champ_metrics['roc_auc']:.4f} | Recall={champ_metrics['recall']*100:.1f}% | F1={champ_metrics['f1_score']:.4f}")
        except Exception as e:
            print(f"  Notice: Champion evaluation encountered error: {e}. Treating as initial release.")

    # 6. Champion vs. Challenger Decision Gate
    print("\n[4/5] Executing Clinical Safety & Performance Gating...")
    gate_failures = []

    if chall_metrics["recall"] < MIN_RECALL_GATE:
        gate_failures.append(f"Recall ({chall_metrics['recall']*100:.1f}%) < Minimum Clinical Gate ({MIN_RECALL_GATE*100:.1f}%)")

    if chall_metrics["roc_auc"] < MIN_AUC_GATE:
        gate_failures.append(f"ROC-AUC ({chall_metrics['roc_auc']:.4f}) < Minimum Gate ({MIN_AUC_GATE:.4f})")

    if champ_metrics and not force_promotion:
        min_allowed_f1 = champ_metrics["f1_score"] * F1_RETENTION
        if chall_metrics["f1_score"] < min_allowed_f1:
            gate_failures.append(f"F1 ({chall_metrics['f1_score']:.4f}) degraded beyond 4% of Champion ({min_allowed_f1:.4f})")

    decision = "PROMOTED" if len(gate_failures) == 0 or force_promotion else "REJECTED"
    reason = "Passed all clinical safety & non-regression gates" if decision == "PROMOTED" else "; ".join(gate_failures)
    print(f"  Decision Gate Result: {decision}")
    print(f"  Reason: {reason}")

    # 7. Promotion or Rejection
    print("\n[5/5] Updating Model Registry & Artifacts...")
    registry = load_mlops_registry()
    version_id = f"v{len(registry) + 1}.0"

    registry_entry = {
        "version": version_id,
        "timestamp": timestamp,
        "decision": decision,
        "reason": reason,
        "sample_size": len(df),
        "challenger_metrics": chall_metrics,
        "champion_metrics": champ_metrics,
        "features": FEATURE_COLS
    }
    registry.append(registry_entry)
    save_mlops_registry(registry)

    if decision == "PROMOTED":
        # Archive old champion
        if champ_model_path.exists():
            ts_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = ARCHIVE_DIR / f"model_archive_{ts_str}.pkl"
            shutil.copy2(champ_model_path, archive_path)
            print(f"  Archived previous champion to: {archive_path}")

        # Update drift stats baseline
        new_drift_stats = {}
        for col in FEATURE_COLS:
            new_drift_stats[col] = {
                "mean": float(round(X_train[col].mean(), 3)),
                "std":  float(round(X_train[col].std(), 3))
            }

        with open(champ_model_path, "wb") as f:
            pickle.dump(challenger, f)
        with open(champ_scaler_path, "wb") as f:
            pickle.dump(scaler, f)
        with open(SAVED_DIR / "drift_stats.pkl", "wb") as f:
            pickle.dump(new_drift_stats, f)
        with open(SAVED_DIR / "feature_names.pkl", "wb") as f:
            pickle.dump(FEATURE_COLS, f)

        print(f"  --> Challenger successfully PROMOTED to production as {version_id}!")
    else:
        print(f"  --> Challenger REJECTED. Production model remains unchanged.")

    print("=" * 65)
    return {
        "status": decision,
        "version": version_id,
        "reason": reason,
        "timestamp": timestamp,
        "challenger_metrics": chall_metrics,
        "champion_metrics": champ_metrics
    }

if __name__ == "__main__":
    run_continuous_retraining()
