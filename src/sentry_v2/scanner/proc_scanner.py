import asyncio
import aiofiles
import os
from typing import List, Optional
from src.sentry_v2.policy.fair_share import ProcessMetric

PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")

class ProcScanner:
    def __init__(self, max_hogs: int = 10):
        self.max_hogs = max_hogs

    async def get_top_hogs(self) -> List[ProcessMetric]:
        pids = await self._list_pids()
        
        # Read all /proc/pid/stat + statm concurrently
        tasks = [self._read_pid_metrics(pid) for pid in pids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        metrics = [r for r in results if isinstance(r, ProcessMetric)]
        metrics.sort(key=lambda m: m.cpu_pct, reverse=True)
        return metrics[:self.max_hogs]

    async def _list_pids(self) -> List[int]:
        try:
            # /proc is an in-memory tmpfs; standard os.listdir is instant and non-blocking
            entries = os.listdir("/proc")
            return [int(e) for e in entries if e.isdigit()]
        except Exception: 
            return []

    async def _read_pid_metrics(self, pid: int) -> Optional[ProcessMetric]:
        try:
            # Read stat (CPU jiffies)
            async with aiofiles.open(f"/proc/{pid}/stat", "r") as f:
                stat = await f.read()
            
            # Parse utime/stime (fields 14, 15 after comm)
            fields = stat.split()
            utime = int(fields[13])
            stime = int(fields[14])
            total_jiffies = utime + stime

            # Read statm (RSS in pages)
            async with aiofiles.open(f"/proc/{pid}/statm", "r") as f:
                statm = await f.read()
            rss_pages = int(statm.split()[1])
            rss_bytes = rss_pages * PAGE_SIZE

            # Return raw jiffies for ranking; actual % calculation handled downstream if needed
            return ProcessMetric(pid=pid, cpu_pct=float(total_jiffies), rss_bytes=rss_bytes)
            
        except (FileNotFoundError, IndexError, ValueError, PermissionError):
            # Process died during scan or is restricted
            return None
