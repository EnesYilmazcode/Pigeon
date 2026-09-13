"""CLAUDE.md is how Claude learns the schema, so it has to keep up with the data."""
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class SchemaDocTest(unittest.TestCase):
    def test_every_field_is_documented(self):
        with open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8") as f:
            documented = set(re.findall(r"`([a-zA-Z]+)`", f.read()))
        with open(os.path.join(ROOT, "contacts.example.json"), encoding="utf-8") as f:
            used = {k for row in json.load(f) for k in row}
        self.assertEqual(sorted(used - documented), [])

    def test_statuses_match_the_page(self):
        with open(os.path.join(ROOT, "app.html"), encoding="utf-8") as f:
            page = re.search(r"var STATUSES = \[([^\]]*)\]", f.read()).group(1)
        with open(os.path.join(ROOT, "CLAUDE.md"), encoding="utf-8") as f:
            row = [line for line in f if line.startswith("| `status`")][0]
        self.assertEqual(re.findall(r'"(\w+)"', page), re.findall(r"`(\w+)`", row)[1:])


if __name__ == "__main__":
    unittest.main()
