#!/usr/bin/env python3
"""
tools/run_experiment.py - WORKING VERSION
Uses user systemd (--user) for slice/scope management.
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

REPS_PER_CONDITION = 3
CONDITIONS = ["A_unmanaged", "B_static", "C_adaptive"]
TRIAL_DURATION = 15
COOLDOWN_BETWEEN = 5
LATENCY_SAMPLES_PER_TRIAL = 2000

TELEMETRY_SOCK = "/run/sentry/telemetry.sock"

# Use user systemd
SYSTEMD_USER = ["systemctl", "--user"]
SYSTEMD_RUN_USER = ["systemd-run", "--user"]


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
    def __init__(self, interval_ms: float = 1.0, samples: int = LATENCY_SAMPLES_PER_TRIAL):
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
        self.results: List[TrialResult] = []
        self.latency_measurer = LatencyMeasurer()
        self._scope_procs = {}

    def run_cmd(self, cmd, capture=True, timeout=None):
        if not capture:
            def run_bg():
                subprocess.run(cmd, shell=True,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
            t = threading.Thread(target=run_bg)
            t.daemon = True
            t.start()
            time.sleep(1)
            return subprocess.CompletedProcess(cmd, 0, "", "")
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
        except Exception:
            # Silently ignore telemetry failures (permission issues)
            return False

    def setup_topology(self):
        print("Setting up experiment topology...")

        # Stop any existing scope units
        for unit in [FOREGROUND_SCOPE, BACKGROUND_SCOPE]:
            self.run_cmd(f"systemctl --user stop {unit} 2>/dev/null || true")

        # Verify slices exist
        for slice_name in [EXPERIMENT_SLICE, MEASUREMENT_SLICE]:
            result = self.run_cmd(f"systemctl --user is-active {slice_name}")
            if result.returncode != 0:
                print(f"  ❌ Slice {slice_name} not active")
                return False
            print(f"  ✅ {slice_name} active")

        # Create scopes WITH workload
        print("  Creating foreground scope with stress-ng...")
        self._run_scope_bg(FOREGROUND_SCOPE, "10000", ["stress-ng", "--cpu", "4", "--timeout", "3600s"])

        print("  Creating background scope...")
        self._run_scope_bg(BACKGROUND_SCOPE, "100", ["stress-ng", "--cpu", "8", "--timeout", "3600s"])

        time.sleep(5)  # Give systemd time to create units and start stress-ng

        # Verify
        for scope, weight in [(FOREGROUND_SCOPE, "10000"), (BACKGROUND_SCOPE, "100")]:
            result = self.run_cmd(f"systemctl --user show --property=CPUWeight --value {scope}")
            actual = result.stdout.strip()
            if actual != weight:
                print(f"  ⚠️  {scope}: weight={actual}, expected {weight}")
            else:
                print(f"  ✅ {scope}: CPUWeight={weight}")

        print("  ✅ Topology ready")
        return True

    def _run_scope_bg(self, unit: str, weight: str, cmd_args: List[str]):
        """Run systemd-run --scope in background thread, then set CPUWeight."""
        def run_scope():
            cmd = ["systemd-run", "--user", "--scope", f"--slice={EXPERIMENT_SLICE}",
                   f"--unit={unit}"] + cmd_args
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Then set CPUWeight reliably
            time.sleep(1)
            subprocess.run(["systemctl", "--user", "set-property", unit, f"CPUWeight={weight}", "--runtime"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        t = threading.Thread(target=run_scope)
        t.daemon = True
        t.start()
        self._scope_procs[unit] = t

    def cleanup_topology(self):
        for unit in [FOREGROUND_SCOPE, BACKGROUND_SCOPE]:
            self.run_cmd(f"systemctl --user stop {unit} 2>/dev/null || true")
        self._scope_procs.clear()

    def apply_condition(self, condition: str):
        if condition == "A_unmanaged":
            self.run_cmd(f"systemctl --user set-property {FOREGROUND_SCOPE} CPUWeight=10000 --runtime", capture=False)
            self.run_cmd(f"systemctl --user set-property {BACKGROUND_SCOPE} CPUWeight=10000 --runtime", capture=False)
            print("  Condition A: Both scopes CPUWeight=10000")
            self.send_telemetry({"type": "disable_focus_qos"})

        elif condition == "B_static":
            self.run_cmd(f"systemctl --user set-property {FOREGROUND_SCOPE} CPUWeight=10000 --runtime", capture=False)
            self.run_cmd(f"systemctl --user set-property {BACKGROUND_SCOPE} CPUWeight=100 --runtime", capture=False)
            print("  Condition B: FG=10000, BG=100 (static)")
            self.send_telemetry({"type": "disable_focus_qos"})

        elif condition == "C_adaptive":
            self.run_cmd(f"systemctl --user set-property {FOREGROUND_SCOPE} CPUWeight=10000 --runtime", capture=False)
            self.run_cmd(f"systemctl --user set-property {BACKGROUND_SCOPE} CPUWeight=100 --runtime", capture=False)
            print("  Condition C: Adaptive (SENTRY shifts on focus)")
            time.sleep(1)
            self.send_telemetry({"type": "enable_focus_qos"})

        time.sleep(1)

    def run_trial(self, condition: str, rep: int) -> TrialResult:
        print(f"\n{'='*50}")
        print(f"TRIAL: {condition} - Rep {rep+1}/{REPS_PER_CONDITION}")
        print(f"{'='*50}")

        self.apply_condition(condition)

        print("  Starting latency measurement...")
        self.latency_measurer.start()

        print(f"  Running for {TRIAL_DURATION}s...")
        time.sleep(TRIAL_DURATION)

        latency = self.latency_measurer.stop()
        psi = self.parse_psi()
        controller = self.get_controller_metrics()

        result = TrialResult(
            condition=condition,
            rep=rep,
            p50_latency_us=latency.get("p50", 0),
            p95_latency_us=latency.get("p95", 0),
            p99_latency_us=latency.get("p99", 0),
            max_latency_us=latency.get("max", 0),
            psi_cpu_avg10=psi.get("cpu_avg10", 0),
            psi_mem_avg10=psi.get("mem_avg10", 0),
            psi_io_avg10=psi.get("io_avg10", 0),
            controller_cpu_pct=controller.get("cpu_pct", 0),
            controller_rss_mb=controller.get("rss_mb", 0),
            timestamp=time.time()
        )

        self.results.append(result)
        print(f"  ✅ Trial complete: P99={result.p99_latency_us:.1f}µs")

        return result

    def run_cmd(self, cmd, capture=True, timeout=None):
        if not capture:
            def run_bg():
                subprocess.run(cmd, shell=True,
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
            t = threading.Thread(target=run_bg)
            t.daemon = True
            t.start()
            time.sleep(1)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=timeout)
        if result.returncode != 0 and capture:
            print(f"  ❌ Failed: {cmd}")
            print(f"     stderr: {result.stderr[:200]}")
        return result

    def parse_psi(self) -> Dict:
        psi = {"cpu_avg10": 0, "mem_avg10": 0, "io_avg10": 0}
        try:
            for resource in ["cpu", "memory", "io"]:
                with open(f"/proc/pressure/{resource}", "r") as f:
                    for line in f:
                        if line.startswith("avg10"):
                            parts = line.strip().split()
                            for part in parts:
                                if part.startswith("avg10="):
                                    psi[f"{resource}_avg10"] = float(part.split("=")[1])
        except Exception:
            pass
        return psi

    def get_controller_metrics(self) -> Dict:
        try:
            result = self.run_cmd("ps -o pcpu,rss -p $(pgrep -f start_sentry.py) --no-headers")
            if result.stdout.strip():
                parts = result.stdout.strip().split()
                return {"cpu_pct": float(parts[0]), "rss_mb": int(parts[1]) / 1024}
        except:
            pass
        return {"cpu_pct": 0, "rss_mb": 0}

    async def run_experiment(self):
        print("=" * 50)
        print("SENTRY DAY 3 EXPERIMENT")
        print("=" * 50)

        if not self.setup_topology():
            return

        trial_order = []
        for condition in CONDITIONS:
            reps = list(range(REPS_PER_CONDITION))
            random.shuffle(reps)
            for rep in reps:
                trial_order.append((condition, rep))

        print(f"Total trials: {len(trial_order)}")
        print(f"Order: {[(c, r) for c, r in trial_order]}")

        for i, (condition, rep) in enumerate(trial_order):
            self.run_trial(condition, rep)

            if i < len(trial_order) - 1:
                print(f"  Cooldown {COOLDOWN_BETWEEN}s...")
                time.sleep(COOLDOWN_BETWEEN)

        self.cleanup_topology()
        self.save_results()
        self.print_summary()

    def save_results(self):
        output = {
            "experiment": "SENTRY Day 3",
            "timestamp": time.time(),
            "conditions": CONDITIONS,
            "reps_per_condition": REPS_PER_CONDITION,
            "trial_duration": TRIAL_DURATION,
            "latency_samples_per_trial": LATENCY_SAMPLES_PER_TRIAL,
            "results": [asdict(r) for r in self.results]
        }

        filepath = f"/home/maj-ajay/SENTRY/experiment_results_{int(time.time())}.json"
        with open(filepath, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {filepath}")

    def print_summary(self):
        print("\n" + "=" * 50)
        print("EXPERIMENT SUMMARY")
        print("=" * 50)

        for condition in CONDITIONS:
            cond_results = [r for r in self.results if r.condition == condition]
            if not cond_results:
                continue

            p50_vals = [r.p50_latency_us for r in cond_results]
            p95_vals = [r.p95_latency_us for r in cond_results]
            p99_vals = [r.p99_latency_us for r in cond_results]
            max_vals = [r.max_latency_us for r in cond_results]

            print(f"\n{condition} ({len(cond_results)} trials):")
            print(f"  P50 Latency:  min={min(p50_vals):.1f} max={max(p50_vals):.1f} avg={sum(p50_vals)/len(p50_vals):.1f} µs")
            print(f"  P95 Latency:  min={min(p95_vals):.1f} max={max(p95_vals):.1f} avg={sum(p95_vals)/len(p95_vals):.1f} µs")
            print(f"  P99 Latency:  min={min(p99_vals):.1f} max={max(p99_vals):.1f} avg={sum(p99_vals)/len(p99_vals):.1f} µs")
            print(f"  Max Latency:  min={min(max_vals):.1f} max={max(max_vals):.1f} avg={sum(max_vals)/len(max_vals):.1f} µs")


async def main():
    runner = ExperimentRunner()
    await runner.run_experiment()


if __name__ == "__main__":
    asyncio.run(main())