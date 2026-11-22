"""Compare the Phase 6 revision and frozen Phase 7 runtime on labeled patches."""

import argparse
import gzip
import json
import subprocess

from benchmark_phase06 import (
    OUTPUT as PHASE06,
    audited_structural_labels,
    benchmark,
    build,
    build_baseline,
    fingerprints,
    scored_cases,
)
from run_phase02 import ROOT, SAMPLE, VALIDATION, audit_labels, load_json, validation
from selector import load_map


BASELINE = "5a6187bc9dd26f830988d62c6b72994317aab6ec"
IMAGES = ("blast-radius-phase07-baseline", "blast-radius-phase07")
OUTPUT = ROOT / ".investigation/phase07"


def freeze_candidate(freeze):
    record = OUTPUT / "candidate-fingerprints.json"
    actual = {"runtime_files": fingerprints(), "patches": load_json(OUTPUT / "manifest.json")}
    if freeze and not record.exists():
        record.write_text(json.dumps(actual, indent=2) + "\n", encoding="utf-8")
    if not record.exists() or actual != load_json(record):
        raise ValueError("Freeze the runtime and patch manifest before opening the holdout")


def labeled_batches(tests, include_holdout):
    previous_validation = {case: load_json(VALIDATION / f"{case}-labels.json")
                           for case in validation.CASES}
    audit_labels(tests, previous_validation)
    yield "sample", SAMPLE, load_json(SAMPLE / "answers.json")["commits"]
    yield "previous-validation", VALIDATION, previous_validation
    for output in (PHASE06, OUTPUT):
        manifest = load_json(output / "manifest.json")
        for cohort in ("development", "holdout"):
            if output == OUTPUT and cohort == "holdout" and not include_holdout:
                continue
            directory = output / cohort
            yield f"{output.name}-{cohort}", directory, audited_structural_labels(directory, tests, manifest)


def main():
    parser = argparse.ArgumentParser()
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--freeze", action="store_true")
    options.add_argument("--development", action="store_true", help="Replay known labels without Docker")
    args = parser.parse_args()
    if not args.development:
        freeze_candidate(args.freeze)
    if args.freeze:
        return

    catalogue = load_json(SAMPLE / "tests.json")
    tests = catalogue["tests"]
    duration = {test["number"]: round(test["seconds"] * 1000) for test in tests}
    by_id = {test["id"]: {**test, "ms": duration[test["number"]]} for test in tests}
    skipped = frozenset(catalogue.get("skipped", ())).difference(by_id)
    fixtures = load_map(ROOT / "fixture_map.json", tests)
    maps = {
        "phase06": gzip.decompress(subprocess.check_output(["git", "show", f"{BASELINE}:precise_map.json.gz"])),
        "phase07": gzip.decompress((ROOT / "precise_map.json.gz").read_bytes()),
    }
    maps = {name: json.loads(payload) for name, payload in maps.items()}
    if not args.development:
        build_baseline(BASELINE, IMAGES[0], OUTPUT)
        build(ROOT, IMAGES[1])

    comparisons = {}
    for cohort, directory, answers in labeled_batches(tests, include_holdout=not args.development):
        comparison = {}
        for (name, evidence), image in zip(maps.items(), IMAGES):
            details = scored_cases(answers, duration, directory, evidence, fixtures, by_id,
                                   skipped if name == "phase07" else ())
            if args.development:
                for case, row in details.items():
                    if cohort != "sample" or row["misses"]:
                        print(name, case, row["reason"], row["selected"], row["scheduled_ms"],
                              row["failing_floor_ms"], len(row["misses"]), flush=True)
                continue
            comparison[name] = benchmark(image, directory, answers, tests, details,
                                         f"{cohort}-{name}", OUTPUT)
        comparisons[cohort] = comparison

    if args.development:
        return
    (OUTPUT / "benchmark.json").write_text(json.dumps(comparisons, indent=2), encoding="utf-8")
    if any(result["phase07"]["missed_commits"] for result in comparisons.values()):
        raise SystemExit("Phase 7 omitted known failures")
    sample = comparisons.pop("sample")
    if sample["phase07"]["scheduled_ms"] > sample["phase06"]["scheduled_ms"]:
        raise SystemExit("Phase 7 regressed on the official sample")
    if sum(row["phase07"]["median_total_us"] for row in comparisons.values()) >= sum(
            row["phase06"]["median_total_us"] for row in comparisons.values()):
        raise SystemExit("Phase 7 did not reduce the CPU-adjusted cost of the independent cohorts")


if __name__ == "__main__":
    main()
