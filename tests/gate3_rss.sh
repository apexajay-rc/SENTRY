#!/bin/bash
# SENTRY V2 Gate 3: 24-Hour Memory Stability
set -e

mkdir -p tests
mkdir -p tests/results/gate3_rss
RSS_LOG="tests/results/gate3_rss/rss_log.csv"
RESULT_TXT="tests/results/gate3_rss/result.txt"

DAEMON_PID=$(pgrep -f "start_sentry.py" | head -n1)
if [ -z "$DAEMON_PID" ]; then
    echo "ERROR: Daemon PID not found. Is SENTRY running?"
    exit 1
fi

echo "Timestamp,RSS_KB" > $RSS_LOG

echo "Starting synthetic mixed load (Steady + Ephemeral)..."
# Baseline: 10 steady hogs lasting 24 hours
stress-ng -c 10 --timeout 86400s > /dev/null 2>&1 &
STEADY_PID=$!

# Chaos: Ephemeral loop spawning and killing threads to test daemon caching
(
    while true; do
        stress-ng -c 50 --timeout 5s > /dev/null 2>&1
        sleep 10
    done
) &
EPH_PID=$!

cleanup() {
    echo "Cleaning up Gate 3 load generators..."
    kill $STEADY_PID $EPH_PID 2>/dev/null || true
    killall stress-ng 2>/dev/null || true
}
trap cleanup EXIT

echo "Monitoring SENTRY RSS for 24 hours (PID: $DAEMON_PID)..."

# Record Initial RSS
START_RSS=$(pmap -x $DAEMON_PID | tail -n 1 | awk '{print $3}')
echo "$(date +%s),$START_RSS" >> $RSS_LOG

# 24 hours = 86400 seconds. 300s (5m) intervals = 288 iterations
for i in $(seq 1 288); do
    sleep 300
    if ! kill -0 $DAEMON_PID 2>/dev/null; then
        echo "FAIL,Daemon crashed" > $RESULT_TXT
        exit 1
    fi
    CURRENT_RSS=$(pmap -x $DAEMON_PID | tail -n 1 | awk '{print $3}')
    echo "$(date +%s),$CURRENT_RSS" >> $RSS_LOG
done

# Analyze Delta
END_RSS=$(pmap -x $DAEMON_PID | tail -n 1 | awk '{print $3}')
DIFF_KB=$((END_RSS - START_RSS))
DIFF_MB=$(echo "scale=2; $DIFF_KB / 1024" | bc)

echo "Initial RSS: ${START_RSS} KB | Final RSS: ${END_RSS} KB | Growth: ${DIFF_MB} MB"

if (( $(echo "$DIFF_MB < 10.0" | bc -l) )); then
    echo "PASS,$DIFF_MB" > $RESULT_TXT
else
    echo "FAIL,$DIFF_MB" > $RESULT_TXT
fi

echo "24-Hour Test Complete. Result: $(cat $RESULT_TXT)"
