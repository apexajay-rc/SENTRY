import time
import os
import subprocess
import signal
from collections import deque
from datetime import datetime

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


def get_cpu_usage():
    with open('/proc/stat', 'r') as f:
        line = f.readline()
        values = list(map(int, line.split()[1:]))
        idle = values[3]
        total = sum(values)
    return idle, total


def calculate_cpu():
    idle1, total1 = get_cpu_usage()
    time.sleep(1)
    idle2, total2 = get_cpu_usage()

    idle_delta = idle2 - idle1
    total_delta = total2 - total1

    cpu_usage = 100 * (1 - idle_delta / total_delta)
    return round(cpu_usage, 2)


def get_memory_usage():
    with open('/proc/meminfo', 'r') as f:
        lines = f.readlines()

    mem_total = int(lines[0].split()[1])
    mem_available = int(lines[2].split()[1])

    mem_used = mem_total - mem_available
    usage = (mem_used / mem_total) * 100
    return round(usage, 2)


def get_io_wait():
    with open('/proc/stat', 'r') as f:
        line = f.readline()
        values = list(map(int, line.split()[1:]))
        iowait = values[4]
        total = sum(values)

    return round((iowait / total) * 100, 2)


def compute_stress(cpu, memory, io):
    score = (0.5 * cpu + 0.3 * memory + 0.2 * io) / 100
    return round(score, 2)


def classify(score):
    if score < 0.25:
        return "LOW"
    elif score < 0.45:
        return "MODERATE"
    elif score < 0.65:
        return "HIGH"
    return "CRITICAL"


def trend_rising():
    if len(stress_history) < 5:
        return False

    first_half = list(stress_history)[:2]
    second_half = list(stress_history)[-2:]

    return sum(second_half) / len(second_half) > sum(first_half) / len(first_half)


def get_top_process():
    try:
        output = subprocess.check_output(
            ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"]
        ).decode().splitlines()

        best_pid = None
        best_name = None
        best_score = -1

        for line in output[1:]:
            parts = line.split()

            if len(parts) < 4:
                continue

            pid = parts[0]
            name = parts[1]

            try:
                cpu = float(parts[2])
                mem = float(parts[3])
            except:
                continue

            score = (0.7 * cpu) + (0.3 * mem)

            if name not in CRITICAL_PROCESSES and score > best_score:
                best_score = score
                best_pid = pid
                best_name = name

        if best_pid:
            return best_pid, best_name, round(best_score, 2)

        return None, None, None

    except:
        return None, None, None


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


print("[SENTRY] Autonomous Daemon Started\n")

while True:

    current_time = time.time()

    for pid in list(paused_processes.keys()):
        if current_time - paused_processes[pid] > RESUME_SECONDS:
            try:
                result = resume_process(pid)
                log_event(result)
                del paused_processes[pid]
            except:
                del paused_processes[pid]

    cpu = calculate_cpu()
    memory = get_memory_usage()
    io = get_io_wait()

    score = compute_stress(cpu, memory, io)
    stress_history.append(score)

    level = classify(score)

    pid, name, pscore = get_top_process()

    action = "No action executed"

    if pid and trend_rising():

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
