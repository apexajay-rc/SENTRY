import sys
import threading
import time
from collections import deque
from pathlib import Path

import flet as ft

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.classifier import classify_stress, decision_hint
from core.ipc import IpcClient
from core.metrics import SystemMetricsSampler, compute_stress
from core.platform_adapter import PLATFORM
from core.process import ProcessSampler, read_total_memory_kb
from core.procfs import read_system_stat

stress_history = deque(maxlen=10)
metrics_sampler = SystemMetricsSampler(interval=0.5)
process_sampler = ProcessSampler()
ipc_client = IpcClient()

LEVEL_COLORS = {
    "LOW": ft.Colors.GREEN,
    "MODERATE": ft.Colors.ORANGE,
    "HIGH": ft.Colors.RED,
    "CRITICAL": ft.Colors.PURPLE,
}


def classify_with_color(score, mode):
    level = classify_stress(score, mode)
    return level, LEVEL_COLORS[level]


def format_top_processes_local(process_sampler, system_total_delta, total_memory_kb):
    rows = []
    for process in process_sampler.top_processes(system_total_delta, total_memory_kb, limit=3):
        rows.append(f"{process.comm} : {process.cpu_percent}% CPU")
    return "\n".join(rows) if rows else "Collecting"


def format_top_processes_ipc(top_processes):
    if not top_processes:
        return "Collecting"
    rows = []
    for process in top_processes[:3]:
        rows.append(f"{process['comm']} : {process['cpu_percent']}% CPU")
    return "\n".join(rows)


def sparkline_from_history(history):
    bars = ""
    for score in history:
        if score < 0.25:
            bars += "▁"
        elif score < 0.35:
            bars += "▃"
        elif score < 0.45:
            bars += "▅"
        else:
            bars += "▇"
    return bars or "Collecting"


def main(page: ft.Page):
    page.title = "SENTRY"
    page.theme_mode = "dark"
    page.window_width = 1200
    page.window_height = 800
    page.padding = 20
    page.bgcolor = "#0b1220"

    connection_text = ft.Text(size=16, color=ft.Colors.ORANGE)
    cpu_text = ft.Text(size=20)
    mem_text = ft.Text(size=20)
    io_text = ft.Text(size=20)
    psi_text = ft.Text(size=18)

    stress_text = ft.Text(size=22, weight="bold")
    level_text = ft.Text(size=24, weight="bold")
    process_text = ft.Text(size=18)

    trend_text = ft.Text(size=18)
    action_text = ft.Text(size=18)

    spark_text = ft.Text(size=30)
    decision_text = ft.Text(size=20)

    mode_dropdown = ft.Dropdown(
        label="System Mode",
        value="Balanced",
        options=[
            ft.dropdown.Option("Gaming"),
            ft.dropdown.Option("Editing"),
            ft.dropdown.Option("Balanced"),
        ],
    )

    armed_switch = ft.Switch(label="Armed (allow mitigation)", value=False)
    observe_switch = ft.Switch(label="Observe only", value=True)
    dry_run_switch = ft.Switch(label="Dry run", value=False)

    ipc_connected = {"value": False}
    previous_stat = None

    if PLATFORM == "Linux":
        metrics_sampler.warmup()
        process_sampler.prime()
        previous_stat = read_system_stat()

    def push_ipc_command(command_builder):
        if not ipc_connected["value"]:
            return
        command_builder()

    def on_mode_change(_event):
        push_ipc_command(lambda: ipc_client.set_mode(mode_dropdown.value))

    def on_armed_change(event):
        push_ipc_command(lambda: ipc_client.set_armed(event.control.value))

    def on_observe_change(event):
        push_ipc_command(lambda: ipc_client.set_observe_only(event.control.value))

    def on_dry_run_change(event):
        push_ipc_command(lambda: ipc_client.set_dry_run(event.control.value))

    mode_dropdown.on_change = on_mode_change
    armed_switch.on_change = on_armed_change
    observe_switch.on_change = on_observe_change
    dry_run_switch.on_change = on_dry_run_change

    def apply_state(state):
        mode = state.get("mode", "Balanced")
        score = state.get("stress_score", 0.0)
        trend = state.get("trend", "Collecting")
        level, color = classify_with_color(score, mode)

        cpu_text.value = f"CPU Usage: {state.get('cpu_percent', 0)}%"
        mem_text.value = f"Memory Usage: {state.get('memory_percent', 0)}%"
        io_text.value = f"I/O Wait: {state.get('io_wait_percent', 0)}%"
        stress_text.value = f"Unified Stress Score: {score}"
        level_text.value = f"System Level: {level}"
        level_text.color = color
        trend_text.value = f"Trend: {trend}"
        action_text.value = f"Daemon: {state.get('last_action', 'N/A')}"
        spark_text.value = sparkline_from_history(state.get("stress_history", []))
        decision_text.value = f"Decision Engine: {decision_hint(level, trend)}"
        process_text.value = f"Top Processes:\n{format_top_processes_ipc(state.get('top_processes', []))}"

        psi = state.get("psi", {})
        if psi.get("cpu") is not None:
            psi_text.value = (
                f"PSI (avg10): CPU {psi.get('cpu')} | "
                f"MEM {psi.get('memory')} | IO {psi.get('io')}"
            )
        else:
            psi_text.value = "PSI: unavailable"

        mode_dropdown.value = mode
        armed_switch.value = state.get("armed", False)
        observe_switch.value = state.get("observe_only", True)
        dry_run_switch.value = state.get("dry_run", False)

    def update_local_metrics():
        nonlocal previous_stat

        if PLATFORM == "Linux":
            current_stat = read_system_stat()
            system_total_delta = current_stat.total - previous_stat.total
            previous_stat = current_stat

            metrics = metrics_sampler.sample()
            cpu = metrics.cpu_percent
            mem = metrics.memory_percent
            io = metrics.io_wait_percent
            score = metrics.stress_score

            if metrics.psi_cpu_some_avg10 is not None:
                psi_text.value = (
                    f"PSI (avg10): CPU {metrics.psi_cpu_some_avg10} | "
                    f"MEM {metrics.psi_memory_some_avg10} | IO {metrics.psi_io_some_avg10}"
                )
            else:
                psi_text.value = "PSI: unavailable on this kernel"

            total_memory_kb = read_total_memory_kb()
            process_text.value = (
                f"Top Processes:\n"
                f"{format_top_processes_local(process_sampler, system_total_delta, total_memory_kb)}"
            )
        else:
            from core.platform_adapter import calculate_cpu, get_io_wait, get_memory_usage

            cpu = calculate_cpu()
            mem = get_memory_usage()
            io = get_io_wait()
            score = compute_stress(cpu, mem, io)
            psi_text.value = "PSI: Linux only"
            process_text.value = "Top Processes:\nUnavailable on this platform"

        stress_history.append(score)
        mode = mode_dropdown.value
        level, color = classify_with_color(score, mode)
        trend = "Collecting"
        if len(stress_history) >= 5:
            first = list(stress_history)[:2]
            last = list(stress_history)[-2:]
            trend = "Rising" if sum(last) > sum(first) else "Stable"

        cpu_text.value = f"CPU Usage: {cpu}%"
        mem_text.value = f"Memory Usage: {mem}%"
        io_text.value = f"I/O Wait: {io}%"
        stress_text.value = f"Unified Stress Score: {score}"
        level_text.value = f"System Level: {level}"
        level_text.color = color
        trend_text.value = f"Trend: {trend}"
        action_text.value = f"Mode: {mode} ({PLATFORM}) — local fallback"
        spark_text.value = sparkline_from_history(list(stress_history))
        decision_text.value = f"Decision Engine: {decision_hint(level, trend)}"

    def refresh_loop():
        while True:
            if ipc_client.ping():
                ipc_connected["value"] = True
                connection_text.value = "Daemon: connected (IPC)"
                connection_text.color = ft.Colors.GREEN
                state = ipc_client.get_state()
                if state:
                    apply_state(state)
            else:
                ipc_connected["value"] = False
                connection_text.value = "Daemon: not running — local fallback"
                connection_text.color = ft.Colors.ORANGE
                update_local_metrics()

            page.update()
            time.sleep(2)

    threading.Thread(target=refresh_loop, daemon=True).start()

    left = ft.Column(
        [
            ft.Card(ft.Container(connection_text, padding=20)),
            ft.Card(ft.Container(cpu_text, padding=20)),
            ft.Card(ft.Container(mem_text, padding=20)),
            ft.Card(ft.Container(io_text, padding=20)),
            ft.Card(ft.Container(stress_text, padding=20)),
            ft.Card(ft.Container(level_text, padding=20)),
            ft.Card(ft.Container(psi_text, padding=20)),
        ],
        expand=1,
    )

    center = ft.Column(
        [
            ft.Text("Stress Intelligence", size=24, weight="bold"),
            ft.Card(ft.Container(spark_text, padding=20)),
            ft.Card(ft.Container(decision_text, padding=20)),
        ],
        expand=2,
    )

    right = ft.Column(
        [
            ft.Card(ft.Container(process_text, padding=20)),
            ft.Card(ft.Container(trend_text, padding=20)),
            ft.Card(ft.Container(action_text, padding=20)),
            ft.Card(ft.Container(mode_dropdown, padding=20)),
            ft.Card(ft.Container(armed_switch, padding=20)),
            ft.Card(ft.Container(observe_switch, padding=20)),
            ft.Card(ft.Container(dry_run_switch, padding=20)),
        ],
        expand=1,
    )

    page.add(
        ft.Column(
            [
                ft.Text("SENTRY Dashboard", size=30, weight="bold"),
                ft.Divider(),
                ft.Row([left, center, right], expand=True),
            ]
        )
    )


if __name__ == "__main__":
    ft.app(target=main)
