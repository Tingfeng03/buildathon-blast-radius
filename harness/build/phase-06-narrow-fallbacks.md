# Phase 06 · Narrow costly fallbacks

The organizer reported 505.0 seconds including CPU, with zero misses. The target remains under 150 seconds with zero misses on the organizer batch. The organizer provides aggregate scores, so local comparisons need to measure fallback cost on more than the public sample. Two of the four independent validation patches still use the full suite, at 36.817 seconds each.

## Approved scope

- Use Phase 05 as the baseline. Design and freeze independent patches for structural changes that can fall through its selector, including nested statement changes, class or module configuration, and import-affecting edits. Use the pinned suite to obtain labels. Reuse the four existing independent patches.
- Evaluate whether verified structural edits can use the enclosing callable's observed callers or a narrower set supported by measured class use and module loading. Cover import-time execution, worker processes, and affected test files when the changed module fails to import. Keep full-suite fallback for cases with incomplete dependency evidence.
- Compare scheduled milliseconds by reason, missed commits, and total selector CPU. Measure the candidate under the existing Linux AMD64 container restrictions. Use the organizer sample for regression checking and report the four-worker reference.

## Verification

Run `python -B -m unittest discover -s tests -v`, `python -B harness/run_sample.py`, and the three-run smoke benchmark in `harness/benchmark_phase05.py`. Run `python -B harness/benchmark_phase06.py` to compare the pinned Phase 5 revision with the frozen candidate across the public sample, previous independent validation, new development patches, and the holdout. Require zero observed misses, no sample simulated cost regression, and a net cost improvement on the independent structural edits. Report the failing-set scheduling bounds. Only an organizer run can verify the competition target.
