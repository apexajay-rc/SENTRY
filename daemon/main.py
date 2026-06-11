import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.classifier import trend_rising
from core.cgroups import add_process, set_cpu_weight, setup_cgroup
from core.metrics import SystemMetricsSampler, compute_stress
from core.platform_adapter import PLATFORM
from core.policy import classify_basic, get_action_limits
from core.process import ProcessSampler, read_total_memory_kb
from core.procfs import read_system_stat

if PLATFORM == "Linux":
    setup_cgroup()

LOG_FILE = "sentry_log.txt"
stress_history = deque(maxlen=5)
last_mitigated = {}

CRITICAL_PROCESSES = {
    "systemd",
    "gnome-shell",
    "Xorg",
    "pulseaudio",
    "pipewire",
    "ps",
}

COOLDOWN_SECONDS = 15

metrics_sampler = SystemMetricsSampler()
process_sampler = ProcessSampler()


def log_event(message):
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(f"[{datetime.now()}] {message}\n")


def _format_psi(metrics):
    if metrics is None or metrics.psi_cpu_some_avg10 is None:
        return ""

    parts = []
    if metrics.psi_cpu_some_avg10 is not None:
        parts.append(f"PSI_CPU={metrics.psi_cpu_some_avg10}")
    if metrics.psi_memory_some_avg10 is not None:
        parts.append(f"PSI_MEM={metrics.psi_memory_some_avg10}")
    if metrics.psi_io_some_avg10 is not None:
        parts.append(f"PSI_IO={metrics.psi_io_some_avg10}")

    return f" | {' | '.join(parts)}" if parts else ""


def main():
    print(f"[SENTRY] Safe Daemon Started ({PLATFORM})\n")

    previous_stat = None
    if PLATFORM == "Linux":
        metrics_sampler.warmup()
        process_sampler.prime()
        previous_stat = read_system_stat()

    while True:
        current_time = time.time()
        metrics = None

        if PLATFORM == "Linux":
            current_stat = read_system_stat()
            system_total_delta = current_stat.total - previous_stat.total
            previous_stat = current_stat

            metrics = metrics_sampler.sample()
            stress_history.append(metrics.stress_score)
            level = classify_basic(metrics.stress_score)

            total_memory_kb = read_total_memory_kb()
            pid, name, pscore = process_sampler.top_process(
                system_total_delta,
                total_memory_kb,
                protected_comm=CRITICAL_PROCESSES,
            )

            cpu = metrics.cpu_percent
            memory = metrics.memory_percent
            io = metrics.io_wait_percent
            score = metrics.stress_score
        else:
            from core.platform_adapter import (
                calculate_cpu,
                get_io_wait,
                get_memory_usage,
                get_top_process,
            )

            cpu = calculate_cpu()
            memory = get_memory_usage()
            io = get_io_wait()
            score = compute_stress(cpu, memory, io)
            stress_history.append(score)
            level = classify_basic(score)
            pid, name, pscore = get_top_process()

        action = "No action executed"

        if PLATFORM != "Linux":
            action = "Monitoring only (control disabled on this platform)"
        elif not pid or not name:
            action = "No valid target"
        elif name in CRITICAL_PROCESSES:
            action = f"Skipped critical process ({name})"
        elif not trend_rising(stress_history):
            action = "No rising trend detected"
        elif pid in last_mitigated and current_time - last_mitigated[pid] < COOLDOWN_SECONDS:
            action = "Cooldown active"
        elif level in ["MODERATE", "HIGH", "CRITICAL"]:
            limits = get_action_limits(level)
            add_process(pid)
            set_cpu_weight(limits["cpu_weight"])
            action = (
                f"cgroup throttle applied (PID {pid}, "
                f"cpu_weight={limits['cpu_weight']})"
            )
            last_mitigated[pid] = current_time
        else:
            action = "System stable"

        output = (
            f"CPU={cpu}% | MEM={memory}% | IO={io}% | Stress={score} | "
            f"Level={level} | Target={name}({pid}) | ProcessScore={pscore} | "
            f"Action={action}{_format_psi(metrics)}"
        )

        print(output)
        log_event(output)
        time.sleep(3)


if __name__ == "__main__":
    main()
