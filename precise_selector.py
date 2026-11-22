"""Resolve a verified Python diff to tests that observed the affected base behavior."""

import ast
import gzip
import json
import re
import zlib
from difflib import SequenceMatcher
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
                    and all(valid_index(info[key]) for key in
                            ("pool", "importers", "binding_importers") if key in info)
                    and isinstance(info.get("membership", {}), dict)
                    and all(valid_index(i) for i in info.get("membership", {}).values())):
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


def guarded_statement(old, new):
    if not (isinstance(old, (ast.Expr, ast.Return)) and isinstance(new, ast.If)
            and len(new.body) == 1 and not new.orelse and same(old, new.body[0])):
        return False
    if isinstance(old, ast.Expr) and isinstance(old.value, ast.Constant):
        return False
    test = new.test
    return (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
            and not test.left.id.startswith("__")
            and len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.NotEq))
            and isinstance(test.comparators[0], ast.Constant)
            and type(test.comparators[0].value) in (int, str, bool))


def executable_changes(old, new, binding_edits=False):
    """Find outer expressions, keeping the entry to a short-circuit expression."""
    if same(old, new):
        return
    if isinstance(old, ast.expr) and isinstance(new, ast.expr):
        if any(isinstance(n, (ast.NamedExpr, ast.Lambda, ast.Yield, ast.YieldFrom))
               for n in ast.walk(new)) and type(old) is not type(new):
            raise Unknown
        yield old, new
    elif binding_edits and guarded_statement(old, new):
        # The condition only runs when execution reaches the original statement.
        yield old, new.test
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for a, b in zip(old, new):
            yield from executable_changes(a, b, binding_edits)
    elif isinstance(old, ast.stmt) and type(old) is type(new):
        if isinstance(old, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not all(same(getattr(old, f), getattr(new, f)) for f in old._fields if f != "body"):
                raise Unknown
            yield from executable_changes(old.body, new.body, binding_edits)
            return
        if isinstance(old, (ast.ClassDef, ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
            raise Unknown
        for field in old._fields:
            a, b = getattr(old, field), getattr(new, field)
            if field in ("targets", "target", "name", "optional_vars") and not same(a, b):
                raise Unknown
            yield from executable_changes(a, b, binding_edits)
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
    for old, changed in executable_changes(fn.body, new.body, evidence.get("binding_edits")):
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


def callable_readers(fn, new, info, evidence):
    """A modified body can affect any caller, including a call that skips the edited lines."""
    def generator_body(node):
        pending = list(node.body)
        while pending:
            stmt = pending.pop()
            if isinstance(stmt, (ast.Yield, ast.YieldFrom)):
                return True
            if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                pending.extend(ast.iter_child_nodes(stmt))
        return False

    if ast.get_docstring(fn, clean=False) != ast.get_docstring(new, clean=False) or (
        generator_body(fn) != generator_body(new)
    ):
        raise Unknown("Callable metadata changed")
    first = fn.body[0].lineno
    if first <= fn.lineno:
        raise Unknown("Cannot separate a single-line body from definition-time evaluation")
    readers = set()
    for line in range(first, fn.end_lineno + 1):
        readers.update(point(info, evidence, line))
    if not readers or -1 in readers:
        raise Unknown("Callable has incomplete execution attribution")
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


def module_readers(info, evidence, key="importers"):
    if key not in info:
        raise Unknown("No bounded import evidence for module")
    return groups(evidence, info[key])


def assignment_name(old, new):
    if type(old) is not type(new) or not isinstance(old, (ast.Assign, ast.AnnAssign)):
        raise Unknown
    if not all(same(getattr(old, f), getattr(new, f)) for f in old._fields if f != "value"):
        raise Unknown
    targets = old.targets if isinstance(old, ast.Assign) else [old.target]
    if len(targets) != 1 or not isinstance(targets[0], ast.Name) or not targets[0].id.isupper():
        raise Unknown
    return targets[0].id


def enum_member(value, info):
    if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name):
        name = value.value.id
        if value.attr in info.get("enums", {}).get(name, ()):
            return name
    return None


def passive_data(node):
    """Recognize data expressions without calls, comprehensions, or operators with side effects."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) or passive_data(node.value)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(passive_data(value) for value in node.elts)
    if isinstance(node, ast.Dict):
        return all(key is not None and passive_data(key) and passive_data(value)
                   for key, value in zip(node.keys, node.values))
    return (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant) and type(node.operand.value) in (int, float))


def changed_sequences(old, new, key):
    matcher = SequenceMatcher(None, list(map(key, old)), list(map(key, new)), autojunk=False)
    return [(old[a:b], new[c:d]) for tag, a, b, c, d in matcher.get_opcodes() if tag != "equal"]


def data_edit(old, new):
    if isinstance(old, ast.Dict) and isinstance(new, ast.Dict):
        entries = changed_sequences(list(zip(old.keys, old.values)), list(zip(new.keys, new.values)),
                                    lambda item: tuple(ast.dump(n) if n is not None else "" for n in item))
        return all(key is not None and passive_data(key) and passive_data(value)
                   for before, after in entries for key, value in before + after)
    return passive_data(old) and passive_data(new)


def membership_removal(old, new):
    if not (isinstance(old, ast.Set) and isinstance(new, ast.Set)):
        return False
    return all(not after for _, after in changed_sequences(old.elts, new.elts, ast.dump))


def configuration_readers(old, new, owner, info, evidence):
    name = assignment_name(old, new)
    membership = info.get("membership", {}).get(name) if owner is None else None
    if (membership is not None and membership_removal(old.value, new.value)
            and all(passive_data(value) for value in old.value.elts)):
        return groups(evidence, membership)
    enum = enum_member(old.value, info)
    if owner and enum and enum_member(new.value, info) == enum:
        observed = evidence["classes"].get(owner)
        if observed is not None:
            instances = groups(evidence, observed) - {-1}
            named = evidence["class_reads"].get(f"{owner}.{name}")
            if instances:
                return instances | (groups(evidence, named) if named is not None else set())
    if not data_edit(old.value, new.value):
        raise Unknown("Configuration edit may evaluate executable code")
    return module_readers(info, evidence)


def import_edit(old, new):
    def permitted(node):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
        if not isinstance(node, ast.Raise) or node.cause is not None:
            return False
        exc = node.exc
        return (isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name)
                and exc.func.id in ("ImportError", "ModuleNotFoundError")
                and not exc.keywords and all(isinstance(arg, ast.Constant) for arg in exc.args))
    return all(permitted(node) for before, after in changed_sequences(old, new, ast.dump)
               for node in before + after)


def introduced_bindings(old, new, owner):
    """Align unchanged definitions around added, inert bindings."""
    changes = changed_sequences(old, new, ast.dump)
    bound = set()
    for stmt in old:
        if isinstance(stmt, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(stmt.name)
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name):
                bound.add(node.id)
            elif isinstance(node, ast.alias):
                bound.add(node.asname or node.name.split(".")[0])
    for before, after in changes:
        if before:
            return False
        for node in after:
            if (owner is None and isinstance(node, ast.FunctionDef)
                    and not (node.decorator_list or node.returns or node.args.defaults
                             or any(node.args.kw_defaults) or getattr(node, "type_params", ()))
                    and all(arg.annotation is None for arg in ast.walk(node.args)
                            if isinstance(arg, ast.arg))):
                name = node.name
                if not name.startswith("_") or name.startswith("__"):
                    return False
            elif (owner is not None and isinstance(node, ast.Assign) and len(node.targets) == 1
                  and isinstance(node.targets[0], ast.Name) and node.targets[0].id.isupper()
                  and isinstance(node.value, ast.Constant)):
                name = node.targets[0].id
            else:
                return False
            if name in bound:
                return False
            bound.add(name)
    return bool(changes)


def constant_default_edit(old, new):
    if old.decorator_list or not same(old.body, new.body):
        return False
    if not all(same(getattr(old, field), getattr(new, field))
               for field in old._fields if field != "args"):
        return False
    if not all(same(getattr(old.args, field), getattr(new.args, field))
               for field in old.args._fields if field not in ("defaults", "kw_defaults")):
        return False
    for before, after in ((old.args.defaults, new.args.defaults),
                          (old.args.kw_defaults, new.args.kw_defaults)):
        if len(before) != len(after):
            return False
        if any(not same(a, b) and not (isinstance(a, ast.Constant)
                                       and isinstance(b, ast.Constant)
                                       and type(a.value) is type(b.value))
               for a, b in zip(before, after)):
            return False
    return True


def definitions(old, new, path, info, evidence, reasons, owner=None):
    binding_key = "binding_importers" if "binding_importers" in info else "importers"
    if len(old) != len(new):
        if evidence.get("binding_edits") and introduced_bindings(old, new, owner):
            reasons.add("definition dependencies")
            return module_readers(info, evidence, binding_key)
        raise Unknown
    readers = set()
    for a, b in zip(old, new):
        if same(a, b):
            continue
        if type(a) is type(b) and isinstance(a, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not all(same(getattr(a, f), getattr(b, f)) for f in a._fields if f != "body"):
                if (evidence.get("binding_edits") and isinstance(a, ast.FunctionDef)
                        and constant_default_edit(a, b)):
                    if owner is None and binding_key == "binding_importers":
                        # The pinned optimizer dispatches rules by parameter name.
                        try:
                            readers.update(callable_readers(a, b, info, evidence))
                        except Unknown:
                            readers.update(module_readers(info, evidence, binding_key))
                    else:
                        readers.update(module_readers(info, evidence, binding_key))
                    reasons.add("default argument dependencies")
                    continue
                raise Unknown
            if isinstance(a, ast.ClassDef):
                module = path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
                readers.update(definitions(a.body, b.body, path, info, evidence, reasons,
                                           f"{owner or module}.{a.name}"))
            else:
                try:
                    readers.update(body_readers(a, b, path, info, evidence))
                    reasons.add("precise source coverage")
                except Unknown:
                    if not evidence.get("structural"):
                        raise
                    readers.update(callable_readers(a, b, info, evidence))
                    reasons.add("enclosing callable coverage")
        else:
            if owner:
                try:
                    readers.update(class_setting(a, b, owner, info, evidence))
                    reasons.add("precise class setting")
                    continue
                except Unknown:
                    if not evidence.get("structural"):
                        raise
            if not evidence.get("structural"):
                raise Unknown
            readers.update(configuration_readers(a, b, owner, info, evidence))
            reasons.add("configuration dependencies")
    return readers


@lru_cache(maxsize=12)
def base_tree(path, source):
    return ast.parse(source, path, type_comments=True)


def source_readers(patch, evidence, reasons=None):
    readers = set()
    if reasons is None:
        reasons = set()
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
        file_reasons = set()
        try:
            readers.update(definitions(old.body, new.body, path, info, evidence, file_reasons))
        except Unknown:
            if not evidence.get("structural") or not import_edit(old.body, new.body):
                raise
            readers.update(module_readers(info, evidence))
            file_reasons = {"import dependencies"}
        reasons.update(file_reasons or {"source-only change"})
    if -1 in readers:
        raise Unknown
    return {evidence["ids"][i] for i in readers}
