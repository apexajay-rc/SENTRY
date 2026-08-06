import os
import re
from dataclasses import dataclass
from typing import Optional

PROC_ROOT = os.environ.get("SENTRY_PROC_ROOT", "/proc")


def proc_path(*parts: str) -> str:
    return os.path.join(PROC_ROOT, *parts)


@dataclass(frozen=True)
class CpuStatSnapshot:
    idle: int
    iowait: int
    total: int


@dataclass(frozen=True)
class ProcessSnapshot:
    pid: int
    comm: str
    utime: int
    stime: int
    rss_kb: int

    @property
    def cpu_jiffies(self) -> int:
        return self.utime + self.stime


@dataclass(frozen=True)
class PsiReading:
    some_avg10: float
    full_avg10: float


def read_system_stat(proc_root: str = PROC_ROOT) -> CpuStatSnapshot:
    with open(os.path.join(proc_root, "stat"), "r", encoding="utf-8") as handle:
        values = list(map(int, handle.readline().split()[1:]))

    idle = values[3]
    iowait = values[4]
    total = sum(values)
    return CpuStatSnapshot(idle=idle, iowait=iowait, total=total)


def cpu_usage_percent(previous: CpuStatSnapshot, current: CpuStatSnapshot) -> float:
    total_delta = current.total - previous.total
    if total_delta <= 0:
        return 0.0

    idle_delta = current.idle - previous.idle
    return round(100 * (1 - idle_delta / total_delta), 2)


def io_wait_percent(previous: CpuStatSnapshot, current: CpuStatSnapshot) -> float:
    total_delta = current.total - previous.total
    if total_delta <= 0:
        return 0.0

    iowait_delta = current.iowait - previous.iowait
    return round(100 * iowait_delta / total_delta, 2)


def read_memory_usage_percent(proc_root: str = PROC_ROOT) -> float:
    meminfo = {}
    with open(os.path.join(proc_root, "meminfo"), "r", encoding="utf-8") as handle:
        for line in handle:
            key, value = line.split(":", 1)
            meminfo[key.strip()] = int(value.strip().split()[0])

    total = meminfo["MemTotal"]
    available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
    used = total - available
    return round((used / total) * 100, 2)


def read_psi(resource: str, proc_root: str = PROC_ROOT) -> Optional[PsiReading]:
    path = os.path.join(proc_root, "pressure", resource)
    if not os.path.isfile(path):
        return None

    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()

    parsed = {}
    for line in lines:
        kind, rest = line.split(None, 1)
        parsed[kind] = rest

    some = _parse_psi_line(parsed.get("some", ""))
    full = _parse_psi_line(parsed.get("full", ""))
    if some is None or full is None:
        return None

    return PsiReading(some_avg10=some, full_avg10=full)


def _parse_psi_line(line: str) -> Optional[float]:
    match = re.search(r"avg10=([0-9.]+)", line)
    if not match:
        return None
    return float(match.group(1))


def parse_process_stat(raw: str) -> tuple[str, int, int]:
    close_paren = raw.rfind(")")
    if close_paren == -1:
        raise ValueError("Invalid /proc/pid/stat line")

    comm = raw[raw.find("(") + 1 : close_paren]
    fields = raw[close_paren + 2 :].split()
    utime = int(fields[11])
    stime = int(fields[12])
    return comm, utime, stime


def read_process_snapshot(pid: int, proc_root: str = PROC_ROOT) -> Optional[ProcessSnapshot]:
    stat_path = os.path.join(proc_root, str(pid), "stat")
    status_path = os.path.join(proc_root, str(pid), "status")

    if not os.path.isfile(stat_path):
        return None

    try:
        with open(stat_path, "r", encoding="utf-8") as handle:
            comm, utime, stime = parse_process_stat(handle.read())

        rss_kb = 0
        if os.path.isfile(status_path):
            with open(status_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        rss_kb = int(line.split()[1])
                        break

        return ProcessSnapshot(
            pid=pid,
            comm=comm,
            utime=utime,
            stime=stime,
            rss_kb=rss_kb,
        )
    except (OSError, ValueError, IndexError, PermissionError):
        return None


def list_process_ids(proc_root: str = PROC_ROOT) -> list[int]:
    pids = []
    for name in os.listdir(proc_root):
        if name.isdigit():
            pids.append(int(name))
    return pids
