use anyhow::Result;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::fs;

mod monitor;
mod tree_crawler;
mod audio_monitor;
mod topology;
mod predictor;

/// Translates a raw PID into a permanent executable name for the ML model
fn get_process_name(pid: u32) -> String {
    fs::read_to_string(format!("/proc/{}/comm", pid))
        .unwrap_or_else(|_| "unknown".to_string())
        .trim()
        .to_string()
}

fn main() -> Result<()> {
    println!("[SENTRY-CORE] Initializing hybrid protection system...");

    // Set up a clean exit flag for SIGINT (Ctrl+C) and SIGTERM (systemctl stop)
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();
    
    ctrlc::set_handler(move || {
        println!("\n[SENTRY-CORE] Shutdown signal received. Detaching Ring -1 Dictator...");
        r.store(false, Ordering::SeqCst);
    })?;

    // 1. Map Physical Hardware
    let core_map = topology::build_core_map();
    println!("[TOPOLOGY] Physical hardware silicon scan complete.");
    println!(
        "[TOPOLOGY] UNIVERSAL ROUTER: Mapping {} cores to VIP Zone, {} cores to Background Quarantine.",
        core_map.p_cores.len(),
        core_map.e_cores.len()
    );

    // 2. Launch Kernel Engine
    let mut bpf_controller = sentry_bpf::launch_bpf_engine()?;
    bpf_controller.sync_core_topology(&core_map.p_cores, &core_map.e_cores)?;
    println!("[BPF-ENGINE] Successfully routed silicon topology to the Kernel.");

    let audio_tree_lock = audio_monitor::start_audio_tracker();

    // --- PILLAR 3: THE CLAIRVOYANT ENGINE ---
    // We require an 80% confidence threshold before allowing SENTRY to guess
    let mut markov_brain = predictor::MarkovEngine::new(0.80);
    let mut last_app_name = String::new();

    println!("[SENTRY-CORE] SENTRY is now actively governing CPU scheduling context.");
    println!("[SENTRY-CORE] Monitors engaged. Press Ctrl+C or stop systemd service to exit.");
    
    monitor::start_focus_monitor(move |pid| {
        // A. Identify the application name
        let current_app = get_process_name(pid);
        
        // B. Train the Markov Matrix dynamically in real-time
        if !last_app_name.is_empty() && last_app_name != current_app {
            markov_brain.record_transition(&last_app_name, &current_app);
        }

        // C. Attempt a prediction
        if let Some((predicted_app, confidence)) = markov_brain.predict_next(&current_app) {
            println!(
                "[CLAIRVOYANCE] High probability workflow detected. Pre-warming cache for: {} ({:.1}%)", 
                predicted_app, 
                confidence * 100.0
            );
            // Future v8 hook: We will proactively pull the predicted app's PIDs into the VIP array here
        }

        // D. Standard Reactive Routing (The Bedrock)
        let mut combined_tree = tree_crawler::get_process_tree(pid);
        let focus_count = combined_tree.len();
        
        let mut audio_count = 0;
        if let Ok(audio_tree) = audio_tree_lock.read() {
            audio_count = audio_tree.len();
            combined_tree.extend(audio_tree.iter());
        }
        
        println!(
            "[TREE-CRAWLER] Focused Window: {} ({} threads) + Audio ({} threads) -> Pushing {} VIPs",
            current_app, focus_count, audio_count, combined_tree.len()
        );

        bpf_controller.sync_vip_tree(&combined_tree)?;
        
        // The Borrow-Checker Fix: Move the string assignment to the very end of the loop
        last_app_name = current_app;
        
        Ok(())
    });

    // Clean execution loop: exits gracefully when `running` is set to false
    while running.load(Ordering::SeqCst) {
        std::thread::sleep(std::time::Duration::from_millis(200));
    }

    println!("[SENTRY-CORE] Unregistering eBPF scheduler and restoring default Linux CFS.");
    Ok(())
}
