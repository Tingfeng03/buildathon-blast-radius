# Phase 04 · Verify the submission candidate

Verify commit `b3481b4e2ef2c05e588c45a314349526fde4406a`. Keep the candidate code and image contents fixed. Run:

```text
python -B harness/verify_phase04.py --revision b3481b4e2ef2c05e588c45a314349526fde4406a
```

The harness uses a clean detached local checkout, runs the committed tests, and builds the pinned Linux AMD64 image without cache under four CPU and 8 GB builder limits. It verifies the packaged map, uses the organizer's limits and scorer, checks sample and validation schedule parity, and runs both 45-patch stress batches. Raw evidence is kept under `.investigation/phase04/`.

Submission readiness also requires anonymous access to the exact commit. Check the configured GitHub repository and commit through the public API, and confirm anonymous Git access. Authenticated visibility alone does not satisfy this gate. Record any blocker in the build log.
