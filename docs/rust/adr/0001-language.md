# ADR 0001: Rust as the primary implementation language

- Status: Accepted
- Date: 2026-11-07

## Context

SENTRY is a long-running Linux userspace controller that will eventually coordinate systemd, cgroup v2, kernel pressure signals, IPC and recovery state. It may run with elevated privileges in later deployments.

## Decision

Use Rust as the primary implementation language. Prefer safe Rust and standard Linux interfaces. Keep the first workspace small and dependency-light.

## Rationale

The decision is based on memory safety, explicit ownership, concurrency control, deployability and maintainability. No claim is made that Python performance has been measured as a bottleneck in the previous implementation.

## Consequences

- The first release is a small Rust workspace.
- Existing Python implementations remain historical references.
- `unsafe` requires explicit justification and tests.
- eBPF and sched_ext work remain separate until an evidence-based requirement exists.
