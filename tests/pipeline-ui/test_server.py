"""Tests for scripts/pipeline-ui.py: HTTP API, security rules, idle shutdown and the CLI."""
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

import fixture_builder as fb
from pipeline_ui import gitinfo

SCRIPT = os.path.join(fb.SCRIPTS, "pipeline-ui.py")
_spec = importlib.util.spec_from_file_location("pipeline_ui_cli", SCRIPT)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)
TOKEN = "-".join(["test", "dashboard", "key"] * 3)  # a fixed key so the tests can build cookies


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # report the 303 itself
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def fetch(port, path, host=None, token=TOKEN, cookie=None, method="GET"):
    """(status, headers, body); token goes in the X-Pipeline-UI-Token header, None sends no key."""
    request = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method)
    if host:
        request.add_header("Host", host)
    if token:
        request.add_header("X-Pipeline-UI-Token", token)
    if cookie:
        request.add_header("Cookie", cookie)
    try:
        with OPENER.open(request, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as err:
        try:
            return err.code, err.headers, err.read()
        finally:
            err.close()


def serve_in_thread(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return thread


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.repo = fb.make_git_repo(os.path.join(cls.tmp, "repo"))
        cls.cfg = os.path.join(cls.tmp, "cfg")
        cls.ids = fb.emi_like(cls.cfg, cls.repo)
        cls.port = cli.free_port()
        cls.server = cli.make_server(cls.repo, cls.port, cfg=cls.cfg, token=TOKEN)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, host=None, token=TOKEN, cookie=None, method="GET"):
        return fetch(self.port, path, host=host, token=token, cookie=cookie, method=method)

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

    # ---- per-launch key ----
    def test_no_key_refused(self):
        for path in ("/api/runs", "/api/health", "/api/runs/" + self.run_path("run1")):
            code, headers, body = self.get(path, token=None)
            self.assertEqual(code, 403, path)
            self.assertEqual(json.loads(body), {"error": "missing or wrong dashboard key"})
            self.assertEqual(headers["Cache-Control"], "no-store")
        code, headers, body = self.get("/", token=None)
        self.assertEqual(code, 403)
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertEqual(body.decode("utf-8"),
                         "Open the dashboard with the link /pipeline-ui printed (it includes a one-time key).")

    def test_wrong_key_refused(self):
        self.assertEqual(self.get("/api/runs", token="wrong")[0], 403)
        self.assertEqual(self.get("/api/runs", token=None, cookie="pui_%d=wrong" % self.port)[0], 403)
        wrong_link = "/?t=" + "wrong"
        code = self.get(wrong_link, token=None)
        self.assertEqual(code[0], 403)
        self.assertEqual(self.get("/", token=None, cookie="pui_%d=%s" % (self.port + 1, TOKEN))[0], 403)

    def test_key_link_sets_the_port_cookie(self):
        code, headers, _body = self.get("/?t=" + TOKEN, token=None)
        self.assertEqual(code, 303)
        self.assertEqual(headers["Location"], "/")
        self.assertEqual(headers["Set-Cookie"], "pui_%d=%s; HttpOnly; SameSite=Strict; Path=/" % (self.port, TOKEN))
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_cookie_and_header_both_work(self):
        cookie = "other=1; pui_%d=%s; theme=dark" % (self.port, TOKEN)
        self.assertEqual(self.get("/api/runs", token=None, cookie=cookie)[0], 200)
        self.assertEqual(self.get("/", token=None, cookie=cookie)[0], 200)
        self.assertEqual(self.get("/api/health")[0], 200)

    def test_refused_requests_do_not_count_as_activity(self):
        self.server.last_request = 1000.0
        self.get("/api/runs", token=None)
        self.get("/api/runs", token="wrong")
        self.get("/api/runs", host="evil.example:%d" % self.port)
        self.assertEqual(self.server.last_request, 1000.0)
        self.get("/api/runs")
        self.assertGreater(self.server.last_request, 1000.0)

    # ---- every response is no-store; methods other than GET are refused ----
    def test_head_and_post_refused(self):
        for method in ("HEAD", "POST", "PUT", "DELETE", "OPTIONS"):
            code, headers, body = self.get("/api/runs", method=method)
            self.assertEqual(code, 405, method)
            self.assertEqual(headers["Allow"], "GET")
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            if method == "HEAD":
                self.assertEqual(body, b"")
            else:
                self.assertEqual(json.loads(body), {"error": "method not allowed"})
        no_key_post = self.get("/api/runs", method="POST", token=None)
        no_key_head = self.get("/", method="HEAD", token=None)
        self.assertEqual((no_key_post[0], no_key_head[0]), (403, 403))
        self.assertEqual(self.get("/api/runs", method="POST", host="evil.example:%d" % self.port)[0], 403)

    def test_stdlib_errors_are_no_store_too(self):
        code, headers, _body = self.get("/api/runs", method="PATCH")
        self.assertEqual(code, 501)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(b"GET /a b c HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
            reply = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                reply += chunk
        head = reply.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        self.assertTrue(head.startswith("HTTP/1.0 400") or head.startswith("HTTP/1.1 400"), head)
        self.assertIn("Cache-Control: no-store", head)
        self.assertIn("X-Content-Type-Options: nosniff", head)
        self.assertEqual(head.count("Cache-Control"), 1)

    def test_success_headers_not_duplicated(self):
        _code, headers, _body = self.get("/api/health")
        self.assertEqual(headers.get_all("Cache-Control"), ["no-store"])
        self.assertEqual(headers.get_all("X-Content-Type-Options"), ["nosniff"])


class PortTest(unittest.TestCase):
    def test_no_second_server_on_a_listening_port(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cfg = os.path.join(tmp, "cfg")
        port = cli.free_port()
        first = cli.make_server(tmp, port, cfg=cfg)
        try:
            try:
                second = cli.make_server(tmp, port, cfg=cfg)
            except OSError:
                second = None
            if second is not None:
                second.server_close()
            self.assertIsNone(second, "a second server could bind port %d" % port)
        finally:
            first.server_close()


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
            url = urllib.parse.urlsplit(first["url"])
            key = (urllib.parse.parse_qs(url.query).get("t") or [None])[0]
            try:
                self.assertFalse(first["reused"])
                self.assertIn("?t=", first["url"])
                self.assertEqual(cli.read_state(repo, cfg=env["CLAUDE_CONFIG_DIR"])["token"], key)
                second = call("start")
                self.assertTrue(second["reused"])
                self.assertEqual(second["url"], first["url"])
                self.assertTrue(call("status")["running"])
            finally:
                self.assertEqual(call("stop"), {"stopped": True})
            deadline = time.time() + 10
            while time.time() < deadline and cli.health(url.port, key):
                time.sleep(0.2)
            self.assertEqual(call("status"), {"running": False})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class StopStatusTest(unittest.TestCase):
    """stop and status trust only a server that accepts the state file's key and is this project's."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.cfg = os.path.join(self.tmp, "cfg")
        self.kill = mock.patch.object(cli.os, "kill").start()  # the "pid" below is this test process
        self.addCleanup(mock.patch.stopall)

    def start_server(self, project, token):
        port = cli.free_port()
        server = cli.make_server(project, port, cfg=self.cfg, token=token)
        serve_in_thread(server)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return port

    def write_state(self, port, token):
        cli.write_state(self.repo, {"pid": os.getpid(), "port": port, "project": os.path.abspath(self.repo),
                                    "token": token}, self.cfg)

    def not_ours(self, port):
        return {"error": "the server on port %d is not this project's dashboard; not stopped" % port}

    @unittest.skipIf(os.name == "nt", "Windows relies on the user profile's ACL")
    def test_state_file_is_private_on_posix(self):
        self.write_state(1, "k")
        self.assertEqual(os.stat(cli.state_path(self.repo, self.cfg)).st_mode & 0o777, 0o600)

    def test_serve_writes_the_key_to_the_state_file(self):
        servers = []
        real = cli.make_server

        def capture(*args, **kwargs):
            servers.append(real(*args, **kwargs))
            return servers[-1]

        port = cli.free_port()
        with mock.patch.object(cli, "make_server", side_effect=capture):
            thread = threading.Thread(target=cli.serve, args=(self.repo, port, self.cfg), daemon=True)
            thread.start()
            deadline = time.time() + 10
            while time.time() < deadline and not cli.read_state(self.repo, self.cfg):
                time.sleep(0.05)
        try:
            state = cli.read_state(self.repo, self.cfg)
            self.assertEqual(state["port"], port)
            self.assertEqual(state["token"], servers[0].token)
            self.assertGreaterEqual(len(state["token"]), 40)
            self.assertEqual(cli.health(port, state["token"])["project"], os.path.abspath(self.repo))
            self.assertIsNone(cli.health(port, "wrong"))
            self.assertIsNone(cli.health(port))
        finally:
            servers[0].shutdown()
            thread.join(10)

    def test_wrong_key_is_never_stopped(self):
        port = self.start_server(self.repo, "theirs")
        self.write_state(port, "ours")
        self.assertEqual(cli.cmd_stop(self.repo, self.cfg), self.not_ours(port))
        self.kill.assert_not_called()
        self.assertIsNotNone(cli.read_state(self.repo, self.cfg))
        self.assertEqual(cli.cmd_status(self.repo, self.cfg), {"running": False})

    def test_other_project_is_never_stopped(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(other)
        port = self.start_server(other, "ours")
        self.write_state(port, "ours")
        self.assertEqual(cli.cmd_stop(self.repo, self.cfg), self.not_ours(port))
        self.kill.assert_not_called()
        self.assertIsNotNone(cli.read_state(self.repo, self.cfg))

    def test_nothing_answering_clears_the_state(self):
        self.write_state(cli.free_port(), "ours")
        self.assertEqual(cli.cmd_stop(self.repo, self.cfg), {"running": False})
        self.kill.assert_not_called()
        self.assertIsNone(cli.read_state(self.repo, self.cfg))

    def test_our_server_is_stopped(self):
        port = self.start_server(self.repo, "ours")
        self.write_state(port, "ours")
        status = cli.cmd_status(self.repo, self.cfg)
        self.assertTrue(status["running"])
        self.assertEqual(status["url"], "http://127.0.0.1:%d/?t=ours" % port)
        self.assertEqual(cli.cmd_stop(self.repo, self.cfg), {"stopped": True})
        self.kill.assert_called_once_with(os.getpid(), cli.signal.SIGTERM)
        self.assertIsNone(cli.read_state(self.repo, self.cfg))


if __name__ == "__main__":
    unittest.main()
