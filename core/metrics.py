import time

def get_cpu_usage():
    with open('/proc/stat', 'r') as f:
        values = list(map(int, f.readline().split()[1:]))
    idle = values[3]
    total = sum(values)
    return idle, total

def calculate_cpu():
    idle1, total1 = get_cpu_usage()
    time.sleep(0.5)
    idle2, total2 = get_cpu_usage()

    idle_delta = idle2 - idle1
    total_delta = total2 - total1

    return round(100 * (1 - idle_delta / total_delta), 2)


def get_memory_usage():
    with open('/proc/meminfo', 'r') as f:
        lines = f.readlines()

    total = int(lines[0].split()[1])
    available = int(lines[2].split()[1])

    used = total - available
    return round((used / total) * 100, 2)


def get_io_wait():
    with open('/proc/stat', 'r') as f:
        values = list(map(int, f.readline().split()[1:]))

    iowait = values[4]
    total = sum(values)

    return round((iowait / total) * 100, 2)


def compute_stress(cpu, memory, io):
    return round((0.5 * cpu + 0.3 * memory + 0.2 * io) / 100, 2)
