# SENTRY Engineering Constitution

## Product purpose

SENTRY is a Linux workload governor whose purpose is to preserve interactive responsiveness while explicitly designated background workloads continue making useful progress.

The product is judged by user-visible outcomes, not by the number of metrics collected or kernel interfaces used.

## Initial user and workflow

The first user is a Linux developer who runs resource-intensive builds or indexing jobs while continuing interactive work in an IDE, browser or communication application.

The first workflow is explicit workload grouping:

```bash
sentry run --background --name rust-build -- cargo build --release
```

SENTRY first proves that it can identify and observe a workload reliably. Enforcement follows only after ownership and restoration are correct.

## Success criteria

The initial hypothesis is accepted only if controlled experiments demonstrate all of the following:

1. Foreground application p95/p99 response latency improves under defined contention.
2. The background workload continues making progress.
3. Background completion-time degradation remains within an explicitly agreed budget (initial target: 10%).
4. Original resource settings are restored after the pressure condition ends.
5. No unrelated workload or manager-owned cgroup is modified.
6. Results are reproducible and compared with existing tools, particularly System76 Scheduler and uresourced where applicable.

The initial performance targets are hypotheses, not claims of achieved performance.

## Non-goals

SENTRY is not intended to become:

- An OOM killer or replacement for systemd-oomd.
- A CPU scheduler or sched_ext implementation.
- A laptop power/frequency manager.
- A generic process-name-to-priority rules engine.
- A container orchestrator or VM manager.
- A GPU resource manager.
- A machine-learning prediction platform.
- A host-wide cgroup migration daemon.

## Non-negotiable engineering principles

### Explicit ownership

SENTRY may modify only workloads whose resource-control ownership it can prove. In the first design, these are scopes that SENTRY created and labelled.

### Reversibility

Every intervention must record the exact property, previous value, applied value, owner and restoration state. The design must tolerate daemon crash, restart, workload exit and partial failure.

### No silent interference

SENTRY must not overwrite a property changed by another manager after SENTRY's intervention. Conflicts must be detected and surfaced.

### Measure pressure, not just utilisation

CPU, memory and I/O utilisation are not interchangeable with contention. Linux PSI and per-cgroup accounting are primary inputs, with availability and sampling quality made observable.

### Intent is explicit before it is inferred

The initial release uses explicit workload intent. Automatic desktop focus inference is not a prerequisite for validating the first product wedge.

### Fail safe

Missing PSI, missing controllers, unavailable systemd, permission errors or corrupt recovery state must disable enforcement rather than trigger guessed actions.

### Explain every action

Every intervention must expose the signal, decision, target workload, changed property, previous value, new value and restoration result.

### Earn complexity

Rust, eBPF, machine learning, desktop extensions and additional control loops are introduced only when a measured requirement justifies them.

## Language

The primary implementation language is Rust. The choice is based on memory safety, explicit ownership, reliable concurrency and maintainable Linux integration—not on an unproven claim that Python overhead is currently the bottleneck.

Use safe Rust by default. Any `unsafe` block requires a documented justification and focused tests.
