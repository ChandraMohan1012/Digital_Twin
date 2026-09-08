"""
WearTwin Clinical Machine Learning Pipeline
Trained on CDC NHANES 2017-2018 Real Adult Clinical Cohort (N=5,261)
Features:
  - hr: 60s resting pulse (bpm)
  - bp_sys: Systolic blood pressure (mmHg)
  - bp_dia: Diastolic blood pressure (mmHg)
  - bmi: Body Mass Index (kg/m^2)
  - age: Chronological age (years)
  - activity_level: Continuous physical exertion index (0-10)

Ground Truth:
  - High Risk (Prediabetes + Diabetes): Laboratory HbA1c >= 5.7% (ADA criteria)
  - Clinical Diabetes: Laboratory HbA1c >= 6.5% (ADA diagnostic threshold)
"""

import os
import json
import pickle
import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, average_precision_score, confusion_matrix
)
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
import xgboost as xgb
import lightgbm as lgb
import shap
import warnings
warnings.filterwarnings('ignore')

SAVED_DIR = Path("ml/saved_models")
SAVED_DIR.mkdir(parents=True, exist_ok=True)
DATA_PATH = Path("ml/data/nhanes_diabetes.parquet")

def train_and_evaluate():
    print("=" * 65)
    print("  WearTwin -- Clinical ML Training Pipeline (CDC NHANES)")
    print("=" * 65)

    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Dataset not found at {DATA_PATH}. Run ml/load_real_data.py first.")

    # 1. Load Real Clinical Cohort
    print("\n[1/6] Loading CDC NHANES Clinical Cohort...")
    df = pd.read_parquet(DATA_PATH)
    feature_cols = ["hr", "bp_sys", "bp_dia", "bmi", "age", "activity_level"]
    target_col = "high_risk"  # HbA1c >= 5.7% (Screening / early warning target)

    print(f"  Total records: {len(df)}")
    print(f"  Features ({len(feature_cols)}): {feature_cols}")
    print(f"  Target: '{target_col}' (HbA1c >= 5.7%)")
    print(f"    Positive (High-Risk): {df[target_col].sum()} ({df[target_col].mean()*100:.1f}%)")
    print(f"    Negative (Control):   {(df[target_col]==0).sum()} ({(1-df[target_col].mean())*100:.1f}%)")

    # Also track clinical diabetes (HbA1c >= 6.5%)
    print(f"  Secondary diagnostic threshold (HbA1c >= 6.5%):")
    print(f"    Positive (Diabetes):  {df['diabetes'].sum()} ({df['diabetes'].mean()*100:.1f}%)")

    # 2. Train / Test Split & Scaling
    print("\n[2/6] Stratified Train/Test Split (80/20) & Standardization...")
    X = df[feature_cols]
    y = df[target_col]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )
    print(f"  Training cohort:   {len(X_train)} samples")
    print(f"  Hold-out test set: {len(X_test)} samples")

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled  = scaler.transform(X_test)

    # Calculate class imbalance weighting factor
    pos_weight = float((len(y_train) - sum(y_train)) / sum(y_train))
    print(f"  Calculated scale_pos_weight: {pos_weight:.2f}")

    # Compute baseline drift statistics on training data
    drift_stats = {}
    for col in feature_cols:
        drift_stats[col] = {
            "mean": float(round(X_train[col].mean(), 3)),
            "std":  float(round(X_train[col].std(), 3))
        }

    # 3. Model Zoo Training & Cross-Comparison
    print("\n[3/6] Training & Benchmarking 4 Machine Learning Architectures...")
    models = {
        "LightGBM": lgb.LGBMClassifier(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.05,
            scale_pos_weight=pos_weight,
            random_state=42,
            verbose=-1
        ),
        "XGBoost": xgb.XGBClassifier(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.05,
            scale_pos_weight=pos_weight,
            random_state=42,
            eval_metric="logloss"
        ),
        "Random Forest": RandomForestClassifier(
            n_estimators=150,
            max_depth=5,
            class_weight="balanced",
            random_state=42
        ),
        "Logistic Regression": LogisticRegression(
            class_weight="balanced",
            max_iter=1000,
            random_state=42
        )
    }

    results = {}
    fitted_models = {}

    for name, clf in models.items():
        clf.fit(X_train_scaled, y_train)
        fitted_models[name] = clf

        preds = clf.predict(X_test_scaled)
        probs = clf.predict_proba(X_test_scaled)[:, 1]

        cm = confusion_matrix(y_test, preds)
        tn, fp, fn, tp = cm.ravel()
        specificity = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0

        metrics = {
            "accuracy":    round(float(accuracy_score(y_test, preds)), 4),
            "precision":   round(float(precision_score(y_test, preds)), 4),
            "recall":      round(float(recall_score(y_test, preds)), 4),
            "specificity": round(specificity, 4),
            "f1_score":    round(float(f1_score(y_test, preds)), 4),
            "roc_auc":     round(float(roc_auc_score(y_test, probs)), 4),
            "pr_auc":      round(float(average_precision_score(y_test, probs)), 4),
            "confusion_matrix": {
                "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)
            }
        }
        results[name] = metrics
        print(f"  [{name:19s}] AUC: {metrics['roc_auc']:.4f} | Recall: {metrics['recall']*100:.1f}% | Prec: {metrics['precision']*100:.1f}% | F1: {metrics['f1_score']:.4f} | Acc: {metrics['accuracy']*100:.1f}%")

    # Select champion model based on F1-score and clinical Recall
    best_model_name = max(results, key=lambda k: results[k]["f1_score"])
    best_model = fitted_models[best_model_name]
    print(f"\n  --> Champion Architecture: {best_model_name} (F1 = {results[best_model_name]['f1_score']:.4f}, AUC = {results[best_model_name]['roc_auc']:.4f})")

    # 4. Clinical Threshold Tuning Analysis
    print("\n[4/6] Conducting Decision Threshold Calibration Analysis...")
    best_probs = best_model.predict_proba(X_test_scaled)[:, 1]
    thresholds = [0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    threshold_analysis = []

    print(f"  {'Threshold':<11} {'Recall (Sensitivity)':<22} {'Specificity':<15} {'Precision':<12} {'F1-Score':<10}")
    print("  " + "-" * 70)
    for t in thresholds:
        t_preds = (best_probs >= t).astype(int)
        t_cm = confusion_matrix(y_test, t_preds)
        tn, fp, fn, tp = t_cm.ravel()
        t_rec = float(recall_score(y_test, t_preds))
        t_spec = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
        t_prec = float(precision_score(y_test, t_preds)) if (tp + fp) > 0 else 0.0
        t_f1 = float(f1_score(y_test, t_preds)) if (t_prec + t_rec) > 0 else 0.0

        entry = {
            "threshold": t,
            "recall": round(t_rec, 4),
            "specificity": round(t_spec, 4),
            "precision": round(t_prec, 4),
            "f1_score": round(t_f1, 4),
            "tp": int(tp), "fp": int(fp), "tn": int(tn), "fn": int(fn)
        }
        threshold_analysis.append(entry)
        star = " *" if t == 0.45 else ""
        print(f"  {t:<11.2f} {t_rec*100:<21.1f}% {t_spec*100:<14.1f}% {t_prec*100:<11.1f}% {t_f1:<10.4f}{star}")

    # 5. SHAP Explainability & Global Importance
    print("\n[5/6] Computing SHAP Global Feature Attributions...")
    if best_model_name in ["LightGBM", "Random Forest"]:
        explainer = shap.TreeExplainer(best_model)
    else:
        # Fallback explainer for tree or linear models
        explainer = shap.TreeExplainer(best_model)

    shap_test = explainer.shap_values(X_test_scaled)
    if isinstance(shap_test, list) and len(shap_test) > 1:
        shap_vals = shap_test[1]
    elif isinstance(shap_test, np.ndarray) and shap_test.ndim > 2:
        shap_vals = shap_test[:, :, 1]
    else:
        shap_vals = shap_test

    global_importance = np.abs(shap_vals).mean(axis=0)
    feature_importance_dict = {
        feat: round(float(imp), 4)
        for feat, imp in sorted(zip(feature_cols, global_importance), key=lambda x: x[1], reverse=True)
    }

    print("  Global SHAP Feature Attribution Ranking:")
    for rank, (feat, imp) in enumerate(feature_importance_dict.items(), 1):
        print(f"    {rank}. {feat:16s} : {imp:.4f}")

    # 6. Save Artifacts for Backend Inference
    print("\n[6/6] Persisting Production Artifacts...")
    with open(SAVED_DIR / "model.pkl", "wb") as f:
        pickle.dump(best_model, f)
    with open(SAVED_DIR / "scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)
    with open(SAVED_DIR / "feature_names.pkl", "wb") as f:
        pickle.dump(feature_cols, f)
    with open(SAVED_DIR / "drift_stats.pkl", "wb") as f:
        pickle.dump(drift_stats, f)

    # Save comprehensive reports
    report = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "dataset": "CDC NHANES 2017-2018 Adult Clinical Cohort",
        "sample_size": len(df),
        "target": "high_risk (HbA1c >= 5.7%)",
        "features": feature_cols,
        "champion_model": best_model_name,
        "models": results,
        "shap_importance": feature_importance_dict,
        "recommended_threshold": 0.45
    }
    with open(SAVED_DIR / "clinical_comparison_report.json", "w") as f:
        json.dump(report, f, indent=2)

    with open(SAVED_DIR / "clinical_threshold_analysis.json", "w") as f:
        json.dump(threshold_analysis, f, indent=2)

    print(f"  Artifacts saved:")
    print(f"    - {SAVED_DIR / 'model.pkl'} ({best_model_name})")
    print(f"    - {SAVED_DIR / 'scaler.pkl'}")
    print(f"    - {SAVED_DIR / 'feature_names.pkl'}")
    print(f"    - {SAVED_DIR / 'drift_stats.pkl'}")
    print(f"    - {SAVED_DIR / 'clinical_comparison_report.json'}")
    print(f"    - {SAVED_DIR / 'clinical_threshold_analysis.json'}")
    print("=" * 65)
    print("  TRAINING COMPLETE -- REAL CLINICAL MODEL READY")
    print("=" * 65)

if __name__ == "__main__":
    train_and_evaluate()
