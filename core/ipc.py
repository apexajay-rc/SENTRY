"""
core/ipc.py

SENTRY Inter-Process Communication (IPC) module.
Hardened v1.0: Implements a strict ThreadPoolExecutor and Slow-Loris timeout
to mathematically prevent Thread Explosion Denial-of-Service (DoS) attacks.
"""

import json
import os
import socket
import threading
import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 17481


def default_unix_socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return os.path.join(runtime, "sentry.sock")
    if os.name == "nt":
        return os.path.join(os.environ.get("TEMP", "."), "sentry.sock")
    return "/tmp/sentry.sock"


def resolve_ipc_endpoint() -> tuple[Any, ...]:
    override = os.environ.get("SENTRY_IPC_ENDPOINT")
    if override:
        return _parse_endpoint(override)

    if os.name != "nt":
        return ("unix", os.environ.get("SENTRY_IPC_SOCKET", default_unix_socket_path()))
    return ("tcp", DEFAULT_TCP_HOST, DEFAULT_TCP_PORT)


def _parse_endpoint(value: str) -> tuple[Any, ...]:
    if value.startswith("unix:"):
        return ("unix", value[5:])
    if value.startswith("tcp:"):
        host, port = value[4:].rsplit(":", 1)
        return ("tcp", host, int(port))
    raise ValueError(f"Invalid SENTRY IPC endpoint: {value}")


@dataclass
class DaemonState:
    platform: str = "unknown"
    mode: str = "Balanced"
    armed: bool = False
    observe_only: bool = True
    dry_run: bool = False
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    io_wait_percent: float = 0.0
    stress_score: float = 0.0
    utilization_score: float = 0.0
    psi_score: Optional[float] = None
    level: str = "LOW"
    trend: str = "Collecting"
    target_pid: Optional[int] = None
    target_comm: Optional[str] = None
    target_score: Optional[float] = None
    last_action: str = "No action executed"
    stress_history: list[float] = field(default_factory=list)
    top_processes: list[dict[str, Any]] = field(default_factory=list)
    psi_cpu_some_avg10: Optional[float] = None
    psi_memory_some_avg10: Optional[float] = None
    psi_io_some_avg10: Optional[float] = None
    updated_at: str = ""

    def __post_init__(self):
        self._lock = threading.RLock()

    def update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "platform": self.platform,
                "mode": self.mode,
                "armed": self.armed,
                "observe_only": self.observe_only,
                "dry_run": self.dry_run,
                "cpu_percent": self.cpu_percent,
                "memory_percent": self.memory_percent,
                "io_wait_percent": self.io_wait_percent,
                "stress_score": self.stress_score,
                "utilization_score": self.utilization_score,
                "psi_score": self.psi_score,
                "level": self.level,
                "trend": self.trend,
                "target_pid": self.target_pid,
                "target_comm": self.target_comm,
                "target_score": self.target_score,
                "last_action": self.last_action,
                "stress_history": list(self.stress_history),
                "top_processes": list(self.top_processes),
                "psi": {
                    "cpu": self.psi_cpu_some_avg10,
                    "memory": self.psi_memory_some_avg10,
                    "io": self.psi_io_some_avg10,
                },
                "updated_at": self.updated_at,
            }

    def apply_command(self, command: dict[str, Any]) -> dict[str, Any]:
        cmd_type = command.get("type")
        if cmd_type == "get_state":
            return {"ok": True, "state": self.snapshot()}

        with self._lock:
            if cmd_type == "set_mode":
                mode = command.get("mode")
                if mode not in {"Gaming", "Editing", "Balanced"}:
                    return {"ok": False, "error": "Invalid mode"}
                self.mode = mode
            elif cmd_type == "set_armed":
                self.armed = bool(command.get("armed", False))
            elif cmd_type == "set_observe_only":
                self.observe_only = bool(command.get("observe_only", True))
            elif cmd_type == "set_dry_run":
                self.dry_run = bool(command.get("dry_run", False))
            elif cmd_type == "ping":
                return {"ok": True, "pong": True}
            else:
                return {"ok": False, "error": f"Unknown command: {cmd_type}"}

            self.updated_at = datetime.now(timezone.utc).isoformat()
            return {"ok": True, "state": self.snapshot()}


class IpcServer:
    def __init__(
        self,
        state: DaemonState,
        endpoint: Optional[tuple[Any, ...]] = None,
    ):
        self.state = state
        self.endpoint = endpoint or resolve_ipc_endpoint()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._socket: Optional[socket.socket] = None
        self.address: Optional[tuple[Any, ...]] = None
        
        # Security Hardening: Cap maximum concurrent IPC threads to prevent DoS
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=10, thread_name_prefix="SentryIpcWorker")

    def start_background(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
        
        # Gracefully shutdown the thread pool without waiting for hijacked sockets
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _serve(self) -> None:
        kind = self.endpoint[0]
        sock = socket.socket(socket.AF_UNIX if kind == "unix" else socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket = sock

        if kind == "unix":
            path = self.endpoint[1]
            if os.path.exists(path):
                os.unlink(path)
            sock.bind(path)
            self.address = ("unix", path)
        else:
            host, port = self.endpoint[1], self.endpoint[2]
            sock.bind((host, port))
            self.address = ("tcp", host, sock.getsockname()[1])

        sock.listen(5)
        sock.settimeout(0.5)

        while not self._stop.is_set():
            try:
                conn, _addr = sock.accept()
                # Security Hardening: Strict 5-second socket timeout to prevent Slow-Loris thread hijacking
                conn.settimeout(5.0)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                break

            try:
                # Dispatch to bounded pool instead of infinitely spawning OS threads
                self._pool.submit(self._handle_client, conn)
            except RuntimeError:
                # Pool is shutting down, safely close the connection and exit
                conn.close()
                break

    def _handle_client(self, conn: socket.socket) -> None:
        with conn:
            try:
                payload = _recv_line(conn)
                if not payload:
                    return
                request = json.loads(payload)
                response = self.state.apply_command(request)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                response = {"ok": False, "error": str(exc)}
            except Exception as exc:
                response = {"ok": False, "error": f"Unhandled error: {exc}"}
                
            try:
                _send_line(conn, json.dumps(response))
            except OSError:
                pass


class IpcClient:
    def __init__(self, endpoint: Optional[tuple[Any, ...]] = None):
        self.endpoint = endpoint or resolve_ipc_endpoint()
        self.timeout = 1.0

    def request(self, command: dict[str, Any]) -> dict[str, Any]:
        kind = self.endpoint[0]
        sock = socket.socket(socket.AF_UNIX if kind == "unix" else socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            if kind == "unix":
                sock.connect(self.endpoint[1])
            else:
                sock.connect((self.endpoint[1], self.endpoint[2]))
            _send_line(sock, json.dumps(command))
            payload = _recv_line(sock)
            if not payload:
                return {"ok": False, "error": "Empty response"}
            return json.loads(payload)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            sock.close()

    def ping(self) -> bool:
        return self.request({"type": "ping"}).get("ok", False)

    def get_state(self) -> Optional[dict[str, Any]]:
        response = self.request({"type": "get_state"})
        if response.get("ok"):
            return response.get("state")
        return None

    def set_mode(self, mode: str) -> Optional[dict[str, Any]]:
        response = self.request({"type": "set_mode", "mode": mode})
        if response.get("ok"):
            return response.get("state")
        return None

    def set_armed(self, armed: bool) -> Optional[dict[str, Any]]:
        response = self.request({"type": "set_armed", "armed": armed})
        if response.get("ok"):
            return response.get("state")
        return None

    def set_observe_only(self, observe_only: bool) -> Optional[dict[str, Any]]:
        response = self.request({"type": "set_observe_only", "observe_only": observe_only})
        if response.get("ok"):
            return response.get("state")
        return None

    def set_dry_run(self, dry_run: bool) -> Optional[dict[str, Any]]:
        response = self.request({"type": "set_dry_run", "dry_run": dry_run})
        if response.get("ok"):
            return response.get("state")
        return None


def _send_line(conn: socket.socket, message: str) -> None:
    conn.sendall((message + "\n").encode("utf-8"))


def _recv_line(conn: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        data = conn.recv(4096)
        if not data:
            break
        chunks.append(data)
        if b"\n" in data:
            break
    if not chunks:
        return ""
    return b"".join(chunks).split(b"\n", 1)[0].decode("utf-8")
