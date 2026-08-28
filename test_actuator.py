import asyncio
import os
import signal
import subprocess
from pathlib import Path

class UserspaceActuator:
    """
    Fallback CPU throttling via SIGSTOP/SIGCONT Duty Cycling.
    Period = 100ms.
    """
    PERIOD_MS = 100 

    def __init__(self):
        self._tasks = {}

    async def apply_throttle(self, pid: int, quota_pct: int) -> None:
        if pid in self._tasks:
            self._tasks[pid].cancel()
        
        task = asyncio.create_task(self._duty_cycle(pid, quota_pct))
        self._tasks[pid] = task
        print(f"Userspace duty-cycle started for PID {pid} at {quota_pct}%")

    async def release_throttle(self, pid: int) -> None:
        if pid in self._tasks:
            self._tasks[pid].cancel()
            del self._tasks[pid]
            await self._send_signal(pid, signal.SIGCONT)
            print(f"Userspace throttle released for PID {pid}")

    async def _duty_cycle(self, pid: int, quota_pct: int) -> None:
        period_sec = self.PERIOD_MS / 1000.0
        on_sec = period_sec * (quota_pct / 100.0)
        off_sec = period_sec - on_sec
        
        try:
            while True:
                # Wake process up
                await self._send_signal(pid, signal.SIGCONT)
                if on_sec > 0:
                    await asyncio.sleep(on_sec)
                
                # Put process to sleep
                await self._send_signal(pid, signal.SIGSTOP)
                if off_sec > 0:
                    await asyncio.sleep(off_sec)
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
                        try:
                            os.kill(int(tid_str), sig)
                        except ProcessLookupError:
                            pass
        except ProcessLookupError:
            pass
        except PermissionError:
            pass

async def main():
    actuator = UserspaceActuator()
    
    proc = subprocess.Popen(["sha256sum", "/dev/zero"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid = proc.pid
    print(f"Started non-forking CPU hog (sha256sum) PID {pid}")
    
    print("Waiting 3 seconds for CPU spike...")
    await asyncio.sleep(3)
    
    print("\n>>> APPLYING USERSPACE (SIGSTOP) THROTTLE TO 30% <<<")
    await actuator.apply_throttle(pid, 30)
    
    print("Holding limit for 15 seconds. CHECK HTOP NOW!")
    await asyncio.sleep(15)
    
    print("\n>>> RELEASING THROTTLE <<<")
    await actuator.release_throttle(pid)
    print("Check htop! It should instantly return to 100%.")
    
    await asyncio.sleep(5)
    proc.terminate()
    print("Test complete.")

if __name__ == "__main__":
    asyncio.run(main())
