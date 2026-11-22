import ast
import unittest

from tools.build_precise_map import lazy_imports


class StructuralEvidenceTests(unittest.TestCase):
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
