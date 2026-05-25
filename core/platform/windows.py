import time
import psutil


def calculate_cpu():
    """
    Uses blocking interval for stable measurement.
    """
    return round(psutil.cpu_percent(interval=0.5), 2)


def get_memory_usage():
    mem = psutil.virtual_memory()
    return round(mem.percent, 2)


def get_io_wait():
    """
    Windows does not expose iowait cleanly.
    We return 0.0 as a safe neutral placeholder.
    """
    return 0.0


def get_top_process():
    """
    Returns:
        (pid:str, name:str, score:float)
        or (None, None, None)
    """
    try:
        processes = []

        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                cpu = proc.info['cpu_percent']
                mem = proc.info['memory_percent']

                # Skip processes with no meaningful data
                if cpu is None or mem is None:
                    continue

                score = (0.7 * cpu) + (0.3 * mem)

                processes.append((score, proc.info))

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not processes:
            return None, None, None

        processes.sort(reverse=True, key=lambda x: x[0])

        best = processes[0][1]

        return (
            str(best['pid']),
            best['name'],
            round((0.7 * best['cpu_percent'] + 0.3 * best['memory_percent']), 2)
        )

    except Exception:
        return None, None, None
