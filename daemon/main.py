import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.classifier import trend_label, trend_rising
from core.cgroups import add_process, set_cpu_weight
from core.config import ConfigManager
from core.ipc import DaemonState, IpcServer, resolve_ipc_endpoint
from core.metrics import SystemMetricsSampler, compute_stress
from core.platform_adapter import PLATFORM
from core.policy import classify_basic, get_action_limits
from core.process import ProcessSampler, read_total_memory_kb
from core.procfs import read_system_stat
from core.runtime import init_runtime

config = init_runtime()
daemon_state = DaemonState(platform=PLATFORM)
ipc_server = IpcServer(daemon_state)
metrics_sampler = SystemMetricsSampler(metric_weights=config.metric_weights())
process_sampler = ProcessSampler()


def log_event(message: str) -> None:
    log_path = config.text_log_file()
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(f"[{datetime.now()}] {message}\n")


def _format_top_processes(process_sampler, system_total_delta, total_memory_kb):
    return [
        {
            "pid": process.pid,
            "comm": process.comm,
            "cpu_percent": process.cpu_percent,
            "memory_percent": process.memory_percent,
            "score": process.score,
        }
        for process in process_sampler.top_processes(system_total_delta, total_memory_kb, limit=5)
    ]


def _decide_action(level, pid, name, current_time, last_mitigated, stress_history):
    snapshot = daemon_state.snapshot()
    critical_processes = config.critical_processes_set()
    cooldown_seconds = config.cooldown_seconds()

    if PLATFORM != "Linux":
        return "Monitoring only (control disabled on this platform)"
    if not config.cgroup_enabled():
        return "Cgroup control disabled in config"
    if snapshot["observe_only"]:
        return "Observe only (mitigation disabled)"
    if not snapshot["armed"]:
        return "Disarmed (mitigation disabled)"
    if not pid or not name:
        return "No valid target"
    if name in critical_processes:
        return f"Skipped critical process ({name})"
    if not trend_rising(stress_history):
        return "No rising trend detected"
    if pid in last_mitigated and current_time - last_mitigated[pid] < cooldown_seconds:
        return "Cooldown active"
    if level not in ["MODERATE", "HIGH", "CRITICAL"]:
        return "System stable"

    limits = get_action_limits(level)
    action = (
        f"cgroup throttle applied (PID {pid}, cpu_weight={limits['cpu_weight']})"
    )

    if snapshot["dry_run"]:
        return f"[dry-run] Would apply {action}"

    add_process(pid)
    set_cpu_weight(limits["cpu_weight"])
    last_mitigated[pid] = current_time
    return action


def main():
    endpoint = resolve_ipc_endpoint()
    ipc_server.start_background()
    print(f"[SENTRY] Safe Daemon Started ({PLATFORM})")
    print(f"[SENTRY] Config: {config.config_file}")
    print(f"[SENTRY] IPC listening on {endpoint}\n")

    stress_history = deque(maxlen=10)
    last_mitigated = {}
    previous_stat = None
    poll_interval = config.poll_interval()
    critical_processes = config.critical_processes_set()

    if PLATFORM == "Linux":
        metrics_sampler.warmup()
        process_sampler.prime()
        previous_stat = read_system_stat()

    while True:
        current_time = time.time()
        metrics = None
        pid = None
        name = None
        pscore = None

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
                protected_comm=critical_processes,
            )

            cpu = metrics.cpu_percent
            memory = metrics.memory_percent
            io = metrics.io_wait_percent
            score = metrics.stress_score
            top_processes = _format_top_processes(
                process_sampler, system_total_delta, total_memory_kb
            )
            psi_cpu = metrics.psi_cpu_some_avg10
            psi_mem = metrics.psi_memory_some_avg10
            psi_io = metrics.psi_io_some_avg10
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
            top_processes = []
            psi_cpu = psi_mem = psi_io = None

        action = _decide_action(
            level, pid, name, current_time, last_mitigated, stress_history
        )

        daemon_state.update(
            cpu_percent=cpu,
            memory_percent=memory,
            io_wait_percent=io,
            stress_score=score,
            level=level,
            trend=trend_label(stress_history),
            target_pid=int(pid) if pid else None,
            target_comm=name,
            target_score=pscore,
            last_action=action,
            stress_history=list(stress_history),
            top_processes=top_processes,
            psi_cpu_some_avg10=psi_cpu,
            psi_memory_some_avg10=psi_mem,
            psi_io_some_avg10=psi_io,
        )

        psi_parts = []
        if psi_cpu is not None:
            psi_parts.append(f"PSI_CPU={psi_cpu}")
        if psi_mem is not None:
            psi_parts.append(f"PSI_MEM={psi_mem}")
        if psi_io is not None:
            psi_parts.append(f"PSI_IO={psi_io}")
        psi_text = f" | {' | '.join(psi_parts)}" if psi_parts else ""

        output = (
            f"CPU={cpu}% | MEM={memory}% | IO={io}% | Stress={score} | "
            f"Level={level} | Target={name}({pid}) | ProcessScore={pscore} | "
            f"Action={action}{psi_text}"
        )

        print(output)
        log_event(output)
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
