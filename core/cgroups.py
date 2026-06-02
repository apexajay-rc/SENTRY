"""
cgroups v2 resource control module for SENTRY.
Manages CPU, memory, and I/O limits via kernel cgroups.
"""

import os
import logging

CGROUP_PATH = "/sys/fs/cgroup/sentry_bg"
logger = logging.getLogger(__name__)


def setup_cgroup():
    """Initialize SENTRY cgroup hierarchy."""
    try:
        os.makedirs(CGROUP_PATH, exist_ok=True)
        logger.info(f"Cgroup initialized at {CGROUP_PATH}")
    except Exception as e:
        logger.warning(f"Failed to setup cgroup: {e}")


def add_process(pid):
    """
    Add process to SENTRY cgroup.
    
    Args:
        pid (int/str): Process ID to add
    """
    try:
        cgroup_procs = f"{CGROUP_PATH}/cgroup.procs"
        with open(cgroup_procs, "w") as f:
            f.write(str(pid))
        logger.debug(f"Added PID {pid} to cgroup")
    except Exception as e:
        logger.warning(f"Failed to add PID {pid} to cgroup: {e}")


def set_cpu_weight(weight=50):
    """
    Set CPU weight for cgroup (cgroups v2).
    
    Args:
        weight (int): CPU weight [1-10000]. 
                      1 = heavily throttled, 10000 = no limit
                      Default 100 = proportional, 50 = 50% share
    """
    try:
        cpu_weight_file = f"{CGROUP_PATH}/cpu.weight"
        with open(cpu_weight_file, "w") as f:
            f.write(str(weight))
        logger.debug(f"Set CPU weight to {weight}")
    except Exception as e:
        logger.warning(f"Failed to set CPU weight: {e}")


def set_memory_limit(memory_bytes):
    """
    Set hard memory limit for cgroup.
    
    Args:
        memory_bytes (int): Hard limit in bytes
                           0 = no limit
    """
    try:
        if memory_bytes <= 0:
            # Remove limit if invalid
            memory_limit_file = f"{CGROUP_PATH}/memory.max"
            with open(memory_limit_file, "w") as f:
                f.write("max")
            logger.debug("Removed memory limit")
        else:
            memory_limit_file = f"{CGROUP_PATH}/memory.max"
            with open(memory_limit_file, "w") as f:
                f.write(str(memory_bytes))
            logger.debug(f"Set memory limit to {memory_bytes} bytes")
    except Exception as e:
        logger.warning(f"Failed to set memory limit: {e}")


def set_memory_limit_percent(percent):
    """
    Set memory limit as percentage of process RSS.
    
    Args:
        percent (int): Percentage [1-100]
    """
    try:
        if percent < 1 or percent > 100:
            logger.warning(f"Invalid memory percent: {percent}")
            return
        
        # Get current memory usage
        memory_current_file = f"{CGROUP_PATH}/memory.current"
        try:
            with open(memory_current_file, "r") as f:
                current_bytes = int(f.read().strip())
        except:
            logger.warning("Could not read current memory usage")
            return
        
        # Calculate limit
        limit_bytes = max(1, int(current_bytes * percent / 100))
        set_memory_limit(limit_bytes)
        
    except Exception as e:
        logger.warning(f"Failed to set memory limit percent: {e}")


def set_io_weight(weight=50):
    """
    Set I/O weight for cgroup (cgroups v2).
    
    Args:
        weight (int): I/O weight [1-10000].
                      1 = heavily throttled, 10000 = no limit
                      Default 100 = proportional
    """
    try:
        io_weight_file = f"{CGROUP_PATH}/io.weight"
        with open(io_weight_file, "w") as f:
            f.write(str(weight))
        logger.debug(f"Set I/O weight to {weight}")
    except Exception as e:
        logger.warning(f"Failed to set I/O weight: {e}")


def set_io_max(device, riops, wiops):
    """
    Set I/O rate limits per device.
    
    Args:
        device (str): Device name (e.g., "8:0" for /dev/sda)
        riops (int): Read IOPS limit (0 = unlimited)
        wiops (int): Write IOPS limit (0 = unlimited)
    """
    try:
        io_max_file = f"{CGROUP_PATH}/io.max"
        
        if riops <= 0 and wiops <= 0:
            # Remove limit for device
            with open(io_max_file, "w") as f:
                f.write(f"{device} riops=max wiops=max\n")
            logger.debug(f"Removed I/O limits for {device}")
        else:
            riops_str = f"riops={riops}" if riops > 0 else "riops=max"
            wiops_str = f"wiops={wiops}" if wiops > 0 else "wiops=max"
            
            with open(io_max_file, "w") as f:
                f.write(f"{device} {riops_str} {wiops_str}\n")
            logger.debug(f"Set I/O limits for {device}: {riops_str}, {wiops_str}")
            
    except Exception as e:
        logger.warning(f"Failed to set I/O limits: {e}")


def reset_all_limits():
    """Remove all limits from SENTRY cgroup."""
    try:
        # Reset CPU weight to default (100)
        set_cpu_weight(100)
        
        # Reset memory limit to max
        set_memory_limit(0)
        
        # Reset I/O weight to default (100)
        set_io_weight(100)
        
        logger.info("Reset all cgroup limits to defaults")
    except Exception as e:
        logger.warning(f"Failed to reset cgroup limits: {e}")


def get_cgroup_memory_usage():
    """
    Get current memory usage of cgroup.
    
    Returns:
        int: Memory in bytes, or None if unavailable
    """
    try:
        memory_current_file = f"{CGROUP_PATH}/memory.current"
        with open(memory_current_file, "r") as f:
            return int(f.read().strip())
    except Exception as e:
        logger.debug(f"Could not read cgroup memory: {e}")
        return None


def get_cgroup_memory_limit():
    """
    Get current memory limit of cgroup.
    
    Returns:
        int: Memory limit in bytes, or None if no limit
    """
    try:
        memory_max_file = f"{CGROUP_PATH}/memory.max"
        with open(memory_max_file, "r") as f:
            content = f.read().strip()
            if content == "max":
                return None
            return int(content)
    except Exception as e:
        logger.debug(f"Could not read cgroup memory limit: {e}")
        return None
