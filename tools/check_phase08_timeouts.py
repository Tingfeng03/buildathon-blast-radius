"""Recheck observed suite timeouts in isolation and preserve the original reports."""

import argparse
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from label_phase08 import CASES, edits_for, patch_bytes
from phase02.validation import run_suite


def timeout_ids(directory, case):
    candidates = set()
    failed = Counter()
    direct_timeouts = Counter()
    for reports in sorted(directory.glob(f"{case}*-reports.jsonl")):
        for line in reports.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if "id" in event and event["result"] == "failed":
                failed[event["id"]] += 1
                if event.get("timeout"):
                    direct_timeouts[event["id"]] += 1
    candidates.update(node for node, count in failed.items() if count == direct_timeouts[node])
    # Early reports omit the timeout flag. Require exactly one failed event and
    # a matching pytest summary entry before exercising the same focused control.
    for log in sorted(directory.glob(f"{case}*-pytest.log")):
        names = re.findall(r"^FAILED (\S+) - .*Timeout \(>", log.read_text(encoding="utf-8"), re.MULTILINE)
        candidates.update(node for node in names if failed[node] == 1)
    return candidates


def check(base, sample, output):
    controls = output / "timeout-controls"
    controls.mkdir(parents=True, exist_ok=True)
    tests = json.loads((sample / "tests.json").read_text(encoding="utf-8"))["tests"]
    files = {test["id"]: test["file"] for test in tests}
    pending = {case: timeout_ids(output, case) & files.keys() for case in CASES}
    targets = sorted(set().union(*pending.values()))
    result = {"test_timeout_s": 300, "baseline": {}, "cases": {}}
    if targets:
        by_file = defaultdict(set)
        for target in targets:
            by_file[files[target]].add(target)
        with TemporaryDirectory() as directory:
            checkout = Path(directory) / "checkout"
            shutil.copytree(base, checkout, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
            result["baseline"] = run_suite(checkout, controls, "baseline", targets, by_file, test_timeout=300)
            for case, timed_out in pending.items():
                if not timed_out:
                    continue
                edits = edits_for(base, case)
                if patch_bytes(edits) != (output / "commits" / f"{case}.patch").read_bytes():
                    raise ValueError(f"Frozen patch changed: {case}")
                for path, _, changed in edits:
                    (checkout / path).write_text(changed, encoding="utf-8")
                try:
                    outcomes = run_suite(checkout, controls, case, sorted(timed_out), by_file, test_timeout=300)
                    result["cases"][case] = {node: outcomes.get(node) for node in sorted(timed_out)}
                finally:
                    for path, original, _ in edits:
                        (checkout / path).write_text(original, encoding="utf-8")
    (controls / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("sample", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    check(args.base, args.sample, args.output)
