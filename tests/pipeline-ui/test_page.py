"""Static checks for scripts/pipeline-ui.html."""
import os
import re
import unittest

import fixture_builder as fb

PAGE = os.path.join(fb.SCRIPTS, "pipeline-ui.html")


class PageTest(unittest.TestCase):
    def setUp(self):
        with open(PAGE, encoding="utf-8") as fh:
            self.html = fh.read()

    def test_no_external_resources(self):
        self.assertIsNone(re.search(r"""(src|href)\s*=\s*["']https?://""", self.html))
        self.assertNotIn("@import", self.html)
        self.assertNotIn("fonts.googleapis", self.html)

    def test_never_renders_markup_from_data(self):
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(banned, self.html, banned)

    def test_title_dark_mode_and_mobile(self):
        self.assertIn("<title>Pipeline runs</title>", self.html)
        self.assertIn("prefers-color-scheme: dark", self.html)
        self.assertIn('name="viewport"', self.html)

    def test_uses_every_api_route(self):
        for route in ("/api/runs", "/api/diff", "/api/file"):
            self.assertIn(route, self.html)


if __name__ == "__main__":
    unittest.main()
