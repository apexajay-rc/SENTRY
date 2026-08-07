use anyhow::Result;

mod monitor;

fn main() -> Result<()> {
    println!("[SENTRY-CORE] Initializing hybrid protection system...");

    // 1. Launch the Ring -1 eBPF Dictator engine into the Linux kernel
    let mut bpf_controller = sentry_bpf::launch_bpf_engine()?;

    println!("[SENTRY-CORE] SENTRY is now actively governing CPU scheduling context.");
    
    // 2. Start the window focus listener in the background
    monitor::start_focus_monitor(move |pid| {
        bpf_controller.update_vip_pid(pid)?;
        Ok(())
    });

    println!("[SENTRY-CORE] Focus monitor engaged. Press Ctrl+C to exit.");

    // Keep the main thread alive
    loop {
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
}
