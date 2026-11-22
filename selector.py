"""Select tests for independent sqlglot patches."""
import argparse
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from source_selector import load_source_map, select_source

BASE = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")
HEADER = re.compile(r"^diff --git a/(tests/fixtures/optimizer/[A-Za-z0-9_.-]+\.sql) b/\1$")


def schedule(tests):
    ordered = sorted(tests, key=lambda t: (-t["ms"], t["number"]))
    candidates = []
    for count in range(1, min(8, len(ordered)) + 1):
        workers = [[] for _ in range(count)]
        loads = [0] * count
        for test in ordered:
            index = loads.index(min(loads))
            workers[index].append(test["number"])
            loads[index] += test["ms"]
        candidates.append((max(loads) + 2000 * count, count, workers))
    return min(candidates, default=(0, 0, []))[2]


''' kinda like detecting which file was changed '''
def changed_fixtures(patch):
    lines = patch.splitlines()
    paths = []
    i = 0
    while i < len(lines):
        match = HEADER.fullmatch(lines[i])
        if not match:
            return None
        path = match.group(1)
        paths.append(path)
        i += 1
        if i < len(lines) and lines[i].startswith("index "):
            if not re.fullmatch(r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100644)?", lines[i]):
                return None
            i += 1
        if lines[i:i+2] != ["--- a/" + path, "+++ b/" + path]:
            return None
        i += 2
        hunks = 0
        while i < len(lines) and not lines[i].startswith("diff --git "):
            match = HUNK.fullmatch(lines[i])
            if not match:
                return None
            old = int(match.group(2) or "1")
            new = int(match.group(4) or "1")
            i += 1
            while i < len(lines) and not lines[i].startswith(("@@ ", "diff --git ")):
                line = lines[i]
                if line == r"\ No newline at end of file":
                    i += 1
                    continue
                if not line or line[0] not in " +-":
                    return None
                old -= line[0] in " -"
                new -= line[0] in " +"
                if old < 0 or new < 0:
                    return None
                i += 1
            if old or new:
                return None
            hunks += 1
        if not hunks:
            return None
    return paths or None


def load_map(path, tests):
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        ids = {t["id"] for t in tests}
        if data["base_commit"] != BASE or not ids.issubset(set(data["reference_ids"])):
            return {}
        fixtures = data["fixtures"]
        if not isinstance(fixtures, dict):
            return {}
        for path, readers in fixtures.items():
            if not HEADER.fullmatch(f"diff --git a/{path} b/{path}") or not isinstance(readers, list) or not readers or not all(isinstance(r, str) for r in readers):
                return {}
        return fixtures
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def select(patch, fixtures, by_id):
    paths = changed_fixtures(patch)
    if not paths or any(path not in fixtures for path in paths):
        return None
    readers = {reader for path in paths for reader in fixtures[path]}
    if not readers.issubset(by_id):
        return None
    return [by_id[reader] for reader in sorted(readers)]


def select_patch(patch, fixtures, source_map, by_id):
    try:
        picked = select(patch, fixtures, by_id)
    except ValueError:
        return None
    if picked is None and source_map is not None:
        picked = select_source(patch, source_map, by_id)
    return picked


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--all-tests", action="store_true")
    modes.add_argument("--fixture-only", action="store_true")
    args = parser.parse_args()
    data = Path("/data")
    # Load the complete catalogue.
    tests = json.loads((data / "tests.json").read_text(encoding="utf-8"))["tests"]
    for test in tests:
        test["ms"] = int((Decimal(str(test["seconds"])) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    by_id = {test["id"]: test for test in tests}
    fixtures = {} if args.all_tests else load_map(Path("/app/fixture_map.json"), tests)
    source_map = None
    if not (args.all_tests or args.fixture_only):
        source_map = load_source_map(Path("/app/source_map.json.gz"), BASE, by_id)
    # full test as fallback
    fallback = schedule(tests)
    for patch in sorted((data / "commits").glob("*.patch")):
        try:
            selected = None if args.all_tests else select_patch(
                patch.read_text(encoding="utf-8"), fixtures, source_map, by_id,
            )
        except (OSError, UnicodeError):
            selected = None
        # use fallback(everything) if no test were selected
        workers = fallback if selected is None else schedule(selected)
        print(json.dumps({"commit": patch.stem, "workers": workers}, separators=(",", ":")))


if __name__ == "__main__":
    main()
