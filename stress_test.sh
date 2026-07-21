#!/bin/bash
# SENTRY Stress Test Script
# Option 2: CPU Hog (stress-ng CPU workers)

echo "============================================"
echo "  SENTRY STRESS TEST - Option 2: CPU HOG"
echo "============================================"
echo ""
echo "This will spawn 4 CPU-intensive workers using stress-ng."
echo "They will consume 100% CPU on 4 cores for 60 seconds."
echo ""
echo "Expected SENTRY behavior:"
echo "  1. Daemon (daemon/main.py) should log: 'Throttling CPU hog PID: <PID>'"
echo "  2. TUI (tools/sentry_top.py) should show stress-ng workers in 'PENALTY BOX' with 20% CPU clamp"
echo ""
echo "Starting stress-ng in 3 seconds... (Ctrl+C to cancel)"
sleep 3

# Spawn 4 CPU workers for 60 seconds
stress-ng --cpu 4 --timeout 60s --metrics-brief

echo ""
echo "Stress test complete. SENTRY should have released the throttles after cooldown (~60s)."