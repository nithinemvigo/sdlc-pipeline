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

    def test_overlapping_refreshes_are_guarded(self):
        self.assertIn("const seq = ++state.seq;", self.html)
        self.assertGreaterEqual(self.html.count("seq !== state.seq"), 2)

    def test_unchanged_polls_do_not_rebuild_the_page(self):
        self.assertIn("state.dirty", self.html)
        self.assertIn("state.last.text === text", self.html)
        self.assertIn("if (!unchanged) show(", self.html)
        self.assertIn("function redraw() { state.dirty = true; refresh(); }", self.html)
        self.assertNotIn("refresh(); return; }", self.html)  # toggles go through redraw()

    def test_part_shows_the_error_only_when_data_is_missing(self):
        self.assertIn("function part(title, error, data, build)", self.html)
        self.assertIn("data === null || data === undefined", self.html)
        self.assertIn('class: "warn" }, error)', self.html)

    def test_session_and_unrendered_errors_are_shown(self):
        self.assertIn("errs.session", self.html)
        self.assertIn("This session could not be read", self.html)
        self.assertIn("PART_ERRORS.indexOf(k) < 0", self.html)

    def test_small_fixes(self):
        self.assertIn("overflow-wrap: anywhere", self.html)
        self.assertIn("/sdlc-pipeline:pipeline-all, /sdlc-pipeline:pipeline or /sdlc-pipeline:pipeline-ui", self.html)
        self.assertIn('e.key === " "', self.html)


if __name__ == "__main__":
    unittest.main()
