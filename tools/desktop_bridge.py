#!/usr/bin/env python3
"""
tools/desktop_bridge.py

SENTRY Foreground QoS Bridge - Active Window PID Detection.
Maps active window → PID → systemd DBus CPUWeight shift (foreground=10000, background=100).

Supported compositors:
- GNOME (Mutter): Requires GNOME Shell extension for active window (placeholder)
- KWin: org.kde.kwin.Scripting DBus
- X11 fallback: xdotool
"""

import os
import sys
import json
import time
import socket
import logging
import asyncio
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sentry.desktop_bridge")

SENTRY_TELEMETRY_SOCK = "/run/sentry/telemetry.sock"
POLL_INTERVAL = 0.3  # 300ms


class GnomeBackend:
    """GNOME (Mutter) active window detection - placeholder for Wayland.
    
    Note: GNOME Wayland does not expose active window via DBus without a 
    GNOME Shell extension. This backend returns None and logs a warning.
    """

    def __init__(self):
        pass

    async def initialize(self) -> bool:
        logger.warning("GNOME Wayland backend: Active window detection requires GNOME Shell extension. Returning None.")
        return True

    async def get_active_pid(self) -> Optional[int]:
        return None


class KWinBackend:
    """KWin active window detection via Scripting DBus."""

    def __init__(self, bus):
        self._bus = bus
        self._workspace_proxy = None

    async def initialize(self) -> bool:
        try:
            introspection = await self._bus.introspect(
                'org.kde.kwin', '/org/kde/kwin/Scripting'
            )
            proxy = self._bus.get_proxy_object(
                'org.kde.kwin', '/org/kde/kwin/Scripting', introspection
            )
            self._workspace_proxy = proxy.get_interface('org.kde.kwin.Scripting')
            logger.info("KWin Scripting backend initialized")
            return True
        except Exception as e:
            logger.warning(f"KWin backend init failed: {e}")
            return False

    async def get_active_pid(self) -> Optional[int]:
        try:
            if not self._workspace_proxy:
                return None

            # Get active window
            window_variant = await self._workspace_proxy.call_active_window()
            if not window_variant or not window_variant.value:
                return None

            window_path = str(window_variant.value)
            window_proxy = self._bus.get_proxy_object('org.kde.kwin', window_path)
            introspection = await self._bus.introspect('org.kde.kwin', window_path)
            window_iface = window_proxy.get_interface('org.kde.kwin.Window')

            pid_variant = await window_iface.call_get_pid()
            pid = int(pid_variant.value)
            return pid if pid > 0 else None
        except Exception as e:
            logger.debug(f"KWin get_active_pid failed: {e}")
            return None


class X11Backend:
    """X11/XWayland fallback using xdotool."""

    async def get_active_pid(self) -> Optional[int]:
        try:
            proc = await asyncio.create_subprocess_exec(
                'xdotool', 'getactivewindow',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.debug(f"xdotool getactivewindow failed: {stderr.decode().strip()}")
                return None
            win_id = stdout.decode().strip()

            proc = await asyncio.create_subprocess_exec(
                'xdotool', 'getwindowpid', win_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.debug(f"xdotool getwindowpid failed: {stderr.decode().strip()}")
                return None
            pid_str = stdout.decode().strip()
            return int(pid_str) if pid_str.isdigit() else None
        except Exception as e:
            logger.debug(f"X11 backend error: {e}")
            return None


class DesktopBridge:
    """Main desktop bridge - detects active window PID and notifies SENTRY."""

    def __init__(self):
        self._bus = None
        self._backends = []
        self._last_pid = None
        self._socket = None

    async def initialize(self) -> bool:
        """Initialize DBus connection and detect compositor backend."""
        try:
            from dbus_next.aio import MessageBus
            from dbus_next.constants import BusType

            self._bus = await MessageBus(bus_type=BusType.SESSION).connect()

            # Try GNOME backend (placeholder)
            gnome = GnomeBackend()
            if await gnome.initialize():
                logger.info("GNOME backend registered (placeholder)")

            # Try KWin backend
            kwin = KWinBackend(self._bus)
            if await kwin.initialize():
                self._backends.append(kwin)
                logger.info("Using KWin Scripting backend")

            # X11 fallback (always available)
            self._backends.append(X11Backend())
            logger.info("X11/xdotool fallback registered")

            if not self._backends:
                logger.error("No desktop backend available")
                return False

            # UDP socket for SENTRY telemetry
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            return True
        except Exception as e:
            logger.error(f"Desktop bridge initialization failed: {e}")
            return False

    async def get_active_pid(self) -> Optional[int]:
        """Query active backends for current foreground PID."""
        for backend in self._backends:
            try:
                pid = await backend.get_active_pid()
                if pid and pid > 0:
                    return pid
            except Exception as e:
                logger.debug(f"Backend {type(backend).__name__} failed: {e}")
        return None

    async def run(self):
        """Main loop - detect focus changes and notify SENTRY."""
        logger.info(f"Desktop bridge running, polling every {POLL_INTERVAL}s")
        logger.info(f"SENTRY socket: {SENTRY_TELEMETRY_SOCK}")

        while True:
            try:
                pid = await self.get_active_pid()
                if pid and pid != self._last_pid:
                    # Send focus change notification to SENTRY
                    payload = json.dumps({
                        "type": "focus_change",
                        "pid": pid,
                        "timestamp": time.time()
                    }).encode()
                    try:
                        self._socket.sendto(payload, SENTRY_TELEMETRY_SOCK)
                        logger.info(f"Focus change → PID {pid}")
                        self._last_pid = pid
                    except Exception as e:
                        logger.warning(f"Failed to send focus change: {e}")

                await asyncio.sleep(POLL_INTERVAL)
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(1)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    bridge = DesktopBridge()
    if not await bridge.initialize():
        logger.error("Failed to initialize desktop bridge")
        sys.exit(1)

    await bridge.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Desktop bridge stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)