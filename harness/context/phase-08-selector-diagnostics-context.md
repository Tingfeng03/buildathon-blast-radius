# Phase 8 walkthrough

1. Read `CASES` and `prepare` in `tools/label_phase08.py`. The cohort uses anchored edits against the pinned tree. The manifest records exact patch bytes before any scheduling or label inspection.
2. Read `label_case` and `run_suite` in `tools/phase02/validation.py`. The labeler applies each patch in a temporary checkout and records a pytest outcome for each numbered test. The benchmark independently checks that all numbered outcomes agree with the raw reports.
3. Read `file_selector` in `harness/probe_phase08.py`. It measures the effect of using existing fixture-open observations and the test catalogue as fallback evidence. It exposes how much this change could save and where shared loading could cause it to omit failures.
4. Read `controlled_labels` and `summarize` in `harness/benchmark_phase08.py`. The report compares the archived Phase 7 image and the diagnostic probe, with original suite results and isolated timeout controls. The failing-only schedule uses the actual assigned workers and recorded test durations. The mathematical lower bound can be smaller if packing the failing tests attains a different worker split.

## Reproduce

Use the pinned checkout and Linux AMD64 analysis image from [Phase 7](phase-07-costly-selections-context.md). The commands run from the project root. Split the label runs across disjoint CPU sets when host resources permit.

```powershell
python -B tools/label_phase08.py prepare .investigation/sqlglot blast-radius-sample/sample .investigation/phase08
$phase08Cases = Get-ChildItem .investigation/phase08/commits -Filter '*.patch'
foreach ($phase08Case in $phase08Cases) {
    git -C .investigation/sqlglot apply --check $phase08Case.FullName
    if ($LASTEXITCODE -ne 0) { throw "Patch check failed for $($phase08Case.Name)" }
}
$phase08Mounts = @(
    '--volume', "${PWD}/.investigation/sqlglot:/src:ro",
    '--volume', "${PWD}/tools:/tools:ro",
    '--volume', "${PWD}/.investigation/phase08:/evidence",
    '--volume', "${PWD}/blast-radius-sample/sample/tests.json:/sample/tests.json:ro"
)
$phase08Names = $phase08Cases.BaseName
docker run --rm --platform linux/amd64 --network none --cpus 4 --env SKIP_INTEGRATION=0 --env PYTHONDONTWRITEBYTECODE=1 @phase08Mounts blast-radius-analysis-phase02 python /tools/label_phase08.py label /src /sample /evidence @phase08Names
docker run --rm --platform linux/amd64 --network none --cpus 4 --env SKIP_INTEGRATION=0 --env PYTHONDONTWRITEBYTECODE=1 @phase08Mounts blast-radius-analysis-phase02 python /tools/check_phase08_timeouts.py /src /sample /evidence
docker run --rm --platform linux/amd64 --network none --cpus 4 --env SKIP_INTEGRATION=0 --env PYTHONDONTWRITEBYTECODE=1 @phase08Mounts blast-radius-analysis-phase02 python /tools/label_phase08.py dependency-witnesses /src /sample /evidence
python -B -m unittest discover -s tests -q
python -B harness/benchmark_phase08.py
```

The final report is `.investigation/phase08/benchmark.json`. The benchmark retains original suite results. Isolated controls use a 300 s test limit and clear a timeout in the diagnostic result only when the same numbered test passes on both the pinned baseline and the patched revision.
