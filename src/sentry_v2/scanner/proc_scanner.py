import asyncio
import aiofiles
import os
from typing import List, Optional, Dict
from src.sentry_v2.policy.fair_share import ProcessMetric
from src.sentry_v2.metrics.sampler import MetricsSampler

PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")

class ProcScanner:
    def __init__(self, sampler: MetricsSampler, max_hogs: int = 10):
        self.sampler = sampler  # REMEDIATION 3: Dependency Injection
        self.max_hogs = max_hogs
        self._prev_jiffies: Dict[int, int] = {}
        self._sem = asyncio.Semaphore(256)  # REMEDIATION 5: Bounded Concurrency

    async def get_top_hogs(self, max_hogs: int) -> List[ProcessMetric]:
        sys_delta = self.sampler.last_total_delta
        if sys_delta <= 0: return []

        pids = await self._list_pids()
        
        async def _read_bounded(pid: int):
            async with self._sem:
                return await self._read_pid_metrics(pid, sys_delta)

        tasks = [_read_bounded(pid) for pid in pids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Cleanup dead PIDs from our memory map
        current_pids = set(pids)
        self._prev_jiffies = {k: v for k, v in self._prev_jiffies.items() if k in current_pids}
        
        metrics = [r for r in results if isinstance(r, ProcessMetric)]
        metrics.sort(key=lambda m: m.cpu_pct, reverse=True)
        return metrics[:max_hogs]

    async def _list_pids(self) -> List[int]:
        try:
            entries = os.listdir("/proc")
            return [int(e) for e in entries if e.isdigit()]
        except Exception: return []

    async def _read_pid_metrics(self, pid: int, sys_delta: float) -> Optional[ProcessMetric]:
        try:
            async with aiofiles.open(f"/proc/{pid}/stat", "r") as f:
                stat = await f.read()
            
            fields = stat.split()
            cur_jiffies = int(fields[13]) + int(fields[14])
            
            # REMEDIATION 3: Normalized True CPU Percentage
            prev_jiffies = self._prev_jiffies.get(pid, cur_jiffies)
            proc_delta = cur_jiffies - prev_jiffies
            self._prev_jiffies[pid] = cur_jiffies
            
            cpu_pct = 100.0 * (proc_delta / sys_delta) if sys_delta > 0 else 0.0

            async with aiofiles.open(f"/proc/{pid}/statm", "r") as f:
                statm = await f.read()
            rss_bytes = int(statm.split()[1]) * PAGE_SIZE

            return ProcessMetric(pid=pid, cpu_pct=round(cpu_pct, 2), rss_bytes=rss_bytes)
            
        except (FileNotFoundError, IndexError, ValueError, PermissionError):
            return None
