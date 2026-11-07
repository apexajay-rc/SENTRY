use sentry_core::WorkloadRequest;
use sentry_linux::workload::create_workload_id;
use std::process::Command;

const SENTRY_WORKLOADS_SLICE: &str = "sentry-workloads.slice";
const BASELINE_CPU_WEIGHT: u32 = 100;

/// Run an explicitly background workload inside a SENTRY-owned systemd user scope.
///
/// `CPUWeight=100` is systemd's default relative weight. Setting it explicitly
/// causes systemd to enable the CPU controller along the SENTRY workload
/// hierarchy, while imposing no CPU quota or adaptive throttling.
pub fn run(request: WorkloadRequest) -> Result<i32, String> {
    request.validate()?;
    let workload_id = create_workload_id(&request)?;
    let unit = workload_id.unit_name();
    eprintln!("SENTRY: launching background workload in {unit}");

    let status = build_systemd_run_command(&request, unit)
        .status()
        .map_err(|error| {
            format!(
                "failed to execute systemd-run: {error}; check that systemd-run is installed and the user manager is available"
            )
        })?;

    if let Some(code) = status.code() {
        Ok(code)
    } else {
        #[cfg(unix)]
        {
            use std::os::unix::process::ExitStatusExt;
            Ok(status.signal().map(|signal| 128 + signal).unwrap_or(1))
        }
        #[cfg(not(unix))]
        {
            Ok(1)
        }
    }
}

fn build_systemd_run_command(request: &WorkloadRequest, unit: &str) -> Command {
    let description = format!("SENTRY background workload ({unit})");
    let mut command = Command::new("systemd-run");
    command
        .arg("--user")
        .arg("--scope")
        .arg("--collect")
        .arg(format!("--slice={SENTRY_WORKLOADS_SLICE}"))
        .arg(format!("--property=CPUWeight={BASELINE_CPU_WEIGHT}"))
        .arg(format!("--unit={unit}"))
        .arg(format!("--description={description}"))
        .arg("--")
        .args(&request.command);
    command
}

#[cfg(test)]
mod tests {
    use super::*;
    use sentry_core::WorkloadIntent;
    use std::ffi::OsString;

    #[test]
    fn launch_sets_neutral_cpu_weight_in_sentry_slice() {
        let request = WorkloadRequest {
            display_name: Some("rust-build".to_owned()),
            intent: WorkloadIntent::Background,
            command: vec![
                OsString::from("cargo"),
                OsString::from("build"),
                OsString::from("--release"),
            ],
        };

        let command = build_systemd_run_command(&request, "sentry-rust-build.scope");
        let args: Vec<String> = command
            .get_args()
            .map(|argument| argument.to_string_lossy().into_owned())
            .collect();

        assert!(args.contains(&format!("--slice={SENTRY_WORKLOADS_SLICE}")));
        assert!(args.contains(&format!("--property=CPUWeight={BASELINE_CPU_WEIGHT}")));
        assert!(!args
            .iter()
            .any(|arg| arg.starts_with("--property=CPUQuota=")));
        assert!(!args
            .iter()
            .any(|arg| arg.starts_with("--property=MemoryHigh=")));

        let separator = args.iter().position(|arg| arg == "--").unwrap();
        let command_args: Vec<&str> = args[separator + 1..].iter().map(String::as_str).collect();
        assert_eq!(command_args, vec!["cargo", "build", "--release"]);
    }
}
