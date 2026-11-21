"""Measure test dependencies on the unmodified sqlglot checkout."""

import gzip
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import coverage
import pytest


ROOT = Path("/src")
OUTPUT = Path("/evidence")


class TestDependencies:
    def __init__(self, cov):
        self.cov = cov
        self.context = ""
        self.nodeids = []
        self.fixtures = defaultdict(set)

    def pytest_collection_finish(self, session):
        self.nodeids = [item.nodeid for item in session.items]

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item):
        self.context = item.nodeid
        self.cov.switch_context(self.context)
        try:
            return (yield)
        finally:
            self.context = ""
            self.cov.switch_context("")

    def audit(self, event, args):
        if event != "open" or not isinstance(args[0], str):
            return
        path = args[0]
        if "/fixtures/" not in path and not path.startswith("tests/fixtures/"):
            return
        path = os.path.abspath(path)
        prefix = f"{ROOT}/tests/fixtures/"
        if path.startswith(prefix):
            self.fixtures[path.removeprefix(f"{ROOT}/")].add(self.context)


def main():
    cov = coverage.Coverage(
        config_file=False,
        include=[f"{ROOT}/sqlglot/*"],
        data_file=None,
    )
    dependencies = TestDependencies(cov)
    sys.addaudithook(dependencies.audit)
    start = time.monotonic()
    cov.start()
    try:
        status = pytest.main(["-q", "-p", "no:cacheprovider", "tests"], plugins=[dependencies])
    finally:
        cov.stop()
    test_wall = time.monotonic() - start

    # Store test IDs once. Integers inside this file refer to this ID list.
    nodeids = sorted(dependencies.nodeids)
    positions = {nodeid: index for index, nodeid in enumerate(nodeids)}
    positions[""] = -1
    data = cov.get_data()
    sources = {}
    for filename in sorted(data.measured_files()):
        lines = data.contexts_by_lineno(filename)
        sources[filename.removeprefix(f"{ROOT}/")] = {
            line: sorted(positions[context] for context in contexts)
            for line, contexts in sorted(lines.items())
        }
    fixtures = {
        path: sorted(positions[context] for context in contexts)
        for path, contexts in sorted(dependencies.fixtures.items())
    }
    result = {
        "coverage_version": coverage.__version__,
        "pytest_status": int(status),
        "test_wall_seconds": test_wall,
        "nodeids": nodeids,
        "sources": sources,
        "fixtures": fixtures,
    }
    payload = json.dumps(result, separators=(",", ":")).encode()
    compressed = gzip.compress(payload, mtime=0)
    (OUTPUT / "dependencies.json.gz").write_bytes(compressed)
    print(f"Coverage {coverage.__version__}, pytest exit {status}, {test_wall:.1f} s wall")
    print(f"{len(payload):,} bytes JSON, {len(compressed):,} bytes gzipped")
    return status


if __name__ == "__main__":
    sys.exit(main())
