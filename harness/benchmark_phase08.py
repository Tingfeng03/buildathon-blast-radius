"""Attribute Phase 7 score to labeled failures and measure a path-based probe."""

import argparse
import gzip
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark_phase06 import audited_structural_labels, benchmark, build, build_baseline, scored_cases
from probe_phase08 import file_selector
from run_phase02 import ROOT, SAMPLE, load_json, scorer, validation
from selector import load_map, schedule, select_patch

sys.path.insert(0, str(ROOT / "tools"))
from label_phase08 import CASES
from check_phase08_timeouts import timeout_ids

OUTPUT = ROOT / ".investigation/phase08"
REVISION = "0f63813b0a47409b31f91fd5961d806a99c848c4"
BASELINE_IMAGE = "blast-radius-phase08-phase07"
PROBE_IMAGE = "blast-radius-phase08-probe"


def fixture_evidence(by_id):
    with gzip.open(ROOT / ".investigation/dependencies.json.gz", "rt", encoding="utf-8") as stream:
        observed = json.load(stream)
    nodeids = observed["nodeids"]
    if observed["pytest_status"] != 0 or not set(by_id).issubset(nodeids):
        raise ValueError("Fixture probe requires a complete passing base trace")
    return {
        path: sorted(nodeids[index] for index in indices)
        for path, indices in observed["fixtures"].items()
        if indices and all(type(index) is int and 0 <= index < len(nodeids) for index in indices)
    }


def build_probe(readers):
    with TemporaryDirectory(dir=OUTPUT) as directory:
        context = Path(directory)
        (context / "Dockerfile").write_text(
            f"FROM {BASELINE_IMAGE}\n"
            "RUN mv /app/selector.py /app/phase07_selector.py\n"
            "COPY selector.py fixture_probe.json /app/\n",
            encoding="utf-8",
        )
        shutil.copyfile(ROOT / "harness/probe_phase08.py", context / "selector.py")
        (context / "fixture_probe.json").write_text(json.dumps(readers), encoding="utf-8")
        build(context, PROBE_IMAGE)


def cost(workers, duration):
    return max((sum(duration[test] for test in worker) for worker in workers), default=0) + 2000 * len(workers)


def summarize(rows, duration, by_number, answers):
    aggregates = defaultdict(lambda: {"patches": 0, "scheduled_ms": 0, "failing_floor_ms": 0,
                                      "failing_only_schedule_ms": 0, "harmless_ms": 0, "missed": 0})
    for case, row in rows.items():
        failing = answers[case]["failing"]
        failing_only = schedule(by_number[number] for number in failing)
        row["failing_only_schedule_ms"] = cost(failing_only, duration)
        row["category"] = CASES[case][0] if case in CASES else "sample"
        row["cost_above_floor_ms"] = row["scheduled_ms"] - row["failing_floor_ms"]
        for kind in (f"category/{row['category']}", f"reason/{row['reason']}"):
            entry = aggregates[kind]
            entry["patches"] += 1
            entry["scheduled_ms"] += row["scheduled_ms"]
            entry["failing_floor_ms"] += row["failing_floor_ms"]
            entry["failing_only_schedule_ms"] += row["failing_only_schedule_ms"]
            entry["harmless_ms"] += row["scheduled_ms"] if not failing else 0
            entry["missed"] += bool(row["misses"])
    return dict(aggregates)


def controlled_labels(raw, by_id):
    pending = {case: timeout_ids(OUTPUT, case) & by_id.keys() for case in raw}
    if not any(pending.values()):
        return raw, {}
    directory = OUTPUT / "timeout-controls"
    control = load_json(directory / "result.json")
    by_file = defaultdict(set)
    for test in by_id.values():
        by_file[test["file"]].add(test["id"])

    def observed(tag):
        path = directory / f"{tag}-reports.jsonl"
        events = map(json.loads, path.read_text(encoding="utf-8").splitlines())
        return validation.outcomes(events, by_file)

    baseline = observed("baseline")
    adjusted = {}
    cleared = {}
    for case, record in raw.items():
        retained = set(record["failing"])
        if pending[case]:
            replay = observed(case)
            if set(control["cases"][case]) != pending[case]:
                raise ValueError(f"Incomplete timeout recheck for {case}")
            for node in sorted(pending[case]):
                outcome = replay.get(node)
                if control["baseline"].get(node) != baseline.get(node) or control["cases"][case][node] != outcome:
                    raise ValueError(f"Recorded timeout control disagrees with raw pytest evidence for {node}")
                if outcome == baseline.get(node) == "passed":
                    retained.remove(by_id[node]["number"])
                    cleared.setdefault(case, []).append(node)
        adjusted[case] = {**record, "failing": sorted(retained)}
    return adjusted, cleared


def dependency_witnesses(evidence, fixtures, by_id, skipped, probe_select):
    findings = {}
    for name in ("fixture-witness", "test-import-witness"):
        directory = OUTPUT / name
        result = load_json(directory / "result.json")
        node = result["test"]
        by_file = {by_id[node]["file"]: {node}}
        for label in ("base", "changed"):
            reports = (directory / f"{label}-reports.jsonl").read_text(encoding="utf-8").splitlines()
            if validation.outcomes(map(json.loads, reports), by_file).get(node) != result[label]:
                raise ValueError(f"Witness label disagrees with the {label} reports for {node}")
        if result["base"] != "passed" or result["changed"] != "failed":
            raise ValueError(f"Expected the witness test to regress for {node}")
        patch = (directory / "change.patch").read_text(encoding="utf-8")
        picked = probe_select(patch, fixtures, evidence, by_id, skipped=skipped)
        findings[name] = {**result, "probe_selected": picked is None or any(test["id"] == node for test in picked)}
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selections", action="store_true", help="Print planned schedules before opening labels")
    args = parser.parse_args()

    catalogue = load_json(SAMPLE / "tests.json")
    tests = catalogue["tests"]
    duration = {test["number"]: round(test["seconds"] * 1000) for test in tests}
    by_id = {test["id"]: {**test, "ms": duration[test["number"]]} for test in tests}
    by_number = {test["number"]: test for test in by_id.values()}
    skipped = frozenset(catalogue.get("skipped", ())).difference(by_id)
    evidence_bytes = subprocess.check_output(["git", "show", f"{REVISION}:precise_map.json.gz"], cwd=ROOT)
    evidence = json.loads(gzip.decompress(evidence_bytes))
    fixtures = load_map(ROOT / "fixture_map.json", tests)
    fixture_readers = fixture_evidence(by_id)
    probe_select = file_selector(select_patch, fixture_readers)

    def details(answers, directory, select):
        return scored_cases(answers, duration, directory, evidence, fixtures, by_id, skipped, select=select)

    if args.selections:
        unknown_labels = {case: {"failing": []} for case in CASES}
        current = details(unknown_labels, OUTPUT, select_patch)
        probe = details(unknown_labels, OUTPUT, probe_select)
        for case, row in current.items():
            print(case, row["reason"], row["scheduled_ms"], probe[case]["reason"], probe[case]["scheduled_ms"])
        return

    manifest = load_json(OUTPUT / "manifest.json")
    if set(manifest) != set(CASES):
        raise ValueError("Frozen cases and diagnostic manifest disagree")
    raw = audited_structural_labels(OUTPUT, tests, manifest)
    diagnostic, cleared = controlled_labels(raw, by_id)
    batches = {
        "diagnostic": (OUTPUT, diagnostic),
        "sample": (SAMPLE, load_json(SAMPLE / "answers.json")["commits"]),
    }
    build_baseline(REVISION, BASELINE_IMAGE, OUTPUT)
    build_probe(fixture_readers)
    report = {}
    for name, (directory, answers) in batches.items():
        report[name] = {}
        for mode, image, select in (
            ("phase07", BASELINE_IMAGE, select_patch),
            ("file_probe", PROBE_IMAGE, probe_select),
        ):
            rows = details(answers, directory, select)
            groups = summarize(rows, duration, by_number, answers)
            result = benchmark(image, directory, answers, tests, rows, f"{name}-{mode}", OUTPUT)
            report[name][mode] = {**result, "groups": groups}
            if name == "diagnostic":
                raw_rows = details(raw, directory, select)
                stdout = (OUTPUT / f"{name}-{mode}-1.jsonl").read_bytes()
                raw_score = scorer().evaluate_run(stdout, tests, raw)
                if not raw_score["ok"]:
                    raise RuntimeError(raw_score)
                report[name][mode]["original_suite"] = {
                    "simulated_ms": raw_score["simulated_milliseconds"],
                    "missed_commits": raw_score["missed_commits"],
                    "failing_floor_ms": sum(row["failing_floor_ms"] for row in raw_rows.values()),
                }
    report["timeouts_cleared_by_isolated_control"] = cleared
    report["dependency_witnesses"] = dependency_witnesses(evidence, fixtures, by_id, skipped, probe_select)
    (OUTPUT / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
