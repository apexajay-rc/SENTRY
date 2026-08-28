import asyncio
from src.sentry_v2.daemon.control_loop import ControlLoop

if __name__ == "__main__":
    daemon = ControlLoop()
    try:
        asyncio.run(daemon.run())
    except KeyboardInterrupt:
        print("\nSENTRY daemon gracefully shut down.")
