"""Checks for commands/pipeline-dashboard.md and the version bump."""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import fixture_builder as fb

COMMAND = os.path.join(fb.REPO_ROOT, "commands", "pipeline-dashboard.md")
RUNS_COMMAND = os.path.join(fb.REPO_ROOT, "commands", "pipeline-runs.md")
FAKE_SCRIPT = "import json, os, sys\nprint(json.dumps({'script': os.path.abspath(__file__), 'argv': sys.argv[1:]}))\n"


def bash_blocks(text):
    return re.findall(r"```bash\n(.*?)```", text, re.S)


def git_bash():
    """Git Bash (never the WSL launcher in System32 or WindowsApps), else None."""
    candidates = [shutil.which("bash")]
    if os.name == "nt":
        git = shutil.which("git")
        if git:
            top = os.path.dirname(os.path.dirname(os.path.realpath(git)))
            for base in (top, os.path.dirname(top)):
                candidates += [os.path.join(base, "bin", "bash.exe"), os.path.join(base, "usr", "bin", "bash.exe")]
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        lowered = os.path.normcase(path)
        if os.name == "nt" and ("system32" in lowered or "windowsapps" in lowered):
            continue
        return path
    return None


class CommandTest(unittest.TestCase):
    def setUp(self):
        with open(COMMAND, encoding="utf-8") as fh:
            self.text = fh.read()

    def test_frontmatter(self):
        self.assertTrue(self.text.startswith("---\ndescription: "))
        self.assertIn("\nargument-hint: ", self.text.split("\n---\n", 1)[0])

    def test_starts_the_dashboard_then_hands_off(self):
        self.assertIn('scripts/pipeline-dashboard.py" start --project', self.text)
        for flow in ("pipeline-all", "pipeline", "pipeline-parallel"):
            self.assertIn("`%s`" % flow, self.text)
        self.assertIn("sdlc-pipeline:<flow>", self.text)

    def test_versions(self):
        for relative in (".claude-plugin/plugin.json", ".cursor-plugin/plugin.json"):
            with open(os.path.join(fb.REPO_ROOT, relative), encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["version"], "3.6.0", relative)
        with open(os.path.join(fb.REPO_ROOT, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["plugins"][0]["version"], "3.6.0")


class FrontmatterYamlTest(unittest.TestCase):
    """An unquoted frontmatter value starting with a YAML indicator ([ ] { } & * ! | > % @ ` # ,)
    or containing ': ' or ' #' breaks or changes the parse; Claude Code then loads the command,
    agent or skill with empty or cut-short metadata."""

    INDICATOR = re.compile(r"^([\w-]+):[ \t]+([\[\]{}&*!|>%@`#,])")
    VALUE = re.compile(r"^([\w-]+):[ \t]+(\S.*)$")
    PATTERNS = (("commands", "*.md"), ("agents", "*.md"), ("skills", "*", "SKILL.md"))

    def headers(self):
        paths = []
        for parts in self.PATTERNS:
            paths += sorted(glob.glob(os.path.join(fb.REPO_ROOT, *parts)))
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if text.startswith("---\n"):
                yield os.path.relpath(path, fb.REPO_ROOT), text[4:].split("\n---\n", 1)[0]

    def test_no_unquoted_value_that_yaml_reads_differently(self):
        checked = 0
        for name, header in self.headers():
            checked += 1
            for line in header.splitlines():
                self.assertIsNone(self.INDICATOR.match(line), "%s: %s" % (name, line))
                match = self.VALUE.match(line)
                if match and match.group(2)[0] not in "\"'":
                    value = match.group(2)
                    self.assertFalse(": " in value or " #" in value, "%s: %s" % (name, line))
        self.assertGreater(checked, 0)


class RunsCommandTest(unittest.TestCase):
    """/pipeline-runs opens or stops the dashboard from any session, without a pipeline run."""

    def setUp(self):
        with open(RUNS_COMMAND, encoding="utf-8") as fh:
            self.text = fh.read()
        with open(COMMAND, encoding="utf-8") as fh:
            self.dashboard_blocks = bash_blocks(fh.read())

    def test_frontmatter(self):
        self.assertTrue(self.text.startswith("---\ndescription: "))
        self.assertIn("\nargument-hint: ", self.text.split("\n---\n", 1)[0])

    def test_same_start_and_stop_blocks_as_pipeline_dashboard(self):
        # byte-identical, so CommandScriptTest's plugin lookup checks cover this command too
        self.assertEqual(bash_blocks(self.text), self.dashboard_blocks)

    def test_never_starts_a_pipeline(self):
        self.assertNotIn("Skill", self.text)
        self.assertNotIn("sdlc-pipeline:<flow>", self.text)
        self.assertNotIn("AskUserQuestion", self.text)


class CommandScriptTest(unittest.TestCase):
    """Runs the command's Bash blocks against a fake plugin cache; the real server never starts."""

    def setUp(self):
        self.bash = git_bash()
        if not self.bash:
            self.skipTest("Git Bash not found on PATH; the command's Bash cannot be run here")
        with open(COMMAND, encoding="utf-8") as fh:
            self.blocks = bash_blocks(fh.read())
        self.assertEqual(len(self.blocks), 2, "expected the start block and the stop block")
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        self.project = os.path.join(self.tmp, "project")
        os.makedirs(self.project)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def fake_root(self, *parts):
        root = os.path.join(self.tmp, *parts)
        os.makedirs(os.path.join(root, "scripts"))
        with open(os.path.join(root, "scripts", "pipeline-dashboard.py"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(FAKE_SCRIPT)
        return root

    def run_block(self, block, **overrides):
        env = dict(os.environ)
        for name in ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT", "CLAUDE_CONFIG_DIR", "CLAUDECODE"):
            env.pop(name, None)
        env.update(HOME=self.home.replace("\\", "/"), CLAUDECODE="1")
        env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
        for name, value in overrides.items():
            if value is None:
                env.pop(name, None)
            else:
                env[name] = value
        proc = subprocess.run([self.bash, "-c", block], cwd=self.project, env=env,
                              capture_output=True, text=True, timeout=60)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, "exactly one output line expected: %r / %r" % (proc.stdout, proc.stderr))
        return json.loads(lines[0])

    def same_path(self, a, b):
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))

    def assert_called(self, result, root, command):
        self.assertIn("argv", result, result)
        self.assertTrue(self.same_path(result["script"], os.path.join(root, "scripts", "pipeline-dashboard.py")), result)
        argv = result["argv"]
        self.assertEqual(argv[:2], [command, "--project"])
        self.assertTrue(self.same_path(argv[2], self.project), argv)
        self.assertEqual(argv[3:], ["--open"] if command == "start" else [])

    def test_newest_cached_version_is_used(self):
        cache = os.path.join("home", ".claude", "plugins", "cache", "x", "sdlc-pipeline")
        self.fake_root(cache, "3.4.1")
        self.fake_root(cache, "3.9.0")  # newest by plain text order, not by version order
        os.makedirs(os.path.join(self.tmp, cache, "3.11.0"))  # no script inside: must be ignored
        newest = self.fake_root(cache, "3.10.0")
        self.assert_called(self.run_block(self.blocks[0]), newest, "start")
        self.assert_called(self.run_block(self.blocks[1]), newest, "stop")

    def installed(self, *entries):
        """Writes plugins/installed_plugins.json (version 2) with sdlc-pipeline entries (marketplace, path, version)."""
        plugins = {}
        for marketplace, path, version in entries:
            plugins.setdefault("sdlc-pipeline@" + marketplace, []).append(
                {"scope": "user", "installPath": path, "version": version})
        plugins["other@x"] = [{"scope": "user", "installPath": self.tmp, "version": "99.0.0"}]
        folder = os.path.join(self.home, ".claude", "plugins")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "installed_plugins.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 2, "plugins": plugins}, fh)

    def test_installed_version_beats_newer_cache(self):
        cache = os.path.join("home", ".claude", "plugins", "cache", "x", "sdlc-pipeline")
        installed = self.fake_root(cache, "3.4.1")
        self.fake_root(cache, "3.9.0")
        self.installed(("x", installed, "3.4.1"))  # a native path, as Claude Code writes it
        self.assert_called(self.run_block(self.blocks[0]), installed, "start")
        self.assert_called(self.run_block(self.blocks[1]), installed, "stop")

    def test_highest_installed_version_wins(self):
        a = self.fake_root("market-a", "3.9.0")
        b = self.fake_root("market-b", "3.10.0")
        self.installed(("a", a, "3.9.0"), ("b", b, "3.10.0"))
        self.assert_called(self.run_block(self.blocks[0]), b, "start")

    def test_installed_entry_without_the_script_falls_back_to_the_cache(self):
        cache = os.path.join("home", ".claude", "plugins", "cache", "x", "sdlc-pipeline")
        old = os.path.join(self.tmp, "old-install")
        os.makedirs(old)
        newest = self.fake_root(cache, "3.10.0")
        self.fake_root(cache, "3.9.0")
        self.installed(("x", old, "3.11.0"))
        self.assert_called(self.run_block(self.blocks[0]), newest, "start")

    def test_unreadable_installed_file_falls_back_to_the_cache(self):
        newest = self.fake_root("home", ".claude", "plugins", "cache", "x", "sdlc-pipeline", "3.5.0")
        with open(os.path.join(self.home, ".claude", "plugins", "installed_plugins.json"), "w") as fh:
            fh.write("{not json")
        self.assert_called(self.run_block(self.blocks[0]), newest, "start")

    def test_claude_plugin_root_wins(self):
        self.fake_root("home", ".claude", "plugins", "cache", "x", "sdlc-pipeline", "3.5.0")
        explicit = self.fake_root("explicit")
        result = self.run_block(self.blocks[0], CLAUDE_PLUGIN_ROOT=explicit.replace("\\", "/"))
        self.assert_called(result, explicit, "start")

    def test_outside_claude_code(self):
        self.fake_root("home", ".claude", "plugins", "cache", "x", "sdlc-pipeline", "3.5.0")
        self.assertEqual(self.run_block(self.blocks[0], CLAUDECODE=None), {"error": "needs-claude-code"})

    def test_no_plugin_folder(self):
        self.assertEqual(self.run_block(self.blocks[0]), {"error": "plugin folder not found"})
        self.assertEqual(self.run_block(self.blocks[1]), {"error": "plugin folder not found"})


if __name__ == "__main__":
    unittest.main()
