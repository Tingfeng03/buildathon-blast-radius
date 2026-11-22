"""Build and score the submission image on the organizer's sample."""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sample = root / "blast-radius-sample" / "sample"
parser = argparse.ArgumentParser()
modes = parser.add_mutually_exclusive_group()
modes.add_argument("--all-tests", action="store_true")
modes.add_argument("--fixture-only", action="store_true")
args = parser.parse_args()
image = "blast-radius-sample-run"
subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", image, str(root)], check=True)
command = [
    "docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none",
    "--cpus", "2", "--memory", "4096m", "--memory-swap", "4096m",
    "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp:rw,size=64m,mode=1777",
    "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
    "--env", "HOME=/tmp",
    "--volume", f"{sample / 'commits'}:/data/commits:ro",
    "--volume", f"{sample / 'tests.json'}:/data/tests.json:ro",
    image,
]
if args.all_tests or args.fixture_only:
    flag = "--all-tests" if args.all_tests else "--fixture-only"
    command.extend(["python", "/app/selector.py", flag])
with tempfile.TemporaryDirectory() as directory:
    output = Path(directory) / "output.jsonl"
    with output.open("wb") as stream:
        subprocess.run(command, stdout=stream, check=True, timeout=180)
    subprocess.run([sys.executable, str(root / "blast-radius-sample" / "score.py"),
                    str(sample), str(sample / "answers.json"), str(output)], check=True)
