# Phase 08 · Measure the cost of current selections

The organizer scored Phase 7 at 462.5 s with zero misses. It saved 7.609 simulated seconds on the organizer batch and 75.999 s across the existing 16 independent patches. The difference points to a need for broader evidence about where the selector spends time.

- Freeze 12 synthetic, independently applied patches chosen by file purpose before inspecting their schedules or outcomes. Include test edits, nested and nonnested fixtures, dialect settings, library code, project metadata and documentation, and a mixed patch. The strata give breadth for diagnosis. Their proportions are a design choice.
- Check every frozen diff against the pinned tree. Use Linux AMD64, the locked baseline dependencies, and integration tests to label all 1,620 numbered IDs per patch. Audit the labels against raw pytest outcomes, including subtest and collection failures.
- Run the archived Phase 7 image three times on the diagnostic batch and public sample. Sum the lower bounds for schedules of just the failing tests, the achieved costs of such schedules, and the cost above the lower bound. Attribute cost by patch category and selector decision. Report scheduled cost, missed commits, and median CPU separately.
- Measure a benchmark-only probe for widening the file evidence. It tries base fixture observations or the catalogue entries from a changed test file when Phase 7 would select the entire suite. Include both simulated savings and failures missed in the comparison. The probe is an experiment whose assumptions must be tested before applying it to the submission.

Prepare and label with `tools/label_phase08.py`. Compare with `python -B harness/benchmark_phase08.py`. Completion requires a full audited diagnostic matrix, paired Linux measurements for both batches, and a recommendation grounded in the measured cost and misses.
