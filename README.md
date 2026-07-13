# SENTRY

**Context-Aware Kernel Resource Arbitration for Linux**

[![Linux](https://img.shields.io/badge/Linux-Kernel%20%E2%89%A5%205.x-FCC624?style=for-the-badge&logo=linux&logoColor=black)](https://kernel.org)
[![eBPF](https://img.shields.io/badge/eBPF-BCC-blue?style=for-the-badge)](https://github.com/iovisor/bcc)
[![cgroup v2](https://img.shields.io/badge/cgroup-v2-E74C3C?style=for-the-badge)](https://docs.kernel.org/admin-guide/cgroup-v2.html)
[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-2ECC71?style=for-the-badge)](#license)

---

## Overview

SENTRY is a Ring‑0‑adjacent resource arbitration system for Linux. It closes the gap between two data planes that conventional schedulers keep separate: **kernel-space CPU accounting**, observed via an eBPF probe attached directly to the scheduler's `sched_switch` tracepoint, and **user-space spatial context** — specifically, which process the user is actually looking at right now.

Standard CPU accounting (`top`, `ps`, cgroup CPU statistics) answers *how much* CPU time a process consumed. It cannot answer *whether that consumption should be tolerated*, because that judgment depends on information the kernel does not have: which window currently has focus. A compiler running at 100% CPU in the background is a non-issue. The same consumption pattern in the user's foreground application is the definition of a stutter.

SENTRY closes that loop:

1. An eBPF sensor (`core/bpf_sensor.py`) measures per-PID CPU consumption at the tracepoint level, independent of `/proc` polling intervals.
2. A desktop telemetry bridge (`tools/desktop_bridge.py`) resolves the actively focused window's PID across X11, XWayland, and native Wayland compositors (Hyprland, Sway/i3, KDE Wayland), and streams it to the daemon over a local UDP channel.
3. The daemon cross-references the two: processes exceeding the CPU threshold are throttled, *unless* they are the process currently in the user's foreground — in which case they are immune.
4. A curses-based TUI (`tools/sentry_top.py`) exposes both data planes — the current spatial lock and the set of throttled PIDs — by polling the daemon over a second local UDP channel.

---

## Core Architecture

### Pillar 1 — eBPF Kernel Sensor (`core/bpf_sensor.py`)

`BPFSensor` compiles and injects a small C program into the kernel via BCC, attaching to the `sched_switch` scheduler tracepoint:

```c
TRACEPOINT_PROBE(sched, sched_switch) {
    u32 prev_pid = args->prev_pid;
    u32 next_pid = args->next_pid;
    u64 ts = bpf_ktime_get_ns();
    // accumulate on-CPU time for the outgoing PID, reset the clock for the incoming PID
}
```

Two BPF hash maps live in kernel space:

| Map | Key | Value | Purpose |
|---|---|---|---|
| `start_time` | PID | timestamp (ns) | Tracks when a PID was last scheduled onto a CPU |
| `cpu_time` | PID | accumulated ns | Running total of on-CPU time between polling windows |

`get_top_hogs(threshold_ns)` reads `cpu_time`, returns every PID that accumulated more than the threshold within the current window (500ms default), and **clears the map**, implementing a sliding-window measurement rather than a monotonic counter. This runs entirely at the tracepoint level — there is no `/proc` polling in the hot path of consumption measurement.

### Pillar 2 — Universal Desktop Telemetry Bridge (`tools/desktop_bridge.py`)

`UniversalDesktopResolver` detects the active session type and compositor via `XDG_SESSION_TYPE` / `XDG_CURRENT_DESKTOP`, and dispatches to the correct backend to resolve the focused window's owning PID:

| Environment | Resolution method |
|---|---|
| Hyprland | `hyprctl activewindow -j` (native IPC) |
| Sway / i3 | `swaymsg -t get_tree`, depth-first search for the focused node |
| KDE Plasma (Wayland) | `kdotool`, with fallback to `xdotool` if unavailable |
| X11 / XWayland / EWMH-compliant desktops | `xdotool getactivewindow` → `getwindowpid` |

The bridge polls at a 300ms interval and transmits **only on a PID change** ("gaze shift"), emitting a single UDP datagram containing the raw PID to `127.0.0.1:50505`. This edge-triggered design keeps the telemetry channel idle during sustained focus on one window.

### Pillar 3 — Kernel Enforcement (`SafetyGuard` / `CgroupManager`)

The daemon consumes both signals to make an enforcement decision:

- **`SafetyGuard`** maintains the current spatial lock (`active_foreground_pid`), sourced from the UDP telemetry bridge. Any PID matching the current spatial lock is granted immunity from throttling regardless of measured CPU consumption.
- **`CgroupManager`** applies enforcement against non-immune PIDs that exceed the eBPF-measured threshold by writing a CPU cap into that process's cgroup v2 controller — referred to operationally as **the Penalty Box** — clamping the offending process to a fraction of a core rather than suspending or killing it. Enforcement is reversible: once a throttled PID's window expires, its cgroup limit is released.

### Pillar 4 — Command Center TUI (`tools/sentry_top.py`)

The daemon exposes its live state over a second UDP channel (`127.0.0.1:50506`). On receiving a `STATUS` datagram, it responds with a JSON snapshot:

```json
{
  "spatial_pid": 41213,
  "throttled_tasks": [
    { "pid": 8842, "time_left": 12.4 }
  ]
}
```

`sentry_top.py` renders this via `curses` at a 10 FPS refresh rate: the current spatial lock under **Pillar 1: Spatial Context**, and every actively throttled PID with time remaining under **The Penalty Box**. The TUI degrades gracefully to a `DAEMON OFFLINE` state if the daemon is unreachable, rather than blocking on the socket.

### Data Flow

```
                 ┌─────────────────────────┐
                 │   Linux Kernel Scheduler  │
                 │   (sched_switch trace)    │
                 └────────────┬─────────────┘
                              │ eBPF tracepoint probe
                              ▼
                 ┌─────────────────────────┐
                 │      BPFSensor            │
                 │  cpu_time / start_time    │
                 │      BPF hash maps        │
                 └────────────┬─────────────┘
                              │ get_top_hogs()
                              ▼
   UDP :50505      ┌─────────────────────────┐      UDP :50506
  ───────────────► │      SENTRY Daemon       │ ◄───────────────
  Desktop Bridge    │  SafetyGuard ⇄ CgroupMgr │      sentry_top
  (focused PID)     └────────────┬─────────────┘      (STATUS poll)
                              │
                              ▼
                    cgroup v2 CPU clamp
                    (Penalty Box, reversible)
```

---

## Prerequisites & Installation

### System Requirements

- Linux kernel with `CONFIG_BPF`, `CONFIG_BPF_SYSCALL`, and tracepoint support enabled
- Cgroups v2 unified hierarchy mounted at `/sys/fs/cgroup`
- Root privileges (or `CAP_SYS_ADMIN` / `CAP_BPF`) — required to load BPF programs into the kernel
- Python 3.8+

### eBPF Toolchain (BCC)

```bash
sudo apt-get update
sudo apt-get install -y python3-bpfcc linux-headers-$(uname -r) bpfcc-tools
```

Verify BCC can see kernel headers before proceeding:

```bash
sudo python3 -c "from bcc import BPF; print('BCC OK')"
```

### Desktop Bridge Dependencies

The telemetry bridge shells out to the compositor-appropriate query tool. Install what matches your session:

| Session | Package |
|---|---|
| X11 / XWayland | `xdotool` |
| KDE Plasma (Wayland) | `kdotool` |
| Hyprland | `hyprctl` (ships with Hyprland) |
| Sway / i3 | `sway` / `i3` (ships `swaymsg`) |

```bash
sudo apt-get install -y xdotool
```

### Python Dependencies

```bash
git clone https://github.com/apexajay-rc/SENTRY.git
cd SENTRY
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Deployment / Usage

SENTRY runs as three cooperating processes. The daemon must run as root (BPF program loading and cgroup writes both require elevated privileges); the bridge and TUI run in the user's session.

**1. Start the Ring‑0 enforcement daemon:**

```bash
sudo .venv/bin/python3 -m daemon.main
```

**2. Start the desktop telemetry bridge**, from within the target graphical session (not over SSH — it must have access to the compositor):

```bash
python3 tools/desktop_bridge.py
```

**3. Launch the command center TUI** to observe enforcement in real time:

```bash
python3 tools/sentry_top.py
```

Press `Q` to exit the TUI. Terminating the bridge or the TUI has no effect on active enforcement; only the daemon owns the enforcement state.

---

## Current Capabilities

- **Microsecond-resolution CPU accounting** via a kernel tracepoint probe, independent of `/proc` polling granularity.
- **Dynamic CPU throttling** of processes that exceed a configurable CPU-time threshold within a sliding measurement window, enforced through cgroup v2 (the Penalty Box).
- **Foreground immunity** — the process backing the currently focused window is exempt from throttling, resolved live across X11, XWayland, Hyprland, Sway/i3, and KDE Wayland.
- **Reversible enforcement** — throttled processes are released once their penalty window expires; no process is killed or suspended.
- **Zero-overhead spatial polling** — the desktop bridge transmits only on a focus change, not on a fixed interval, keeping idle CPU cost negligible.
- **Live observability** via a dedicated UDP status channel and curses TUI, decoupled from the enforcement path itself.

---

## Architectural Roadmap

The following represent the planned evolution of SENTRY's kernel-space enforcement surface. None of the items below are implemented in the current codebase; they are documented here as direction, not delivered capability.

### Near Term — PSI-Aware Memory Defense

- Subscribe to kernel **Pressure Stall Information** (`/proc/pressure/memory`) alongside the existing CPU tracepoint, giving SENTRY a second, independent signal for contention that CPU accounting alone cannot see.
- Extend `CgroupManager` to apply `memory.high` limits against non-immune memory consumers when a PSI stall trigger fires, mirroring the existing CPU Penalty Box mechanism for memory pressure.
- Blend PSI stall duration with eBPF CPU-time data into a single pressure score, rather than treating CPU and memory contention as independent triggers.

### Medium Term — IPC Dependency Graphing

- Attach eBPF probes to `connect`, `sendmsg`, and related syscalls to observe UNIX domain socket connections between processes.
- Build a live dependency graph from observed IPC edges, so that a backend process feeding data to the user's foreground application inherits transitive immunity from the spatial lock, rather than being throttled as an apparently unrelated background task.
- Extend `SafetyGuard` to walk this graph when evaluating immunity, instead of comparing only against the single `active_foreground_pid`.

### Long Term — Hardware Topology Manipulation

- Dynamic **core isolation**: reassign the foreground process's affinity to a reserved set of physical cores under sustained system-wide contention, insulating it from scheduler noise on shared cores.
- **L3 cache allocation** via Intel RDT / AMD QoS extensions (where available), to prevent throttled background processes from evicting the foreground process's working set from shared cache — a form of contention CPU-time accounting alone cannot detect or mitigate.
- Topology-aware placement that accounts for NUMA locality when assigning immunity-driven core reservations.

---

## License

MIT. See `LICENSE` for details.
