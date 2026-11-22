"""Select tests for supported edits using pinned source evidence."""

import gzip
import json
import re
import zlib

SOURCE_PATH = r"sqlglot/[\w./-]+\.py"
HEADER = re.compile(rf"diff --git a/({SOURCE_PATH}) b/\1", re.ASCII)
INDEX = re.compile(r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100644)?")
HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*", re.ASCII)
UNSAFE = re.compile(r"^\s*(?:@|(?:async\s+)?def\s|class\s|from\s|import\s|global\s|nonlocal\s)|\b(?:__import__|importlib)\b")
SETTING = re.compile(r"\s*([A-Z][A-Z0-9_]+)\s*=\s*[\w.+'\" -]+")


def valid_readers(readers, reference_ids):
    return isinstance(readers, list) and all(
        isinstance(reader, str) and reader in reference_ids for reader in readers
    )


def valid_file(info, reference_ids):
    if not isinstance(info, dict) or not isinstance(info.get("source"), str):
        return False
    functions = info.get("functions")
    settings = info.get("settings", {})
    if not isinstance(functions, list) or not isinstance(settings, dict):
        return False
    for function in functions:
        if not isinstance(function, list) or len(function) != 4:
            return False
        start, end, indent, readers = function
        if not (
            all(type(value) is int for value in (start, end, indent))
            and 1 <= start <= end and indent > 0
            and valid_readers(readers, reference_ids)
        ):
            return False
    for line, setting in settings.items():
        if not (
            line.isascii() and line.isdecimal() and not line.startswith("0")
            and isinstance(setting, list) and len(setting) == 2
            and isinstance(setting[0], str) and valid_readers(setting[1], reference_ids)
        ):
            return False
    return valid_readers(info.get("importers", []), reference_ids)


def load_source_map(path, base_commit, by_id):
    """Disable source selection when the packaged evidence cannot be trusted."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            evidence = json.load(stream)
    except (OSError, EOFError, ValueError, RecursionError, zlib.error):
        return None
    if not isinstance(evidence, dict) or evidence.get("base_commit") != base_commit:
        return None
    references = evidence.get("reference_ids")
    if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
        return None
    reference_ids = set(references)
    files = evidence.get("files")
    if not isinstance(files, dict) or not reference_ids.issuperset(by_id):
        return None
    if not all(
        re.fullmatch(SOURCE_PATH, path, re.ASCII) and valid_file(info, reference_ids)
        for path, info in files.items()
    ):
        return None
    return evidence


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
    except (IndexError, ValueError, SyntaxError, OverflowError, RecursionError):
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

