"""Verify a committed Blast Radius candidate from a clean local checkout."""

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_LIMIT = 4 * 1024**3
BUILD_MEMORY = 8 * 1024**3
STDOUT_LIMIT = 2_000_000
REPO_LIMIT = 20_000_000
APP_FILES = {"selector.py", "source_selector.py", "fixture_map.json", "source_map.json.gz"}


def run(command, *, cwd=None, timeout=60, log=None):
    if log is None:
        return subprocess.run(command, cwd=cwd, timeout=timeout, capture_output=True, check=True).stdout
    with log.open("wb") as stream:
        subprocess.run(command, cwd=cwd, timeout=timeout, stdout=stream, stderr=subprocess.STDOUT, check=True)


def meter(command):
    result = subprocess.run(command)
    root = Path("/sys/fs/cgroup")
    if (root / "cpu.stat").is_file():
        counters = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
        cpu_us = int(counters["usage_usec"])
        peak = root / "memory.peak"
    else:
        cpuacct, = root.glob("*/cpuacct.usage")
        cpu_us = int(cpuacct.read_text()) // 1000
        peak = root / "memory/memory.max_usage_in_bytes"
    metrics = {"cpu_us": cpu_us, "peak_memory_bytes": int(peak.read_text()) if peak.is_file() else None}
    print("PHASE04 " + json.dumps(metrics), file=sys.stderr, flush=True)
    return result.returncode


def clean_checkout(revision, output, map_hash):
    target = output / "checkout"
    run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(ROOT), str(target)])
    run(["git", "checkout", "--quiet", "--detach", revision], cwd=target)
    if run(["git", "rev-parse", "HEAD"], cwd=target).decode().strip() != revision:
        raise RuntimeError("Clean checkout did not resolve to the submission revision")
    if run(["git", "status", "--porcelain"], cwd=target):
        raise RuntimeError("Candidate checkout is not clean")
    if hashlib.sha256((target / "source_map.json.gz").read_bytes()).hexdigest() != map_hash:
        raise RuntimeError("Candidate checkout does not contain the verified source map")
    tracked = run(["git", "ls-files", "-z"], cwd=target).decode().split("\0")[:-1]
    file_bytes = sum((target / name).stat().st_size for name in tracked)
    git_bytes = sum(path.stat().st_size for path in (target / ".git").rglob("*") if path.is_file())
    if file_bytes + git_bytes > REPO_LIMIT:
        raise RuntimeError(f"Checkout and Git metadata: {file_bytes + git_bytes} bytes exceeds the repository limit")
    stats = {"tracked_bytes": file_bytes, "git_bytes": git_bytes, "total_bytes": file_bytes + git_bytes}
    return target, stats


def cold_build(checkout, output, builder, image):
    run(["docker", "buildx", "create", "--name", builder, "--driver", "docker-container",
         "--driver-opt", "memory=8g,memory-swap=8g,cpu-quota=400000,cpu-period=100000"])
    try:
        started = time.monotonic()
        run(["docker", "buildx", "inspect", "--bootstrap", builder], timeout=600, log=output / "builder.log")
        builder_config = json.loads(run(["docker", "inspect", f"buildx_buildkit_{builder}0"]))[0]["HostConfig"]
        limits = {field: builder_config[field] for field in ("Memory", "MemorySwap", "CpuQuota", "CpuPeriod")}
        if limits != {"Memory": BUILD_MEMORY, "MemorySwap": BUILD_MEMORY, "CpuQuota": 400000, "CpuPeriod": 100000}:
            raise RuntimeError(f"Builder did not apply the required limits: {limits}")
        run(["docker", "buildx", "build", "--builder", builder, "--platform", "linux/amd64",
             "--no-cache", "--pull", "--load", "--tag", image, "."],
            cwd=checkout, timeout=max(1, 600 - (time.monotonic() - started)), log=output / "build.log")
        seconds = time.monotonic() - started
        if seconds > 600:
            raise RuntimeError(f"Cold build exceeded ten minutes: {seconds:.3f} seconds")
        return seconds, limits
    finally:
        run(["docker", "buildx", "rm", builder])


def image_metadata(image, map_hash):
    info = json.loads(run(["docker", "image", "inspect", image]))[0]
    command = info["Config"]["Cmd"]
    if (info["Os"], info["Architecture"]) != ("linux", "amd64") or command != ["python", "/app/selector.py"]:
        raise RuntimeError("Wrong runtime platform or default command")
    probe = (
        "import hashlib,json,pathlib; app=pathlib.Path('/app'); "
        "print(json.dumps({'files': sorted(p.name for p in app.iterdir()), "
        "'map_sha256': hashlib.sha256((app/'source_map.json.gz').read_bytes()).hexdigest()}))"
    )
    observed = json.loads(run(["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
                               "--read-only", "--user", "65534:65534", image, "python", "-B", "-c", probe]))
    if set(observed["files"]) != APP_FILES or observed["map_sha256"] != map_hash:
        raise RuntimeError(f"Packaged image differs from the approved runtime files: {observed}")
    return info["Id"], command, observed


def replay(image, command, tag, commits, catalogue, output, timeout, measured=True):
    name = f"{image}-{tag}"
    flags = [
        "docker", "run", "--name", name, "--platform", "linux/amd64",
        "--network", "none", "--cgroupns", "private", "--cpus", "2",
        "--memory", "4096m", "--memory-swap", "4096m", "--pids-limit", "256",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--user", "65534:65534", "--env", "HOME=/tmp",
        "--volume", f"{commits}:/data/commits:ro", "--volume", f"{catalogue}:/data/tests.json:ro",
    ]
    if measured:
        flags.extend(["--volume", f"{Path(__file__).resolve()}:/harness/verify.py:ro",
                      image, "python", "/harness/verify.py", "--measure", *command])
    else:
        flags.append(image)
    try:
        started = time.monotonic()
        result = subprocess.run(flags, capture_output=True, timeout=timeout)
        wall_seconds = time.monotonic() - started
        (output / f"{tag}.jsonl").write_bytes(result.stdout)
        (output / f"{tag}.stderr").write_bytes(result.stderr)
        result.check_returncode()
        info = json.loads(run(["docker", "inspect", name]))[0]
        host = info["HostConfig"]
        limits = {
            "NetworkMode": "none", "NanoCpus": 2_000_000_000, "Memory": MEMORY_LIMIT,
            "MemorySwap": MEMORY_LIMIT, "PidsLimit": 256, "ReadonlyRootfs": True,
            "Tmpfs": {"/tmp": "rw,size=64m,mode=1777"},
        }
        for field, expected in limits.items():
            if host[field] != expected:
                raise RuntimeError(f"{tag}: runtime limit {field} differs: {host[field]}")
        if info["State"]["OOMKilled"] or info["Config"]["User"] != "65534:65534" or any(
            mount["RW"] for mount in info["Mounts"] if mount["Type"] == "bind"
        ):
            raise RuntimeError(f"{tag}: unexpected runtime state or mount permissions")
        if len(result.stdout) > STDOUT_LIMIT or wall_seconds > timeout:
            raise RuntimeError(f"{tag}: stdout or wall time exceeds the limit")
        metrics = {"wall_seconds": wall_seconds, "stdout_bytes": len(result.stdout)}
        if measured:
            probe = re.search(rb"^PHASE04 (\{.*\})\r?$", result.stderr, re.M)
            if not probe:
                raise RuntimeError(f"{tag}: runtime metrics are missing")
            metrics.update(json.loads(probe[1]))
            peak = metrics["peak_memory_bytes"]
            if peak is not None and peak > MEMORY_LIMIT:
                raise RuntimeError(f"{tag}: peak memory is above the limit")
        return result.stdout, metrics
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30)


def stress_inputs(sample, validation, output, source_ids, sample_answers, validation_answers):
    mixed, fallback = output / "stress-mixed", output / "stress-fallback"
    mixed.mkdir()
    fallback.mkdir()
    mixed_answers = dict(sample_answers)
    for path in sorted((sample / "commits").glob("*.patch")):
        (mixed / path.name).write_bytes(path.read_bytes())
    for index in range(15):
        source = source_ids[index % len(source_ids)]
        name = f"source-repeat-{index:02}"
        (mixed / f"{name}.patch").write_bytes((sample / "commits" / f"{source}.patch").read_bytes())
        mixed_answers[name] = sample_answers[source]
    import_patch = (validation / "commits" / "validation-import.patch").read_bytes()
    fallback_answers = {}
    for index in range(45):
        name = f"fallback-repeat-{index:02}"
        (fallback / f"{name}.patch").write_bytes(import_patch)
        fallback_answers[name] = validation_answers["validation-import"]
    return (mixed, mixed_answers), (fallback, fallback_answers)


def score_result(score, stdout, metrics, tests, answers):
    evaluation = score.evaluate_run(stdout, tests, answers)
    if not evaluation["ok"] or evaluation["missed_commits"]:
        raise RuntimeError(f"Sample scorer rejected the run or found misses: {evaluation}")
    metrics.update(evaluation)
    if "cpu_us" in metrics:
        metrics["total_us"] = score.run_total_microseconds(metrics["simulated_milliseconds"], metrics["cpu_us"])
    return metrics


def verify(revision):
    import run_phase02 as phase

    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise SystemExit("Supply the full 40-character candidate commit SHA")
    run_id = uuid.uuid4().hex[:10]
    output = ROOT / ".investigation" / "phase04" / run_id
    output.mkdir(parents=True)
    print("Verification evidence:", output, flush=True)
    map_hash = phase.INTEGRATED_MAP_SHA256
    checkout, repo_size = clean_checkout(revision, output, map_hash)
    run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=checkout, log=output / "unit-tests.log")
    image = f"blast-phase04-{run_id}"
    print("Building clean checkout", revision, flush=True)
    build_seconds, build_limits = cold_build(checkout, output, image, image)
    image_id, command, packaged = image_metadata(image, map_hash)
    score = phase.scorer()
    sample = checkout / "blast-radius-sample" / "sample"
    catalogue = sample / "tests.json"
    tests = phase.load_json(catalogue)["tests"]
    sample_answers = phase.load_json(sample / "answers.json")["commits"]
    validation_answers = {
        name: phase.load_json(phase.VALIDATION / f"{name}-labels.json") for name in phase.validation.CASES
    }
    phase.audit_labels(tests, validation_answers)
    if not all(record["complete"] for record in validation_answers.values()):
        raise RuntimeError("Independent validation labels are incomplete")
    phase03 = ROOT / ".investigation" / "phase03"
    expected_sample = (phase03 / "sample-integrated-1.jsonl").read_bytes()
    expected_validation = (phase03 / "validation-integrated-1.jsonl").read_bytes()
    print("Checking sample and validation parity", flush=True)
    sample_runs = []
    for index in range(1, 4):
        stdout, metrics = replay(image, command, f"sample-{index}", sample / "commits", catalogue, output, 180)
        if stdout != expected_sample:
            raise RuntimeError("Clean image failed Phase 03 sample schedule parity")
        sample_runs.append(score_result(score, stdout, metrics, tests, sample_answers))
    stdout, default = replay(image, command, "sample-unwrapped", sample / "commits", catalogue, output, 180,
                             measured=False)
    if stdout != expected_sample:
        raise RuntimeError("The unwrapped default command produced a different schedule")
    score_result(score, stdout, default, tests, sample_answers)
    stdout, validation = replay(image, command, "validation", phase.VALIDATION / "commits", catalogue, output, 180)
    if stdout != expected_validation:
        raise RuntimeError("Clean image failed Phase 03 validation schedule parity")
    score_result(score, stdout, validation, tests, validation_answers)
    previous = phase.load_json(phase03 / "benchmark-sample.json")["modes"]
    source_ids = sorted(set(previous["integrated"]["runs"][0]["narrowed"])
                        - set(previous["phase01"]["runs"][0]["narrowed"]))
    batches = stress_inputs(sample, phase.VALIDATION, output, source_ids, sample_answers, validation_answers)
    stress = {}
    print("Checking both 45-patch resource batches", flush=True)
    for name, (commits, answers) in zip(("mixed", "fallback"), batches):
        if len(answers) != 45:
            raise RuntimeError("Stress batch does not contain exactly 45 patch IDs")
        stdout, metrics = replay(image, command, f"stress-{name}", commits, catalogue, output, 270)
        stress[name] = score_result(score, stdout, metrics, tests, answers)
        if name == "fallback":
            expected = {test["number"] for test in tests}
            for row in map(json.loads, stdout.splitlines()):
                if {number for worker in row["workers"] for number in worker} != expected:
                    raise RuntimeError("An import-error stress patch did not fall back to all tests")
    median = int(statistics.median(result["total_us"] for result in sample_runs))
    report = {
        "candidate": revision, "image_id": image_id, "runtime": packaged, "repository": repo_size,
        "build_seconds": build_seconds, "build_limits": build_limits, "sample_runs": sample_runs,
        "sample_median_us": median, "sample_score": ((median + 50_000) // 100_000) / 10,
        "unwrapped": default, "validation": validation, "stress": stress,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--measure"]:
        sys.exit(meter(sys.argv[2:]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    verify(parser.parse_args().revision)
