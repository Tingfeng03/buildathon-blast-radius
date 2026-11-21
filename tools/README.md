# Fixture map regeneration

The collector records fixture opens during pytest test calls on the pinned checkout. It excludes a fixture if an open was observed outside a test call. It records observed dependencies, which do not guarantee coverage of all possible behavior on a patched checkout.

Build the analysis image from the starter's pinned base with `requirements.lock` installed. From the workspace root in PowerShell, run:

```powershell
$base = (Get-Content 'blast-radius-sample/Dockerfile' | Where-Object { $_ -like 'FROM *' })
$analysisDockerfile = "$base`nCOPY requirements.lock /tmp/requirements.lock`nRUN python -m pip install --no-cache-dir -r /tmp/requirements.lock`n"
$analysisDockerfile | docker build --platform linux/amd64 -t blast-radius-analysis-investigation -f - blast-radius-sample
```

Mount the clean, detached pinned sqlglot checkout at `/src:ro`, this project's `tools` at `/tools:ro`, and an output directory at `/evidence`. Set `PYTHONPATH=/src` and `SKIP_INTEGRATION=0`, then run `python /tools/collect_fixtures.py` from `/src`. Copy the generated `fixture_map.json` to the project root and rerun both sample modes.

For the existing local investigation image, PowerShell commands are:

```powershell
$scratch = (Resolve-Path '.investigation').Path
$toolsPath = (Resolve-Path 'tools').Path
docker run --rm --platform linux/amd64 --network none --cpus 4 --memory 8192m --env PYTHONPATH=/src --env SKIP_INTEGRATION=0 --volume "${scratch}/sqlglot:/src:ro" --volume "${scratch}:/evidence" --volume "${toolsPath}:/tools:ro" --workdir /src blast-radius-analysis-investigation python /tools/collect_fixtures.py
Copy-Item .investigation/fixture_map.json fixture_map.json
```

The checkout must be clean and detached at `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. The collector checks the detached HEAD. The developer is responsible for confirming the worktree is clean.
