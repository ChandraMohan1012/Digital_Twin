import os
import json
import pickle
import datetime
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score,
    precision_score, recall_score, confusion_matrix
)
import xgboost as xgb
import lightgbm as lgb
import shap
import warnings
warnings.filterwarnings('ignore')

print("=" * 65)
print("  WearTwin -- Healthcare Digital Twin ML Training Pipeline")
print("=" * 65)

# ---------------------------------------------------------------
# 1. Synthetic Physiological Dataset  (N=5000, 6 features)
#
#    Features: hr, spo2, temp, bp_sys, bp_dia, activity_level
#    activity_level: continuous 0-10 scale derived from MPU6050
#      0 = sedentary, 5 = moderate activity, 10 = vigorous
#    70% Normal / 30% High-Risk class distribution
#    Labels derived from a latent risk score with Gaussian noise
#    (sigma=1.6) -- prevents deterministic rule leakage.
#
#    NOTE: Age, BMI, and family history are stored in
#    patient_profiles (static profile fields) and are planned
#    for inclusion in a future model iteration that performs
#    per-patient profile enrichment at inference time. They are
#    intentionally excluded from the current streaming inference
#    model because they do not change with each sensor cycle.
# ---------------------------------------------------------------
print("\n[1/6] Generating Synthetic Physiological Dataset (N=5000, 6 features)...")
np.random.seed(42)
num_samples = 5000

# --- Normal vital distributions (~70% of dataset) ---
num_normal    = int(num_samples * 0.7)
hr_normal     = np.random.normal(75,   8,   num_normal)
spo2_normal   = np.random.normal(97.5, 1.5, num_normal)
temp_normal   = np.random.normal(36.8, 0.4, num_normal)
bp_sys_normal = np.random.normal(118,  9,   num_normal)
bp_dia_normal = np.random.normal(76,   6,   num_normal)
act_normal    = np.random.normal(4.5,  2.0, num_normal)   # moderate activity

# --- Higher-risk vital distributions (~30% of dataset) ---
# Ranges intentionally OVERLAP with normal -- real physiological
# data does not separate cleanly by threshold.
num_high_risk = num_samples - num_normal
n3 = num_high_risk // 3
n2 = num_high_risk // 2

hr_risk = np.concatenate([
    np.random.normal(128, 15, n3),              # tachycardia-leaning
    np.random.normal(52,   8, n3),              # bradycardia-leaning
    np.random.normal(92,  12, num_high_risk - 2 * n3)
])
spo2_risk = np.concatenate([
    np.random.normal(91,   3.5, n2),            # hypoxia-leaning
    np.random.normal(95.5, 2,   num_high_risk - n2)
])
temp_risk = np.concatenate([
    np.random.normal(38.4, 0.9, n2),            # fever-leaning
    np.random.normal(36.9, 0.5, num_high_risk - n2)
])
bp_sys_risk = np.concatenate([
    np.random.normal(152, 18, n2),              # hypertensive-leaning
    np.random.normal(88,   8, num_high_risk - n2)
])
bp_dia_risk = bp_sys_risk * 0.6 + np.random.normal(5, 6, num_high_risk)

# Low activity (sedentary) is a T2D risk marker -- high-risk group
# has bimodal activity: mostly sedentary with some over-exercising
act_risk = np.concatenate([
    np.random.normal(1.5, 1.2, n2),             # sedentary / low activity
    np.random.normal(8.5, 1.0, num_high_risk - n2)  # vigorous / compensatory
])

# Clip to physiologically valid ranges
hr            = np.clip(np.concatenate([hr_normal,     hr_risk]),     40,   190)
spo2          = np.clip(np.concatenate([spo2_normal,   spo2_risk]),   70,   100)
temp          = np.clip(np.concatenate([temp_normal,   temp_risk]),   34.0, 41.5)
bp_sys        = np.clip(np.concatenate([bp_sys_normal, bp_sys_risk]), 70,   210)
bp_dia        = np.clip(np.concatenate([bp_dia_normal, bp_dia_risk]), 40,   130)
activity_lvl  = np.clip(np.concatenate([act_normal,    act_risk]),    0.0,  10.0)

# ---------------------------------------------------------------
# Label generation via latent risk score + Gaussian noise.
# Activity: sedentary (<3) increases risk; vigorous (>8) also
# slightly elevated due to overexertion pattern.
# ---------------------------------------------------------------
activity_risk_contrib = np.where(
    activity_lvl < 3,  (3 - activity_lvl) / 3 * 0.6,   # sedentary penalty
    np.where(activity_lvl > 8, (activity_lvl - 8) / 2 * 0.3, 0)  # vigorous penalty
)

latent_risk_score = (
    0.9 * ((hr     - 75)   / 20)  +
    0.9 * ((97.5   - spo2) / 3)   +
    0.9 * ((temp   - 36.8) / 1.0) +
    0.7 * ((bp_sys - 118)  / 20)  +
    0.5 * ((bp_dia - 76)   / 12)  +
    0.6 * activity_risk_contrib
)
noise  = np.random.normal(0, 1.6, num_samples)
latent = latent_risk_score + noise
thresh = np.percentile(latent, 70)   # ~30% high-risk prevalence
y      = np.where(latent > thresh, 1, 0)

feature_names = ['hr', 'spo2', 'temp', 'bp_sys', 'bp_dia', 'activity_level']
data = pd.DataFrame({
    'hr': hr, 'spo2': spo2, 'temp': temp,
    'bp_sys': bp_sys, 'bp_dia': bp_dia,
    'activity_level': activity_lvl,
    'Outcome': y
})
X = data[feature_names]

high_risk_count = int(y.sum())
normal_count    = num_samples - high_risk_count
class_ratio     = normal_count / high_risk_count

print(f"   Samples     : {num_samples}  |  Features: {len(feature_names)}")
print(f"   Normal      : {normal_count} (70%)  |  High-Risk: {high_risk_count} (30%)")
print(f"   Features    : {feature_names}")
print(f"   Imbalance   : {class_ratio:.2f}:1  (neg:pos)")

# ---------------------------------------------------------------
# 2. Train / Test Split & Scaling (80/20 stratified)
# ---------------------------------------------------------------
print("\n[2/6] Splitting and Scaling Data (80/20 stratified)...")
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)
scaler         = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled  = scaler.transform(X_test)
print(f"   Train: {len(X_train)} samples  |  Test: {len(X_test)} samples")

# ---------------------------------------------------------------
# Helper: evaluate any model, print metrics + confusion matrix
# ---------------------------------------------------------------
def evaluate(name, y_true, y_pred, y_prob):
    acc  = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec  = recall_score(y_true, y_pred, zero_division=0)
    f1   = f1_score(y_true, y_pred, zero_division=0)
    auc  = roc_auc_score(y_true, y_prob)
    cm   = confusion_matrix(y_true, y_pred)
    tn, fp, fn, tp = cm.ravel()

    print(f"\n   --- {name} Results ---")
    print(f"   Accuracy  : {acc:.4f}")
    print(f"   Precision : {prec:.4f}")
    print(f"   Recall    : {rec:.4f}  <- higher = fewer missed high-risk cases")
    print(f"   F1-Score  : {f1:.4f}")
    print(f"   AUC-ROC   : {auc:.4f}")
    print(f"   Confusion Matrix (test n={len(y_true)}):")
    print(f"                      Pred Normal   Pred High-Risk")
    print(f"   Actual Normal      TN={tn:<6}      FP={fp:<6}")
    print(f"   Actual High-Risk   FN={fn:<6}      TP={tp:<6}")
    return {"name": name, "acc": acc, "prec": prec, "rec": rec,
            "f1": f1, "auc": auc, "tn": tn, "fp": fp, "fn": fn, "tp": tp}

# ---------------------------------------------------------------
# 3. XGBoost  (class-balanced via scale_pos_weight)
# ---------------------------------------------------------------
print("\n[3/6] Training XGBoost Classifier (class-balanced)...")
xgb_model = xgb.XGBClassifier(
    eval_metric='logloss', random_state=42,
    n_estimators=200, max_depth=4, learning_rate=0.05,
    scale_pos_weight=class_ratio
)
xgb_model.fit(X_train_scaled, y_train)
xgb_preds  = xgb_model.predict(X_test_scaled)
xgb_probs  = xgb_model.predict_proba(X_test_scaled)[:, 1]
xgb_results = evaluate("XGBoost", y_test, xgb_preds, xgb_probs)

# ---------------------------------------------------------------
# 4. LightGBM  (class-balanced via class_weight='balanced')
# ---------------------------------------------------------------
print("\n[4/6] Training LightGBM Classifier (class-balanced)...")
lgb_model = lgb.LGBMClassifier(
    random_state=42, n_estimators=200, max_depth=4,
    learning_rate=0.05, class_weight='balanced', verbose=-1
)
lgb_model.fit(X_train_scaled, y_train)
lgb_preds  = lgb_model.predict(X_test_scaled)
lgb_probs  = lgb_model.predict_proba(X_test_scaled)[:, 1]
lgb_results = evaluate("LightGBM", y_test, lgb_preds, lgb_probs)

# ---------------------------------------------------------------
# 5. Model Comparison + Best Model Selection
# ---------------------------------------------------------------
print("\n[5/6] Model Comparison Summary")
print("=" * 65)
print(f"  {'Metric':<18} {'XGBoost':>12} {'LightGBM':>12}  {'Winner':>10}")
print("-" * 65)
for label, key in [("Accuracy","acc"),("Precision","prec"),("Recall","rec"),("F1-Score","f1"),("AUC-ROC","auc")]:
    xv, lv = xgb_results[key], lgb_results[key]
    print(f"  {label:<18} {xv:>12.4f} {lv:>12.4f}  {'XGBoost' if xv >= lv else 'LightGBM':>10}")
print("=" * 65)

best_model = xgb_model if xgb_results["f1"] >= lgb_results["f1"] else lgb_model
best_name  = "XGBoost"  if xgb_results["f1"] >= lgb_results["f1"] else "LightGBM"
best_res   = xgb_results if best_name == "XGBoost" else lgb_results
print(f"\n  [WINNER] Best model by F1-Score: {best_name}")

# ---------------------------------------------------------------
# 5b. Clinical Decision Threshold Optimization (Recall Sensitivity)
# Directly answers Reviewer 2: evaluates how adjusting probability
# cutoff increases recall for early warning screening.
# ---------------------------------------------------------------
print(f"\n[5b] Decision Threshold Tuning for {best_name} (Early-Risk Sensitivity)")
print("=" * 65)
print(f"  {'Threshold':<12} {'Recall':>10} {'Precision':>12} {'F1-Score':>10} {'Accuracy':>10}")
print("-" * 65)

best_probs = xgb_probs if best_name == "XGBoost" else lgb_probs
threshold_results = []
for thresh_val in [0.50, 0.45, 0.40, 0.35, 0.30]:
    t_preds = np.where(best_probs >= thresh_val, 1, 0)
    t_rec   = recall_score(y_test, t_preds, zero_division=0)
    t_prec  = precision_score(y_test, t_preds, zero_division=0)
    t_f1    = f1_score(y_test, t_preds, zero_division=0)
    t_acc   = accuracy_score(y_test, t_preds)
    threshold_results.append({
        "threshold": thresh_val,
        "recall":    round(float(t_rec),  4),
        "precision": round(float(t_prec), 4),
        "f1":        round(float(t_f1),   4),
        "accuracy":  round(float(t_acc),  4)
    })
    print(f"  {thresh_val:<12.2f} {t_rec:>10.4f} {t_prec:>12.4f} {t_f1:>10.4f} {t_acc:>10.4f}")
print("=" * 65)

# ---------------------------------------------------------------
# Drift Detection Baseline
# Compute per-feature training statistics so the backend can
# compare incoming live readings against the training distribution
# and warn when input data drifts far from learned patterns.
# ---------------------------------------------------------------
train_stats = {}
for col in feature_names:
    vals = X_train[col]
    train_stats[col] = {
        "mean": round(float(vals.mean()), 4),
        "std":  round(float(vals.std()),  4),
        "min":  round(float(vals.min()),  4),
        "max":  round(float(vals.max()),  4),
        "p5":   round(float(np.percentile(vals, 5)),  4),
        "p95":  round(float(np.percentile(vals, 95)), 4)
    }

def check_drift(sample_dict, stats, z_threshold=3.5):
    """
    Returns list of drifted features where |z-score| > z_threshold.
    Used at inference time to flag out-of-distribution readings.
    """
    alerts = []
    for feat, val in sample_dict.items():
        if feat not in stats:
            continue
        s = stats[feat]
        if s["std"] == 0:
            continue
        z = abs((val - s["mean"]) / s["std"])
        if z > z_threshold:
            alerts.append({
                "feature": feat,
                "value": val,
                "z_score": round(z, 2),
                "train_mean": s["mean"],
                "train_std": s["std"]
            })
    return alerts

# Quick drift check on raw test data
drift_counts = sum(
    1 for i in range(len(X_test))
    if check_drift(dict(zip(feature_names, X_test.iloc[i].tolist())), train_stats, z_threshold=3.5)
)
print(f"\n  [DRIFT] Samples with extreme feature values in test set: {drift_counts}/{len(X_test)}")

# ---------------------------------------------------------------
# 6. SHAP Explainability on best model
# ---------------------------------------------------------------
print(f"\n[6/6] SHAP Explainability on best model ({best_name})...")
try:
    explainer   = shap.TreeExplainer(best_model)
    shap_values = explainer.shap_values(X_test_scaled[:5])
    print("   SHAP TreeExplainer initialized successfully.")
except Exception as e:
    try:
        explainer   = shap.Explainer(best_model.predict, X_train_scaled)
        shap_values = explainer(X_test_scaled[:5])
        print(f"   SHAP generic Explainer (fallback): {e}")
    except Exception as se:
        explainer = None
        print(f"   WARNING: SHAP explainer failed: {se}")

# ---------------------------------------------------------------
# Save all artifacts
# ---------------------------------------------------------------
os.makedirs("ml/saved_models", exist_ok=True)

with open("ml/saved_models/model.pkl",        "wb") as f: pickle.dump(best_model, f)
with open("ml/saved_models/scaler.pkl",       "wb") as f: pickle.dump(scaler, f)
with open("ml/saved_models/feature_names.pkl","wb") as f: pickle.dump(feature_names, f)
with open("ml/saved_models/drift_stats.pkl",  "wb") as f: pickle.dump(train_stats, f)

# Versioned model metadata
version_tag  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
model_version = {
    "version":      version_tag,
    "best_model":   best_name,
    "features":     feature_names,
    "num_features": len(feature_names),
    "dataset": {
        "total_samples":     num_samples,
        "normal_samples":    normal_count,
        "high_risk_samples": high_risk_count,
        "high_risk_ratio":   round(float(y.mean()), 4),
        "train_split": 0.8,
        "test_split":  0.2,
        "label_method": "latent_risk_score_with_gaussian_noise_sigma_1.6"
    },
    "metrics": {
        "xgboost": {
            "accuracy":  round(xgb_results["acc"],  4),
            "precision": round(xgb_results["prec"], 4),
            "recall":    round(xgb_results["rec"],  4),
            "f1":        round(xgb_results["f1"],   4),
            "auc":       round(xgb_results["auc"],  4),
            "confusion_matrix": {"TN": int(xgb_results["tn"]), "FP": int(xgb_results["fp"]),
                                 "FN": int(xgb_results["fn"]), "TP": int(xgb_results["tp"])}
        },
        "lightgbm": {
            "accuracy":  round(lgb_results["acc"],  4),
            "precision": round(lgb_results["prec"], 4),
            "recall":    round(lgb_results["rec"],  4),
            "f1":        round(lgb_results["f1"],   4),
            "auc":       round(lgb_results["auc"],  4),
            "confusion_matrix": {"TN": int(lgb_results["tn"]), "FP": int(lgb_results["fp"]),
                                 "FN": int(lgb_results["fn"]), "TP": int(lgb_results["tp"])}
        }
    },
    "drift_baseline": train_stats,
    "threshold_analysis": threshold_results,
    "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
}

# Save threshold analysis report separately
with open("ml/saved_models/threshold_analysis.json", "w") as f:
    json.dump(threshold_results, f, indent=2)

# Always overwrite latest; also save a timestamped copy for history
with open("ml/saved_models/model_version.json", "w") as f:
    json.dump(model_version, f, indent=2)
with open(f"ml/saved_models/model_version_{version_tag}.json", "w") as f:
    json.dump(model_version, f, indent=2)

# Save comparison report separately (for paper figures)
comparison_report = {
    "xgboost":   model_version["metrics"]["xgboost"],
    "lightgbm":  model_version["metrics"]["lightgbm"],
    "best_model": best_name,
    "dataset":   model_version["dataset"],
    "threshold_analysis": threshold_results
}
with open("ml/saved_models/comparison_report.json", "w") as f:
    json.dump(comparison_report, f, indent=2)

print("\n" + "=" * 65)
print(f"  [SUCCESS] Training Complete -- Best Model: {best_name}")
print(f"  [SAVED]   ml/saved_models/model.pkl              ({best_name})")
print(f"  [SAVED]   ml/saved_models/scaler.pkl")
print(f"  [SAVED]   ml/saved_models/feature_names.pkl      {feature_names}")
print(f"  [SAVED]   ml/saved_models/drift_stats.pkl        (6 features)")
print(f"  [SAVED]   ml/saved_models/threshold_analysis.json")
print(f"  [SAVED]   ml/saved_models/model_version.json     v{version_tag}")
print(f"  [SAVED]   ml/saved_models/comparison_report.json")
print("=" * 65)
print(f"\n  FINAL METRICS ({best_name})")
print(f"  Accuracy  : {best_res['acc']:.4f}")
print(f"  Precision : {best_res['prec']:.4f}")
print(f"  Recall    : {best_res['rec']:.4f}  (was 0.54 before class balancing)")
print(f"  F1-Score  : {best_res['f1']:.4f}")
print(f"  AUC-ROC   : {best_res['auc']:.4f}")
print("=" * 65)
