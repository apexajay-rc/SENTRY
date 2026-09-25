import asyncio
import os
import logging

from src.sentry_v2.daemon.control_loop import ControlLoop
from src.sentry_v2.daemon.systemd import sd_notify

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sentry.main")

async def async_main():
    logger.info(f"SENTRY booted. UID: {os.getuid()}, GID: {os.getgid()}")
    sd_notify("READY=1")
    
    loop = ControlLoop()
    await loop.run()

def main():
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("SENTRY daemon shutting down.")

if __name__ == "__main__":
    main()
