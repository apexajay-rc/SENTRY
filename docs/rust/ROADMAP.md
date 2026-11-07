# Rust Rewrite Roadmap

## Phase 0 — Workload identity and observation

- Establish a reproducible Rust workspace and CI.
- Launch explicitly background workloads in SENTRY-owned transient user scopes.
- Inspect cgroup v2 and parse host PSI without changing system settings.
- Place SENTRY workloads under `sentry-workloads.slice`.
- Discover running SENTRY scopes and read their cgroup CPU, memory, I/O and PSI interfaces.
- Add a read-only `sentry observe` snapshot command.
- Add tests for naming, CLI argument preservation, PSI parsing and cgroup inspection.
- Document supported and unsupported environments.

Exit evidence: a user can build SENTRY, run `sentry doctor`, launch a harmless command in `sentry-workloads.slice`, and inspect its live cgroup snapshot with `sentry observe`.

## Phase 1 — Workload telemetry and thesis validation

- Add repeated sampling and CPU-use deltas for SENTRY-owned scopes.
- Add process identity snapshots (PID plus start time) within owned scopes.
- Add per-cgroup PSI where the kernel exposes it.
- Build a repeatable foreground/background benchmark.
- Compare unmanaged baseline and existing scheduling tools.

Exit evidence: reproducible pressure attribution and benchmark data; no resource enforcement yet unless the later safety design is accepted.

## Phase 2 — Reversible resource control

- Design an intervention journal and ownership protocol.
- Implement one CPU control property on SENTRY-owned scopes only.
- Detect third-party property changes and refuse conflicting restoration.
- Add crash/restart/partial-failure integration tests.

Exit evidence: exact restoration after normal exit, daemon crash, restart and conflict scenarios.

## Phase 3 — Adaptive policy

- Implement a small deterministic state machine with hysteresis.
- Add bounded graduated interventions.
- Measure outcome feedback and false interventions.

Exit evidence: measurable interactive latency improvement with an agreed background throughput penalty budget.

## Phase 4 — Integrations and ecosystem

- Evaluate desktop intent adapters only where benchmark evidence justifies them.
- Add distro packaging after stable service and recovery semantics.
- Collaborate with existing desktop and systemd projects rather than duplicating their responsibilities.

No phase is accepted because its feature list is complete; each phase requires its stated evidence.
