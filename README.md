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
# 🏗️ SENTRY

**SENTRY** is a **policy-driven Linux resource pressure management daemon** that continuously observes kernel-level resource contention, computes a unified system stress model from **utilization and Linux Pressure Stall Information (PSI)**, identifies dominant workload contributors, and applies deterministic mitigation policies through **cgroup-based resource controls**.

Rather than acting as a conventional monitoring application, SENTRY operates as a **closed-loop control system**: collect → classify → decide → mitigate → evaluate. Every subsystem is designed around deterministic state transitions, modular policy evaluation, and separation between observation, decision making, and enforcement.

---

# 🛠️ Key Architectural Pillars

* **Policy-Driven Decision Engine**

  * Resource mitigation is determined through configurable policy thresholds instead of hardcoded heuristics.
  * Escalation matrices translate stress classifications into deterministic resource limits.

* **Kernel-Native Telemetry**

  * Samples CPU, memory, I/O wait and Linux **Pressure Stall Information (PSI)** directly from `/proc`.
  * Avoids heavyweight external monitoring agents.

* **Deterministic Closed-Loop Feedback**

  * Observation, classification, mitigation and recovery are isolated into dedicated subsystems.
  * Active mitigations are tracked independently from effectiveness evaluation.

* **Modular Systems Architecture**

  * Collection, policy evaluation, IPC, daemon lifecycle, dashboard, feedback engine and enforcement remain loosely coupled.
  * Individual modules can evolve without introducing cross-component dependencies.

---

# 📊 Core Subsystems & Data Flow

```text
                           Linux Kernel
                                  │
               ┌──────────────────┴──────────────────┐
               │                                     │
          /proc/stat                         /proc/pressure/*
               │                                     │
               └──────────────┬──────────────────────┘
                              │
                    System Metrics Sampler
                              │
          CPU • Memory • I/O Wait • PSI Samples
                              │
                              ▼
                     Pressure Computation Engine
                              │
                Unified Stress Score Generation
                              │
                              ▼
                    Policy Classification Layer
                              │
      LOW → MODERATE → HIGH → CRITICAL State Machine
                              │
                              ▼
                    Process Ranking & Selection
                              │
                      Candidate Identification
                              │
                              ▼
                 Cgroup Resource Enforcement Layer
                              │
       CPU Weight • Memory Limits • IO Weight Controls
                              │
                 Action Tracking & Safety Guard
                              │
                Feedback / Resume Decision Engine
                              │
          ┌───────────────────┴────────────────────┐
          │                                        │
          ▼                                        ▼
     IPC Server                              Dashboard GUI
```

---

## Core Subsystems

### Metric Collection Layer

Responsible for collecting kernel telemetry.

Primary responsibilities include:

* Reading `/proc/stat`
* Reading `/proc/meminfo`
* Reading Linux PSI interfaces
* Computing utilization deltas
* Producing normalized metric samples

This layer intentionally performs **no policy decisions**.

---

### Pressure Engine

Transforms raw utilization into a normalized **Unified Stress Score**.

Inputs include:

* CPU utilization
* Memory utilization
* I/O wait
* PSI pressure

Outputs include:

* Utilization score
* PSI score
* Combined pressure score

This provides a single decision variable consumed by higher layers.

---

### Policy Engine

Maps stress scores into deterministic operating states.

Example progression:

```text
Stress Score
      │
      ▼
 LOW
      │
      ▼
MODERATE
      │
      ▼
 HIGH
      │
      ▼
CRITICAL
```

Each level maps directly to an escalation policy describing:

* CPU weight
* Memory limits
* IO weight

Policies are configuration-driven rather than embedded into business logic.

---

### Process Selection

Ranks candidate processes using weighted resource contribution.

The implementation evaluates CPU and resident memory before producing an ordered candidate list.

Protected processes can be excluded before enforcement.

---

### Enforcement Layer

Resource mitigation is delegated to dedicated cgroup management components.

Typical actions include:

* CPU throttling
* Memory restriction
* IO prioritization
* Automatic restoration after timeout

Importantly, enforcement logic remains separate from policy logic.

---

### Action Tracker

Maintains runtime state for every active mitigation.

Tracks:

* target PID
* mitigation type
* application timestamp
* previous pressure
* timeout expiration

The tracker deliberately **does not evaluate success**.

That responsibility belongs to the feedback subsystem.

---

### Feedback Engine

Completes the control loop.

Responsibilities include:

* monitoring mitigation outcomes
* determining recovery
* resuming previously throttled workloads
* preventing permanent resource restriction

---

### IPC Layer

Provides daemon ↔ client communication.

Responsibilities:

* daemon state queries
* mode switching
* observe-only mode
* armed/disarmed state
* dry-run operation

The IPC abstraction allows the dashboard to remain independent of the daemon implementation.

---

### Dashboard

The GUI serves as a visualization layer rather than a monitoring engine.

Displays:

* Unified Stress Score
* PSI values
* utilization metrics
* trend history
* top processes
* daemon state
* mitigation decisions

When the daemon is unavailable, the dashboard automatically falls back to local metric collection.

---

# Repository Layout

```text
SENTRY
├── core/
│   ├── metrics.py
│   ├── procfs.py
│   ├── process.py
│   ├── psi_sensor.py
│   ├── policy.py
│   ├── cgroup_manager.py
│   ├── action_tracker.py
│   ├── safety_guard.py
│   ├── ipc.py
│   └── config.py
│
├── engine/
│   ├── pressure.py
│   ├── classifier.py
│   ├── selector.py
│   ├── feedback.py
│   ├── reconciliation.py
│   └── timeseries.py
│
├── daemon/
│   ├── main.py
│   └── systemd_integration.py
│
├── dashboard/
│   └── main_gui.py
│
├── tests/
│
├── packaging/
│
├── tools/
│
├── Makefile
├── requirements.txt
└── sentry_config.yaml
```
# ⚙️ Internal Architecture & Execution Pipeline

SENTRY follows a **deterministic control-loop architecture**. Rather than reacting to isolated CPU spikes, the daemon continuously builds a holistic model of system pressure, evaluates policy rules, and applies reversible mitigation actions.

Every iteration of the daemon follows the same execution pipeline.

```text
 ┌───────────────────────────────────────────────────────────┐
 │                   Daemon Main Loop                        │
 └───────────────────────────────────────────────────────────┘
                    │
                    ▼
          Collect System Metrics
                    │
                    ▼
          Read Linux PSI Samples
                    │
                    ▼
      Compute Unified Stress Score
                    │
                    ▼
      Classify Current System State
                    │
                    ▼
        Analyze Historical Trend
                    │
                    ▼
      Rank Candidate Processes
                    │
                    ▼
        Evaluate Policy Rules
                    │
                    ▼
     Apply Resource Mitigation
                    │
                    ▼
      Record Active Action State
                    │
                    ▼
      Evaluate Previous Decisions
                    │
                    ▼
        Resume / Continue Limits
                    │
                    ▼
           Publish Daemon State
```

This architecture separates **observation**, **decision making**, **resource enforcement**, and **feedback** into independent execution stages.

---

# 📊 Unified Pressure Computation

Traditional monitoring systems typically evaluate CPU usage, memory usage, or I/O independently. SENTRY instead constructs a **Unified Stress Score** that fuses multiple kernel signals into a single normalized metric.

## Stage 1 — Utilization Sampling

Raw system utilization is collected from Linux kernel interfaces.

```text
CPU Usage
Memory Usage
I/O Wait
```

These metrics are sampled using delta-based calculations rather than instantaneous snapshots wherever applicable, reducing transient measurement noise.

---

## Stage 2 — Pressure Stall Information (PSI)

Linux PSI introduces information that conventional utilization metrics cannot capture.

Instead of asking:

> "How busy is the CPU?"

PSI answers:

> "How long are processes stalled because the CPU, memory, or storage subsystem cannot make forward progress?"

SENTRY incorporates PSI values including:

```text
CPU Pressure
Memory Pressure
I/O Pressure
```

This allows stress classification to account for **resource contention**, not merely utilization.

---

## Stage 3 — Weighted Fusion

Both utilization and PSI are normalized before being merged into a single pressure model.

Conceptually:

```text
          Utilization Score
                 │
                 ▼
        Weighted Aggregation
                 ▲
                 │
             PSI Score
                 │
                 ▼
        Unified Stress Score
```

The weighting coefficients are configurable through the runtime configuration rather than embedded into the implementation, allowing deployments to tune sensitivity for different workload classes.

---

# 🧠 Policy Classification Engine

The unified stress score feeds directly into the policy engine.

Instead of continuously scaling actions, SENTRY employs **discrete operating states**.

```text
0.00 ───────────────────────────────────────────────► 1.00

 LOW
      │
      ▼
 MODERATE
           │
           ▼
 HIGH
               │
               ▼
 CRITICAL
```

Each state corresponds to a deterministic policy.

| Level    | Typical Behavior                       |
| -------- | -------------------------------------- |
| LOW      | Observation only                       |
| MODERATE | Begin conservative mitigation          |
| HIGH     | Aggressive resource control            |
| CRITICAL | Maximum configured resource protection |

The thresholds are loaded from configuration, allowing administrators to adapt behavior without modifying source code.

---

# 📈 Trend Analysis

Stress classification is intentionally separated from trend analysis.

Two systems may both report **HIGH**, but their trajectories can differ:

```text
Machine A

LOW
LOW
MODERATE
HIGH
HIGH

Stable
```

versus

```text
Machine B

LOW
LOW
MODERATE
HIGH
CRITICAL

Rising
```

Trend analysis enables the decision engine to distinguish:

* stable workloads
* escalating pressure
* transient spikes
* insufficient historical data

This prevents isolated metric spikes from immediately triggering aggressive mitigation.

---

# 🎯 Process Selection Pipeline

After system-level classification, SENTRY identifies which workload contributes most significantly to current pressure.

The process sampler computes weighted per-process resource scores derived from:

```text
CPU Utilization
Memory Utilization
```

These values are combined into a ranking score.

```text
          Process A
              │
              ▼
          Score 74.1

          Process B
              │
              ▼
          Score 52.7

          Process C
              │
              ▼
          Score 18.4
```

Processes are then ordered from highest to lowest contribution.

Protected applications can be excluded before mitigation, preventing critical system services from becoming enforcement targets.

---

# 🔒 Resource Enforcement

SENTRY does not terminate workloads.

Instead, it applies **graduated resource controls** using Linux control groups.

The enforcement layer is responsible for translating policy decisions into operating-system primitives.

Typical mitigation actions include:

```text
CPU Weight Reduction

Memory Limit Adjustment

I/O Weight Reduction
```

Because enforcement is isolated from decision making, alternative enforcement backends can be introduced without modifying policy evaluation.

---

# 📝 Action Lifecycle

Every mitigation action becomes a tracked runtime object.

```text
Decision
     │
     ▼
Apply Limits
     │
     ▼
Record Metadata
     │
     ▼
Monitor Timeout
     │
     ▼
Resume Resources
```

Tracked metadata includes:

* process identifier
* mitigation type
* application timestamp
* previous stress level
* previous pressure state
* applied resource parameters

This explicit lifecycle prevents duplicate enforcement and enables deterministic recovery.

---

# 🛡️ Safety Guard

The safety subsystem exists to prevent unsafe or contradictory actions.

Its responsibilities include:

* preventing repeated throttling of the same workload
* avoiding duplicate enforcement
* validating policy decisions
* ensuring recovery conditions are satisfied
* protecting against inconsistent runtime state

This layer acts as a final validation stage before operating-system resources are modified.

---

# 🔄 Feedback & Reconciliation Engine

Mitigation is only one phase of the control loop.

After actions have been applied, SENTRY continuously evaluates whether:

* pressure has decreased
* mitigation remains necessary
* workloads should be restored
* previous actions should expire

Conceptually:

```text
Observe
    │
    ▼
Mitigate
    │
    ▼
Observe Again
    │
    ▼
Pressure Reduced?
      │
 ┌────┴────┐
 │         │
 ▼         ▼
Resume   Continue
```

Separating feedback from enforcement prevents policy logic from becoming tightly coupled to runtime bookkeeping.

---

# 🌐 IPC Architecture

The daemon exposes a lightweight IPC interface to decouple the monitoring backend from client applications.

```text
        Dashboard
             │
             │
     JSON Commands
             │
             ▼
      IPC Client Library
             │
             ▼
     Unix Socket / TCP
             │
             ▼
        IPC Server
             │
             ▼
       Daemon State
```

Supported interactions include:

* retrieving daemon state
* switching operational mode
* enabling or disabling mitigation
* observe-only mode
* dry-run mode
* health checks (ping)

Because IPC is isolated behind a dedicated abstraction, additional clients (CLI tools, REST gateways, exporters, or orchestration systems) can reuse the same communication protocol without interacting directly with daemon internals.

# ⚡ Technical Specifications

| Component               | Specification                                                    |
| ----------------------- | ---------------------------------------------------------------- |
| **Primary Language**    | Python 3.11+                                                     |
| **Target Platform**     | Linux (Primary), Windows (limited platform abstraction)          |
| **Architecture**        | Modular, Policy-Driven Daemon                                    |
| **Kernel Interfaces**   | `/proc/stat`, `/proc/meminfo`, `/proc/[pid]`, `/proc/pressure/*` |
| **Scheduling Model**    | Periodic Sampling Loop                                           |
| **Decision Model**      | Rule-Based State Machine                                         |
| **Stress Model**        | Unified Utilization + PSI Composite Score                        |
| **Resource Isolation**  | Linux cgroups                                                    |
| **IPC Transport**       | Unix Domain Socket (Linux), TCP Fallback                         |
| **Dashboard Framework** | Flet                                                             |
| **Configuration**       | YAML                                                             |
| **Packaging**           | systemd Service                                                  |
| **Testing**             | pytest with synthetic `/proc` fixtures                           |
| **Logging**             | Structured daemon logging                                        |
| **Deployment Target**   | Long-running background daemon                                   |

---

# 🧵 Concurrency Model

SENTRY intentionally adopts a conservative concurrency model.

```text
                    Main Daemon Thread
                           │
      ┌────────────────────┼────────────────────┐
      │                    │                    │
      ▼                    ▼                    ▼
 Metric Sampling     Policy Engine      Action Tracker
      │
      ▼
 State Update
      │
      ▼
 IPC Publication
```

Auxiliary components operate independently.

```text
Dashboard Thread
        │
        ▼
IPC Client Polling

──────────────

IPC Server
        │
        ▼
Per-client Worker Thread
```

This architecture minimizes shared mutable state while allowing responsive UI updates and concurrent IPC requests.

---

# 💾 Memory Characteristics

The daemon intentionally maintains a **small working set**.

Persistent runtime state consists primarily of:

* Recent stress history
* Active mitigation records
* Top process cache
* Runtime configuration
* IPC state

Large telemetry archives are deliberately avoided.

The implementation favors:

* **bounded history buffers**
* **streaming metric computation**
* **incremental sampling**
* **constant-size daemon state**

rather than retaining long-term in-memory datasets.

---

# 🔧 Runtime Dependencies

## Python Packages

```bash
pip install -r requirements.txt
```

Primary runtime components include:

* Flet (Dashboard)
* PyYAML
* pytest
* Standard Library networking
* dataclasses
* threading

Kernel telemetry is obtained directly from Linux rather than through heavyweight monitoring libraries.

---

# 📁 Configuration

Runtime behavior is configured through:

```text
sentry_config.yaml
```

Typical configuration groups include:

```text
Thresholds

Metric Weights

Escalation Matrix

Protected Processes

Sampling Interval

Observation Mode

Mitigation Parameters
```

Configuration-driven policy makes deployments reproducible without recompilation.

---

# 🚀 Getting Started

## Clone Repository

```bash
git clone https://github.com/<username>/SENTRY.git

cd SENTRY
```

---

## Create Virtual Environment

```bash
python3 -m venv .venv

source .venv/bin/activate
```

---

## Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Launch Dashboard

```bash
python dashboard/main_gui.py
```

---

## Start Daemon

```bash
python daemon/main.py
```

---

## Observe Only Mode

```bash
python daemon/main.py --observe
```

---

## Dry Run

```bash
python daemon/main.py --dry-run
```

No resource limits are enforced.

The complete decision pipeline remains active.

---

# ⚙️ Building with Make

The repository includes a dedicated Makefile for common development workflows.

Typical commands:

```bash
make install

make test

make lint

make run

make clean
```

---

# 🧪 Running Tests

Execute the complete validation suite.

```bash
pytest
```

Run with verbose output.

```bash
pytest -v
```

Run an individual subsystem.

```bash
pytest tests/test_pressure_engine.py
```

The project includes synthetic `/proc` fixtures to allow deterministic testing without depending on live kernel telemetry.

---

# 🖥️ Running as a systemd Service

The repository ships with a native service definition.

Install:

```bash
sudo cp packaging/sentry.service \
    /etc/systemd/system/
```

Reload:

```bash
sudo systemctl daemon-reload
```

Enable:

```bash
sudo systemctl enable sentry
```

Start:

```bash
sudo systemctl start sentry
```

Status:

```bash
systemctl status sentry
```

Logs:

```bash
journalctl -u sentry -f
```

Native `sd_notify` integration allows systemd to track:

* startup completion
* graceful shutdown
* watchdog heartbeats

---

# 📡 IPC Commands

The daemon exposes a lightweight JSON protocol.

Typical interactions include:

```text
get_state

ping

set_mode

set_armed

set_observe_only

set_dry_run
```

Example request:

```json
{
    "type": "get_state"
}
```

Example response:

```json
{
    "ok": true,
    "state": {
        "...": "..."
    }
}
```

This protocol intentionally remains small and stable to simplify integration with external tooling.

---

# 📊 Performance & Benchmarking

> **Note:** Populate the following values after executing reproducible benchmarks on the target hardware.

| Metric                 | Target  |
| ---------------------- | ------- |
| Sampling Interval      | 500 ms  |
| Daemon Startup Time    | < XX ms |
| IPC Round Trip         | < XX ms |
| Policy Evaluation      | < XX µs |
| Process Ranking        | < XX ms |
| Stress Computation     | < XX µs |
| Dashboard Refresh      | 2 s     |
| Idle CPU Usage         | < X %   |
| Idle Memory Footprint  | < XX MB |
| Concurrent IPC Clients | XX+     |
| Mitigation Latency     | < XX ms |

---

## Suggested Benchmark Suite

Measure the following independently.

```text
Metric Collection Latency

PSI Parsing Latency

Stress Score Computation

Policy Classification

Process Enumeration

cgroup Enforcement

IPC Round Trip Time

Dashboard Refresh Time

Memory Allocation Rate

CPU Overhead
```

A reproducible benchmark should report:

```text
Average

Median

p95

p99

Maximum

Standard Deviation
```

---

# 🔍 Observability

The daemon exposes several layers of runtime visibility.

```text
Kernel Metrics
        │
        ▼
Unified Stress Score
        │
        ▼
Stress Trend
        │
        ▼
Decision Engine
        │
        ▼
Mitigation Action
        │
        ▼
Action History
```

This progression enables operators to trace **why** an action occurred—not merely that it occurred.

---

# 🔒 Reliability Characteristics

The architecture emphasizes deterministic behavior under sustained load through:

* **Bounded in-memory state**
* **Configurable policy thresholds**
* **Thread-safe daemon state management**
* **Graceful mitigation rollback**
* **Platform abstraction layer**
* **Native systemd supervision**
* **Fallback dashboard telemetry when the daemon is unavailable**
* **Separation of observation, decision, enforcement, and feedback responsibilities**

These design choices reduce subsystem coupling and simplify reasoning about runtime behavior, testing, and future extensions.

---
# 🎯 Design Philosophy

SENTRY was designed around a simple systems engineering principle:

> **Protect overall system responsiveness instead of maximizing individual process throughput.**

Traditional monitoring systems terminate at observability—they report utilization and pressure but leave remediation to the operator. SENTRY extends beyond monitoring by implementing a **closed-loop resource management architecture** that continuously observes, reasons about, and acts upon kernel telemetry while maintaining deterministic behavior.

Several architectural principles guide the implementation.

### Separation of Responsibilities

Each subsystem owns a single responsibility.

```text
Kernel Telemetry
        │
        ▼
Metric Collection

        │
        ▼
Pressure Computation

        │
        ▼
Policy Classification

        │
        ▼
Process Selection

        │
        ▼
Resource Enforcement

        │
        ▼
Feedback Evaluation
```

This separation reduces coupling and allows individual components to evolve independently.

---

### Deterministic Decision Making

Policy decisions are intentionally **configuration-driven** rather than heuristic-heavy.

Given identical telemetry and configuration, the daemon should always produce identical mitigation decisions.

This makes behavior:

* reproducible
* testable
* explainable
* auditable

---

### Kernel-First Architecture

Rather than depending on third-party monitoring agents, SENTRY builds directly upon Linux kernel facilities.

Primary data sources include:

```text
/proc/stat

/proc/meminfo

/proc/[pid]

/proc/pressure/*
```

This minimizes runtime dependencies while leveraging interfaces maintained by the Linux kernel itself.

---

### Safety Before Aggression

Mitigation is deliberately conservative.

The daemon prioritizes:

* observation
* gradual escalation
* reversible actions
* automatic recovery

instead of immediately applying maximum resource restrictions.

This reduces the likelihood of destabilizing the system during transient workload spikes.

---

# 🗺️ Roadmap

The current architecture provides a strong foundation for several future extensions.

## Advanced Scheduling Policies

Potential additions include:

* Adaptive policy learning
* Workload-aware scheduling
* Priority inheritance
* Dynamic escalation based on workload class
* Application-specific mitigation profiles

---

## Richer Kernel Integration

Future Linux capabilities could include:

```text
eBPF

perf events

sched tracepoints

pressure event triggers

cgroup v2 event notifications
```

These would allow SENTRY to move from periodic sampling toward event-driven decision making.

---

## Distributed Observability

Possible future integrations include:

* Prometheus exporters
* OpenTelemetry metrics
* Grafana dashboards
* REST API
* gRPC control plane

This would enable centralized monitoring across multiple hosts.

---

## Machine Learning Assisted Policies

The current rule-based engine intentionally favors predictability.

Future research directions could explore:

* workload classification
* anomaly detection
* adaptive threshold tuning
* predictive pressure forecasting
* reinforcement-based mitigation policies

These capabilities should remain optional, preserving the deterministic policy engine as the default execution path.

---

## Cross-Platform Support

Although Linux remains the primary target, the platform abstraction layer provides a foundation for expanding support to additional operating systems where equivalent kernel telemetry and resource control primitives exist.

---

# 🤝 Contributing

Contributions should preserve the architectural principles of the project.

Before submitting changes, consider the following guidelines:

### Architectural Expectations

* Maintain strict separation between telemetry, policy, enforcement, and feedback.
* Avoid introducing unnecessary coupling across modules.
* Prefer composition over inheritance.
* Keep policy definitions configuration-driven.
* Preserve deterministic behavior.

---

### Code Quality

All new contributions should:

* include unit tests
* avoid unnecessary dependencies
* follow existing module organization
* document architectural decisions
* preserve backward compatibility where practical

---

### Pull Request Checklist

```text
□ Tests pass

□ New functionality documented

□ Configuration updated if required

□ Logging added where appropriate

□ No duplicated business logic

□ Module responsibilities remain isolated
```

---

# 📚 Documentation

The repository is organized to make architectural navigation straightforward.

| Directory    | Purpose                                                                              |
| ------------ | ------------------------------------------------------------------------------------ |
| `core/`      | Kernel interaction, metrics, IPC, policies, configuration, safety, cgroup management |
| `engine/`    | Pressure computation, classification, process selection, reconciliation, feedback    |
| `daemon/`    | Long-running control loop and service lifecycle                                      |
| `dashboard/` | Graphical monitoring interface                                                       |
| `model/`     | Shared data models and immutable state objects                                       |
| `tests/`     | Unit tests and synthetic `/proc` fixtures                                            |
| `packaging/` | systemd service definitions                                                          |
| `tools/`     | Auxiliary utilities and CLI helpers                                                  |

---

# 🔐 License

This project is distributed under the **MIT License**.

Refer to the `LICENSE` file for the complete license text.

---

# 📖 Citation

If SENTRY contributes to academic work, research prototypes, or engineering publications, consider citing the repository rather than individual modules so architectural changes remain reflected over time.

Example:

```text
SENTRY: Policy-Driven Resource Pressure Management
for Linux Systems

GitHub Repository:
https://github.com/<username>/SENTRY
```

---

# ✅ Project Status

| Capability                      | Status        |
| ------------------------------- | ------------- |
| Linux `/proc` Telemetry         | ✔ Implemented |
| Linux PSI Integration           | ✔ Implemented |
| Unified Stress Model            | ✔ Implemented |
| Policy Engine                   | ✔ Implemented |
| Process Ranking                 | ✔ Implemented |
| cgroup Resource Enforcement     | ✔ Implemented |
| Action Tracking                 | ✔ Implemented |
| Feedback Engine                 | ✔ Implemented |
| IPC Control Plane               | ✔ Implemented |
| Flet Dashboard                  | ✔ Implemented |
| systemd Integration             | ✔ Implemented |
| Automated Tests                 | ✔ Implemented |
| Windows Platform Abstraction    | ⚠ Partial     |
| Distributed Control Plane       | 🚧 Planned    |
| eBPF Integration                | 🚧 Future     |

---

# 📌 Closing Summary

SENTRY is a **policy-driven Linux resource pressure management system** that combines kernel-native telemetry, unified pressure modeling, deterministic policy evaluation, and cgroup-based resource enforcement into a cohesive closed-loop control architecture.

Unlike conventional monitoring tools that terminate at observation, SENTRY continuously progresses through **measurement → classification → decision → mitigation → feedback**, enabling automated resource management while preserving modularity, deterministic behavior, and operational transparency. Its architecture cleanly separates telemetry collection, pressure computation, policy evaluation, process selection, enforcement, and recovery, providing a maintainable foundation for future enhancements such as event-driven kernel instrumentation, distributed observability, and adaptive policy engines.








