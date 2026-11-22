"""Measure three runs of the packaged selector on both labeled datasets."""

import json
import subprocess
from statistics import median

from run_phase02 import ROOT, SAMPLE, VALIDATION, audit_labels, load_json, run_mode, scorer, validation


def main():
    destination = ROOT / ".investigation/phase05"
    destination.mkdir(parents=True, exist_ok=True)
    labels = {case: load_json(VALIDATION / f"{case}-labels.json") for case in validation.CASES}
    tests = load_json(SAMPLE / "tests.json")["tests"]
    audit_labels(tests, labels)
    image = "blast-radius-phase05"
    subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", image, str(ROOT)], check=True)
    score = scorer()
    for name, directory, answers in (
        ("sample", SAMPLE, load_json(SAMPLE / "answers.json")["commits"]),
        ("validation", VALIDATION, labels),
    ):
        totals = []
        for i in range(1, 4):
            stdout, cpu_us = run_mode("integrated", directory / "commits", image)
            (destination / f"{name}-{i}.jsonl").write_bytes(stdout)
            report = score.evaluate_run(stdout, tests, answers)
            if not report["ok"] or report["missed_commits"]:
                raise ValueError(report)
            sim = report["simulated_milliseconds"] / 1000
            totals.append(sim + cpu_us / 1_000_000)
            print(json.dumps(dict(dataset=name, run=i, simulated=sim, missed=0, cpu_us=cpu_us)), flush=True)
        print(f"{name} median including CPU = {median(totals):.3f} s")


if __name__ == "__main__":
    main()
