"""Collect fixture opens during test calls on the pinned sqlglot checkout."""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import pytest

BASE = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
root = Path("/src")
output = Path("/evidence/fixture_map.json")


class Collector:
    def __init__(self):
        self.current = ""
        self.ids = []
        self.readers = defaultdict(set)
        self.outside = set()

    def pytest_collection_finish(self, session):
        self.ids = sorted(item.nodeid for item in session.items)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_call(self, item):
        self.current = item.nodeid
        try:
            return (yield)
        finally:
            self.current = ""

    def audit(self, event, args):
        if event != "open" or not isinstance(args[0], str):
            return
        name = os.path.abspath(args[0])
        prefix = "/src/"
        if not name.startswith(prefix):
            return
        path = name[len(prefix):]
        if not re.fullmatch(r"tests/fixtures/optimizer/[A-Za-z0-9_.-]+\.sql", path):
            return
        if self.current:
            self.readers[path].add(self.current)
        else:
            self.outside.add(path)


def main():
    commit = (root / ".git" / "HEAD").read_text().strip()
    if commit != BASE or os.environ.get("SKIP_INTEGRATION") != "0":
        raise SystemExit("Expected pinned checkout and SKIP_INTEGRATION=0")
    collector = Collector()
    sys.addaudithook(collector.audit)
    status = pytest.main(["-q", "-p", "no:cacheprovider", "tests"], plugins=[collector])
    if status:
        raise SystemExit(status)
    result = {
        "base_commit": BASE,
        "reference_ids": collector.ids,
        "fixtures": {path: sorted(readers) for path, readers in sorted(collector.readers.items())
                     if path not in collector.outside},
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(result['fixtures'])} fixture paths")


if __name__ == "__main__":
    main()
