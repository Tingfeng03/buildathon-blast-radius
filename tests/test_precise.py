import difflib
import ast
import json
import unittest

from precise_selector import identity_readers, supported_value
from selector import select_patch


class PreciseTests(unittest.TestCase):
    path = "sqlglot/example.py"
    fixture = "tests/fixtures/optimizer/a.sql"

    def patch(self, before, after, path=None):
        path = path or self.path
        return f"diff --git a/{path} b/{path}\n" + "".join(difflib.unified_diff(
            before.splitlines(True), after.splitlines(True), "a/" + path, "b/" + path,
        ))

    def select(self, before, after, extra="", readers=0, lines=None):
        ids = ["source", "fixture", "reads-text"]
        evidence = {
            "format": 1, "ids": ids, "groups": [[], [0], [2], [-1, 0]], "sites": {},
            "files": {self.path: {
                "source": before, "readers": readers, "lines": lines or {"2": 1},
            }},
        }
        return select_patch(self.patch(before, after) + extra, {self.fixture: ["fixture"]},
                            evidence, {i: i for i in ids})

    def test_mixed_patch_union_and_unknown_operation(self):
        before = "def run():\n    return 1\n"
        changed = before.replace("1", "2")
        fixture = self.patch("SELECT 1\n", "SELECT 2\n", self.fixture)
        self.assertEqual(self.select(before, changed, fixture), ["fixture", "source"])
        self.assertIsNone(self.select(before, changed, fixture.replace("a.sql", "b.sql")))
        self.assertIsNone(self.select(before, changed, self.patch(before, changed)))

    def test_python_comment_source_readers_and_comment_inside_sql_string(self):
        before = "def run():\n    return 1\n"
        self.assertEqual(self.select(before, "# ordinary comment\n" + before), [])
        self.assertEqual(self.select(before, "# ordinary comment\n" + before, readers=2), ["reads-text"])
        sql = "def run():\n    return '''SELECT\n# literal\n1'''\n"
        self.assertEqual(self.select(sql, sql.replace("literal", "changed")), ["source"])
        self.assertIsNone(self.select(before, "# coding: ascii\n" + before))

    def test_unknown_coverage_and_scope_or_import_changes_fall_back(self):
        before = "def run():\n    return 1\n"
        self.assertIsNone(self.select(before, before.replace("1", "2"), lines={"2": 3}))
        self.assertIsNone(self.select(before, before.replace("1", "2"), lines={"9": 1}))
        self.assertIsNone(self.select(before, before.replace("return", "x = 3\n    return")))
        self.assertIsNone(self.select(before, "raise ImportError()\n" + before))

    def test_short_circuit_change_accounts_for_earlier_operands(self):
        before = "def run(x):\n    if (x and\n        x.value):\n        return 1\n"
        self.assertEqual(self.select(before, before.replace("and", "or"), lines={"2": 1, "3": 2}),
                         ["reads-text", "source"])

    def test_identity_pruning_keeps_overloaded_and_unprofiled_readers(self):
        def expression(test):
            return ast.parse(f"x if holder.value {test} None else y", mode="eval").body
        old = expression("is")
        site = f"{self.path}:1:{old.test.col_offset}"
        ordinary = ["example.Table", "builtins.object", False]
        custom = ["example.Table", "example.Table", False]
        none = ["builtins.NoneType", "builtins.NoneType", False]
        evidence = {"groups": [[0], [1]], "sites": {site: {
            json.dumps([ordinary, none]): 0, json.dumps([custom, none]): 1,
        }}}
        self.assertEqual(identity_readers(old, expression("=="), self.path, evidence, {0, 1, 2}), {1, 2})
        self.assertIsNone(identity_readers(old, expression("!="), self.path, evidence, {0, 1, 2}))

    def test_new_executable_class_setting_requires_fallback(self):
        def value(code):
            return ast.parse(code, mode="eval").body
        self.assertTrue(supported_value(value("(16, 2)"), value("(8, 2)"), {}))
        self.assertFalse(supported_value(value("(16, 2)"), value("missing()"), {}))
        self.assertFalse(supported_value(value("f(1)"), value("f(0)"), {}))

    def test_edit_to_closure_body_uses_executions_of_that_body(self):
        old = "def factory():\n    def inner(x):\n        return x + 1\n    return inner\n"
        self.assertEqual(self.select(old, old.replace("+ 1", "+ 2"), lines={"2": 3, "3": 1}), ["source"])
