//! Platform-independent SENTRY domain types.
//!
//! This crate deliberately contains no Linux syscalls, systemd integration,
//! policy enforcement, or third-party dependencies.

use std::ffi::OsString;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

/// Explicit intent supplied by the caller when a workload is launched.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkloadIntent {
    Background,
}

/// A command that the user explicitly asks SENTRY to group as a workload.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkloadRequest {
    pub display_name: Option<String>,
    pub intent: WorkloadIntent,
    pub command: Vec<OsString>,
}

impl WorkloadRequest {
    pub fn validate(&self) -> Result<(), String> {
        let Some(program) = self.command.first() else {
            return Err("workload command must not be empty".to_owned());
        };

        if program.is_empty() {
            return Err("workload executable must not be empty".to_owned());
        }

        if let Some(name) = self.display_name.as_deref() {
            if name.trim().is_empty() {
                return Err("workload name must not be empty".to_owned());
            }
            if name.chars().any(char::is_control) {
                return Err("workload name must not contain control characters".to_owned());
            }
        }

        Ok(())
    }

    pub fn executable_path(&self) -> PathBuf {
        PathBuf::from(self.command[0].as_os_str())
    }
}

/// Stable identity for one transient SENTRY-owned systemd scope.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct WorkloadId {
    unit_name: String,
}

impl WorkloadId {
    pub fn from_unit_name(unit_name: String) -> Result<Self, String> {
        let Some(stem) = unit_name
            .strip_prefix("sentry-")
            .and_then(|name| name.strip_suffix(".scope"))
        else {
            return Err("workload unit must be a SENTRY-owned .scope".to_owned());
        };
        if stem.is_empty()
            || unit_name.len() > 240
            || !stem.chars().all(|character| {
                character.is_ascii_lowercase() || character.is_ascii_digit() || character == '-'
            })
        {
            return Err("workload unit name is invalid or too long".to_owned());
        }
        Ok(Self { unit_name })
    }

    pub fn unit_name(&self) -> &str {
        &self.unit_name
    }
}

/// A timestamp helper kept in the domain crate so IDs are deterministic to test.
pub fn unix_timestamp_micros() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_micros())
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_empty_command() {
        let request = WorkloadRequest {
            display_name: None,
            intent: WorkloadIntent::Background,
            command: Vec::new(),
        };
        assert!(request.validate().is_err());
    }

    #[test]
    fn rejects_control_characters_in_name() {
        let request = WorkloadRequest {
            display_name: Some("build\njob".to_owned()),
            intent: WorkloadIntent::Background,
            command: vec![OsString::from("cargo")],
        };
        assert!(request.validate().is_err());
    }

    #[test]
    fn accepts_explicit_background_workload() {
        let request = WorkloadRequest {
            display_name: Some("rust build".to_owned()),
            intent: WorkloadIntent::Background,
            command: vec![OsString::from("cargo"), OsString::from("build")],
        };
        assert!(request.validate().is_ok());
    }

    #[test]
    fn validates_sentry_scope_identity() {
        let id = WorkloadId::from_unit_name("sentry-rust-build-123.scope".to_owned()).unwrap();
        assert_eq!(id.unit_name(), "sentry-rust-build-123.scope");
        assert!(WorkloadId::from_unit_name("user.slice".to_owned()).is_err());
    }
}
