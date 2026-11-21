# Blast Radius Hackathon Rules

## Objective

For each independent code change to the Python SQL parser sqlglot, select the tests to run and distribute them across up to eight workers. Some changes break no tests; selecting no tests is valid. Lower simulated CI time is better.

Every patch applies independently to sqlglot commit `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. A change that only adds a comment is not guaranteed to be harmless.

## Getting started

- Download `blast-radius-sample.tar.gz` and unpack it into an empty folder; the archive has no top-level folder.
- Install Docker, make, and Python 3.9 or newer.
- Run `make sample` to build the starter image, run it under the stated limits on 30 sample commits, and score its output.
- Consult `SCORING.md` for the exact scoring rules. It is also included in the starter archive.

## Submission

- Submit a public GitHub repository with a `Dockerfile` at its root, and identify the commit to score.
- Any language, libraries, and amount of AI are allowed.
- Keep the repository public, including every submitted commit, until results are published. An entry that cannot be fetched or restored for the final scores nothing.
- The repository may contain at most 20 MB. Git submodules and Git LFS files are not fetched. Clone sqlglot in the Dockerfile and commit maps as plain files.

## Input and output contract

- `/data/commits/<id>.patch` contains one unified diff for each commit.
- `/data/tests.json` lists every test by number, file path, and recorded runtime in seconds.
- Print exactly one JSON line per commit to stdout, for example:

  ```json
  {"commit":"k7q2","workers":[[12,845,901],[3,77]]}
  ```

- Each inner array is a worker's test numbers. `"workers": []` runs nothing.
- Use at most eight workers per commit, do not repeat a test within a commit, and use only test numbers from `tests.json`.
- Send logs to stderr. Any other stdout output or more than 2 MB of stdout rejects the run.

## Scoring

For each commit, the cost is the recorded test seconds of its busiest worker, plus two seconds per worker. Running nothing costs zero. If the selection omits one or more tests that fail on that commit, add 300 seconds once for that commit. Add the program's CPU seconds across the batch; running sqlglot tests while deciding is allowed and charged as program CPU time.

The image runs three times, and the middle total counts, rounded to 0.1 seconds. The starter baseline is **1614.1 seconds**, running every test across three workers. The scorer version is `blast-radius-1`.

A test fails when pytest reports a failure, error, or timeout for it, or when its file cannot be imported. A test with subtests counts as one test; any failing subtest fails it.

The reported score includes each run's simulated seconds, CPU seconds, and number of missed commits, but does not identify the missed commits. Practice and final runs do not reveal the program's output; debug locally using `make sample`.

Equal scores rank the earlier submission first. In the final, entries at most one second behind the best score tie and rank by submission time; remaining entries are grouped in the same way starting from the next best score. First place wins.

## Build and runtime limits

### Build

- Network access, four cores, 8 GB memory, and 10 minutes.
- Installing sqlglot and running its tests to build coverage or import maps is allowed.
- Every submission is built from scratch. A map generated once and committed can avoid repeating a lengthy test run during each build.
- Downloads are limited to public package registries (PyPI, npm, Docker Hub), GitHub releases at a fixed tag, and sqlglot at commit `eb11aec`. Do not download from an address controlled by the team; final images are rebuilt after the cutoff.

### Run

- No network access; two cores; 4 GB memory.
- Three minutes for the whole batch; 4.5 minutes in the final, which has about 1.5 times as many commits.
- Runs as user `nobody`, with `HOME=/tmp`, a read-only disk, an initially empty 64 MB `/tmp`, and at most 256 processes.

A broken rule, crash, timeout, memory limit overrun, or failed build rejects the submission with a reason and does not change the team's best score.

## Competition restrictions

- One team per person; use your own team's repository. Do not share code between teams. Top entries are compared, and entrants may be asked to explain their work. If two teams submit the same repository, commit, or archive, the later submission is disqualified.
- Do not look up answers worked out ahead of time by patch. Tables mapping a patch or kind of edit to the tests it breaks are prohibited. Maps built from the pinned base commit, such as coverage, import, or fixture maps, are allowed. Top entries are reviewed.
- Teams may initially submit once per hour; the limit may be raised if the queue stays short.
- Only the final counts; the practice board carries no prize.
- If a commit is found to be mislabeled before results are published, it is corrected for every team.

## Final

At the cutoff, the selected commit (the team's best unless another is chosen) is scored on unseen changes, including kinds of change absent from practice. At least the top five entries are then rescored on the same commits, five runs each, one at a time on one idle machine. The middle total replaces their first final score.

**Cutoff: Monday, 12:00 AM GMT+8.**
