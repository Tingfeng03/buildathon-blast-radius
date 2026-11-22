# Phase 09 · Select tests across shared fixtures and imports

Phase 8 saved 200.464 simulated seconds on 12 diagnostic patches with isolated timeout controls. Its file probe also omitted two targeted failures. The TPC-DS executor consumes SQL from class setup, and the DAX tests inherit the validator from another test module.

- Trace the pinned, passing suite for direct fixture reads and reads attributable to pytest scopes. Attribute teardown reads to the broadest scope ending at that point. Exclude unattributed paths from the new fixture map, including opens recorded by child Python processes.
- Use the transitive pinned test import graph for edits to assertion expectations and edits that preserve the AST. Verify the unified diff against the pinned test source. Keep the full suite for collection changes, setup changes, and other unsupported edits.
- Resolve mapped IDs against the runtime catalogue and union selection evidence across files. Use the existing full-suite fallback when any changed file is unresolved.
- Freeze the candidate and six independently applied holdout patches before labeling. Label every numbered test on both Phase 8 witness patches and the holdout on Linux AMD64 with integration enabled, using one suite at a time.

Require zero misses across the public sample, prior independent cohorts, controlled Phase 8 diagnostics, the two fully labeled witnesses, and the fresh holdout. The candidate must explicitly include the two originally missed tests, match or improve the 117.408 s simulated sample, and reduce the median CPU-inclusive score on both the Phase 8 diagnostic batch and the fresh holdout. Verify map regeneration and runtime limits before recommending a candidate. See the [reproduction commands](../context/phase-09-shared-dependencies-context.md).
