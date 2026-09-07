import asyncio
import socket
import struct
import json
import os
import pwd
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("sentry.bridge")

@dataclass(frozen=True)
class TelemetrySnapshot:
    timestamp: float
    level: str
    score: float
    cpu_pct: float
    mem_pct: float
    throttled_pids: list[int]
    immune_pids: list[int]

class TelemetryBridge:
    def __init__(self, bind_path: str = "/run/sentry/telemetry.sock"):
        self.bind_path = bind_path
        self._socket: Optional[socket.socket] = None
        self._clients: set = set()
        self._running = False
        
        try:
            self._sentry_uid = pwd.getpwnam("sentry").pw_uid
        except KeyError:
            self._sentry_uid = os.getuid()

    async def start(self) -> None:
        if os.path.exists(self.bind_path):
            try:
                os.unlink(self.bind_path)
            except OSError:
                pass
        
        # Ensure directory exists for standalone testing
        os.makedirs(os.path.dirname(self.bind_path), exist_ok=True)

        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._socket.bind(self.bind_path)
        self._socket.setblocking(False)
        
        try:
            os.chmod(self.bind_path, 0o660)
        except PermissionError:
            pass
        
        self._running = True
        asyncio.create_task(self._recv_loop())
        logger.info(f"Telemetry Bridge active on {self.bind_path} (SO_PEERCRED Enforced)")

    async def _recv_loop(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                data, addr = await loop.sock_recvfrom(self._socket, 1024)
                if not data:
                    continue
                
                # GATE 6: SO_PEERCRED VALIDATION
                cred_data = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                pid, uid, gid = struct.unpack("3i", cred_data)
                
                # AUTHORIZATION POLICY
                if uid not in (0, self._sentry_uid):
                    logger.warning(f"Rejected telemetry subscription from unauthorized UID: {uid}")
                    continue
                
                try:
                    msg = json.loads(data.decode())
                    if msg.get("type") == "subscribe" and addr:
                        self._clients.add(addr)
                except json.JSONDecodeError:
                    pass
            except Exception as e:
                await asyncio.sleep(0.1)

    def broadcast(self, snapshot: TelemetrySnapshot) -> None:
        if not self._clients or not self._socket:
            return
        
        payload = json.dumps({
            "timestamp": snapshot.timestamp,
            "level": snapshot.level,
            "score": snapshot.score,
            "cpu_pct": snapshot.cpu_pct,
            "mem_pct": snapshot.mem_pct,
            "throttled_pids": snapshot.throttled_pids,
            "immune_pids": snapshot.immune_pids,
        }).encode()
        
        dead_clients = set()
        for addr in self._clients:
            try:
                self._socket.sendto(payload, addr)
            except OSError:
                dead_clients.add(addr)
                
        self._clients -= dead_clients
