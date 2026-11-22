import gzip
import json
from io import BytesIO
import unittest
from pathlib import Path
from unittest.mock import patch

import selector
from source_selector import load_source_map


class IntegratedSelectorTests(unittest.TestCase):
    def setUp(self):
        self.source = "sqlglot/example.py"
        self.fixture = "tests/fixtures/optimizer/example.sql"
        self.by_id = {"source-reader": {"number": 0}, "fixture-reader": {"number": 1}}
        self.fixtures = {self.fixture: ["fixture-reader"]}
        self.evidence = {
            "base_commit": selector.BASE,
            "reference_ids": list(self.by_id),
            "files": {self.source: {
                "source": "def run():\n    return 1\n",
                "functions": [[2, 2, 4, ["source-reader"]]],
            }},
        }
        self.source_patch = self.diff(self.source, " def run():\n-    return 1\n+    return 2", "-1,2 +1,2")
        self.fixture_patch = self.diff(self.fixture, "-SELECT 1\n+SELECT 2")

    @staticmethod
    def diff(path, lines, positions="-1 +1"):
        return (
            f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ {positions} @@\n{lines}\n"
        )

    def test_fixture_selection_precedes_source_analysis(self):
        with patch("selector.select_source") as source:
            picked = selector.select_patch(self.fixture_patch, self.fixtures, self.evidence, self.by_id)
        source.assert_not_called()
        self.assertEqual(picked, [self.by_id["fixture-reader"]])

    def test_source_selection_and_mixed_patch_fallback(self):
        self.assertEqual(
            selector.select_patch(self.source_patch, self.fixtures, self.evidence, self.by_id),
            [self.by_id["source-reader"]],
        )
        self.assertIsNone(selector.select_patch(
            self.fixture_patch + self.source_patch, self.fixtures, self.evidence, self.by_id,
        ))
        self.assertIsNone(selector.select_patch(
            self.source_patch.replace("+    return 2", "+    return )"), self.fixtures, self.evidence, self.by_id,
        ))

    def test_map_failures_preserve_fixture_selection_and_disable_source_selection(self):
        def packed(body):
            return BytesIO(gzip.compress(json.dumps(body).encode("utf-8")))

        scenarios = {
            "missing": Path(__file__) / "map.json.gz",
            "corrupt": BytesIO(b"not gzip"),
            "truncated": BytesIO(gzip.compress(b"{}")[:-2]),
            "wrong commit": packed({**self.evidence, "base_commit": "other"}),
            "unknown test": packed({**self.evidence, "reference_ids": ["fixture-reader"]}),
            "invalid entry": packed({**self.evidence, "files": {self.source: None}}),
        }
        for scenario, stream in scenarios.items():
            with self.subTest(scenario=scenario):
                source_map = load_source_map(stream, selector.BASE, self.by_id)
                self.assertIsNone(source_map)
                self.assertIsNone(selector.select_patch(
                    self.source_patch, self.fixtures, source_map, self.by_id,
                ))
                self.assertEqual(
                    selector.select_patch(self.fixture_patch, self.fixtures, source_map, self.by_id),
                    [self.by_id["fixture-reader"]],
                )
        self.assertEqual(load_source_map(packed(self.evidence), selector.BASE, self.by_id), self.evidence)
