# ADR 0004: Place managed workloads in a dedicated user slice

- Status: Accepted for the initial Linux implementation
- Date: 2026-11-07

## Context

A workload scope created under the default `app.slice` inherits resource-controller
availability and policy from a general-purpose desktop slice. SENTRY should not
modify that hierarchy or infer ownership over ordinary desktop applications.

The target workstation exposes a systemd user manager and cgroup v2. A manual
probes confirmed that `systemd-run --user --scope --slice=sentry-workloads.slice`
creates a scope under `sentry.slice/sentry-workloads.slice`. A transient
`CPUWeight=200` probe and a separate `CPUWeight=100` probe both caused the CPU
controller to be propagated to that workload hierarchy; the kernel exposed the
corresponding `cpu.weight` and `cpu.max` files.

## Decision

SENTRY-launched workloads are placed in `sentry-workloads.slice` using
`systemd-run --user --scope --slice=sentry-workloads.slice` and receive an
explicit `CPUWeight=100` baseline. This matches systemd's default relative
weight and is not a CPU quota. It prompts systemd to enable CPU controller
propagation for the SENTRY-owned workload hierarchy on the validated host.

The initial observer discovers only running `sentry-*.scope` units whose
reported `Slice` is exactly `sentry-workloads.slice`. It resolves each unit's
`ControlGroup` through systemd and reads cgroup files without writing to them.

## Consequences

- SENTRY has an explicit workload ownership boundary.
- Ordinary desktop application cgroups are not enumerated or controlled.
- Controller availability is evaluated per workload cgroup; it is not assumed
  from the root hierarchy. The baseline CPU weight is intended to make CPU
  control files available under the SENTRY slice, but the observer still checks
  the actual files rather than assuming their presence.
- CPU, memory and I/O interfaces may differ by host configuration. Missing
  interfaces are reported as unavailable, not as zero.
- The slice is a systemd user-manager construct. No root service is required
  for this initial workflow.
- This decision does not imply that SENTRY currently enforces resource limits.
