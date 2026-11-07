# ADR 0003: No adaptive resource enforcement in the initial slice

- Status: Accepted
- Date: 2026-11-07

## Context

The previous implementation had inconsistent CPUWeight/CPUQuota/MemoryHigh semantics, incomplete restoration, uncertain ownership and an unsafe uninstaller. A new controller must not repeat those failure modes.

## Decision

The initial executable can inspect capabilities and group an explicitly background workload. The launcher sets `CPUWeight=100` on each SENTRY-owned scope. This is systemd's neutral default relative weight; it enables CPU controller interfaces within the SENTRY-owned subtree on the validated host, but does not impose an absolute CPU quota or adapt a workload's share. The initial executable must not change memory, I/O, affinity, nice or OOM settings, and must not dynamically alter CPU weight.

## Exit condition

Enforcement is considered only after the project has a workload identity model, an ownership journal, conflict detection and integration tests that prove exact restoration.
