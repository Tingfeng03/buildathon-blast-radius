"""Resolve a verified Python diff to tests that observed the affected base behavior."""

import ast
import gzip
import json
import re
import zlib
from functools import lru_cache

from source_selector import patched_files


class Unknown(ValueError):
    """The base evidence cannot resolve this edit."""


def load_precise_map(path, base, by_id):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            evidence = json.load(stream)
        ids = evidence["ids"]
        if (evidence["format"] != 1 or evidence["base_commit"] != base
                or not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)
                or not set(by_id).issubset(ids) or len(ids) != len(set(ids))
                or not all(isinstance(evidence[key], dict) for key in
                           ("files", "classes", "sites", "class_reads", "attributes"))):
            return None
        groups_ = evidence["groups"]
        def valid_index(i):
            return type(i) is int and 0 <= i < len(groups_)
        for group in groups_:
            if not isinstance(group, list) or any(type(i) is not int or not -1 <= i < len(ids) for i in group):
                return None
        for info in evidence["files"].values():
            if not (isinstance(info, dict) and isinstance(info["source"], str)
                    and isinstance(info["lines"], dict) and valid_index(info["readers"])
                    and all(valid_index(i) for i in info["lines"].values())
                    and ("pool" not in info or valid_index(info["pool"]))):
                return None
        return evidence
    except (KeyError, TypeError, OSError, EOFError, ValueError, RecursionError, zlib.error):
        return None


def same(a, b):
    if isinstance(a, ast.AST):
        return type(a) is type(b) and all(same(getattr(a, f), getattr(b, f)) for f in a._fields)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(map(same, a, b))
    return type(a) is type(b) and a == b


def groups(evidence, group_number):
    if type(group_number) is not int or group_number < 0:
        raise Unknown
    return set(evidence["groups"][group_number])


def point(info, evidence, line):
    index = info["lines"].get(str(line))
    return groups(evidence, index) if index is not None else set()


def differing_parts(a, b):
    """Descend through shared syntax to the smallest changed AST nodes."""
    if same(a, b):
        return
    if type(a) is type(b) and isinstance(a, ast.AST):
        for f in a._fields:
            x, y = getattr(a, f), getattr(b, f)
            if same(x, y):
                continue
            if not isinstance(x, (ast.AST, list)):
                yield a, b
                return
            if isinstance(x, list) and (not isinstance(y, list) or len(x) != len(y)):
                yield a, b
                return
        for f in a._fields:
            yield from differing_parts(getattr(a, f), getattr(b, f))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for x, y in zip(a, b):
            yield from differing_parts(x, y)
    else:
        yield a, b


def identity_readers(old, new, path, evidence, reached):
    changes = list(differing_parts(old, new))
    if len(changes) == 1 and isinstance(changes[0][0], ast.Is) and isinstance(changes[0][1], ast.Eq):
        comparisons = [(a, b) for a, b in zip(ast.walk(old), ast.walk(new))
                       if isinstance(a, ast.Compare) and not same(a.ops, b.ops)]
        if len(comparisons) == 1:
            old, new = comparisons[0]
    if not (isinstance(old, ast.Compare) and isinstance(new, ast.Compare)
            and len(old.ops) == len(new.ops) == 1 and isinstance(old.ops[0], ast.Is)
            and isinstance(new.ops[0], ast.Eq) and same(old.left, new.left)
            and same(old.comparators, new.comparators)):
        return None
    pairs = evidence["sites"].get(f"{path}:{old.lineno}:{old.col_offset}")
    if not pairs:
        return None
    observed, uncertain = set(), set()
    for pair, group in pairs.items():
        readers = groups(evidence, group)
        left, right = json.loads(pair)
        # Default equality is identity. For the same string-valued Enum class,
        # equal string members are aliases of the same singleton.
        ordinary = ("builtins.object", "builtins.NoneType")
        equivalent = (left[1] in ordinary and right[1] in ordinary or
                      left == right and left[2] and left[1] == "builtins.str")
        observed.update(readers)
        if not equivalent:
            uncertain.update(readers)
    return (reached - observed) | uncertain


def executable_changes(old, new):
    """Find outer expressions, keeping the entry to a short-circuit expression."""
    if same(old, new):
        return
    if isinstance(old, ast.expr) and isinstance(new, ast.expr):
        if any(isinstance(n, (ast.NamedExpr, ast.Lambda, ast.Yield, ast.YieldFrom))
               for n in ast.walk(new)) and type(old) is not type(new):
            raise Unknown
        yield old, new
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for a, b in zip(old, new):
            yield from executable_changes(a, b)
    elif isinstance(old, ast.stmt) and type(old) is type(new):
        if isinstance(old, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not all(same(getattr(old, f), getattr(new, f)) for f in old._fields if f != "body"):
                raise Unknown
            yield from executable_changes(old.body, new.body)
            return
        if isinstance(old, (ast.ClassDef, ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            raise Unknown
        for field in old._fields:
            a, b = getattr(old, field), getattr(new, field)
            if field in ("targets", "target", "name", "optional_vars") and not same(a, b):
                raise Unknown
            yield from executable_changes(a, b)
    else:
        raise Unknown


def body_readers(fn, new, path, info, evidence):
    def bindings(function):
        return {n.id for n in ast.walk(function) if isinstance(n, ast.Name)
                and isinstance(n.ctx, (ast.Store, ast.Del))}
    if bindings(fn) != bindings(new):
        raise Unknown
    readers = set()
    if len(fn.body) != len(new.body):
        # An inserted return or expression can run before any previously covered
        # statement at that offset. Every observed caller of the function matters.
        if not all(isinstance(n, (ast.Expr, ast.Return, ast.Pass)) for n in new.body
                   if not any(same(n, previous) for previous in fn.body)):
            raise Unknown
        if not all(any(same(n, current) for current in new.body) for n in fn.body):
            raise Unknown
        for line in range(fn.body[0].lineno, fn.end_lineno + 1):
            readers.update(point(info, evidence, line))
        if not readers or any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(new)):
            raise Unknown
        if "pool" in info:
            readers.update(groups(evidence, info["pool"]))
        return readers
    for old, changed in executable_changes(fn.body, new.body):
        reached = point(info, evidence, old.lineno)
        # Coverage can credit a multiline expression to its constituent lines.
        for line in range(old.lineno + 1, old.end_lineno + 1):
            reached.update(point(info, evidence, line))
        if not reached:
            # Some expressions have no separate executable line event.
            for line in range(fn.body[0].lineno, fn.end_lineno + 1):
                reached.update(point(info, evidence, line))
        if not reached:
            raise Unknown
        narrowed = identity_readers(old, changed, path, evidence, reached)
        readers.update(reached if narrowed is None else narrowed)
    if "pool" in info:
        readers.update(groups(evidence, info["pool"]))
    return readers


def supported_value(a, b, info):
    if isinstance(a, ast.Call):
        if not (isinstance(a.func, ast.Name) and a.func.id in info.get("factories", ())):
            return False
    else:
        try:
            ast.literal_eval(a)
            ast.literal_eval(b)
        except (ValueError, TypeError):
            return False
    return all(isinstance(x, ast.Constant) and isinstance(y, ast.Constant)
               and type(x.value) is type(y.value) for x, y in differing_parts(a, b))


def class_setting(old, new, owner, info, evidence):
    if type(old) is not type(new) or not isinstance(old, (ast.Assign, ast.AnnAssign)):
        raise Unknown
    if not all(same(getattr(old, f), getattr(new, f)) for f in old._fields if f != "value"):
        raise Unknown
    target = old.target if isinstance(old, ast.AnnAssign) else old.targets[0]
    if not isinstance(target, ast.Name):
        raise Unknown
    observed = evidence["classes"].get(owner)
    if observed is None:
        raise Unknown
    instances = groups(evidence, observed)
    # Construction outside a test is common during import. Only test-specific
    # uses of this type are attributable here.
    instances.discard(-1)
    if not instances:
        raise Unknown
    direct_group = evidence["class_reads"].get(f"{owner}.{target.id}")
    named = groups(evidence, direct_group) if direct_group is not None else set()
    if isinstance(old.value, ast.Dict) and isinstance(new.value, ast.Dict):
        if not same(old.value.keys, new.value.keys):
            raise Unknown
        changes = [(a, b) for a, b in zip(old.value.values, new.value.values) if not same(a, b)]
        if all(isinstance(a, ast.Lambda) and isinstance(b, ast.Lambda)
               and same(a.args, b.args) for a, b in changes):
            reached = set()
            for a, b in changes:
                for x, _ in differing_parts(a.body, b.body):
                    if not hasattr(x, "lineno"):
                        return instances | named
                    reached.update(point(info, evidence, x.lineno))
            if reached and -1 not in reached:
                return reached | named
        elif not all(supported_value(a, b, info) for a, b in changes):
            raise Unknown
        return instances | named
    if not supported_value(old.value, new.value, info):
        raise Unknown
    attr = evidence["attributes"].get(target.id)
    if attr is None:
        raise Unknown
    direct = groups(evidence, attr)
    return named | (instances if -1 in direct else direct)


def definitions(old, new, path, info, evidence, owner=None):
    if len(old) != len(new):
        raise Unknown
    readers = set()
    for a, b in zip(old, new):
        if same(a, b):
            continue
        if type(a) is type(b) and isinstance(a, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not all(same(getattr(a, f), getattr(b, f)) for f in a._fields if f != "body"):
                raise Unknown
            if isinstance(a, ast.ClassDef):
                module = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
                readers.update(definitions(a.body, b.body, path, info, evidence, f"{owner or module}.{a.name}"))
            else:
                readers.update(body_readers(a, b, path, info, evidence))
        elif owner:
            readers.update(class_setting(a, b, owner, info, evidence))
        else:
            raise Unknown
    return readers


@lru_cache(maxsize=12)
def base_tree(path, source):
    return ast.parse(source, path, type_comments=True)


def source_readers(patch, evidence):
    readers = set()
    for path, info, source in patched_files(patch, evidence["files"], include_source=True):
        original = info["source"]
        # File encodings can change import behavior even when decoding both strings
        # as UTF-8 happens to produce identical Python syntax trees.
        cookie = r"(?m)^[ \t\f]*\#.*?coding[:=][ \t]*([-\w.]+)"
        if re.findall(cookie, "\n".join(original.split("\n", 2)[:2])) != re.findall(
                cookie, "\n".join(source.split("\n", 2)[:2])):
            raise Unknown
        old, new = base_tree(path, original), ast.parse(source, path, type_comments=True)
        if [node.tag for node in old.type_ignores] != [node.tag for node in new.type_ignores]:
            raise Unknown
        readers.update(groups(evidence, info["readers"]))
        readers.update(definitions(old.body, new.body, path, info, evidence))
    if -1 in readers:
        raise Unknown
    return {evidence["ids"][i] for i in readers}
