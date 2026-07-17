import os
import pickle
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
import xgboost as xgb
import lightgbm as lgb
import shap
import warnings
warnings.filterwarnings('ignore')

print("1. Downloading PIMA Diabetes Dataset...")
url = "https://raw.githubusercontent.com/jbrownlee/Datasets/master/pima-indians-diabetes.data.csv"
columns = ['Pregnancies', 'Glucose', 'BloodPressure', 'SkinThickness', 'Insulin', 'BMI', 'DiabetesPedigreeFunction', 'Age', 'Outcome']
data = pd.read_csv(url, names=columns)

print("2. Preprocessing (Handling missing values & scaling)...")
# In PIMA, 0 values in certain columns are actually missing values
cols_with_zeros = ['Glucose', 'BloodPressure', 'SkinThickness', 'Insulin', 'BMI']
data[cols_with_zeros] = data[cols_with_zeros].replace(0, np.nan)
data.fillna(data.mean(), inplace=True)

X = data.drop('Outcome', axis=1)
y = data['Outcome']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

print("\n3. Training XGBoost...")
xgb_model = xgb.XGBClassifier(eval_metric='logloss', random_state=42)
xgb_model.fit(X_train_scaled, y_train)
xgb_preds = xgb_model.predict(X_test_scaled)
xgb_probs = xgb_model.predict_proba(X_test_scaled)[:, 1]

print(f"   XGBoost - Accuracy: {accuracy_score(y_test, xgb_preds):.3f}, F1: {f1_score(y_test, xgb_preds):.3f}, AUC: {roc_auc_score(y_test, xgb_probs):.3f}")

print("\n4. Training LightGBM...")
lgb_model = lgb.LGBMClassifier(random_state=42, verbose=-1)
lgb_model.fit(X_train_scaled, y_train)
lgb_preds = lgb_model.predict(X_test_scaled)
lgb_probs = lgb_model.predict_proba(X_test_scaled)[:, 1]

print(f"   LightGBM - Accuracy: {accuracy_score(y_test, lgb_preds):.3f}, F1: {f1_score(y_test, lgb_preds):.3f}, AUC: {roc_auc_score(y_test, lgb_probs):.3f}")

# Choosing the best model
best_model = xgb_model
print("\n5. Integrating SHAP for Explainability...")
explainer = shap.Explainer(best_model)
shap_values = explainer(X_test_scaled)
print("   SHAP integration successful.")

print("\n6. Saving Model and Scaler to disk (.pkl)...")
os.makedirs("ml/saved_models", exist_ok=True)

with open("ml/saved_models/model.pkl", "wb") as f:
    pickle.dump(best_model, f)
with open("ml/saved_models/scaler.pkl", "wb") as f:
    pickle.dump(scaler, f)
with open("ml/saved_models/feature_names.pkl", "wb") as f:
    pickle.dump(columns[:-1], f)

print("\n✅ Phase 4 Model Training Complete! Saved to ml/saved_models/")
