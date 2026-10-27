"""Every problem Deck Doctor can report must have a fix guide in docs/fixes/."""

import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
INFO_ONLY = {"no_launch", "running", "looks_ok", "plugins_ok", "changed_since_launch"}


def finding_ids() -> set:
    ids = set()
    for name in ("diagnose.py", "health.py", "emulator.py"):
        with open(os.path.join(ROOT, "py_modules", "deck_doctor", name)) as f:
            src = f.read()
        ids |= set(re.findall(r'Finding\(\s*"(\w+)"', src))
        ids |= set(re.findall(r'^\s*\("(\w+)", "[A-Z]', src, re.M))  # (id, title, detail) tables
    return ids


class Guides(unittest.TestCase):
    def test_every_problem_has_a_guide(self):
        ids = finding_ids() - INFO_ONLY
        self.assertGreater(len(ids), 10)
        missing = [i for i in sorted(ids) if not os.path.exists(os.path.join(ROOT, "docs", "fixes", f"{i}.md"))]
        self.assertEqual(missing, [])

    def test_frontend_guide_list_matches_docs(self):
        with open(os.path.join(ROOT, "src", "index.tsx")) as f:
            m = re.search(r"const GUIDES = new Set\(\[(.*?)\]\)", f.read(), re.S)
        listed = set(re.findall(r'"(\w+)"', m.group(1)))
        docs = {n[:-3] for n in os.listdir(os.path.join(ROOT, "docs", "fixes")) if n != "README.md"}
        self.assertEqual(listed, docs)


if __name__ == "__main__":
    unittest.main()
