"""Tests for scripts/pipeline-dashboard.py: HTTP API, security rules, idle shutdown and the CLI."""
import importlib.util
import hashlib
import hmac
import json
import os
import pathlib
import secrets
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
from pipeline_dashboard import gitinfo

SCRIPT = os.path.join(fb.SCRIPTS, "pipeline-dashboard.py")
_spec = importlib.util.spec_from_file_location("pipeline_dashboard_cli", SCRIPT)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)
TOKEN = "-".join(["test", "dashboard", "key"] * 3)  # a fixed key so the tests can build cookies


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # report the 303 itself
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def fetch(port, path, host=None, token=TOKEN, cookie=None, method="GET"):
    """(status, headers, body); token goes in the X-Pipeline-Dashboard-Token header, None sends no key."""
    request = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), method=method)
    if host:
        request.add_header("Host", host)
    if token:
        request.add_header("X-Pipeline-Dashboard-Token", token)
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

    def anon(self, path, **kwargs):
        """The same request with no key at all."""
        kwargs["token"] = None
        return self.get(path, **kwargs)

    def sign(self, run, key, exp):
        message = ("%s\n%s\n%d" % (run, key, exp)).encode("utf-8")
        return hmac.new(TOKEN.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def file_url(self, run, key, exp, sig):
        return "/api/file?" + urllib.parse.urlencode({"run": run, "key": key, "exp": exp, "sig": sig})

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

    # ---- per-launch key: only in the X-Pipeline-Dashboard-Token header ----
    def test_page_needs_no_key(self):
        code, headers, body = self.anon("/")
        self.assertEqual(code, 200)
        self.assertIn(b"<title>", body)
        self.assertIsNone(headers["Set-Cookie"])

    def test_every_api_route_needs_the_key(self):
        for path in ("/api/runs", "/api/health", "/api/runs/" + self.run_path("run1"),
                     "/api/diff?run=x&commit=y", "/api/file?run=%s&key=acceptance" % self.run_path("run1"),
                     "/api/file-link?run=%s&key=html-1" % self.run_path("run1"), "/api/nope", "/favicon.ico"):
            code, headers, body = self.anon(path)
            self.assertEqual(code, 403, path)
            self.assertEqual(json.loads(body), {"error": "missing or wrong dashboard key"})
            self.assertEqual(headers["Cache-Control"], "no-store")

    def test_wrong_key_and_cookies_refused(self):
        self.assertEqual(self.get("/api/runs", token="wrong")[0], 403)
        for cookie in ("pui_%d=%s" % (self.port, TOKEN), "t=%s" % TOKEN):
            self.assertEqual(self.anon("/api/runs", cookie=cookie)[0], 403, cookie)
        old_link = self.anon("/?t=" + TOKEN)  # the round-1 link sets nothing now
        self.assertEqual(old_link[0], 200)
        self.assertIsNone(old_link[1]["Set-Cookie"])

    def test_no_set_cookie_anywhere(self):
        paths = ["/", "/?t=" + TOKEN, "/api/runs", "/api/health", "/api/nope",
                 "/api/file-link?run=%s&key=html-1" % self.run_path("run1")]
        for path in paths:
            for token in (TOKEN, "wrong"):
                _code, headers, _body = self.get(path, token=token)
                self.assertIsNone(headers["Set-Cookie"], path)

    def test_refused_requests_do_not_count_as_activity(self):
        self.server.last_request = 1000.0
        self.anon("/api/runs")
        self.get("/api/runs", token="wrong")
        self.get("/api/runs", host="evil.example:%d" % self.port)
        self.anon("/")  # the page itself holds no data and is not activity
        self.assertEqual(self.server.last_request, 1000.0)
        self.get("/api/runs")
        self.assertGreater(self.server.last_request, 1000.0)

    # ---- signed 60-second links for HTML artifacts ----
    def test_signed_file_link_opens_the_html_report(self):
        run = self.ids["run1"]
        code, _headers, body = self.get("/api/file-link?run=%s&key=html-1" % self.run_path("run1"))
        self.assertEqual(code, 200)
        url = json.loads(body)["url"]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(urllib.parse.urlsplit(url).path, "/api/file")
        self.assertEqual((query["run"], query["key"]), ([run], ["html-1"]))
        exp = int(query["exp"][0])
        self.assertTrue(time.time() + 50 < exp <= time.time() + 61)
        self.assertEqual(query["sig"], [self.sign(run, "html-1", exp)])
        code, headers, body = self.anon(url)
        self.assertEqual(code, 200)
        self.assertEqual(headers["Content-Security-Policy"], "sandbox allow-scripts")
        self.assertIn(b"<title>", body)

    def test_bad_signatures_refused(self):
        run, other = self.ids["run1"], self.ids["run2"]
        now = int(time.time())
        good = self.sign(run, "html-1", now + 60)
        self.assertEqual(self.anon(self.file_url(run, "html-1", now + 60, good))[0], 200)
        tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
        cases = {
            "tampered": self.file_url(run, "html-1", now + 60, tampered),
            "exp changed": self.file_url(run, "html-1", now + 61, good),
            "expired": self.file_url(run, "html-1", now - 1, self.sign(run, "html-1", now - 1)),
            "too far ahead": self.file_url(run, "html-1", now + 500, self.sign(run, "html-1", now + 500)),
            "other run": self.file_url(other, "html-1", now + 60, good),
            "other file": self.file_url(run, "acceptance", now + 60, good),
            "not a number": self.file_url(run, "html-1", "soon", good),
            "no sig": "/api/file?" + urllib.parse.urlencode({"run": run, "key": "html-1", "exp": now + 60}),
        }
        for name, url in cases.items():
            code, _headers, body = self.anon(url)
            self.assertEqual(code, 403, name)
            self.assertEqual(json.loads(body), {"error": "missing or wrong dashboard key"}, name)
        # a signature works for /api/file only
        diff = "/api/diff?" + urllib.parse.urlencode({"run": run, "commit": "0" * 40, "exp": now + 60, "sig": good})
        self.assertEqual(self.anon(diff)[0], 403)

    def test_file_link_needs_a_known_file(self):
        self.assertEqual(self.get("/api/file-link?run=%s&key=nope" % self.run_path("run1"))[0], 404)
        self.assertEqual(self.anon("/api/file-link?run=%s&key=html-1" % self.run_path("run1"))[0], 403)

    def test_referrer_policy_on_every_response(self):
        responses = [self.anon("/"), self.get("/api/runs"), self.anon("/api/runs"), self.get("/api/nope"),
                     self.get("/api/runs", method="POST"), self.get("/api/runs", method="PATCH"),
                     self.get("/api/runs", host="evil.example:%d" % self.port)]
        for code, headers, _body in responses:
            self.assertEqual(headers.get_all("Referrer-Policy"), ["no-referrer"], code)

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
        no_key_post = self.anon("/api/runs", method="POST")
        no_key_head = self.anon("/", method="HEAD")
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
        self.assertIn("Referrer-Policy: no-referrer", head)
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
            key = (urllib.parse.parse_qs(url.fragment).get("k") or [None])[0]
            try:
                self.assertFalse(first["reused"])
                self.assertIn("/#k=", first["url"])
                self.assertNotIn("?", first["url"])
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


class VersionRestartTest(unittest.TestCase):
    """start replaces a dashboard left running by an older plugin version."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.abspath(os.path.join(self.tmp, "repo"))
        os.makedirs(self.repo)
        self.cfg = os.path.join(self.tmp, "cfg")
        cli.write_state(self.repo, {"pid": 4242, "port": 8799, "project": self.repo, "token": "k"}, self.cfg)
        self.stop = mock.patch.object(cli, "cmd_stop", return_value={"stopped": True}).start()
        self.no_port = mock.patch.object(cli, "free_port", return_value=None).start()  # never spawn
        self.addCleanup(mock.patch.stopall)

    def reply(self, version):
        return mock.patch.object(cli, "health", return_value={"project": self.repo, "version": version, "pid": 4242})

    def test_same_version_is_reused(self):
        with self.reply(cli.plugin_version()):
            result = cli.cmd_start(self.repo, cfg=self.cfg)
        self.assertEqual(result, {"url": "http://127.0.0.1:8799/#k=k", "pid": 4242, "reused": True})
        self.stop.assert_not_called()

    def test_older_version_is_stopped_and_replaced(self):
        with self.reply("0.0.1"):
            result = cli.cmd_start(self.repo, cfg=self.cfg)
        self.stop.assert_called_once_with(self.repo, self.cfg)
        self.assertEqual(result, {"error": "no free port in 8765-8784"})  # it went on to start a new one

    def test_older_version_that_cannot_be_stopped_is_reported(self):
        self.stop.return_value = {"error": "the server on port 8799 is not this project's dashboard; not stopped"}
        with self.reply("0.0.1"):
            result = cli.cmd_start(self.repo, cfg=self.cfg)
        self.assertEqual(result, self.stop.return_value)
        self.no_port.assert_not_called()


class SpawnTest(unittest.TestCase):
    def test_server_gets_a_hidden_console_not_a_detached_one(self):
        """DETACHED_PROCESS leaves the server without a console, so Windows opens a window for
        every console program it runs (git). A hidden console is inherited by those children."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        proc = mock.Mock(pid=1, returncode=1)
        proc.poll.return_value = 1
        with mock.patch.object(cli, "free_port", return_value=8790),                 mock.patch.object(cli.subprocess, "Popen", return_value=proc) as popen:
            result = cli.cmd_start(tmp, cfg=os.path.join(tmp, "cfg"))
        self.assertIn("error", result)
        options = popen.call_args[1]
        if os.name == "nt":
            self.assertEqual(options["creationflags"] & 0x08000000, 0x08000000)  # CREATE_NO_WINDOW
            self.assertEqual(options["creationflags"] & 0x00000008, 0)  # not DETACHED_PROCESS
        else:
            self.assertTrue(options["start_new_session"])


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
        with open(cli.open_path(self.repo, self.cfg), "w", encoding="utf-8") as fh:
            fh.write("redirect")
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
        self.assertIsNone(cli.read_state(self.repo, self.cfg))
        self.assertFalse(os.path.exists(cli.open_path(self.repo, self.cfg)))  # serve() cleanup

    def test_start_open_uses_a_redirect_file(self):
        key = secrets.token_urlsafe(32)
        port = self.start_server(self.repo, key)
        self.write_state(port, key)
        opened = []
        with mock.patch.object(cli.webbrowser, "open", side_effect=lambda url, *a, **k: opened.append(url)):
            result = cli.cmd_start(self.repo, open_browser=True, cfg=self.cfg)
        self.assertEqual(result["url"], "http://127.0.0.1:%d/#k=%s" % (port, key))  # the JSON line keeps it
        path = cli.open_path(self.repo, self.cfg)
        self.assertEqual(opened, [pathlib.Path(path).as_uri()])
        self.assertNotIn(key, opened[0])
        with open(path, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn('<meta http-equiv="refresh" content="0; url=%s">' % result["url"], page)
        self.assertIn('<a href="%s">' % result["url"], page)
        if os.name != "nt":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(cli.cmd_stop(self.repo, self.cfg), {"stopped": True})
        self.assertFalse(os.path.exists(path))

    def test_state_without_a_usable_key_is_stale(self):
        def bad_states():
            base = {"pid": os.getpid(), "port": 8799, "project": os.path.abspath(self.repo)}
            yield dict(base)
            for token in ("", 42, None, ["k"]):
                yield dict(base, token=token)

        never = mock.patch.object(cli, "probe", side_effect=AssertionError("a keyless state was probed"))
        with never, mock.patch.object(cli, "free_port", return_value=None):
            for state in bad_states():
                for command in ("start", "stop", "status"):
                    cli.write_state(self.repo, state, self.cfg)
                    if command == "start":
                        result = cli.cmd_start(self.repo, cfg=self.cfg)
                        self.assertEqual(result, {"error": "no free port in 8765-8784"}, state)  # went on to a fresh start
                    elif command == "stop":
                        self.assertEqual(cli.cmd_stop(self.repo, self.cfg), {"running": False}, state)
                    else:
                        self.assertEqual(cli.cmd_status(self.repo, self.cfg), {"running": False}, state)
                    self.assertFalse(os.path.exists(cli.state_path(self.repo, self.cfg)), (command, state))
        self.kill.assert_not_called()

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
        self.assertEqual(status["url"], "http://127.0.0.1:%d/#k=ours" % port)
        self.assertEqual(cli.cmd_stop(self.repo, self.cfg), {"stopped": True})
        self.kill.assert_called_once_with(os.getpid(), cli.signal.SIGTERM)
        self.assertIsNone(cli.read_state(self.repo, self.cfg))


if __name__ == "__main__":
    unittest.main()
