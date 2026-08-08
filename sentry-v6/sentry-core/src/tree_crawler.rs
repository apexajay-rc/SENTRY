use std::collections::{HashMap, HashSet, VecDeque};
use std::fs;

/// Crawls /proc to build an adjacency list and returns all descendants of the root PID.
pub fn get_process_tree(root_pid: u32) -> HashSet<u32> {
    let mut tree = HashSet::new();
    tree.insert(root_pid);

    // Read all PIDs and their Parent PIDs (PPID) from /proc
    let ppid_map = build_ppid_map();

    // Breadth-First Search to find all children, grandchildren, etc.
    let mut queue = VecDeque::new();
    queue.push_back(root_pid);

    while let Some(current_pid) = queue.pop_front() {
        if let Some(children) = ppid_map.get(&current_pid) {
            for &child_pid in children {
                if tree.insert(child_pid) {
                    queue.push_back(child_pid);
                }
            }
        }
    }

    tree
}

/// Scans /proc to map out PPID -> [Child PIDs]
fn build_ppid_map() -> HashMap<u32, Vec<u32>> {
    let mut ppid_map: HashMap<u32, Vec<u32>> = HashMap::new();

    let proc_dir = match fs::read_dir("/proc") {
        Ok(dir) => dir,
        Err(_) => return ppid_map,
    };

    for entry in proc_dir.flatten() {
        let file_name = entry.file_name();
        let pid_str = file_name.to_string_lossy();
        
        if let Ok(pid) = pid_str.parse::<u32>() {
            let stat_path = format!("/proc/{}/stat", pid);
            if let Ok(stat_text) = fs::read_to_string(&stat_path) {
                if let Some(ppid) = parse_ppid(&stat_text) {
                    ppid_map.entry(ppid).or_default().push(pid);
                }
            }
        }
    }

    ppid_map
}

/// Safely extracts the PPID from the /proc/[pid]/stat line.
/// Format is: pid (comm) state ppid ...
fn parse_ppid(stat_text: &str) -> Option<u32> {
    // Process names can contain parentheses e.g. "123 (my app (1)) S 100"
    // Find the LAST closing parenthesis to safely split the string.
    let rparen_idx = stat_text.rfind(')')?;
    
    // The slice after the last ')' looks like: " S 100 200 ..."
    let rest = &stat_text[rparen_idx + 1..];
    
    let mut parts = rest.split_whitespace();
    parts.next(); // Skip the 'state' field (e.g., "S")
    
    // The next field is the PPID
    parts.next()?.parse::<u32>().ok()
}
