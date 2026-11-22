"""Benchmark-only probe for edits to observed fixtures and numbered test files."""

import json
import re
from pathlib import Path


def file_selector(base_select, fixture_readers):
    def select(patch, fixtures, source_map, by_id, reasons=None, skipped=()):
        picked = base_select(patch, fixtures, source_map, by_id, reasons, skipped)
        if picked is not None:
            return picked
        selected = {}
        local_reasons = set()
        for part in re.split(r"\n(?=diff --git )", patch):
            header = re.match(r"diff --git a/([^\n ]+) b/\1\n(?:index [^\n]+\n)?--- a/\1\n\+\+\+ b/\1\n@@ ", part)
            if not header:
                return None
            path = header[1]
            if path in fixture_readers:
                ids = set(fixture_readers[path]).difference(skipped)
                if not ids or not ids.issubset(by_id):
                    return None
                selected.update((test_id, by_id[test_id]) for test_id in ids)
                local_reasons.add("observed fixture file")
                continue
            direct = [test for test in by_id.values() if test["file"] == path]
            if direct:
                selected.update((test["id"], test) for test in direct)
                local_reasons.add("catalogued test file")
                continue
            readers = base_select(part, fixtures, source_map, by_id, local_reasons, skipped)
            if readers is None:
                return None
            selected.update((test["id"], test) for test in readers)
        if reasons is not None:
            reasons.clear()
            reasons.update(local_reasons)
        return list(selected.values())
    return select


if __name__ == "__main__":
    import phase07_selector

    fixture_readers = json.loads(Path("/app/fixture_probe.json").read_text(encoding="utf-8"))
    phase07_selector.select_patch = file_selector(phase07_selector.select_patch, fixture_readers)
    phase07_selector.main()
