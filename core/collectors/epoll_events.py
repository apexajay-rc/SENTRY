"""
core/collectors/epoll_events.py

Provides a minimal, event-driven reactor using Linux epoll.
Designed to monitor kernel event descriptors (like PSI triggers)
without active polling.
"""

import select
import logging
import errno
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Type alias for callbacks: takes an integer file descriptor and an integer event mask
EventCallback = Callable[[int, int], None]

class EpollReactor:
    """
    A lightweight event loop utilizing Linux epoll.
    
    This class manages file descriptors and executes registered callbacks
    when the kernel signals state changes (e.g., EPOLLPRI for PSI events).
    """

    def __init__(self) -> None:
        try:
            self._epoll = select.epoll()
        except AttributeError:
            raise RuntimeError("epoll is not available on this platform. SENTRY requires Linux.")
        
        # Maps file descriptor (int) to its registered callback
        self._callbacks: Dict[int, EventCallback] = {}
        self._running = False

    def register(self, fd: int, callback: EventCallback, eventmask: int = select.EPOLLPRI | select.EPOLLERR) -> None:
        """
        Registers a file descriptor for monitoring.

        Args:
            fd: The file descriptor integer to monitor.
            callback: The function to execute when the event fires.
            eventmask: The epoll event mask. Defaults to EPOLLPRI (used by PSI) and EPOLLERR.
        """
        if fd in self._callbacks:
            logger.warning(f"File descriptor {fd} is already registered. Overwriting callback.")
            self.unregister(fd)

        try:
            self._epoll.register(fd, eventmask)
            self._callbacks[fd] = callback
            logger.debug(f"Registered FD {fd} with mask {bin(eventmask)}")
        except OSError as e:
            logger.error(f"Failed to register FD {fd} with epoll: {e}")
            raise

    def unregister(self, fd: int) -> None:
        """Stops monitoring a file descriptor and removes its callback."""
        if fd in self._callbacks:
            try:
                self._epoll.unregister(fd)
            except OSError as e:
                # Ignore ENOENT (No such file or directory) if the FD was already closed
                if e.errno != errno.ENOENT:
                    logger.warning(f"Error unregistering FD {fd}: {e}")
            finally:
                del self._callbacks[fd]
                logger.debug(f"Unregistered FD {fd}")

    def poll(self, timeout: float = 1.0) -> None:
        """
        Blocks until an event occurs or the timeout is reached.
        Executes callbacks for any triggered file descriptors.

        Args:
            timeout: Maximum time to block in seconds.
        """
        try:
            # epoll.poll timeout is in seconds
            events = self._epoll.poll(timeout)
        except InterruptedError:
            # standard behavior during signal handling (e.g., SIGTERM)
            return
        except OSError as e:
            logger.error(f"epoll loop encountered an OS error: {e}")
            return

        for fd, event_mask in events:
            callback = self._callbacks.get(fd)
            if callback:
                try:
                    callback(fd, event_mask)
                except Exception as e:
                    logger.exception(f"Unhandled exception in callback for FD {fd}: {e}")
            else:
                # This indicates a state mismatch between epoll and our registry
                logger.error(f"Event received for unregistered FD {fd}. Unregistering from epoll.")
                self.unregister(fd)

    def close(self) -> None:
        """Closes the epoll object and clears all registries."""
        self._callbacks.clear()
        if not self._epoll.closed:
            self._epoll.close()

    def __enter__(self) -> 'EpollReactor':
        return self

    def __exit__(self, exc_type: Optional[type], exc_val: Optional[Exception], exc_tb: Optional[object]) -> None:
        self.close()
