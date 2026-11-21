import ast
import unittest

from tools.phase02.candidate import select_source
from tools.phase02.evidence import static_importers
from tools.phase02.validation import outcomes


class Phase02Tests(unittest.TestCase):
    def test_insertion_uses_the_existing_body_and_checks_base_context(self):
        name = "sqlglot/module.py"
        patch = (
            f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n"
            "@@ -1,2 +1,3 @@\n def run():\n+    return 2\n     return 1\n"
        )
        test = {"id": "test", "number": 1}
        evidence = {"files": {name: {
            "source": "def run():\n    return 1\n", "functions": [[2, 2, 4, ["test"]]],
        }}}
        self.assertEqual(select_source(patch, evidence, {"test": test}), [test])
        self.assertIsNone(select_source(patch.replace("return 1", "return 3"), evidence, {"test": test}))
        self.assertIsNone(select_source(patch.replace("return 2", "import os"), evidence, {"test": test}))

    def test_unobserved_tests_and_incomplete_passes_remain_unknown(self):
        records = [
            {"file_error": "tests/broken.py"},
            {"id": "a", "phase": "call", "result": "passed"},
            {"id": "b", "phase": "call", "result": "passed"},
            {"id": "b", "phase": "teardown", "result": "passed"},
            {"id": "c", "phase": "call", "result": "failed"},
            {"id": "c", "phase": "call", "result": "passed"},
            {"id": "c", "phase": "teardown", "result": "passed"},
        ]
        got = outcomes(records, {"tests/broken.py": {"d", "e"}, "tests/other.py": {"a", "b", "c", "f"}})
        self.assertEqual(got, {"b": "passed", "c": "failed", "d": "failed", "e": "failed"})

    def test_static_imports_follow_relative_edges_to_numbered_tests(self):
        sources = {
            "sqlglot/entry.py": "from . import target",
            "sqlglot/target.py": "",
            "sqlglot/unrelated.py": "",
            "tests/test_a.py": "from sqlglot.entry import run",
            "tests/test_b.py": "import sqlglot.unrelated",
        }
        readers = static_importers(
            {path: ast.parse(code) for path, code in sources.items()},
            ["tests/test_a.py::test_run", "tests/test_b.py::test_unrelated"],
        )
        self.assertEqual(readers["sqlglot.target"], {"tests/test_a.py::test_run"})
