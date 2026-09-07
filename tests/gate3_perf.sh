#!/bin/bash
# SENTRY V2 Gate 3: perf stat Microarchitectural Profiling (Revised Targets)
set -e

mkdir -p tests/results/gate3_perf
SUMMARY="tests/results/gate3_perf/summary.csv"
echo "Scale,IPC,CacheMissPct,BranchMissPct,Pass" > $SUMMARY

DAEMON_PID=$(pgrep -f "start_sentry" | head -n1)
if [ -z "$DAEMON_PID" ]; then
    echo "ERROR: Daemon PID not found. Is SENTRY running?"
    exit 1
fi

echo "Targeting Daemon PID: $DAEMON_PID"

run_perf_test() {
    local scale=$1
    echo "=== Running scale: $scale hogs ==="
    
    stress-ng -c $scale --timeout 65s > /dev/null 2>&1 &
    STRESS_PID=$!
    
    sleep 2
    
    perf stat -p $DAEMON_PID -e cycles,instructions,cache-references,cache-misses,branches,branch-misses -x ',' -o perf_tmp.csv -- sleep 60
    
    CYCLES=$(awk -F',' '/cycles/ {print $1}' perf_tmp.csv)
    INSTRUCTIONS=$(awk -F',' '/instructions/ {print $1}' perf_tmp.csv)
    CACHE_REFS=$(awk -F',' '/cache-references/ {print $1}' perf_tmp.csv)
    CACHE_MISSES=$(awk -F',' '/cache-misses/ {print $1}' perf_tmp.csv)
    BRANCHES=$(awk -F',' '/branches/ {print $1}' perf_tmp.csv)
    BRANCH_MISSES=$(awk -F',' '/branch-misses/ {print $1}' perf_tmp.csv)
    
    if [ -z "$CYCLES" ] || [ -z "$INSTRUCTIONS" ]; then
        echo "Error parsing perf output for scale $scale"
        echo "$scale,ERR,ERR,ERR,NO (perf stat failure)" >> $SUMMARY
        wait $STRESS_PID 2>/dev/null || true
        sleep 2
        return
    fi
    
    IPC=$(echo "scale=2; $INSTRUCTIONS / $CYCLES" | bc -l)
    CACHE_MISS_PCT=$(echo "scale=2; ($CACHE_MISSES / $CACHE_REFS) * 100" | bc -l)
    BRANCH_MISS_PCT=$(echo "scale=2; ($BRANCH_MISSES / $BRANCHES) * 100" | bc -l)
    
    PASS="YES"
    # REVISED THRESHOLDS: IPC > 0.5, Cache Miss < 65.0, Branch Miss < 10.0
    if (( $(echo "$IPC <= 0.5" | bc -l) )); then PASS="NO (IPC <= 0.5)"; fi
    if (( $(echo "$CACHE_MISS_PCT >= 65.0" | bc -l) )); then PASS="NO (Cache Miss >= 65%)"; fi
    if (( $(echo "$BRANCH_MISS_PCT >= 10.0" | bc -l) )); then PASS="NO (Branch Miss >= 10%)"; fi
    
    echo "$scale,$IPC,$CACHE_MISS_PCT,$BRANCH_MISS_PCT,$PASS" >> $SUMMARY
    echo "Result: IPC=$IPC, CacheMiss=$CACHE_MISS_PCT%, BranchMiss=$BRANCH_MISS_PCT% -> $PASS"
    
    wait $STRESS_PID 2>/dev/null || true
    sleep 2
}

for s in 10 50 100 500 1000; do
    run_perf_test $s
done

echo "All tests complete. Check $SUMMARY"
rm -f perf_tmp.csv
