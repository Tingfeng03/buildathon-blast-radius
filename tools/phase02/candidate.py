"""Replay experimental selection policies. This module is not shipped."""

import gzip
import json
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import selector

HEADER = re.compile(r"diff --git a/(sqlglot/[\w./-]+\.py) b/\1", re.ASCII)
INDEX = re.compile(r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100644)?")
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*", re.ASCII)
UNSAFE = re.compile(r"^\s*(?:@|(?:async\s+)?def\s|class\s|from\s|import\s|global\s|nonlocal\s)|\b(?:__import__|importlib)\b")
SETTING = re.compile(r"\s*([A-Z][A-Z0-9_]+)\s*=\s*[\w.+'\" -]+")


def patched_files(patch, files):
    """Accept ordinary in-place Git patches and verify them against the base text."""
    lines = patch.split("\n")
    if lines[-1] == "":
        lines.pop()
    index = 0
    seen = set()
    while index < len(lines):
        header = HEADER.fullmatch(lines[index])
        if not header or header[1] not in files or header[1] in seen:
            raise ValueError("Unsupported path")
        path = header[1]
        seen.add(path)
        info = files[path]
        original = info["source"].split("\n")
        index += 1
        if index < len(lines) and INDEX.fullmatch(lines[index]):
            index += 1
        if lines[index:index + 2] != [f"--- a/{path}", f"+++ b/{path}"]:
            raise ValueError("Unsupported file operation")
        index += 2
        result, edits, cursor = [], [], 0
        while index < len(lines) and not lines[index].startswith("diff --git "):
            hunk = HUNK.fullmatch(lines[index])
            if not hunk:
                raise ValueError("Unsupported hunk")
            old_size, new_size = int(hunk[2] or 1), int(hunk[4] or 1)
            start = int(hunk[1]) - bool(old_size)
            new_start = int(hunk[3]) - bool(new_size)
            if not cursor <= start <= len(original):
                raise ValueError("Invalid base offset")
            result.extend(original[cursor:start])
            if new_start != len(result):
                raise ValueError("Invalid output offset")
            cursor = start
            index += 1
            removed, added = [], []
            anchor = cursor
            while old_size or new_size:
                line = lines[index]
                index += 1
                kind, content = line[:1], line[1:]
                if kind not in (" ", "-", "+"):
                    raise ValueError("Invalid hunk content")
                if kind == " ":
                    if removed or added:
                        edits.append((anchor, removed, added))
                        removed, added = [], []
                    anchor = cursor + 1
                if kind != "+":
                    if not old_size or original[cursor] != content:
                        raise ValueError("Hunk does not match the base")
                    cursor += 1
                    old_size -= 1
                if kind != "-":
                    if not new_size:
                        raise ValueError("Invalid output line count")
                    result.append(content)
                    new_size -= 1
                if kind == "-":
                    removed.append(content)
                elif kind == "+":
                    added.append(content)
            if removed or added:
                edits.append((anchor, removed, added))
        if not edits:
            raise ValueError("No edits")
        result.extend(original[cursor:])
        compile("\n".join(result), path, "exec")
        yield info, edits


def select_source(patch, evidence, by_id):
    readers = set()
    try:
        for info, edits in patched_files(patch, evidence["files"]):
            for anchor, removed, added in edits:
                if any(UNSAFE.search(line) for line in removed + added):
                    return None
                change_readers = readers_for_edit(info, anchor, removed, added)
                if not change_readers:
                    return None
                readers.update(change_readers)
            readers.update(info.get("importers", ()))
    except (IndexError, ValueError, SyntaxError, OverflowError):
        return None
    if not readers or not readers.issubset(by_id):
        return None
    return [by_id[node] for node in sorted(readers)]


def readers_for_edit(info, anchor, removed, added):
    settings = info.get("settings", {})
    setting = settings.get(str(anchor + 1))
    if setting and len(removed) == len(added) == 1:
        before, after = SETTING.fullmatch(removed[0]), SETTING.fullmatch(added[0])
        if before and after and before[1] == after[1] == setting[0]:
            return setting[1]
    candidates = []
    for start, end, indent, ids in info["functions"]:
        if not start <= anchor + 1 <= end or anchor + len(removed) > end:
            continue
        if any(line.strip() and (len(line) - len(line.lstrip(" ")) < indent) for line in added):
            continue
        candidates.append((end - start, ids))
    return min(candidates, default=(0, []), key=lambda item: item[0])[1]


def main():
    data = Path("/data")
    tests = json.loads((data / "tests.json").read_text(encoding="utf-8"))["tests"]
    for test in tests:
        test["ms"] = int((Decimal(str(test["seconds"])) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    by_id = {test["id"]: test for test in tests}
    fixtures = selector.load_map(Path("/app/fixture_map.json"), tests)
    with gzip.open(sys.argv[1], "rt", encoding="utf-8") as stream:
        evidence = json.load(stream)
    if evidence["base_commit"] != selector.BASE or not set(by_id).issubset(evidence["reference_ids"]):
        evidence = {"files": {}}
    fallback = selector.schedule(tests)
    for path in sorted((data / "commits").glob("*.patch")):
        picked = None
        try:
            patch = path.read_text(encoding="utf-8")
            picked = selector.select(patch, fixtures, by_id)
            if picked is None:
                picked = select_source(patch, evidence, by_id)
        except (OSError, UnicodeError):
            pass
        workers = fallback if picked is None else selector.schedule(picked)
        print(json.dumps({"commit": path.stem, "workers": workers}, separators=(",", ":")))


if __name__ == "__main__":
    main()
