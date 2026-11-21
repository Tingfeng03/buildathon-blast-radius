# Phase 02 context

Source selection here is an offline comparison. The submission selector still uses the Phase 01 fixture map and full-suite fallback. The experimental maps are keyed by pytest ID and built exclusively from the unchanged pinned checkout.

The added worker trace covers `parse_and_optimize()` tasks submitted by `TestOptimizer.check_file()`. It does not cover other child entry points such as `TestExecutor`'s process pool or the dialect lazy-load subprocess. Worker coverage recovered four previously omitted optimizer tests on the organizer's join patch. Static import reachability covered the remaining executor test. Static reachability and attribute-name matching can both select unrelated tests.

Evaluation keeps an unknown outcome distinct from a pass. The labeler accounts against the numbered catalogue and can finish interrupted cases from raw pytest reports. The CPU benchmark runs all modes through the same container entry point and combines the scorer's simulated cost with each run's CPU before taking the median. The meter includes the common wrapper up to its final counter read.

The combined candidate was the only tested mode with zero misses on both datasets. It narrowed 18 sample patches compared with eight in Phase 01, and one of the four independent validation patches. Static imports widened the sample shared-setting case back to the full suite. A combined variant without shared-setting evidence has not been validated. The holdout covers four designed failure modes, so zero observed misses is evidence for the tested scope.

For a walkthrough, start at `harness/run_phase02.py`, then read `trace_workers.py` and `evidence.py` in `tools/phase02`. Follow `candidate.select_source()` to see how edit evidence becomes a test set, then `validation.outcomes()` for failure label accounting.
