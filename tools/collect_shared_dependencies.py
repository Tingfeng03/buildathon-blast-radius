"""Generate the Phase 9 test and fixture dependency map from pinned sqlglot."""

import argparse
import ast
import gzip
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from phase02.evidence import import_edges, module_name
from phase09.sitecustomize import fixture_path

BASE = "eb11aec4be8cb2122afe713a4816662c3f0fb2fa"
ROOT = Path("/src")


class FixtureReads:
    def __init__(self):
        self.owners = {}
        self.active = set()
        self.readers = defaultdict(set)
        self.unresolved = set()

    def pytest_collection_finish(self, session):
        for item in session.items:
            for node in item.listchain():
                self.owners.setdefault(node, set()).add(item.nodeid)

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_call(self, item):
        self.active = {item.nodeid}
        try:
            return (yield)
        finally:
            self.active = set()

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_fixture_setup(self, fixturedef, request):
        previous = self.active
        self.active = self.owners.get(request.node, set())
        try:
            return (yield)
        finally:
            self.active = previous

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_teardown(self, item, nextitem):
        remaining = set(nextitem.listchain()) if nextitem else set()
        departing = next(node for node in item.listchain() if node not in remaining)
        self.active = self.owners[departing]
        try:
            return (yield)
        finally:
            self.active = set()

    def audit(self, event, args):
        if event != "open" or not (path := fixture_path(args[0])):
            return
        if self.active:
            self.readers[path].update(self.active)
        else:
            self.unresolved.add(path)


def test_modules(ids, root):
    sources = {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
               for p in sorted((root / "tests").rglob("*.py"))}
    modules = {module_name(path): path for path in sources}
    graph = {}
    for name, path in modules.items():
        deps = import_edges(path, ast.parse(sources[path]), modules)
        for module in deps | {name}:
            parts = module.split(".")
            deps.update(".".join(parts[:i]) for i in range(1, len(parts)))
        graph[name] = deps.intersection(modules)
    readers = defaultdict(set)
    for node in sorted(ids):
        pending = [module_name(node.split("::", 1)[0])]
        visited = set()
        while pending:
            module = pending.pop()
            if module not in visited:
                visited.add(module)
                readers[module].add(node)
                pending.extend(graph[module] - visited)
    return {
        path: {"source": sources[path], "readers": sorted(readers[module])}
        for module, path in modules.items() if readers[module] and Path(path).name not in {"__init__.py", "conftest.py"}
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    revision = (ROOT / ".git/HEAD").read_text(encoding="utf-8").strip()
    if revision.startswith("ref: "):
        revision = (ROOT / ".git" / revision.removeprefix("ref: ")).read_text(encoding="utf-8").strip()
    if revision != BASE or os.environ.get("SKIP_INTEGRATION") != "0":
        raise SystemExit("Expected pinned checkout and SKIP_INTEGRATION=0")
    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    ids = {test["id"] for test in catalogue["tests"]}
    collector = FixtureReads()
    sys.addaudithook(collector.audit)
    os.chdir(ROOT)
    with TemporaryDirectory() as temporary:
        child_opens = Path(temporary) / "fixture-paths"
        os.environ["BLAST_RADIUS_CHILD_OPENS"] = str(child_opens)
        try:
            status = pytest.main(["-q", "-p", "no:cacheprovider", "tests"], plugins=[collector])
        finally:
            del os.environ["BLAST_RADIUS_CHILD_OPENS"]
        if child_opens.exists():
            collector.unresolved.update(child_opens.read_text(encoding="utf-8").splitlines())
    session_ids = {node.nodeid for node in collector.owners if isinstance(node, pytest.Item)}
    if status or session_ids != ids.union(catalogue.get("skipped", ())):
        raise SystemExit("Pinned suite failed or its collected IDs differ from the catalogue")
    result = {
        "base_commit": BASE,
        "reference_ids": sorted(session_ids),
        "fixtures": {path: sorted(readers) for path, readers in sorted(collector.readers.items())
                     if path not in collector.unresolved and path.endswith((".sql", ".json"))},
        "test_modules": test_modules(session_ids, ROOT),
    }
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    args.output.write_bytes(gzip.compress(payload, mtime=0))
    print(f"Recorded {len(result['fixtures'])} fixtures and {len(result['test_modules'])} test modules")
    print(f"Unresolved fixture paths: {sorted(collector.unresolved)}")


if __name__ == "__main__":
    main()
