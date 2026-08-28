#!/bin/bash
set -euo pipefail

REPO_ROOT="/home/maj-ajay/SENTRY"
cd "$REPO_ROOT"

echo "[PHASE 0] Creating attic structure..."
mkdir -p attic/rust_graveyard
mkdir -p attic/ebpf_graveyard
mkdir -p attic/python_v1_graveyard

echo "[PHASE 0] Moving Rust prototypes..."
mv sentry-v6 attic/rust_graveyard/ 2>/dev/null || true
mv tools/daemon_rust attic/rust_graveyard/ 2>/dev/null || true

echo "[PHASE 0] Moving eBPF prototypes..."
mv core/bpf attic/ebpf_graveyard/ 2>/dev/null || true

echo "[PHASE 0] Moving flawed Python modules..."
mv core/psi_sensor.py attic/python_v1_graveyard/ 2>/dev/null || true
mv core/action_tracker.py attic/python_v1_graveyard/ 2>/dev/null || true
mv core/classifier.py attic/python_v1_graveyard/ 2>/dev/null || true
mv core/platform_adapter.py attic/python_v1_graveyard/ 2>/dev/null || true
mv core/proc_scanner.py attic/python_v1_graveyard/ 2>/dev/null || true
mv core/cgroup_manager.py attic/python_v1_graveyard/ 2>/dev/null || true
mv engine attic/python_v1_graveyard/ 2>/dev/null || true

echo "[PHASE 0] Purge complete."
echo ""
echo "=== RUN THESE MANUALLY TO VERIFY ==="
cat << 'VERIFY_EOF'
grep -r "psutil" --include="*.py" core/ daemon/ || echo "✓ psutil: CLEAN"
grep -r "subtree_control" --include="*.py" core/ daemon/ || echo "✓ subtree_control: CLEAN"
grep -r "ThreadPoolExecutor" --include="*.py" core/ daemon/ || echo "✓ ThreadPoolExecutor: CLEAN"
VERIFY_EOF
