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

## Phase 03 · Integrate the verified source selector

The submission image now uses fixture selection, then the verified source rules, then the cached full-suite schedule. It ships only the runtime modules and the two maps. It uses the same output contract and scheduler. Unavailable or incompatible source evidence leaves fixture selection available and causes source edits to use the full suite.

The packaged source map is 2,598,683 bytes. Its SHA-256 is `6d9825c25fbb13d1fdd7fcf2a60e49c910c058d4691aaffe66b9d9b6360ccae5`, matching the frozen Phase 02 artifact. Historical fingerprints still match, including the byte-for-byte archived Phase 01 selector.

| Dataset | Mode | Simulated seconds | Median CPU seconds | Median total (s) | Missed commits |
| --- | --- | ---: | ---: | ---: | ---: |
| Organizer sample | Phase 01 | 827.874 | 0.439 | 828.3 | 0 |
| Organizer sample | Integrated | 565.979 | 0.760 | 566.7 | 0 |
| Independent validation | Phase 01 | 147.268 | 0.455 | 147.7 | 0 |
| Independent validation | Integrated | 137.905 | 0.621 | 138.5 | 0 |

- `python -B -m unittest discover -s tests -v` passed all nine tests.
- `python -B harness/run_phase02.py benchmark-integration` passed the three-run median gates on both datasets. The organizer accepted all 12 scored runs. Integrated schedules matched the frozen combined candidate byte for byte. The `--fixture-only` comparison also reproduced the Phase 01 schedules on both datasets. Per-run results are under `.investigation/phase03`.
- `python -B harness/run_sample.py` scored 565.979 simulated seconds with zero misses. With `--all-tests`, it reproduced 1104.510 simulated seconds with zero misses.
- See the [runtime walkthrough and map provenance](context/phase-03-integrate-source-selection-context.md). Phase 04 will verify readiness from a clean checkout on a final-sized batch.

## Phase 04 · Verify the submission candidate

**Local checks passed. Public access is pending.** The exact candidate is `b3481b4e2ef2c05e588c45a314349526fde4406a`. The authenticated remote advertises this SHA at `refs/heads/main`. The anonymous API request for the repository returned HTTP 404, and anonymous Git requested authentication with credential helpers disabled. Recheck anonymous access after the repository is public or the same commit is available at a public submission URL.

- `python -B harness/verify_phase04.py --revision b3481b4e2ef2c05e588c45a314349526fde4406a` checked a fresh detached checkout. All nine unit tests passed. Tracked content used 3,170,423 bytes and the checkout including Git metadata used 5,903,991 bytes.
- The Linux AMD64 cold build took 13.843 s including builder bootstrap. Docker confirmed the four-CPU and 8 GiB builder limits. The image ID is `sha256:7418671c28f19862a86f08ab5ade71ec50d8d95f13706c6550e245bc63d0aaa8`. The image contained only the expected four files in `/app`, and the source-map digest matched Phase 03.
- All three sample runs, the unwrapped run, and the four-patch validation replay matched the Phase 03 schedules exactly, with zero missed commits. Each sample run cost 565.979 simulated seconds. CPU was 0.700380, 0.710194, and 0.657458 s. The median CPU-adjusted sample score was **566.7 s**.

| Batch | Patches | Maximum observed wall time | Stdout bytes | Peak memory bytes |
| --- | ---: | ---: | ---: | ---: |
| Organizer sample | 30 | 1.500 s | 89,537 | 89,317,376 |
| Independent validation | 4 | 1.203 s | 23,048 | 88,444,928 |
| Mixed stress | 45 | 1.281 s | 98,862 | 88,633,344 |
| Full-suite fallback stress | 45 | 1.109 s | 316,890 | 88,481,792 |

Both stress runs passed the output contract, measured resource checks, and known labels. Every fallback row scheduled all numbered tests. These runs reused known patches to measure headroom. Final accuracy on unseen patches remains unmeasured.

Raw evidence is under `.investigation/phase04/8a07bc04fd/`. The first attempt built the image but failed in the measurement wrapper due to its mount path. The corrected rerun produced the recorded results. Repository and commit access checks are recorded in `.investigation/phase04/public-access.json`.

## Phase 05 · Narrow source and mixed-file selections

The organizer reported 858.131 simulated seconds and zero misses on the submitted build, with 0.58 s median CPU. On the local sample, 12 full-suite runs accounted for 441.804 of Phase 03's 565.979 simulated seconds. The scheduler already attained the cost lower bound for every selected set.

The candidate verifies Python hunks against pinned text and compares syntax trees to distinguish source-only edits from executable changes. It uses base line and class evidence, including both process pools, and unions the resulting readers with those of changed fixtures. Unresolved changes use the full suite.

| Dataset and selector | Simulated seconds | Median CPU seconds | Median total seconds | Missed commits |
| --- | ---: | ---: | ---: | ---: |
| Sample, four-worker all-tests reference | 1104.510 | — | — | 0 |
| Sample, Phase 03 | 565.979 | 0.760 | 566.739 | 0 |
| Sample, Phase 05 | 117.408 | 1.258 | 118.666 | 0 |
| Independent validation, Phase 03 | 137.905 | 0.621 | 138.526 | 0 |
| Independent validation, Phase 05 | 124.542 | 0.840 | 125.382 | 0 |

- `python -B -m unittest discover -s tests -q` passed 16 tests. `git diff --check` passed.
- `python -B harness/run_sample.py` scored the packaged Linux AMD64 default entry point at 117.408 simulated seconds with zero misses. `python -B harness/benchmark_phase05.py` passed three runs per dataset under the competition runtime limits. Sample CPU was 1.257515, 1.371700 and 1.201638 s. Validation CPU was 0.824073, 0.871034 and 0.840481 s. Raw schedules are under `.investigation/phase05/`.
- The initial class profiler collided with sqlglot's `instance` keyword. With a positional-only receiver, the full profile passed 1,620 tests and 25,440 subtests with one skip. An executor task can return before running a sqlglot line. The corrected executor collector verifies task entry separately from line coverage and passed 60 tests and 426 subtests.
- The packaged map is 1,387,677 bytes. `python -B tools/build_precise_map.py` regenerated the same SHA-256 from the saved traces. All three schedules were byte-identical within each dataset. See the [walkthrough and reproduction commands](context/phase-05-precise-selection-context.md). Local acceptance passed.

### Organizer follow-up

The user reported 503.591 simulated seconds on all three runs, with CPU of 1.39, 1.43 and 1.40 seconds and zero missed commits each time. The median total rounds to **505.0 s**, down from **858.7 s** on the previous submission. The Phase 05 implementation is at `b9e503cc8477d4df071ef8fe9902e65c423ba2a7` in the workspace. The organizer feedback gives aggregate cost only, so the patches and selections responsible for the remaining cost are unknown.

Rechecking the saved Phase 05 schedules against the maximum of the longest test and the average worker load, plus worker overhead, gives zero scheduling headroom for the selected tests on either labeled batch. On independent validation, the import change and shared-setting change each schedule the full suite for 36.817 seconds. Their labeled failing sets have lower bounds of 12.896 and 6.282 seconds respectively. These two cases provide a local way to measure the cost of the fallback. The two most expensive sample schedules already attain the lower bounds of their failing sets.

## Phase 06 · Narrow costly fallbacks

Phase 6 passed local acceptance. Structural edits to functions with unchanged declarations can use observed callers. Supported configuration edits use class evidence or module dependencies. Import-sensitive changes in mapped dialect modules use the pinned import graph and covered uses. An attribution gap still selects the full suite. Code review found that a cached lazy package attribute may bypass the module trace. The final map adds those static references, and the candidate was frozen before the holdout labels were opened for scoring.

| Batch | Phase 5 simulated s | Phase 6 simulated s | Median CPU s, Phase 5 → 6 | Median total s, Phase 5 → 6 | Failing-set lower bound s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Public sample, 30 patches | 117.408 | 117.408 | 1.641 → 1.711 | 119.049 → 119.119 | 94.351 |
| Previous validation, 4 patches | 124.542 | 91.262 | 1.233 → 0.952 | 125.775 → 92.214 | 68.099 |
| Structural development, 2 patches | 73.634 | 14.529 | 0.804 → 0.869 | 74.438 → 15.398 | 3.129 |
| Structural holdout, 3 patches | 110.451 | 47.014 | 0.896 → 0.838 | 111.347 → 47.852 | 16.958 |

Both images had zero missed commits on every run. Phase 5 used the full suite on seven of the nine independent patches. The candidate resolved all seven. The remaining excess includes the holdout optimizer edit, which costs 25.454 s with enclosing-callable coverage against a 4.232 s lower bound on its failing set.

- `python -B -m unittest discover -s tests -q` passed 20 tests. `git diff --check` passed.
- The pinned Linux AMD64 full suite accounted for all 1,620 numbered tests on each of the five new patches. The development patches had 3 and 0 failures. The holdout patches had 1 nested-edit failure, 1 module-setting failure, and 117 import-related failures.
- `python -B harness/run_sample.py` and its `--all-tests` mode gave 117.408 s and 1104.510 s respectively, with zero misses. The existing three-run smoke benchmark passed on both the public sample and previous validation while Phase 6 was being developed.
- `python -B harness/benchmark_phase06.py --freeze` checked the runtime fingerprints. `python -B harness/benchmark_phase06.py` rebuilt both Linux images, audited label evidence, and passed all 24 scored runs. Schedules matched across the three repeats in each comparison and agreed with host diagnostics. One Phase 6 sample run used 3.276 CPU seconds, while the other two used 1.711 and 1.433.
- `python -B tools/build_precise_map.py` regenerated the final 1,395,190-byte map with SHA-256 `b0454e196c115064baad933fe2ccb144cc280fe85f8854634ec741dea4152143`. See the [walkthrough and reproduction commands](context/phase-06-narrow-fallbacks-context.md).

The organizer reported 468.777 simulated seconds and zero missed commits on each run, with CPU times of 1.92, 1.96 and 1.89 s. The median score was **470.7 s** at revision `5a6187bc9dd26f830988d62c6b72994317aab6ec`. That was 34.3 s below Phase 5. Reaching a score under 150 s still requires more than 320.7 s in savings.

## Phase 07 · Reduce the cost of broad selections

The candidate uses statement coverage for bounded guards around existing statements, attributed membership checks for removals from local sets, and pinned import or callable evidence for selected definition edits. The runtime catalogue can explicitly mark a mapped ID as skipped. The scheduler continues to price the selected tests using the catalogue.

- The pinned suite accounted for all 1,620 numbered IDs on each of four new development cases. The Phase 6 and Phase 7 schedules both cover every observed failure. Scheduled time fell from 109.962 s to 70.432 s. The guarded optimizer statement accounts for 23.441 s of that reduction, the optimizer default for 11.363 s, and the local set removal for 4.726 s. The added private helper still costs 36.817 s.
- The 24 unit tests passed. The packaged sample scored 117.408 simulated seconds, and the four-worker all-tests run scored 1104.510 s. Both had zero misses. The map regenerated byte-for-byte with SHA-256 `e1e526574a98b07586322596ca87e967ba75169fd04bce5a061b2caad6b15ae1`.
- The runtime and patch manifest were frozen before reading holdout results. See the [walkthrough and reproduction commands](context/phase-07-costly-selections-context.md).

| Dataset | Patches | Simulated s, Phase 6 → 7 | Median CPU s, Phase 6 → 7 | Failing-set lower bound s |
| --- | ---: | ---: | ---: | ---: |
| Public sample | 30 | 117.408 → 117.408 | 1.267 → 1.314 | 94.351 |
| Previous validation | 4 | 91.262 → 91.262 | 1.104 → 1.181 | 68.099 |
| Phase 6 development | 2 | 14.529 → 14.529 | 0.803 → 0.883 | 3.129 |
| Phase 6 holdout | 3 | 47.014 → 42.288 | 0.857 → 0.967 | 16.958 |
| Phase 7 development | 4 | 109.962 → 70.432 | 0.787 → 0.797 | 6.651 |
| Phase 7 holdout | 3 | 86.534 → 54.791 | 0.876 → 0.844 | 6.760 |

`python -B harness/benchmark_phase07.py` passed all 36 Linux AMD64 runs, with zero missed commits and consistent schedules. The fresh holdout accounts for all 1,620 numbered tests per patch. Its BigQuery default edit broke 18 tests, all of which remained selected after its cost fell from 36.817 s to 14.437 s. The two other holdout edits broke zero tests and together cost 40.354 s under Phase 7.

The 16 independent patches saved 75.999 simulated seconds. Summing each independent batch's median CPU-adjusted score gives 353.728 s for Phase 6 and 277.975 s for Phase 7. The Phase 7 sample median with CPU was 118.722 s. Phase 7 passed local acceptance. The organizer score is pending.

The organizer subsequently scored revision `0f63813b0a47409b31f91fd5961d806a99c848c4` at **462.5 s**. All three runs scheduled 461.168 simulated seconds with zero misses. CPU was 1.34, 1.33, and 1.69 s. The improvement over Phase 6 was 7.609 simulated seconds.

## Phase 08 · Diagnose selection cost

The frozen 12-patch cohort spans test changes, fixtures, dialect configuration, library source, project files, and a mixed change. All twelve diffs passed `git apply --check` on the pinned checkout. The Linux AMD64 suite produced an outcome for each of the 1,620 numbered tests on every patch. The patches were selected to cover these categories. The results do not estimate the organizer's patch mix.

Eight concurrent runs timed out on the parser stress test at the local 120 s cap. The same test passed on the pinned checkout in 43.94 s and on all eight patched revisions in 47.04–78.27 s in serial rechecks. The benchmark audits both sets of reports and preserves the original suite scores. The table uses the outcomes from the serial rechecks for those eight timeouts.

| Batch | Mode | Simulated s | Median CPU s | Missed commits |
| --- | --- | ---: | ---: | ---: |
| Diagnostic, 12 patches | Phase 7 | 408.310 | 1.387 | 0 |
| Diagnostic, 12 patches | File probe | 207.846 | 0.982 | 0 |
| Public sample, 30 patches | Phase 7 | 117.408 | 1.393 | 0 |
| Public sample, 30 patches | File probe | 117.408 | 1.641 | 0 |

The diagnostic batch can be scheduled for 6.914 s using only its observed failures, attaining the mathematical lower bound. Phase 7 used the full suite on ten patches. Those fallbacks account for 361.256 s of the 401.396 s gap above the lower bound. Nine passing patches together cost 297.859 s under Phase 7. The file probe reduced six full-suite schedules, saving 200.464 s in total.

Two focused regressions exposed gaps in the probe. The TPC-DS executor test passed on the pinned baseline and failed when the nested SQL fixture changed, but the probe omitted it. The fixture is loaded during class setup and consumed later. A DAX test also passed on the baseline and failed when the shared dialect validator changed in another test file. The probe omitted that test as well. Future fixture evidence needs to account for shared setup, and test-file evidence needs to include imported helpers and their dependents.

- `python -B harness/benchmark_phase08.py` passed the input and output checks in all 12 Linux selector runs. Host and Docker schedules agreed. The official sample scorer accepted both images. The four-worker all-tests sample reference is 1104.510 s.
- `python -B -m unittest discover -s tests -q` passed all 24 unit tests. `git diff --check` passed. The changes are confined to the diagnostic harness and its documentation.
- The [Phase 8 walkthrough](context/phase-08-selector-diagnostics-context.md) lists the commands and raw evidence.

## Phase 09 · Select tests across shared fixtures and imports

The selector uses the pinned test import graph for supported assertion changes and fixture reads attributed to pytest scopes. The map covers 30 fixture paths and 59 test modules. The previously omitted TPC-DS executor and DAX tests are both selected. Full-suite labeling of the two witness patches found six failing tests in total, and the candidate selected all six. The six new holdout patches had five failing tests, all selected. All 1,620 numbered tests were accounted for on each of the eight patches, with no timeouts.

| Batch | Phase 7 simulated s | Phase 9 simulated s | Phase 7 median CPU s | Phase 9 median CPU s | Missed commits in either |
| --- | ---: | ---: | ---: | ---: | ---: |
| Public sample | 117.408 | 117.408 | 1.682 | 1.674 | 0 |
| Phase 8 diagnostics, controlled | 408.310 | 227.704 | 1.055 | 1.128 | 0 |
| Phase 9 holdout | 220.902 | 77.550 | 0.999 | 1.392 | 0 |
| Phase 8 witnesses, full-suite labels | 73.634 | 34.680 | 1.124 | 1.294 | 0 |

The five prior independent cohorts retained their Phase 7 simulated costs and zero misses. Each entry uses three restricted Linux AMD64 runs per version. The scorer also accepted the all-tests sample at 1,104.510 s and zero misses. The 45-patch resource replay took 2.969 s of wall time and emitted 5,023 bytes. The pre-log workspace and Git metadata measured 12,334,140 bytes.

- Fixture-only narrowing saved 80.073 s on the Phase 8 diagnostics and 46.177 s on the holdout. Test-import narrowing saved 69.631 s and 62.407 s on test-only patches. The respective mixed patches saved 30.902 s and 34.768 s.
- The original Phase 8 concurrent-suite labels included eight timeouts. Against those labels, Phase 7 has one missed commit and Phase 9 has six, at 708.310 s and 2,027.704 s simulated. Both have zero misses after the separately recorded isolated controls.
- A second pinned-suite trace regenerated the 531,493-byte map byte for byte. The no-cache Docker build, the default image command, and all 26 repository unit tests passed. `git diff --check` reported only the usual line-ending conversion notices.

See the [Phase 9 walkthrough](context/phase-09-shared-dependencies-context.md) for the selector flow, evidence limits, and reproduction commands. The paired diagnostic and holdout gains meet the local performance gates. The organizer score depends on the prevalence of supported changes in its batch.
