"""Benchmark the frozen Phase 5 image and Phase 6 on the same four batches."""

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from collections import defaultdict
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selector import load_map, schedule, select_patch
from run_phase02 import ROOT, SAMPLE, VALIDATION, audit_labels, load_json, run_mode, scorer, validation

BASELINE = "b9e503cc8477d4df071ef8fe9902e65c423ba2a7"
BASELINE_IMAGE = "blast-radius-phase06-baseline"
CANDIDATE_IMAGE = "blast-radius-phase06"
OUTPUT = ROOT / ".investigation/phase06"
RUNTIME_FILES = (".dockerignore", "Dockerfile", "selector.py", "source_selector.py",
                 "fixture_map.json", "precise_selector.py", "precise_map.json.gz")


def fingerprints():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in RUNTIME_FILES}


def check_candidate(freeze=False):
    path = OUTPUT / "candidate-fingerprints.json"
    actual = fingerprints()
    if freeze and not path.exists():
        path.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
    if not path.exists() or load_json(path) != actual:
        raise ValueError("Freeze the unchanged candidate before opening the holdout labels")


def build_baseline(revision=BASELINE, image=BASELINE_IMAGE, output=OUTPUT):
    archive = subprocess.check_output(["git", "archive", revision, *RUNTIME_FILES], cwd=ROOT)
    with TemporaryDirectory(dir=output) as directory:
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            stream.extractall(directory, filter="data")
        build(directory, image)


def build(context, image):
    subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", image, str(context)], check=True)


def scored_cases(dataset, duration, directory, evidence, fixtures, by_id, skipped=(), *, select=select_patch):
    rows = {}
    for path in sorted((directory / "commits").glob("*.patch")):
        reasons = set()
        picked = select(path.read_text(encoding="utf-8"), fixtures, evidence, by_id, reasons, skipped)
        workers = schedule(by_id.values() if picked is None else picked)
        failing = dataset[path.stem]["failing"]
        selected = {test for worker in workers for test in worker}
        rows[path.stem] = {
            "workers": workers,
            "scheduled_ms": max((sum(duration[i] for i in w) for w in workers), default=0) + 2000 * len(workers),
            "failing_floor_ms": min(
                (max(max(duration[i] for i in failing), (sum(duration[i] for i in failing) + n - 1) // n)
                 + 2000 * n for n in range(1, min(len(failing), 8) + 1)), default=0,
            ),
            "misses": sorted(set(failing) - selected),
            "selected": len(selected),
            "reason": "full suite" if picked is None else " + ".join(sorted(reasons)),
        }
    return rows


def audited_structural_labels(directory, tests, manifest):
    by_file = defaultdict(set)
    for test in tests:
        by_file[test["file"]].add(test["id"])
    labels = {}
    for patch in sorted((directory / "commits").glob("*.patch")):
        name = patch.stem
        if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest[name]:
            raise ValueError(f"Frozen patch hash mismatch: {name}")
        label = load_json(directory / f"{name}-labels.json")
        observed = {}
        for raw in sorted(directory.glob(f"{name}*-reports.jsonl")):
            for node, result in validation.outcomes(
                map(json.loads, raw.read_text(encoding="utf-8").splitlines()), by_file
            ).items():
                if result == "failed" or node not in observed:
                    observed[node] = result
        failing = sorted(t["number"] for t in tests if observed.get(t["id"]) == "failed")
        if (not label["complete"] or label["accounted"] != len(tests) or
                not {t["id"] for t in tests}.issubset(observed) or failing != label["failing"]):
            raise ValueError(f"Raw pytest evidence disagrees with label: {name}")
        labels[name] = label
    if set(labels) != {name for name in manifest if name.startswith(directory.name + "-")} or not labels:
        raise ValueError(f"Incomplete cohort: {directory.name}")
    return labels


def benchmark(image, directory, answers, tests, details, destination, output=OUTPUT):
    cpu_times = []
    expected = {commit: row["workers"] for commit, row in details.items()}
    previous = None
    score = scorer()
    for run in range(1, 4):
        stdout, cpu_us = run_mode("integrated", directory / "commits", image)
        (output / f"{destination}-{run}.jsonl").write_bytes(stdout)
        if previous is not None and previous != stdout:
            raise RuntimeError(f"Nondeterministic schedules for {destination}")
        actual = {r["commit"]: r["workers"] for r in map(json.loads, stdout.splitlines())}
        if actual != expected:
            raise RuntimeError(f"Host diagnostics do not match Docker output for {destination}")
        report = score.evaluate_run(stdout, tests, answers)
        if not report["ok"]:
            raise RuntimeError(report)
        previous = stdout
        cpu_times.append(cpu_us)
    costs = defaultdict(int)
    for row in details.values():
        costs[row["reason"]] += row["scheduled_ms"]
    result = {
        "scheduled_ms": sum(costs.values()),
        "simulated_ms": report["simulated_milliseconds"],
        "missed_commits": report["missed_commits"],
        "failing_floor_ms": sum(row["failing_floor_ms"] for row in details.values()),
        "cpu_us": cpu_times,
        "median_total_us": report["simulated_milliseconds"] * 1000 + median(cpu_times),
        "scheduled_ms_by_reason": dict(costs),
        "commits": details,
    }
    print(destination, json.dumps({k: v for k, v in result.items() if k != "commits"}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()
    check_candidate(freeze=args.freeze)
    if args.freeze:
        return
    tests = load_json(SAMPLE / "tests.json")["tests"]
    duration = {t["number"]: round(t["seconds"] * 1000) for t in tests}
    by_id = {t["id"]: {**t, "ms": duration[t["number"]]} for t in tests}
    fixtures = load_map(ROOT / "fixture_map.json", tests)
    validation_labels = {case: load_json(VALIDATION / f"{case}-labels.json") for case in validation.CASES}
    audit_labels(tests, validation_labels)
    manifest = load_json(OUTPUT / "manifest.json")
    batches = {
        "sample": (SAMPLE, load_json(SAMPLE / "answers.json")["commits"]),
        "validation": (VALIDATION, validation_labels),
    }
    for cohort in ("development", "holdout"):
        directory = OUTPUT / cohort
        batches[cohort] = (directory, audited_structural_labels(directory, tests, manifest))

    build_baseline()
    build(ROOT, CANDIDATE_IMAGE)
    baseline = subprocess.check_output(["git", "show", f"{BASELINE}:precise_map.json.gz"], cwd=ROOT)
    candidate = (ROOT / "precise_map.json.gz").read_bytes()
    results = {}
    for cohort, (directory, answers) in batches.items():
        comparison = {}
        for mode, image, payload in (("phase05", BASELINE_IMAGE, baseline), ("phase06", CANDIDATE_IMAGE, candidate)):
            evidence = json.loads(gzip.decompress(payload))
            details = scored_cases(answers, duration, directory, evidence, fixtures, by_id)
            comparison[mode] = benchmark(image, directory, answers, tests, details, f"{cohort}-{mode}")
        results[cohort] = comparison
    (OUTPUT / "benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    if any(pair["phase06"]["missed_commits"] for pair in results.values()):
        raise SystemExit("Phase 6 missed a failing commit")
    if results["sample"]["phase06"]["scheduled_ms"] > results["sample"]["phase05"]["scheduled_ms"]:
        raise SystemExit("Phase 6 regressed on the sample")
    if sum(results[cohort]["phase06"]["median_total_us"] for cohort in ("development", "holdout")) >= sum(
        results[cohort]["phase05"]["median_total_us"] for cohort in ("development", "holdout")
    ):
        raise SystemExit("Structural batch did not get cheaper")


if __name__ == "__main__":
    main()
