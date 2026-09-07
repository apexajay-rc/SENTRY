import os
import socket
import logging

logger = logging.getLogger("sentry.systemd")

def sd_notify(state: str) -> None:
    sock_path = os.environ.get("NOTIFY_SOCKET")
    if not sock_path:
        logger.warning("NOTIFY_SOCKET env var is missing! Systemd did not pass it.")
        return
    
    # Abstract namespace sockets start with '@'
    if sock_path.startswith('@'):
        sock_path = '\0' + sock_path[1:]
        
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(state.encode(), sock_path)
        logger.info(f"Successfully sent to systemd: {state}")
    except Exception as e:
        logger.error(f"Failed to send {state} to systemd socket {sock_path}: {e}")
