# Blast Radius development roadmap

**Status:** Phase 01 completed and verified. Later phases await review. The [project goals](GOALS.md) define the outcomes and constraints for every phase.

## Architectural decisions

| Decision for the proposed build | Reason |
| --- | --- |
| Generate dependency maps during development from the pinned sqlglot environment. Package compact, reproducible maps with the selector. | The instrumented investigation run took 476.5 seconds before export. Precomputation keeps that cost out of evaluation and repeated image builds. |
| Key map entries by pytest ID and resolve them against the runtime catalogue. Use the catalogue's numbers and durations for output. | This preserves the link to the source test and makes each schedule reflect the actual inputs. |
| Keep selection and scheduling independent. Select once per patch, then evaluate up to eight deterministic longest-test-first assignments in whole milliseconds, including worker overhead. Cache the full-suite assignment for reuse across the batch. | Both narrow selections and full-suite fallbacks can use the same scheduler. The best worker count depends on which tests were selected. |
| Start with fixture-reader evidence. Narrow a selection only when every change in the patch is eligible and every reader resolves. Otherwise schedule the full suite. | Both investigation probes caught all eight fixture-only failures. Even the broader source-file probe missed failures on three commits. |

**Open decision for phase 02.** The base trace misses optimizer work in spawned processes and can attribute a shared class setting only to the test that first loaded it. Compare subprocess tracing and analysis of imports or shared-attribute readers before deciding which evidence, if any, justifies narrowing source-code changes. Runtime test execution is permitted and would need to earn back its measured CPU cost.

## Independently verifiable phases

| Phase | Deliverable | Exit evidence |
| --- | --- | --- |
| **01 · Fixture selection and runnable baseline** | First wire the verified full-suite scheduler into the submission container. Then select the union of observed readers for in-place edits confined to mapped optimizer SQL fixtures. Keep an all-tests mode and a single local sample runner. | The official scorer accepts both container outputs on all 30 patches. All-tests mode scores **1104.510 s, zero misses**. Default mode scores **827.874 s, zero misses**, narrowing eight patches. Focused checks cover mixed changes, multiple fixtures, missing IDs, and fallback. |
| **02 · Investigate source-change dependencies** | Compare candidate dependency evidence with the phase 01 fallback. Evaluate on the sample and on independently designed patches covering an import failure, a shared setting, a subprocess path, and an insertion. Obtain validation labels by running the pinned tests on those patches. | Reproducible results show missed commits, simulated cost, map size, and collection cost for each candidate. Record which source changes can be narrowed, or retain the phase 01 fallback if the evidence is insufficient. |
| **03 · Integrate and evaluate source selection** | Integrate the approach supported by phase 02 for the supported cases. If phase 02 supports no extension, carry the verified phase 01 selector directly to phase 04. | Compare with phase 01 on the same inputs. A candidate advances when it preserves zero observed misses on the validation sets and improves total cost after accounting for selector CPU. Retain the full-suite fallback for unresolved cases. |
| **04 · Verify the submission candidate** | Build the selected version from a clean checkout and exercise it with the organizer's restrictions, including a final-sized batch for resource testing. | Verify repository size, clean build duration, stdout validity and size, and batch wall time. Record three valid sample runs with simulated cost and measured CPU. Identify the exact candidate revision for the team's submission decision. |

At each phase boundary, use the [development workflow](AGENTS.md) to agree on scope and acceptance checks, record observed evidence, and review the outcome before advancing.
