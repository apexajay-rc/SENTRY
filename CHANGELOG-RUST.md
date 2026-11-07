# Rust rewrite changelog

## Unreleased — Workload observation slice

- Place newly launched workloads in the dedicated `sentry-workloads.slice`.
- Set an explicit baseline `CPUWeight=100` on SENTRY scopes (systemd's default relative weight) so CPU controller interfaces are exposed in the owned subtree; no CPU quota or adaptive throttling is applied.
- Add read-only discovery of running SENTRY-owned scopes.
- Add cgroup CPU, memory, I/O and PSI snapshot parsing with explicit missing/error states.
- Add `sentry observe` for a one-shot workload snapshot.
- Add ADRs for the dedicated workload slice and observation/enforcement boundary.

## 0.1.0 — Initial workspace scaffold

- Added a three-crate Cargo workspace (`sentry-core`, `sentry-linux`, `sentry-cli`).
- Added explicit background workload grouping through transient systemd user scopes.
- Added read-only PSI parsing and cgroup v2 inspection.
- Added `sentry doctor` diagnostics.
- Added unit tests and Rust CI.
- Deliberately did not add resource enforcement, a privileged daemon, or automatic desktop focus detection.


## Unreleased — Reversible aggregate CPU-weight control (experimental)

- Added an operator-triggered `sentry.slice` CPUWeight actuator.
- Restricts experimental target weights to 20–100 and requires a 30–3600 second lease.
- Persists a private per-user runtime lease record and schedules expiry restoration through the systemd user manager.
- Verifies the dedicated SENTRY slice hierarchy, controller placement, and effective kernel `cpu.weight` before and after intervention.
- Preserves external changes: restoration only writes the baseline when the current kernel value still matches SENTRY's recorded target.
- Does not include automatic pressure policy, foreground detection, or daemon-driven adaptation.
