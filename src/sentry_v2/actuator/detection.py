import asyncio
import aiofiles
from pathlib import Path

async def cfs_bandwidth_available() -> bool:
    try:
        # A quick check to see if the kernel even exposes the cpu.max file at root
        # and allows us to read/write to our own cgroup test directory.
        test_cgroup = Path("/sys/fs/cgroup/sentry_probe")
        await aiofiles.os.makedirs(test_cgroup, exist_ok=True)
        async with aiofiles.open(test_cgroup / "cpu.max", "w") as f:
            await f.write("50000 100000")
        await aiofiles.os.rmdir(test_cgroup)
        return True
    except Exception:
        return False
