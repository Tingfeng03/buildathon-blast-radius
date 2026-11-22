import ast
import unittest

from tools.build_precise_map import lazy_imports, membership_readers


class StructuralEvidenceTests(unittest.TestCase):
    def test_local_membership_requires_attributed_uses_without_export(self):
        path = "sqlglot/generators/example.py"
        source = (
            "OPTIONS = {1, 2}\n"
            "class Example:\n"
            "    def accepts(self, value):\n"
            "        return value in OPTIONS\n"
        )
        trees = {path: ast.parse(source)}
        trace = {path: {4: {"consumer"}}}
        self.assertEqual(membership_readers(trees, {}, trace), {path: {"OPTIONS": {"consumer"}}})
        for access in (
            "from sqlglot.generators.example import OPTIONS",
            "from sqlglot.generators.example import *",
            "settings = example.OPTIONS",
            "settings = getattr(example, 'OPTIONS')",
            "mock.patch('sqlglot.generators.example.OPTIONS')",
        ):
            with self.subTest(access=access):
                self.assertEqual(membership_readers(trees, {"tests/test_example.py": ast.parse(access)}, trace), {})
        self.assertEqual(membership_readers(trees, {}, {path: {4: {"", "consumer"}}}), {})
        self.assertEqual(membership_readers({path: ast.parse(source + "COPY = OPTIONS\n")}, {}, trace), {})

    def test_lazy_dialects_are_dependencies_even_when_cached(self):
        package = "sqlglot.dialects"
        exports = {"SQLite": f"{package}.sqlite", "Snowflake": f"{package}.snowflake"}
        for source, dialect in (
            ("import sqlglot.dialects\nvalue = sqlglot.dialects.Snowflake", "Snowflake"),
            ("import sqlglot as s\nvalue = s.dialects.SQLite", "SQLite"),
            ("from sqlglot import dialects as d\nvalue = getattr(d, 'SQLite')", "SQLite"),
            ("from sqlglot.dialects import Snowflake", "Snowflake"),
        ):
            with self.subTest(source=source):
                self.assertEqual(lazy_imports(ast.parse(source), package, exports), {exports[dialect]})
        self.assertEqual(lazy_imports(ast.parse("value = unrelated.SQLite"), package, exports), set())
