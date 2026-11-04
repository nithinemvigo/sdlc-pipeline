"""Tests for scripts/pipeline-ui.py: HTTP API, security rules, idle shutdown and the CLI."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

import fixture_builder as fb
from pipeline_ui import gitinfo

SCRIPT = os.path.join(fb.SCRIPTS, "pipeline-ui.py")
_spec = importlib.util.spec_from_file_location("pipeline_ui_cli", SCRIPT)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = fb.make_git_repo(os.path.join(cls.tmp, "repo"))
        cls.cfg = os.path.join(cls.tmp, "cfg")
        cls.ids = fb.emi_like(cls.cfg, cls.repo)
        cls.port = cli.free_port()
        cls.server = cli.make_server(cls.repo, cls.port, cfg=cls.cfg)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, host=None):
        request = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path))
        if host:
            request.add_header("Host", host)
        try:
            with OPENER.open(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as err:
            try:
                return err.code, err.headers, err.read()
            finally:
                err.close()

    def run_path(self, key):
        return urllib.parse.quote(self.ids[key], safe="")

    def test_bound_to_loopback(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_health_and_runs(self):
        code, headers, body = self.get("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["project"], os.path.abspath(self.repo))
        self.assertEqual(headers["Cache-Control"], "no-store")
        code, _headers, body = self.get("/api/runs")
        self.assertEqual([r["id"] for r in json.loads(body)["runs"]], [self.ids["run2"], self.ids["run1"]])

    def test_run_detail_and_unknown_run(self):
        code, _headers, body = self.get("/api/runs/" + self.run_path("run1"))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)["status"], "finished")
        self.assertEqual(self.get("/api/runs/nope")[0], 404)

    def test_page(self):
        code, headers, body = self.get("/")
        self.assertEqual(code, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn(b"<title>", body)

    def test_diff_only_for_the_runs_commits(self):
        good = gitinfo.branch_commits(self.repo, "feature/calculate-emi", "master")[1]["sha"]
        other = fb.git(self.repo, "rev-parse", "fix/rounding")
        code, _headers, body = self.get("/api/diff?run=%s&commit=%s" % (self.run_path("run1"), good))
        self.assertEqual(code, 200)
        self.assertIn(b"emi.py", body)
        self.assertEqual(self.get("/api/diff?run=%s&commit=%s" % (self.run_path("run1"), other))[0], 404)

    def test_files(self):
        base = "/api/file?run=%s&key=" % self.run_path("run1")
        self.assertEqual(self.get(base + urllib.parse.quote("../../README.md"))[0], 404)
        code, _headers, body = self.get(base + "acceptance")
        self.assertEqual((code, body), (200, b"# Acceptance\n"))
        code, headers, _body = self.get(base + "html-1")
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Security-Policy"], "sandbox allow-scripts")

    def test_foreign_host_refused(self):
        self.assertEqual(self.get("/api/runs", host="evil.example:%d" % self.port)[0], 403)
        self.assertEqual(self.get("/api/runs", host="localhost:%d" % self.port)[0], 200)


class IdleTest(unittest.TestCase):
    def test_idle_server_shuts_down(self):
        tmp = tempfile.mkdtemp()
        try:
            server = cli.make_server(tmp, cli.free_port(), cfg=os.path.join(tmp, "cfg"))
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
            thread.start()
            server.last_request = time.time() - 10
            cli.start_idle_watch(server, idle_limit=1, interval=0.05)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            server.server_close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class CliTest(unittest.TestCase):
    def test_start_reuse_status_stop(self):
        tmp = tempfile.mkdtemp()
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=os.path.join(tmp, "cfg"))

        def call(*args):
            proc = subprocess.run([sys.executable, SCRIPT] + list(args) + ["--project", repo],
                                  capture_output=True, text=True, env=env, timeout=30)
            return json.loads(proc.stdout)

        try:
            first = call("start")
            self.assertIn("url", first, first)
            self.assertFalse(first["reused"])
            try:
                second = call("start")
                self.assertTrue(second["reused"])
                self.assertEqual(second["url"], first["url"])
                self.assertTrue(call("status")["running"])
            finally:
                self.assertEqual(call("stop"), {"stopped": True})
            deadline = time.time() + 10
            while time.time() < deadline and cli.health(int(first["url"].rsplit(":", 1)[1].strip("/"))):
                time.sleep(0.2)
            self.assertEqual(call("status"), {"running": False})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
