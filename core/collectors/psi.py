"""
PSI Collector

Reads Linux Pressure Stall Information (PSI)
from the kernel.

Sources:
    /proc/pressure/cpu
    /proc/pressure/memory
    /proc/pressure/io
"""


def _read_pressure_file(path):
    data = {}

    try:
        with open(path, "r") as f:
            lines = f.readlines()

        for line in lines:
            parts = line.strip().split()

            pressure_type = parts[0]
            metrics = {}

            for item in parts[1:]:
                key, value = item.split("=")

                if key == "total":
                    metrics[key] = int(value)
                else:
                    metrics[key] = float(value)

            data[pressure_type] = metrics

    except Exception as e:
        data["error"] = str(e)

    return data


def get_cpu_pressure():
    return _read_pressure_file("/proc/pressure/cpu")


def get_memory_pressure():
    return _read_pressure_file("/proc/pressure/memory")


def get_io_pressure():
    return _read_pressure_file("/proc/pressure/io")


def collect_psi():
    return {
        "cpu": get_cpu_pressure(),
        "memory": get_memory_pressure(),
        "io": get_io_pressure(),
    }
