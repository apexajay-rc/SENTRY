use std::collections::{HashMap, HashSet};
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::process::Command;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

// ==========================================
// KERNEL/SYS UTILITIES & IPC TRACING
// ==========================================

#[derive(Clone, Copy, PartialEq)]
pub enum PenaltyPhase {
    GracePeriod, // Cgroup 20% clamp
    DeepSleep,   // SIGSTOP (0.0% CPU)
}

fn append_audit_log(action: &str, pid: u32, details: &str) {
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open("/var/log/sentry_audit.log") {
        let ts = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        let log_line = format!(r#"{{"ts": {}, "action": "{}", "pid": {}, "details": "{}"}}"#, ts, action, pid, details);
        let _ = writeln!(file, "{}", log_line);
    }
}

fn get_process_start_time(pid: u32) -> u64 {
    if let Ok(stat_contents) = fs::read_to_string(format!("/proc/{}/stat", pid)) {
        if let Some(rparen) = stat_contents.rfind(')') {
            let parts: Vec<&str> = stat_contents[rparen + 1..].split_whitespace().collect();
            if parts.len() >= 20 {
                return parts[19].parse().unwrap_or(0); 
            }
        }
    }
    0
}

fn get_pgid(pid: u32) -> u32 {
    if let Ok(stat_contents) = fs::read_to_string(format!("/proc/{}/stat", pid)) {
        if let Some(rparen) = stat_contents.rfind(')') {
            let parts: Vec<&str> = stat_contents[rparen + 1..].split_whitespace().collect();
            if parts.len() >= 3 {
                return parts[2].parse().unwrap_or(0); 
            }
        }
    }
    0
}

fn get_ipc_inodes(pid: u32) -> HashSet<u64> {
    let mut inodes = HashSet::new();
    if let Ok(entries) = fs::read_dir(format!("/proc/{}/fd", pid)) {
        for entry in entries.flatten() {
            if let Ok(path) = fs::read_link(entry.path()) {
                let path_str = path.to_string_lossy();
                if path_str.starts_with("socket:[") || path_str.starts_with("pipe:[") {
                    if let (Some(start), Some(end)) = (path_str.find('['), path_str.find(']')) {
                        if let Ok(inode) = path_str[start + 1..end].parse::<u64>() {
                            inodes.insert(inode);
                        }
                    }
                }
            }
        }
    }
    inodes
}

// THE SOCKET ORACLE
fn is_safe_to_freeze(pid: u32) -> bool {
    if let Ok(entries) = fs::read_dir(format!("/proc/{}/fd", pid)) {
        for entry in entries.flatten() {
            if let Ok(path) = fs::read_link(entry.path()) {
                if path.to_string_lossy().starts_with("socket:[") {
                    return false; // Holds network or audio pipes. Unsafe to freeze.
                }
            }
        }
    }
    true
}

// ==========================================
// 1. CGROUP MANAGER (The Actuator)
// ==========================================
pub struct CgroupManager {
    base_path: String,
}

impl CgroupManager {
    pub fn new() -> Self {
        let path = "/sys/fs/cgroup/sentry_throttle".to_string();
        let _ = fs::create_dir_all(&path);
        CgroupManager { base_path: path }
    }

    pub fn apply_cpu_throttle(&self, pid: u32, name: &str) {
        let procs_path = format!("{}/cgroup.procs", self.base_path);
        if let Ok(mut file) = OpenOptions::new().write(true).open(&procs_path) {
            if file.write_all(format!("{}\n", pid).as_bytes()).is_ok() {
                let max_path = format!("{}/cpu.max", self.base_path);
                if let Ok(mut max_file) = OpenOptions::new().write(true).open(&max_path) {
                    let _ = max_file.write_all(b"20000 100000\n");
                    println!("[ACTION] GRACE PERIOD INITIATED (20% CPU): {} (PID {})", name, pid);
                    append_audit_log("CLAMP_CPU", pid, name);
                }
            }
        }
    }

    pub fn apply_memory_throttle(&self, pid: u32, name: &str) {
        let procs_path = format!("{}/cgroup.procs", self.base_path);
        if let Ok(mut file) = OpenOptions::new().write(true).open(&procs_path) {
            if file.write_all(format!("{}\n", pid).as_bytes()).is_ok() {
                let mem_path = format!("{}/memory.high", self.base_path);
                if let Ok(mut mem_file) = OpenOptions::new().write(true).open(&mem_path) {
                    let _ = mem_file.write_all(b"52428800\n"); 
                    println!("[ACTION] GRACE PERIOD INITIATED (RAM): {} (PID {})", name, pid);
                    append_audit_log("CLAMP_RAM", pid, name);
                }
            }
        }
    }

    pub fn release_process(&self, pid: u32) {
        // Move process back to the root cgroup to instantly lift all hardware restrictions
        if let Ok(mut file) = OpenOptions::new().write(true).open("/sys/fs/cgroup/cgroup.procs") {
            let _ = file.write_all(format!("{}\n", pid).as_bytes());
        }
    }
}

// ==========================================
// 2. MEMORY PROFILER (PSI Sensor)
// ==========================================
pub struct MemoryProfiler {
    cgroup_manager: CgroupManager,
}

impl MemoryProfiler {
    pub fn new() -> Self {
        MemoryProfiler {
            cgroup_manager: CgroupManager::new(),
        }
    }

    pub fn check_pressure_and_clamp(&self, vip_pid: u32, observe_only: bool, throttled_tasks: &mut HashMap<u32, (u64, u64, PenaltyPhase)>, now: u64) {
        if let Ok(psi_data) = fs::read_to_string("/proc/pressure/memory") {
            if let Some(some_line) = psi_data.lines().find(|l| l.starts_with("some")) {
                if let Some(avg10) = some_line.split_whitespace().find(|p| p.starts_with("avg10=")) {
                    if let Ok(pressure) = avg10[6..].parse::<f64>() {
                        if pressure > 5.0 {
                            println!("[WARNING] HIGH MEMORY PRESSURE DETECTED ({}%)", pressure);
                            if !observe_only {
                                self.hunt_and_clamp(vip_pid, throttled_tasks, now);
                            }
                        }
                    }
                }
            }
        }
    }

    fn hunt_and_clamp(&self, vip_pid: u32, throttled_tasks: &mut HashMap<u32, (u64, u64, PenaltyPhase)>, now: u64) {
        let mut max_rss = 0;
        let mut target_pid = 0;
        let mut target_name = String::new();

        let vip_pgid = get_pgid(vip_pid);
        let vip_inodes = get_ipc_inodes(vip_pid);

        if let Ok(entries) = fs::read_dir("/proc") {
            for entry in entries.flatten() {
                if let Ok(file_type) = entry.file_type() {
                    if file_type.is_dir() {
                        if let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() {
                            if pid != vip_pid && pid != 0 && !throttled_tasks.contains_key(&pid) {
                                if let Ok(statm) = fs::read_to_string(format!("/proc/{}/statm", pid)) {
                                    let parts: Vec<&str> = statm.split_whitespace().collect();
                                    if parts.len() > 1 {
                                        if let Ok(rss) = parts[1].parse::<u64>() {
                                            if rss > max_rss {
                                                max_rss = rss;
                                                target_pid = pid;
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        if target_pid != 0 {
            if let Ok(stat_contents) = fs::read_to_string(format!("/proc/{}/stat", target_pid)) {
                let name = stat_contents.split_whitespace().nth(1).unwrap_or("").trim_matches(|c| c == '(' || c == ')');
                target_name = name.to_string();
            }

            let target_pgid = get_pgid(target_pid);
            if target_pgid == vip_pgid && target_pgid != 0 {
                return;
            }

            let target_inodes = get_ipc_inodes(target_pid);
            if !vip_inodes.is_disjoint(&target_inodes) {
                return;
            }

            let start_time = get_process_start_time(target_pid);
            self.cgroup_manager.apply_memory_throttle(target_pid, &target_name);
            throttled_tasks.insert(target_pid, (now + 60, start_time, PenaltyPhase::GracePeriod));
        }
    }
}

// ==========================================
// 3. CPU PROFILER (Topology Aware)
// ==========================================
pub struct CpuProfiler {
    core_count: u64,
    previous_ticks: HashMap<u32, u64>,
    pub throttled_tasks: HashMap<u32, (u64, u64, PenaltyPhase)>, 
    cgroup_manager: CgroupManager,
}

impl CpuProfiler {
    pub fn new() -> Self {
        let cores = thread::available_parallelism().map(|n| n.get()).unwrap_or(4) as u64;
        println!("[INFO] Hardware Topography Scanned: {} Logical Cores Detected", cores);
        
        CpuProfiler {
            core_count: cores,
            previous_ticks: HashMap::new(),
            throttled_tasks: HashMap::new(),
            cgroup_manager: CgroupManager::new(),
        }
    }

    pub fn emergency_release(&mut self, vip_pid: u32) {
        let vip_pgid = get_pgid(vip_pid);
        let mut to_release = Vec::new();
        
        for (&pid, tuple) in self.throttled_tasks.iter() {
            if pid == vip_pid || (vip_pgid != 0 && get_pgid(pid) == vip_pgid) {
                to_release.push((pid, tuple.2));
            }
        }

        for (pid, phase) in to_release {
            self.throttled_tasks.remove(&pid);
            println!("[CRYO] ⚡ VIP Focus Shift! Instant Resuscitation for PID {}", pid);
            
            if phase == PenaltyPhase::DeepSleep {
                let _ = Command::new("kill").arg("-SIGCONT").arg(pid.to_string()).status();
            }
            self.cgroup_manager.release_process(pid);
        }
    }

    pub fn scan_for_hogs(&mut self, vip_pid: u32, observe_only: bool, now: u64) {
        self.throttled_tasks.retain(|&pid, tuple| {
            let expiration = tuple.0;
            let start_time = tuple.1;
            let phase = &mut tuple.2;

            if now > expiration {
                println!("[INFO] Penalty Box expired. Releasing PID {}", pid);
                if *phase == PenaltyPhase::DeepSleep {
                    let _ = Command::new("kill").arg("-SIGCONT").arg(pid.to_string()).status();
                }
                self.cgroup_manager.release_process(pid);
                false
            } else {
                let current_start = get_process_start_time(pid);
                if current_start == 0 {
                    self.cgroup_manager.release_process(pid);
                    false
                } else if current_start != start_time {
                    println!("[WARNING] TOCTOU DETECTED! PID {} recycled. Purging record.", pid);
                    self.cgroup_manager.release_process(pid);
                    false
                } else {
                    // CRYO-BYPASS LOGIC: Enter deep sleep after 30 seconds
                    if *phase == PenaltyPhase::GracePeriod && expiration.saturating_sub(now) <= 30 {
                        if is_safe_to_freeze(pid) {
                            println!("[CRYO] Grace period ended. ❄️ Firing SIGSTOP on PID {}", pid);
                            let _ = Command::new("kill").arg("-SIGSTOP").arg(pid.to_string()).status();
                            *phase = PenaltyPhase::DeepSleep;
                        } else {
                            // Leave it in Grace Period to protect sockets
                            *phase = PenaltyPhase::GracePeriod;
                        }
                    }
                    true
                }
            }
        });

        let anomaly_threshold = if self.core_count > 4 { 15 } else { 12 };
        let sanity_bound = 50 * self.core_count;
        let max_actions_per_window = if self.core_count > 4 { 3 } else { 1 };
        let mut actions_this_window = 0;
        
        let mut current_ticks = HashMap::new();
        let vip_pgid = get_pgid(vip_pid);
        let vip_inodes = get_ipc_inodes(vip_pid);
        
        if let Ok(entries) = fs::read_dir("/proc") {
            for entry in entries.flatten() {
                if let Ok(file_type) = entry.file_type() {
                    if file_type.is_dir() {
                        if let Ok(pid) = entry.file_name().to_string_lossy().parse::<u32>() {
                            if let Ok(stat_contents) = fs::read_to_string(format!("/proc/{}/stat", pid)) {
                                if let Some(rparen) = stat_contents.rfind(')') {
                                    let parts: Vec<&str> = stat_contents[rparen + 1..].split_whitespace().collect();
                                    if parts.len() >= 15 {
                                        let utime: u64 = parts[11].parse().unwrap_or(0);
                                        let stime: u64 = parts[12].parse().unwrap_or(0);
                                        let total_ticks = utime + stime;
                                        
                                        current_ticks.insert(pid, total_ticks);
                                        
                                        if let Some(&prev_ticks) = self.previous_ticks.get(&pid) {
                                            let delta = total_ticks.saturating_sub(prev_ticks);
                                            
                                            if delta > anomaly_threshold && delta < sanity_bound && pid != vip_pid && pid != 0 && !self.throttled_tasks.contains_key(&pid) {
                                                let name = stat_contents[..rparen].split('(').nth(1).unwrap_or("UNKNOWN");
                                                
                                                let target_pgid = get_pgid(pid);
                                                if target_pgid == vip_pgid && target_pgid != 0 {
                                                    continue; 
                                                }

                                                let target_inodes = get_ipc_inodes(pid);
                                                if !vip_inodes.is_disjoint(&target_inodes) {
                                                    continue;
                                                }

                                                if actions_this_window >= max_actions_per_window {
                                                    continue;
                                                }
                                                
                                                if !observe_only {
                                                    let start_time = get_process_start_time(pid);
                                                    self.cgroup_manager.apply_cpu_throttle(pid, name);
                                                    self.throttled_tasks.insert(pid, (now + 60, start_time, PenaltyPhase::GracePeriod));
                                                    actions_this_window += 1;
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        self.previous_ticks = current_ticks;
    }
}

// ==========================================
// 4. MAIN DAEMON LOOP (The Heartbeat)
// ==========================================
fn main() -> io::Result<()> {
    let my_pid = std::process::id();
    let _ = Command::new("renice").arg("-n").arg("-20").arg("-p").arg(my_pid.to_string()).status();
    
    println!("=====================================================");
    println!("[INFO] SENTRY v5.0 (CRYO-BYPASS & HYBRID STATE) ONLINE");
    println!("=====================================================");
    println!("[INFO] Daemon Priority Elevated to -20 (Maximum)");

    let bridge_sock = "/run/sentry_bridge.sock";
    let hud_sock = "/run/sentry_hud.sock";
    
    for sock in [bridge_sock, hud_sock].iter() {
        if Path::new(sock).exists() { fs::remove_file(sock)?; }
    }

    let bridge_socket = UnixDatagram::bind(bridge_sock)?;
    let hud_socket = UnixDatagram::bind(hud_sock)?;
    bridge_socket.set_nonblocking(true)?; 
    hud_socket.set_nonblocking(true)?; 

    if let Ok(uid) = std::env::var("SUDO_UID") {
        let _ = Command::new("chown").arg(format!("{}:{}", uid, uid)).arg(bridge_sock).status();
        let _ = Command::new("chown").arg(format!("{}:{}", uid, uid)).arg(hud_sock).status();
    }
    fs::set_permissions(bridge_sock, fs::Permissions::from_mode(0o660))?;
    fs::set_permissions(hud_sock, fs::Permissions::from_mode(0o660))?;

    println!("[INFO] Secure Bridge & HUD Sockets Armed (0o660).");
    println!("[INFO] Entering 200ms Orbital Event Loop...\n");

    let mut buf = [0; 1024];
    let mut hud_buf = [0; 1024];
    let mut current_vip_pid: u32 = 0;
    let mut observe_only = false;
    
    let mut cpu_profiler = CpuProfiler::new();
    let mem_profiler = MemoryProfiler::new();

    loop {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();

        match bridge_socket.recv_from(&mut buf) {
            Ok((size, _)) => {
                let msg = String::from_utf8_lossy(&buf[..size]);
                if let Ok(pid) = msg.trim().parse::<u32>() {
                    // IF THE VIP CHANGES, TRIGGER INSTANT RESUSCITATION
                    if pid != current_vip_pid && pid != 0 {
                        current_vip_pid = pid;
                        cpu_profiler.emergency_release(current_vip_pid);
                    }
                }
            }
            Err(ref e) if e.kind() == io::ErrorKind::WouldBlock => {}
            Err(_) => {}
        }

        match hud_socket.recv_from(&mut hud_buf) {
            Ok((size, sender_addr)) => {
                let msg = String::from_utf8_lossy(&hud_buf[..size]);
                if msg.trim() == "TOGGLE_OBSERVE" {
                    observe_only = !observe_only;
                    println!("[INFO] Mode Changed: Observe Only = {}", observe_only);
                } else if msg.trim() == "STATUS" {
                    if let Some(client_path) = sender_addr.as_pathname() {
                     let mut tasks_json = Vec::new();
                        for (&pid, tuple) in &cpu_profiler.throttled_tasks {
                            let expire = tuple.0;
                            
                            // Pre-calculate exact relative seconds to prevent Python math errors
                            let time_left = expire.saturating_sub(now); 
                            
                            let phase = if tuple.2 == PenaltyPhase::DeepSleep { "[FROZEN]" } else { "[CLAMPED]" };
                            let name = fs::read_to_string(format!("/proc/{}/comm", pid)).unwrap_or_else(|_| "UNKNOWN\n".to_string());
                            
                            // Keep the name pristine. Pass time_left to both keys to guarantee the TUI catches it.
                            tasks_json.push(format!(r#"{{"pid": {}, "name": "{}", "phase": "{}", "expire_in": {}, "time_remaining": {}}}"#, 
                                pid, name.trim(), phase, time_left, time_left));
                        }
                        
                        let payload = format!(r#"{{"spatial_pid": {}, "observe_only": {}, "throttled_tasks": [{}]}}"#, 
                            current_vip_pid, observe_only, tasks_json.join(","));
                            
                        let _ = hud_socket.send_to(payload.as_bytes(), client_path);
                    }
                }
            }
            Err(ref e) if e.kind() == io::ErrorKind::WouldBlock => {}
            Err(_) => {}
        }

        cpu_profiler.scan_for_hogs(current_vip_pid, observe_only, now);
        mem_profiler.check_pressure_and_clamp(current_vip_pid, observe_only, &mut cpu_profiler.throttled_tasks, now);

        thread::sleep(Duration::from_millis(200));
    }
}
