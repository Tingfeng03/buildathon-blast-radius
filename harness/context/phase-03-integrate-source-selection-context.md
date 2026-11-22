# Phase 03 context

The image carries the verified Phase 02 map and the Phase 01 fixture map. The default entry point tries fixture selection, then source selection, then the cached full-suite schedule. All three routes use the same scheduler. Use `--fixture-only` for Phase 01 behavior and `--all-tests` for the full-suite reference.

`source_map.json.gz` is the 2,598,683-byte combined map produced from the unchanged pinned checkout. Its SHA-256 is `6d9825c25fbb13d1fdd7fcf2a60e49c910c058d4691aaffe66b9d9b6360ccae5`. For provenance and regeneration, follow [the Phase 02 collection commands](../../tools/phase02/README.md). The map builder writes the combined artifact to `.investigation/phase02/workers/imports.json.gz`. Check its digest against the verified artifact before replacing the packaged map. A different artifact needs its own validation.

Start the walkthrough at `selector.main()` and `select_patch()`, then read `source_selector.load_source_map()`, `select_source()`, and `patched_files()`. The integration benchmark in `harness/run_phase02.py` preserves the historical Phase 02 fingerprints by using the archived Phase 01 selector. Its results live in `.investigation/phase03`.

Source selection depends on observed coverage and static dependency evidence from the pinned checkout. The validation set is finite, and uncertain edits still use the full suite.
