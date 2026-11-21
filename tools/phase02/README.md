# Reproduce the Phase 02 investigation

Use a clean detached checkout of the pinned sqlglot commit at `.investigation/sqlglot`. From the project root, build the analysis image in PowerShell:

```powershell
$base = Get-Content 'blast-radius-sample/Dockerfile' | Where-Object { $_ -like 'FROM *' }
$definition = "$base`nCOPY requirements.lock /tmp/requirements.lock`nRUN python -m pip install --no-cache-dir -r /tmp/requirements.lock coverage==7.17.4`n"
$definition | docker build --platform linux/amd64 -t blast-radius-analysis-phase02 -f - blast-radius-sample
```

Then run these commands from the project root:

```text
python -B harness/run_phase02.py freeze
python -B harness/run_phase02.py collect-parent
python -B harness/run_phase02.py collect
python -B harness/run_phase02.py label
python -B harness/run_phase02.py benchmark
python -B harness/run_phase02.py diagnose
python -B harness/run_phase02.py decision
```

Reuse `.investigation/dependencies.json.gz` from the original investigation when available. The collectors refuse to replace existing raw evidence. The `maps` command rebuilds candidate maps from saved traces. Use `benchmark --dataset sample` or `benchmark --dataset validation` to run one dataset.

If validation is interrupted after a clean baseline, stop any still-running analysis for those cases, then run `python -B harness/run_phase02.py resume-labels`. It reuses observed reports and retries unresolved files sequentially.

The benchmark uses the Phase 01 image for every mode and mounts experiment code and maps read-only. It reads the private Linux cgroup CPU counter after the selector exits. The counter includes the shared measurement wrapper up to that read. The organizer's scorer runs on the host. Raw traces, labels, schedules, and reports live under `.investigation/phase02`.
