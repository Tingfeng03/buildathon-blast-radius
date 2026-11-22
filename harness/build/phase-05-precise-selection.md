# Phase 05 · Narrow source and mixed-file selections

Target less than 150 seconds including selector CPU and zero misses. Only an organizer run can confirm the submitted score. On the 30-patch sample, the current selector costs 565.979 simulated seconds. Its schedules attain the per-selection lower bound. Twelve full-suite selections account for 441.804 seconds.

Use the pinned Python source, the existing parent and optimizer traces, and collect the missing executor process-pool coverage. Resolve supported source and fixture files independently and union their readers. Treat source edits whose effects cannot be attributed conservatively. Generate any new evidence without reading patches or labels. Score the default entry point on the organizer sample and the independently labeled import, setting, worker, and insertion patches. Compare against Phase 03 and the four-worker reference. Require zero observed misses on both datasets and a lower sample total before recommending a candidate.

Run focused regression tests with `python -B -m unittest discover -s tests -v`. Run `python -B harness/run_sample.py` and replay the four validation patches under the same Linux AMD64 runtime limits. Record simulated cost, misses and measured CPU separately in the build log.
