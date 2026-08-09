use std::collections::HashMap;
use std::fs;

#[derive(Debug, Clone)]
pub struct CpuTopology {
    pub p_cores: Vec<u32>,
    pub e_cores: Vec<u32>,
}

/// Scans the physical motherboard topology to separate High-Performance (P-Cores)
/// from High-Efficiency (E-Cores) by analyzing hardware max frequencies.
pub fn build_core_map() -> CpuTopology {
    let mut freq_map: HashMap<u64, Vec<u32>> = HashMap::new();
    let mut all_cpus: Vec<u32> = Vec::new();

    // 1. Traverse the Linux sysfs CPU directory
    if let Ok(entries) = fs::read_dir("/sys/devices/system/cpu") {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let name_str = name.to_string_lossy();

            // 2. Identify logical CPU folders (e.g., "cpu0", "cpu12")
            if name_str.starts_with("cpu") {
                // Safely parse the number after "cpu". If it fails, it's a folder like "cpuidle"
                if let Ok(cpu_id) = name_str[3..].parse::<u32>() {
                    all_cpus.push(cpu_id);

                    // 3. Read the exact hardware max frequency for this specific core
                    let freq_path = format!("/sys/devices/system/cpu/{}/cpufreq/cpuinfo_max_freq", name_str);
                    if let Ok(freq_str) = fs::read_to_string(freq_path) {
                        if let Ok(freq) = freq_str.trim().parse::<u64>() {
                            freq_map.entry(freq).or_default().push(cpu_id);
                        }
                    }
                }
            }
        }
    }

    all_cpus.sort_unstable();

    // FALLBACK: If we are in a VM or a kernel missing cpufreq drivers, 
    // we default all discovered cores to P-Cores to prevent crashing.
    if freq_map.is_empty() {
        return CpuTopology {
            p_cores: all_cpus,
            e_cores: Vec::new(),
        };
    }

    // 4. Sort the frequencies from Highest (P-Cores) to Lowest (E-Cores)
    let mut unique_freqs: Vec<u64> = freq_map.keys().copied().collect();
    unique_freqs.sort_unstable_by(|a, b| b.cmp(a)); // Descending sort

    // The absolute highest frequency bracket belongs to the P-Cores
    let mut p_cores = freq_map.remove(&unique_freqs[0]).unwrap_or_default();
    p_cores.sort_unstable();

    // Any remaining frequency brackets are grouped together as E-Cores
    let mut e_cores = Vec::new();
    for freq in unique_freqs.iter().skip(1) {
        if let Some(mut cores) = freq_map.remove(freq) {
            e_cores.append(&mut cores);
        }
    }
    e_cores.sort_unstable();
    
    // --- THE UNIVERSAL ROUTER FALLBACK ---
    // If there are no E-Cores (Homogeneous CPU), we mathematically partition the array.
    // 75% dedicated exclusively to VIPs, 25% quarantined for background OS tasks.
    if e_cores.is_empty() && p_cores.len() > 1 {
        let split_idx = std::cmp::max(1, (p_cores.len() * 3) / 4);
        e_cores = p_cores[split_idx..].to_vec(); // The last 25%
        p_cores = p_cores[0..split_idx].to_vec(); // The first 75%
    }
    CpuTopology { p_cores, e_cores }
}
