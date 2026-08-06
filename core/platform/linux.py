import time
import subprocess


def _read_proc_stat():
    with open('/proc/stat', 'r') as f:
        values = list(map(int, f.readline().split()[1:]))
    idle = values[3]
    iowait = values[4]
    total = sum(values)
    return idle, iowait, total


def calculate_cpu():
    idle1, _, total1 = _read_proc_stat()
    time.sleep(0.5)
    idle2, _, total2 = _read_proc_stat()

    idle_delta = idle2 - idle1
    total_delta = total2 - total1

    if total_delta == 0:
        return 0.0

    cpu = 100 * (1 - idle_delta / total_delta)
    return round(cpu, 2)


def get_memory_usage():
    with open('/proc/meminfo', 'r') as f:
        lines = f.readlines()

    mem_total = int(lines[0].split()[1])
    mem_available = int(lines[2].split()[1])

    mem_used = mem_total - mem_available

    if mem_total == 0:
        return 0.0

    return round((mem_used / mem_total) * 100, 2)


def get_io_wait():
    _, iowait, total = _read_proc_stat()

    if total == 0:
        return 0.0

    return round((iowait / total) * 100, 2)


def get_top_process():
    """
    Returns:
        (pid:str, name:str, score:float)
        or (None, None, None)
    """
    try:
        output = subprocess.check_output(
            ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"],
            stderr=subprocess.DEVNULL
        ).decode().splitlines()

        best_pid = None
        best_name = None
        best_score = -1.0

        for line in output[1:]:
            parts = line.split()

            if len(parts) < 4:
                continue

            pid = parts[0]
            name = parts[1]

            try:
                cpu = float(parts[2])
                mem = float(parts[3])
            except ValueError:
                continue

            score = (0.7 * cpu) + (0.3 * mem)

            if score > best_score:
                best_score = score
                best_pid = pid
                best_name = name

        if best_pid:
            return best_pid, best_name, round(best_score, 2)

        return None, None, None

    except Exception:
        return None, None, None
