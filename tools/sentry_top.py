#!/usr/bin/env python3
"""
tools/sentry_top.py

A low-overhead, military-grade Terminal User Interface (TUI) for SENTRY.
Communicates with the SENTRY Ring 0 Daemon via local Unix IPC to render a live
dashboard of Spatial VIPs and tasks currently locked in the Penalty Box.
"""

import curses
import socket
import json
import time
import os

SENTRY_HUD_SOCK = "/run/sentry_hud.sock"

def get_process_name(pid):
    """Attempt to resolve the process name for a cleaner UI."""
    try:
        with open(f"/proc/{pid}/comm", "r") as f:
            return f.read().strip()
    except Exception:
        return "UNKNOWN"

def fetch_sentry_state(sock):
    """Pings the SENTRY daemon for a brain-dump."""
    try:
        sock.sendto(b"STATUS", SENTRY_HUD_SOCK)
        data, _ = sock.recvfrom(4096)
        return json.loads(data.decode())
    except (socket.timeout, ConnectionRefusedError, FileNotFoundError):
        return None

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

    # Create a unique transient client socket for this TUI instance
    client_sock_path = f"/tmp/sentry_top_client_{os.getpid()}.sock"
    if os.path.exists(client_sock_path):
        os.unlink(client_sock_path)
        
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(client_sock_path)
    sock.settimeout(0.2) # Don't block the UI if SENTRY is offline

    try:
        while True:
            # Handle user input
            key = stdscr.getch()
            if key == ord('q') or key == ord('Q'):
                break
            elif key == ord('o') or key == ord('O'):
                # Toggle Observe Only mode in the running daemon
                try:
                    sock.sendto(b"TOGGLE_OBSERVE", SENTRY_HUD_SOCK)
                except Exception:
                    pass

            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()

            state = fetch_sentry_state(sock)

            # --- HEADER ---
            header_text = " SENTRY RING-0 COMMAND CENTER "
            stdscr.addstr(1, max_x // 2 - len(header_text) // 2, header_text, curses.color_pair(3) | curses.A_BOLD)
            stdscr.addstr(2, 2, "-" * (max_x - 4), curses.color_pair(3))

            if state is None:
                err_msg = "[!] DAEMON OFFLINE OR UNREACHABLE"
                stdscr.addstr(4, max_x // 2 - len(err_msg) // 2, err_msg, curses.color_pair(2) | curses.A_BOLD)
                stdscr.addstr(5, max_x // 2 - 24, "Ensure 'sudo ./target/debug/daemon_rust' is running.")
            else:
                # Render the current arming state
                observe_only = state.get("observe_only", False)
                mode_text = "[ OBSERVE ONLY ]" if observe_only else "[ ARMED ]"
                mode_color = curses.color_pair(4) if observe_only else curses.color_pair(1)
                stdscr.addstr(2, max_x - len(mode_text) - 4, mode_text, mode_color | curses.A_BOLD)

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
                stdscr.addstr(10, 4, "THE PENALTY BOX (20% CPU CLAMP / CRYO SLEEP)", curses.color_pair(3) | curses.A_BOLD)
                
                throttled_tasks = state.get("throttled_tasks", [])
                
                if not throttled_tasks:
                    stdscr.addstr(12, 6, "Box is empty. System state nominal.", curses.color_pair(1))
                else:
                    # Table Header (Expanded COMMAND width to fit the phase tags)
                    stdscr.addstr(12, 6, f"{'PID':<10} | {'COMMAND':<28} | {'TIME REMAINING':<15}", curses.color_pair(4) | curses.A_BOLD)
                    stdscr.addstr(13, 6, "-" * 59)
                    
                    row = 14
                    for task in throttled_tasks:
                        pid = task.get("pid")
                        
                        # Fix 1: Fetch the correct timer key sent by Rust
                        time_left = task.get("time_remaining", 0) 
                        
                        # Fix 2: Fetch the phase and name directly from the Rust JSON
                        phase = task.get("phase", "")
                        proc_name = task.get("name", "UNKNOWN")
                        
                        # Combine phase and name for the display
                        display_name = f"{phase} {proc_name}".strip()
                        
                        # Safely cast to float for display
                        try:
                            time_disp = float(time_left)
                        except ValueError:
                            time_disp = 0.0
                        
                        stdscr.addstr(row, 6, f"{pid:<10} | {display_name:<28} | {time_disp:>4.1f} sec", curses.color_pair(2))
                        row += 1
                        if row >= max_y - 2:
                            break # Prevent UI overflow

            # --- FOOTER ---
            footer_text = "Press 'O' to toggle Observe Mode | Press 'Q' to exit"
            stdscr.addstr(max_y - 2, max_x - len(footer_text) - 2, footer_text, curses.color_pair(3))

            stdscr.refresh()
            time.sleep(0.1) # 10FPS refresh rate (Zero overhead)
            
    finally:
        sock.close()
        if os.path.exists(client_sock_path):
            os.unlink(client_sock_path)

if __name__ == "__main__":
    try:
        curses.wrapper(draw_hud)
    except KeyboardInterrupt:
        pass
