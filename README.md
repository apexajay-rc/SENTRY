# SENTRY ? System Stress Monitoring & Control

SENTRY is a Linux systems project that explores how resource pressure can be detected, visualized, and managed in real time.

It consists of two core components:
- **Dashboard** ? visualizes system state
- **Daemon** ? monitors and applies mitigation actions

---

## Features

### Monitoring
- **Delta-based CPU** from `/proc/stat` (instantaneous, not cumulative)
- **Delta-based I/O wait** from `/proc/stat`
- Memory usage from `/proc/meminfo` (`MemAvailable`-aware)
- **Per-process CPU** from `/proc/[pid]/stat` jiffies (replaces lifetime `ps %cpu`)
- Optional **Linux PSI** readings when `/proc/pressure/*` is available
- Unified stress score computation

### Analysis
- Shared `core/` modules for metrics, process sampling, and classification
- Stress classification:
  - LOW
  - MODERATE
  - HIGH
  - CRITICAL
- Trend detection (Rising / Stable)
- Top process identification via `/proc` sampling

### Control (Daemon)
- **cgroup v2 throttling** (`cpu.max`) ? reversible, no process killing
- Escalation via `core/policy.py` (MODERATE ? HIGH ? CRITICAL)
- Cooldown and protected-process handling
- Windows: monitoring only (control disabled)

### Visualization (Dashboard)
- Real-time UI using Flet
- Stress sparkline graph
- Decision suggestions
- Mode-based tuning (Gaming / Editing / Balanced)

---

## Architecture

```
SENTRY/
??? core/
?   ??? procfs.py      # /proc parsing (testable via SENTRY_PROC_ROOT)
?   ??? metrics.py     # SystemMetricsSampler + stress score
?   ??? process.py     # ProcessSampler (per-PID CPU/memory)
?   ??? classifier.py  # Levels, trends, decision hints
??? daemon/            # Autonomous mitigation loop
??? dashboard/         # Flet UI (read-only)
??? tests/             # Unit tests with mocked /proc fixtures
```

### Dashboard (`dashboard/`)
- UI layer
- Displays system metrics and trends
- Safe (no system modification)

### Daemon (`daemon/`)
- Background process
- Detects stress and applies mitigation
- Interacts with system processes

---

## Requirements

- Linux (Ubuntu recommended)
- Python 3.8+
- `/proc` filesystem access

---

## Setup

### 1. Clone the repository

    git clone https://github.com/apexajay-rc/SENTRY.git
    cd SENTRY

---

### 2. Create virtual environment

    python3 -m venv venv
    source venv/bin/activate

---

### 3. Install dependencies

    pip install -r requirements.txt

---

## How to Run

Run from the repository root:

### Run Dashboard

    python dashboard/main_gui.py

---

### Run Daemon

    python daemon/main.py

---

### Run Tests

    python -m unittest discover -s tests -v

Tests use mocked `/proc` fixtures. Override the proc root with `SENTRY_PROC_ROOT` for custom test harnesses.

---

## Example Output (Daemon)

    CPU=45% | MEM=62% | IO=3% | Stress=0.48 | Level=HIGH | Target=chrome(1234) | ProcessScore=38.5 | Action=cgroup throttle applied (PID 1234, cpu_weight=30) | PSI_CPU=12.3 | PSI_MEM=4.1 | PSI_IO=0.8

---

## Limitations

- Uses polling-based monitoring (not event-driven)
- PSI is read but not yet used in stress scoring or policy
- Process control is reactive
- Dashboard and daemon are not yet connected over IPC
- Some actions (pause/kill) may impact system stability if misused

---

## Future Work

- Weight PSI into stress score and mitigation policy
- Introduce cgroup-based resource control
- Connect dashboard ? daemon over a socket
- Add observe-only / dry-run defaults
- Add workload classification (foreground vs background)
- Benchmark suite vs systemd-oomd and earlyoom

---

## License

MIT License
