#!/usr/bin/env python3
"""
tools/train_sentry_ai.py

Phase 3: The SENTRY Brain Forge.
Loads the behavioral triad dataset, scales the physical metrics,
and trains an Isolation Forest to mathematically identify rogue workloads.
"""

import os
import sys
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler
import joblib

# Ensure the dataset exists
data_file = "sentry_training_data.csv"
if not os.path.exists(data_file):
    print(f"❌ ERROR: Dataset '{data_file}' not found. Run dataset_forge.py first.")
    sys.exit(1)

print("=> 🧠 Initializing SENTRY AI Forge...")

# 1. LOAD DATA
print("=> 📊 Loading raw telemetry data...")
df = pd.read_csv(data_file)
print(f"   [+] Loaded {len(df)} workload snapshots.")

# 2. PREPROCESSING (Eliminating Bias)
# We drop 'pid', 'comm', and 'timestamp'. 
# The AI must learn pure physics, not vocabulary!
features = ['cpu_ms', 'syscalls', 'page_faults']
X = df[features]

# We use RobustScaler because our dataset contains extreme outliers (stress-ng).
# Standard scaling would get skewed by the malware. RobustScaler ignores extremes.
print("=> ⚖️  Scaling physical metrics (RobustScaler)...")
scaler = RobustScaler()
X_scaled = scaler.fit_transform(X)

# 3. TRAINING THE AI
print("=> 🌲 Planting the Isolation Forest...")
# contamination=0.05 means we assume roughly 5% of the data in our 60s window was anomalous
ai_model = IsolationForest(n_estimators=100, contamination=0.05, random_state=42, n_jobs=-1)

print("=> ⚙️  Training model on behavioral topologies...")
ai_model.fit(X_scaled)

# 4. INFERENCE REPORT (Testing the AI against its own training data)
print("=> 🔍 Generating classification report...")
# The model returns 1 for INLIERS (Normal) and -1 for OUTLIERS (Threats)
df['anomaly_status'] = ai_model.predict(X_scaled)

# Separate the results
normal_procs = df[df['anomaly_status'] == 1]
threat_procs = df[df['anomaly_status'] == -1]

print("\n" + "="*60)
print(" 🛡️  SENTRY AI TRAINING REPORT ")
print("="*60)
print(f"Total Snapshots Analyzed: {len(df)}")
print(f"Classified as Normal:     {len(normal_procs)}")
print(f"Classified as Threats:    {len(threat_procs)}")

print("\n=> 🚨 TOP 5 THREATS ISOLATED BY AI (Anomaly = -1):")
# Sort threats by highest CPU usage to see what the AI caught
top_threats = threat_procs.sort_values(by='cpu_ms', ascending=False).head(5)
if not top_threats.empty:
    print(f"{'PID':<8} | {'COMMAND':<15} | {'CPU (ms)':<10} | {'SYSCALLS':<10} | {'FAULTS'}")
    print("-" * 65)
    for index, row in top_threats.iterrows():
        print(f"{int(row['pid']):<8} | {str(row['comm']):<15} | {row['cpu_ms']:<10.2f} | {int(row['syscalls']):<10} | {int(row['page_faults'])}")
else:
    print("   [!] No threats isolated. Try running stress-ng during data collection.")

print("\n=> ✅ TOP 5 LEGITIMATE HEAVY WORKLOADS CLEARED BY AI (Anomaly = 1):")
# Sort normal processes by highest CPU to prove the AI didn't kill legitimate apps
heavy_normal = normal_procs.sort_values(by='cpu_ms', ascending=False).head(5)
if not heavy_normal.empty:
    print(f"{'PID':<8} | {'COMMAND':<15} | {'CPU (ms)':<10} | {'SYSCALLS':<10} | {'FAULTS'}")
    print("-" * 65)
    for index, row in heavy_normal.iterrows():
        print(f"{int(row['pid']):<8} | {str(row['comm']):<15} | {row['cpu_ms']:<10.2f} | {int(row['syscalls']):<10} | {int(row['page_faults'])}")

# 5. SAVING THE BRAIN
print("\n=> 💾 Compiling AI weights to disk...")
os.makedirs("core/model", exist_ok=True)
joblib.dump(ai_model, 'core/model/sentry_model.pkl')
joblib.dump(scaler, 'core/model/sentry_scaler.pkl')

print("=> 🎯 SUCCESS: SENTRY Brain (sentry_model.pkl) is ready for Ring-0 deployment!")
