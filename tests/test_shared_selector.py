import difflib
import unittest

from selector import select_patch


def patch(path, before, after):
    return f"diff --git a/{path} b/{path}\n" + "".join(difflib.unified_diff(
        before.splitlines(True), after.splitlines(True), "a/" + path, "b/" + path,
    ))


class SharedSelectorTests(unittest.TestCase):
    module = "tests/test_helpers.py"
    fixture = "tests/fixtures/optimizer/nested/data.sql"
    original = (
        "class TestHelpers:\n"
        "    def setUpClass(cls):\n"
        "        cls.value = 1\n"
        "    def check(self, expected):\n"
        "        self.assertEqual(expected, self.value)\n"
    )

    def select(self, change, skipped=()):
        shared = {
            "fixtures": {self.fixture: ["fixture", "shared-setup"]},
            "test_modules": {self.module: {"source": self.original, "readers": ["local", "importer"]}},
        }
        by_id = {name: name for name in ("fixture", "shared-setup", "local", "importer") if name not in skipped}
        return select_patch(change, {}, {"format": 1, "files": {}}, by_id, skipped=skipped, shared=shared)

    def test_union_includes_test_importers_and_shared_setup_readers(self):
        changed = self.original.replace("assertEqual(expected,", "assertEqual(expected.upper(),")
        changes = patch(self.module, self.original, changed) + patch(self.fixture, "SELECT 1\n", "SELECT 2\n")
        self.assertEqual(self.select(changes), ["fixture", "importer", "local", "shared-setup"])
        self.assertEqual(self.select(changes, skipped=("importer",)), ["fixture", "local", "shared-setup"])

    def test_unknown_changes_force_full_suite(self):
        edits = (
            patch(self.module, self.original, self.original.replace("cls.value = 1", "cls.value = 2")),
            patch(self.module, self.original, self.original.replace("self.value)", "self.value(,)")),
            patch(self.module, self.original, "import missing\n" + self.original),
            patch(self.module, self.original, self.original.replace("def check(", "def collect(")),
            patch(self.module, self.original, self.original.replace("expected,", "fabricate(),", 1)),
            patch(self.fixture.replace("data.sql", "unknown.sql"), "SELECT 1\n", "SELECT 2\n"),
        )
        known = patch(self.fixture, "SELECT 1\n", "SELECT 3\n")
        for unresolved in edits:
            with self.subTest(change=unresolved):
                self.assertIsNone(self.select(known + unresolved))
