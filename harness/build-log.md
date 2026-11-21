# Build log

## Phase 01 — Fixture selection and runnable baseline

Implemented the root container, deterministic scheduler, optimizer fixture reader map, conservative fallback, and local scoring runner.

- `python -m unittest discover -s tests -v` — 3 focused tests passed.
- `python harness/run_sample.py` — scorer accepted all 30 results, 827.874 simulated seconds, zero misses. Eight patches used fixture selection.
- `python harness/run_sample.py --all-tests` — scorer accepted all 30 results, 1104.510 simulated seconds, zero misses.
- Map regeneration in the pinned analysis container — 1620 passed, one skipped, 25440 subtests passed in 177.32 seconds. The generated map matched the shipped map exactly, including 24 fixture paths.
- Selector CPU was not measured by the local scorer. Fixture reads are observed evidence and may miss dependencies under different execution conditions.

The first all-tests invocation failed because Docker treated the argument as an executable. The runner was corrected and the successful rerun is reported above.
