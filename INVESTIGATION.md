# Blast Radius investigation

This document records what we measured before choosing a selector design. All scores below are for the 30 local sample patches and exclude selector CPU time.

## Baselines

| Run | Simulated seconds | Missed commits |
| --- | ---: | ---: |
| Unmodified starter, all tests on 3 workers | 1210.470 | 0 |
| All tests on 4 workers, using longest test first | 1104.510 | 0 |
| Changed base lines and fixture readers | 1589.306 | 5 |
| Changed source files and fixture readers | 1137.331 | 3 |
| Only the labeled failing tests, benchmark using sample answers | 94.351 | 0 |

The starter ran in Docker under the Makefile flags via PowerShell. The kit's `score.py` validated the starter, four-worker, and two coverage probe outputs. The brief advertises 1614.1 seconds, which differs from the result on the supplied sample. The available materials do not identify the batch or CPU measurements behind the advertised figure.

The full suite has 103.047 recorded test seconds. Its longest test, `TestParser::test_max_nodes`, takes 28.817 seconds. The second longest, `TestExecutor::test_execute_tpcds`, takes 21.454 seconds. With four workers the full-suite loads were 28.817, 24.744, 24.743, and 24.743 seconds. At four workers the schedule attains the lower bound set by the longest test. With fewer workers the total load divided by the number of workers gives a higher cost after overhead. With more workers the longest test stays on the critical path and overhead rises.

For a given selection and worker count, the busiest worker must take at least as long as the longest test or the average worker load, whichever is greater. Add 2 seconds per worker to get a lower bound on the cost. Trying one through eight workers with longest-test-first scheduling attained this bound at the best worker count on each sample's known failing set. The minimum simulated score with zero misses is therefore 94.351 seconds on this sample, before selector CPU. The sample answers are used only to calculate this benchmark and evaluate the experiments.

## Inputs and test structure

- The sample catalogue contains **1,620 selectable pytest IDs across 58 files**, plus one skipped test. Use pytest IDs to connect precomputed evidence to the runtime catalogue, and use the catalogue's numbers and recorded durations for output.
- All 30 sample patches passed `git apply --check` against `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. The sample includes 16 code, 8 fixture, 3 multi-file, and 3 comment patches. Twelve break nothing. The median patch breaks one test, the largest breaks 37, and there are 73 labeled failures across the batch. Each fixture-only patch breaks one test. The three comment samples have zero failures, and the rules explicitly allow comment changes that fail tests.
- In `tests/dialects/test_dialect.py`, `Validator.validate_all` can parse with one dialect and generate SQL for others in a single test. A dialect change can therefore affect a test in another dialect's test file.
- In `tests/test_optimizer.py`, `check_file` reads SQL and expected output from fixtures via `tests/helpers.py`. It sends parsing and optimization to a spawned `ProcessPoolExecutor` and reports failures as subtests of the parent pytest test. A trace in the pytest process can see the fixture read and SQL generation in the parent. It leaves out the Python lines executed by worker processes.
- `sqlglot/dialects/dialect.py` registers dialects and loads them dynamically. Import and class setup can run before any specific test starts. Code executed once during import or class setup can affect later tests that never execute those same lines.

## Coverage experiment

The unchanged suite passed **1,620 tests and 25,440 subtests**, with one skip matching the catalogue. The container used Python 3.13.18, SQLite 3.46.1, and pytest 9.2.0. The instrumented test run took **476.5 seconds of wall time** on this machine, before map export. That makes development-time collection worth considering given the ten-minute clean build budget.

The collector labels Python lines with the pytest ID active during setup, test execution, and teardown. It also records fixture file opens by test ID. The artifact covers **52,229 lines in 183 sqlglot files** and **62 fixture paths**, using 11,448,251 bytes as JSON or 548,895 bytes gzipped. The probe ran in the parent process. It also collected 16,294 source lines reached only outside a test's context, and five selectable tests had no sqlglot lines attributed to them. A complete catalogue match therefore does not imply complete attribution.

| Probe | Selection rule | Median tests selected | Cost before penalties | Failing tests omitted |
| --- | --- | ---: | ---: | ---: |
| Changed base lines | Tests that executed a removed or replaced Python line, plus readers of edited fixtures | 1 | 89.306 s | 23 of 73 |
| Changed source files | Tests that executed any line in an edited Python file, plus readers of edited fixtures | 27.5 | 237.331 s | 6 of 73 |

Both probes try one through eight workers per selection and choose the lowest simulated cost. Both caught all eight fixture-only failures. Neither probe attributes import or other shared state to later readers, traces optimizer subprocesses, or handles new Python lines through their enclosing scope. The three insertion-only sample patches are comment additions, so the sample gives no evidence about behavior-changing insertions.

Two observed misses show why broadening from line to file coverage has limits:

- An edit to `TSQL.WEEK_OFFSET` was attributed to a BigQuery test that loaded the dialect. The optimizer's `test_simplify` failed because the simplifier reads that class attribute later. Both probes missed it.
- A change to `optimizer/eliminate_joins.py` missed five of eight failures with the line probe and three with the file probe. Some omitted optimizer tests use the spawned worker pool. This is consistent with the parent-only trace gap, although the experiment did not trace the patched workers to isolate each failure.

File coverage also produces large selections for shared code. In the base run, 1,586 numbered tests executed at least one line in `sqlglot/dialects/dialect.py`, and 1,519 exercised `sqlglot/parser.py`.

## Implications for the build plan

- Keep the four-worker full-suite result as the local zero-miss reference. Choose the worker count from the actual selection and duration catalogue at runtime. At sample durations, a single miss costs more than eight full-suite runs.
- Fixture reads are a promising direct relationship. For source changes, use coverage as one input and investigate how to handle shared attributes, imports, and spawned processes. Define conservative fallbacks for changes the map cannot explain.
- Use the local scorer to compare selection variants against the four-worker reference. Track missed commits, simulated cost before penalties, and eventually selector CPU. Evaluate additional independently designed patches to test cases sparse or absent in the sample, such as new code and import failures.

## Reproducing the investigation

- Build and run the unchanged starter using `blast-radius-sample/Makefile` and score the output with `score.py`. The PowerShell run used Linux AMD64, two cores, 4 GB memory, no network, read-only root, a 64 MB temporary filesystem, and user `65534:65534`. Only the patches and test catalogue were mounted.
- The local `.investigation/sqlglot` checkout is detached at the pinned commit. Keep it and the local investigation outputs out of the submission. The checkout alone exceeds the 20 MB repository limit.
- The analysis image uses the same pinned base image as the starter, the supplied `requirements.lock`, and Coverage.py 7.17.4. The coverage probe sets `SKIP_INTEGRATION=0`, `PYTHONPATH=/src`, and `COVERAGE_CORE=ctrace`, mounts the unchanged checkout at `/src`, and runs `.investigation/collect_coverage.py` with `.investigation` mounted at `/evidence`. The map comes from the unmodified source and tests. Run `python .investigation/evaluate_coverage.py` to compare selections with labels locally after map generation.
