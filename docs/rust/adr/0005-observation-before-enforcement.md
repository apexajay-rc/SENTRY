# ADR 0005: Separate observation from enforcement

- Status: Accepted
- Date: 2026-11-07

## Decision

The workload observer is read-only. It discovers SENTRY-owned transient scopes,
resolves their cgroup paths from systemd, and reads available accounting and PSI
interfaces. It never writes to cgroupfs or changes unit properties.

Each cgroup file is represented as available, missing, or error. Missing files
must not be converted to zero-valued metrics. A later enforcement subsystem
will have a separate API and explicit ownership/recovery contract.

## Rationale

The same host may expose CPU accounting without exposing CPU enforcement, or
memory pressure without I/O accounting. SENTRY must report these distinctions
accurately before it is given authority to change resource allocation.
