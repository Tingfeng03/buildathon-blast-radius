# Blast Radius development roadmap

**Status:** Phases 01 through 03 completed and verified. Phase 04 awaits review. The [project goals](GOALS.md) define the outcomes and constraints for every phase.

## Architectural decisions

| Decision for the proposed build | Reason |
| --- | --- |
| Generate dependency maps during development from the pinned sqlglot environment. Package compact, reproducible maps with the selector. | The instrumented investigation run took 476.5 seconds before export. Precomputation keeps that cost out of evaluation and repeated image builds. |
| Key map entries by pytest ID and resolve them against the runtime catalogue. Use the catalogue's numbers and durations for output. | This preserves the link to the source test and makes each schedule reflect the actual inputs. |
| Keep selection and scheduling independent. Select once per patch, then evaluate up to eight deterministic longest-test-first assignments in whole milliseconds, including worker overhead. Cache the full-suite assignment for reuse across the batch. | Both narrow selections and full-suite fallbacks can use the same scheduler. The best worker count depends on which tests were selected. |
| Start with fixture-reader evidence. Narrow a selection only when every change in the patch is eligible and every reader resolves. Otherwise schedule the full suite. | Both investigation probes caught all eight fixture-only failures. Even the broader source-file probe missed failures on three commits. |

**Phase 02 result.** The combined candidate uses parent and optimizer worker traces, shared-attribute reads, and static import dependencies for supported edits. It was the only tested candidate with zero misses on both datasets. It improved the median CPU-adjusted sample score from 828.4 to 566.8 seconds and the validation score from 148.0 to 138.6 seconds. Phase 03 can evaluate integration of that candidate with its full-suite fallback. See the [build log](harness/build-log.md).

**Phase 03 result.** The packaged selector reproduced the verified candidate schedules. It improved the median CPU-adjusted sample score from 828.3 to 566.7 seconds and the validation score from 147.7 to 138.5 seconds, with zero misses on both datasets. The default image uses the integrated selector, with Phase 01 and the full-suite reference available as comparison modes.

## Independently verifiable phases

| Phase | Deliverable | Exit evidence |
| --- | --- | --- |
| **01 · Fixture selection and runnable baseline** | First wire the verified full-suite scheduler into the submission container. Then select the union of observed readers for in-place edits confined to mapped optimizer SQL fixtures. Keep an all-tests mode and a single local sample runner. | The official scorer accepts both container outputs on all 30 patches. All-tests mode scores **1104.510 s, zero misses**. Default mode scores **827.874 s, zero misses**, narrowing eight patches. Focused checks cover mixed changes, multiple fixtures, missing IDs, and fallback. |
| **02 · Investigate source-change dependencies** | Compare candidate dependency evidence with the phase 01 fallback. Evaluate on the sample and on independently designed patches covering an import failure, a shared setting, a subprocess path, and an insertion. Obtain validation labels by running the pinned tests on those patches. | Reproducible results show missed commits, simulated cost, map size, and collection cost for each candidate. Record which source changes can be narrowed, or retain the phase 01 fallback if the evidence is insufficient. |
| **03 · Integrate and evaluate source selection** | Integrate the approach supported by phase 02 for the supported cases. If phase 02 supports no extension, carry the verified phase 01 selector directly to phase 04. | Compare with phase 01 on the same inputs. A candidate advances when it preserves zero observed misses on the validation sets and improves total cost after accounting for selector CPU. Retain the full-suite fallback for unresolved cases. |
| **04 · Verify the submission candidate** | Build the selected version from a clean checkout and exercise it with the organizer's restrictions, including a final-sized batch for resource testing. | Verify repository size, clean build duration, stdout validity and size, and batch wall time. Record three valid sample runs with simulated cost and measured CPU. Identify the exact candidate revision for the team's submission decision. |

At each phase boundary, use the [development workflow](AGENTS.md) to agree on scope and acceptance checks, record observed evidence, and review the outcome before advancing.
