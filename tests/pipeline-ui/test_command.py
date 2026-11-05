"""Checks for commands/pipeline-ui.md and the version bump."""
import json
import os
import unittest

import fixture_builder as fb

COMMAND = os.path.join(fb.REPO_ROOT, "commands", "pipeline-ui.md")


class CommandTest(unittest.TestCase):
    def setUp(self):
        with open(COMMAND, encoding="utf-8") as fh:
            self.text = fh.read()

    def test_frontmatter(self):
        self.assertTrue(self.text.startswith("---\ndescription: "))
        self.assertIn("\nargument-hint: ", self.text.split("\n---\n", 1)[0])

    def test_starts_the_dashboard_then_hands_off(self):
        self.assertIn('scripts/pipeline-ui.py" start --project', self.text)
        for flow in ("pipeline-all", "pipeline", "pipeline-parallel"):
            self.assertIn("`%s`" % flow, self.text)
        self.assertIn("sdlc-pipeline:<flow>", self.text)

    def test_versions(self):
        for relative in (".claude-plugin/plugin.json", ".cursor-plugin/plugin.json"):
            with open(os.path.join(fb.REPO_ROOT, relative), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["version"], "3.5.0", relative)
        with open(os.path.join(fb.REPO_ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["plugins"][0]["version"], "3.5.0")


if __name__ == "__main__":
    unittest.main()
