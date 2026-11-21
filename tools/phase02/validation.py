"""Construct independent validation edits and account for pytest outcomes."""

import ast
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CASES = {
    "validation-import": (
        "sqlglot/dialects/postgres.py",
        "class Postgres(Dialect):",
        'raise ImportError("Phase 02 validation import failure")\n\n\nclass Postgres(Dialect):',
    ),
    "validation-setting": (
        "sqlglot/dialects/duckdb.py",
        "NORMALIZATION_STRATEGY = NormalizationStrategy.CASE_INSENSITIVE",
        "NORMALIZATION_STRATEGY = NormalizationStrategy.UPPERCASE",
    ),
    "validation-worker": (
        "sqlglot/optimizer/eliminate_ctes.py", "if count <= 0:", "if count < 0:",
    ),
    "validation-insertion": (
        "sqlglot/optimizer/simplify.py",
        "def simplify_parens(expression: exp.Expr, dialect: DialectType) -> exp.Expr:\n",
        "def simplify_parens(expression: exp.Expr, dialect: DialectType) -> exp.Expr:\n"
        "    return expression\n",
    ),
}


def edited_text(base, case):
    name, before, after = CASES[case]
    original = (base / name).read_text(encoding="utf-8")
    if original.count(before) != 1:
        raise ValueError(f"Expected one anchor in pinned {name}")
    changed = original.replace(before, after, 1)
    ast.parse(changed)
    return name, original, changed


def prepare(base, output):
    commits = output / "commits"
    commits.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        name, original, changed = edited_text(base, case)
        diff = difflib.unified_diff(
            original.splitlines(keepends=True), changed.splitlines(keepends=True),
            "a/" + name, "b/" + name,
        )
        (commits / (case + ".patch")).write_text(
            f"diff --git a/{name} b/{name}\n" + "".join(diff), encoding="utf-8", newline="\n",
        )


def outcomes(records, by_file):
    """Failures dominate; a pass needs a call result and completed teardown."""
    state = {}
    calls = set()
    for event in records:
        if "file_error" in event:
            for node in by_file.get(event["file_error"], ()):
                state[node] = "failed"
            continue
        node = event["id"]
        if event["result"] == "failed":
            state[node] = "failed"
        elif event["phase"] == "call" and event["result"] == "passed":
            calls.add(node)
        elif event["result"] == "skipped" and event["phase"] in ("setup", "call"):
            state.setdefault(node, "skipped")
        elif event["phase"] == "teardown" and node in calls:
            state.setdefault(node, "passed")
    return state


def label_case(base, sample, output, case):
    tests = json.loads((sample / "tests.json").read_text(encoding="utf-8"))["tests"]
    by_file = {}
    numbers = {}
    for test in tests:
        by_file.setdefault(test["file"], set()).add(test["id"])
        numbers[test["id"]] = test["number"]
    with tempfile.TemporaryDirectory() as temporary:
        checkout = Path(temporary) / "checkout"
        shutil.copytree(base, checkout, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        if case != "baseline":
            path, _, changed = edited_text(base, case)
            (checkout / path).write_text(changed, encoding="utf-8")
        state = run_suite(checkout, output, case, [], by_file)
        missing_files = [path for path, ids in sorted(by_file.items()) if ids.difference(state)]
        for index, path in enumerate(missing_files):
            retry = run_suite(checkout, output, f"{case}-retry-{index}", [path], by_file)
            # A retry can establish positive evidence for previously unobserved IDs.
            # Failures from either run are retained.
            for node, outcome in retry.items():
                if outcome == "failed" or node not in state:
                    state[node] = outcome
    unknown = sorted(set(numbers).difference(state))
    failing = sorted(numbers[node] for node in numbers if state.get(node) == "failed")
    result = {
        "complete": not unknown, "unresolved": unknown, "accounted": len(numbers) - len(unknown),
        "failing": failing, "outcomes": {node: state[node] for node in sorted(numbers) if node in state},
    }
    (output / f"{case}-labels.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(case, "accounted", result["accounted"], "failed", len(failing), "unresolved", len(unknown), flush=True)
    return result


def run_suite(checkout, output, tag, targets, by_file):
    reports = output / f"{tag}-reports.jsonl"
    reports.write_text("", encoding="utf-8")
    with (output / f"{tag}-pytest.log").open("w", encoding="utf-8") as log:
        try:
            run = subprocess.run(
                [sys.executable, __file__, "pytest", str(reports), *(targets or ["tests"])],
                cwd=checkout, stdout=log, stderr=subprocess.STDOUT, timeout=900,
                env={**os.environ, "PYTHONPATH": str(checkout), "PYTHONDONTWRITEBYTECODE": "1"},
            )
            # Internal errors and interrupts leave the reporter's partial record usable.
            print(tag, "pytest exit", run.returncode, flush=True)
        except subprocess.TimeoutExpired:
            print(tag, "pytest wall timeout", flush=True)
    records = []
    for line in reports.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            # The process can be killed while writing its last record.
            continue
    return outcomes(records, by_file)


def pytest_main(reports, targets):
    import pytest
    from _pytest.subtests import SubtestReport

    class Reporter:
        def pytest_runtest_logreport(self, report):
            if isinstance(report, SubtestReport) and not report.failed:
                return
            self.record({"id": report.nodeid, "phase": report.when, "result": report.outcome})

        def pytest_collectreport(self, report):
            if report.failed and report.nodeid.endswith(".py"):
                self.record({"file_error": report.nodeid})

        @staticmethod
        def record(event):
            with reports.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event) + "\n")

    return pytest.main(
        ["-q", "-p", "no:cacheprovider", "--continue-on-collection-errors",
         "--timeout=120", "--timeout-method=signal", *targets], plugins=[Reporter()],
    )


if __name__ == "__main__":
    if sys.argv[1] == "pytest":
        sys.exit(pytest_main(Path(sys.argv[2]), sys.argv[3:]))
    base, sample, output = map(Path, sys.argv[2:5])
    index = sys.argv[5]
    result = label_case(base, sample, output, index)
    if index == "baseline" and (result["failing"] or not result["complete"]):
        sys.exit("Baseline validation failed")
