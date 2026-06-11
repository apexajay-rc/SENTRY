import sys
import threading
import time
from collections import deque
from pathlib import Path

import flet as ft

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.classifier import classify_stress, decision_hint, trend_label
from core.metrics import SystemMetricsSampler, compute_stress
from core.platform_adapter import PLATFORM
from core.process import ProcessSampler, read_total_memory_kb
from core.procfs import read_system_stat

stress_history = deque(maxlen=10)
metrics_sampler = SystemMetricsSampler(interval=0.5)
process_sampler = ProcessSampler()

LEVEL_COLORS = {
    "LOW": ft.Colors.GREEN,
    "MODERATE": ft.Colors.ORANGE,
    "HIGH": ft.Colors.RED,
    "CRITICAL": ft.Colors.PURPLE,
}


def classify_with_color(score, mode):
    level = classify_stress(score, mode)
    return level, LEVEL_COLORS[level]


def format_top_processes(process_sampler, system_total_delta, total_memory_kb):
    rows = []
    for process in process_sampler.top_processes(system_total_delta, total_memory_kb, limit=3):
        rows.append(f"{process.comm} : {process.cpu_percent}% CPU")
    return "\n".join(rows) if rows else "Collecting"


def sparkline():
    bars = ""
    for score in stress_history:
        if score < 0.25:
            bars += "▁"
        elif score < 0.35:
            bars += "▃"
        elif score < 0.45:
            bars += "▅"
        else:
            bars += "▇"
    return bars


def main(page: ft.Page):
    page.title = "SENTRY"
    page.theme_mode = "dark"
    page.window_width = 1200
    page.window_height = 750
    page.padding = 20
    page.bgcolor = "#0b1220"

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

    previous_stat = None
    if PLATFORM == "Linux":
        metrics_sampler.warmup()
        process_sampler.prime()
        previous_stat = read_system_stat()

    def update_metrics():
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
                f"{format_top_processes(process_sampler, system_total_delta, total_memory_kb)}"
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
        trend = trend_label(stress_history)

        cpu_text.value = f"CPU Usage: {cpu}%"
        mem_text.value = f"Memory Usage: {mem}%"
        io_text.value = f"I/O Wait: {io}%"
        stress_text.value = f"Unified Stress Score: {score}"
        level_text.value = f"System Level: {level}"
        level_text.color = color
        trend_text.value = f"Trend: {trend}"
        action_text.value = f"Mode: {mode} ({PLATFORM})"
        spark_text.value = sparkline()
        decision_text.value = f"Decision Engine: {decision_hint(level, trend)}"

        page.update()

    def refresh_loop():
        while True:
            update_metrics()
            time.sleep(2)

    threading.Thread(target=refresh_loop, daemon=True).start()

    left = ft.Column(
        [
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
