#!/bin/bash
# SENTRY Stress Test Suite
# Run this script to simulate different types of rogue workloads.

echo "============================================="
echo "  SENTRY v1.0 - Clinical Stress Test Suite   "
echo "============================================="

# Ensure stress-ng is installed
if ! command -v stress-ng &> /dev/null; then
    echo "Installing stress-ng (Industry standard Linux stress tool)..."
    sudo apt-get update && sudo apt-get install -y stress-ng
fi

echo ""
echo "Select a stress test to run:"
echo "1) The Memory Leaker (Tests PSI Sensor)"
echo "2) The Multi-Core Assault (Tests eBPF Ring Buffer Speed)"
echo "3) The Yo-Yo / Cooldown Test (Tests Reconciler)"
echo "4) Exit"
echo ""
read -p "Enter choice [1-4]: " choice

case $choice in
    1)
        echo "🔥 Starting Memory Leaker..."
        echo "-> This uses very little CPU but rapidly allocates RAM."
        echo "-> Watch SENTRY: The CPU sliding window will IGNORE this."
        echo "-> The PSI Sensor should detect 'memory some' pressure and trigger the mitigation."
        # Spawns 2 workers, allocating 80% of available RAM, holding it for 30s
        stress-ng --vm 2 --vm-bytes 80% --timeout 30s
        ;;
    2)
        echo "🔥 Starting Multi-Core Assault..."
        echo "-> This pins all your CPU cores to 100% simultaneously."
        echo "-> Watch SENTRY: The eBPF Ring Buffer will get flooded with thousands of sched_switch events."
        echo "-> The Aggregator must independently track and throttle multiple PIDs at once."
        # Spawns CPU workers equal to the number of cores you have
        stress-ng --cpu 0 --timeout 30s
        ;;
    3)
        echo "🔥 Starting Yo-Yo / Cooldown Test..."
        echo "-> This creates a CPU spike, sleeps, and spikes again."
        echo "-> Watch SENTRY: It should throttle the PID, then when the cooldown expires,"
        echo "   it should release the throttle, only to catch it again when it re-spikes."
        for i in {1..3}; do
            echo "   [Cycle $i] Spiking CPU for 5 seconds..."
            stress-ng --cpu 1 --timeout 5s &
            PID=$!
            wait $PID
            echo "   [Cycle $i] Resting for 15 seconds (waiting for SENTRY cooldown)..."
            sleep 15
        done
        ;;
    4)
        echo "Exiting."
        exit 0
        ;;
    *)
        echo "Invalid choice."
        ;;
esac

echo "✅ Test completed."
