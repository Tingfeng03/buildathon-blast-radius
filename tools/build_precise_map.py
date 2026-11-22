"""Build compact reader groups from the pinned checkout and successful base traces."""

import ast
import gzip
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from phase02.evidence import attribute_reads, merge, module_name, read_traces

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from selector import BASE


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def closure_factories(trees):
    """A call to a factory of this shape only binds its arguments in a closure."""
    factories = set()
    for path, tree in trees.items():
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef) or fn.decorator_list or len(fn.body) != 2:
                continue
            nested, result = fn.body
            if (isinstance(nested, ast.FunctionDef) and not nested.decorator_list
                    and not nested.args.defaults and not any(nested.args.kw_defaults)
                    and isinstance(result, ast.Return) and isinstance(result.value, ast.Name)
                    and result.value.id == nested.name):
                factories.add((module_name(path), fn.name))
    names = defaultdict(set)
    for path, tree in trees.items():
        names[path].update(name for mod, name in factories if mod == module_name(path))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and not node.level:
                names[path].update(a.asname or a.name for a in node.names if (node.module, a.name) in factories)
    return names


def direct_class_reads(base, ids, classes):
    """Attribute reads on a named class can occur without constructing an instance."""
    by_name, by_file = defaultdict(set), defaultdict(set)
    for cls in classes:
        by_name[cls.rsplit(".", 1)[-1]].add(cls)
    for nodeid in ids:
        by_file[nodeid.split("::")[0]].add(nodeid)
    readers = defaultdict(set)
    for path, file_tests in by_file.items():
        tree = ast.parse((base / path).read_text(encoding="utf-8"))
        functions = [(n.lineno, n.end_lineno, n.name) for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            receiver = node.value
            short = getattr(receiver, "id", None) or getattr(receiver, "attr", None)
            if short not in by_name:
                continue
            names = {name for start, end, name in functions if start <= node.lineno <= end}
            tests = {i for i in file_tests if i.rsplit("::", 1)[-1].split("[")[0] in names}
            for cls in by_name[short]:
                readers[f"{cls}.{node.attr}"].update(tests or file_tests)
    return readers


def base_traces(scratch):
    ids, parent, workers, optimizer = read_traces(scratch, scratch / "phase02/workers")
    pool_tests = set(optimizer["submitted_ids"])
    # A child can serialize a returned value after traced_call has finished.
    # Charge unscoped child lines to the pool's callers. Parent import-time
    # evidence retains its unknown-context marker.
    for coverage in workers.values():
        for readers in coverage.values():
            if "" in readers:
                readers.remove("")
                readers.update(pool_tests)
    lines = merge(parent, workers)
    executor = scratch / "phase05/executor-lines"
    run = read(executor / "executor-run.json")
    started = set()
    for part in executor.glob("tasks-*.json"):
        if not (executor / part.name.replace("tasks-", "worker-")).is_file():
            raise ValueError("A worker did not export its coverage")
        started.update(read(part))
    for part in executor.glob("worker-*.json"):
        for path, coverage in read(part)["sources"].items():
            for line, tests in coverage.items():
                readers = set(tests)
                if "" in readers:
                    readers.remove("")
                    readers.update(run["submitted_ids"])
                lines.setdefault(path, {}).setdefault(int(line), set()).update(readers)
    if run["status"] or not started or set(run["submitted_ids"]) != started:
        raise ValueError("Incomplete executor trace")
    pool_tests.update(run["submitted_ids"])
    return ids, lines, pool_tests


def profile_data(profile):
    if read(profile / "profile-run.json")["status"]:
        raise ValueError("Incomplete base profile")
    classes, sites, reads = defaultdict(set), defaultdict(lambda: defaultdict(set)), defaultdict(set)
    for part in profile.glob("profile-[0-9]*.json"):
        data = read(part)
        for key, tests in data["classes"].items():
            classes[key].update(tests)
        for key, tests in data["sources"].items():
            reads[key].update(tests)
        for site, pairs in data["sites"].items():
            for pair, tests in pairs.items():
                sites[site][pair].update(tests)
    if not classes or not sites:
        raise ValueError("Missing runtime observations")
    return classes, sites, reads


def make_map(base, ids, lines, pool_tests, classes, sites, reads):
    sources = {p.relative_to(base).as_posix(): p.read_text(encoding="utf-8")
               for p in sorted((base / "sqlglot").rglob("*.py"))}
    trees = {p: ast.parse(src) for p, src in sources.items()}
    attributes = attribute_reads(trees, lines)
    factories = closure_factories(trees)
    static_reads = direct_class_reads(base, ids, classes)
    # Queue serialization can execute between pytest contexts. Link the modules imported
    # by pickle hooks to every test that submitted a task in either pool.
    pickle_modules = set()
    for tree in trees.values():
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef) and fn.name in ("__reduce__", "__reduce_ex__"):
                pickle_modules.update(n.module for n in ast.walk(fn) if isinstance(n, ast.ImportFrom))

    positions = {test: i for i, test in enumerate(ids)}
    positions[""] = -1
    groups = {}
    def group(tests):
        values = tuple(sorted(positions[test] for test in tests))
        return groups.setdefault(values, len(groups))

    files = {}
    for path, source in sources.items():
        info = {"source": source, "lines": {i: group(v) for i, v in sorted(lines.get(path, {}).items())},
                "readers": group(reads[path]), "factories": sorted(factories[path])}
        if module_name(path) in pickle_modules:
            info["pool"] = group(pool_tests)
        files[path] = info
    return {
        "format": 1, "base_commit": BASE, "ids": ids, "files": files,
        "classes": {k: group(v) for k, v in sorted(classes.items())},
        "attributes": {k: group(v) for k, v in sorted(attributes.items())},
        "class_reads": {k: group(v) for k, v in sorted(static_reads.items())},
        "sites": {k: {pair: group(v) for pair, v in sorted(pairs.items())}
                  for k, pairs in sorted(sites.items())},
        "groups": list(groups),
    }


def build():
    scratch = ROOT / ".investigation"
    base = scratch / "sqlglot"
    if (subprocess.check_output(["git", "-C", base, "rev-parse", "HEAD"], text=True).strip() != BASE
            or subprocess.check_output(["git", "-C", base, "status", "--porcelain"])):
        raise ValueError("Expected a clean pinned checkout")
    output = make_map(base, *base_traces(scratch), *profile_data(scratch / "phase05/base-profile"))
    payload = json.dumps(output, separators=(",", ":"), sort_keys=True).encode()
    (ROOT / "precise_map.json.gz").write_bytes(gzip.compress(payload, mtime=0))


if __name__ == "__main__":
    build()
