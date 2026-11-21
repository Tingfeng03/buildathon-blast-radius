# Phase 01 · Fixture selection and runnable baseline

**Scope:** Package the full-suite scheduler and select readers of known optimizer SQL fixtures. Fall back to all tests for unsupported or uncertain changes.

**Acceptance:** The organizer's scorer accepts 30 results in each mode. All-tests mode scores 1104.510 simulated seconds with zero misses. Fixture mode targets 827.874 seconds with zero misses. Focused tests cover scheduling, multi-fixture patches, insertions, and fallback behavior.

**Verification:** Run `python -m unittest discover -s tests -v`, `python harness/run_sample.py --all-tests`, and `python harness/run_sample.py`. Record results in the build log.
