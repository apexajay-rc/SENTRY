"""
Process Collector

Identifies active workloads.
"""

import psutil


def get_process_snapshot():
    processes = []

    for proc in psutil.process_iter(
        ["pid", "name", "cpu_percent", "memory_percent"]
    ):
        try:
            processes.append(
                {
                    "pid": proc.info["pid"],
                    "name": proc.info["name"],
                    "cpu": proc.info["cpu_percent"],
                    "memory": round(
                        proc.info["memory_percent"], 2
                    ),
                }
            )

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            psutil.ZombieProcess,
        ):
            continue

    return processes


def get_top_cpu_processes(limit=10):
    processes = get_process_snapshot()

    processes.sort(
        key=lambda p: p["cpu"],
        reverse=True
    )

    return processes[:limit]


def get_top_memory_processes(limit=10):
    processes = get_process_snapshot()

    processes.sort(
        key=lambda p: p["memory"],
        reverse=True
    )

    return processes[:limit]
