import asyncio, os, signal, logging
from pathlib import Path
from typing import Dict
from src.sentry_v2.actuator.protocol import ThrottleActuator, ThrottleSpec

logger = logging.getLogger("sentry.actuator.userspace")

class UserspaceActuator(ThrottleActuator):
    PERIOD_MS = 100 

    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}

    async def apply_throttle(self, pid: int, spec: ThrottleSpec) -> None:
        if pid in self._tasks: self._tasks[pid].cancel()
        
        # Ring-3 cannot do proportional weight. It falls back to quota regardless of mode.
        if spec.cpu_quota_pct >= 100:
            if pid in self._tasks: del self._tasks[pid]
            return
            
        self._tasks[pid] = asyncio.create_task(self._duty_cycle(pid, spec.cpu_quota_pct))

    async def release_throttle(self, pid: int) -> None:
        if pid in self._tasks:
            self._tasks[pid].cancel()
            del self._tasks[pid]
            await self._send_signal(pid, signal.SIGCONT)

    async def _duty_cycle(self, pid: int, quota_pct: int) -> None:
        period_sec = self.PERIOD_MS / 1000.0
        on_sec = period_sec * (quota_pct / 100.0)
        off_sec = period_sec - on_sec
        try:
            while True:
                await self._send_signal(pid, signal.SIGCONT)
                if on_sec > 0: await asyncio.sleep(on_sec)
                await self._send_signal(pid, signal.SIGSTOP)
                if off_sec > 0: await asyncio.sleep(off_sec)
        except asyncio.CancelledError:
            await self._send_signal(pid, signal.SIGCONT)
            raise

    async def _send_signal(self, pid: int, sig: int) -> None:
        try:
            os.kill(pid, sig)
            task_dir = Path(f"/proc/{pid}/task")
            if task_dir.exists():
                for tid_str in os.listdir(task_dir):
                    if tid_str != str(pid):
                        try: os.kill(int(tid_str), sig)
                        except: pass
        except: pass
