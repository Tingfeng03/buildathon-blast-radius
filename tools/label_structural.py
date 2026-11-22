"""Freeze independent structural edits and label them with the pinned suite."""

import difflib
import hashlib
import json
import sys
from pathlib import Path

from phase02 import validation

CASES = {
    "development-nested": (
        "sqlglot/generators/bigquery.py",
        '    if scale == exp.UnixToTime.MILLIS:\n        return self.func("TIMESTAMP_MILLIS", timestamp)',
        '    if scale == exp.UnixToTime.MILLIS:\n'
        '        timestamp = exp.Literal.number(0)\n'
        '        return self.func("TIMESTAMP_MILLIS", timestamp)',
    ),
    "development-class": (
        "sqlglot/dialects/redshift.py",
        '        "MONTH": "%B",\n',
        '',
    ),
    "holdout-nested": (
        "sqlglot/optimizer/normalize.py",
        "            if normalized(node, dnf=dnf):\n                continue\n",
        "",
    ),
    "holdout-module": (
        "sqlglot/generators/databricks.py",
        "    exp.DType.TIMESTAMPNTZ,\n    exp.DType.TIMESTAMPLTZ,\n",
        "    exp.DType.TIMESTAMPLTZ,\n",
    ),
    "holdout-import": (
        "sqlglot/dialects/sqlite.py",
        "class SQLite(Dialect):",
        'raise ImportError("Phase 06 independent collection check")\n\n\nclass SQLite(Dialect):',
    ),
}


def patch_bytes(base, case):
    path, old, new = validation.edited_text(base, case)
    diff = difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}")
    return (f"diff --git a/{path} b/{path}\n" + "".join(diff)).encode()


def prepare(base, output, cases=CASES):
    manifest = {}
    for case in cases:
        directory = output / case.split("-")[0] / "commits"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{case}.patch"
        payload = patch_bytes(base, case)
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"Frozen patch changed: {case}")
        path.write_bytes(payload)
        manifest[case] = hashlib.sha256(payload).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(cohorts=CASES):
    action, base, sample, output, *cases = sys.argv[1:]
    base, sample, output = map(Path, (base, sample, output))
    validation.CASES.update(cohorts)
    if action == "prepare":
        prepare(base, output, cohorts)
        return
    if action != "label" or not cases:
        raise SystemExit("Use prepare or label with one or more frozen cases")
    for case in cases:
        if case not in cohorts:
            raise ValueError(f"Unknown case in this cohort: {case}")
        directory = output / case.split("-")[0]
        if (directory / "commits" / f"{case}.patch").read_bytes() != patch_bytes(base, case):
            raise ValueError(f"Frozen patch changed: {case}")
        result = validation.label_case(base, sample, directory, case)
        if not result["complete"]:
            raise RuntimeError(f"Unresolved test results for {case}")


if __name__ == "__main__":
    main()
