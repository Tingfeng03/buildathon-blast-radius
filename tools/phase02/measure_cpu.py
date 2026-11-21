"""Container entry point shared by the baseline and the candidate replays."""

import subprocess
import sys
from pathlib import Path

result = subprocess.run(sys.argv[1:])
# This private Linux cgroup includes the selector and all its descendants.
# Read it after the selector exits. Only this wrapper's final print and exit follow.
root = Path("/sys/fs/cgroup")
if (root / "cpu.stat").is_file():
    counters = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
    cpu_us = int(counters["usage_usec"])
else:
    cpuacct, = root.glob("*/cpuacct.usage")
    cpu_us = int(cpuacct.read_text()) // 1000
print(f"PHASE02_CPU_US={cpu_us}", file=sys.stderr, flush=True)
sys.exit(result.returncode)
