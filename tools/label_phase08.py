"""Freeze and label independent diagnostic patches against the pinned checkout."""

import argparse
import difflib
import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from phase02.validation import label_case, run_suite


# Choose edits by file purpose before inspecting selector output or test outcomes.
# These strata cover different inputs to the system and do not estimate their prevalence.
CASES = {
    "phase08-test-assertion": ("tests", (
        ("tests/test_helper.py", '        self.assertEqual(s1(), "a0")',
         '        self.assertEqual(s1(), "a1")'),
    )),
    "phase08-test-comment": ("tests", (
        ("tests/test_tokens.py", "    def test_space_keywords(self):\n",
         "    def test_space_keywords(self):\n        # Token counts include punctuation.\n"),
    )),
    "phase08-fixture-identity": ("fixtures", (
        ("tests/fixtures/identity.sql", "SUM(1)\nSUM(CASE WHEN", "SUM(1\nSUM(CASE WHEN"),
    )),
    "phase08-fixture-json": ("fixtures", (
        ("tests/fixtures/jsonpath/cts.json", '      "name": "basic, root",',
         '      "name": "basic root selection",'),
    )),
    "phase08-fixture-nested-sql": ("fixtures", (
        ("tests/fixtures/optimizer/tpc-ds/tpc-ds.sql", "-- TPC-DS 1\n",
         "-- TPC-DS 1 (customer returns)\n"),
    )),
    "phase08-config-dialect": ("configuration", (
        ("sqlglot/dialects/mysql.py", "    DPIPE_IS_STRING_CONCAT = False\n",
         "    DPIPE_IS_STRING_CONCAT = True\n"),
    )),
    "phase08-config-typing": ("configuration", (
        ("sqlglot/dialects/mysql.py", "    SAFE_DIVISION = True\n",
         "    SAFE_DIVISION: bool = True\n"),
    )),
    "phase08-source-condition": ("source", (
        ("sqlglot/schema.py", "return name in self.column_names(table, dialect=dialect, normalize=normalize)",
         "return name not in self.column_names(table, dialect=dialect, normalize=normalize)"),
    )),
    "phase08-source-refactor": ("source", (
        ("sqlglot/schema.py", "        return not self.mapping\n",
         "        return not bool(self.mapping)\n"),
    )),
    "phase08-project-docs": ("project files", (
        ("README.md", "## Install\n", "## Install\n\nInstall SQLGlot with pip.\n"),
    )),
    "phase08-project-lint": ("project files", (
        ("pyproject.toml", "line-length = 100\n", "line-length = 96\n"),
    )),
    "phase08-mixed": ("mixed", (
        ("tests/test_helper.py", '        self.assertEqual(s2(), "b0")',
         '        self.assertEqual(s2(), "b1")'),
        ("sqlglot/dialects/mysql.py", "    CONCAT_WS_COALESCE = True\n",
         "    CONCAT_WS_COALESCE = False\n"),
    )),
}


def edits_for(base, case):
    edits = []
    for path, before, after in CASES[case][1]:
        original = (base / path).read_text(encoding="utf-8")
        if original.count(before) != 1 or not original.endswith("\n"):
            raise ValueError(f"Expected one anchor and a final newline in pinned {path}")
        edits.append((path, original, original.replace(before, after, 1)))
    return edits


def patch_bytes(edits):
    parts = []
    for path, old, new in edits:
        diff = difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}")
        parts.append(f"diff --git a/{path} b/{path}\n" + "".join(diff))
    return "".join(parts).encode()


def prepare(base, output):
    commits = output / "commits"
    commits.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for case in CASES:
        path = commits / f"{case}.patch"
        payload = patch_bytes(edits_for(base, case))
        if path.exists() and path.read_bytes() != payload:
            raise ValueError(f"Frozen patch changed: {case}")
        if not path.exists():
            path.write_bytes(payload)
        manifest[case] = hashlib.sha256(payload).hexdigest()
    target = output / "manifest.json"
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != manifest:
            raise ValueError("Frozen manifest changed")
    else:
        target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def check_witness(base, output, test_id, changed_path, edit):
    by_file = {test_id.split("::")[0]: {test_id}}
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as directory:
        checkout = Path(directory) / "checkout"
        shutil.copytree(base, checkout, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
        before = run_suite(checkout, output, "base", [test_id], by_file)
        path = checkout / changed_path
        original = path.read_text(encoding="utf-8")
        changed = edit(original)
        (output / "change.patch").write_bytes(patch_bytes([(changed_path, original, changed)]))
        path.write_text(changed, encoding="utf-8")
        after = run_suite(checkout, output, "changed", [test_id], by_file)
    result = {"test": test_id, "base": before.get(test_id), "changed": after.get(test_id)}
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    if result["base"] != "passed" or result["changed"] != "failed":
        raise ValueError("Targeted witness did not establish the expected dependency")


def fixture_witness(source):
    start = source.index("\nWITH customer_total_return\n")
    end = source.index(";")
    if start > end:
        raise ValueError("Unexpected first query in the pinned fixture")
    return source[:start] + "\nSELECT (" + source[end:]


def validator_witness(source):
    anchor = "self.assertEqual(write_sql, expression.sql(dialect=write_dialect))"
    if source.count(anchor) != 1:
        raise ValueError("Unexpected transpile helper in the pinned suite")
    return source.replace(anchor, anchor.replace("write_sql,", "write_sql.upper(),"), 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "label", "dependency-witnesses"))
    parser.add_argument("base", type=Path)
    parser.add_argument("sample", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("cases", nargs="*")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.base, args.output)
        return
    if args.action == "dependency-witnesses":
        check_witness(args.base, args.output / "fixture-witness",
                      "tests/test_executor.py::TestExecutor::test_execute_tpcds",
                      "tests/fixtures/optimizer/tpc-ds/tpc-ds.sql", fixture_witness)
        check_witness(args.base, args.output / "test-import-witness",
                      "tests/dialects/test_dax.py::TestDAX::test_evaluate",
                      "tests/dialects/test_dialect.py", validator_witness)
        return
    if not args.cases or not set(args.cases).issubset(CASES):
        parser.error("provide one or more frozen case names")
    manifest = json.loads((args.output / "manifest.json").read_text(encoding="utf-8"))
    for case in args.cases:
        edits = edits_for(args.base, case)
        payload = (args.output / "commits" / f"{case}.patch").read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest[case] or payload != patch_bytes(edits):
            raise ValueError(f"Frozen patch changed: {case}")
        if not label_case(args.base, args.sample, args.output, case, edits=edits)["complete"]:
            raise RuntimeError(f"Unresolved test results for {case}")


if __name__ == "__main__":
    main()
