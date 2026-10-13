#!/usr/bin/env python3
"""
tools/sentry_top.py

SENTRY Top - Real-time system & process monitor for SENTRY.
Shows system stress, SENTRY state, and per-process CPU/memory with CPUWeight.
"""

import asyncio
import json
import socket
import time
import os
import signal
import sys
from typing import Optional, Dict, List
from dataclasses import dataclass, field

from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

SENTRY_TELEMETRY_SOCK = "/run/sentry/telemetry.sock"

console = Console()


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_pct: float
    mem_pct: float
    cpu_weight: int = 100
    throttled: bool = False
    cooldown_remaining: float = 0.0


@dataclass
class SentryState:
    stress_score: float = 0.0
    level: str = "LOW"
    cpu_pct: float = 0.0
    mem_pct: float = 0.0
    psi_cpu: float = 0.0
    psi_mem: float = 0.0
    psi_io: float = 0.0
    throttled_pids: List[int] = field(default_factory=list)
    immune_pids: List[int] = field(default_factory=list)
    foreground_pid: Optional[int] = None
    timestamp: float = 0.0


class ProcessScanner:
    """Scan /proc for process CPU/memory info."""

    def __init__(self):
        self._last_stats: Dict[int, tuple] = {}
        self._page_size = os.sysconf("SC_PAGE_SIZE")

    def scan(self) -> List[ProcessInfo]:
        processes = []
        now = time.time()

        try:
            pids = [int(name) for name in os.listdir("/proc") if name.isdigit()]
        except OSError:
            return []

        for pid in pids:
            try:
                with open(f"/proc/{pid}/stat", "r") as f:
                    data = f.read()
                with open(f"/proc/{pid}/statm", "r") as f:
                    statm = f.read()
                with open(f"/proc/{pid}/comm", "r") as f:
                    name = f.read().strip()
            except (OSError, ValueError):
                continue

            # Parse stat
            try:
                comm_end = data.rindex(')')
                fields = data[comm_end + 2:].split()
                if len(fields) < 15:
                    continue
                utime = int(fields[13])
                stime = int(fields[14])
                total_time = utime + stime
            except (ValueError, IndexError):
                continue

            # CPU%
            cpu_pct = 0.0
            if pid in self._last_stats:
                prev_time, prev_total = self._last_stats[pid]
                proc_delta = total_time - prev_time
                if proc_delta > 0:
                    cpu_pct = min(100.0, proc_delta * 100.0 / (os.cpu_count() or 1))

            self._last_stats[pid] = (total_time, now)

            # Memory%
            try:
                rss_pages = int(statm.split()[1])
                meminfo = {}
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        k, v = line.split(":", 1)
                        meminfo[k] = int(v.split()[0])
                total_mem = meminfo["MemTotal"]
                mem_pct = (rss_pages * os.sysconf("SC_PAGE_SIZE") / 1024) / (total_mem / 1024) * 100
            except:
                mem_pct = 0.0

            if cpu_pct > 0.1 or mem_pct > 0.1:
                processes.append(ProcessInfo(
                    pid=pid,
                    name=name[:15],
                    cpu_pct=round(cpu_pct, 1),
                    mem_pct=round(mem_pct, 1)
                ))

        return sorted(processes, key=lambda p: p.cpu_pct, reverse=True)[:20]


class TelemetryClient:
    """Connect to SENTRY telemetry socket."""

    def __init__(self, sock_path: str = "/run/sentry/telemetry.sock"):
        self.sock_path = sock_path
        self.sock: Optional[socket.socket] = None
        self.state = SentryState()
        self._connected = False

    async def connect(self):
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self.sock.setblocking(False)
            self.sock.bind(f"/tmp/sentry_top_{os.getpid()}.sock")

            # Subscribe
            msg = json.dumps({"type": "subscribe"}).encode()
            self.sock.sendto(msg, self.sock_path)
            self._connected = True
        except Exception as e:
            self._connected = False

    async def poll(self):
        if not self._connected or not self.sock:
            return
        try:
            data, _ = self.sock.recvfrom(4096)
            if data:
                msg = json.loads(data.decode())
                self._update_state(msg)
        except BlockingIOError:
            pass
        except Exception:
            pass

    def _update_state(self, msg: dict):
        self.state.stress_score = msg.get("stress_score", self.state.stress_score)
        self.state.level = msg.get("level", self.state.level)
        self.state.cpu_pct = msg.get("cpu_pct", self.state.cpu_pct)
        self.state.mem_pct = msg.get("mem_pct", self.state.mem_pct)
        self.state.throttled_pids = msg.get("throttled_pids", self.state.throttled_pids)
        self.state.immune_pids = msg.get("immune_pids", self.state.immune_pids)
        self.state.foreground_pid = msg.get("foreground_pid", self.state.foreground_pid)
        self.state.timestamp = msg.get("timestamp", time.time())

        # If focus_change message
        if msg.get("type") == "focus_change":
            self.state.foreground_pid = msg.get("pid")


class SentryTop:
    def __init__(self):
        self.console = Console()
        self.scanner = ProcessScanner()
        self.telemetry = TelemetryClient()
        self.processes: List[ProcessInfo] = []
        self.running = True
        self.last_update = 0

    async def setup(self):
        await self.telemetry.connect()
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        self.running = False

    def _make_header(self) -> Panel:
        state = self.telemetry.state

        # Stress bar
        stress = state.stress_score
        bar_width = 40
        filled = int(stress / 120 * 40)
        bar = "█" * filled + "░" * (40 - filled)

        level_color = {
            "LOW": "green",
            "MODERATE": "yellow",
            "HIGH": "orange3",
            "CRITICAL": "red"
        }.get(state.level, "white")

        # Foreground indicator
        fg_text = ""
        if state.foreground_pid:
            fg_text = f"  🎯 Foreground PID: [bold cyan]{state.foreground_pid}[/bold cyan]"

        header_text = Text()
        header_text.append("SENTRY TOP  ", style="bold white on blue")
        header_text.append(f"  Stress: {stress:.1f}/120  ", style="white")
        header_text.append(f"[{bar}]  ", style=level_color)
        header_text.append(f"Level: ", style="white")
        header_text.append(state.level, style=f"bold {level_color}")
        header_text.append(f"  CPU: {self.telemetry.state.cpu_pct:.1f}%  ", style="white")
        header_text.append(f"RAM: {self.telemetry.state.mem_pct:.1f}%  ", style="white")
        header_text.append(f"PSI: CPU={self.telemetry.state.psi_cpu:.1f}% MEM={self.telemetry.state.psi_mem:.1f}% IO={self.telemetry.state.psi_io:.1f}%", style="dim white")
        header_text.append(fg_text)

        return Panel(header_text, border_style=level_color, padding=(0, 1))

    def _make_process_table(self) -> Table:
        table = Table(show_header=True, header_style="bold cyan", show_lines=False)
        table.add_column("PID", style="cyan", width=8)
        table.add_column("NAME", style="white", width=18)
        table.add_column("CPU%", style="magenta", width=8, justify="right")
        table.add_column("MEM%", style="green", width=8, justify="right")
        table.add_column("WEIGHT", style="yellow", width=8, justify="right")
        table.add_column("STATUS", style="white", width=12)

        throttled_set = set(self.telemetry.state.throttled_pids)
        immune_set = set(self.telemetry.state.immune_pids)

        for proc in self.processes:
            status_parts = []
            if proc.pid in immune_set:
                status_parts.append("[green]🛡 IMMUNE[/green]")
            if proc.pid in self.telemetry.state.throttled_pids:
                status_parts.append("[red]⚡ THROTTLED[/red]")
            if self.telemetry.state.foreground_pid == proc.pid:
                status_parts.append("[bold cyan]🎯 FOREGROUND[/bold cyan]")

            status = " ".join(status_parts) if status_parts else "running"

            weight = "N/A"

            table.add_row(
                str(proc.pid),
                proc.name,
                f"{proc.cpu_pct:.1f}",
                f"{proc.mem_pct:.1f}",
                weight,
                status
            )

        return table

    def _make_throttled_panel(self) -> Panel:
        state = self.telemetry.state
        if not state.throttled_pids:
            return Panel("[dim]No throttled processes[/dim]", title="⚡ Throttled", border_style="red")

        lines = []
        for pid in state.throttled_pids:
            proc_info = next((p for p in self.processes if p.pid == pid), None)
            name = proc_info.name if proc_info else "unknown"
            lines.append(f"  PID [cyan]{pid}[/cyan]  {name}")

        return Panel("\n".join(lines), title="⚡ Throttled", border_style="red")

    def _make_immune_panel(self) -> Panel:
        state = self.telemetry.state
        if not state.immune_pids:
            return Panel("[dim]No immune processes[/dim]", title="🛡 Immune", border_style="green")

        lines = []
        for pid in state.immune_pids:
            proc_info = next((p for p in self.processes if p.pid == pid), None)
            name = proc_info.name if proc_info else "unknown"
            lines.append(f"  PID [cyan]{pid}[/cyan]  {name}")

        return Panel("\n".join(lines), title="🛡 Immune", border_style="green")

    def _render(self):
        """Render everything as a single string for Live display."""
        lines = []
        
        # Header
        state = self.telemetry.state
        stress = state.stress_score
        bar_width = 40
        filled = int(stress / 120 * 40)
        bar = "█" * filled + "░" * (40 - filled)
        
        level_color = {
            "LOW": "green",
            "MODERATE": "yellow",
            "HIGH": "orange3",
            "CRITICAL": "red"
        }.get(state.level, "white")

        lines.append(f"SENTRY TOP   Stress: {stress:.1f}/120  [{bar}]  Level: {state.level}")
        lines.append(f"  CPU: {self.telemetry.state.cpu_pct:.1f}%  RAM: {self.telemetry.state.mem_pct:.1f}%  PSI: CPU={self.telemetry.state.psi_cpu:.1f}% MEM={self.telemetry.state.psi_mem:.1f}% IO={self.telemetry.state.psi_io:.1f}%")
        if self.telemetry.state.foreground_pid:
            lines.append(f"  🎯 Foreground PID: {state.foreground_pid}")
        lines.append("")

        # Process table
        lines.append(f"{'PID':>8}  {'NAME':<18}  {'CPU%':>6}  {'MEM%':>6}  {'WEIGHT':>6}  {'STATUS'}")
        lines.append("-" * 80)
        
        throttled_set = set(self.telemetry.state.throttled_pids)
        immune_set = set(self.telemetry.state.immune_pids)
        
        for proc in self.processes:
            status_parts = []
            if proc.pid in immune_set:
                status_parts.append("🛡 IMMUNE")
            if proc.pid in self.telemetry.state.throttled_pids:
                status_parts.append("⚡ THROTTLED")
            if self.telemetry.state.foreground_pid == proc.pid:
                status_parts.append("🎯 FOREGROUND")
            
            status = " ".join(status_parts) if status_parts else "running"
            weight = "N/A"
            
            lines.append(f"{proc.pid:>8}  {proc.name:<18}  {proc.cpu_pct:>5.1f}  {proc.mem_pct:>5.1f}  {str('N/A'):>6}  {' '.join(status_parts) if status_parts else 'running'}")

        lines.append("")
        
        # Throttled panel
        if self.telemetry.state.throttled_pids:
            lines.append("⚡ Throttled:")
            for pid in self.telemetry.state.throttled_pids:
                proc_info = next((p for p in self.processes if p.pid == pid), None)
                name = proc_info.name if proc_info else "unknown"
                lines.append(f"  PID {pid}  {name}")
        else:
            lines.append("⚡ Throttled: (none)")
        
        lines.append("")
        
        # Immune panel
        if self.telemetry.state.immune_pids:
            lines.append("🛡 Immune:")
            for pid in self.telemetry.state.immune_pids:
                proc_info = next((p for p in self.processes if p.pid == pid), None)
                name = proc_info.name if proc_info else "unknown"
                lines.append(f"  PID {pid}  {name}")
        else:
            lines.append("🛡 Immune: (none)")

        return "\n".join(lines)

    async def run(self):
        await self.setup()

        self.console.clear()
        while self.running:
            # Update telemetry
            await self.telemetry.poll()

            # Scan processes every 1s
            if time.time() - self.last_update >= 1.0:
                self.processes = self.scanner.scan()
                self.last_update = time.time()

            # Render
            self.console.clear()
            self.console.print(self._render())
            await asyncio.sleep(0.5)


async def main():
    app = SentryTop()
    await app.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold red]SENTRY TOP stopped[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        sys.exit(1)