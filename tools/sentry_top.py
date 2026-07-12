#!/usr/bin/env python3
"""
tools/sentry_top.py

A low-overhead, military-grade Terminal User Interface (TUI) for SENTRY.
Communicates with the SENTRY Ring 0 Daemon via local IPC to render a live
dashboard of Spatial VIPs and tasks currently locked in the Penalty Box.
"""

import curses
import socket
import json
import time

IPC_PORT = 50506
UDP_IP = "127.0.0.1"

def get_process_name(pid):
    """Attempt to resolve the process name for a cleaner UI."""
    try:
        with open(f"/proc/{pid}/comm", "r") as f:
            return f.read().strip()
    except Exception:
        return "UNKNOWN"

def fetch_sentry_state():
    """Pings the SENTRY daemon for a brain-dump."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.2) # Don't block the UI if SENTRY is offline
    try:
        sock.sendto(b"STATUS", (UDP_IP, IPC_PORT))
        data, _ = sock.recvfrom(4096)
        return json.loads(data.decode())
    except (socket.timeout, ConnectionRefusedError):
        return None
    finally:
        sock.close()

def draw_hud(stdscr):
    # Setup curses environment
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)   # Success / Active
    curses.init_pair(2, curses.COLOR_RED, -1)     # Danger / Penalty
    curses.init_pair(3, curses.COLOR_CYAN, -1)    # Headers
    curses.init_pair(4, curses.COLOR_YELLOW, -1)  # Warnings

    curses.curs_set(0) # Hide the cursor
    stdscr.nodelay(True) # Make getch() non-blocking

    while True:
        # Handle Exit
        key = stdscr.getch()
        if key == ord('q') or key == ord('Q'):
            break

        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        state = fetch_sentry_state()

        # --- HEADER ---
        header_text = " SENTRY RING-0 COMMAND CENTER "
        stdscr.addstr(1, max_x // 2 - len(header_text) // 2, header_text, curses.color_pair(3) | curses.A_BOLD)
        stdscr.addstr(2, 2, "-" * (max_x - 4), curses.color_pair(3))

        if state is None:
            err_msg = "[!] DAEMON OFFLINE OR UNREACHABLE"
            stdscr.addstr(4, max_x // 2 - len(err_msg) // 2, err_msg, curses.color_pair(2) | curses.A_BOLD)
            stdscr.addstr(5, max_x // 2 - 24, "Ensure 'sudo python3 -m daemon.main' is running.")
        else:
            # --- PILLAR 1: SPATIAL CONTEXT ---
            spatial_pid = state.get("spatial_pid")
            stdscr.addstr(4, 4, "PILLAR 1: SPATIAL CONTEXT (FLOW STATE GUARD)", curses.color_pair(3) | curses.A_BOLD)
            
            if spatial_pid:
                proc_name = get_process_name(spatial_pid)
                stdscr.addstr(6, 6, f"Target Lock: [ PID {spatial_pid} ] -> {proc_name}", curses.color_pair(1) | curses.A_BOLD)
                stdscr.addstr(7, 6, "Status: ABSOLUTE IMMUNITY GRANTED", curses.color_pair(1))
            else:
                stdscr.addstr(6, 6, "Target Lock: [ NONE ]", curses.color_pair(4))

            # --- THE PENALTY BOX ---
            stdscr.addstr(10, 4, "THE PENALTY BOX (20% CPU CLAMP)", curses.color_pair(3) | curses.A_BOLD)
            
            throttled_tasks = state.get("throttled_tasks", [])
            
            if not throttled_tasks:
                stdscr.addstr(12, 6, "Box is empty. System state nominal.", curses.color_pair(1))
            else:
                # Table Header
                stdscr.addstr(12, 6, f"{'PID':<10} | {'COMMAND':<15} | {'TIME REMAINING':<15}", curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(13, 6, "-" * 50)
                
                row = 14
                for task in throttled_tasks:
                    pid = task.get("pid")
                    time_left = task.get("time_left", 0)
                    proc_name = get_process_name(pid)
                    
                    stdscr.addstr(row, 6, f"{pid:<10} | {proc_name:<15} | {time_left:>4.1f} sec", curses.color_pair(2))
                    row += 1
                    if row >= max_y - 2:
                        break # Prevent UI overflow

        # --- FOOTER ---
        footer_text = "Press 'Q' to exit"
        stdscr.addstr(max_y - 2, max_x - len(footer_text) - 2, footer_text, curses.color_pair(3))

        stdscr.refresh()
        time.sleep(0.1) # 10FPS refresh rate (Zero overhead)

if __name__ == "__main__":
    try:
        curses.wrapper(draw_hud)
    except KeyboardInterrupt:
        pass
