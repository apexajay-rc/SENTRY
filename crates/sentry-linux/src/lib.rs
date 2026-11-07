//! Linux observation and integration primitives for SENTRY.
//!
//! Provides PSI/cgroup observation, explicit workload grouping, and a bounded,
//! explicitly leased aggregate CPU-weight actuator for the SENTRY user slice.

pub mod cgroup;
pub mod cpu_weight;
pub mod observer;
pub mod psi;
pub mod systemd;
pub mod workload;
