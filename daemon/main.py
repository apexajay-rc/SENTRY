import time
import os
import signal
from collections import deque
from datetime import datetime

from core.platform_adapter import (
    calculate_cpu,
    get_memory_usage,
    get_io_wait,
    get_top_process,
    PLATFORM
)
from core.metrics import compute_stress
from core.policy import classify_basic

LOG_FILE = "sentry_log.txt"

stress_history = deque(maxlen=5)
last_mitigated = {}
paused_processes = {}

CRITICAL_PROCESSES = [
    "systemd",
    "gnome-shell",
    "Xorg",
    "pulseaudio",
    "pipewire",
    "python3",
    "ps"
]

COOLDOWN_SECONDS = 15
RESUME_SECONDS = 10


def log_event(message):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now()}] {message}\n")


def trend_rising():
    if len(stress_history) < 5:
        return False

    first_half = list(stress_history)[:2]
    second_half = list(stress_history)[-2:]

    return sum(second_half) / len(second_half) > sum(first_half) / len(first_half)


def reduce_priority(pid):
    os.system(f"renice +5 -p {pid}")
    return f"Priority reduced for PID {pid}"


def pause_process(pid):
    os.kill(int(pid), signal.SIGSTOP)
    paused_processes[pid] = time.time()
    return f"Process paused PID {pid}"


def resume_process(pid):
    os.kill(int(pid), signal.SIGCONT)
    return f"Process resumed PID {pid}"


def kill_process(pid):
    os.kill(int(pid), signal.SIGTERM)
    return f"Process terminated PID {pid}"


print(f"[SENTRY] Autonomous Daemon Started ({PLATFORM})\n")

while True:
    current_time = time.time()

    # Resume paused processes
    for pid in list(paused_processes.keys()):
        if current_time - paused_processes[pid] > RESUME_SECONDS:
            try:
                result = resume_process(pid)
                log_event(result)
                del paused_processes[pid]
            except:
                del paused_processes[pid]

    # Metrics
    cpu = calculate_cpu()
    memory = get_memory_usage()
    io = get_io_wait()

    score = compute_stress(cpu, memory, io)
    stress_history.append(score)

    level = classify_basic(score)

    pid, name, pscore = get_top_process()

    action = "No action executed"

    # Disable control on non-Linux
    if PLATFORM != "Linux":
        action = "Control disabled (non-Linux platform)"

    elif pid and name not in CRITICAL_PROCESSES and trend_rising():

        if pid in last_mitigated and current_time - last_mitigated[pid] < COOLDOWN_SECONDS:
            action = "Cooldown active"

        else:
            if level == "MODERATE":
                action = reduce_priority(pid)

            elif level == "HIGH":
                action = pause_process(pid)

            elif level == "CRITICAL":
                action = kill_process(pid)

            last_mitigated[pid] = current_time

    output = (
        f"CPU={cpu}% | MEM={memory}% | IO={io}% | "
        f"Stress={score} | Level={level} | "
        f"Target={name}({pid}) | ProcessScore={pscore} | Action={action}"
    )

    print(output)
    log_event(output)

    time.sleep(3)
