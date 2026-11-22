# Phase 03 · Integrate the verified source selector

Package the combined Phase 02 candidate and its exact map. Use fixture selection first, then source selection, then the cached full-suite schedule. Keep `--fixture-only` for Phase 01 and `--all-tests` for the reference schedule. Missing, corrupt, or incompatible source evidence disables source selection.

Run `python -B -m unittest discover -s tests -v`, `python -B harness/run_sample.py --all-tests`, and `python -B harness/run_phase02.py benchmark-integration`. Verify original map and selector fingerprints, byte-for-byte schedule parity on both datasets, and zero missed commits. Require the packaged selector to improve the median CPU-adjusted score on both datasets under the same container limits. Record the evidence in the build log.
