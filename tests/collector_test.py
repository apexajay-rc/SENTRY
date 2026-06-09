from pprint import pprint

from core.collectors.psi import collect_psi
from core.collectors.procfs import collect_procfs
from core.collectors.processes import (
    get_top_cpu_processes,
)

print("\n=== PSI ===")
pprint(collect_psi())

print("\n=== SYSTEM ===")
pprint(collect_procfs())

print("\n=== TOP CPU PROCESSES ===")
pprint(get_top_cpu_processes(5))
