"""Freeze six Phase 9 holdout patches and label them and the Phase 8 witnesses."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from label_phase08 import fixture_witness, patch_bytes, validator_witness
from phase02.validation import label_case

CASES = {
    "holdout-direct-fixture": (
        ("tests/fixtures/partial.sql", "SELECT a FROM x WHERE\n", "SELECT a FROM x WHERE true\n"),
    ),
    "holdout-shared-fixture": (
        ("tests/fixtures/optimizer/tpc-h/tpc-h.sql", "-- TPC-H 1\n", "-- TPC-H 1 (pricing)\n"),
    ),
    "holdout-test-assertion": (
        ("tests/test_helper.py", "self.assertEqual(s2(), \"b2\")", "self.assertEqual(s2(), \"b3\")"),
    ),
    "holdout-imported-helper": (
        ("tests/dialects/test_dialect.py", "self.assertIn(fragment, duckdb_sql)",
         "self.assertIn(fragment.upper(), duckdb_sql)"),
    ),
    "holdout-mixed": (
        ("tests/test_tokens.py", "self.assertEqual(tokens[0].comments, [\" c \"])",
         "self.assertEqual(tokens[0].comments, [\" changed \"])"),
        ("tests/fixtures/pretty.sql", "SET x = 1;\n", "SET x = 2;\n"),
    ),
    "holdout-unresolved": (
        ("tests/test_executor.py", "cls.cache = {}\n", "cls.cache = dict()\n"),
    ),
    "witnesses-fixture": (("tests/fixtures/optimizer/tpc-ds/tpc-ds.sql", fixture_witness, None),),
    "witnesses-test-import": (("tests/dialects/test_dialect.py", validator_witness, None),),
}


def edits_for(base, case):
    edits = []
    for path, before, after in CASES[case]:
        original = (base / path).read_text(encoding="utf-8")
        if callable(before):
            changed = before(original)
        else:
            if original.count(before) != 1:
                raise ValueError(f"Expected one anchor for {case} in {path}")
            changed = original.replace(before, after, 1)
        edits.append((path, original, changed))
    return edits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "label"))
    parser.add_argument("base", type=Path)
    parser.add_argument("sample", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    for group in ("holdout", "witnesses"):
        output = args.output / group
        manifest = output / "manifest.json"
        cases = [name for name in CASES if name.startswith(group + "-")]
        edits = {name: edits_for(args.base, name) for name in cases}
        patches = {name: patch_bytes(edits[name]) for name in cases}
        hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in patches.items()}
        if manifest.exists() and json.loads(manifest.read_text(encoding="utf-8")) != hashes:
            raise ValueError(f"Frozen {group} manifest has changed")
        if args.action == "prepare":
            (output / "commits").mkdir(parents=True, exist_ok=True)
        elif not manifest.exists() or not (args.output / "candidate.json").exists():
            raise ValueError("Freeze both patches and candidate before labeling")
        for name, payload in patches.items():
            path = output / "commits" / f"{name}.patch"
            if args.action == "prepare" and not path.exists():
                path.write_bytes(payload)
            if path.read_bytes() != payload:
                raise ValueError(f"Patch bytes changed for {name}")
        if args.action == "prepare":
            manifest.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
            continue
        for name in cases:
            target = output / f"{name}-labels.json"
            if target.exists() and json.loads(target.read_text(encoding="utf-8"))["complete"]:
                continue
            with TemporaryDirectory() as temporary:
                scratch = Path(temporary)
                label = label_case(args.base, args.sample, scratch, name, edits=edits[name])
                for path in scratch.iterdir():
                    if path.name != target.name:
                        shutil.copyfile(path, output / path.name)
                shutil.copyfile(scratch / target.name, target)
            if not label["complete"]:
                raise RuntimeError(f"Unresolved outcomes for {name}")


if __name__ == "__main__":
    main()
