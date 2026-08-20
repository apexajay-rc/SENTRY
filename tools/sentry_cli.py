#!/usr/bin/env python3
"""
tools/sentry_cli.py

Unified CLI entrypoint for SENTRY V1.0.
Provides: hud, status, logs, restart, config, version subcommands.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

# Socket paths
BRIDGE_SOCKET = "/run/sentry_bridge.sock"
HUD_SOCKET = "/run/sentry_hud.sock"
CONFIG_PATH = "/opt/sentry/sentry_config.yaml"
INSTALL_ROOT = "/opt/sentry"

# Colors for terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_error(msg: str) -> None:
    print(f"{RED}[ERROR]{RESET} {msg}", file=sys.stderr)


def print_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def print_info(msg: str) -> None:
    print(f"{CYAN}[INFO]{RESET} {msg}")


def print_success(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET} {msg}")


def query_hud_socket(command: str = "STATUS") -> Optional[Dict[str, Any]]:
    """Query the SENTRY HUD socket for status."""
    if not os.path.exists(HUD_SOCKET):
        return None

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.settimeout(2.0)

        # Create a temporary client socket for response
        client_sock_path = f"/tmp/sentry_cli_{os.getpid()}.sock"
        if os.path.exists(client_sock_path):
            os.unlink(client_sock_path)

        sock.bind(client_sock_path)
        sock.sendto(command.encode(), HUD_SOCKET)
        data, _ = sock.recvfrom(4096)

        sock.close()
        if os.path.exists(client_sock_path):
            os.unlink(client_sock_path)

        return json.loads(data.decode())

    except (ConnectionRefusedError, FileNotFoundError, socket.timeout, json.JSONDecodeError):
        return None
    except Exception:
        return None


def send_bridge_command(command: str) -> bool:
    """Send a command to the bridge socket."""
    if not os.path.exists(BRIDGE_SOCKET):
        return False

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        sock.sendto(command.encode(), BRIDGE_SOCKET)
        sock.close()
        return True
    except Exception:
        return False


def cmd_hud(args: argparse.Namespace) -> int:
    """Interactive HUD client - polls daemon every second."""
    from tools.sentry_hud import main as hud_main
    return hud_main()


def cmd_status(args: argparse.Namespace) -> int:
    """Show current daemon status."""
    state = query_hud_socket()
    if state is None:
        print_error("SENTRY daemon not reachable. Is the service running?")
        print("  systemctl status sentry")
        return 1

    spatial_pid = state.get("spatial_pid")
    throttled = state.get("throttled_tasks", [])
    observe_only = state.get("observe_only", False)

    print(f"{BOLD}SENTRY Status{RESET}")
    print(f"  Daemon:       {GREEN}ONLINE{RESET}")
    print(f"  Mode:         {'OBSERVE ONLY' if observe_only else 'ARMED'}")
    print(f"  Spatial PID:  {spatial_pid if spatial_pid else '(none)'}")

    if throttled:
        print(f"  Throttled:    {len(throttled)} task(s)")
        for task in throttled:
            pid = task.get("pid", "?")
            time_left = task.get("time_left", 0.0)
            print(f"    PID {pid}: {time_left:.1f}s remaining")
    else:
        print(f"  Throttled:    {GREEN}none{RESET}")

    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """Stream or show daemon logs."""
    try:
        if args.follow:
            subprocess.run(["journalctl", "-u", "sentry", "-f"], check=True)
        else:
            subprocess.run(["journalctl", "-u", "sentry", "-n", str(args.lines)], check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to read logs: {e}")
        return 1
    except FileNotFoundError:
        print_error("journalctl not found. Is systemd available?")
        return 1


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart SENTRY services."""
    try:
        print_info("Restarting SENTRY daemon...")
        subprocess.run(["systemctl", "restart", "sentry"], check=True)

        if not args.daemon_only:
            print_info("Restarting desktop bridge (user service)...")
            subprocess.run(["systemctl", "--user", "restart", "sentry-bridge"], check=True)

        print_success("SENTRY services restarted.")
        return 0
    except subprocess.CalledProcessError as e:
        print_error(f"Failed to restart: {e}")
        return 1


def cmd_config(args: argparse.Namespace) -> int:
    """Show or edit configuration."""
    if args.edit:
        editor = os.environ.get("EDITOR", "nano")
        try:
            subprocess.run([editor, CONFIG_PATH], check=True)
            print_info("Configuration edited. Restart daemon to apply: sentry restart")
        except subprocess.CalledProcessError:
            print_error(f"Editor '{editor}' failed.")
            return 1
    else:
        try:
            with open(CONFIG_PATH, "r") as f:
                print(f.read())
        except FileNotFoundError:
            print_error(f"Config not found at {CONFIG_PATH}")
            return 1
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    """Show version information."""
    print("SENTRY V1.0 (SENTRY Desktop)")
    print("  Architecture: Python userspace daemon + cgroups v2")
    print("  Features: Spatial Immunity, PSI-blended stress, Causal feedback")
    print("  Kernel: 5.15+ (cgroups v2), systemd 245+")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sentry",
        description="SENTRY V1.0 - Spatial Immunity for Linux",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  sentry hud          Interactive HUD (real-time telemetry)
  sentry status       One-shot status check
  sentry logs -f      Follow daemon logs
  sentry restart      Restart all SENTRY services
  sentry config       View configuration
  sentry config -e    Edit configuration
  sentry version      Show version info
"""
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # hud
    subparsers.add_parser("hud", help="Interactive HUD (real-time telemetry)")

    # status
    subparsers.add_parser("status", help="Show current daemon status")

    # logs
    logs_parser = subparsers.add_parser("logs", help="Show daemon logs")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    logs_parser.add_argument("-n", "--lines", type=int, default=50, help="Number of lines to show")

    # restart
    restart_parser = subparsers.add_parser("restart", help="Restart SENTRY services")
    restart_parser.add_argument("--daemon-only", action="store_true", help="Restart only root daemon")

    # config
    config_parser = subparsers.add_parser("config", help="View or edit configuration")
    config_parser.add_argument("-e", "--edit", action="store_true", help="Edit config in $EDITOR")

    # version
    subparsers.add_parser("version", help="Show version information")

    args = parser.parse_args()

    # Dispatch
    handlers = {
        "hud": cmd_hud,
        "status": cmd_status,
        "logs": cmd_logs,
        "restart": cmd_restart,
        "config": cmd_config,
        "version": cmd_version,
    }

    handler = handlers.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())