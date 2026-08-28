from src.sentry_v2.config import SentryConfig

def test_dynamic_loading():
    print("--- INITIATING CONFIGURATION BENCHMARK ---")
    
    # 1. Load the configuration
    config = SentryConfig.load("sentry-v2.yaml")
    
    # 2. Output the mathematical constraints
    print(f"CRITICAL Threshold: {config.thresholds.critical} (Type: {type(config.thresholds.critical).__name__})")
    print(f"Memory Multiplier:  {config.memory.value} (Type: {type(config.memory.value).__name__})")
    print(f"Immune Slices:      {config.immunity.immune_slices}")
    
    # 3. Prove Immutability (This should intentionally crash)
    try:
        print("\nAttempting to inject bias at runtime (Modifying CRITICAL to 10)...")
        config.thresholds.critical = 10
    except Exception as e:
        print(f"SUCCESS: System rejected runtime tampering -> {type(e).__name__}: {e}")

if __name__ == "__main__":
    test_dynamic_loading()
