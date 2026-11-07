# ADR 0002: Workload identity is a SENTRY-owned systemd scope

- Status: Accepted
- Date: 2026-11-07

## Context

The previous implementation selected arbitrary PIDs but changed systemd-unit properties. Multiple PIDs can share one unit, and PID identity is reusable. This creates incorrect targeting and unsafe restoration risks.

## Decision

The initial product creates a transient systemd **user scope** for each explicitly designated background workload. That scope is the workload identity. PIDs are observations/attribution details only, not the policy or actuation identity.

## Consequences

- The initial CLI uses `systemd-run --user --scope`.
- The initial product does not control existing arbitrary services or system scopes.
- Containers and VMs are out of scope unless explicitly placed in a SENTRY-owned parent scope or integrated through their manager.
