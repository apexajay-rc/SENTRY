from pathlib import Path

def cfs_bandwidth_available() -> bool:
    try:
        # A quick check to see if the kernel even exposes the cpu.max file at root
        # and allows us to read/write to our own cgroup test directory.
        test_cgroup = Path("/sys/fs/cgroup/sentry_probe")
        test_cgroup.mkdir(parents=True, exist_ok=True)
        with open(test_cgroup / "cpu.max", "w") as f:
            f.write("50000 100000")
        test_cgroup.rmdir()
        return True
    except Exception:
        return False
