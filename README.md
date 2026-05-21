# SENTRY — System Stress Monitoring & Control

SENTRY is a Linux systems project that explores how resource pressure can be detected, visualized, and managed in real time.

It consists of two core components:
- **Dashboard** → visualizes system state
- **Daemon** → monitors and applies mitigation actions

---

## Features

### Monitoring
- CPU usage tracking from `/proc/stat`
- Memory usage tracking from `/proc/meminfo`
- I/O wait estimation
- Unified stress score computation

### Analysis
- Stress classification:
  - LOW
  - MODERATE
  - HIGH
  - CRITICAL
- Trend detection (Rising / Stable)
- Top process identification

### Control (Daemon)
- Priority reduction (`renice`)
- Process pause/resume (`SIGSTOP` / `SIGCONT`)
- Process termination (`SIGTERM`)
- Cooldown and safety handling

### Visualization (Dashboard)
- Real-time UI using Flet
- Stress sparkline graph
- Decision suggestions
- Mode-based tuning (Gaming / Editing / Balanced)

---

## Architecture

SENTRY is structured into two components:

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

    git clone https://github.com/apexajay-rc/sentry.git
    cd sentry

---

### 2. Create virtual environment

    python3 -m venv venv
    source venv/bin/activate

---

### 3. Install dependencies

    pip install -r requirements.txt

---

## How to Run

### Run Dashboard

    cd dashboard
    python main-gui.py

---

### Run Daemon

    cd daemon
    python main.py

---

## Example Output (Daemon)

    CPU=45% | MEM=62% | IO=3% | Stress=0.48 | Level=HIGH | Target=chrome(1234) | Action=Priority reduced

---

## Limitations

- Uses polling-based monitoring (not event-driven)
- Relies on aggregate metrics (not true contention signals)
- Process control is reactive
- Some actions (pause/kill) may impact system stability if misused

---

## Future Work

- Replace polling with Linux PSI (Pressure Stall Information)
- Introduce cgroup-based resource control
- Add workload classification (foreground vs background)
- Improve decision accuracy with better signals

---

## License

MIT License
