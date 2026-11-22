# Phase 9 walkthrough

1. Read `FixtureReads` and `test_modules` in `tools/collect_shared_dependencies.py`. Pytest hooks identify the calling test or a setup scope, and teardown uses the largest scope ending. The Python subprocess audit hook flags fixture paths with unassigned readers. The import graph links the changed module to its own tests and the tests in transitive importers.
2. Read `test_readers` in `shared_selector.py`, then `select_patch` in `selector.py`. Test diffs are applied to pinned source and checked for changes outside supported assertion expectations. Fixture edits use known readers for supported text formats. The selector unions IDs across all changed files and sends the result to the existing scheduler.
3. Read `tools/label_phase09.py` and `harness/benchmark_phase09.py`. The first freezes patch bytes and produces full-suite labels. The second checks the frozen runtime hashes, audits raw labels, and checks the host schedules against each restricted Linux run.

The maps describe the passing pinned base. The fixture map covers observed Python opens of SQL and JSON fixtures. Native file reads or dependencies introduced by a patch may escape that observation. The test map follows static imports, so reflection or implicit state shared outside the import graph can also escape it. The supported assertion edits and full-suite fallback bound the candidate's use of that evidence.

## Reproduce from the project root

Reuse the pinned checkout and locked Linux AMD64 analysis image from [Phase 5](phase-05-precise-selection-context.md).

```powershell
python -B tools/label_phase09.py prepare .investigation/sqlglot blast-radius-sample/sample .investigation/phase09
$phase09Mounts = @(
    '--volume', "${PWD}/.investigation/sqlglot:/src:ro",
    '--volume', "${PWD}/tools:/tools:ro",
    '--volume', "${PWD}/.investigation/phase09:/evidence",
    '--volume', "${PWD}/blast-radius-sample/sample/tests.json:/sample/tests.json:ro"
)
docker run --rm --platform linux/amd64 --network none --cpus 4 --memory 8192m --env SKIP_INTEGRATION=0 --env PYTHONDONTWRITEBYTECODE=1 --env PYTHONPATH=/tools/phase09:/src @phase09Mounts blast-radius-analysis-phase02 python /tools/collect_shared_dependencies.py /sample/tests.json /evidence/shared_map.json.gz
Get-FileHash shared_map.json.gz,.investigation/phase09/shared_map.json.gz
python -B harness/benchmark_phase09.py --freeze
docker run --rm --platform linux/amd64 --network none --cpus 4 --memory 8192m --env SKIP_INTEGRATION=0 --env PYTHONDONTWRITEBYTECODE=1 @phase09Mounts blast-radius-analysis-phase02 python /tools/label_phase09.py label /src /sample /evidence
python -B -m unittest discover -s tests -q
python -B harness/benchmark_phase09.py
python -B blast-radius-sample/score.py blast-radius-sample/sample blast-radius-sample/sample/answers.json .investigation/phase09/sample-phase09-1.jsonl
```

The benchmark writes `.investigation/phase09/benchmark.json` and `.investigation/phase09/resources.json`. The report retains original and controlled Phase 8 scores. The prior independent batches and the Phase 8 diagnostics need their raw evidence directories.
