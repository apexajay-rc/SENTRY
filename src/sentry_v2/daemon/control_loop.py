import time
import asyncio
import logging
import os
import signal
from pathlib import Path

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

    async def initialize(self):
        self.actuator = create_actuator()
        await self.immunity.initialize()
        
        # Initialize telemetry bridge
        self.telemetry_bridge = TelemetryBridge()
        await self.telemetry_bridge.start()
        
        loop = asyncio.get_event_loop()
        try: loop.add_signal_handler(signal.SIGHUP, lambda: setattr(self, '_reload', True))
        except NotImplementedError: pass # Windows support

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
        """Ramp quota from current -> 100% over 5 seconds."""
        try:
            pid_cgroup = self.actuator.sentry_root / str(pid)
            cpu_max_path = pid_cgroup / "cpu.max"
            if not cpu_max_path.exists():
                await self.actuator.release_throttle(pid)
                return
            
            with open(cpu_max_path) as f:
                current = f.read().strip()
            if current == "max 100000":
                return
            current_quota = int(current.split()[0])
            
            steps = 5
            for i in range(1, steps + 1):
                ramp_quota = current_quota + (100000 - current_quota) * i // 5
                with open(cpu_max_path, 'w') as f:
                    f.write(f"{ramp_quota} 100000")
                await asyncio.sleep(1.0)
        except Exception:
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
