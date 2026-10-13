import time
import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import Optional

from src.sentry_v2.daemon.systemd import sd_notify
from src.sentry_v2.metrics.sampler import MetricsSampler
from src.sentry_v2.scanner.proc_scanner import ProcScanner
from src.sentry_v2.ipc.bridge import TelemetryBridge, TelemetrySnapshot
from src.sentry_v2.policy.scoring import compute_stress
from src.sentry_v2.policy.state_machine import StateMachine
from src.sentry_v2.policy.fair_share import allocate
from src.sentry_v2.policy.immunity import ImmunityEngine
from src.sentry_v2.actuator.factory import create_actuator
from src.sentry_v2.actuator.protocol import ThrottleSpec
from src.sentry_v2.config import load_config

# FIX: Restore logging configuration so we can actually see the output!
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sentry.control")

# Experiment scope names
FOREGROUND_SCOPE = "foreground.scope"
BACKGROUND_SCOPE = "background.scope"
EXPERIMENT_SCOPES = {FOREGROUND_SCOPE, BACKGROUND_SCOPE}


class ControlLoop:
    def __init__(self, config_path: str = "sentry-v2.yaml"):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.sampler = MetricsSampler()
        self.scanner = ProcScanner(sampler=self.sampler)
        self.state_machine = StateMachine(self.config.thresholds)
        self.immunity = ImmunityEngine(self.config.immunity)
        self.actuator = None
        self.telemetry_bridge = None
        self._throttled_pids = set()
        self.num_cores = os.cpu_count() or 1
        self._running = False
        self._reload = False
        
        # Focus-based QoS state
        self._foreground_scope: Optional[str] = None
        self._focus_active = False

    async def initialize(self):
        self.actuator = await create_actuator()
        await self.immunity.initialize()
        
        # Initialize telemetry bridge (handle permission errors gracefully)
        self.telemetry_bridge = TelemetryBridge()
        try:
            await self.telemetry_bridge.start()
            # Register focus change handler
            self.telemetry_bridge.set_focus_handler(self._handle_focus_change)
        except PermissionError:
            logger.warning("Telemetry bridge failed to start (permission denied). Running without telemetry.")
            self.telemetry_bridge = None
        
        loop = asyncio.get_event_loop()
        try: loop.add_signal_handler(signal.SIGHUP, lambda: setattr(self, '_reload', True))
        except NotImplementedError: pass # Windows support

    def _handle_focus_change(self, pid: int):
        """Handle focus change from desktop bridge - shift experiment scope weights."""
        if not self._focus_active:
            return
            
        # Find which experiment scope this PID belongs to
        target_scope = self._pid_to_experiment_scope(pid)
        if not target_scope:
            # PID not in our experiment scopes - ignore
            logger.debug(f"Focus PID {pid} not in experiment scopes, ignoring")
            return
            
        # Shift weights: focused=10000, unfocused=100
        focused_weight = 10000
        unfocused_weight = 100
        
        if target_scope == FOREGROUND_SCOPE:
            logger.info(f"FOCUS SHIFT: foreground.scope=10000, background.scope=100 (PID {pid})")
            asyncio.create_task(self.actuator._set_cpu_weight(FOREGROUND_SCOPE, focused_weight))
            asyncio.create_task(self.actuator._set_cpu_weight(BACKGROUND_SCOPE, unfocused_weight))
        elif target_scope == BACKGROUND_SCOPE:
            logger.info(f"FOCUS SHIFT: background.scope=10000, foreground.scope=100 (PID {pid})")
            asyncio.create_task(self.actuator._set_cpu_weight(BACKGROUND_SCOPE, focused_weight))
            asyncio.create_task(self.actuator._set_cpu_weight(FOREGROUND_SCOPE, unfocused_weight))

    def _pid_to_experiment_scope(self, pid: int) -> Optional[str]:
        """Check if PID belongs to an experiment scope, return scope name or None."""
        try:
            with open(f'/proc/{pid}/cgroup', 'r') as f:
                cgroup_path = f.read().strip().split(':')[-1]
            # Extract leaf scope
            if cgroup_path and cgroup_path != '/':
                leaf = cgroup_path.strip('/').split('/')[-1]
                leaf_unit = leaf.replace('_2e', '.').replace('_2d', '-')
                if leaf_unit in EXPERIMENT_SCOPES:
                    return leaf_unit
        except Exception:
            pass
        return None

    def enable_focus_qos(self):
        """Enable focus-based QoS (called when experiment starts)."""
        self._focus_active = True
        logger.info("Focus-based QoS ENABLED")

    def disable_focus_qos(self):
        """Disable focus-based QoS, restore equal weights."""
        self._focus_active = False
        # Restore equal weights
        asyncio.create_task(self.actuator._set_cpu_weight(FOREGROUND_SCOPE, 10000))
        asyncio.create_task(self.actuator._set_cpu_weight(BACKGROUND_SCOPE, 10000))
        logger.info("Focus-based QoS DISABLED - weights restored to 10000")

    async def run(self):
        await self.initialize()
        self._running = True
        logger.info(f"Control loop started. Cores: {self.num_cores}")
        self.sampler.sample()  # Prime the sampler (synchronous)
        await asyncio.sleep(1.0)

        while self._running:
            tick = time.time()
            if self._reload:
                self.config = load_config(self.config_path)
                self.state_machine = StateMachine(self.config.thresholds)
                self._reload = False
                logger.info("Config SIGHUP reloaded.")

            try:
                sample = self.sampler.sample()
                score = compute_stress(sample, self.config.thresholds)
                level, trans = self.state_machine.step(score)
                policy = self.state_machine.get_policy()
                
                # FIX: Bring back the heartbeat so we can see the daemon breathing
                logger.info(f"HEARTBEAT: Score {score.combined}/120 (CPU: {sample.cpu_pct}%, RAM: {sample.mem_pct}%)")

                if trans:
                    logger.info(f"State -> {level.name} | Score: {score.combined}/120")

                new_throttled = set()
                if policy.max_hogs > 0:
                    hogs = self.scanner.get_top_hogs(max_hogs=policy.max_hogs * 2) 
                    
                    candidate_hogs = []
                    for h in hogs:
                        decision = self.immunity.is_immune(h.pid)
                        if decision.immune:
                            logger.info(f"PROTECTED: PID {h.pid} ({decision.reason})")
                        else:
                            candidate_hogs.append(h)
                            if len(candidate_hogs) == policy.max_hogs: break

                    allocs = allocate(policy.cpu_quota_pct, policy.memory_headroom_multiplier, candidate_hogs)
                    for a in allocs:
                        spec = ThrottleSpec(
                            mode=policy.mode, cpu_quota_pct=a.cpu_quota_pct,
                            cpu_weight=a.cpu_weight, memory_limit_bytes=a.memory_limit_bytes
                        )
                        await self.actuator.apply_throttle(a.pid, spec)
                        new_throttled.add(a.pid)
                        if a.pid not in self._throttled_pids:
                            logger.info(f"ENFORCING: PID {a.pid} clamped.")

                # Gradual release for PIDs no longer throttled
                for pid in self._throttled_pids - new_throttled:
                    await self._gradual_release(pid)
                    self.immunity.slice_immunity.invalidate(pid)
                    logger.info(f"RELEASED: PID {pid}")
                self._throttled_pids = new_throttled

                # Broadcast telemetry
                self._broadcast_telemetry(sample, score, level, new_throttled)

            except Exception as e:
                logger.error(f"Error: {e}")

            elapsed = time.time() - tick
            await asyncio.sleep(max(0, 1.0 - elapsed))

    async def _gradual_release(self, pid: int) -> None:
            """Ramp CPUWeight from current -> original over 5 seconds via systemd DBus."""
            try:
                unit_name = await self.actuator._get_unit_name_from_pid(pid)
                if not unit_name:
                    await self.actuator.release_throttle(pid)
                    return

                original_weight = self.actuator._original_weights.get(unit_name, 100)
                current_weight = await self.actuator._get_current_cpu_weight(unit_name)
                if current_weight is None or current_weight == original_weight:
                    await self.actuator.release_throttle(pid)
                    return

                steps = 5
                for i in range(1, steps + 1):
                    ramp_weight = current_weight + (original_weight - current_weight) * i // steps
                    await self.actuator._set_cpu_weight(unit_name, ramp_weight)
                    await asyncio.sleep(1.0)

                # Ensure exact final value
                await self.actuator._set_cpu_weight(unit_name, original_weight)
                self.actuator._pid_cooldowns.pop(pid, None)
                self.actuator._original_weights.pop(unit_name, None)

            except Exception as e:
                logger.error(f"Gradual release failed for PID {pid}: {e}")
                await self.actuator.release_throttle(pid)

    def _broadcast_telemetry(self, sample, score, level, new_throttled):
        try:
            snapshot = TelemetrySnapshot(
                timestamp=time.time(),
                level=level.name,  # Convert enum to string name
                score=score.combined,
                cpu_pct=sample.cpu_pct,
                mem_pct=sample.mem_pct,
                throttled_pids=list(self._throttled_pids),
                immune_pids=[], 
            )
            if self.telemetry_bridge:
                logger.debug(f"Broadcasting telemetry: clients={len(self.telemetry_bridge._clients) if hasattr(self.telemetry_bridge, '_clients') else 'unknown'}")
                self.telemetry_bridge.broadcast(snapshot)
        except Exception as e:
            logger.error(f"Telemetry broadcast failed: {e}")
