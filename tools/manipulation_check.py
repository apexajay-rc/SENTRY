#!/usr/bin/env python3
"""
Manipulation Check — Verify CPUWeight mechanism changes CPU allocation under contention.

Tests:
1. Create real CPU contention (more workers than CPUs)
2. Three weight configurations: equal, FG-high/BG-low, FG-low/BG-high
3. Measure CPU time via cpu.stat usage_usec
4. Verify weights in systemd AND cgroup filesystem
"""

import subprocess
import time
import threading
import json
import os
import sys
from typing import Dict, List

EXPERIMENT_SLICE = "experiment.slice"
FOREGROUND_SCOPE = "foreground.scope"
BACKGROUND_SCOPE = "background.scope"

# Use more workers than CPUs to create contention
# On 12-core: 16 FG + 16 BG = 32 workers competing for 12 CPUs
FG_WORKERS = 16
BG_WORKERS = 16
MEASUREMENT_DURATION = 10  # seconds

def run_cmd(cmd, capture=True, timeout=None):
    if not capture:
        def run_bg():
            subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t = threading.Thread(target=run_bg)
        t.daemon = True
        t.start()
        time.sleep(0.5)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    result = subprocess.run(cmd, shell=True, capture_output=capture, text=True, timeout=timeout)
    return result

def create_scope_with_property(unit: str, weight: str, workers: int) -> bool:
    """Create scope with CPUWeight property set at creation time."""
    def run_scope():
        cmd = [
            "systemd-run", "--user", "--scope", 
            f"--slice={EXPERIMENT_SLICE}",
            f"--unit={unit}",
            f"--property=CPUWeight={weight}",
            "stress-ng", "--cpu", str(workers), "--timeout", "3600s"
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t = threading.Thread(target=run_scope)
    t.daemon = True
    t.start()
    return True

def wait_for_scope(unit: str, timeout: float = 10.0) -> bool:
    """Wait for scope to appear and have CPUWeight set."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        result = run_cmd(f"systemctl --user show --property=CPUWeight,ControlGroup --value {unit}")
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2 and lines[1] != "[not set]":
                return True
        time.sleep(0.2)
    return False

def get_cpuweight(unit: str) -> str:
    result = run_cmd(f"systemctl --user show --property=CPUWeight --value {unit}")
    return result.stdout.strip()

def get_controlgroup(unit: str) -> str:
    result = run_cmd(f"systemctl --user show --property=ControlGroup --value {unit}")
    return result.stdout.strip()

def get_cgroup_cpu_weight(cgroup_path: str) -> str:
    """Read cpu.weight from cgroup filesystem."""
    weight_file = f"/sys/fs/cgroup{cgroup_path}/cpu.weight"
    try:
        with open(weight_file, 'r') as f:
            return f.read().strip()
    except:
        return "NOT_FOUND"

def get_cgroup_cpu_stat(cgroup_path: str) -> Dict:
    """Read cpu.stat from cgroup filesystem."""
    stat_file = f"/sys/fs/cgroup{cgroup_path}/cpu.stat"
    try:
        with open(stat_file, 'r') as f:
            stats = {}
            for line in f:
                if ' ' in line:
                    key, val = line.strip().split(' ', 1)
                    stats[key] = int(val)
            return stats
    except:
        return {}

def get_stress_ng_pids(unit: str) -> List[int]:
    """Find stress-ng worker PIDs in a scope using cgroup hierarchy."""
    try:
        # Get cgroup path first
        cgroup = get_controlgroup(unit)
        if not cgroup:
            return []
        
        # Read tasks from cgroup
        tasks_file = f"/sys/fs/cgroup{cgroup}/cgroup.procs"
        if os.path.exists(tasks_file):
            with open(tasks_file, 'r') as f:
                return [int(line.strip()) for line in f if line.strip()]
        return []
    except:
        return []

def verify_process_cgroups(unit: str, expected_cgroup: str) -> bool:
    """Verify all stress-ng processes are in the expected cgroup."""
    pids = get_stress_ng_pids(unit)
    for pid in pids:
        try:
            with open(f"/proc/{pid}/cgroup", 'r') as f:
                cgroup_line = f.read().strip()
                if expected_cgroup not in cgroup_line:
                    return False
        except:
            return False
    return len(pids) > 0

def cleanup():
    for unit in [FOREGROUND_SCOPE, BACKGROUND_SCOPE]:
        run_cmd(f"systemctl --user stop {unit} 2>/dev/null || true")
    time.sleep(1)

def run_manipulation_check():
    print("=" * 70)
    print("MANIPULATION CHECK: CPUWeight → CPU Allocation Under Contention")
    print("=" * 70)
    
    # Ensure slice exists
    result = run_cmd(f"systemctl --user is-active {EXPERIMENT_SLICE}")
    if result.returncode != 0:
        print(f"❌ Slice {EXPERIMENT_SLICE} not active")
        return False
    print(f"✅ Slice {EXPERIMENT_SLICE} active")
    
    cleanup()
    
    # Test configurations: (fg_weight, bg_weight, description)
    configs = [
        ("10000", "10000", "Equal weights (baseline)"),
        ("10000", "100", "FG high / BG low (foreground priority)"),
        ("100", "10000", "FG low / BG high (background priority)"),
        ("10000", "10000", "Equal weights (re-baseline)"),
    ]
    
    all_results = []
    
    for fg_weight, bg_weight, desc in configs:
        print(f"\n{'='*70}")
        print(f"TEST: {desc} (FG={fg_weight}, BG={bg_weight})")
        print(f"{'='*70}")
        
        # Create scopes WITH --property=CPUWeight at creation
        print(f"  Creating foreground scope (stress-ng --cpu {FG_WORKERS})...")
        create_scope_with_property(FOREGROUND_SCOPE, fg_weight, FG_WORKERS)
        
        print(f"  Creating background scope (stress-ng --cpu {BG_WORKERS})...")
        create_scope_with_property(BACKGROUND_SCOPE, bg_weight, BG_WORKERS)
        
        # Wait for scopes and weights to be active
        print("  Waiting for scopes to activate and weights to apply...")
        if not wait_for_scope(FOREGROUND_SCOPE):
            print("  ❌ Foreground scope failed to activate")
            cleanup()
            return False
        if not wait_for_scope(BACKGROUND_SCOPE):
            print("  ❌ Background scope failed to activate")
            cleanup()
            return False
        
        # Verify weights in systemd
        fg_weight_actual = get_cpuweight(FOREGROUND_SCOPE)
        bg_weight_actual = get_cpuweight(BACKGROUND_SCOPE)
        print(f"  systemd CPUWeight: FG={fg_weight_actual}, BG={bg_weight_actual}")
        
        # Verify weights in cgroup filesystem
        fg_cgroup = get_controlgroup(FOREGROUND_SCOPE)
        bg_cgroup = get_controlgroup(BACKGROUND_SCOPE)
        fg_cgroup_weight = get_cgroup_cpu_weight(fg_cgroup)
        bg_cgroup_weight = get_cgroup_cpu_weight(bg_cgroup)
        print(f"  cgroup path: FG={fg_cgroup}")
        print(f"  cgroup path: BG={bg_cgroup}")
        print(f"  kernel cpu.weight: FG={fg_cgroup_weight}, BG={bg_cgroup_weight}")
        
        # Verify process placement
        fg_verified = verify_process_cgroups(FOREGROUND_SCOPE, fg_cgroup)
        bg_verified = verify_process_cgroups(BACKGROUND_SCOPE, bg_cgroup)
        print(f"  Process cgroup verified: FG={fg_verified}, BG={bg_verified}")
        
        # REJECT if configuration doesn't match
        if fg_weight_actual != fg_weight or bg_weight_actual != bg_weight:
            print(f"  ❌ REJECTED: systemd weights don't match requested")
            cleanup()
            continue
        if fg_cgroup_weight != fg_weight or bg_cgroup_weight != bg_weight:
            print(f"  ❌ REJECTED: kernel weights don't match requested")
            cleanup()
            continue
        if not fg_verified or not bg_verified:
            print(f"  ❌ REJECTED: processes not in correct cgroups")
            cleanup()
            continue
        
        print(f"  ✅ Configuration verified - starting measurement...")
        
        # Record initial cpu.stat
        time.sleep(1)  # Let workloads stabilize
        fg_stat_start = get_cgroup_cpu_stat(fg_cgroup)
        bg_stat_start = get_cgroup_cpu_stat(bg_cgroup)
        
        # Measure for fixed duration
        print(f"  Measuring CPU allocation for {MEASUREMENT_DURATION}s...")
        time.sleep(MEASUREMENT_DURATION)
        
        # Record final cpu.stat
        fg_stat_end = get_cgroup_cpu_stat(fg_cgroup)
        bg_stat_end = get_cgroup_cpu_stat(bg_cgroup)
        
        # Calculate usage
        fg_usage = fg_stat_end.get('usage_usec', 0) - fg_stat_start.get('usage_usec', 0)
        bg_usage = bg_stat_end.get('usage_usec', 0) - bg_stat_start.get('usage_usec', 0)
        total_usage = fg_usage + bg_usage
        fg_pct = (fg_usage / total_usage * 100) if total_usage > 0 else 0
        bg_pct = (bg_usage / total_usage * 100) if total_usage > 0 else 0
        
        # Expected ratio based on weights
        expected_fg_ratio = int(fg_weight) / (int(fg_weight) + int(bg_weight))
        expected_fg_pct = expected_fg_ratio * 100
        
        print(f"  CPU usage: FG={fg_usage/1e6:.2f}s ({fg_pct:.1f}%), BG={bg_usage/1e6:.2f}s ({bg_pct:.1f}%)")
        print(f"  Expected FG%: {expected_fg_pct:.1f}%")
        print(f"  Deviation: {fg_pct - expected_fg_pct:+.1f}%")
        
        result = {
            "config": desc,
            "fg_weight": fg_weight,
            "bg_weight": bg_weight,
            "fg_weight_actual": fg_weight_actual,
            "bg_weight_actual": bg_weight_actual,
            "fg_cgroup_weight": fg_cgroup_weight,
            "bg_cgroup_weight": bg_cgroup_weight,
            "fg_cgroup": fg_cgroup,
            "bg_cgroup": bg_cgroup,
            "fg_usage_usec": fg_usage,
            "bg_usage_usec": bg_usage,
            "fg_pct": fg_pct,
            "bg_pct": bg_pct,
            "expected_fg_pct": expected_fg_pct,
            "deviation_pct": fg_pct - expected_fg_pct,
            "processes_verified": fg_verified and bg_verified,
        }
        all_results.append(result)
        
        cleanup()
        time.sleep(2)
    
    # Analysis
    print(f"\n{'='*70}")
    print("ANALYSIS")
    print(f"{'='*70}")
    
    baseline = all_results[0] if all_results else None
    fg_priority = all_results[1] if len(all_results) > 1 else None
    bg_priority = all_results[2] if len(all_results) > 2 else None
    re_baseline = all_results[3] if len(all_results) > 3 else None
    
    if baseline:
        print(f"\nBaseline (equal weights 10000/10000):")
        print(f"  FG CPU share: {baseline['fg_pct']:.1f}% (expected 50.0%)")
        print(f"  Deviation: {baseline['deviation_pct']:+.1f}%")
    
    if fg_priority:
        print(f"\nFG priority (10000/100):")
        print(f"  FG CPU share: {fg_priority['fg_pct']:.1f}% (expected 99.0%)")
        print(f"  Deviation: {fg_priority['deviation_pct']:+.1f}%")
    
    if bg_priority:
        print(f"\nBG priority (100/10000):")
        print(f"  FG CPU share: {bg_priority['fg_pct']:.1f}% (expected 1.0%)")
        print(f"  Deviation: {bg_priority['deviation_pct']:+.1f}%")
    
    if re_baseline:
        print(f"\nRe-baseline (10000/10000):")
        print(f"  FG CPU share: {re_baseline['fg_pct']:.1f}% (expected 50.0%)")
        print(f"  Deviation: {re_baseline['deviation_pct']:+.1f}%")
    
    # Check manipulation worked
    checks = {}
    if fg_priority and baseline:
        fg_shift = fg_priority['fg_pct'] - baseline['fg_pct']
        checks['fg_priority_increases_fg_share'] = fg_shift > 10  # Should increase by ~49%
        print(f"\nFG priority increases FG share: {'✅' if checks['fg_priority_increases_fg_share'] else '❌'} (Δ={fg_shift:+.1f}%)")
    
    if bg_priority and baseline:
        bg_shift = baseline['fg_pct'] - bg_priority['fg_pct']
        checks['bg_priority_decreases_fg_share'] = bg_shift > 10  # Should decrease by ~49%
        print(f"BG priority decreases FG share: {'✅' if checks['bg_priority_decreases_fg_share'] else '❌'} (Δ={bg_shift:+.1f}%)")
    
    checks['weights_in_systemd'] = all(
        r['fg_weight_actual'] == r['fg_weight'] and r['bg_weight_actual'] == r['bg_weight'] 
        for r in all_results
    )
    print(f"Weights correct in systemd: {'✅' if checks['weights_in_systemd'] else '❌'}")
    
    checks['weights_in_kernel'] = all(
        r['fg_cgroup_weight'] == r['fg_weight'] and r['bg_cgroup_weight'] == r['bg_weight'] 
        for r in all_results
    )
    print(f"Weights correct in kernel: {'✅' if checks['weights_in_kernel'] else '❌'}")
    
    checks['processes_verified'] = all(r['processes_verified'] for r in all_results)
    print(f"Processes in correct cgroups: {'✅' if checks['processes_verified'] else '❌'}")
    
    success = all(checks.values())
    print(f"\n{'='*70}")
    print(f"MANIPULATION CHECK: {'✅ PASSED' if success else '❌ FAILED'}")
    print(f"{'='*70}")
    
    # Save results
    output = {
        "timestamp": time.time(),
        "trials": all_results,
        "checks": checks,
        "passed": success,
    }
    
    filepath = f"/home/maj-ajay/SENTRY/manipulation_check_{int(time.time())}.json"
    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {filepath}")
    
    return success

if __name__ == "__main__":
    success = run_manipulation_check()
    sys.exit(0 if success else 1)