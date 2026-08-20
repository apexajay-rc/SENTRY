#!/usr/bin/env python3
"""
tools/sentry_hud.py

Standalone CLI HUD client for SENTRY daemon.
Connects to the daemon's status socket (/run/sentry_hud.sock) and displays
real-time telemetry: stress score, system state, and throttled tasks.
"""

import json
import socket
import time
import sys
import os
from typing import Optional, Dict, Any

# Configuration
HUD_SOCKET_PATH = "/run/sentry_hud.sock"
POLL_INTERVAL = 1.0  # seconds


def format_throttled_tasks(throttled_tasks: list) -> str:
    """Format throttled tasks for display."""
    if not throttled_tasks:
        return "  (none)"
    
    lines = []
    for task in throttled_tasks:
        pid = task.get("pid", "?")
        time_left = task.get("time_left", 0.0)
        lines.append(f"  PID {pid}: {time_left:.1f}s remaining")
    return "\n".join(lines)


def format_state(state: Dict[str, Any]) -> str:
    """Format daemon state for pretty terminal output."""
    stress = state.get("stress_score", 0.0)
    level = state.get("state", "UNKNOWN")
    spatial_pid = state.get("spatial_pid")
    observe_only = state.get("observe_only", False)
    throttled = state.get("throttled_tasks", [])
    
    # Color codes for terminal
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    
    # Level color
    if level in ("CRITICAL", "HIGH"):
        level_color = RED
    elif level == "MODERATE":
        level_color = YELLOW
    else:
        level_color = GREEN
    
    # Observe mode indicator
    mode_indicator = f"{YELLOW}[OBSERVE ONLY]{RESET}" if observe_only else f"{GREEN}[ARMED]{RESET}"
    
    lines = []
    lines.append(f"{BOLD}╔═══════════════════════════════════════════════════════════╗{RESET}")
    lines.append(f"{BOLD}║                    SENTRY HUD CLIENT                        ║{RESET}")
    lines.append(f"{BOLD}╚═══════════════════════════════════════════════════════════╝{RESET}")
    lines.append("")
    lines.append(f"  {BOLD}System Stress Score:{RESET} {CYAN}{stress:.3f}{RESET}")
    lines.append(f"  {BOLD}Current State:{RESET}     {level_color}{level}{RESET}  {mode_indicator}")
    
    if spatial_pid:
        lines.append(f"  {BOLD}Spatial PID:{RESET}       {CYAN}{spatial_pid}{RESET} {GREEN}(IMMUNE){RESET}")
    else:
        lines.append(f"  {BOLD}Spatial PID:{RESET}       {YELLOW}(none){RESET}")
    
    lines.append("")
    lines.append(f"  {BOLD}THROTTLED TASKS:{RESET}")
    lines.append(format_throttled_tasks(throttled))
    lines.append("")
    lines.append(f"  Press Ctrl+C to exit. Polling every {POLL_INTERVAL}s.")
    
    return "\n".join(lines)


def query_hud_socket() -> Optional[Dict[str, Any]]:
    """Query the SENTRY HUD socket for status."""
    if not os.path.exists(HUD_SOCKET_PATH):
        return None
    
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        
        # Create a temporary client socket for response
        client_sock_path = f"/tmp/sentry_hud_client_{os.getpid()}.sock"
        if os.path.exists(client_sock_path):
            os.unlink(client_sock_path)
        
        sock.bind(client_sock_path)
        
        # Send STATUS command
        sock.sendto(b"STATUS", HUD_SOCKET_PATH)
        
        # Receive response
        data, _ = sock.recvfrom(4096)
        
        # Cleanup
        sock.close()
        if os.path.exists(client_sock_path):
            os.unlink(client_sock_path)
        
        return json.loads(data.decode())
    
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout, json.JSONDecodeError):
        return None
    except Exception:
        return None


def main():
    """Main HUD client loop."""
    print("SENTRY HUD Client - Connecting to daemon...")
    print(f"Socket: {HUD_SOCKET_PATH}")
    print("")
    
    consecutive_failures = 0
    
    try:
        while True:
            state = query_hud_socket()
            
            if state is None:
                consecutive_failures += 1
                if consecutive_failures == 1:
                    print("\033[2J\033[H", end="")  # Clear screen
                    print("SENTRY HUD Client - Waiting for daemon...")
                    print(f"Socket: {HUD_SOCKET_PATH}")
                    print("")
                    print(f"  {consecutive_failures} consecutive connection failures.")
                    print("  Is the daemon running? (sudo python daemon/main.py)")
                else:
                    print(f"\r  {consecutive_failures} consecutive connection failures...", end="", flush=True)
            else:
                consecutive_failures = 0
                # Clear screen and print formatted state
                print("\033[2J\033[H", end="")  # Clear screen, move cursor to top-left
                print(format_state(state))
            
            time.sleep(POLL_INTERVAL)
    
    except KeyboardInterrupt:
        print("\n\n[EXIT] HUD client stopped by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()