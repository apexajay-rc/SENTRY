"""
daemon/systemd_integration.py

Provides native systemd sd_notify integration without requiring external C libraries.
Allows SENTRY to signal readiness and heartbeat status to the service manager.
"""

import os
import socket
import logging

logger = logging.getLogger(__name__)

class SystemdNotifier:
    """
    Implements the sd_notify protocol via the NOTIFY_SOCKET environment variable.
    """

    def __init__(self) -> None:
        self.notify_socket_path = os.environ.get("NOTIFY_SOCKET")
        if self.notify_socket_path:
            # Handle abstract namespace sockets (which start with '@')
            if self.notify_socket_path.startswith("@"):
                self.notify_socket_path = "\0" + self.notify_socket_path[1:]
            logger.debug(f"Detected systemd NOTIFY_SOCKET at {self.notify_socket_path}")
        else:
            logger.debug("NOTIFY_SOCKET not found. Running outside of systemd supervision.")

    def notify(self, state: str) -> bool:
        """
        Sends a state string to systemd.
        
        Args:
            state: The state payload (e.g., 'READY=1', 'WATCHDOG=1')
            
        Returns:
            True if the message was sent, False otherwise.
        """
        if not self.notify_socket_path:
            return False

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.sendto(state.encode('utf-8'), self.notify_socket_path)
            return True
        except OSError as e:
            logger.warning(f"Failed to send sd_notify message '{state}': {e}")
            return False

    def ready(self) -> None:
        """Signals that the daemon has finished initialization."""
        self.notify("READY=1")

    def stopping(self) -> None:
        """Signals that the daemon is beginning a graceful shutdown."""
        self.notify("STOPPING=1")

    def ping_watchdog(self) -> None:
        """Pings the systemd watchdog to prove the daemon is not deadlocked."""
        self.notify("WATCHDOG=1")
