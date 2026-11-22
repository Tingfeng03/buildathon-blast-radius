"""Observe base expression/dialect classes, comparison operand types and Python source reads."""

import ast
import builtins
import importlib.abc
import importlib.machinery
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import cache, wraps
from multiprocessing.util import Finalize
from pathlib import Path

import pytest

ROOT = Path("/src")
OUTPUT = Path("/evidence")
current = ""
observations = defaultdict(set)
installed = False


@cache
def class_name(cls):
    return f"{cls.__module__}.{cls.__qualname__}"


def compare(site, left, right, negate):
    observations[current].add((site, type(left), type(right)))
    return (left is not right) if negate else (left is right)


class CompareSites(ast.NodeTransformer):
    def __init__(self, path):
        self.path = path

    def visit_Compare(self, node):
        self.generic_visit(node)
        if (len(node.ops) == 1 and isinstance(node.ops[0], (ast.Is, ast.IsNot))
                and isinstance(node.left, ast.Attribute)):
            site = f"{self.path}:{node.lineno}:{node.col_offset}"
            call = ast.Call(ast.Name("_blast_base_compare", ast.Load()), [
                ast.Constant(site), node.left, node.comparators[0],
                ast.Constant(isinstance(node.ops[0], ast.IsNot)),
            ], [])
            return ast.copy_location(call, node)
        return node


class SourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        path = Path(self.path)
        tree = ast.parse(path.read_bytes(), self.path)
        tree = CompareSites(path.relative_to(ROOT).as_posix()).visit(tree)
        return compile(ast.fix_missing_locations(tree), self.path, "exec", dont_inherit=True)


class SourceFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".", 1)[0] != "sqlglot":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = SourceLoader(fullname, spec.origin)
        return spec


def watch_instances(cls):
    init = cls.__init__

    @wraps(init)
    def observed(instance, /, *args, **kwargs):
        observations[current].add(type(instance))
        init(instance, *args, **kwargs)

    cls.__init__ = observed


def source_read(event, args):
    if event != "open" or not isinstance(args[0], str) or not args[0].endswith(".py"):
        return
    path = os.path.abspath(args[0])
    if not path.startswith("/src/sqlglot/"):
        return
    frame = sys._getframe(1)
    while frame:
        if frame.f_code.co_name in ("get_code", "get_data", "exec_module"):
            return
        frame = frame.f_back
    observations[current].add(path.removeprefix("/src/"))


def install():
    global installed
    if installed:
        return
    installed = True
    builtins._blast_base_compare = compare
    sys.meta_path.insert(0, SourceFinder())
    sys.addaudithook(source_read)
    from sqlglot import Dialect, Generator, Parser, Tokenizer, exp
    for cls in (Dialect, Generator, Parser, Tokenizer, exp.Expr):
        watch_instances(cls)


def type_info(cls):
    import enum
    owner = next(base for base in cls.__mro__ if "__eq__" in vars(base))
    return [class_name(cls), class_name(owner), issubclass(cls, enum.Enum)]


def export():
    classes, sites, sources = defaultdict(set), defaultdict(lambda: defaultdict(set)), defaultdict(set)
    for test, events in observations.items():
        for event in events:
            if isinstance(event, str):
                sources[event].add(test)
            elif isinstance(event, type):
                for cls in event.__mro__:
                    if cls.__module__.startswith("sqlglot."):
                        classes[class_name(cls)].add(test)
            else:
                site, left, right = event
                pair = json.dumps([type_info(left), type_info(right)], separators=(",", ":"))
                sites[site][pair].add(test)
    def ids(mapping):
        return {key: sorted(value) for key, value in mapping.items()}
    (OUTPUT / f"profile-{os.getpid()}.json").write_text(json.dumps({
        "classes": ids(classes), "sites": {s: ids(v) for s, v in sites.items()},
        "sources": ids(sources),
    }))


def task(test, fn, args, kwargs):
    global current
    current = test
    install()
    return fn(*args, **kwargs)


def initialize(initializer, args):
    install()
    Finalize(None, export, exitpriority=10)
    if initializer:
        initializer(*args)


class Context:
    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_protocol(self, item):
        global current
        current = item.nodeid
        try:
            return (yield)
        finally:
            current = ""


def main():
    install()
    submit, init = ProcessPoolExecutor.submit, ProcessPoolExecutor.__init__
    def observed_init(pool, *args, initializer=None, initargs=(), **kwargs):
        return init(pool, *args, initializer=initialize, initargs=(initializer, initargs), **kwargs)
    def observed_submit(pool, fn, /, *args, **kwargs):
        return submit(pool, task, current, fn, args, kwargs)
    ProcessPoolExecutor.__init__, ProcessPoolExecutor.submit = observed_init, observed_submit
    status = pytest.main(["-q", "-p", "no:cacheprovider", "tests"], plugins=[Context()])
    export()
    (OUTPUT / "profile-run.json").write_text(json.dumps({"status": int(status)}))
    return status


if __name__ == "__main__":
    sys.exit(main())
elif __name__ == "__mp_main__":
    install()
