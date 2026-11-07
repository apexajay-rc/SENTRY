use sentry_linux::{cgroup, psi, systemd};

#[derive(Clone, Copy)]
enum Status {
    Pass,
    Warn,
    Fail,
}

struct Check {
    name: &'static str,
    status: Status,
    detail: String,
}

pub fn run() -> u8 {
    let mut checks = Vec::new();

    checks.push(Check {
        name: "Operating system",
        status: if cfg!(target_os = "linux") {
            Status::Pass
        } else {
            Status::Fail
        },
        detail: std::env::consts::OS.to_owned(),
    });

    match cgroup::inspect_unified_hierarchy() {
        Ok(info) => {
            let controllers = if info.available_controllers.is_empty() {
                "none reported".to_owned()
            } else {
                info.available_controllers.join(", ")
            };
            checks.push(Check {
                name: "cgroup v2",
                status: Status::Pass,
                detail: format!(
                    "unified hierarchy files present; available controllers: {controllers}"
                ),
            });
            checks.push(Check {
                name: "cgroup child controllers",
                status: Status::Warn,
                detail: if info.enabled_for_children.is_empty() {
                    "no controllers enabled at the root; this is not changed by `doctor`".to_owned()
                } else {
                    info.enabled_for_children.join(", ")
                },
            });
        }
        Err(error) => checks.push(Check {
            name: "cgroup v2",
            status: Status::Warn,
            detail: error,
        }),
    }

    for resource in ["cpu", "memory", "io"] {
        let name = match resource {
            "cpu" => "CPU PSI",
            "memory" => "Memory PSI",
            _ => "I/O PSI",
        };
        match psi::read_snapshot(resource) {
            Ok(snapshot) => {
                let mut detail = format!("some avg10={:.2}%", snapshot.some.avg10);
                if let Some(full) = snapshot.full {
                    detail.push_str(&format!(", full avg10={:.2}%", full.avg10));
                }
                checks.push(Check {
                    name,
                    status: Status::Pass,
                    detail,
                });
            }
            Err(error) => checks.push(Check {
                name,
                status: Status::Warn,
                detail: error,
            }),
        }
    }

    let manager = systemd::inspect_user_manager();
    checks.push(Check {
        name: "systemd-run",
        status: if manager.systemd_run_available {
            Status::Pass
        } else {
            Status::Fail
        },
        detail: if manager.systemd_run_available {
            "executable available".to_owned()
        } else {
            manager.detail.clone()
        },
    });
    checks.push(Check {
        name: "systemd user manager",
        status: if manager.user_manager_reachable {
            Status::Pass
        } else {
            Status::Fail
        },
        detail: if manager.user_manager_reachable {
            "reachable".to_owned()
        } else {
            manager.detail
        },
    });

    println!("SENTRY environment report\n");
    let mut hard_failure = false;
    for check in checks {
        let marker = match check.status {
            Status::Pass => "[PASS]",
            Status::Warn => "[WARN]",
            Status::Fail => {
                hard_failure = true;
                "[FAIL]"
            }
        };
        println!("{marker:6} {:24} {}", check.name, check.detail);
    }

    if hard_failure {
        println!("\nOne or more required execution prerequisites are unavailable.");
        1
    } else {
        println!("\nBasic workload-grouping prerequisites are available. No system settings were changed.");
        0
    }
}
