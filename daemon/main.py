import time
import os
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
from core.actions import reduce_priority, noop


LOG_FILE = "sentry_log.txt"

stress_history = deque(maxlen=5)
last_mitigated = {}

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


def log_event(message):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now()}] {message}\n")


def trend_rising():
    if len(stress_history) < 5:
        return False

    first_half = list(stress_history)[:2]
    second_half = list(stress_history)[-2:]

    return sum(second_half) / len(second_half) > sum(first_half) / len(first_half)


print(f"[SENTRY] Safe Daemon Started ({PLATFORM})\n")

while True:
    current_time = time.time()

    # Collect metrics
    cpu = calculate_cpu()
    memory = get_memory_usage()
    io = get_io_wait()

    score = compute_stress(cpu, memory, io)
    stress_history.append(score)

    level = classify_basic(score)

    pid, name, pscore = get_top_process()

    action = "No action executed"

    # Platform guard
    if PLATFORM != "Linux":
        action = "Monitoring only (control disabled on this platform)"

    elif not pid or not name:
        action = "No valid target"

    elif name in CRITICAL_PROCESSES:
        action = f"Skipped critical process ({name})"

    elif not trend_rising():
        action = "No rising trend detected"

    else:
        # Cooldown check
        if pid in last_mitigated and current_time - last_mitigated[pid] < COOLDOWN_SECONDS:
            action = "Cooldown active"

        else:
            # Safe control strategy
            if level in ["MODERATE", "HIGH", "CRITICAL"]:
                action = reduce_priority(pid)
                last_mitigated[pid] = current_time
            else:
                action = "System stable"

    output = (
        f"CPU={cpu}% | MEM={memory}% | IO={io}% | "
        f"Stress={score} | Level={level} | "
        f"Target={name}({pid}) | ProcessScore={pscore} | Action={action}"
    )

    print(output)
    log_event(output)

    time.sleep(3)
