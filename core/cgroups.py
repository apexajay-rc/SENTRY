import os

CGROUP_PATH = "/sys/fs/cgroup/sentry_bg"


def setup_cgroup():
    try:
        os.makedirs(CGROUP_PATH, exist_ok=True)
    except Exception:
        pass


def add_process(pid):
    try:
        with open(f"{CGROUP_PATH}/cgroup.procs", "w") as f:
            f.write(str(pid))
    except Exception:
        pass


def set_cpu_weight(weight=50):
    try:
        with open(f"{CGROUP_PATH}/cpu.weight", "w") as f:
            f.write(str(weight))
    except Exception:
        pass
