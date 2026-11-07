use sentry_core::{unix_timestamp_micros, WorkloadId, WorkloadRequest};
use std::path::Path;

/// Build a unique transient systemd scope identity for a SENTRY-owned workload.
pub fn create_workload_id(request: &WorkloadRequest) -> Result<WorkloadId, String> {
    request.validate()?;
    let executable_path = request.executable_path();
    let executable = executable_path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("workload");
    let source = request.display_name.as_deref().unwrap_or(executable);
    let slug = slugify(source);
    let unit_name = format!(
        "sentry-{slug}-{}-{}.scope",
        std::process::id(),
        unix_timestamp_micros()
    );
    WorkloadId::from_unit_name(unit_name)
}

pub fn slugify(value: &str) -> String {
    let mut slug = String::new();
    let mut previous_separator = false;

    for character in value.chars() {
        if slug.len() >= 40 {
            break;
        }
        if character.is_ascii_alphanumeric() {
            slug.push(character.to_ascii_lowercase());
            previous_separator = false;
        } else if !slug.is_empty() && !previous_separator {
            slug.push('-');
            previous_separator = true;
        }
    }

    let slug = slug.trim_matches('-');
    if slug.is_empty() {
        "workload".to_owned()
    } else {
        slug.to_owned()
    }
}

/// Return the binary name without requiring the argument to be UTF-8.
pub fn executable_name(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("workload")
        .to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use sentry_core::WorkloadIntent;
    use std::ffi::OsString;

    #[test]
    fn slugifies_human_names() {
        assert_eq!(slugify("Rust Build / Release"), "rust-build-release");
    }

    #[test]
    fn falls_back_for_empty_names() {
        assert_eq!(slugify(" -- "), "workload");
    }

    #[test]
    fn generated_id_is_sentry_scope() {
        let request = WorkloadRequest {
            display_name: Some("rust build".to_owned()),
            intent: WorkloadIntent::Background,
            command: vec![OsString::from("cargo"), OsString::from("build")],
        };
        let id = create_workload_id(&request).unwrap();
        assert!(id.unit_name().starts_with("sentry-rust-build-"));
        assert!(id.unit_name().ends_with(".scope"));
    }
}
