import asyncio
import logging
import time

from src.sentry_v2.metrics.sampler import MetricsSampler
from src.sentry_v2.scanner.proc_scanner import ProcScanner
from src.sentry_v2.policy.scoring import compute_stress
from src.sentry_v2.policy.state_machine import StateMachine
from src.sentry_v2.policy.fair_share import allocate
from src.sentry_v2.actuator.factory import create_actuator
from src.sentry_v2.actuator.protocol import ThrottleSpec
from src.sentry_v2.config import SentryConfig

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sentry.control")

class ControlLoop:
    def __init__(self, config_path: str = "sentry-v2.yaml"):
        self.config = SentryConfig.load(config_path)
        self.sampler = MetricsSampler()
        # Initialize scanner with the absolute max hogs we might ever need (Critical state = 5)
        self.scanner = ProcScanner(max_hogs=5)
        self.state_machine = StateMachine(self.config.thresholds)
        self.actuator = None
        self._throttled_pids = set()

    async def run(self):
        self.actuator = await create_actuator()
        logger.info(f"Control loop started. Actuator: {type(self.actuator).__name__}")

        while True:
            start_time = time.time()
            
            try:
                # 1. Sample OS Telemetry
                sample = await self.sampler.sample()
                
                # 2. Compute Stress Score
                score = compute_stress(sample, self.config.thresholds)
                logger.info(f"HEARTBEAT: Score {score.combined}/120 (CPU: {sample.cpu_pct}%, RAM: {sample.mem_pct}%)")
                
                # 3. Evaluate State Machine
                level, transitioned = self.state_machine.step(score)
                policy = self.state_machine.get_policy()
                
                if transitioned:
                    logger.info(f"State Transition -> {level.name} | Score: {score.combined}/120")

                new_throttled_pids = set()

                # 4. Act (If policy dictates we need to throttle hogs)
                if policy.max_hogs > 0:
                    self.scanner.max_hogs = policy.max_hogs
                    hogs = await self.scanner.get_top_hogs()
                    allocations = allocate(policy.cpu_quota_pct, self.config.memory.value, hogs)
                    
                    for alloc in allocations:
                        spec = ThrottleSpec(
                            cpu_quota_pct=alloc.cpu_quota_pct, 
                            memory_limit_bytes=alloc.memory_limit_bytes
                        )
                        await self.actuator.apply_throttle(alloc.pid, spec)
                        new_throttled_pids.add(alloc.pid)
                        
                        # Log enforcement if it's a newly throttled PID
                        if alloc.pid not in self._throttled_pids:
                            logger.info(f"ENFORCING: PID {alloc.pid} clamped to {spec.cpu_quota_pct}% CPU")

                # 5. Cleanup (Release PIDs that are no longer targeted)
                for pid in self._throttled_pids - new_throttled_pids:
                    await self.actuator.release_throttle(pid)
                    logger.info(f"RELEASED: PID {pid} restored to full resources")
                
                self._throttled_pids = new_throttled_pids

            except Exception as e:
                logger.error(f"Control loop encountered an error: {e}")

            # 6. Sleep to precisely maintain the 1Hz (1.0s) tick rate
            elapsed = time.time() - start_time
            sleep_time = max(0, 1.0 - elapsed)
            await asyncio.sleep(sleep_time)
