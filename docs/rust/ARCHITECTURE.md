# Rust Rewrite: Architecture and Boundaries

## Current executable slice

```text
sentry CLI
  ├── doctor
  │    ├── inspect cgroup v2 control files
  │    ├── parse /proc/pressure/{cpu,memory,io}
  │    └── probe systemd-run and the systemd user manager
  │
  ├── run --background
  │    ├── require explicit workload intent
  │    ├── create a SENTRY-owned transient scope name
  │    └── invoke systemd-run --user --scope --slice=sentry-workloads.slice
  │         --property=CPUWeight=100 (neutral systemd default weight)
  │
  └── observe
       ├── discover running sentry-*.scope units in sentry-workloads.slice
       ├── resolve each unit ControlGroup through the user systemd manager
       └── read cgroup accounting, controller files and per-cgroup PSI
```

`run` creates a workload boundary and explicitly sets `CPUWeight=100`, systemd's neutral default relative weight. On the validated host this causes systemd to propagate the CPU controller into the SENTRY-owned subtree, exposing `cpu.weight` and `cpu.max` for observation and later controlled use. It does not impose a CPU quota or perform adaptive throttling. `observe` takes a one-shot, read-only snapshot. Neither command sets `MemoryHigh`, `IOWeight`, affinity, nice or OOM policy.

## Intended architecture (not yet implemented)

```text
Workload intent / CLI / application adapters
                  |
                  v
         Workload identity registry
                  |
                  v
         Pressure observation layer <---- Linux PSI + cgroup accounting
                  |
                  v
             Policy engine
                  |
                  v
         Bounded decision state machine
                  |
                  v
      Ownership-aware systemd actuator
                  |
                  v
           cgroup v2 controls
                  |
                  v
      Outcome measurement / feedback
                  |
                  v
      Intervention journal + recovery
```

## Workspace boundaries

- `sentry-core`: platform-independent domain types and invariants.
- `sentry-linux`: Linux observation, PSI parsing, cgroup inspection, systemd interaction and workload scope creation.
- `sentry-cli`: command-line interface and process exit-code handling.

The split is intentionally small. Do not create a crate for every module before a real reuse or isolation requirement exists.

## Workload identity

A workload is an explicitly created systemd scope, not an arbitrary PID. PIDs may be used for attribution, but policy and actuation must target a workload boundary with a known owner and lifecycle.

The initial CLI uses the invoking user's systemd manager. It does not use the system manager, require root or move processes between existing cgroups.

## Current status

Implemented:

- Explicit background intent in CLI.
- Transient user-scope launch under `sentry-workloads.slice`, with explicit baseline `CPUWeight=100` to activate CPU controller interfaces in the owned subtree.
- Workload unit naming and validation.
- Read-only PSI snapshot parser.
- Read-only cgroup v2 control-file inspection.
- Discovery of running SENTRY scopes in `sentry-workloads.slice`.
- Per-workload CPU accounting, memory events, optional I/O accounting and cgroup PSI snapshots.
- Explicit `Missing` and `Error` states for unavailable or unreadable cgroup interfaces.
- `sentry observe` one-shot workload reporting.
- systemd user-manager diagnostics.

Not implemented:

- Persistent daemon.
- Continuous cgroup workload telemetry or sampling deltas.
- PSI trigger file descriptors.
- Policy or adaptive control loop.
- Any resource-control actuator.
- Intervention journal or crash recovery.
- Automatic desktop focus detection.
- Container or VM integration.

## Safety boundary

No code in the current executable slice may write to cgroup control files or call systemd property-setting methods. Enforcement requires a separate accepted ADR, ownership journal, conflict detection and integration tests proving exact restoration.
