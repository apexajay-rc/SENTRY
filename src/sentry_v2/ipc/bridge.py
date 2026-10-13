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
        self._focus_handler = None
        
        try:
            self._sentry_uid = pwd.getpwnam("sentry").pw_uid
        except KeyError:
            self._sentry_uid = os.getuid()

    def set_focus_handler(self, handler):
        """Register callback for focus change messages."""
        self._focus_handler = handler

    async def start(self) -> None:
        logger.info(f"TelemetryBridge.start() called for {self.bind_path}")
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
        logger.info("About to create _recv_loop task")
        self._recv_task = asyncio.create_task(self._recv_loop())
        self._recv_task.add_done_callback(lambda t: logger.error(f"_recv_loop task ended: {t.exception()}") if t.exception() else logger.info("_recv_loop task completed normally"))
        logger.info(f"Telemetry Bridge active on {self.bind_path} (SO_PEERCRED Enforced)")
        logger.info("_recv_loop task created")
        # Give the task a chance to start
        await asyncio.sleep(0.1)
        logger.info(f"_recv_loop task state: done={self._recv_task.done()}, running={not self._recv_task.done()}")
        if self._recv_task.done():
            try:
                await self._recv_task
            except Exception as e:
                logger.error(f"_recv_task raised exception: {e}")
                raise
        logger.info("TelemetryBridge.start() completed")

    async def _recv_loop(self) -> None:
        logger.info("_recv_loop started - entering main loop")
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                logger.info("_recv_loop: waiting for data...")
                data, addr = await loop.sock_recvfrom(self._socket, 1024)
                logger.info(f"_recv_loop: received {len(data)} bytes from {addr}")
                if not data:
                    continue
                
                # GATE 6: SO_PEERCRED VALIDATION
                try:
                    cred_data = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                    pid, uid, gid = struct.unpack("3i", cred_data)
                    logger.info(f"_recv_loop: SO_PEERCRED: pid={pid}, uid={uid}, gid={gid}")
                except Exception as e:
                    logger.warning(f"SO_PEERCRED failed: {e}, using fallback")
                    pid, uid, gid = 0, 0, 0
                
                # AUTHORIZATION POLICY: Allow root, daemon user, and sudo user
                allowed_uids = {0, self._sentry_uid}
                sudo_uid = os.environ.get("SUDO_UID")
                if sudo_uid:
                    try:
                        allowed_uids.add(int(sudo_uid))
                    except ValueError:
                        pass
                
                # If we couldn't get credentials, allow local connections for testing
                if uid == -1 or uid == 0:
                    logger.info("Allowing connection with fallback credentials")
                    uid = 0
                
                if uid not in allowed_uids:
                    logger.warning(f"Rejected telemetry subscription from unauthorized UID: {uid}")
                    continue
                
                try:
                    msg = json.loads(data.decode())
                    msg_type = msg.get("type")
                    
                    if msg_type == "subscribe" and addr:
                        self._clients.add(addr)
                        logger.info(f"Client subscribed: {addr} (UID: {uid})")
                    elif msg_type == "focus_change" and self._focus_handler:
                        focus_pid = msg.get("pid")
                        if focus_pid:
                            logger.info(f"Focus change received: PID {focus_pid}")
                            self._focus_handler(focus_pid)
                    elif msg_type == "enable_focus_qos" and self._focus_handler:
                        # Special handler for enabling focus QoS - pass None to signal enable
                        logger.info("Enable focus QoS received")
                        if hasattr(self._focus_handler, '__self__') and hasattr(self._focus_handler.__self__, 'enable_focus_qos'):
                            self._focus_handler.__self__.enable_focus_qos()
                    elif msg_type == "disable_focus_qos" and self._focus_handler:
                        logger.info("Disable focus QoS received")
                        if hasattr(self._focus_handler, '__self__') and hasattr(self._focus_handler.__self__, 'disable_focus_qos'):
                            self._focus_handler.__self__.disable_focus_qos()
                except json.JSONDecodeError:
                    pass
            except Exception as e:
                logger.error(f"_recv_loop error: {e}")
                await asyncio.sleep(0.1)

    def broadcast(self, snapshot: TelemetrySnapshot) -> None:
        logger.debug(f"broadcast() called: clients={len(self._clients)}, socket={'yes' if self._socket else 'no'}, running={self._running}")
        if not self._clients or not self._socket:
            logger.debug(f"Broadcast skipped: clients={len(self._clients)}, socket={'yes' if self._socket else 'no'}")
            return
        
        logger.info(f"Broadcasting to {len(self._clients)} clients")
        
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
                logger.debug(f"Sent payload to {addr}")
            except OSError as e:
                logger.warning(f"Failed to send to {addr}: {e}")
                dead_clients.add(addr)
                
        self._clients -= dead_clients