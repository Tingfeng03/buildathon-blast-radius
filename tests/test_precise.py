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

    def select(self, before, after, extra="", readers=0, lines=None, structural=False, importers=None,
               binding_edits=False, membership=None, skipped=()):
        ids = ["source", "fixture", "reads-text"]
        evidence = {
            "format": 1, "structural": structural, "binding_edits": binding_edits, "ids": ids,
            "groups": [[], [0], [2], [-1, 0]], "sites": {},
            "files": {self.path: {
                "source": before, "readers": readers, "lines": lines or {"2": 1},
            }},
        }
        if importers is not None:
            evidence["files"][self.path]["importers"] = importers
        if membership is not None:
            evidence["files"][self.path]["membership"] = membership
        return select_patch(self.patch(before, after) + extra, {self.fixture: ["fixture"]},
                            evidence, {i: i for i in ids if i not in skipped}, skipped=skipped)

    def test_constant_default_and_inert_added_binding_use_module_evidence(self):
        before = "def run(value=1):\n    return value\n"
        options = {"structural": True, "binding_edits": True, "importers": 1}
        self.assertEqual(self.select(before, before.replace("=1", "=2"), **options), ["source"])
        self.assertIsNone(self.select(before, before.replace("=1", "=factory()"), **options))
        self.assertEqual(self.select(before, before + "\ndef _helper():\n    pass\n", **options), ["source"])
        self.assertIsNone(self.select(before, before + "\n@factory()\ndef _helper():\n    pass\n", **options))
        self.assertEqual(self.select(before, before.replace("=1", "=2"), skipped=("source",), **options), [])

    def test_membership_removal_uses_readers_but_replacements_use_importers(self):
        before = "ITEMS = {1, 2}\n"
        options = {"structural": True, "importers": 2, "membership": {"ITEMS": 1}}
        self.assertEqual(self.select(before, "ITEMS = {1}\n", **options), ["source"])
        self.assertEqual(self.select(before, "ITEMS = {1, 3}\n", **options), ["reads-text"])

    def test_guarded_statement_uses_original_statement_readers(self):
        before = "def run(x):\n    if x:\n        return 1\n    return 0\n"
        after = before.replace("        return 1", "        if x == 1:\n            return 1")
        self.assertEqual(self.select(before, after, lines={"2": 2, "3": 1, "4": 2},
                                     structural=True, binding_edits=True), ["source"])

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

    def test_structural_edit_includes_callers_outside_the_edited_branch(self):
        old = "def run(value):\n    if value:\n        return 1\n    return 0\n"
        new = old.replace("return 1", "result = 2\n        return result")
        self.assertEqual(self.select(old, new, structural=True, lines={"3": 1, "4": 2}),
                         ["reads-text", "source"])
        self.assertIsNone(self.select(old, new, structural=True, lines={"3": 1, "4": 3}))
        self.assertIsNone(self.select(old, old.replace("return 1", "yield 1"), structural=True,
                                      lines={"3": 1, "4": 2}))

    def test_import_changes_require_bounded_module_evidence(self):
        old = "def run():\n    return 1\n"
        new = 'raise ImportError("module unavailable")\n' + old
        self.assertIsNone(self.select(old, new, structural=True))
        self.assertEqual(self.select(old, new, structural=True, importers=2), ["reads-text"])
        self.assertIsNone(self.select(old, "do_something()\n" + old, structural=True, importers=2))

    def test_module_configuration_has_to_be_data(self):
        old = "SETTINGS = {'units': (1, 2, 3)}\n"
        new = old.replace("1, 2, 3", "1, 2")
        self.assertEqual(self.select(old, new, structural=True, importers=2), ["reads-text"])
        self.assertIsNone(self.select(old, "SETTINGS = run()\n", structural=True, importers=2))
