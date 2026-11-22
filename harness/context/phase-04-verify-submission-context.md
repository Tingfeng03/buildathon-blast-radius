# Phase 04 context

The verified candidate is commit `b3481b4e2ef2c05e588c45a314349526fde4406a`. The verification tooling lives outside the candidate image and the checks do not change its selector, maps, or Dockerfile.

For a walkthrough, start at `verify()` in `harness/verify_phase04.py`. It checks out the candidate, calls `cold_build()` and `image_metadata()`, then uses `replay()` and `score_result()` to check the image's schedules and resource limits. `stress_inputs()` creates local batches from known patches, with labels kept on the host. The measurements establish local headroom and schedule parity for this revision.

The configured GitHub remote serves the commit with credentials. Anonymous API and Git checks did not reach it. Once the user makes this repository accessible or supplies a public mirror, verify the exact SHA anonymously again. The same tested SHA can be submitted without rebuilding locally solely for a visibility change.
