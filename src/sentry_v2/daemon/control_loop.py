import asyncio
import logging
import time
import os

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
        self.scanner = ProcScanner(sampler=self.sampler)
        self.state_machine = StateMachine(self.config.thresholds)
        self.actuator = None
        self._throttled_pids = set()
        self.num_cores = os.cpu_count() or 1  # MISSING ATTR FIX

    async def run(self):
        self.actuator = await create_actuator()
        logger.info(f"Control loop started. Actuator: {type(self.actuator).__name__} | Cores: {self.num_cores}")
        
        await self.sampler.sample()
        await asyncio.sleep(1.0)

        while True:
            start_time = time.time()
            try:
                sample = await self.sampler.sample()
                score = compute_stress(sample, self.config.thresholds)
                level, transitioned = self.state_machine.step(score)
                policy = self.state_machine.get_policy()
                
                if transitioned:
                    logger.info(f"State Transition -> {level.name} | Mode: {policy.mode} | Score: {score.combined}/120")

                new_throttled_pids = set()
                if policy.max_hogs > 0:
                    # STATE MUTATION FIX: Pass dynamically
                    hogs = await self.scanner.get_top_hogs(max_hogs=policy.max_hogs)
                    
                    allocations = allocate(policy.cpu_quota_pct, policy.memory_headroom_multiplier, hogs)
                    
                    for alloc in allocations:
                        spec = ThrottleSpec(
                            mode=policy.mode,
                            cpu_quota_pct=alloc.cpu_quota_pct, 
                            cpu_weight=alloc.cpu_weight,
                            memory_limit_bytes=alloc.memory_limit_bytes
                        )
                        await self.actuator.apply_throttle(alloc.pid, spec)
                        new_throttled_pids.add(alloc.pid)
                        
                        if alloc.pid not in self._throttled_pids:
                            logger.info(f"ENFORCING: PID {alloc.pid} | Mode: {spec.mode} | Quota: {spec.cpu_quota_pct}% | Weight: {spec.cpu_weight}")

                for pid in self._throttled_pids - new_throttled_pids:
                    await self.actuator.release_throttle(pid)
                    logger.info(f"RELEASED: PID {pid} restored to full resources")
                
                self._throttled_pids = new_throttled_pids

            except Exception as e:
                logger.error(f"Control loop error: {e}")

            elapsed = time.time() - start_time
            await asyncio.sleep(max(0, 1.0 - elapsed))
