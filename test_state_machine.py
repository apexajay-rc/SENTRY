from src.sentry_v2.policy.state_machine import StateMachine, StressLevel
from src.sentry_v2.policy.scoring import StressScore
from src.sentry_v2.config import SentryConfig

def run_test():
    config = SentryConfig.load()
    sm = StateMachine(config.thresholds)
    
    print(f"Initial State: {sm.current.name}")
    
    # 1. Spike score to trigger HIGH (Threshold is 75)
    score_high = StressScore(utilization=60.0, psi_triggered=True, combined=80.0)
    level, changed = sm.step(score_high)
    print(f"Score 80.0 -> State: {level.name} (Transitioned: {changed})")
    
    # 2. Drop score below threshold, test dwell time behavior (needs 30 ticks)
    score_low = StressScore(utilization=20.0, psi_triggered=False, combined=20.0)
    
    print("\nSimulating 29 ticks of low score (should NOT drop down yet due to dwell)...")
    for i in range(29):
        level, changed = sm.step(score_low)
    print(f"After 29 ticks -> State: {level.name}")
    
    print("\nSimulating the 30th tick...")
    level, changed = sm.step(score_low)
    print(f"After 30th tick -> State: {level.name} (Transitioned: {changed})")

if __name__ == "__main__":
    run_test()
