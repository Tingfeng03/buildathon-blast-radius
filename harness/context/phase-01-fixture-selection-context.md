# Phase 01 context

The fixture map records test-call opens from the pinned base suite. Fixtures seen outside individual calls are excluded. The map contains 24 optimizer fixture paths and was reproduced using the collector in `tools/collect_fixtures.py`. The reference suite included 1620 passing tests and one skip. The sample contains eight eligible fixture-only patches.

The map cannot prove that all possible dependencies on a fixture were observed. Unsupported patches, missing readers, and catalogue mismatches select the entire suite. Selector CPU remains unmeasured.
