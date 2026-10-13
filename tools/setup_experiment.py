#!/usr/bin/env python3
"""
tools/setup_experiment.py

SENTRY Day 3 Experiment - Creates controlled cgroup topology.
Creates experiment.slice with foreground/background scopes for benchmarking.
Uses systemd-run for transient units (no sudo unit file writes needed).
"""

import asyncio
import subprocess
import sys
import time
import os

EXPERIMENT_SLICE = "experiment.slice"
FOREGROUND_SCOPE = "foreground.scope"
BACKGROUND_SCOPE = "background.scope"
MEASUREMENT_SLICE = "measurement.slice"

WORKLOADS = {
    "foreground": {"cpu": 4, "timeout": "300s", "description": "Foreground interactive (4 CPU)"},
    "background": {"cpu": 8, "timeout": "300s", "description": "Background batch (8 CPU)"}
}

def run_cmd(cmd, capture=True):
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True)
    if result.returncode != 0 and capture:
        print(f"  ❌ Failed: {cmd}")
        print(f"     stderr: {result.stderr}")
    return result

def create_slice(slice_name, cpu_weight=None, memory_high=None):
    """Create a transient slice using systemd-run."""
    print(f"Creating {slice_name}...")
    
    # Create slice with systemd-run --scope (transient)
    cmd = [
        "systemd-run", "--scope",
        f"--slice={slice_name}",
        f"--unit={slice_name}",
        "--collect",
        "sleep", "infinity"
    ]
    
    if cpu_weight:
        cmd.insert(-2, f"--property=CPUWeight={cpu_weight}")
    if memory_high:
        cmd.insert(-2, f"--property=MemoryHigh={memory_high}")
    
    result = run_cmd(" ".join(cmd), capture=False)
    if result.returncode == 0:
        print(f"  ✅ {slice_name} created (transient)")
        return True
    return False

def create_scope(scope_name, slice_name, cpu_weight=None):
    """Create a transient scope in a slice."""
    print(f"Creating {scope_name} in {slice_name}...")
    
    cmd = [
        "systemd-run", "--scope",
        f"--slice={slice_name}",
        f"--unit={scope_name}",
        "--collect",
        "sleep", "infinity"
    ]
    
    if cpu_weight:
        cmd.insert(-2, f"--property=CPUWeight={cpu_weight}")
    
    result = run_cmd(" ".join(cmd), capture=False)
    if result.returncode == 0:
        print(f"  ✅ {scope_name} created")
        return True
    return False

def launch_workload(scope_name, cpu_cores, timeout="300s"):
    """Launch stress-ng workload in existing scope."""
    print(f"Launching stress-ng --cpu {cpu_cores} in {scope_name}...")
    
    # Use systemd-run to run in the same scope
    cmd = [
        "systemd-run", "--scope",
        f"--unit={scope_name}",
        "stress-ng", f"--cpu={cpu_cores}", f"--timeout={timeout}"
    ]
    
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"  ✅ Workload launched (PID: {proc.pid})")
    return proc

def cleanup():
    """Clean up experiment slices and scopes."""
    print("Cleaning up experiment...")
    
    for unit in [FOREGROUND_SCOPE, BACKGROUND_SCOPE, EXPERIMENT_SLICE, MEASUREMENT_SLICE]:
        run_cmd(f"systemctl stop {unit} 2>/dev/null || true")
    
    print("  ✅ Cleanup complete")

def setup_experiment():
    """Set up the full experiment topology using transient units."""
    print("=" * 60)
    print("SENTRY DAY 3 EXPERIMENT - TOPOLOGY SETUP (transient)")
    print("=" * 60)
    
    # Create slices (transient)
    create_slice(EXPERIMENT_SLICE, cpu_weight=10000)
    create_slice(MEASUREMENT_SLICE, cpu_weight=10000)
    
    time.sleep(2)
    
    # Create scopes in experiment slice
    create_scope(FOREGROUND_SCOPE, EXPERIMENT_SLICE, cpu_weight=10000)
    create_scope(BACKGROUND_SCOPE, EXPERIMENT_SLICE, cpu_weight=100)
    
    time.sleep(2)
    
    # Verify
    print("\nVerifying topology...")
    for scope in [FOREGROUND_SCOPE, BACKGROUND_SCOPE]:
        result = run_cmd(f"systemctl status {scope} --no-pager | head -5")
        status = "running" if "active (running)" in result.stdout else "NOT RUNNING"
        print(f"  {scope}: {status}")
    
    print("\n" + "=" * 60)
    print("TOPOLOGY READY")
    print("=" * 60)
    print(f"""
Experiment topology:
  {EXPERIMENT_SLICE} (CPUWeight=10000)
  ├── {FOREGROUND_SCOPE} (CPUWeight=10000) → stress-ng --cpu 4
  └── {BACKGROUND_SCOPE} (CPUWeight=100)    → stress-ng --cpu 8

  {MEASUREMENT_SLICE} (CPUWeight=10000) → measurement tools (EXCLUDED from SENTRY)
""")

def launch_workloads():
    """Launch stress-ng in both scopes."""
    print("Launching workloads...")
    
    fg_proc = launch_workload(FOREGROUND_SCOPE, WORKLOADS["foreground"]["cpu"], WORKLOADS["foreground"]["timeout"])
    bg_proc = launch_workload(BACKGROUND_SCOPE, WORKLOADS["background"]["cpu"], WORKLOADS["background"]["timeout"])
    
    if fg_proc and bg_proc:
        print("\n✅ Both workloads running")
        return fg_proc, bg_proc
    return None, None

async def main():
    if len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        cleanup()
        return
    
    if len(sys.argv) > 1 and sys.argv[1] == "launch":
        launch_workloads()
        return
    
    setup_experiment()
    
    print("\nRun 'python3 setup_experiment.py launch' to start workloads")
    print("Run 'python3 setup_experiment.py cleanup' to clean up")

if __name__ == "__main__":
    import time
    asyncio.run(main())