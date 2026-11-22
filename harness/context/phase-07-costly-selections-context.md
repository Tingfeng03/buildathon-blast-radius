# Phase 7 walkthrough

1. Start with `select_patch` and `main` in `selector.py`. The selector still unions evidence across files. A referenced ID can be omitted from that union when the catalogue explicitly marks it skipped and gives it no test number.
2. Read `definitions`, `body_readers`, and `guarded_statement` in `precise_selector.py`. A limited guard around an unchanged statement uses the tests that executed the statement. Literal default changes use import dependencies or the observed callers of an optimizer function. New private module helpers and constant class attributes use import dependencies when scope alignment proves the preceding declarations are unchanged.
3. Read `membership_readers` and `import_dependents` in `tools/build_precise_map.py`. The regenerated map identifies set constants whose only pinned uses are attributed membership checks. Definitions that export the set, read it through attributes or local aliases, or consume it outside an attributed method retain module-level coverage.
4. Read `harness/benchmark_phase07.py`. It uses locally generated labels for evaluation, checks their agreement with the pytest reporter, and compares actual output with host diagnostics for both revisions.

## Reproduce

Use the pinned checkout, stored parent and worker traces, and Linux AMD64 analysis image from [Phase 6](phase-06-narrow-fallbacks-context.md). Run the commands from the project root.

```powershell
python -B tools/label_phase07.py prepare .investigation/sqlglot blast-radius-sample/sample .investigation/phase07
$phase07Mounts = @(
    '--volume', "${PWD}/.investigation/sqlglot:/src:ro",
    '--volume', "${PWD}/tools:/tools:ro",
    '--volume', "${PWD}/.investigation/phase07:/evidence",
    '--volume', "${PWD}/blast-radius-sample/sample/tests.json:/sample/tests.json:ro"
)
docker run --rm --platform linux/amd64 --network none --cpus 4 --memory 8192m --env SKIP_INTEGRATION=0 --env PYTHONDONTWRITEBYTECODE=1 @phase07Mounts blast-radius-analysis-phase02 python /tools/label_phase07.py label /src /sample /evidence development-default development-definition development-setting development-nested
python -B tools/build_precise_map.py
python -B harness/benchmark_phase07.py --development
python -B harness/benchmark_phase07.py --freeze
docker run --rm --platform linux/amd64 --network none --cpus 4 --memory 8192m --env SKIP_INTEGRATION=0 --env PYTHONDONTWRITEBYTECODE=1 @phase07Mounts blast-radius-analysis-phase02 python /tools/label_phase07.py label /src /sample /evidence holdout-default holdout-setting holdout-definition
python -B -m unittest discover -s tests -q
python -B harness/run_sample.py
python -B harness/run_sample.py --all-tests
python -B harness/benchmark_phase07.py
```

The final output is `.investigation/phase07/benchmark.json`. It includes each selection reason, its scheduled cost and failing-set lower bound, and the three CPU measurements for each version and cohort.
