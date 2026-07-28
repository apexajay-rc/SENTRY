<div align="center">

<pre>
███████╗███████╗███╗   ██╗████████╗██████╗ ██╗   ██╗
██╔════╝██╔════╝████╗  ██║╚══██╔══╝██╔══██╗╚██╗ ██╔╝
███████╗█████╗  ██╔██╗ ██║   ██║   ██████╔╝ ╚████╔╝
╚════██║██╔══╝  ██║╚██╗██║   ██║   ██╔══██╗  ╚██╔╝
███████║███████╗██║ ╚████║   ██║   ██║  ██║   ██║
╚══════╝╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝
</pre>

<img src="assets/logo/sentry-meerkat.png" width="220" alt="SENTRY Meerkat">

# SENTRY

### Policy-Driven Linux Resource Arbitration for Interactive Workloads

**Observe • Evaluate • Protect • Recover**

<br>

<img src="https://img.shields.io/badge/Linux-cgroup_v2-black?logo=linux&logoColor=white">
<img src="https://img.shields.io/badge/Kernel-PSI-blue">
<img src="https://img.shields.io/badge/Enforcement-cgroup_v2-success">
<img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white">
<img src="https://img.shields.io/badge/License-MIT-green">
<img src="https://img.shields.io/badge/Status-Experimental-orange">

</div>

---

> **SENTRY** is a Linux userspace daemon that preserves desktop responsiveness during CPU and memory contention by combining **Linux Pressure Stall Information (PSI)**, **foreground workload awareness**, and **cgroup v2** resource controls. Instead of terminating processes, SENTRY applies **temporary, policy-driven resource constraints** to competing background workloads and automatically restores them when system pressure subsides.

---

## Why SENTRY?

Traditional Linux resource management answers one question:

> **Which process consumes the most resources?**

SENTRY answers a different one:

> **Which workload should remain responsive right now?**

Rather than relying solely on CPU utilization or reacting only after memory exhaustion, SENTRY continuously evaluates system pressure, active user context, and configurable policies before making resource arbitration decisions.

<div align="center">

| Traditional Resource Management | SENTRY |
|:-------------------------------:|:------:|
| Resource-centric | User-centric |
| Reactive | Proactive |
| Kill or terminate | Temporary resource constraints |
| CPU & memory usage | PSI + foreground awareness |
| Static behavior | Policy-driven arbitration |
| Emergency response | Continuous monitoring |

</div>

---

## Philosophy

SENTRY follows four principles that guide every design decision.

| Principle | Description |
|------------|-------------|
| **Observe** | Continuously monitor Linux PSI and desktop activity. |
| **Evaluate** | Combine kernel telemetry, foreground state, and policy rules before taking action. |
| **Protect** | Preserve the responsiveness of interactive workloads using reversible resource controls. |
| **Recover** | Automatically restore constrained workloads once resource pressure subsides. |

---

> [!NOTE]
>
> ### Why a Meerkat?
>
> In a meerkat colony, a sentry stands upright and continuously watches the surroundings while the rest of the colony works. It does not fight every threat—it observes, detects danger early, and alerts the colony when intervention is needed.
>
> SENTRY follows the same philosophy.
>
> Rather than reacting after the desktop becomes unresponsive, it continuously monitors Linux resource pressure, detects contention early, protects interactive workloads, and restores normal operation automatically.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Monitoring Dashboard](#monitoring-dashboard)
- [Security Model](#security-model)
- [Performance](#performance)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Why SENTRY?

Modern Linux systems are excellent at maximizing throughput, but throughput and responsiveness are not always the same thing.

During heavy CPU or memory contention, interactive applications such as browsers, IDEs, terminals, and video calls can become sluggish even though the system remains technically operational.

Traditional approaches typically react only after severe contention has already occurred by terminating processes, invoking the OOM Killer, or relying solely on scheduler heuristics.

SENTRY takes a different approach.

Instead of asking:

> *Which process is consuming the most resources?*

SENTRY asks:

> *Which workload should remain responsive right now?*

By continuously observing Linux Pressure Stall Information (PSI), identifying foreground workloads, and applying temporary policy-driven cgroup controls to competing background processes, SENTRY preserves desktop responsiveness without terminating applications.

When pressure subsides, all restrictions are automatically removed.

## Features

| Feature | Description |
|----------|-------------|
| **Linux PSI Monitoring** | Continuously observes CPU, memory, and I/O pressure using the Linux PSI interface. |
| **Foreground Awareness** | Detects the actively used desktop application and prioritizes its responsiveness. |
| **Policy Engine** | Makes enforcement decisions based on configurable resource policies instead of static thresholds. |
| **cgroup v2 Enforcement** | Applies temporary CPU and memory constraints to selected workloads. |
| **Automatic Recovery** | Restores constrained processes once resource pressure returns to normal. |
| **Decision Logging** | Records every policy decision for debugging and auditability. |
| **Desktop Integration** | Designed specifically for interactive Linux desktop environments. |
| **Safe-by-Default** | Uses reversible controls instead of forcefully terminating applications. |

## Architecture

```mermaid
flowchart TD

A[Linux Kernel PSI]
B[Desktop Bridge]
C[Policy Engine]
D[Resource Arbiter]
E[cgroup v2]
F[Decision Logger]

A --> C
B --> C
C --> D
D --> E
C --> F
```
### Linux PSI Monitor

Collects real-time CPU, memory, and I/O pressure metrics directly from the Linux kernel.

---

### Desktop Bridge

Determines which application currently owns user focus.

---

### Policy Engine

Combines kernel pressure, desktop state, cooldown timers, and administrator-defined policies to determine whether intervention is required.

---

### Resource Arbiter

Applies reversible cgroup v2 constraints to selected workloads.

---

### Decision Logger

Produces structured logs describing every observation and enforcement action.
