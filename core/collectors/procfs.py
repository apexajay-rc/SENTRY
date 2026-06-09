"""
Traditional Linux metrics.

These measure utilization.

NOT pressure.
"""

import time


def _read_cpu():
    with open("/proc/stat", "r") as f:
        values = list(map(int, f.readline().split()[1:]))

    idle = values[3]
    total = sum(values)

    return idle, total


def get_cpu_usage():
    idle1, total1 = _read_cpu()

    time.sleep(0.5)

    idle2, total2 = _read_cpu()

    idle_delta = idle2 - idle1
    total_delta = total2 - total1

    if total_delta == 0:
        return 0.0

    usage = 100 * (1 - idle_delta / total_delta)

    return round(usage, 2)


def get_memory_usage():
    with open("/proc/meminfo", "r") as f:
        lines = f.readlines()

    mem_total = int(lines[0].split()[1])
    mem_available = int(lines[2].split()[1])

    mem_used = mem_total - mem_available

    return round((mem_used / mem_total) * 100, 2)


def get_swap_usage():
    with open("/proc/meminfo", "r") as f:
        meminfo = {}

        for line in f:
            parts = line.split()

            if len(parts) >= 2:
                meminfo[parts[0].rstrip(":")] = int(parts[1])

    swap_total = meminfo.get("SwapTotal", 0)
    swap_free = meminfo.get("SwapFree", 0)

    if swap_total == 0:
        return 0.0

    swap_used = swap_total - swap_free

    return round((swap_used / swap_total) * 100, 2)


def collect_procfs():
    return {
        "cpu_percent": get_cpu_usage(),
        "memory_percent": get_memory_usage(),
        "swap_percent": get_swap_usage(),
    }
