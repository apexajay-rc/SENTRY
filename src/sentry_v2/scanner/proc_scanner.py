import os
import heapq
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from src.sentry_v2.metrics.sampler import MetricsSampler
from src.sentry_v2.policy.fair_share import ProcessMetric

PROC_ROOT = Path("/proc")
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
READ_SIZE_STAT = 1024
READ_SIZE_STATM = 128

class JiffyRingBuffer:
    def __init__(self, capacity: int = 8192):
        self.capacity = capacity
        self.pids = [0] * capacity
        self.jiffies = [0] * capacity
        self.timestamps = [0.0] * capacity
        self.size = 0
        self._pid_to_index: dict[int, int] = {}

    def get(self, pid: int) -> int:
        idx = self._pid_to_index.get(pid)
        if idx is not None and self.pids[idx] == pid:
            return self.jiffies[idx]
        return 0

    def update_jiffies(self, pid: int, jiffies: int, timestamp: float) -> None:
        idx = self._pid_to_index.get(pid)
        if idx is not None and self.pids[idx] == pid:
            self.jiffies[idx] = jiffies
            self.timestamps[idx] = timestamp
            return
        
        if self.size < self.capacity:
            idx = self.size
            self.size += 1
        else:
            idx = self.size % self.capacity
            old_pid = self.pids[idx]
            self._pid_to_index.pop(old_pid, None)
        
        self.pids[idx] = pid
        self.jiffies[idx] = jiffies
        self.timestamps[idx] = timestamp
        self._pid_to_index[pid] = idx

    def cleanup_dead(self, active_pids: set[int]) -> None:
        dead = [pid for pid in self._pid_to_index if pid not in active_pids]
        for pid in dead:
            idx = self._pid_to_index.pop(pid)
            self.pids[idx] = 0
            self.jiffies[idx] = 0
            self.timestamps[idx] = 0.0

class ProcScanner:
    def __init__(self, sampler: MetricsSampler, max_hogs: int = 10):
        self.sampler = sampler
        self.max_hogs = max_hogs
        self.jiffy_ring = JiffyRingBuffer()

    def get_top_hogs(self, max_hogs: int = None) -> List[ProcessMetric]:
        if max_hogs is None:
            max_hogs = self.max_hogs

        sys_delta = self.sampler.last_total_delta
        if sys_delta <= 0:
            return []
        
        now = time.monotonic()
        pids = self._list_pids()
        if not pids:
            return []

        active_pids = set()
        heap = [] 

        for pid in pids:
            active_pids.add(pid)
            cpu_pct, rss_bytes = self._read_pid_metrics(pid, sys_delta, now)
            if cpu_pct > 0.0:
                if len(heap) < max_hogs:
                    heapq.heappush(heap, (-cpu_pct, pid, cpu_pct, rss_bytes))
                elif -heap[0][0] < cpu_pct:
                    heapq.heapreplace(heap, (-cpu_pct, pid, cpu_pct, rss_bytes))

        self.jiffy_ring.cleanup_dead(active_pids)

        result = []
        for neg_pct, pid, cpu_pct, rss_bytes in sorted(heap, reverse=True):
            result.append(ProcessMetric(pid=pid, cpu_pct=cpu_pct, rss_bytes=rss_bytes))
        return result

    def _list_pids(self) -> List[int]:
        try:
            return [int(name) for name in os.listdir(PROC_ROOT) if name.isdigit()]
        except OSError:
            return []

    def _read_pid_metrics(self, pid: int, sys_delta: int, now: float) -> tuple[float, int]:
        stat_path = f"/proc/{pid}/stat"
        try:
            with open(stat_path, 'rb') as f:
                data = f.read(READ_SIZE_STAT)
            if not data:
                return 0.0, 0
        except OSError:
            return 0.0, 0

        try:
            comm_end = data.rindex(b')')
            fields = data[comm_end + 2:].split()
            if len(fields) < 15:
                return 0.0, 0
            utime = int(fields[13])
            stime = int(fields[14])
            total_jiffies = utime + stime
        except (ValueError, IndexError):
            return 0.0, 0

        prev_jiffies = self.jiffy_ring.get(pid)
        proc_delta = total_jiffies - prev_jiffies
        if proc_delta <= 0:
            self.jiffy_ring.update_jiffies(pid, total_jiffies, now)
            return 0.0, 0
        
        cpu_pct = 100.0 * proc_delta / sys_delta
        self.jiffy_ring.update_jiffies(pid, total_jiffies, now)

        statm_path = f"/proc/{pid}/statm"
        try:
            with open(statm_path, 'rb') as f:
                data = f.read(READ_SIZE_STATM)
            if data:
                rss_pages = int(data.split()[1])
                rss_bytes = rss_pages * PAGE_SIZE
            else:
                rss_bytes = 0
        except (OSError, ValueError, IndexError):
            rss_bytes = 0

        return round(cpu_pct, 2), rss_bytes
