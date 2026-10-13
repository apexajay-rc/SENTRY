#!/usr/bin/env python3
"""
tools/run_experiment.py - SIMPLIFIED TEST VERSION
"""

import asyncio
import subprocess
import sys
import time
import json
import os
import random
import socket
import threading
from dataclasses import dataclass, asdict
from typing import List, Dict

# Experiment configuration
EXPERIMENT_SLICE = "experiment.slice"
FOREGROUND_SCOPE = "foreground.scope"
BACKGROUND_SCOPE = "background.scope"
MEASUREMENT_SLICE = "measurement.slice"

REPS_PER_CONDITION = 1  # TEST: only 1 rep per condition
CONDITIONS = ["A_unmanaged", "B_static", "C_adaptive"]
TRIAL_DURATION = 10  # TEST: only 10 seconds
COOLDOWN_BETWEEN = 5  # seconds between trials
LATENCY_SAMPLES_PER_TRIAL = 1000

TELEMETRY_SOCK = "/run/sentry/telemetry.sock"

@dataclass
class TrialResult:
    condition: str
    rep: int
    p50_latency_us: float = 0
    p95_latency_us: float = 0
    p99_latency_us: float = 0
    max_latency_us: float = 0
    psi_cpu_avg10: float = 0
    psi_mem_avg10: float = 0
    psi_io_avg10: float = 0
    controller_cpu_pct: float = 0
    controller_rss_mb: float = 0
    timestamp: float = 0

class LatencyMeasurer:
    def __init__(self, interval_ms: float = 1.0, samples: int = 1000):
        self.interval_ms = interval_ms
        self.samples = samples
        self.latencies = []
        self._running = False
        self._thread = None
    
    def start(self):
        self.latencies = []
        self._running = True
        self._thread = threading.Thread(target=self._measure_loop)
        self._thread.start()
    
    def _measure_loop(self):
        interval_s = self.interval_ms / 1000.0
        for _ in range(self.samples):
            if not self._running:
                break
            start = time.perf_counter_ns()
            time.sleep(interval_s)
            end = time.perf_counter_ns()
            actual_us = (end - start) / 1000
            expected_us = self.interval_ms * 1000
            latency = max(0, actual_us - expected_us)
            self.latencies.append(latency)
    
    def stop(self) -> Dict:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        
        if not self.latencies:
            return {"p50": 0, "p95": 0, "p99": 0, "max": 0}
        
        self.latencies.sort()
        total = len(self.latencies)
        return {
            "p50": self.latencies[int(total * 0.50)],
            "p95": self.latencies[int(total * 0.95)],
            "p99": self.latencies[int(total * 0.99)],
            "max": self.latencies[-1]
        }

class ExperimentRunner:
    def __init__(self):
        self.results = []
        self.latency_measurer = LatencyMeasurer()
        
    def run_cmd(self, cmd, capture=True, timeout=None):
        result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=timeout)
        if result.returncode != 0 and capture:
            print(f"  ❌ Failed: {cmd}")
            print(f"     stderr: {result.stderr[:200]}")
        return result

    def send_telemetry(self, msg: dict):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            payload = json.dumps(msg).encode()
            sock.sendto(payload, TELEMETRY_SOCK)
            sock.close()
            return True
        except Exception as e:
            print(f"  ⚠️  Failed to send telemetry: {e}")
            return False

    def setup_topology(self):
        print("Setting up experiment topology...")
        
        for unit in [FOREGROUND_SCOPE, BACKGROUND_SCOPE]:
            self.run_cmd(f"systemctl stop {unit} 2>/dev/null || true")
        
        for slice_name in [EXPERIMENT_SLICE, MEASUREMENT_SLICE]:
            result = self.run_cmd(f"systemctl is-active {slice_name}")
            if result.returncode != 0:
                print(f"  ❌ Slice {slice_name} not active")
                return False
            print(f"  ✅ {slice_name} active")
        
        print("  Creating foreground scope...")
        self.run_cmd(f"systemd-run --no-block --scope --slice={EXPERIMENT_SLICE} --unit={FOREGROUND_SCOPE} --property=CPUWeight=10000 sleep 3600", capture=False)
        print("  Creating background scope...")
        self.run_cmd(f"systemd-run --no-block --scope --slice={EXPERIMENT_SLICE} --unit={BACKGROUND_SCOPE} --property=CPUWeight=100 sleep 3600", capture=False)
        time.sleep(3)
        
        print("  Adding stress-ng workloads...")
        self.run_cmd(f"systemd-run --no-block --scope --slice={EXPERIMENT_SLICE} --unit={FOREGROUND_SCOPE} stress-ng --cpu 4 --timeout 3600s", capture=False)
        self.run_cmd(f"systemd-run --no-block --scope --slice={EXPERIMENT_SLICE} --unit={BACKGROUND_SCOPE} stress-ng --cpu 8 --timeout 3600s", capture=False)
        time.sleep(3)
        
        for scope, weight in [(FOREGROUND_SCOPE, "10000"), (BACKGROUND_SCOPE, "100")]:
            result = self.run_cmd(f"systemctl show --property=CPUWeight --value {scope}")
            actual = result.stdout.strip()
            if actual != weight:
                print(f"  ⚠️  {scope}: weight={actual}, expected {weight}")
            else:
                print(f"  ✅ {scope}: CPUWeight={weight}")
        
        print("  ✅ Topology ready")
        return True

    def cleanup_topology(self):
        for unit in [FOREGROUND_SCOPE, BACKGROUND_SCOPE]:
            self.run_cmd(f"systemctl stop {unit} 2>/dev/null || true")

    def apply_condition(self, condition: str):
        if condition == "A_unmanaged":
            self.run_cmd(f"systemctl set-property {FOREGROUND_SCOPE} CPUWeight=10000 --runtime", capture=False)
            self.run_cmd(f"systemctl set-property {BACKGROUND_SCOPE} CPUWeight=10000 --runtime", capture=False)
            print("  Condition A: Both scopes CPUWeight=10000")
            
        elif condition == "B_static":
            self.run_cmd(f"systemctl set-property {FOREGROUND_SCOPE} CPUWeight=10000 --runtime", capture=False)
            self.run_cmd(f"systemctl set-property {BACKGROUND_SCOPE} CPUWeight=100 --runtime", capture=False)
            print("  Condition B: FG=10000, BG=100 (static)")
            
        elif condition == "C_adaptive":
            self.run_cmd(f"systemctl set-property {FOREGROUND_SCOPE} CPUWeight=10000 --runtime", capture=False)
            self.run_cmd(f"systemctl set-property {BACKGROUND_SCOPE} CPUWeight=100 --runtime", capture=False)
            print("  Condition C: Adaptive (SENTRY shifts on focus)")
            time.sleep(1)
            # In real version: send enable_focus_qos
            
        time.sleep(1)

    def run_trial(self, condition: str, rep: int):
        print(f"\n{'='*50}")
        print(f"TRIAL: {condition} - Rep 1/1")
        print(f"{'='*50}")
        
        self.apply_condition(condition)
        
        print("  Starting latency measurement...")
        # Simple measurement inline for testing
        latencies = []
        interval_ms = 1.0
        samples = 1000
        interval_s = 1.0 / 1000.0
        
        print(f"  Running for 10s...")
        for _ in range(1000):
            start = time.perf_counter_ns()
            time.sleep(0.001)
            end = time.perf_counter_ns()
            actual_us = (end - start) / 1000
            expected_us = 1000
            latency = max(0, actual_us - expected_us)
        
        latencies = []
        for _ in range(1000):
            start = time.perf_counter_ns()
            time.sleep(0.001)
            end = time.perf_counter_ns()
            actual_us = (end - start) / 1000
            expected_us = 1000
            latency = max(0, actual_us - expected_us)
            latencies.append(latency)
        
        latencies.sort()
        total = len(latencies)
        return {
            "p50": latencies[int(total * 0.50)],
            "p95": latencies[int(total * 0.95)],
            "p99": latencies[int(total * 0.99)],
            "max": latencies[-1]
        }

    def run_cmd(self, cmd, capture=True, timeout=None):
        result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=timeout)
        if result.returncode != 0 and capture:
            print(f"  ❌ Failed: {cmd}")
            print(f"     stderr: {result.stderr[:200]}")
        return result

async def main():
    print("=" * 50)
    print("SENTRY DAY 3 EXPERIMENT - SIMPLIFIED TEST")
    print("=" * 50)
    
    # Check slices
    result = subprocess.run("systemctl is-active experiment.slice measurement.slice", shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print("Slices not active!")
        return
    
    print("Slices active, running quick test...")
    
    # Run one quick trial
    latencies = []
    for _ in range(500):
        start = time.perf_counter_ns()
        time.sleep(0.001)
        end = time.perf_counter_ns()
        actual_us = (end - start) / 1000
        expected_us = 1000
        latency = max(0, actual_us - expected_us)
        latencies.append(latency)
    
    latencies.sort()
    total = len(latencies)
    print(f"\nTest complete:")
    print(f"  P50: {latencies[int(total*0.50)]:.1f}µs")
    print(f"  P95: {latencies[int(total*0.95)]:.1f}µs")
    print(f"  P99: {latencies[int(total*0.99)]:.1f}µs")
    print(f"  Max: {latencies[-1]:.1f}µs")

if __name__ == "__main__":
    asyncio.run(main())