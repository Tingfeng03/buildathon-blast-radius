"""Collect, label, and benchmark Phase 02 without changing the submission."""

import argparse
import hashlib
import importlib.util
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "blast-radius-sample" / "sample"
SCRATCH = ROOT / ".investigation"
BASE = SCRATCH / "sqlglot"
OUTPUT = SCRATCH / "phase02"
VALIDATION = OUTPUT / "validation"
TOOLS = ROOT / "tools" / "phase02"
ANALYSIS = "blast-radius-analysis-phase02"
IMAGE = "blast-radius-phase02-benchmark"
BASE_COMMIT = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
INTEGRATED_MAP_SHA256 = "6d9825c25fbb13d1fdd7fcf2a60e49c910c058d4691aaffe66b9d9b6360ccae5"

sys.path.insert(0, str(TOOLS))
sys.path.insert(1, str(ROOT))
import evidence
import validation

MODES = ("phase01", *evidence.MODES)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def check_base():
    for args, expected in [(["rev-parse", "HEAD"], BASE_COMMIT),
                           (["status", "--porcelain"], "")]:
        result = subprocess.check_output(["git", "-C", str(BASE), *args], text=True).strip()
        if result != expected:
            raise SystemExit("Expected the unchanged pinned sqlglot checkout")


def fingerprint():
    paths = {path: ROOT / path for path in (
        "harness/build/phase-02-source-dependencies.md", "fixture_map.json",
        "tools/phase02/candidate.py", "tools/phase02/evidence.py", "tools/phase02/validation.py",
    )}
    paths["selector.py"] = TOOLS / "selector.py"
    return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}


def freeze():
    check_base()
    if any(VALIDATION.glob("validation-*-reports.jsonl")):
        require_frozen()
        print("Validation has started. The existing freeze is intact.")
        return
    validation.prepare(BASE, VALIDATION)
    (OUTPUT / "frozen-rules.json").write_text(json.dumps(fingerprint(), indent=2), encoding="utf-8")
    print("Frozen candidate rules and generated four validation patches", flush=True)


def require_frozen():
    if load_json(OUTPUT / "frozen-rules.json") != fingerprint():
        raise SystemExit("Candidate or validation inputs changed after freezing")


def analysis_container(script, args, evidence_dir, mount_sample=False):
    command = [
        "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
        "--cpus", "4", "--memory", "8192m", "--workdir", "/src",
        "--env", "PYTHONPATH=/src", "--env", "SKIP_INTEGRATION=0", "--env", "COVERAGE_CORE=ctrace",
        "--volume", f"{BASE}:/src:ro", "--volume", f"{TOOLS}:/tools:ro",
        "--volume", f"{evidence_dir}:/evidence",
    ]
    if mount_sample:
        command.extend(["--volume", f"{SAMPLE / 'tests.json'}:/sample/tests.json:ro"])
    command.extend([ANALYSIS, "python", f"/tools/{script}", *args])
    subprocess.run(command, check=True)


def collect():
    check_base()
    worker_output = OUTPUT / "workers"
    worker_output.mkdir(parents=True, exist_ok=True)
    if any(worker_output.iterdir()):
        raise SystemExit("Worker output already exists. Move it aside before collecting again.")
    analysis_container("trace_workers.py", [], worker_output)
    rebuild_maps()


def collect_parent():
    check_base()
    if (SCRATCH / "dependencies.json.gz").exists():
        raise SystemExit("Parent coverage already exists. Move it aside before collecting again.")
    analysis_container("trace_parent.py", [], SCRATCH)


def rebuild_maps():
    check_base()
    worker_output = OUTPUT / "workers"
    result = evidence.build(BASE, SCRATCH, worker_output, BASE_COMMIT)
    print("Worker proof records:", len(result["proof"]), "map sizes:", result["map_bytes"], flush=True)


def labels():
    check_base()
    require_frozen()
    for case in ("baseline", *validation.CASES):
        analysis_container("validation.py", ["label", "/src", "/sample", "/evidence", case], VALIDATION,
                           mount_sample=True)


def resume_labels():
    check_base()
    require_frozen()
    baseline = load_json(VALIDATION / "baseline-labels.json")
    if not baseline["complete"] or baseline["failing"]:
        raise SystemExit("A verified clean baseline is required")
    for case in validation.CASES:
        destination = VALIDATION / f"{case}-labels.json"
        if destination.exists() and load_json(destination)["complete"]:
            continue
        source = OUTPUT / case.replace("validation-", "independent-")
        if not (source / f"{case}-reports.jsonl").exists():
            source = VALIDATION
        analysis_container("resume_validation.py", ["/src", "/sample", "/evidence", case],
                           source, mount_sample=True)
        if source != VALIDATION:
            destination.write_bytes((source / destination.name).read_bytes())


def scorer():
    spec = importlib.util.spec_from_file_location("organizer_score", SAMPLE.parent / "score.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_mode(mode, commits, image=IMAGE):
    command = [
        "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
        "--cgroupns", "private", "--cpus", "2", "--memory", "4096m", "--memory-swap", "4096m",
        "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
        "--env", "HOME=/tmp", "--env", "PYTHONPATH=/app",
        "--volume", f"{commits}:/data/commits:ro", "--volume", f"{SAMPLE / 'tests.json'}:/data/tests.json:ro",
        "--volume", f"{TOOLS}:/phase02:ro",
    ]
    entry_points = {
        "phase01": ["/phase02/selector.py"],
        "integrated": ["/app/selector.py"],
        "fixture-only": ["/app/selector.py", "--fixture-only"],
    }
    entry = entry_points.get(mode)
    if entry is None:
        command.extend(["--volume", f"{OUTPUT / 'workers' / (mode + '.json.gz')}:/evidence.json.gz:ro"])
        entry = ["/phase02/candidate.py", "/evidence.json.gz"]
    command.extend([image, "python", "/phase02/measure_cpu.py", "python", *entry])
    result = subprocess.run(command, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    cpu = re.search(rb"^PHASE02_CPU_US=(\d+)\r?$", result.stderr, re.M)
    if not cpu or len(result.stdout) > 2_000_000:
        raise RuntimeError("Missing container CPU measurement or stdout exceeded 2 MB")
    return result.stdout, int(cpu[1])


def read_selections(path):
    return {row["commit"]: {number for worker in row["workers"] for number in worker}
            for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def audit_labels(tests, answers):
    from resume_validation import merge_outcomes

    by_file = {}
    for test in tests:
        by_file.setdefault(test["file"], set()).add(test["id"])
    for case, recorded in answers.items():
        state = {}
        for directory in (VALIDATION, OUTPUT / case.replace("validation-", "independent-")):
            for path in sorted(directory.glob(f"{case}*-reports.jsonl")):
                reports = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        reports.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                merge_outcomes(state, validation.outcomes(reports, by_file))
        actual = {test["id"]: state[test["id"]] for test in tests if test["id"] in state}
        failing = sorted(test["number"] for test in tests if state.get(test["id"]) == "failed")
        if actual != recorded["outcomes"] or failing != recorded["failing"]:
            raise RuntimeError(f"Raw pytest outcomes do not match the labels for {case}")
        if recorded["complete"] != (len(actual) == len(tests)):
            raise RuntimeError(f"Completeness did not match the catalogue for {case}")


def diagnose():
    import candidate

    answers = load_json(SAMPLE / "answers.json")["commits"]
    tests = load_json(SAMPLE / "tests.json")["tests"]
    nodeids = {test["number"]: test["id"] for test in tests}
    path = "sqlglot/optimizer/eliminate_joins.py"
    patch, = [file for file in (SAMPLE / "commits").glob("*.patch")
              if file.read_text(encoding="utf-8").startswith(f"diff --git a/{path} b/{path}\n")]
    name = patch.stem
    failing = {nodeids[n] for n in answers[name]["failing"]}
    _, parent_trace, worker_trace, _ = evidence.read_traces(SCRATCH, OUTPUT / "workers")
    _, edits = next(candidate.patched_files(
        patch.read_text(encoding="utf-8"),
        {path: {"source": (BASE / path).read_text(encoding="utf-8")}},
    ))
    removed_lines = {line for anchor, removed, _ in edits for line in range(anchor + 1, anchor + 1 + len(removed))}
    details = {}
    for comparison, lines in (("changed-lines", removed_lines), ("whole-file", None)):
        parent = set().union(*(ids for line, ids in parent_trace.get(path, {}).items() if lines is None or line in lines))
        worker = set().union(*(ids for line, ids in worker_trace.get(path, {}).items() if lines is None or line in lines))
        details[comparison] = {
            "parent_omissions": sorted(failing - parent),
            "worker_recovered": sorted((failing - parent) & worker),
            "remaining_omissions": sorted(failing - (parent | worker)),
        }
    results = {mode: read_selections(OUTPUT / f"sample-{mode}-1.jsonl") for mode in MODES}
    before = {nodeids[n] for n in results["parent"][name]}
    after = {nodeids[n] for n in results["worker"][name]}
    details["enclosing-function"] = {
        "parent_omissions": sorted(failing - before),
        "worker_recovered": sorted((failing - before) & after),
        "remaining_omissions": sorted(failing - after),
    }
    marginal = {next_mode: sorted(name for name in answers if results[mode][name] != results[next_mode][name])
                for mode, next_mode in zip(MODES, MODES[1:])}
    report = {"sample_commit": name, "worker_comparisons": details, "changed_by_signal": marginal}
    (OUTPUT / "diagnostics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


def benchmark(dataset="both", integration=False):
    require_frozen()
    target = SCRATCH / "phase03" if integration else OUTPUT
    modes = ("phase01", "integrated") if integration else MODES
    image = "blast-radius-phase03-benchmark" if integration else IMAGE
    if integration:
        source_hash = hashlib.sha256((ROOT / "source_map.json.gz").read_bytes()).hexdigest()
        if source_hash != INTEGRATED_MAP_SHA256:
            raise SystemExit("The packaged map differs from the verified Phase 02 artifact")
        target.mkdir(parents=True, exist_ok=True)
    score = scorer()
    tests = load_json(SAMPLE / "tests.json")["tests"]
    nodeids = {test["number"]: test["id"] for test in tests}
    reference = {test["number"] for test in tests}
    datasets = {}
    if dataset in ("sample", "both"):
        datasets["sample"] = (SAMPLE / "commits", load_json(SAMPLE / "answers.json")["commits"])
    if dataset in ("validation", "both"):
        answers = {
            name: load_json(VALIDATION / f"{name}-labels.json") for name in validation.CASES
        }
        audit_labels(tests, answers)
        datasets["validation"] = (VALIDATION / "commits", answers)
    subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", image, str(ROOT)], check=True)
    for dataset, (commits, answers) in datasets.items():
        complete = all(record.get("complete", True) for record in answers.values())
        if integration:
            if not complete:
                raise RuntimeError(f"{dataset} labels are incomplete")
            expected = {
                "phase01": (OUTPUT / f"{dataset}-phase01-1.jsonl").read_bytes(),
                "integrated": (OUTPUT / f"{dataset}-imports-1.jsonl").read_bytes(),
            }
            fixture, _ = run_mode("fixture-only", commits, image)
            if fixture != expected["phase01"]:
                raise RuntimeError(f"{dataset} fixture-only schedules differ from Phase 01")
        runs = {mode: [] for mode in modes}
        for repeat in range(3):
            for mode in modes:
                stdout, cpu = run_mode(mode, commits, image)
                evaluation = score.evaluate_run(stdout, tests, answers)
                if not evaluation["ok"]:
                    raise RuntimeError(f"Organizer rejected {dataset}/{mode}: {evaluation}")
                (target / f"{dataset}-{mode}-{repeat + 1}.jsonl").write_bytes(stdout)
                if integration and (stdout != expected[mode] or evaluation["missed_commits"]):
                    raise RuntimeError(f"{dataset}/{mode} failed schedule parity or missed a commit")
                selection = {row["commit"]: {n for worker in row["workers"] for n in worker}
                             for row in map(json.loads, stdout.splitlines())}
                misses = evaluation["missed_commits"]
                simulated = evaluation["simulated_milliseconds"]
                omitted = {name: sorted(nodeids[n] for n in answers[name]["failing"] if n not in selection[name])
                           for name in misses}
                runs[mode].append({
                    "cpu_us": cpu, "total_us": score.run_total_microseconds(simulated, cpu),
                    "scheduled_ms": simulated - len(misses) * score.MISS_PENALTY_MILLISECONDS,
                    "simulated_ms": simulated, "missed_commits": misses, "omitted_ids": omitted,
                    "narrowed": sorted(name for name, picked in selection.items() if picked != reference),
                })
        summary = {"complete": complete, "modes": {}}
        for mode, records in runs.items():
            median_us = int(statistics.median(record["total_us"] for record in records))
            rounded = ((median_us + 50_000) // 100_000) / 10
            summary["modes"][mode] = {"runs": records, "median_us": median_us, "score": rounded}
            print(dataset, mode, "score", rounded, "known missed commits", records[0]["missed_commits"], flush=True)
        (target / f"benchmark-{dataset}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        if integration and summary["modes"]["integrated"]["score"] >= summary["modes"]["phase01"]["score"]:
            raise RuntimeError(f"Integrated selector did not improve the CPU-adjusted {dataset} score")


def decision():
    sample = load_json(OUTPUT / "benchmark-sample.json")["modes"]
    validation_report = load_json(OUTPUT / "benchmark-validation.json")
    reference = sample["phase01"]
    eligible = []
    if validation_report["complete"]:
        for mode in evidence.MODES:
            candidate = sample[mode]
            new_selections = set(candidate["runs"][0]["narrowed"]) - set(reference["runs"][0]["narrowed"])
            all_runs = candidate["runs"] + validation_report["modes"][mode]["runs"]
            if new_selections and candidate["score"] < reference["score"] and not any(
                run["missed_commits"] for run in all_runs
            ):
                eligible.append(mode)
    result = {"qualified": eligible, "recommended": eligible[0] if eligible else "phase01"}
    (OUTPUT / "decision.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    commands = {"freeze": freeze, "collect": collect, "collect-parent": collect_parent,
                "maps": rebuild_maps, "label": labels, "resume-labels": resume_labels,
                "benchmark": benchmark, "benchmark-integration": benchmark,
                "diagnose": diagnose, "decision": decision}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=commands)
    parser.add_argument("--dataset", choices=("both", "sample", "validation"), default="both")
    args = parser.parse_args()
    if args.command in ("benchmark", "benchmark-integration"):
        benchmark(args.dataset, integration=args.command == "benchmark-integration")
    else:
        commands[args.command]()
