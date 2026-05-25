import os


def reduce_priority(pid):
    try:
        os.system(f"renice +5 -p {pid} >/dev/null 2>&1")
        return f"Priority reduced (PID {pid})"
    except:
        return "Priority reduction failed"


def noop(pid):
    return "No action (safe mode)"
