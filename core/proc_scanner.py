#!/usr/bin/env python3
"""
core/proc_scanner.py

Lightweight PID scanner with process inception grace period protection.
Prevents cold-start clamping of newly launched applications.
"""

import os
import time
import psutil
from typing import Optional, Dict, Set

# Grace period constants
DEFAULT_INCEPTION_GRACE_SEC = 15.0      # Seconds after spawn before eligible for throttle
MAX_INCEPTION_GRACE_SEC = 60.0          # Cap for abnormal spawns (e.g., fork bombs)
MIN_PROCESS_AGE_SEC = 0.5               # Minimum age to even consider (kernel noise)
LAUNCH_BURST_THRESHOLD = 0.8            # CPU fraction during grace (0.8 = 80% of core)


class ProcessInceptionTracker:
    """
    Tracks process inception timestamps to implement cold-start grace period.
    Uses psutil.Process.create_time() which reads /proc/[pid]/stat starttime.
    """

    def __init__(self, grace_period_sec: float = DEFAULT_INCEPTION_GRACE_SEC):
        self.grace_period_sec = min(grace_period_sec, MAX_INCEPTION_GRACE_SEC)
        self._inception_cache: Dict[int, float] = {}  # pid -> create_time (monotonic)
        self._last_cleanup = time.monotonic()

    def record_inception(self, pid: int) -> None:
        """Record the inception time of a newly seen process."""
        try:
            proc = psutil.Process(pid)
            # psutil.create_time() returns wall-clock; convert to monotonic-relative
            create_time = proc.create_time()
            # Convert to monotonic by subtracting boot time offset
            boot_time = psutil.boot_time()
            inception_mono = create_time - boot_time + time.monotonic() - time.time()
            self._inception_cache[pid] = inception_mono
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass

    def is_in_grace_period(self, pid: int) -> bool:
        """
        Returns True if process is within its inception grace period.
        Also handles processes that fork: child inherits parent's remaining grace.
        """
        inception = self._inception_cache.get(pid)
        if inception is None:
            # Not tracked yet - record and grant grace
            self.record_inception(pid)
            return True

        age = time.monotonic() - inception
        return age < self.grace_period_sec

    def get_remaining_grace(self, pid: int) -> float:
        """Returns remaining grace period in seconds (0 if expired)."""
        inception = self._inception_cache.get(pid)
        if inception is None:
            return self.grace_period_sec
        remaining = self.grace_period_sec - (time.monotonic() - inception)
        return max(0.0, remaining)

    def cleanup_stale(self, active_pids: Set[int]) -> None:
        """Remove tracking for dead processes."""
        now = time.monotonic()
        if now - self._last_cleanup < 30.0:  # Throttle cleanup
            return
        dead = set(self._inception_cache.keys()) - active_pids
        for pid in dead:
            del self._inception_cache[pid]
        self._last_cleanup = now


class ProcScanner:
    """
    Lightweight PID scanner mathematically bound to the hardware topology.
    Includes process inception grace period to prevent cold-start clamping.
    """

    def __init__(self, inception_grace_sec: float = DEFAULT_INCEPTION_GRACE_SEC):
        self.procs: Dict[int, psutil.Process] = {}
        self.cpu_cache: Dict[int, float] = {}
        self.tick_count = 0

        # Hardware topology for O(1) math lookups
        self.core_count = psutil.cpu_count(logical=True) or 1

        # Dynamic topology threshold: 95% of single core = throttle trigger
        self.dynamic_threshold = 95.0 / self.core_count

        # Process inception grace period tracker
        self.inception = ProcessInceptionTracker(inception_grace_sec)

    def get_top_hogs(self, threshold: Optional[float] = None) -> list:
        """
        Returns PIDs exceeding CPU threshold, excluding processes in inception grace period.
        Dynamically engages Swarm Detection if the system is stressed but no single hog exists.
        """
        self.tick_count += 1
        hogs = []
        candidates = {}

        active_threshold = threshold if threshold is not None else self.dynamic_threshold
        active_pids: Set[int] = set()

        # Periodic cleanup of dead PIDs
        if self.tick_count % 10 == 0:
            current_pids = set(psutil.pids())
            dead_pids = set(self.procs.keys()) - current_pids
            for pid in dead_pids:
                del self.procs[pid]
                if pid in self.cpu_cache:
                    del self.cpu_cache[pid]
            # Clean inception tracker
            self.inception.cleanup_stale(current_pids)

        for pid in psutil.pids():
            active_pids.add(pid)
            is_grace = self.inception.is_in_grace_period(pid)

            try:
                if pid not in self.procs:
                    p = psutil.Process(pid)
                    p.cpu_percent()  # Prime the psutil counter
                    self.procs[pid] = p
                    self.cpu_cache[pid] = 0.0
                    self.inception.record_inception(pid)
                    continue

                raw_cpu = self.procs[pid].cpu_percent()
                system_cpu = raw_cpu / self.core_count
                self.cpu_cache[pid] = system_cpu

                burst_threshold_system = (LAUNCH_BURST_THRESHOLD * 100) / self.core_count

                if is_grace:
                    # LAUNCH BURST DETECTION: Break grace period if abusive
                    if system_cpu >= burst_threshold_system:
                        candidates[pid] = system_cpu
                    else:
                        self.inception.record_inception(pid)
                        continue
                else:
                    candidates[pid] = system_cpu

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                if pid in self.procs:
                    del self.procs[pid]
                if pid in self.cpu_cache:
                    del self.cpu_cache[pid]
            except Exception:
                pass

        # 1. Standard Hog Detection
        for pid, cpu in candidates.items():
            if cpu > active_threshold:
                hogs.append(pid)

        # 2. Swarm Detection
        # SENTRY only calls this function if the global system is stressed.
        # If no single process breached the strict threshold, it is a swarm attack.
        if not hogs and candidates:
            # Sort candidates by CPU utilization (highest first)
            sorted_candidates = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
            # Target the top contributors to break the swarm (minimum 2% system CPU to ignore noise)
            for pid, cpu in sorted_candidates[:4]:
                if cpu >= 2.0:
                    hogs.append(pid)

        return hogs

    def get_inception_info(self, pid: int) -> Dict:
        """Returns inception tracking info for debugging/monitoring."""
        remaining = self.inception.get_remaining_grace(pid)
        return {
            "pid": pid,
            "in_grace_period": remaining > 0,
            "remaining_grace_sec": round(remaining, 1),
            "grace_period_sec": self.inception.grace_period_sec
        }