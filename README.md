# SENTRY — System Pressure Monitoring & Control

SENTRY is a systems-level monitoring project that detects resource contention, classifies system pressure, and applies safe mitigation through Linux cgroups v2. It demonstrates practical approaches to real-time system observability and autonomous resource management.

The architecture follows a clean pipeline: **sense** → **analyze** → **decide** → **act**.

---

## Overview

SENTRY monitors CPU, memory, and I/O pressure in real time, computes a unified stress score, and applies corrective actions via cgroups-based resource throttling. The project is designed to preserve system responsiveness under load while maintaining safety and predictability.

**Key Design Principles:**
- No process termination (only resource constraints)
- Cgroups v2-based throttling (kernel-enforced limits)
- Cross-platform abstraction (Linux + Windows monitoring)
- Safe-by-design mitigation (reversible actions)

---

## Architecture

SENTRY is structured around four layers:

```
┌─────────────────────────────────────────┐
│  Dashboard (Flet UI)                    │  ← Visualization
├─────────────────────────────────────────┤
│  Policy Layer (classify_basic)          │  ← Decision logic
├─────────────────────────────────────────┤
│  Metrics Layer (compute_stress)         │  ← Analysis
├─────────────────────────────────────────┤
│  Platform Adapter (Linux / Windows)     │  ← Abstraction
└─────────────────────────────────────────┘
```

### Components

- **`core/platform_adapter.py`** — OS abstraction layer
  - Reads `/proc/stat`, `/proc/meminfo`, `/proc/diskstats` (Linux)
  - Reads WMI, Performance Counters (Windows)
  - Exports `PLATFORM` constant and metric functions

- **`core/metrics.py`** — Stress score computation
  - Normalizes CPU, memory, I/O into `[0, 1]` range
  - Weighted average stress calculation
  - Trend analysis (rising vs. stable)

- **`core/policy.py`** — Classification engine
  - Maps stress score to severity levels (LOW → MODERATE → HIGH → CRITICAL)
  - Configurable thresholds

- **`daemon/main.py`** — Autonomous agent
  - Monitors system state in control loop
  - Applies cgroups v2 limits on high pressure
  - Logs all actions for audit

- **`dashboard/main-gui.py`** — Real-time visualization
  - Stress sparkline graphs
  - Live metric display
  - Read-only (no control actions)

---

## Features

### Monitoring
- **CPU Usage** — parsed from `/proc/stat` (user + system time)
- **Memory Usage** — RSS + swap from `/proc/meminfo`
- **I/O Wait** — estimated from `/proc/diskstats` or performance counters
- **Top Process Identification** — current highest-load process

### Analysis
- **Unified Stress Score** — weighted combination of normalized metrics
- **Classification** — LOW, MODERATE, HIGH, CRITICAL
- **Trend Detection** — identifies rising vs. stable patterns (5-sample window)
- **Process-Level Scoring** — ranks processes by resource contribution

### Control (Daemon)
- **CPU Throttling** — via cgroups v2 `cpu.max`
- **Memory Limits** — via cgroups v2 `memory.max`
- **I/O Throttling** — via cgroups v2 `io.max`
- **Automatic Resume** — limits are time-bound and reversible
- **Cooldown Logic** — prevents thrashing on marginal workloads

### Visualization (Dashboard)
- **Stress Sparklines** — historical trend at a glance
- **Live Metrics** — CPU, memory, I/O, score, level
- **Process List** — current top consumers
- **Safe by Design** — read-only, no control capability

---

## Cross-Platform Design

SENTRY supports both Linux and Windows through a platform abstraction layer.

### Linux
- Primary target; full feature support
- Metrics from `/proc` filesystem
- Cgroups v2 for resource control
- Tested on Ubuntu 20.04+

### Windows
- Monitoring only (no cgroups equivalent)
- Metrics from WMI and Performance Counters
- Dashboard functional; daemon safe-disables control actions
- Suitable for development and observability

**Platform Detection:**
```python
from core.platform_adapter import PLATFORM

if PLATFORM == "Linux":
    # Apply cgroups limits
else:
    # Monitoring only
```

---

## Safety Model

SENTRY is designed to never make a system unresponsive:

1. **No Process Killing** — only resource constraints
2. **Time-Bounded Actions** — limits automatically expire
3. **Cooldown Windows** — prevents action churn
4. **Kernel Enforcement** — cgroups v2 provides hard limits
5. **Audit Logging** — all decisions logged to `sentry_log.txt`
6. **Safe Defaults** — conservative thresholds on first run

**Action Escalation:**
- MODERATE: 50% CPU cap, 80% memory soft limit
- HIGH: 30% CPU cap, 60% memory hard limit
- CRITICAL: 10% CPU cap, 40% memory hard limit (brief)

---

## Setup

### Requirements
- **Linux:** Ubuntu 20.04+ with cgroups v2 enabled
- **Windows:** Windows 10 Build 19041+
- **Python:** 3.8+
- **Dependencies:** `flet`, `psutil` (Linux/Windows metrics)

### Installation

```bash
git clone https://github.com/apexajay-rc/SENTRY.git
cd SENTRY

python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

---

## Running

### Dashboard (Monitoring Only)
```bash
cd dashboard
python main-gui.py
```

Displays real-time metrics and trends. Safe to run on any system.

### Daemon (Linux Only)
```bash
cd daemon
sudo python main.py  # Requires privileges for cgroups
```

Runs autonomously, logs actions to `sentry_log.txt`.

**Example Output:**
```
CPU=45% | MEM=62% | IO=3% | Stress=0.48 | Level=HIGH | Target=chrome(1234) | Action=cpu_throttled_to_50%
```

---

## Configuration

Edit values in `daemon/main.py`:

```python
COOLDOWN_SECONDS = 15        # Minimum time between actions
RESUME_SECONDS = 10          # Duration of limits
CRITICAL_PROCESSES = [...]   # Never throttle these
```

Thresholds in `core/policy.py`:

```python
THRESHOLDS = {
    "MODERATE": 0.50,
    "HIGH": 0.70,
    "CRITICAL": 0.85,
}
```

---

## Project Structure

```
SENTRY/
├── core/
│   ├── platform_adapter.py   # OS abstraction (CPU, memory, I/O)
│   ├── metrics.py            # Stress score computation
│   └── policy.py             # Classification logic
├── daemon/
│   └── main.py               # Control loop and actions
├── dashboard/
│   └── main-gui.py           # Flet UI
├── requirements.txt
└── README.md
```

---

## Roadmap

### Near-term
- [ ] PSI (Pressure Stall Information) integration for true contention signals
- [ ] Configuration file support (`.yaml`)
- [ ] Structured logging (JSON output)

### Medium-term
- [ ] Per-cgroup policy configuration
- [ ] Historical metrics database (InfluxDB/Prometheus export)
- [ ] Web dashboard (FastAPI + React)

### Long-term
- [ ] Machine learning-based workload classification
- [ ] Predictive throttling (before pressure peaks)
- [ ] Windows cgroups equivalent (Job Objects) support

---

## Limitations

- **Polling-based:** Uses 3-second sampling intervals (not event-driven)
- **Aggregate metrics:** Detects system-wide pressure, not per-application contention
- **Cgroups v2 required:** Limits features on older Linux kernels
- **Root access:** Daemon requires elevated privileges

---

## Testing

Run the dashboard on any platform to validate metric collection:

```bash
python dashboard/main-gui.py
```

On Linux, validate cgroups integration:

```bash
sudo python daemon/main.py &
watch cat sentry_log.txt
```

---

## Contributing

Issues and pull requests welcome. Please include:
- System details (kernel version, Python version)
- Reproduction steps
- Relevant log entries

---

## License

MIT License. See LICENSE file for details.

---

## References

- Linux cgroups v2: https://docs.kernel.org/admin-guide/cgroup-v2.html
- Pressure Stall Information (PSI): https://www.kernel.org/doc/html/latest/accounting/psi.html
- Flet Documentation: https://flet.dev/
