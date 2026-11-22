"""Freeze and benchmark the shared-dependency selector against Phase 7."""

import argparse
import functools
import hashlib
import json
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark_phase06 import RUNTIME_FILES, audited_structural_labels, benchmark, build_baseline, scored_cases
from benchmark_phase07 import labeled_batches
from benchmark_phase08 import OUTPUT as PHASE08, REVISION, controlled_labels
from run_phase02 import ROOT, SAMPLE, load_json, run_mode, scorer
from selector import BASE, load_map, load_precise_map, load_shared_map, select_patch

OUTPUT = ROOT / ".investigation/phase09"
BASELINE_IMAGE = "blast-radius-phase09-baseline"
CANDIDATE_IMAGE = "blast-radius-phase09"
CANDIDATE_FILES = (*RUNTIME_FILES, "shared_selector.py", "shared_map.json.gz")
WITNESSES = {
    "witnesses-fixture": "tests/test_executor.py::TestExecutor::test_execute_tpcds",
    "witnesses-test-import": "tests/dialects/test_dax.py::TestDAX::test_evaluate",
}


def freeze_candidate(save):
    target = OUTPUT / "candidate.json"
    record = {
        "runtime": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CANDIDATE_FILES},
        "patches": {name: load_json(OUTPUT / name / "manifest.json") for name in ("holdout", "witnesses")},
    }
    if save and not target.exists():
        target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if load_json(target) != record:
        raise ValueError("Runtime files or patches differ from the frozen candidate")


def score_batches(catalogue):
    tests = catalogue["tests"]
    duration = {test["number"]: round(test["seconds"] * 1000) for test in tests}
    by_id = {test["id"]: {**test, "ms": duration[test["number"]]} for test in tests}
    skipped = frozenset(catalogue.get("skipped", ())).difference(by_id)
    fixtures = load_map(ROOT / "fixture_map.json", tests)
    precise = load_precise_map(ROOT / "precise_map.json.gz", BASE, by_id)
    shared = load_shared_map(ROOT / "shared_map.json.gz", BASE, by_id)
    if not (fixtures and precise and shared):
        raise ValueError("Unable to load the candidate dependency maps")
    raw = audited_structural_labels(PHASE08, tests, load_json(PHASE08 / "manifest.json"))
    controlled, _ = controlled_labels(raw, by_id)
    batches = list(labeled_batches(tests, include_holdout=True))
    batches.append(("phase08", PHASE08, controlled))
    for name in ("holdout", "witnesses"):
        folder = OUTPUT / name
        batches.append((name, folder, audited_structural_labels(folder, tests, load_json(folder / "manifest.json"))))

    report = {}
    for name, folder, answers in batches:
        comparison = {}
        for mode, image, select in (
            ("phase07", BASELINE_IMAGE, select_patch),
            ("phase09", CANDIDATE_IMAGE, functools.partial(select_patch, shared=shared)),
        ):
            details = scored_cases(answers, duration, folder, precise, fixtures, by_id, skipped, select=select)
            score = benchmark(image, folder, answers, tests, details, f"{name}-{mode}", OUTPUT)
            if name == "phase08":
                stdout = (OUTPUT / f"{name}-{mode}-1.jsonl").read_bytes()
                score["original_suite"] = scorer().evaluate_run(stdout, tests, raw)
            comparison[mode] = score
        report[name] = comparison

    (OUTPUT / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report, by_id


def acceptance(report, by_id):
    failures = [f"{name} missed commits" for name, result in report.items() if result["phase09"]["missed_commits"]]
    if report["sample"]["phase09"]["simulated_ms"] > 117408:
        failures.append("Public sample simulated time increased")
    for name in ("phase08", "holdout"):
        if report[name]["phase09"]["median_total_us"] >= report[name]["phase07"]["median_total_us"]:
            failures.append(f"{name} did not improve after accounting for CPU")
    for name, node in WITNESSES.items():
        details = report["witnesses"]["phase09"]["commits"][name]
        if by_id[node]["number"] not in {test for worker in details["workers"] for test in worker}:
            failures.append(f"{name} omitted {node}")
    if failures:
        raise SystemExit("\n".join(failures))


def check_resources(catalogue):
    paths = subprocess.check_output(["git", "ls-files", "-z", "-c", "-o", "--exclude-standard"], cwd=ROOT)
    names = set(paths.decode("utf-8").strip("\0").split("\0"))
    workspace_bytes = sum((ROOT / name).stat().st_size for name in names)
    metadata_bytes = sum(path.stat().st_size for path in (ROOT / ".git").rglob("*") if path.is_file())
    if workspace_bytes + metadata_bytes > 20_000_000:
        raise ValueError("Repository size exceeds 20 MB")

    # Include the original sample and replay 15 sample patches at new IDs to
    # exercise the expected final batch size without using new labels.
    answers = load_json(SAMPLE / "answers.json")["commits"]
    with TemporaryDirectory(dir=OUTPUT) as temporary:
        commits = Path(temporary)
        for source in sorted((SAMPLE / "commits").glob("*.patch")):
            (commits / source.name).write_bytes(source.read_bytes())
        for name in sorted(answers)[:15]:
            (commits / f"repeat-{name}.patch").write_bytes((commits / f"{name}.patch").read_bytes())
            answers[f"repeat-{name}"] = answers[name]
        started = time.monotonic()
        stdout, cpu_us = run_mode("integrated", commits, CANDIDATE_IMAGE)
        wall_seconds = time.monotonic() - started
    result = scorer().evaluate_run(stdout, catalogue["tests"], answers)
    if not result["ok"] or result["missed_commits"] or wall_seconds >= 180:
        raise RuntimeError(f"Final-sized replay failed: {result}")
    data = {"repo_bytes": workspace_bytes + metadata_bytes, "commits": len(answers),
            "wall_seconds": wall_seconds, "stdout_bytes": len(stdout), "cpu_us": cpu_us}
    (OUTPUT / "resources.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    freeze_candidate(args.freeze)
    if args.freeze:
        return
    build_baseline(REVISION, BASELINE_IMAGE, OUTPUT)
    subprocess.run(["docker", "build", "--platform", "linux/amd64", "--no-cache",
                    "-t", CANDIDATE_IMAGE, str(ROOT)], check=True, timeout=600)
    catalogue = load_json(SAMPLE / "tests.json")
    report, by_id = score_batches(catalogue)
    check_resources(catalogue)
    acceptance(report, by_id)


if __name__ == "__main__":
    main()
