"""Build compact reader groups from the pinned checkout and successful base traces."""

import ast
import gzip
import importlib.util
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from selector import BASE
from tools.phase02.evidence import attribute_reads, import_edges, merge, module_name, read_traces


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


def lazy_imports(tree, package, exports):
    """Resolve the dialect package's public imports and attribute accesses."""
    root, _, child = package.partition(".")
    aliases, roots, dependencies = set(), set(), set()
    nodes = list(ast.walk(tree))
    for node in nodes:
        if isinstance(node, ast.Import):
            for item in node.names:
                if item.name == package and item.asname:
                    aliases.add(item.asname)
                elif item.name == root or item.name.startswith(root + "."):
                    roots.add(item.asname or root)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            if node.module == package:
                dependencies.update(exports[item.name] for item in node.names if item.name in exports)
            elif node.module == root:
                aliases.update(item.asname or item.name for item in node.names if item.name == child)

    def dialect_package(node):
        return (isinstance(node, ast.Name) and node.id in aliases or
                isinstance(node, ast.Attribute) and node.attr == child
                and isinstance(node.value, ast.Name) and node.value.id in roots)

    for node in nodes:
        if isinstance(node, ast.Attribute) and node.attr in exports and dialect_package(node.value):
            dependencies.add(exports[node.attr])
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "getattr" and len(node.args) >= 2
              and dialect_package(node.args[0]) and isinstance(node.args[1], ast.Constant)
              and isinstance(node.args[1].value, str) and node.args[1].value in exports):
            dependencies.add(exports[node.args[1].value])
    return dependencies


def import_dependents(trees, test_trees, ids, lines, classes, direct_reads, source_reads):
    """Join import dependencies with runtime use of lazily loaded dialect modules."""
    package = "sqlglot.dialects"
    dialect_package = trees["sqlglot/dialects/__init__.py"]
    dialects = next(ast.literal_eval(stmt.value) for stmt in dialect_package.body
                    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == "DIALECTS")
    lazy_exports = {name: f"{package}.{name.lower()}" for name in dialects}
    lazy_modules = set(lazy_exports.values())
    paths = {module_name(path): path for path in trees}
    all_trees = trees | test_trees
    known = {module_name(path) for path in all_trees}
    graph = {}
    for path, tree in all_trees.items():
        graph[module_name(path)] = import_edges(path, tree, known) | lazy_imports(tree, package, lazy_exports)

    users = defaultdict(set)
    for node_id in ids:
        users[module_name(node_id.split("::", 1)[0])].add(node_id)
    for module, path in paths.items():
        users[module].update(source_reads.get(path, ()))
        for readers in lines.get(path, {}).values():
            users[module].update(readers)
        for name, readers in classes.items():
            if name.startswith(module + "."):
                users[module].update(readers)
        for name, readers in direct_reads.items():
            if name.startswith(module + "."):
                users[module].update(readers)
        users[module].discard("")

    # Even when a dialect is already cached, accessing the complete registry can
    # fail after any eager dependency of a dialect breaks at import.
    registry_users = direct_reads.get("sqlglot.dialects.dialect.Dialect.classes", set())
    for module in lazy_modules:
        users[module].update(registry_users)
    all_importers = defaultdict(set)
    for module, readers in users.items():
        if not readers:
            continue
        pending, visited = [module], set()
        while pending:
            dependency = pending.pop()
            if dependency in visited:
                continue
            visited.add(dependency)
            all_importers[dependency].update(readers)
            pending.extend(graph.get(dependency, set()) - visited)
    return {
        path: all_importers[module] for module, path in paths.items()
        if (module in lazy_modules or module.startswith(("sqlglot.generators.", "sqlglot.parsers.",
                                                         "sqlglot.typing.", "sqlglot.optimizer.")))
        and not path.endswith("/__init__.py") and all_importers[module]
    }


def membership_readers(trees, test_trees, lines):
    """Find local sets consumed only by attributed membership checks."""
    exposed = set()
    imports = defaultdict(set)
    for path, tree in (trees | test_trees).items():
        module = module_name(path)
        package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                exposed.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                exposed.update(re.findall(r"\b[A-Z_][A-Z_0-9]*\b", node.value))
            elif isinstance(node, ast.ImportFrom):
                dependency = node.module or ""
                if node.level:
                    try:
                        dependency = importlib.util.resolve_name("." * node.level + dependency, package)
                    except ImportError:
                        continue
                imports[dependency].update(alias.name for alias in node.names)

    result = defaultdict(dict)
    for path, tree in trees.items():
        if not path.startswith(("sqlglot/parsers/", "sqlglot/generators/")):
            continue
        imported = imports[module_name(path)]
        if "*" in imported:
            continue
        nodes = list(ast.walk(tree))
        ranges = [(fn.body[0].lineno, fn.end_lineno) for cls in tree.body
                  if isinstance(cls, ast.ClassDef) and not (cls.decorator_list or cls.keywords)
                  for fn in cls.body if isinstance(fn, ast.FunctionDef) and not fn.decorator_list
                  and fn.body[0].lineno > fn.lineno]
        coverage = lines.get(path, {})
        for stmt in tree.body:
            if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name) and isinstance(stmt.value, ast.Set)):
                continue
            target = stmt.targets[0]
            name = target.id
            if not name.isupper() or name in exposed or name in imported:
                continue
            references = {node for node in nodes if isinstance(node, ast.Name) and node.id == name}
            comparisons = [node for node in nodes if isinstance(node, ast.Compare)
                           and len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn))
                           and node.comparators[0] in references
                           and any(start <= node.lineno <= end for start, end in ranges)]
            if not comparisons or references != {target, *(node.comparators[0] for node in comparisons)}:
                continue
            if any(not coverage.get(node.lineno) for node in comparisons):
                continue
            readers = set().union(*(coverage[node.lineno] for node in comparisons))
            if "" not in readers:
                result[path][name] = readers
    return result


def enum_references(trees):
    """Find direct imports of pinned AutoName enums and their member names."""
    enums = {}
    for path, tree in trees.items():
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not any(
                isinstance(base, ast.Name) and base.id == "AutoName" for base in node.bases
            ):
                continue
            enums[module_name(path), node.name] = sorted({
                stmt.targets[0].id for stmt in node.body
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id.isupper()
            })
    references = defaultdict(dict)
    for path, tree in trees.items():
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and not node.level:
                for alias in node.names:
                    members = enums.get((node.module, alias.name))
                    if members:
                        references[path][alias.asname or alias.name] = members
    return references


def make_map(base, ids, lines, pool_tests, classes, sites, reads):
    sources = {p.relative_to(base).as_posix(): p.read_text(encoding="utf-8")
               for p in sorted((base / "sqlglot").rglob("*.py"))}
    trees = {p: ast.parse(src) for p, src in sources.items()}
    test_trees = {path.relative_to(base).as_posix(): ast.parse(path.read_bytes())
                  for path in sorted((base / "tests").rglob("*.py"))}
    attributes = attribute_reads(trees, lines)
    factories = closure_factories(trees)
    static_reads = direct_class_reads(base, ids, classes)
    importers = import_dependents(trees, test_trees, ids, lines, classes, static_reads, reads)
    memberships = membership_readers(trees, test_trees, lines)
    enums = enum_references(trees)
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
        if path in importers:
            key = "binding_importers" if path.startswith("sqlglot/optimizer/") else "importers"
            info[key] = group(importers[path])
        if path in enums:
            info["enums"] = enums[path]
        if path in memberships:
            info["membership"] = {name: group(tests) for name, tests in sorted(memberships[path].items())}
        files[path] = info
    return {
        "format": 1, "structural": True, "binding_edits": True, "base_commit": BASE, "ids": ids, "files": files,
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
