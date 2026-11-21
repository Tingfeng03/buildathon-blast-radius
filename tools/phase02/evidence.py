"""Build frozen candidate evidence from the unchanged checkout and its traces."""

import ast
import gzip
import importlib.util
import json
import time
from collections import defaultdict
from pathlib import Path

MODES = ("parent", "worker", "settings", "imports")


def merge(parent, extra):
    combined = {path: {line: set(ids) for line, ids in lines.items()} for path, lines in parent.items()}
    for path, lines in extra.items():
        target = combined.setdefault(path, {})
        for line, ids in lines.items():
            target.setdefault(line, set()).update(ids)
    return combined


def read_traces(scratch, output):
    with gzip.open(scratch / "dependencies.json.gz", "rt", encoding="utf-8") as stream:
        old = json.load(stream)
    if old["pytest_status"]:
        raise ValueError("The parent collector did not finish successfully")
    ids = old["nodeids"]
    parent = {
        path: {int(line): {ids[i] if i >= 0 else "" for i in indices} for line, indices in lines.items()}
        for path, lines in old["sources"].items()
    }
    run = json.loads((output / "worker-run.json").read_text(encoding="utf-8"))
    if run["status"] or "" in run["submitted_ids"] or set(run["submitted_ids"]).difference(ids):
        raise ValueError("Worker collection failed or submitted tasks without a known pytest ID")
    worker = {}
    proof = []
    expected = "tests/test_optimizer.py::TestOptimizer::test_eliminate_ctes"
    worker_contexts = set()
    for path in sorted(output.glob("worker-*.json")):
        if path.name == "worker-run.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["pid"] == run["parent_pid"]:
            raise ValueError("Worker data came from the parent")
        found = sorted(int(line) for line, nodes in data["sources"].get(
            "sqlglot/optimizer/eliminate_ctes.py", {}
        ).items() if expected in nodes)
        if found:
            proof.append({"pid": data["pid"], "id": expected, "lines": found})
        sources = {name: {int(line): set(nodes) for line, nodes in lines.items()}
                   for name, lines in data["sources"].items()}
        worker_contexts.update(node for lines in sources.values() for nodes in lines.values() for node in nodes if node)
        worker = merge(worker, sources)
    if not proof:
        raise ValueError("No child process proved worker attribution")
    run["submitted_ids_without_worker_lines"] = sorted(set(run["submitted_ids"]).difference(worker_contexts))
    run["proof"] = proof
    run["parent_wall_seconds"] = old["test_wall_seconds"]
    return ids, parent, worker, run


def module_name(path):
    return path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def import_edges(path, tree, known):
    module = module_name(path)
    package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
    edges = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            edges.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                try:
                    base = importlib.util.resolve_name("." * node.level + base, package)
                except ImportError:
                    continue
            edges.add(base)
            edges.update(base + "." + item.name for item in node.names)
    return edges.intersection(known)


def static_importers(trees, ids):
    modules = {module_name(path) for path in trees}
    edges = {module_name(path): import_edges(path, tree, modules) for path, tree in trees.items()}
    tests = defaultdict(list)
    for node in ids:
        tests[module_name(node.split("::", 1)[0])].append(node)
    readers = defaultdict(set)
    for test, nodeids in tests.items():
        pending, visited = list(edges.get(test, ())), set()
        while pending:
            module = pending.pop()
            if module in visited:
                continue
            visited.add(module)
            readers[module].update(nodeids)
            pending.extend(edges[module].difference(visited))
    return readers


def function_ranges(tree, lines):
    ranges = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0]
        # A body on the signature line cannot be isolated by line coordinates.
        if first.lineno <= node.lineno:
            continue
        readers = set()
        for line in range(first.lineno, node.end_lineno + 1):
            readers.update(lines.get(line, ()))
        ranges.append([first.lineno, node.end_lineno, first.col_offset, sorted(readers) if "" not in readers else []])
    return sorted(ranges)


def attribute_reads(trees, coverage):
    attributes = defaultdict(set)
    for path, tree in trees.items():
        lines = coverage.get(path, {})
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                attributes[node.attr].update(lines.get(node.lineno, ()))
    return attributes


def class_settings(tree, attributes):
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name) and stmt.lineno == stmt.end_lineno):
                continue
            name = stmt.targets[0].id
            readers = attributes.get(name, set())
            if name.isupper() and readers and "" not in readers:
                result[str(stmt.lineno)] = [name, sorted(readers)]
    return result


def build(base, scratch, output, base_commit):
    start = time.monotonic()
    ids, parent, worker, run = read_traces(scratch, output)
    combined = merge(parent, worker)
    sources = {path.relative_to(base).as_posix(): path.read_text(encoding="utf-8")
               for folder in ("sqlglot", "tests") for path in sorted((base / folder).rglob("*.py"))}
    trees = {path: ast.parse(source) for path, source in sources.items()}
    attributes = attribute_reads(trees, combined)
    importers = static_importers(trees, ids)
    sizes = {}
    for mode in MODES:
        coverage = parent if mode == "parent" else combined
        files = {}
        for path, tree in trees.items():
            if not path.startswith("sqlglot/"):
                continue
            functions = function_ranges(tree, coverage.get(path, {}))
            settings = class_settings(tree, attributes) if mode in ("settings", "imports") else {}
            if not any(record[3] for record in functions) and not settings:
                continue
            info = {"source": sources[path], "functions": functions}
            if settings:
                info["settings"] = settings
            if mode == "imports":
                info["importers"] = sorted(importers[module_name(path)])
            files[path] = info
        report = {"base_commit": base_commit, "reference_ids": ids, "files": files}
        payload = gzip.compress(json.dumps(report, separators=(",", ":"), sort_keys=True).encode(), mtime=0)
        (output / (mode + ".json.gz")).write_bytes(payload)
        sizes[mode] = len(payload)
    run["map_bytes"] = sizes
    run["evidence_build_wall_seconds"] = time.monotonic() - start
    (output / "evidence-summary.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
    return run
