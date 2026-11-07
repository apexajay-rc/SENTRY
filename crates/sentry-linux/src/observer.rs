//! Read-only observation of SENTRY-owned systemd scopes and their cgroups.
//!
//! This module deliberately never writes to cgroupfs or changes systemd unit
//! properties. It treats missing controller files as unavailable capabilities,
//! not as zero-valued measurements.

use crate::psi::{self, PsiSnapshot};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Component, Path, PathBuf};
use std::process::Command;

const CGROUP_ROOT: &str = "/sys/fs/cgroup";
const SENTRY_SLICE: &str = "sentry-workloads.slice";

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReadState<T> {
    Available(T),
    Missing,
    Error(String),
}

impl<T> ReadState<T> {
    pub fn is_available(&self) -> bool {
        matches!(self, Self::Available(_))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LimitValue {
    Max,
    Value(u64),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CpuMax {
    pub quota_usec: Option<u64>,
    pub period_usec: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IoDeviceStat {
    pub device: String,
    pub counters: BTreeMap<String, u64>,
}

impl std::fmt::Display for LimitValue {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Max => formatter.write_str("max"),
            Self::Value(value) => write!(formatter, "{value} bytes"),
        }
    }
}

impl std::fmt::Display for CpuMax {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self.quota_usec {
            Some(quota) => write!(formatter, "{quota} {}", self.period_usec),
            None => write!(formatter, "max {}", self.period_usec),
        }
    }
}

impl std::fmt::Display for IoDeviceStat {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{} {:?}", self.device, self.counters)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CgroupSnapshot {
    pub control_group: String,
    pub directory: PathBuf,
    pub controllers_available_for_children: ReadState<Vec<String>>,
    pub controllers_enabled_for_children: ReadState<Vec<String>>,
    pub process_count: ReadState<usize>,
    pub cpu_stat: ReadState<BTreeMap<String, u64>>,
    pub cpu_weight: ReadState<u64>,
    pub cpu_max: ReadState<CpuMax>,
    pub memory_current: ReadState<u64>,
    pub memory_high: ReadState<LimitValue>,
    pub memory_events: ReadState<BTreeMap<String, u64>>,
    pub io_stat: ReadState<Vec<IoDeviceStat>>,
    pub cpu_pressure: ReadState<PsiSnapshot>,
    pub memory_pressure: ReadState<PsiSnapshot>,
    pub io_pressure: ReadState<PsiSnapshot>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkloadSnapshot {
    pub unit_name: String,
    pub slice: String,
    pub cgroup: CgroupSnapshot,
}

/// Discover running SENTRY scopes in the dedicated `sentry-workloads.slice`.
///
/// Discovery is intentionally based on systemd unit identity, not a host-wide
/// PID scan. Scopes outside SENTRY's slice are ignored even if their names happen
/// to begin with `sentry-`.
pub fn discover_sentry_workloads() -> Result<Vec<WorkloadSnapshot>, String> {
    discover_sentry_workloads_with_root(Path::new(CGROUP_ROOT))
}

/// Injectable cgroup root for tests and alternate mount layouts.
pub fn discover_sentry_workloads_with_root(root: &Path) -> Result<Vec<WorkloadSnapshot>, String> {
    let output = Command::new("systemctl")
        .args([
            "--user",
            "list-units",
            "--type=scope",
            "--state=running",
            "--no-legend",
            "--no-pager",
            "--plain",
            "--full",
        ])
        .output()
        .map_err(|error| format!("failed to execute systemctl: {error}"))?;

    if !output.status.success() {
        return Err(command_error("systemctl --user list-units", &output.stderr));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut units = stdout
        .lines()
        .filter_map(|line| line.split_whitespace().next())
        .filter(|unit| unit.starts_with("sentry-") && unit.ends_with(".scope"))
        .map(str::to_owned)
        .collect::<Vec<_>>();
    units.sort();
    units.dedup();

    let mut snapshots = Vec::new();
    for unit_name in units {
        let properties = show_scope_properties(&unit_name)?;
        let slice = properties
            .get("Slice")
            .cloned()
            .unwrap_or_else(|| "".to_owned());
        if slice != SENTRY_SLICE {
            continue;
        }
        let control_group = properties
            .get("ControlGroup")
            .ok_or_else(|| format!("systemd did not report ControlGroup for {unit_name}"))?;
        let cgroup = inspect_cgroup(root, control_group)?;
        snapshots.push(WorkloadSnapshot {
            unit_name,
            slice,
            cgroup,
        });
    }

    Ok(snapshots)
}

fn show_scope_properties(unit_name: &str) -> Result<BTreeMap<String, String>, String> {
    let output = Command::new("systemctl")
        .args([
            "--user",
            "show",
            "--no-pager",
            "--property=Slice",
            "--property=ControlGroup",
            unit_name,
        ])
        .output()
        .map_err(|error| format!("failed to inspect {unit_name}: {error}"))?;
    if !output.status.success() {
        return Err(command_error(
            &format!("systemctl --user show {unit_name}"),
            &output.stderr,
        ));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    Ok(stdout
        .lines()
        .filter_map(|line| line.split_once('='))
        .map(|(key, value)| (key.to_owned(), value.to_owned()))
        .collect())
}

fn command_error(command: &str, stderr: &[u8]) -> String {
    let detail = String::from_utf8_lossy(stderr).trim().to_owned();
    if detail.is_empty() {
        format!("{command} failed")
    } else {
        format!("{command} failed: {detail}")
    }
}

pub fn inspect_cgroup(root: &Path, control_group: &str) -> Result<CgroupSnapshot, String> {
    let directory = resolve_cgroup_directory(root, control_group)?;
    let controllers_available_for_children =
        read_parsed(&directory.join("cgroup.controllers"), parse_tokens);
    let controllers_enabled_for_children =
        read_parsed(&directory.join("cgroup.subtree_control"), parse_tokens);
    let process_count = read_parsed(&directory.join("cgroup.procs"), parse_process_count);
    let cpu_stat = read_parsed(&directory.join("cpu.stat"), parse_key_value_counters);
    let cpu_weight = read_parsed(&directory.join("cpu.weight"), parse_u64);
    let cpu_max = read_parsed(&directory.join("cpu.max"), parse_cpu_max);
    let memory_current = read_parsed(&directory.join("memory.current"), parse_u64);
    let memory_high = read_parsed(&directory.join("memory.high"), parse_limit);
    let memory_events = read_parsed(&directory.join("memory.events"), parse_key_value_counters);
    let io_stat = read_parsed(&directory.join("io.stat"), parse_io_stat);
    let cpu_pressure = read_parsed(&directory.join("cpu.pressure"), psi::parse_snapshot);
    let memory_pressure = read_parsed(&directory.join("memory.pressure"), psi::parse_snapshot);
    let io_pressure = read_parsed(&directory.join("io.pressure"), psi::parse_snapshot);

    Ok(CgroupSnapshot {
        control_group: control_group.to_owned(),
        directory,
        controllers_available_for_children,
        controllers_enabled_for_children,
        process_count,
        cpu_stat,
        cpu_weight,
        cpu_max,
        memory_current,
        memory_high,
        memory_events,
        io_stat,
        cpu_pressure,
        memory_pressure,
        io_pressure,
    })
}

fn resolve_cgroup_directory(root: &Path, control_group: &str) -> Result<PathBuf, String> {
    let relative = control_group
        .strip_prefix('/')
        .ok_or_else(|| format!("ControlGroup must be an absolute cgroup path: {control_group}"))?;
    if relative.is_empty() {
        return Err("refusing to inspect the cgroup root as a workload".to_owned());
    }

    let mut safe_relative = PathBuf::new();
    for component in Path::new(relative).components() {
        match component {
            Component::Normal(part) => safe_relative.push(part),
            _ => return Err(format!("unsafe component in cgroup path: {control_group}")),
        }
    }

    let root_canonical = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve cgroup root {}: {error}", root.display()))?;
    let candidate = root_canonical.join(safe_relative);
    let candidate_canonical = candidate
        .canonicalize()
        .map_err(|error| format!("cannot resolve cgroup {control_group}: {error}"))?;
    if !candidate_canonical.starts_with(&root_canonical) {
        return Err(format!(
            "cgroup path escaped the configured root: {control_group}"
        ));
    }
    if !candidate_canonical.is_dir() {
        return Err(format!("cgroup path is not a directory: {control_group}"));
    }
    Ok(candidate_canonical)
}

fn read_parsed<T>(path: &Path, parser: fn(&str) -> Result<T, String>) -> ReadState<T> {
    match fs::read_to_string(path) {
        Ok(contents) => match parser(&contents) {
            Ok(value) => ReadState::Available(value),
            Err(error) => ReadState::Error(format!("{}: {error}", path.display())),
        },
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => ReadState::Missing,
        Err(error) => ReadState::Error(format!("{}: {error}", path.display())),
    }
}

fn parse_tokens(contents: &str) -> Result<Vec<String>, String> {
    Ok(contents.split_whitespace().map(str::to_owned).collect())
}

fn parse_u64(contents: &str) -> Result<u64, String> {
    contents
        .trim()
        .parse::<u64>()
        .map_err(|_| format!("expected an unsigned integer, got `{}`", contents.trim()))
}

fn parse_limit(contents: &str) -> Result<LimitValue, String> {
    let value = contents.trim();
    if value == "max" {
        Ok(LimitValue::Max)
    } else {
        value
            .parse::<u64>()
            .map(LimitValue::Value)
            .map_err(|_| format!("expected `max` or an unsigned integer, got `{value}`"))
    }
}

fn parse_cpu_max(contents: &str) -> Result<CpuMax, String> {
    let fields = contents.split_whitespace().collect::<Vec<_>>();
    if fields.len() != 2 {
        return Err("expected `<quota|max> <period>`".to_owned());
    }
    let quota_usec = if fields[0] == "max" {
        None
    } else {
        Some(
            fields[0]
                .parse::<u64>()
                .map_err(|_| format!("invalid CPU quota `{}`", fields[0]))?,
        )
    };
    let period_usec = fields[1]
        .parse::<u64>()
        .map_err(|_| format!("invalid CPU period `{}`", fields[1]))?;
    if period_usec == 0 {
        return Err("CPU period must be greater than zero".to_owned());
    }
    Ok(CpuMax {
        quota_usec,
        period_usec,
    })
}

fn parse_process_count(contents: &str) -> Result<usize, String> {
    contents
        .lines()
        .filter(|line| !line.trim().is_empty())
        .try_fold(0usize, |count, line| {
            line.trim()
                .parse::<u32>()
                .map(|_| count + 1)
                .map_err(|_| format!("invalid PID in cgroup.procs: `{}`", line.trim()))
        })
}

fn parse_key_value_counters(contents: &str) -> Result<BTreeMap<String, u64>, String> {
    let mut counters = BTreeMap::new();
    for line in contents.lines().filter(|line| !line.trim().is_empty()) {
        let fields = line.split_whitespace().collect::<Vec<_>>();
        if fields.len() != 2 {
            return Err(format!("expected `<key> <value>`, got `{line}`"));
        }
        let value = fields[1]
            .parse::<u64>()
            .map_err(|_| format!("invalid counter `{}`", fields[1]))?;
        if counters.insert(fields[0].to_owned(), value).is_some() {
            return Err(format!("duplicate counter `{}`", fields[0]));
        }
    }
    Ok(counters)
}

fn parse_io_stat(contents: &str) -> Result<Vec<IoDeviceStat>, String> {
    let mut devices = Vec::new();
    for line in contents.lines().filter(|line| !line.trim().is_empty()) {
        let mut fields = line.split_whitespace();
        let device = fields
            .next()
            .ok_or_else(|| "missing device identifier in io.stat".to_owned())?;
        if !device.contains(':') {
            return Err(format!("invalid device identifier `{device}`"));
        }
        let mut counters = BTreeMap::new();
        for field in fields {
            let (key, value) = field
                .split_once('=')
                .ok_or_else(|| format!("invalid io.stat field `{field}`"))?;
            let value = value
                .parse::<u64>()
                .map_err(|_| format!("invalid io.stat counter `{field}`"))?;
            if counters.insert(key.to_owned(), value).is_some() {
                return Err(format!("duplicate io.stat counter `{key}`"));
            }
        }
        devices.push(IoDeviceStat {
            device: device.to_owned(),
            counters,
        });
    }
    Ok(devices)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_unlimited_cpu_max() {
        assert_eq!(
            parse_cpu_max("max 100000\n").unwrap(),
            CpuMax {
                quota_usec: None,
                period_usec: 100_000
            }
        );
    }

    #[test]
    fn parses_limited_cpu_max() {
        assert_eq!(
            parse_cpu_max("25000 100000\n").unwrap(),
            CpuMax {
                quota_usec: Some(25_000),
                period_usec: 100_000
            }
        );
    }

    #[test]
    fn rejects_zero_cpu_period() {
        assert!(parse_cpu_max("max 0").is_err());
    }

    #[test]
    fn parses_memory_limit_states() {
        assert_eq!(parse_limit("max\n").unwrap(), LimitValue::Max);
        assert_eq!(
            parse_limit("1048576\n").unwrap(),
            LimitValue::Value(1_048_576)
        );
    }

    #[test]
    fn parses_cpu_and_memory_counters() {
        let counters =
            parse_key_value_counters("usage_usec 1200\nuser_usec 700\nsystem_usec 500\n").unwrap();
        assert_eq!(counters.get("usage_usec"), Some(&1200));
        assert_eq!(counters.get("system_usec"), Some(&500));
    }

    #[test]
    fn parses_io_device_counters() {
        let devices = parse_io_stat("8:0 rbytes=100 wbytes=200 rios=3 wios=4\n").unwrap();
        assert_eq!(devices.len(), 1);
        assert_eq!(devices[0].device, "8:0");
        assert_eq!(devices[0].counters.get("wbytes"), Some(&200));
    }

    #[test]
    fn counts_processes_not_lines_with_whitespace() {
        assert_eq!(parse_process_count("123\n456\n\n").unwrap(), 2);
    }

    #[test]
    fn rejects_parent_traversal_in_cgroup_path() {
        assert!(resolve_cgroup_directory(Path::new("/tmp"), "/safe/../escape").is_err());
    }

    #[test]
    fn rejects_relative_cgroup_path() {
        assert!(resolve_cgroup_directory(Path::new("/tmp"), "user.slice/foo.scope").is_err());
    }

    #[test]
    fn missing_control_file_is_not_reported_as_zero() {
        let path = std::env::temp_dir().join(format!(
            "sentry-observer-missing-{}-{}",
            std::process::id(),
            crate::workload::slugify("missing-file-test")
        ));
        let state = read_parsed(&path, parse_u64);
        assert_eq!(state, ReadState::Missing);
    }
}
