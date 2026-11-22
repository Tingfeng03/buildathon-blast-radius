"""Resolve test-module and fixture edits using pinned shared dependencies."""

import ast
import gzip
import json
import re
import zlib

from source_selector import patched_files

FIXTURE_PATH = r"tests/fixtures/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.(?:sql|json)"
TEST_PATH = r"tests/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.py"
TEST_HEADER = re.compile(rf"diff --git a/({TEST_PATH}) b/\1")
ENCODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)", re.MULTILINE)
SETUP_NAMES = {"setup", "teardown", "setup_class", "teardown_class", "setup_method",
               "teardown_method", "setup_function", "teardown_function", "setup_module",
               "teardown_module", "load_tests", "asyncSetUp", "asyncTearDown",
               "setUp", "tearDown", "setUpClass", "tearDownClass", "setUpModule", "tearDownModule"}
ASSERTIONS = {"assertEqual", "assertNotEqual", "assertIn", "assertNotIn", "assertIs",
              "assertIsNot", "assertIsNone", "assertIsNotNone", "assertTrue", "assertFalse"}


def load_shared_map(path, base, by_id):
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            data = json.load(stream)
        ids = set(data["reference_ids"])
        if (data["base_commit"] != base or not ids.issuperset(by_id)
                or any(not isinstance(node, str) for node in ids)):
            return None

        def valid_readers(readers):
            return isinstance(readers, list) and bool(readers) and set(readers).issubset(ids)

        for name, readers in data["fixtures"].items():
            if not re.fullmatch(FIXTURE_PATH, name) or not valid_readers(readers):
                return None
        for name, info in data["test_modules"].items():
            if (not re.fullmatch(TEST_PATH, name)
                    or not isinstance(info["source"], str) or not valid_readers(info["readers"])):
                return None
        return data
    except (OSError, EOFError, ValueError, TypeError, AttributeError, KeyError, RecursionError, zlib.error):
        return None


class AssertionShape(ast.NodeTransformer):
    """Normalize expected values without discarding changes to test setup or control flow."""

    def visit_FunctionDef(self, node):
        if (node.name in SETUP_NAMES or node.name.startswith(("pytest_", "__"))
                or node.decorator_list):
            return node
        node.body = [self.visit(stmt) for stmt in node.body]
        return node

    def visit_Call(self, node):
        function = node.func
        if (isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name)
                and function.value.id == "self" and function.attr in ASSERTIONS):
            node.args = [self.assertion_argument(arg) for arg in node.args]
        return node

    def visit_ClassDef(self, node):
        return node

    @staticmethod
    def assertion_argument(node):
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            node.elts = [AssertionShape.assertion_argument(value) for value in node.elts]
        if isinstance(node, ast.Constant):
            return ast.Constant(value=None)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"upper", "lower"} and isinstance(node.func.value, ast.Name)
                and not node.args and not node.keywords):
            return node.func.value
        return node


def assertion_shape(path, source):
    tree = ast.parse(source, path, type_comments=True)
    # Only normalize inside existing functions and class methods. Module and
    # class bodies, defaults, decorators, and collection hooks stay intact.
    transformer = AssertionShape()
    for statement in tree.body:
        if isinstance(statement, ast.FunctionDef):
            transformer.visit_FunctionDef(statement)
        elif isinstance(statement, ast.ClassDef):
            for member in statement.body:
                if isinstance(member, ast.FunctionDef):
                    transformer.visit_FunctionDef(member)
    return ast.dump(tree)


def test_readers(patch, modules):
    [(path, info, changed)] = patched_files(patch, modules, include_source=True, header_pattern=TEST_HEADER)
    original = info["source"]
    if (ENCODING.findall("\n".join(original.split("\n", 2)[:2]))
            != ENCODING.findall("\n".join(changed.split("\n", 2)[:2]))
            or assertion_shape(path, original) != assertion_shape(path, changed)):
        raise ValueError("Test-module change has unresolved effects")
    return info["readers"]
