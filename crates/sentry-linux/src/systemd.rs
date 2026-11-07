use std::process::{Command, Output};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SystemdCheck {
    pub systemd_run_available: bool,
    pub user_manager_reachable: bool,
    pub detail: String,
}

pub fn inspect_user_manager() -> SystemdCheck {
    let systemd_run = Command::new("systemd-run").arg("--version").output();
    let systemctl = Command::new("systemctl")
        .args(["--user", "show-environment"])
        .output();

    let systemd_run_available = output_succeeded(&systemd_run);
    let user_manager_reachable = output_succeeded(&systemctl);

    let detail = match (&systemd_run, &systemctl) {
        (Err(error), _) => format!("systemd-run could not be executed: {error}"),
        (Ok(output), _) if !output.status.success() => {
            format_failure("systemd-run --version", output)
        }
        (_, Err(error)) => format!("systemctl could not be executed: {error}"),
        (_, Ok(output)) if !output.status.success() => {
            format_failure("systemctl --user show-environment", output)
        }
        _ => "systemd-run and the user manager are available".to_owned(),
    };

    SystemdCheck {
        systemd_run_available,
        user_manager_reachable,
        detail,
    }
}

fn output_succeeded(output: &Result<Output, std::io::Error>) -> bool {
    matches!(output, Ok(result) if result.status.success())
}

fn format_failure(command: &str, output: &Output) -> String {
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_owned();
    if stderr.is_empty() {
        format!("{command} exited with {}", output.status)
    } else {
        format!("{command} failed: {stderr}")
    }
}
