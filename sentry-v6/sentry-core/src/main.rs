use anyhow::Result;

mod monitor;
mod tree_crawler;
mod audio_monitor; // New module

fn main() -> Result<()> {
    println!("[SENTRY-CORE] Initializing hybrid protection system...");

    let mut bpf_controller = sentry_bpf::launch_bpf_engine()?;
    
    // Launch the background audio tracker
    let audio_tree_lock = audio_monitor::start_audio_tracker();

    println!("[SENTRY-CORE] SENTRY is now actively governing CPU scheduling context.");
    println!("[SENTRY-CORE] Focus & Audio monitors engaged. Press Ctrl+C to exit.");
    
    monitor::start_focus_monitor(move |pid| {
        // 1. Get the process tree of the newly focused window
        let mut combined_tree = tree_crawler::get_process_tree(pid);
        let focus_count = combined_tree.len();
        
        // 2. Safely read the latest audio background tree
        let mut audio_count = 0;
        if let Ok(audio_tree) = audio_tree_lock.read() {
            audio_count = audio_tree.len();
            // 3. Union them together (merge the sets)
            combined_tree.extend(audio_tree.iter());
        }
        
        println!(
            "[TREE-CRAWLER] Focused Window {} ({} threads) + Audio ({} threads) -> Pushing {} VIPs to Kernel",
            pid, focus_count, audio_count, combined_tree.len()
        );

        // 4. Blast the combined immunity list into the Ring -1 Dictator
        bpf_controller.sync_vip_tree(&combined_tree)?;
        Ok(())
    });

    // Keep the main thread alive indefinitely
    loop {
        std::thread::sleep(std::time::Duration::from_secs(1));
    }
}
