#!/usr/bin/env python3
"""
tools/sentry_hud.py - Fixed CLI HUD client for SENTRY daemon.
Connects to /run/sentry/telemetry.sock and displays real-time telemetry.
"""

import json
import socket
import time
import sys
import os

# Configuration
HUD_SOCKET_PATH = "/run/sentry/telemetry.sock"
POLL_INTERVAL = 1.0

# Colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def format_throttled_tasks(throttled_tasks: list) -> str:
    if not throttled_tasks:
        return "  (none)"
    lines = []
    for task in throttled_tasks:
        pid = task.get("pid", "?")
        time_left = task.get("time_left", 0.0)
        lines.append(f"  PID {pid}: {time_left:.1f}s remaining")
    return "\n".join(lines)


def format_state(state: dict) -> str:
    stress = state.get("stress_score", 0.0)
    level = state.get("state", "UNKNOWN")
    spatial_pid = state.get("spatial_pid")
    observe_only = state.get("observe_only", False)
    throttled = state.get("throttled_tasks", [])

    if level in ("CRITICAL", "HIGH"):
        level_color = "\033[91m"
    elif level == "MODERATE":
        level_color = "\033[93m"
    else:
        level_color = "\033[92m"

    mode_indicator = "\033[93m[OBSERVE ONLY]\033[0m" if state.get("observe_only", False) else "\033[92m[ARMED]\033[0m"

    if level in ("CRITICAL", "HIGH"):
        level_color = "\033[91m"
    elif level == "MODERATE":
        level_color = "\033[93m"
    else:
        level_color = "\033[92m"

    lines = []
    lines.append("\033[1m╔═══════════════════════════════════════════════════════════╗\033[0m")
    lines.append("\033[1m║                    SENTRY HUD CLIENT                      ║\033[0m")
    lines.append("\033[1m╚═════════════════════════════════════════════════════════════╝\033[0m")
    lines.append("")
    lines.append(f"  \033[1mSystem Stress Score:\033[0m \033[96m{stress:.3f}\033[0m")
    lines.append(f"  \033[1mCurrent State:\033[0m     {level_color}{level}\033[0m  {mode_indicator}")

    if spatial_pid:
        lines.append(f"  \033[1mSpatial PID:\033[0m       \033[96m{spatial_pid}\033[0m \033[92m(IMMUNE)\033[0m")
    else:
        lines.append(f"  \033[1mSpatial PID:\033[0m       \033[93m(none)\033[0m")

    lines.append("")
    lines.append(f"  \033[1mTHROTTLED TASKS:\033[0m")
    if not state.get("throttled_tasks"):
        lines.append("  (none)")
    else:
        for task in state.get("throttled_tasks", []):
            pid = task.get("pid", "?")
            time_left = task.get("time_left", 0.0)
            lines.append(f"  PID {pid}: {time_left:.1f}s remaining")
    lines.append("")
    lines.append("  Press Ctrl+C to exit. Polling every 1.0s.")

    return "\n".join(lines)


def main():
    print("SENTRY HUD Client - Connecting to daemon...")
    print("Socket: /run/sentry/telemetry.sock")
    print("")

    client_sock_path = f"/tmp/sentry_hud_client_{os.getpid()}.sock"
    if os.path.exists(client_sock_path):
        os.unlink(client_sock_path)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(f"/tmp/sentry_hud_client_{os.getpid()}.sock")
    sock.setblocking(False)

    daemon_sock = "/run/sentry/telemetry.sock"

    # Send subscribe message (JSON format expected by bridge)
    subscribe_msg = json.dumps({"type": "subscribe"}).encode()
    sock.sendto(subscribe_msg, "/run/sentry/telemetry.sock")
    print(f"Subscribed to /run/sentry/telemetry.sock")
    print("")

    last_data = None
    consecutive_failures = 0

    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                if data:
                    state = json.loads(data.decode())
                    print("\033[2J\033[H", end="")

                    stress = state.get("stress_score", 0.0)
                    level = state.get("state", "UNKNOWN")
                    spatial_pid = state.get("spatial_pid")
                    observe_only = state.get("observe_only", False)
                    throttled = state.get("throttled_tasks", [])

                    if level in ("CRITICAL", "HIGH"):
                        level_color = "\033[91m"
                    elif level == "MODERATE":
                        level_color = "\033[93m"
                    else:
                        level_color = "\033[92m"

                    mode_indicator = "\033[93m[OBSERVE ONLY]\033[0m" if state.get("observe_only", False) else "\033[92m[ARMED]\033[0m"

                    if level in ("CRITICAL", "HIGH"):
                        level_color = "\033[91m"
                    elif level == "MODERATE":
                        level_color = "\033[93m"
                    else:
                        level_color = "\033[92m"

                    mode_indicator = "\033[93m[OBSERVE ONLY]\033[0m" if state.get("observe_only", False) else "\033[92m[ARMED]\033[0m"

                    lines = []
                    lines.append("\033[1m╔═══════════════════════════════════════════════════════════╗\033[0m")
                    lines.append("\033[1m║                    SENTRY HUD CLIENT                      ║\033[0m")
                    lines.append("\033[1m╚═════════════════════════════════════════════════════════════╝\033[0m")
                    lines.append("")
                    lines.append(f"  \033[1mSystem Stress Score:\033[0m \033[96m{stress:.3f}\033[0m")
                    lines.append(f"  \033[1mCurrent State:\033[0m     {level_color}{level}\033[0m  {mode_indicator}")

                    spatial_pid = state.get("spatial_pid")
                    if spatial_pid:
                        lines.append(f"  \033[1mSpatial PID:\033[0m       \033[96m{spatial_pid}\033[0m \033[92m(IMMUNE)\033[0m")
                    else:
                        lines.append(f"  \033[1mSpatial PID:\033[0m       \033[93m(none)\033[0m")

                    lines.append("")
                    lines.append("  \033[1mTHROTTLED TASKS:\033[0m")
                    throttled = state.get("throttled_tasks", [])
                    if not throttled:
                        lines.append("  (none)")
                    else:
                        for task in throttled:
                            pid = task.get("pid", "?")
                            time_left = task.get("time_left", 0.0)
                            lines.append(f"  PID {pid}: {time_left:.1f}s remaining")
                    lines.append("")
                    lines.append("  Press Ctrl+C to exit. Polling every 1.0s.")

                    print("\n".join(lines))
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
            except BlockingIOError:
                pass
            except json.JSONDecodeError:
                pass
            except Exception:
                pass

            if consecutive_failures > 20:
                print("\033[2J\033[H", end="")
                print("SENTRY HUD Client - Waiting for daemon...")
                print("Socket: /run/sentry/telemetry.sock")
                print("")
                print(f"  Waiting for telemetry broadcast...")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n[EXIT] HUD client stopped by user.")
    finally:
        try:
            os.unlink(f"/tmp/sentry_hud_client_{os.getpid()}.sock")
        except:
            pass

if __name__ == "__main__":
    import json
    import socket
    import time
    import os
    import sys

    # Socket setup
    client_sock_path = f"/tmp/sentry_hud_client_{os.getpid()}.sock"
    if os.path.exists(client_sock_path):
        os.unlink(client_sock_path)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(f"/tmp/sentry_hud_client_{os.getpid()}.sock")
    sock.setblocking(False)

    daemon_sock = "/run/sentry/telemetry.sock"

    # Send subscribe message (JSON format expected by bridge)
    subscribe_msg = json.dumps({"type": "subscribe"}).encode()
    sock.sendto(subscribe_msg, "/run/sentry/telemetry.sock")
    print(f"Subscribed to /run/sentry/telemetry.sock")
    print("")

    last_data = None
    consecutive_failures = 0

    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                if data:
                    state = json.loads(data.decode())
                    print("\033[2J\033[H", end="")

                    stress = state.get("stress_score", 0.0)
                    level = state.get("state", "UNKNOWN")
                    spatial_pid = state.get("spatial_pid")
                    observe_only = state.get("observe_only", False)
                    throttled = state.get("throttled_tasks", [])

                    if level in ("CRITICAL", "HIGH"):
                        level_color = "\033[91m"
                    elif level == "MODERATE":
                        level_color = "\033[93m"
                    else:
                        level_color = "\033[92m"

                    mode_indicator = "\033[93m[OBSERVE ONLY]\033[0m" if state.get("observe_only", False) else "\033[92m[ARMED]\033[0m"

                    if level in ("CRITICAL", "HIGH"):
                        level_color = "\033[91m"
                    elif level == "MODERATE":
                        level_color = "\033[93m"
                    else:
                        level_color = "\033[92m"

                    mode_indicator = "\033[93m[OBSERVE ONLY]\033[0m" if state.get("observe_only", False) else "\033[92m[ARMED]\033[0m"

                    lines = []
                    lines.append("\033[1m╔═══════════════════════════════════════════════════════════╗\033[0m")
                    lines.append("\033[1m║                    SENTRY HUD CLIENT                      ║\033[0m")
                    lines.append("\033[1m╚═════════════════════════════════════════════════════════════╝\033[0m")
                    lines.append("")
                    lines.append(f"  \033[1mSystem Stress Score:\033[0m \033[96m{stress:.3f}\033[0m")
                    lines.append(f"  \033[1mCurrent State:\033[0m     {level_color}{level}\033[0m  {mode_indicator}")

                    spatial_pid = state.get("spatial_pid")
                    if spatial_pid:
                        lines.append(f"  \033[1mSpatial PID:\033[0m       \033[96m{spatial_pid}\033[0m \033[92m(IMMUNE)\033[0m")
                    else:
                        lines.append("  \033[1mSpatial PID:\033[0m       \033[93m(none)\033[0m")

                    lines.append("")
                    lines.append("  \033[1mTHROTTLED TASKS:\033[0m")
                    throttled = state.get("throttled_tasks", [])
                    if not throttled:
                        lines.append("  (none)")
                    else:
                        for task in throttled:
                            pid = task.get("pid", "?")
                            time_left = task.get("time_left", 0.0)
                            lines.append(f"  PID {pid}: {time_left:.1f}s remaining")
                    lines.append("")
                    lines.append("  Press Ctrl+C to exit. Polling every 1.0s.")

                    print("\n".join(lines))
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
            except BlockingIOError:
                pass
            except json.JSONDecodeError:
                pass
            except Exception:
                pass

            if consecutive_failures > 20:
                print("\033[2J\033[H", end="")
                print("SENTRY HUD Client - Waiting for daemon...")
                print("Socket: /run/sentry/telemetry.sock")
                print("")
                print(f"  Waiting for telemetry broadcast...")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n[EXIT] HUD client stopped by user.")
    finally:
        try:
            os.unlink(f"/tmp/sentry_hud_client_{os.getpid()}.sock")
        except:
            pass

if __name__ == "__main__":
    import json
    import socket
    import time
    import os

    # Socket setup
    client_sock_path = f"/tmp/sentry_hud_client_{os.getpid()}.sock"
    if os.path.exists(client_sock_path):
        os.unlink(client_sock_path)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(f"/tmp/sentry_hud_client_{os.getpid()}.sock")
    sock.setblocking(False)

    daemon_sock = "/run/sentry/telemetry.sock"

    # Send subscribe message (JSON format expected by bridge)
    subscribe_msg = json.dumps({"type": "subscribe"}).encode()
    sock.sendto(subscribe_msg, "/run/sentry/telemetry.sock")
    print(f"Subscribed to /run/sentry/telemetry.sock")
    print("")

    last_data = None
    consecutive_failures = 0

    try:
        while True:
            try:
                data, _ = sock.recvfrom(4096)
                if data:
                    state = json.loads(data.decode())
                    print("\033[2J\033[H", end="")

                    stress = state.get("stress_score", 0.0)
                    level = state.get("state", "UNKNOWN")
                    spatial_pid = state.get("spatial_pid")
                    observe_only = state.get("observe_only", False)
                    throttled = state.get("throttled_tasks", [])

                    if level in ("CRITICAL", "HIGH"):
                        level_color = "\033[91m"
                    elif level == "MODERATE":
                        level_color = "\033[93m"
                    else:
                        level_color = "\033[92m"

                    mode_indicator = "\033[93m[OBSERVE ONLY]\033[0m" if state.get("observe_only", False) else "\033[92m[ARMED]\033[0m"

                    if level in ("CRITICAL", "HIGH"):
                        level_color = "\033[91m"
                    elif level == "MODERATE":
                        level_color = "\033[93m"
                    else:
                        level_color = "\033[92m"

                    mode_indicator = "\033[93m[OBSERVE ONLY]\033[0m" if state.get("observe_only", False) else "\033[92m[ARMED]\033[0m"

                    lines = []
                    lines.append("\033[1m╔═══════════════════════════════════════════════════════════╗\033[0m")
                    lines.append("\033[1m║                    SENTRY HUD CLIENT                      ║\033[0m")
                    lines.append("\033[1m╚════════════════════════════════════════════════════════════╝\033[0m")
                    lines.append("")
                    lines.append(f"  \033[1mSystem Stress Score:\033[0m \033[96m{stress:.3f}\033[0m")
                    lines.append(f"  \033[1mCurrent State:\033[0m     {level_color}{level}\033[0m  {mode_indicator}")

                    spatial_pid = state.get("spatial_pid")
                    if spatial_pid:
                        lines.append(f"  \033[1mSpatial PID:\033[0m       \033[96m{spatial_pid}\033[0m \033[92m(IMMUNE)\033[0m")
                    else:
                        lines.append("  \033[1mSpatial PID:\033[0m       \033[93m(none)\033[0m")

                    lines.append("")
                    lines.append("  \033[1mTHROTTLED TASKS:\033[0m")
                    throttled = state.get("throttled_tasks", [])
                    if not throttled:
                        lines.append("  (none)")
                    else:
                        for task in throttled:
                            pid = task.get("pid", "?")
                            time_left = task.get("time_left", 0.0)
                            lines.append(f"  PID {pid}: {time_left:.1f}s remaining")
                    lines.append("")
                    lines.append("  Press Ctrl+C to exit. Polling every 1.0s.")

                    print("\n".join(lines))
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
            except BlockingIOError:
                pass
            except json.JSONDecodeError:
                pass
            except Exception:
                pass

            if consecutive_failures > 20:
                print("\033[2J\033[H", end="")
                print("SENTRY HUD Client - Waiting for daemon...")
                print("Socket: /run/sentry/telemetry.sock")
                print("")
                print(f"  Waiting for telemetry broadcast...")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n[EXIT] HUD client stopped by user.")
    finally:
        try:
            os.unlink(f"/tmp/sentry_hud_client_{os.getpid()}.sock")
        except:
            pass

if __name__ == "__main__":
    import json
    import socket
    import time
    import os
    main()
