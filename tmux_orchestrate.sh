#!/bin/bash
# SENTRY Integration Test - 3-Pane tmux Orchestration
# Run this script in a terminal to set up the test environment

SESSION="sentry-test"

# Kill any existing session
tmux kill-session -t $SESSION 2>/dev/null

# Create new session with Pane 1 (Daemon - needs sudo)
tmux new-session -d -s $SESSION -n "DAEMON" "cd /home/maj-ajay/SENTRY && echo '=== PANE 1: SENTRY DAEMON (requires sudo) ===' && echo 'Starting in 3 seconds...' && sleep 3 && sudo .venv/bin/python daemon/main.py"

# Split horizontally for Pane 2 (TUI - user)
tmux split-window -h -t $SESSION:0 "cd /home/maj-ajay/SENTRY && echo '=== PANE 2: SENTRY TUI (user) ===' && echo 'Waiting for daemon...' && sleep 5 && .venv/bin/python tools/sentry_top.py"

# Split vertically for Pane 3 (Attacker)
tmux split-window -v -t $SESSION:0.0 "cd /home/maj-ajay/SENTRY && echo '=== PANE 3: ATTACKER (stress_test.sh Option 2) ===' && echo 'Waiting for daemon to start...' && sleep 7 && ./stress_test.sh <<< 2"

# Select pane 1 and attach
tmux select-pane -t $SESSION:0.0
tmux attach-session -t $SESSION