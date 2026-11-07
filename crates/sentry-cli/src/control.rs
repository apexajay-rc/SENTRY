use crate::cli::ControlCommand;
use sentry_linux::cpu_weight;
use std::process::ExitCode;

pub fn run(command: ControlCommand) -> ExitCode {
    let result = match command {
        ControlCommand::Status => cpu_weight::status().map(|status| {
            println!("SENTRY aggregate CPU control");
            println!("  Slice:                 sentry.slice");
            println!("  Kernel CPUWeight:      {}", status.effective_weight);
            println!("  systemd CPUWeight:     {}", status.systemd_property);
            match status.lease {
                Some(lease) => {
                    println!("  Lease record:          present");
                    println!("  Baseline weight:       {}", lease.baseline_weight);
                    println!("  Target weight:         {}", lease.target_weight);
                    println!("  Lease duration:        {}s", lease.lease_duration_seconds);
                    println!("  Expiry timer:         {}", lease.restoration_timer_state);
                }
                None => println!("  Lease:                 none"),
            }
        }),
        ControlCommand::SetCpuWeight {
            weight,
            lease_seconds,
        } => cpu_weight::set_with_lease(weight, lease_seconds).map(|()| {
            println!(
                "SENTRY: sentry.slice CPUWeight set to {weight}; restoration scheduled in {lease_seconds}s"
            );
        }),
        ControlCommand::Restore { lease_token } => {
            cpu_weight::restore(lease_token.as_deref()).map(|()| {
                if lease_token.is_some() {
                    println!("SENTRY: lease expiry restoration completed");
                } else {
                    println!("SENTRY: original effective CPU weight restored");
                }
            })
        }
    };

    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("sentry: {error}");
            ExitCode::from(1)
        }
    }
}
