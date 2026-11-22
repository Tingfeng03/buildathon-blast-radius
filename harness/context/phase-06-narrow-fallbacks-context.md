# Phase 6 walkthrough

1. Start with `source_readers` in `precise_selector.py`. It checks the patch against the pinned file and classifies the altered AST. Ordinary expressions still use precise coverage. Structural edits to an unchanged function declaration can use coverage of the enclosing callable. A callable whose execution has an unattributed context or whose metadata changes still uses the full suite.
2. Read `configuration_readers` and `import_edit` in the same module. An edit between two existing members of a known enum can use observed instances and direct reads of the class. Data configuration edits and import changes in mapped dialect modules use the tests exposed through import dependencies.
3. Read `import_dependents` in `tools/build_precise_map.py`. It projects static imports from each test file through the pinned module graph and adds coverage, observed class use, and dialect registry access. It accounts for cached dialect attributes even when accessing one does not reload the module. Both worker pools contribute coverage. Dynamic loading and shared state can create dependencies outside the unchanged source and base traces.
4. Read `harness/benchmark_phase06.py` for the paired comparison. It checks the frozen inputs, audits pytest events against labels, and verifies that the host explanations produce the same schedules as the Linux entry point.

## Reproduce from the project root

Reuse the pinned checkout, traces and analysis image described in [Phase 5](phase-05-precise-selection-context.md). Prepare the independent validation patches, rebuild the base map, and freeze the runtime before reading the holdout results.

```powershell
python -B tools/label_structural.py prepare .investigation/sqlglot blast-radius-sample/sample .investigation/phase06
python -B tools/build_precise_map.py
python -B harness/benchmark_phase06.py --freeze
docker run --rm --platform linux/amd64 --network none --cpus 4 --memory 8192m --env SKIP_INTEGRATION=0 --env PYTHONDONTWRITEBYTECODE=1 --volume "${PWD}/.investigation/sqlglot:/src:ro" --volume "${PWD}/tools:/tools:ro" --volume "${PWD}/.investigation/phase06:/evidence" --volume "${PWD}/blast-radius-sample/sample/tests.json:/sample/tests.json:ro" blast-radius-analysis-phase02 python /tools/label_structural.py label /src /sample /evidence development-nested development-class holdout-nested holdout-module holdout-import
python -B harness/run_sample.py
python -B harness/benchmark_phase06.py
```

The paired benchmark rebuilds Phase 5 from its committed source and reports CPU from a private Linux cgroup. See `.investigation/phase06/benchmark.json` for per-patch reasons, scheduled costs, and lower bounds computed from the labeled failures.
