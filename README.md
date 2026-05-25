# SENTRY — System Pressure Monitoring & Control

> **Real-time resource pressure detection and safe mitigation for Linux systems.**  
> Autonomous daemon + observability dashboard. No process killing. Kernel-enforced limits via cgroups v2.

![SENTRY Overview](https://img.shields.io/badge/Linux-Primary-FCC624?logo=linux&logoColor=black) ![Python](https://img.shields.io/badge/Python-3.8+-3776ab?logo=python&logoColor=white) ![cgroups v2](https://img.shields.io/badge/cgroups-v2-FF6B6B) ![MIT License](https://img.shields.io/badge/License-MIT-green)

---

## 🎯 Why SENTRY?

Modern systems fail silently under resource pressure. Applications freeze. Responsiveness collapses. Logs fill with timeout errors. **SENTRY detects this before it happens.**

```
Without SENTRY:
  Chrome eats 95% CPU → System unresponsive → User loses work → OOM killer terminates random processes

With SENTRY:
  Chrome CPU spike detected → Pressure score rises → Limits applied → Chrome throttled to 40% → System stays responsive
```

**Real use case:** Development laptop with Kubernetes + IDE + browser = resource chaos. SENTRY keeps it usable.

---

## 🏗️ Architecture

The core loop runs every 3 seconds:

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   ┌─────────────┐    ┌──────────────┐    ┌──────────────┐  │
│   │   SENSE     │───▶│   ANALYZE    │───▶│   DECIDE     │  │
│   │             │    │              │    │              │  │
│   │ • CPU       │    │ • Score      │    │ • Classify   │  │
│   │ • Memory    │    │ • Trend      │    │ • Escalate   │  │
│   │ • I/O       │    │ • Top proc   │    │ • Cooldown   │  │
│   └─────────────┘    └──────────────┘    └──────────────┘  │
│                                                   │          │
│                                                   ▼          │
│   ┌──────────────────────────────────────────────────────┐  │
│   │              ACT (Cgroups v2)                        │  │
│   │  • CPU throttle (cpu.max)                            │  │
│   │  • Memory limit (memory.max)                         │  │
│   │  • I/O throttle (io.max)                             │  │
│   │  ✓ All reversible, time-bounded                      │  │
│   └──────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Layered Design

```python
┌─────────────────────────────────────────────────┐
│         Dashboard (Flet UI)                      │  🖥️  Read-only visualization
├─────────────────────────────────────────────────┤
│         Policy Layer (classify_basic)           │  🤖  Decision engine
├─────────────────────────────────────────────────┤
│         Metrics Layer (compute_stress)          │  📊  Stress score math
├─────────────────────────────────────────────────┤
│         Platform Adapter (Linux/Windows)        │  🔌  OS abstraction
├─────────────────────────────────────────────────┤
│         Kernel (cgroups v2, /proc)              │  🐧  System reality
└─────────────────────────────────────────────────┘
```

---

## ✨ Features at a Glance

| Feature | Details | Linux | Windows |
|---------|---------|-------|---------|
| **Metrics** | CPU, memory, I/O from kernel | ✅ `/proc/stat` | ✅ WMI |
| **Stress Score** | Unified [0, 1] metric | ✅ Real-time | ✅ Real-time |
| **Classification** | LOW → MODERATE → HIGH → CRITICAL | ✅ 4 levels | ✅ 4 levels |
| **Trend Detection** | Rising vs. stable (5-sample window) | ✅ | ✅ |
| **Top Process ID** | Which process is heaviest? | ✅ | ✅ |
| **CPU Throttling** | cgroups v2 `cpu.max` | ✅ Kernel-enforced | ❌ N/A |
| **Memory Limits** | cgroups v2 `memory.max` | ✅ Kernel-enforced | ❌ N/A |
| **I/O Throttling** | cgroups v2 `io.max` | ✅ Kernel-enforced | ❌ N/A |
| **Automatic Resume** | Time-bounded limits (10s default) | ✅ | ✅ |
| **Audit Logging** | JSON action log | ✅ | ✅ |
| **Dashboard UI** | Real-time graphs + sparklines | ✅ Flet | ✅ Flet |

---

## 🔒 Safety Model

SENTRY is **paranoid by design**. It will never:

- 🚫 Kill a process (only throttle)
- 🚫 Leave limits in place (10-second auto-reset)
- 🚫 Act repeatedly on the same threshold (15-second cooldown)
- 🚫 Throttle critical processes (systemd, Xorg, pipewire, etc.)
- 🚫 Control anything outside Linux (Windows = monitoring only)

**Action Escalation:**

```
Pressure Score → Level        → CPU Limit   → Memory Limit   → I/O Throttle
─────────────────────────────────────────────────────────────────────────
0.50 — 0.69  → MODERATE       → 50%         → Soft (warn)    → 50%
0.70 — 0.84  → HIGH           → 30%         → Hard (limit)   → 30%
0.85+        → CRITICAL       → 10%         → Hard + compact → 10%
```

All limits are **reversed automatically** after `RESUME_SECONDS` (default 10s).

---

## 📦 Installation

### Requirements

```
✓ Linux: Ubuntu 20.04+ (cgroups v2 enabled by default)
✓ Python: 3.8+
✓ Privileges: Root/sudo for cgroups (daemon only)
```

**Check cgroups v2:**
```bash
mount | grep cgroup2
# Output: cgroup2 on /sys/fs/cgroup type cgroup2 (...)
```

### Setup (5 minutes)

```bash
# 1. Clone
git clone https://github.com/apexajay-rc/SENTRY.git
cd SENTRY

# 2. Virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install
pip install -r requirements.txt
```

---

## 🚀 Running

### Dashboard (Safe — no privileges needed)

```bash
cd dashboard
python main-gui.py
```

**Output:** Real-time graphs, stress trends, top processes.  
**Safe on:** Any system (read-only monitoring).

---

### Daemon (Linux only — requires root)

```bash
cd daemon
sudo python main.py
```

**Output:** Control loop, applied actions, audit log.

```
[2026-05-25 14:23:45.123] CPU=45% | MEM=62% | IO=3% | Stress=0.48 | Level=HIGH | Target=chrome(1234) | Action=cpu_throttled_to_50%
[2026-05-25 14:23:48.456] CPU=32% | MEM=59% | IO=1% | Stress=0.38 | Level=MODERATE | Target=chrome(1234) | Action=limit_expired_resumed
```

**Logs saved to:** `sentry_log.txt`

---

## ⚙️ Configuration

### Daemon Behavior (`daemon/main.py`)

```python
COOLDOWN_SECONDS = 15        # Min time between actions on same PID
RESUME_SECONDS = 10          # Auto-reset limits after this duration
CRITICAL_PROCESSES = [       # Never throttle these
    "systemd",
    "gnome-shell",
    "Xorg",
    "pulseaudio",
    "pipewire",
    "python3",  # The daemon itself
    "ps"
]
```

### Stress Thresholds (`core/policy.py`)

```python
THRESHOLDS = {
    "LOW": 0.35,
    "MODERATE": 0.50,
    "HIGH": 0.70,
    "CRITICAL": 0.85,
}
```

Adjust for your workload:
- **Gaming rig:** Higher thresholds (0.80, 0.90)
- **Development laptop:** Conservative (0.40, 0.60)
- **Server:** Aggressive (0.30, 0.50)

---

## 📂 Project Structure

```
SENTRY/
├── core/
│   ├── platform_adapter.py   # 🔌 Linux (/proc) + Windows (WMI)
│   ├── metrics.py            # 📊 Stress score + normalization
│   └── policy.py             # 🤖 Classification logic
├── daemon/
│   └── main.py               # 🔄 Control loop + cgroups interface
├── dashboard/
│   └── main-gui.py           # 🖥️  Flet UI (graphs + metrics)
├── requirements.txt
├── sentry_log.txt            # 📝 Audit trail (auto-generated)
└── README.md
```

---

## 🔍 Observability

### Example: Stress Score Composition

```
CPU=45%  ──→  Normalize [0,1]  ──→  0.45
MEM=62%  ──→  Normalize [0,1]  ──→  0.62
IO=3%    ──→  Normalize [0,1]  ──→  0.03

Stress = (0.45 * 0.50) + (0.62 * 0.35) + (0.03 * 0.15) = 0.485
         └─ CPU weight ─┘  └─ MEM weight ─┘  └─ IO weight ┘

Score 0.485 → Level = MODERATE → Apply limits
```

Adjust weights in `core/metrics.py` for your hardware profile.

---

## 🛣️ Roadmap

### Q2 2026 (Near-term)
- [ ] **PSI Integration** — Replace polling with Linux Pressure Stall Information (`/proc/pressure/*`)
- [ ] **YAML Config** — External configuration file instead of hardcoded thresholds
- [ ] **JSON Logging** — Structured logs for ELK/Datadog integration

### Q3 2026 (Medium-term)
- [ ] **Per-Cgroup Policies** — Different limits for different workload types
- [ ] **Prometheus Export** — `/metrics` endpoint for monitoring stacks
- [ ] **Web Dashboard** — FastAPI + React (replace Flet)

### Q4 2026 (Long-term)
- [ ] **ML-Based Classification** — Predict pressure before it happens
- [ ] **Windows Job Objects** — Full control parity on Windows
- [ ] **Systemd Integration** — Native service unit + transient scopes

---

## ⚠️ Limitations & Tradeoffs

| Aspect | Current | Future |
|--------|---------|--------|
| **Signaling** | Polling every 3s | PSI (event-driven) |
| **Scope** | System-wide aggregate | Per-application, per-cgroup |
| **Control** | cgroups v2 throttling | + Predictive limits |
| **Platform** | Linux only (W10 read-only) | + Windows Job Objects |
| **Persistence** | Text logs | + Metrics DB (Prometheus) |

**When SENTRY isn't enough:**
- Need per-thread CPU affinity → Use `taskset`
- Need network rate limiting → Use `tc` (traffic control)
- Need memory swap tuning → Use `sysctl` directly

---

## 🧪 Testing

### Validate Metrics Collection

```bash
python dashboard/main-gui.py
```

Watch CPU, memory, I/O update in real-time across platforms.

### Stress Test the Daemon

```bash
# Terminal 1: Run daemon
cd daemon
sudo python main.py

# Terminal 2: Watch logs
watch tail -50 sentry_log.txt

# Terminal 3: Generate load
stress-ng --cpu 4 --vm 1 --vm-bytes 500M --timeout 60s
```

Expect to see:
1. Stress score rises
2. Level escalates to HIGH/CRITICAL
3. Actions logged (`cpu_throttled_to_30%`, etc.)
4. Process CPU% drops in logs
5. After 10s, limits auto-reset

---

## 🤝 Contributing

We welcome:
- 🐛 Bug reports (include `uname -a`, `python --version`, logs)
- ✨ Feature requests (with use cases)
- 🔧 PRs (follow existing style, add tests)

**Before opening an issue:**
```bash
python dashboard/main-gui.py  # Does it work?
sudo python daemon/main.py &  # Any errors?
cat sentry_log.txt            # What's logged?
```

---

## 📚 References

| Topic | Link |
|-------|------|
| cgroups v2 | https://docs.kernel.org/admin-guide/cgroup-v2.html |
| PSI (Pressure Stall Information) | https://www.kernel.org/doc/html/latest/accounting/psi.html |
| Flet UI Framework | https://flet.dev/ |
| Linux /proc | https://man7.org/linux/man-pages/man5/proc.5.html |
| cgroup Interfaces | https://www.man7.org/linux/man-pages/man7/cgroups.7.html |

---

## 📄 License

MIT License — Use, modify, distribute freely. See [LICENSE](LICENSE) for details.

---

## 💡 Inspiration & Context

Built during the era of:
- **Cloud-native complexity** — Kubernetes, containers, microservices
- **AI/ML resource hunger** — LLMs, model training, inference servers
- **Developer ergonomics** — Keeping laptops responsive under load
- **Kernel capabilities maturity** — cgroups v2 now stable across distributions

SENTRY is a response to: *"Why does my system freeze when I compile code + train ML models + stream video?"*

---

**Made by [apexajay-rc](https://github.com/apexajay-rc) · Questions? Open an [issue](https://github.com/apexajay-rc/SENTRY/issues).**
