# Build log

## Phase 01 — Fixture selection and runnable baseline

Implemented the root container, deterministic scheduler, optimizer fixture reader map, conservative fallback, and local scoring runner.

- `python -m unittest discover -s tests -v` — 3 focused tests passed.
- `python harness/run_sample.py` — scorer accepted all 30 results, 827.874 simulated seconds, zero misses. Eight patches used fixture selection.
- `python harness/run_sample.py --all-tests` — scorer accepted all 30 results, 1104.510 simulated seconds, zero misses.
- Map regeneration in the pinned analysis container — 1620 passed, one skipped, 25440 subtests passed in 177.32 seconds. The generated map matched the shipped map exactly, including 24 fixture paths.
- Selector CPU was not measured by the local scorer. Fixture reads are observed evidence and may miss dependencies under different execution conditions.

The first all-tests invocation failed because Docker treated the argument as an executable. The runner was corrected and the successful rerun is reported above.

## Phase 02 — Investigate source dependencies

Completed the frozen candidate comparison on the organizer sample and four independent validation patches. Recommend the combined candidate for Phase 03. It was the only tested candidate with zero misses on both datasets and a lower CPU-adjusted sample score.

The parent trace was reused from the pinned investigation run (476.48 s). The successful worker run passed 167 optimizer tests and 6,082 subtests in 102.93 s. Six child PIDs exported lines from `eliminate_ctes.py` under the exact `tests/test_optimizer.py::TestOptimizer::test_eliminate_ctes` ID. All 22 optimizer IDs that submitted traced tasks appeared in the worker data. The first in-memory worker export lost attribution, so collection now uses a private SQLite file per worker.

On the organizer's `eliminate_joins.py` patch, worker coverage recovered four omissions from the parent-only line and enclosing-function comparisons: `test_eliminate_joins`, `test_optimize`, `test_tpcds`, and `test_tpch` in `TestOptimizer`. The file comparison recovered `test_tpcds` and `test_tpch`. The remaining omission was `TestExecutor::test_execute_tpcds`; the import graph added it. The original line and file probes reproduced five and three missed commits overall.

| Sample mode | Scheduled seconds | Missed commits | Median including CPU | Evidence map bytes |
| --- | ---: | ---: | ---: | ---: |
| Phase 01 | 827.874 | 0 | 828.4 | 120,815 |
| Parent function | 421.278 | 3 | 1322.0 | 1,470,023 |
| Add worker evidence | 436.974 | 1 | 737.8 | 1,476,071 |
| Add shared settings | 403.019 | 1 | 703.8 | 1,962,373 |
| Add static imports | 565.979 | 0 | 566.8 | 2,598,683 |

The candidate map sizes are compressed and exclude the common Phase 01 fixture map. Offline map construction took 16.48 s. Each scored mode ran three times using the same Linux AMD64 image, limits, and private cgroup CPU measurement. The sample numbers include any miss penalties and the common CPU meter overhead. Run totals, CPU readings, and omitted pytest IDs are in `.investigation/phase02/benchmark-sample.json`. Worker recovery and changes attributable to each signal are in `.investigation/phase02/diagnostics.json`.

Each validation patch accounted for all 1,620 numbered tests. The import error produced 320 failing IDs, the shared-setting change 21, the worker change 3, and the insertion 18. The insertion's count includes a reported timeout in `TestExecutor::test_execute_tpcds`. The pinned baseline passed with zero numbered failures. The import patch failed during test execution on this suite. A separate pinned pytest smoke check verified that the reporter identifies a file that fails to import, an unaffected passing test, and the parent ID of a failed subtest. A focused test verified how the file error is applied to the numbered tests.

| Validation mode | Scheduled seconds | Missed commits | Median including CPU |
| --- | ---: | ---: | ---: |
| Phase 01 | 147.268 | 0 | 148.0 |
| Parent function | 90.851 | 2 | 691.5 |
| Add worker evidence | 93.820 | 2 | 694.4 |
| Add shared settings | 93.820 | 2 | 694.5 |
| Add static imports | 137.905 | 0 | 138.6 |

Initial concurrent pytest runs were killed before all outcomes were recorded. Sequential retries completed the missing files without changing the frozen candidate rules or patches. Before scoring, the harness independently reconciled each case's raw reports against all numbered IDs. The combined candidate narrowed ten additional sample patches and the worker validation patch. Its import signal recovered the remaining join failure on the sample, but expanded the sample shared-setting edit back to the full suite. This experiment did not score a variant that removes shared-setting evidence from the combined candidate.

- Six focused tests passed with `python -B -m unittest discover -s tests -v`.
- The organizer's scorer accepted all 30 container runs across five modes, two datasets, and three repetitions. The validation report is in `.investigation/phase02/benchmark-validation.json`. The acceptance gate selected `imports` in `.investigation/phase02/decision.json`.
- See the [reproduction commands](../tools/phase02/README.md) and [walkthrough](context/phase-02-source-dependencies-context.md).
