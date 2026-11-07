mod cli;
mod control;
mod doctor;
mod launch;
mod observe;

use std::process::ExitCode;

fn main() -> ExitCode {
    match cli::parse(std::env::args_os().skip(1).collect()) {
        Ok(cli::AppCommand::Help) => {
            cli::print_help();
            ExitCode::SUCCESS
        }
        Ok(cli::AppCommand::Version) => {
            println!("sentry {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        Ok(cli::AppCommand::Doctor) => ExitCode::from(doctor::run()),
        Ok(cli::AppCommand::Observe) => ExitCode::from(observe::run()),
        Ok(cli::AppCommand::Control(command)) => control::run(command),
        Ok(cli::AppCommand::Run(request)) => match launch::run(request) {
            Ok(code) => ExitCode::from(code.clamp(0, 255) as u8),
            Err(error) => {
                eprintln!("sentry: {error}");
                ExitCode::from(1)
            }
        },
        Err(error) => {
            eprintln!("sentry: {error}\n\nRun `sentry help` for usage.");
            ExitCode::from(2)
        }
    }
}
