import flet as ft
import time
import threading
from collections import deque

from core.platform_adapter import (
    calculate_cpu,
    get_memory_usage,
    get_io_wait
)
from core.metrics import compute_stress

stress_history = deque(maxlen=10)


def classify(score, mode):
    if mode == "Gaming":
        high = 0.40
    elif mode == "Editing":
        high = 0.50
    else:
        high = 0.45

    if score < 0.25:
        return "LOW", ft.Colors.GREEN
    elif score < high:
        return "MODERATE", ft.Colors.ORANGE
    elif score < 0.65:
        return "HIGH", ft.Colors.RED
    return "CRITICAL", ft.Colors.PURPLE


def trend_status():
    if len(stress_history) < 5:
        return "Collecting"

    first = list(stress_history)[:2]
    last = list(stress_history)[-2:]

    return "Rising" if sum(last) > sum(first) else "Stable"


def decision_engine(level, trend):
    if level == "HIGH" and trend == "Rising":
        return "Mitigation advised"
    elif level == "MODERATE":
        return "Observe closely"
    return "Stable"


def sparkline():
    bars = ""

    for s in stress_history:
        if s < 0.25:
            bars += "▁"
        elif s < 0.35:
            bars += "▃"
        elif s < 0.45:
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

    stress_text = ft.Text(size=22, weight="bold")
    level_text = ft.Text(size=24, weight="bold")

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
        ]
    )

    def update_metrics():
        cpu = calculate_cpu()
        mem = get_memory_usage()
        io = get_io_wait()

        score = compute_stress(cpu, mem, io)
        stress_history.append(score)

        mode = mode_dropdown.value

        level, color = classify(score, mode)
        trend = trend_status()

        cpu_text.value = f"CPU Usage: {cpu}%"
        mem_text.value = f"Memory Usage: {mem}%"
        io_text.value = f"I/O Wait: {io}%"

        stress_text.value = f"Unified Stress Score: {score}"

        level_text.value = f"System Level: {level}"
        level_text.color = color

        trend_text.value = f"Trend: {trend}"
        action_text.value = f"Mode: {mode}"

        spark_text.value = sparkline()
        decision_text.value = f"Decision Engine: {decision_engine(level, trend)}"

        page.update()

    def refresh_loop():
        while True:
            update_metrics()
            time.sleep(2)

    threading.Thread(target=refresh_loop, daemon=True).start()

    left = ft.Column([
        ft.Card(ft.Container(cpu_text, padding=20)),
        ft.Card(ft.Container(mem_text, padding=20)),
        ft.Card(ft.Container(io_text, padding=20)),
        ft.Card(ft.Container(stress_text, padding=20)),
        ft.Card(ft.Container(level_text, padding=20)),
    ], expand=1)

    center = ft.Column([
        ft.Text("Stress Intelligence", size=24, weight="bold"),
        ft.Card(ft.Container(spark_text, padding=20)),
        ft.Card(ft.Container(decision_text, padding=20)),
    ], expand=2)

    right = ft.Column([
        ft.Card(ft.Container(trend_text, padding=20)),
        ft.Card(ft.Container(action_text, padding=20)),
        ft.Card(ft.Container(mode_dropdown, padding=20)),
    ], expand=1)

    page.add(
        ft.Column([
            ft.Text("SENTRY Dashboard", size=30, weight="bold"),
            ft.Divider(),
            ft.Row([left, center, right], expand=True)
        ])
    )


ft.app(target=main)
