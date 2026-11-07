//! Reversible aggregate CPU-weight control for SENTRY's dedicated user slice.
//!
//! The actuator changes only `sentry.slice`, verifies the kernel cgroup value,
//! and schedules restoration through the user's systemd manager. The timer is
//! independent of the invoking CLI process, so it survives that process exiting
//! or crashing while the user manager remains available.

use std::collections::HashMap;
use std::env;
use std::fs::{self, DirBuilder, OpenOptions};
use std::io::Write;
use std::os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt};
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

pub const MIN_CONTROL_WEIGHT: u32 = 20;
pub const MAX_CONTROL_WEIGHT: u32 = 100;
pub const MIN_LEASE_SECONDS: u64 = 30;
pub const MAX_LEASE_SECONDS: u64 = 3_600;

const SENTRY_SLICE: &str = "sentry.slice";
const WORKLOADS_SLICE: &str = "sentry-workloads.slice";
const STATE_DIRECTORY: &str = "sentry";
const STATE_FILE: &str = "cpu-weight-lease.state";
const STATE_VERSION: &str = "1";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CpuWeightStatus {
    pub effective_weight: u32,
    pub systemd_property: String,
    pub lease: Option<CpuWeightLease>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CpuWeightLease {
    pub baseline_weight: u32,
    pub target_weight: u32,
    pub lease_duration_seconds: u64,
    pub restoration_timer_state: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct LeaseState {
    token: String,
    baseline_weight: u32,
    target_weight: u32,
    lease_seconds: u64,
}

#[derive(Debug, Clone)]
struct OwnedSlice {
    cgroup_directory: PathBuf,
}

/// Read the effective kernel weight and any active SENTRY lease.
pub fn status() -> Result<CpuWeightStatus, String> {
    let slice = inspect_owned_slice()?;
    let effective_weight = read_effective_weight(&slice)?;
    let property = systemctl_show(SENTRY_SLICE, "CPUWeight")?;
    let lease = match read_state_optional()? {
        Some(state) => {
            let timer_unit = format!("{}.timer", timer_unit_base(&state.token));
            let timer_state = systemctl_show(&timer_unit, "ActiveState")
                .unwrap_or_else(|error| format!("unavailable ({error})"));
            Some(CpuWeightLease {
                baseline_weight: state.baseline_weight,
                target_weight: state.target_weight,
                lease_duration_seconds: state.lease_seconds,
                restoration_timer_state: timer_state,
            })
        }
        None => None,
    };

    Ok(CpuWeightStatus {
        effective_weight,
        systemd_property: property,
        lease,
    })
}

/// Apply a bounded aggregate CPU weight and schedule independent restoration.
pub fn set_with_lease(target_weight: u32, lease_seconds: u64) -> Result<(), String> {
    validate_target_weight(target_weight)?;
    validate_lease_seconds(lease_seconds)?;

    let slice = inspect_owned_slice()?;
    let baseline_weight = read_effective_weight(&slice)?;
    validate_target_below_baseline(target_weight, baseline_weight)?;
    let state_path = state_file_path(true)?;

    if state_path.exists() {
        return Err(format!(
            "an existing CPU-weight lease is recorded at {}; inspect it with `sentry control status` and restore it before starting another lease",
            state_path.display()
        ));
    }

    let token = new_token()?;
    let state = LeaseState {
        token: token.clone(),
        baseline_weight,
        target_weight,
        lease_seconds,
    };

    write_state_new(&state_path, &state)?;

    if let Err(error) = schedule_expiry(&state) {
        let _ = cancel_expiry(&state);
        let _ = fs::remove_file(&state_path);
        return Err(format!(
            "could not schedule independent lease restoration; CPU weight was not changed: {error}"
        ));
    }

    if let Err(error) = set_and_verify_weight(&slice, target_weight) {
        let rollback = set_and_verify_weight(&slice, baseline_weight);
        return match rollback {
            Ok(()) => {
                let _ = cancel_expiry(&state);
                let _ = fs::remove_file(&state_path);
                Err(format!(
                    "CPU-weight intervention failed and the baseline was restored: {error}"
                ))
            }
            Err(restore_error) => Err(format!(
                "CPU-weight intervention failed: {error}; immediate baseline restoration also failed: {restore_error}. The independent expiry timer and lease record were retained to attempt restoration again; inspect `sentry control status`"
            )),
        };
    }

    Ok(())
}

/// Restore an active lease. `expected_token` is supplied only by the expiry
/// timer; it prevents an old timer from restoring a newer intervention.
pub fn restore(expected_token: Option<&str>) -> Result<(), String> {
    let Some(state) = read_state_optional()? else {
        return if expected_token.is_some() {
            // A manual restore may have cancelled the timer just as it fired.
            Ok(())
        } else {
            Err("there is no active SENTRY CPU-weight lease to restore".to_owned())
        };
    };

    if let Some(token) = expected_token {
        if token != state.token {
            // A stale timer is harmless and must not touch a newer lease.
            return Ok(());
        }
    }

    let slice = inspect_owned_slice()?;
    let current_weight = read_effective_weight(&slice)?;

    if current_weight == state.baseline_weight {
        // Idempotent recovery: a previous restore may have applied the
        // baseline but failed while removing the state record.
        if expected_token.is_none() {
            let _ = cancel_expiry(&state);
        }
        remove_state_file()?;
        return Ok(());
    }

    if current_weight != state.target_weight {
        if expected_token.is_none() {
            let _ = cancel_expiry(&state);
        }
        remove_state_file()?;
        return Err(format!(
            "the current kernel CPU weight is {current_weight}, not this lease's target {} or baseline {}. SENTRY left the externally changed value untouched and cleared its lease record",
            state.target_weight, state.baseline_weight
        ));
    }

    set_and_verify_weight(&slice, state.baseline_weight)?;
    if expected_token.is_none() {
        // The baseline is verified. If a timer races and fires later, its
        // token check and missing state make it a harmless no-op.
        let _ = cancel_expiry(&state);
    }
    remove_state_file()?;
    Ok(())
}

fn validate_target_weight(weight: u32) -> Result<(), String> {
    if !(MIN_CONTROL_WEIGHT..=MAX_CONTROL_WEIGHT).contains(&weight) {
        return Err(format!(
            "CPUWeight must be between {MIN_CONTROL_WEIGHT} and {MAX_CONTROL_WEIGHT} for this experimental actuator"
        ));
    }
    Ok(())
}

fn validate_target_below_baseline(target: u32, baseline: u32) -> Result<(), String> {
    if target >= baseline {
        return Err(format!(
            "target CPU weight {target} must be lower than baseline {baseline}"
        ));
    }
    Ok(())
}

fn validate_lease_seconds(seconds: u64) -> Result<(), String> {
    if !(MIN_LEASE_SECONDS..=MAX_LEASE_SECONDS).contains(&seconds) {
        return Err(format!(
            "lease duration must be between {MIN_LEASE_SECONDS} and {MAX_LEASE_SECONDS} seconds"
        ));
    }
    Ok(())
}

fn inspect_owned_slice() -> Result<OwnedSlice, String> {
    let id = systemctl_show(SENTRY_SLICE, "Id")?;
    let load_state = systemctl_show(SENTRY_SLICE, "LoadState")?;
    let cgroup_path = systemctl_show(SENTRY_SLICE, "ControlGroup")?;

    if id != SENTRY_SLICE || load_state != "loaded" {
        return Err(format!(
            "refusing to control {SENTRY_SLICE}: systemd did not report the expected loaded slice (Id={id:?}, LoadState={load_state:?})"
        ));
    }

    validate_sentry_cgroup_path(&cgroup_path)?;
    ensure_controller_is_outside(&cgroup_path)?;

    let cgroup_directory = Path::new("/sys/fs/cgroup").join(cgroup_path.trim_start_matches('/'));
    if !cgroup_directory.is_dir() {
        return Err(format!(
            "the SENTRY cgroup directory does not exist: {}",
            cgroup_directory.display()
        ));
    }

    let controllers = fs::read_to_string(cgroup_directory.join("cgroup.controllers"))
        .map_err(|error| format!("cannot inspect SENTRY cgroup controllers: {error}"))?;
    if !controllers
        .split_whitespace()
        .any(|controller| controller == "cpu")
    {
        return Err("the CPU controller is not available in sentry.slice".to_owned());
    }

    let weight_path = cgroup_directory.join("cpu.weight");
    if !weight_path.is_file() {
        return Err(format!(
            "the kernel CPU-weight interface is missing: {}",
            weight_path.display()
        ));
    }

    // Confirm that SENTRY's workload grouping is a child of the aggregate
    // slice, rather than relying on a similarly named but unrelated cgroup.
    let child_id = systemctl_show(WORKLOADS_SLICE, "Id")?;
    let child_path = systemctl_show(WORKLOADS_SLICE, "ControlGroup")?;
    if child_id != WORKLOADS_SLICE || child_path != format!("{cgroup_path}/{WORKLOADS_SLICE}") {
        return Err(format!(
            "refusing to control {SENTRY_SLICE}: expected {WORKLOADS_SLICE} to be its direct child, got Id={child_id:?}, ControlGroup={child_path:?}"
        ));
    }

    Ok(OwnedSlice { cgroup_directory })
}

fn validate_sentry_cgroup_path(path: &str) -> Result<(), String> {
    let parsed = Path::new(path);
    let valid_components = parsed
        .components()
        .all(|component| matches!(component, Component::RootDir | Component::Normal(_)));

    if !parsed.is_absolute()
        || !valid_components
        || !path.starts_with("/user.slice/")
        || !path.ends_with("/sentry.slice")
        || path.contains("//")
    {
        return Err(format!(
            "refusing unexpected sentry.slice cgroup path: {path:?}"
        ));
    }
    Ok(())
}

fn ensure_controller_is_outside(sentry_cgroup_path: &str) -> Result<(), String> {
    let contents = fs::read_to_string("/proc/self/cgroup")
        .map_err(|error| format!("cannot determine SENTRY controller cgroup: {error}"))?;
    let current = contents
        .lines()
        .find_map(|line| line.strip_prefix("0::"))
        .ok_or_else(|| {
            "the current process is not visible in the unified cgroup hierarchy".to_owned()
        })?;
    let sentry_prefix = format!("{sentry_cgroup_path}/");

    if current == sentry_cgroup_path || current.starts_with(&sentry_prefix) {
        return Err(
            "refusing to modify sentry.slice from inside SENTRY's controlled cgroup; run the controller outside sentry.slice"
                .to_owned(),
        );
    }
    Ok(())
}

fn read_effective_weight(slice: &OwnedSlice) -> Result<u32, String> {
    let contents = fs::read_to_string(slice.cgroup_directory.join("cpu.weight"))
        .map_err(|error| format!("cannot read sentry.slice cpu.weight: {error}"))?;
    let weight = contents
        .trim()
        .parse::<u32>()
        .map_err(|error| format!("invalid kernel cpu.weight value {contents:?}: {error}"))?;
    if !(1..=10_000).contains(&weight) {
        return Err(format!("kernel reported out-of-range CPU weight {weight}"));
    }
    Ok(weight)
}

fn set_and_verify_weight(slice: &OwnedSlice, weight: u32) -> Result<(), String> {
    let assignment = format!("CPUWeight={weight}");
    let output = Command::new("systemctl")
        .args(["--user", "set-property", "--runtime", SENTRY_SLICE])
        .arg(&assignment)
        .output()
        .map_err(|error| format!("failed to execute systemctl set-property: {error}"))?;
    ensure_success("systemctl --user set-property", &output)?;

    let actual = read_effective_weight(slice)?;
    if actual != weight {
        return Err(format!(
            "systemd accepted CPUWeight={weight}, but the kernel reports cpu.weight={actual}"
        ));
    }
    Ok(())
}

fn schedule_expiry(state: &LeaseState) -> Result<(), String> {
    let executable = env::current_exe()
        .map_err(|error| format!("cannot resolve the current SENTRY executable: {error}"))?;
    let unit_base = timer_unit_base(&state.token);
    let on_active = format!("--on-active={}s", state.lease_seconds);
    let unit = format!("--unit={unit_base}");

    let runtime_directory = env::var("XDG_RUNTIME_DIR")
        .map_err(|error| format!("XDG_RUNTIME_DIR is unavailable for the lease timer: {error}"))?;
    let runtime_environment = format!("--setenv=XDG_RUNTIME_DIR={runtime_directory}");
    let path_environment = "--setenv=PATH=/usr/bin:/bin";
    let output = Command::new("systemd-run")
        .arg("--user")
        .arg(&on_active)
        .arg(&unit)
        .arg("--quiet")
        .arg("--timer-property=AccuracySec=1s")
        .arg(&runtime_environment)
        .arg(path_environment)
        .arg(executable)
        .args(["control", "cpu-weight", "restore", "--lease-token"])
        .arg(&state.token)
        .output()
        .map_err(|error| format!("failed to execute systemd-run for lease expiry: {error}"))?;
    ensure_success("systemd-run lease timer", &output)?;

    let timer_unit = format!("{}.timer", unit_base);
    let active_state = systemctl_show(&timer_unit, "ActiveState")?;
    if active_state != "active" {
        return Err(format!(
            "systemd-run returned success, but the expiry timer {timer_unit} is {active_state:?} rather than active"
        ));
    }
    Ok(())
}

fn cancel_expiry(state: &LeaseState) -> Result<(), String> {
    let unit_base = timer_unit_base(&state.token);
    // Stop the timer first so it cannot start a new restore service while we
    // are cancelling an expiry that may already have been triggered.
    for unit in [format!("{unit_base}.timer"), format!("{unit_base}.service")] {
        let load_state = systemctl_show(&unit, "LoadState")?;
        if load_state == "loaded" {
            let output = Command::new("systemctl")
                .arg("--user")
                .arg("stop")
                .arg(&unit)
                .output()
                .map_err(|error| format!("cannot stop lease unit {unit}: {error}"))?;
            ensure_success("systemctl stop lease unit", &output)?;
        }
    }
    Ok(())
}

fn timer_unit_base(token: &str) -> String {
    format!("sentry-cpu-weight-lease-{token}")
}

fn systemctl_show(unit: &str, property: &str) -> Result<String, String> {
    let property_arg = format!("--property={property}");
    let output = Command::new("systemctl")
        .arg("--user")
        .arg("show")
        .arg(&property_arg)
        .arg("--value")
        .arg(unit)
        .output()
        .map_err(|error| format!("failed to execute systemctl show for {unit}: {error}"))?;
    ensure_success("systemctl --user show", &output)?;
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn ensure_success(command: &str, output: &Output) -> Result<(), String> {
    if output.status.success() {
        return Ok(());
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    let detail = if !stderr.is_empty() {
        stderr
    } else if !stdout.is_empty() {
        stdout
    } else {
        output.status.to_string()
    };
    Err(format!("{command} failed: {detail}"))
}

fn state_file_path(create_directory: bool) -> Result<PathBuf, String> {
    let runtime = env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .ok_or_else(|| {
            "XDG_RUNTIME_DIR is not set; cannot store a safe runtime lease record".to_owned()
        })?;
    if !runtime.is_absolute() {
        return Err("XDG_RUNTIME_DIR must be an absolute path".to_owned());
    }

    let uid = effective_uid()?;
    verify_private_directory(&runtime, uid, "XDG_RUNTIME_DIR")?;

    let state_directory = runtime.join(STATE_DIRECTORY);
    match fs::symlink_metadata(&state_directory) {
        Ok(_) => verify_private_directory(&state_directory, uid, "SENTRY runtime state directory")?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound && create_directory => {
            DirBuilder::new()
                .mode(0o700)
                .create(&state_directory)
                .map_err(|create_error| {
                    format!(
                        "cannot create SENTRY runtime state directory {}: {create_error}",
                        state_directory.display()
                    )
                })?;
            verify_private_directory(&state_directory, uid, "SENTRY runtime state directory")?;
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(state_directory.join(STATE_FILE));
        }
        Err(error) => {
            return Err(format!(
                "cannot inspect SENTRY runtime state directory: {error}"
            ));
        }
    }

    Ok(state_directory.join(STATE_FILE))
}

fn verify_private_directory(path: &Path, expected_uid: u32, label: &str) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("cannot inspect {label} {}: {error}", path.display()))?;
    if metadata.file_type().is_symlink()
        || !metadata.is_dir()
        || metadata.uid() != expected_uid
        || metadata.mode() & 0o077 != 0
    {
        return Err(format!(
            "refusing unsafe {label} {} (expected an owned directory with mode 0700 or stricter)",
            path.display()
        ));
    }
    Ok(())
}

fn effective_uid() -> Result<u32, String> {
    let status = fs::read_to_string("/proc/self/status")
        .map_err(|error| format!("cannot determine effective UID: {error}"))?;
    let uid_line = status
        .lines()
        .find(|line| line.starts_with("Uid:"))
        .ok_or_else(|| "Uid entry is missing from /proc/self/status".to_owned())?;
    uid_line
        .split_whitespace()
        .nth(1)
        .ok_or_else(|| "effective UID is missing from /proc/self/status".to_owned())?
        .parse::<u32>()
        .map_err(|error| format!("invalid effective UID: {error}"))
}

fn write_state_new(path: &Path, state: &LeaseState) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                format!(
                    "an active lease record already exists at {}",
                    path.display()
                )
            } else {
                format!("cannot create lease record {}: {error}", path.display())
            }
        })?;

    let contents = encode_state(state);
    if let Err(error) = file
        .write_all(contents.as_bytes())
        .and_then(|()| file.sync_all())
    {
        drop(file);
        let _ = fs::remove_file(path);
        return Err(format!("cannot persist CPU-weight lease record: {error}"));
    }
    Ok(())
}

fn read_state_optional() -> Result<Option<LeaseState>, String> {
    let path = state_file_path(false)?;
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("cannot inspect CPU-weight lease record: {error}")),
    };

    let uid = effective_uid()?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.uid() != uid
        || metadata.mode() & 0o077 != 0
    {
        return Err(format!(
            "refusing unsafe CPU-weight lease record at {}",
            path.display()
        ));
    }

    let contents = fs::read_to_string(&path)
        .map_err(|error| format!("cannot read CPU-weight lease record: {error}"))?;
    decode_state(&contents).map(Some)
}

fn remove_state_file() -> Result<(), String> {
    let path = state_file_path(false)?;
    match fs::remove_file(&path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!("cannot remove CPU-weight lease record: {error}")),
    }
}

fn new_token() -> Result<String, String> {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("system clock is before the Unix epoch: {error}"))?
        .as_nanos();
    Ok(format!("{}-{nanos}", std::process::id()))
}

fn encode_state(state: &LeaseState) -> String {
    format!(
        "version={STATE_VERSION}\ntoken={}\nbaseline_weight={}\ntarget_weight={}\nlease_seconds={}\n",
        state.token, state.baseline_weight, state.target_weight, state.lease_seconds
    )
}

fn decode_state(contents: &str) -> Result<LeaseState, String> {
    let mut fields = HashMap::new();
    for line in contents.lines() {
        let (key, value) = line
            .split_once('=')
            .ok_or_else(|| format!("malformed CPU-weight lease record line: {line:?}"))?;
        if fields.insert(key, value).is_some() {
            return Err(format!("duplicate field in CPU-weight lease record: {key}"));
        }
    }

    if fields.len() != 5 || fields.get("version") != Some(&STATE_VERSION) {
        return Err("unsupported or incomplete CPU-weight lease record".to_owned());
    }

    let token = fields
        .get("token")
        .ok_or_else(|| "lease token is missing".to_owned())?
        .to_string();
    if token.is_empty()
        || !token
            .bytes()
            .all(|byte| byte.is_ascii_digit() || byte == b'-')
    {
        return Err("lease token contains invalid characters".to_owned());
    }
    let baseline_weight = parse_u32_field(&fields, "baseline_weight")?;
    let target_weight = parse_u32_field(&fields, "target_weight")?;
    let lease_seconds = fields
        .get("lease_seconds")
        .ok_or_else(|| "lease duration is missing".to_owned())?
        .parse::<u64>()
        .map_err(|error| format!("invalid lease duration: {error}"))?;

    if !(1..=10_000).contains(&baseline_weight) {
        return Err("baseline CPU weight is outside the kernel's valid range".to_owned());
    }
    validate_target_weight(target_weight)?;
    validate_target_below_baseline(target_weight, baseline_weight)?;
    validate_lease_seconds(lease_seconds)?;

    Ok(LeaseState {
        token,
        baseline_weight,
        target_weight,
        lease_seconds,
    })
}

fn parse_u32_field(fields: &HashMap<&str, &str>, key: &str) -> Result<u32, String> {
    fields
        .get(key)
        .ok_or_else(|| format!("{key} is missing"))?
        .parse::<u32>()
        .map_err(|error| format!("invalid {key}: {error}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn example_state() -> LeaseState {
        LeaseState {
            token: "1234-567890".to_owned(),
            baseline_weight: 100,
            target_weight: 20,
            lease_seconds: 60,
        }
    }

    #[test]
    fn lease_state_round_trips() {
        let state = example_state();
        assert_eq!(decode_state(&encode_state(&state)).unwrap(), state);
    }

    #[test]
    fn rejects_duplicate_lease_state_fields() {
        let contents = format!("{}token=2\n", encode_state(&example_state()));
        assert!(decode_state(&contents).unwrap_err().contains("duplicate"));
    }

    #[test]
    fn rejects_unsafe_lease_token() {
        let contents = encode_state(&example_state()).replace("1234-567890", "../../bad");
        assert!(decode_state(&contents)
            .unwrap_err()
            .contains("invalid characters"));
    }

    #[test]
    fn accepts_only_experimental_weight_bounds() {
        assert!(validate_target_weight(20).is_ok());
        assert!(validate_target_weight(100).is_ok());
        assert!(validate_target_weight(19).is_err());
        assert!(validate_target_weight(101).is_err());
    }

    #[test]
    fn requires_intervention_weight_to_be_below_baseline() {
        assert!(validate_target_below_baseline(20, 100).is_ok());
        assert!(validate_target_below_baseline(100, 100).is_err());
        assert!(validate_target_below_baseline(20, 10).is_err());
    }

    #[test]
    fn accepts_only_bounded_leases() {
        assert!(validate_lease_seconds(30).is_ok());
        assert!(validate_lease_seconds(3_600).is_ok());
        assert!(validate_lease_seconds(29).is_err());
        assert!(validate_lease_seconds(3_601).is_err());
    }

    #[test]
    fn accepts_only_the_expected_user_slice_path() {
        assert!(validate_sentry_cgroup_path(
            "/user.slice/user-1000.slice/user@1000.service/sentry.slice"
        )
        .is_ok());
        assert!(validate_sentry_cgroup_path("/system.slice/sentry.slice").is_err());
        assert!(validate_sentry_cgroup_path("/user.slice/../sentry.slice").is_err());
    }
}
