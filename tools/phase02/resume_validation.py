"""Complete unresolved labels after an interrupted analysis container."""

import json
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from validation import edited_text, outcomes, run_suite


def merge_outcomes(state, observations):
    for node, result in observations.items():
        if result == "failed" or node not in state:
            state[node] = result


def resume(base, sample, output, case):
    tests = json.loads((sample / "tests.json").read_text(encoding="utf-8"))["tests"]
    by_file = defaultdict(set)
    for test in tests:
        by_file[test["file"]].add(test["id"])
    state = {}
    for report in sorted(output.glob(f"{case}*-reports.jsonl")):
        events = []
        for line in report.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        merge_outcomes(state, outcomes(events, by_file))
    unresolved_files = [path for path, ids in sorted(by_file.items()) if ids.difference(state)]
    print(case, "resuming", len(unresolved_files), "files", flush=True)
    if unresolved_files:
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary) / "checkout"
            shutil.copytree(base, checkout, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
            path, _, changed = edited_text(base, case)
            (checkout / path).write_text(changed, encoding="utf-8")
            # Batch only files with unknown outcomes. Run separately if a batch aborts.
            for index in range(0, len(unresolved_files), 8):
                group = unresolved_files[index:index + 8]
                observed = run_suite(checkout, output, f"{case}-resume-{index}", group, by_file)
                for path in group:
                    if by_file[path].difference(state, observed):
                        retry = run_suite(checkout, output, f"{case}-resume-{path.replace('/', '-')}", [path], by_file)
                        merge_outcomes(observed, retry)
                merge_outcomes(state, observed)
    unresolved = sorted(test["id"] for test in tests if test["id"] not in state)
    failing = sorted(test["number"] for test in tests if state.get(test["id"]) == "failed")
    result = {
        "complete": not unresolved, "unresolved": unresolved,
        "accounted": len(tests) - len(unresolved), "failing": failing,
        "outcomes": {test["id"]: state[test["id"]] for test in tests if test["id"] in state},
    }
    (output / f"{case}-labels.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(case, "accounted", result["accounted"], "failed", len(failing), "unresolved", len(unresolved), flush=True)


if __name__ == "__main__":
    resume(*map(Path, sys.argv[1:4]), sys.argv[4])
