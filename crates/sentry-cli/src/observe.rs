use sentry_linux::observer::{
    discover_sentry_workloads, CgroupSnapshot, IoDeviceStat, ReadState, WorkloadSnapshot,
};
use std::collections::BTreeMap;

pub fn run() -> u8 {
    let workloads = match discover_sentry_workloads() {
        Ok(workloads) => workloads,
        Err(error) => {
            eprintln!("SENTRY observer: {error}");
            return 1;
        }
    };

    println!("SENTRY workload observation (read-only)\n");
    if workloads.is_empty() {
        println!("No running workloads found in sentry-workloads.slice.");
        println!("Launch one with: sentry run --background --name NAME -- COMMAND [ARG...]");
        return 0;
    }

    for workload in &workloads {
        print_workload(workload);
    }
    println!(
        "Observed {} workload(s). No system settings were changed.",
        workloads.len()
    );
    0
}

fn print_workload(workload: &WorkloadSnapshot) {
    println!("WORKLOAD {}", workload.unit_name);
    println!("  Slice:      {}", workload.slice);
    println!("  ControlGroup: {}", workload.cgroup.control_group);
    println!("  Processes:  {}", show(&workload.cgroup.process_count));
    print_cgroup(&workload.cgroup);
    println!();
}

fn print_cgroup(cgroup: &CgroupSnapshot) {
    println!(
        "  Controllers available to children: {}",
        show_tokens(&cgroup.controllers_available_for_children)
    );
    println!(
        "  Controllers enabled for children:  {}",
        show_tokens(&cgroup.controllers_enabled_for_children)
    );
    println!("  CPU:");
    println!(
        "    usage_usec: {}",
        counter(&cgroup.cpu_stat, "usage_usec")
    );
    println!("    user_usec:  {}", counter(&cgroup.cpu_stat, "user_usec"));
    println!(
        "    system_usec: {}",
        counter(&cgroup.cpu_stat, "system_usec")
    );
    println!("    weight:     {}", show(&cgroup.cpu_weight));
    println!("    max:        {}", show(&cgroup.cpu_max));
    println!("    pressure:   {}", show_psi(&cgroup.cpu_pressure));
    println!("  Memory:");
    println!("    current:    {}", show(&cgroup.memory_current));
    println!("    high:       {}", show(&cgroup.memory_high));
    println!("    events:     {}", show_map(&cgroup.memory_events));
    println!("    pressure:   {}", show_psi(&cgroup.memory_pressure));
    println!("  I/O:");
    println!("    stats:      {}", show_io(&cgroup.io_stat));
    println!("    pressure:   {}", show_psi(&cgroup.io_pressure));
}

fn counter(state: &ReadState<BTreeMap<String, u64>>, key: &str) -> String {
    match state {
        ReadState::Available(values) => values
            .get(key)
            .map(|value| value.to_string())
            .unwrap_or_else(|| "not reported".to_owned()),
        ReadState::Missing => "unavailable".to_owned(),
        ReadState::Error(error) => format!("error ({error})"),
    }
}

fn show_tokens(state: &ReadState<Vec<String>>) -> String {
    match state {
        ReadState::Available(values) if values.is_empty() => "none".to_owned(),
        ReadState::Available(values) => values.join(", "),
        ReadState::Missing => "unavailable".to_owned(),
        ReadState::Error(error) => format!("error ({error})"),
    }
}

fn show<T: std::fmt::Display>(state: &ReadState<T>) -> String {
    match state {
        ReadState::Available(value) => value.to_string(),
        ReadState::Missing => "unavailable".to_owned(),
        ReadState::Error(error) => format!("error ({error})"),
    }
}

fn show_map(state: &ReadState<BTreeMap<String, u64>>) -> String {
    match state {
        ReadState::Available(values) if values.is_empty() => "no events recorded".to_owned(),
        ReadState::Available(values) => values
            .iter()
            .map(|(key, value)| format!("{key}={value}"))
            .collect::<Vec<_>>()
            .join(", "),
        ReadState::Missing => "unavailable".to_owned(),
        ReadState::Error(error) => format!("error ({error})"),
    }
}

fn show_io(state: &ReadState<Vec<IoDeviceStat>>) -> String {
    match state {
        ReadState::Available(devices) if devices.is_empty() => "no device counters".to_owned(),
        ReadState::Available(devices) => devices
            .iter()
            .map(|device| {
                let counters = device
                    .counters
                    .iter()
                    .map(|(key, value)| format!("{key}={value}"))
                    .collect::<Vec<_>>()
                    .join(" ");
                format!("{} {counters}", device.device)
            })
            .collect::<Vec<_>>()
            .join("; "),
        ReadState::Missing => "unavailable (I/O controller not exposed here)".to_owned(),
        ReadState::Error(error) => format!("error ({error})"),
    }
}

fn show_psi(state: &ReadState<sentry_linux::psi::PsiSnapshot>) -> String {
    match state {
        ReadState::Available(snapshot) => {
            let full = snapshot
                .full
                .map(|value| format!(", full avg10={:.2}%", value.avg10))
                .unwrap_or_default();
            format!("some avg10={:.2}%{full}", snapshot.some.avg10)
        }
        ReadState::Missing => "unavailable".to_owned(),
        ReadState::Error(error) => format!("error ({error})"),
    }
}
