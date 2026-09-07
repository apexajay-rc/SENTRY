#!/usr/bin/env python3
import tkinter as tk
import socket
import json
import os
import sys

DAEMON_SOCK = "/run/sentry/telemetry.sock"
CLIENT_SOCK = f"/tmp/sentry_hud_{os.getpid()}.sock"

class SentryHUD:
    def __init__(self, root):
        self.root = root
        self.root.title("SENTRY V2 - Telemetry")
        self.root.geometry("350x200")
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#111111")
        
        # UI Elements
        self.state_label = tk.Label(root, text="WAITING FOR TELEMETRY...", font=("Courier", 16, "bold"), fg="#aaaaaa", bg="#111111")
        self.state_label.pack(pady=10)
        
        self.score_label = tk.Label(root, text="Score: --/120", font=("Courier", 12), fg="#ffffff", bg="#111111")
        self.score_label.pack()
        
        self.metrics_label = tk.Label(root, text="CPU: --% | RAM: --%", font=("Courier", 12), fg="#ffffff", bg="#111111")
        self.metrics_label.pack()
        
        self.clamp_label = tk.Label(root, text="Clamped PIDs: None", font=("Courier", 10), fg="#ff5555", bg="#111111")
        self.clamp_label.pack(pady=15)

        # IPC Setup
        self.setup_ipc()
        self.update_loop()

    def setup_ipc(self):
        if os.path.exists(CLIENT_SOCK):
            os.unlink(CLIENT_SOCK)
            
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(CLIENT_SOCK)
        self.sock.setblocking(False)
        
        try:
            self.sock.sendto(b'{"type": "subscribe"}', DAEMON_SOCK)
        except OSError:
            self.state_label.config(text="DAEMON OFFLINE", fg="#ff5555")

    def update_loop(self):
        try:
            while True:
                data = self.sock.recv(4096)
                self.render_data(json.loads(data.decode()))
        except BlockingIOError:
            pass
        except Exception:
            pass
        finally:
            self.root.after(100, self.update_loop)

    def render_data(self, msg):
        level = msg.get("level", "UNKNOWN")
        color = "#55ff55" if level == "NORMAL" else "#ffff55" if level == "MODERATE" else "#ff5555"
        
        self.state_label.config(text=f"STATE: {level}", fg=color)
        self.score_label.config(text=f"Score: {msg.get('score', 0):.2f}/120")
        self.metrics_label.config(text=f"CPU: {msg.get('cpu_pct', 0):.1f}% | RAM: {msg.get('mem_pct', 0):.1f}%")
        
        pids = msg.get("throttled_pids", [])
        pid_text = ", ".join(map(str, pids)) if pids else "None"
        self.clamp_label.config(text=f"Clamped PIDs: {pid_text}")

if __name__ == "__main__":
    root = tk.Tk()
    app = SentryHUD(root)
    
    def on_closing():
        try:
            os.unlink(CLIENT_SOCK)
        except OSError:
            pass
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()
