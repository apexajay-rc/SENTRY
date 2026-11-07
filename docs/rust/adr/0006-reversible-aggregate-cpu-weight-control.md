# ADR 0006: Reversible aggregate CPU-weight control

- Status: Experimental
- Decision: Use the systemd user manager to control the dedicated `sentry.slice` aggregate `CPUWeight`.

## Context

Three paired synthetic contention trials on an eight-logical-CPU workstation showed lower background cgroup CPU consumption and lower foreground P95/P99 wake-up latency when `sentry.slice` was assigned `CPUWeight=20` instead of 100. The measurements justify a bounded manual actuator, but do not justify automatic adaptation.

## Decision

The Rust CLI exposes an explicit `control cpu-weight set WEIGHT --lease DURATION` command. The first experimental bounds are CPUWeight 20–100 and lease duration 30–3600 seconds. The actuator:

1. Verifies the loaded `sentry.slice` systemd unit and its cgroup path.
2. Verifies `sentry-workloads.slice` is the direct child of `sentry.slice`.
3. Refuses to run if the invoking process is inside the controlled slice.
4. Records the effective kernel baseline in a private `$XDG_RUNTIME_DIR/sentry` state file.
5. Schedules a transient systemd user timer before applying the lower weight.
6. Applies `CPUWeight` using `systemctl --user set-property --runtime` and verifies `cpu.weight` in cgroup v2.
7. Restores only when the current kernel weight still equals SENTRY's recorded target. An external change is not overwritten.

The timer is independent of the original CLI process. This protects against that process exiting or crashing while the user systemd manager remains available. It is not a guarantee across user-manager shutdown, logout configurations that terminate the manager, or reboot.

## Restoration semantics

The actuator captures the *effective kernel weight*, not whether the systemd `CPUWeight` property was originally explicitly configured. If the original property was unset (systemd's default effective weight is 100), restoration sets the effective weight back to 100 using a runtime property. Thus scheduling behaviour is restored, but the property may become explicitly set.

## Non-goals

This is not a pressure-driven policy engine. It does not identify foreground applications, change individual workload weights automatically, set CPU quotas, or control memory/I/O. The synthetic benchmark is not evidence of equivalent gains in every real workload.
