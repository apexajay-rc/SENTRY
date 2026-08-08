use std::collections::HashSet;
use std::process::Command;
use std::sync::{Arc, RwLock};
use std::thread;
use std::time::Duration;

use crate::tree_crawler;

pub fn start_audio_tracker() -> Arc<RwLock<HashSet<u32>>> {
    let shared_audio_tree = Arc::new(RwLock::new(HashSet::new()));
    let thread_tree = Arc::clone(&shared_audio_tree);

    thread::spawn(move || {
        // 1. Cross the Root Boundary
        // Since SENTRY runs as root via sudo, we must find the actual user's audio server.
        let sudo_user = std::env::var("SUDO_USER").unwrap_or_else(|_| "root".to_string());
        
        let uid_output = Command::new("id").arg("-u").arg(&sudo_user).output();
        let uid = match uid_output {
            Ok(out) => String::from_utf8_lossy(&out.stdout).trim().to_string(),
            Err(_) => "1000".to_string(), // Fallback to standard first user ID
        };

        let runtime_dir = format!("XDG_RUNTIME_DIR=/run/user/{}", uid);

        println!("[AUDIO-MONITOR] Initializing for user: {} (UID: {})", sudo_user, uid);

        // 2. The Infinite Polling Loop
        loop {
            let mut active_audio_pids = HashSet::new();

            // Check Playback (Sink Inputs)
            if let Ok(out) = execute_pactl(&sudo_user, &runtime_dir, "sink-inputs") {
                active_audio_pids.extend(extract_pids(&out));
            }

            // Check Recording/Microphone (Source Outputs)
            if let Ok(out) = execute_pactl(&sudo_user, &runtime_dir, "source-outputs") {
                active_audio_pids.extend(extract_pids(&out));
            }

            // 3. Expand base PIDs into full VIP Trees
            let mut audio_vip_tree = HashSet::new();
            for pid in &active_audio_pids {
                let expanded = tree_crawler::get_process_tree(*pid);
                audio_vip_tree.extend(expanded);
            }

            // 4. Safely update the shared state
            if let Ok(mut lock) = thread_tree.write() {
                // Only log if the audio tree size changed to prevent terminal spam
                if lock.len() != audio_vip_tree.len() {
                    if audio_vip_tree.is_empty() {
                        println!("[AUDIO-MONITOR] Audio stream stopped. Releasing priorities.");
                    } else {
                        println!(
                            "[AUDIO-MONITOR] Detected active streams. Expanded to {} audio VIP threads.",
                            audio_vip_tree.len()
                        );
                    }
                }
                *lock = audio_vip_tree;
            }

            // Sleep for 2 seconds to keep CPU overhead near 0%
            thread::sleep(Duration::from_secs(2));
        }
    });

    shared_audio_tree
}

/// Executes pactl safely as the target user.
fn execute_pactl(user: &str, runtime_env: &str, command: &str) -> Result<String, std::io::Error> {
    let output = Command::new("sudo")
        .args(["-u", user, "env", runtime_env, "pactl", "list", command])
        .output()?;
        
    Ok(String::from_utf8_lossy(&output.stdout).to_string())
}

/// Parses the output of pactl to extract process IDs.
fn extract_pids(pactl_output: &str) -> HashSet<u32> {
    let mut pids = HashSet::new();
    
    // Look for lines like: application.process.id = "12345"
    for line in pactl_output.lines() {
        if line.contains("application.process.id") {
            if let Some(start_quote) = line.find('"') {
                if let Some(end_quote) = line[start_quote + 1..].find('"') {
                    let pid_str = &line[start_quote + 1..start_quote + 1 + end_quote];
                    if let Ok(pid) = pid_str.parse::<u32>() {
                        pids.insert(pid);
                    }
                }
            }
        }
    }
    
    pids
}
