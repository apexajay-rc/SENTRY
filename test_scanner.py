import asyncio
import time
from src.sentry_v2.scanner.proc_scanner import ProcScanner

async def run_benchmark():
    print("--- ASYNC /PROC SCANNER BENCHMARK ---\n")
    scanner = ProcScanner(max_hogs=5)
    
    print("Initiating full process tree sweep...")
    start_time = time.time()
    
    top_hogs = await scanner.get_top_hogs()
    
    elapsed = (time.time() - start_time) * 1000  # Convert to ms
    
    print(f"\nSweep completed in {elapsed:.2f} ms")
    print(f"Top {len(top_hogs)} CPU Hogs Discovered:")
    for rank, hog in enumerate(top_hogs, 1):
        mb = hog.rss_bytes / (1024 * 1024)
        print(f"  {rank}. PID: {hog.pid:<8} | Raw CPU Ticks: {hog.cpu_pct:<10} | Memory: {mb:.1f} MB")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
