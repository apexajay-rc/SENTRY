use std::process::Command;
use std::thread;
use std::time::Duration;

/// Polls the active window manager every 100ms to find the focused PID
/// and updates the kernel eBPF map instantly.
pub fn start_focus_monitor<F>(mut update_callback: F) 
where
    F: FnMut(u32) -> anyhow::Result<()> + Send + 'static,
{
    thread::spawn(move || {
        let mut last_pid = 0;

        loop {
            if let Some(pid) = fetch_active_window_pid() {
                if pid != last_pid && pid > 0 {
                    println!("[MONITOR] Focused Window PID changed: {}. Engaging Ring -1 priority...", pid);
                    if let Err(e) = update_callback(pid) {
                        eprintln!("[MONITOR] Failed to update kernel VIP map: {}", e);
                    }
                    last_pid = pid;
                }
            }
            thread::sleep(Duration::from_millis(100));
        }
    });
}

/// Helper to extract the PID of the currently active window using standard X11 tools.
fn fetch_active_window_pid() -> Option<u32> {
    // 1. Get the active window ID from the root window
    let output = Command::new("xprop")
        .args(["-root", "_NET_ACTIVE_WINDOW"])
        .output()
        .ok()?;
    
    let stdout = String::from_utf8_lossy(&output.stdout);
    // Parse out the window hex ID (e.g., "# 0x200003a")
    let win_id = stdout.split('#').nth(1)?.trim();
    if win_id.contains("0x0") {
        return None;
    }

    // 2. Query the PID of that specific window ID
    let pid_output = Command::new("xprop")
        .args(["-id", win_id, "_NET_WM_PID"])
        .output()
        .ok()?;
    
    let pid_stdout = String::from_utf8_lossy(&pid_output.stdout);
    // Parse out the numeric PID (e.g., "_NET_WM_PID(CARDINAL) = 12345")
    let pid_str = pid_stdout.split('=').nth(1)?.trim();
    pid_str.parse::<u32>().ok()
}
