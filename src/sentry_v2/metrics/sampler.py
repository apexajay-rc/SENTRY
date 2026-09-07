from dataclasses import dataclass
from typing import Optional
import os

@dataclass(frozen=True)
class SystemSample:
    cpu_pct: float
    mem_pct: float
    io_wait_pct: float
    psi_cpu: Optional[float]
    psi_mem: Optional[float]
    psi_io: Optional[float]

class MetricsSampler:
    def __init__(self, interval: float = 1.0, psi_interval: float = 10.0):
        self.interval = interval
        self.psi_interval = psi_interval
        self._prev_stat = None
        self._psi_counter = 0
        self.last_total_delta = 0.0  # Expose system delta for Scanner

    def sample(self) -> SystemSample:
        stat = self._read_proc_stat()
        cpu_pct, io_pct = self._calc_cpu_io(stat)
        self._prev_stat = stat
        mem_pct = self._read_mem_pct()
        
        psi_cpu = psi_mem = psi_io = None
        self._psi_counter += self.interval
        if self._psi_counter >= self.psi_interval:
            psi_cpu, psi_mem, psi_io = self._read_psi()
            self._psi_counter = 0

        return SystemSample(cpu_pct, mem_pct, io_pct, psi_cpu, psi_mem, psi_io)

    def _read_proc_stat(self) -> list[int]:
        with open("/proc/stat", "r") as f:
            line = f.readline()
        return list(map(int, line.split()[1:]))

    def _calc_cpu_io(self, cur: list[int]) -> tuple[float, float]:
        if self._prev_stat is None:
            self.last_total_delta = 0.0
            return 0.0, 0.0
        prev = self._prev_stat
        total_delta = sum(cur) - sum(prev)
        self.last_total_delta = float(total_delta)  # Track the delta
        
        if total_delta <= 0: return 0.0, 0.0
        idle_delta = cur[3] - prev[3]
        iowait_delta = cur[4] - prev[4]
        cpu_pct = 100.0 * (1.0 - idle_delta / total_delta)
        io_pct = 100.0 * (iowait_delta / total_delta)
        return round(cpu_pct, 2), round(io_pct, 2)

    def _read_mem_pct(self) -> float:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                k, v = line.split(":", 1)
                meminfo[k] = int(v.split()[0])
        total = meminfo["MemTotal"]
        avail = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        return round(100.0 * (total - avail) / total, 2)

    def _read_psi(self) -> tuple[Optional[float], Optional[float], Optional[float]]:
        def read_one(res: str) -> Optional[float]:
            try:
                with open(f"/proc/pressure/{res}", "r") as f:
                    content = f.read()
                for line in content.splitlines():
                    if line.startswith("some "):
                        return float(line.split("avg10=")[1].split()[0])
            except: return None
        return (read_one("cpu"), read_one("memory"), read_one("io"))
