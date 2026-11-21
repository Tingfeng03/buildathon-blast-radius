import unittest
import selector


def patch(path, body="-old\n+new", counts="-1 +1"):
    return f"diff --git a/{path} b/{path}\nindex 123..456 100644\n--- a/{path}\n+++ b/{path}\n@@ {counts} @@\n{body}\n"


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.a = "tests/fixtures/optimizer/a.sql"
        self.b = "tests/fixtures/optimizer/b.sql"
        self.by_id = {"one": {"id": "one"}, "two": {"id": "two"}}
        self.mapping = {self.a: ["one"], self.b: ["one", "two"]}

    def test_schedule(self):
        self.assertEqual(selector.schedule([]), [])
        self.assertEqual(len(selector.schedule([{"number": 1, "ms": 4000}, {"number": 2, "ms": 4000}])), 2)
        self.assertEqual(len(selector.schedule([{"number": 1, "ms": 2000}, {"number": 2, "ms": 2000}])), 1)

    def test_union_and_insertion(self):
        result = selector.select(patch(self.a) + patch(self.b), self.mapping, self.by_id)
        self.assertEqual({r["id"] for r in result}, {"one", "two"})
        self.assertIsNotNone(selector.select(patch(self.a, "+new", "-0,0 +1"), self.mapping, self.by_id))

    def test_fallbacks(self):
        for text in (patch(self.a) + "diff --git a/x b/x\n", patch(self.a).replace("b/" + self.a, "b/other"), patch(self.a).replace("+new", ""), patch(self.b)):
            self.assertIsNone(selector.select(text, {self.a: ["one"]}, self.by_id))
        self.assertIsNone(selector.select(patch(self.b), self.mapping, {"one": self.by_id["one"]}))


if __name__ == "__main__":
    unittest.main()
