# Phase 02 · Investigate source dependencies

Compare Phase 01 against precomputed dependency evidence on the organizer sample and four validation changes. The submission image and selector stay outside this investigation.

## Frozen comparison rules

Use the Phase 01 scheduler and fixture selection in every operational mode. Limit source selection to in-place edits wholly inside existing function bodies, or to a replacement of a simple class attribute value on its original assignment line. Unknown files, imports or declarations touched by an edit, ambiguous insertions, missing evidence, and unknown test IDs use the full suite. A mixed fixture and source patch also uses the full suite.

| Mode | Evidence |
| --- | --- |
| `phase01` | Existing Phase 01 default behavior |
| `parent` | Union of parent pytest observations anywhere inside each edited function body |
| `worker` | Add worker observations attributed to the submitting test |
| `settings` | Add observations of static reads of a changed class attribute by name |
| `imports` | Add numbered tests in files with a static import path to the edited source file, where the preceding mode already has enough evidence to narrow |

The original line and file probes are diagnostic comparisons. Retain worker results by child PID and verify the exact pytest ID for `test_eliminate_ctes` before using the merged map. Report the exact failing IDs recovered on the organizer's `eliminate_joins.py` change when only worker evidence is enabled.

The four validation changes are specified in `tools/phase02/validation.py`. Define rules and changes before examining their outcomes. Check the unchanged suite and account for every numbered test on each patched run. An unresolved outcome makes the patch inconclusive. Never infer a pass from absent evidence.

## Acceptance

Run focused checks and three fresh Linux AMD64 container runs per mode and dataset under the starter limits. Apply organizer scoring to each result and add selector CPU before computing the median and rounding. Report map size and collection costs separately. A candidate must narrow a source change, miss zero commits on all organizer samples and all four conclusive validations, and improve the rounded median sample score. Choose the simplest candidate that qualifies.
