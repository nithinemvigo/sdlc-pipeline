"""Static checks for scripts/pipeline-dashboard.html."""
import os
import re
import unittest

import fixture_builder as fb

PAGE = os.path.join(fb.SCRIPTS, "pipeline-dashboard.html")


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

    def test_waiting_age_keeps_ticking(self):
        self.assertIn('"data-since": waiting ? since : null', self.html)
        timer = self.html[self.html.index("setInterval("):]
        timer = timer[:timer.index("}, 1000);")]
        self.assertIn('document.querySelectorAll("[data-since]").forEach((el) => '
                      '{ el.textContent = waitingLabel(Number(el.dataset.since)); });', timer)

    def test_nested_agents_follow_their_parent(self):
        self.assertIn("function nested(rows)", self.html)
        self.assertIn('const sorted = state.sort === "start" ? nested(rows) : rows.slice().sort(SORTS[state.sort]);',
                      self.html)
        body = self.html[self.html.index("function nested(rows)"):]
        body = body[:body.index("\n}\n")]
        self.assertIn("kids.get(a.id)", body)  # children are visited right after their parent, recursively
        self.assertIn("seen.has(a.id)", body)  # a parent loop cannot repeat or drop rows
        self.assertIn('" (from " + byId[a.parent].type + ")"', self.html)

    def test_key_from_fragment_to_session_storage_to_header(self):
        self.assertIn('location.hash.match(/^#k=([^&]+)$/)', self.html)
        self.assertIn('sessionStorage.setItem(KEY_STORE, ', self.html)
        self.assertIn('sessionStorage.getItem(KEY_STORE)', self.html)
        self.assertIn('history.replaceState(null, "", location.pathname + location.search);', self.html)
        self.assertIn('const KEY_HEADER = "X-Pipeline-Dashboard-Token";', self.html)
        self.assertIn("headers: { [KEY_HEADER]: key }", self.html)
        self.assertEqual(self.html.count("fetch("), 1, "every request goes through api()")
        self.assertNotIn("document.cookie", self.html)
        self.assertNotIn("?t=", self.html)

    def test_no_key_message_instead_of_the_error_loop(self):
        self.assertIn('"Open the dashboard with the link /pipeline-dashboard printed (it contains a one-time key)."',
                      self.html)
        self.assertIn("if (e.noKey) { show(noKeyView()); return; }", self.html)

    def test_html_reports_open_through_a_signed_link(self):
        self.assertIn('"/api/file-link?run="', self.html)
        self.assertIn('window.open(link.url, "_blank", "noopener")', self.html)
        self.assertNotIn('target: "_blank"', self.html)

    def test_small_fixes(self):
        self.assertIn("overflow-wrap: anywhere", self.html)
        self.assertIn("/sdlc-pipeline:pipeline-all, /sdlc-pipeline:pipeline or /sdlc-pipeline:pipeline-dashboard", self.html)
        self.assertIn('e.key === " "', self.html)


if __name__ == "__main__":
    unittest.main()
