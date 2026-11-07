use sentry_core::{WorkloadIntent, WorkloadRequest};
use std::ffi::{OsStr, OsString};

#[derive(Debug, PartialEq, Eq)]
pub enum AppCommand {
    Help,
    Version,
    Doctor,
    Observe,
    Control(ControlCommand),
    Run(WorkloadRequest),
}

#[derive(Debug, PartialEq, Eq)]
pub enum ControlCommand {
    Status,
    SetCpuWeight { weight: u32, lease_seconds: u64 },
    Restore { lease_token: Option<String> },
}

pub fn parse(args: Vec<OsString>) -> Result<AppCommand, String> {
    let Some(subcommand) = args.first().and_then(|value| value.to_str()) else {
        return Ok(AppCommand::Help);
    };

    match subcommand {
        "help" | "--help" | "-h" => Ok(AppCommand::Help),
        "version" | "--version" | "-V" => Ok(AppCommand::Version),
        "doctor" => {
            if args.len() > 1 {
                Err("`doctor` does not accept arguments".to_owned())
            } else {
                Ok(AppCommand::Doctor)
            }
        }
        "observe" => {
            if args.len() > 1 {
                Err("`observe` does not accept arguments".to_owned())
            } else {
                Ok(AppCommand::Observe)
            }
        }
        "control" => parse_control(&args[1..]).map(AppCommand::Control),
        "run" => parse_run(&args[1..]).map(AppCommand::Run),
        other => Err(format!("unknown command `{other}`")),
    }
}

fn parse_control(args: &[OsString]) -> Result<ControlCommand, String> {
    if args.len() == 1 && args[0] == OsStr::new("status") {
        return Ok(ControlCommand::Status);
    }
    if args.first().and_then(|value| value.to_str()) != Some("cpu-weight") {
        return Err(
            "usage: sentry control status | sentry control cpu-weight <set|restore> ...".to_owned(),
        );
    }

    match args.get(1).and_then(|value| value.to_str()) {
        Some("set") => {
            let weight_text = args
                .get(2)
                .and_then(|value| value.to_str())
                .ok_or_else(|| "`cpu-weight set` requires a numeric weight".to_owned())?;
            let weight = weight_text
                .parse::<u32>()
                .map_err(|error| format!("invalid CPU weight {weight_text:?}: {error}"))?;
            if !(20..=100).contains(&weight) {
                return Err("experimental CPU weight must be between 20 and 100".to_owned());
            }

            if args.get(3).and_then(|value| value.to_str()) != Some("--lease") {
                return Err(
                    "`cpu-weight set` requires `--lease DURATION` (30s to 3600s)".to_owned(),
                );
            }
            let duration = args
                .get(4)
                .and_then(|value| value.to_str())
                .ok_or_else(|| "`--lease` requires a duration such as 60s".to_owned())?;
            if args.len() != 5 {
                return Err("unexpected arguments to `cpu-weight set`".to_owned());
            }
            let lease_seconds = parse_lease_duration(duration)?;
            Ok(ControlCommand::SetCpuWeight {
                weight,
                lease_seconds,
            })
        }
        Some("restore") if args.len() == 2 => Ok(ControlCommand::Restore { lease_token: None }),
        Some("restore") if args.len() == 4 && args[2] == OsStr::new("--lease-token") => {
            let token = args[3]
                .to_str()
                .ok_or_else(|| "invalid internal lease token".to_owned())?;
            if token.is_empty()
                || !token
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || byte == b'-')
            {
                return Err("invalid internal lease token".to_owned());
            }
            Ok(ControlCommand::Restore {
                lease_token: Some(token.to_owned()),
            })
        }
        _ => {
            Err("usage: sentry control cpu-weight set WEIGHT --lease DURATION | restore".to_owned())
        }
    }
}

fn parse_lease_duration(value: &str) -> Result<u64, String> {
    let seconds = if let Some(number) = value.strip_suffix('s') {
        number
            .parse::<u64>()
            .map_err(|error| format!("invalid lease duration {value:?}: {error}"))?
    } else if let Some(number) = value.strip_suffix('m') {
        let minutes = number
            .parse::<u64>()
            .map_err(|error| format!("invalid lease duration {value:?}: {error}"))?;
        minutes
            .checked_mul(60)
            .ok_or_else(|| "lease duration overflows".to_owned())?
    } else {
        return Err("lease duration must use seconds (e.g. 60s) or minutes (e.g. 2m)".to_owned());
    };

    if !(30..=3_600).contains(&seconds) {
        return Err("lease duration must be between 30s and 60m".to_owned());
    }
    Ok(seconds)
}

fn parse_run(args: &[OsString]) -> Result<WorkloadRequest, String> {
    let mut background = false;
    let mut name = None;
    let mut command_start = None;
    let mut index = 0;

    while index < args.len() {
        let argument = &args[index];
        if argument == OsStr::new("--") {
            command_start = Some(index + 1);
            break;
        } else if argument == OsStr::new("--background") {
            background = true;
        } else if argument == OsStr::new("--name") {
            index += 1;
            let Some(value) = args.get(index).and_then(|value| value.to_str()) else {
                return Err("`--name` requires a UTF-8 value".to_owned());
            };
            name = Some(value.to_owned());
        } else {
            return Err(format!(
                "unknown `run` option `{}`; put the workload command after `--`",
                argument.to_string_lossy()
            ));
        }
        index += 1;
    }

    if !background {
        return Err("explicit workload intent is required; add `--background`".to_owned());
    }
    let Some(start) = command_start else {
        return Err("missing `-- COMMAND [ARG...]`".to_owned());
    };

    let request = WorkloadRequest {
        display_name: name,
        intent: WorkloadIntent::Background,
        command: args[start..].to_vec(),
    };
    request.validate()?;
    Ok(request)
}

pub fn print_help() {
    println!(
        "SENTRY — adaptive workload orchestration for Linux\n\n\
         USAGE:\n\
         sentry <COMMAND>\n\n\
         COMMANDS:\n\
         help                         Print this help\n\
         version                      Print version\n\
         doctor                       Inspect Linux resource-management capabilities\n\
         observe                      Read a one-shot snapshot of SENTRY workloads\n\
         control status               Inspect aggregate CPU-weight state\n\
         control cpu-weight set WEIGHT --lease DURATION\n\
                                      Temporarily change sentry.slice CPUWeight\n\
         control cpu-weight restore   Restore the pre-intervention effective weight\n\
         run --background [OPTIONS] -- COMMAND [ARG...]\n\
                                      Run an explicitly background workload in\n\
                                      sentry-workloads.slice\n\n\
         OPTIONS for `run`:\n\
         --background                Required explicit workload intent\n\
         --name NAME                 Optional human-readable workload name\n\n\
         EXAMPLE:\n\
         sentry run --background --name rust-build -- cargo build --release\n\n\
         SAFETY:\n\
         `observe` is read-only. `run` sets a neutral CPUWeight=100 baseline.\n\
         `control cpu-weight set` only modifies the dedicated sentry.slice, only\n\
         within weights 20–100, and always requires a 30–3600 second lease.\n\
         A systemd user timer restores the previous effective kernel weight.\n\
         No CPU quota, memory, I/O, affinity or OOM policy is modified."
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    fn os(values: &[&str]) -> Vec<OsString> {
        values.iter().map(OsString::from).collect()
    }

    #[test]
    fn no_arguments_prints_help() {
        assert_eq!(parse(Vec::new()).unwrap(), AppCommand::Help);
    }

    #[test]
    fn parses_observe_command() {
        assert_eq!(parse(os(&["observe"])).unwrap(), AppCommand::Observe);
        assert!(parse(os(&["observe", "--watch"]))
            .unwrap_err()
            .contains("does not accept arguments"));
    }

    #[test]
    fn requires_explicit_intent() {
        assert!(parse(os(&["run", "--", "cargo", "build"]))
            .unwrap_err()
            .contains("explicit workload intent"));
    }

    #[test]
    fn preserves_command_arguments_after_separator() {
        let request = match parse(os(&[
            "run",
            "--background",
            "--name",
            "rust-build",
            "--",
            "cargo",
            "build",
            "--release",
        ]))
        .unwrap()
        {
            AppCommand::Run(request) => request,
            other => panic!("unexpected command: {other:?}"),
        };
        assert_eq!(request.command, os(&["cargo", "build", "--release"]));
        assert_eq!(request.display_name.as_deref(), Some("rust-build"));
    }

    #[test]
    fn parses_bounded_cpu_weight_lease() {
        assert_eq!(
            parse(os(&[
                "control",
                "cpu-weight",
                "set",
                "20",
                "--lease",
                "60s"
            ]))
            .unwrap(),
            AppCommand::Control(ControlCommand::SetCpuWeight {
                weight: 20,
                lease_seconds: 60,
            })
        );
    }

    #[test]
    fn parses_cpu_weight_restore() {
        assert_eq!(
            parse(os(&["control", "cpu-weight", "restore"])).unwrap(),
            AppCommand::Control(ControlCommand::Restore { lease_token: None })
        );
    }

    #[test]
    fn rejects_out_of_range_weight_and_lease() {
        assert!(parse(os(&[
            "control",
            "cpu-weight",
            "set",
            "10",
            "--lease",
            "60s"
        ]))
        .is_err());
        assert!(parse(os(&[
            "control",
            "cpu-weight",
            "set",
            "20",
            "--lease",
            "10s"
        ]))
        .is_err());
    }

    #[test]
    fn parses_minute_lease_duration() {
        assert_eq!(parse_lease_duration("2m").unwrap(), 120);
    }

    #[test]
    fn rejects_empty_command() {
        assert!(parse(os(&["run", "--background", "--"]))
            .unwrap_err()
            .contains("empty"));
    }
}
