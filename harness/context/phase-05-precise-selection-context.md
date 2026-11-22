# Phase 05 walkthrough

1. `selector.select_patch` splits the diff by file, unions fixture and source readers, and falls back to the full suite if any component is unresolved. The scheduler still uses the runtime catalogue in whole milliseconds.
2. `source_selector.patched_files` verifies source hunks against the pinned text and compiles the result. `precise_selector.source_readers` compares the Python syntax trees. It includes tests observed opening the file as source. Function expression changes use base line coverage, including process pools. Class configuration changes use observed class construction and attribute reads. Changed statements, unsupported import-time operations, or missing evidence use the conservative fallback.
3. `tools/build_precise_map.py` interns sets of pytest IDs and packages the source and observations into `precise_map.json.gz`. `tools/trace_executor.py` extends the earlier optimizer worker tracing to executor pool submissions. `tools/profile_base.py` observes concrete types, operand types for identity comparisons, and source reads in the parent and pool workers. These collectors consume only the pinned base suite. Labels enter the host-side benchmark.

## Regenerating the map

Use the clean pinned checkout, Linux AMD64 analysis image, parent trace and optimizer worker trace described in the [Phase 02 reproduction instructions](../../tools/phase02/README.md). Start the following two collectors with empty output directories. From the project root in PowerShell, run

```powershell
$scratch = Join-Path $PWD '.investigation/phase05'
$jobs = @(@('executor-lines', 'trace_executor.py'), @('base-profile', 'profile_base.py'))
foreach ($job in $jobs) {
    $out = Join-Path $scratch $job[0]
    New-Item -ItemType Directory -Force $out | Out-Null
    if (Get-ChildItem -Force $out) { throw "Expected an empty collector directory at $out" }
    docker run --rm --platform linux/amd64 --network none --cpus 4 --memory 7g --env PYTHONPATH=/src:/tools/phase02 --env SKIP_INTEGRATION=0 --env COVERAGE_CORE=ctrace --env PYTHONDONTWRITEBYTECODE=1 --volume "${PWD}/.investigation/sqlglot:/src:ro" --volume "${PWD}/tools:/tools:ro" --volume "${out}:/evidence" --workdir /src blast-radius-analysis-phase02 python "/tools/$($job[1])"
    if ($LASTEXITCODE) { throw "Base trace failed" }
}
python -B tools/build_precise_map.py
python -B -m unittest discover -s tests -v
python -B harness/run_sample.py
python -B harness/benchmark_phase05.py
```

Each independent validation label must account for the full catalogue before running the benchmark. The pinned probes observe the exercised control flow, object types and file reads. A cached instance, an import-time copy of a setting, or previously unobserved reflection can create a dependency those probes miss.
