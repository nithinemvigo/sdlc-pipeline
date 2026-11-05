#!/usr/bin/env python3
"""Local, read-only dashboard for sdlc-pipeline runs.

    python pipeline-ui.py start  --project <repo> [--open]   start (or reuse) the server, print its URL
    python pipeline-ui.py serve  --project <repo> --port <n> run the server in the foreground
    python pipeline-ui.py stop   --project <repo>            stop this project's server
    python pipeline-ui.py status --project <repo>            is it running?

Prints one JSON line. Standard library only, Python 3.8+. Listens on 127.0.0.1 only, never writes
to the repository; its only files are a state file and a log under <config dir>/sdlc-pipeline/ui/.
"""
import argparse
import hashlib
import hmac
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from pipeline_ui import transcripts  # noqa: E402
from pipeline_ui.dashboard import Dashboard  # noqa: E402

HOST = "127.0.0.1"
FIRST_PORT = 8765
PORT_COUNT = 20
IDLE_LIMIT_S = 2 * 3600
PAGE = os.path.join(HERE, "pipeline-ui.html")
PAGE_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'")
KEY_HEADER = "X-Pipeline-UI-Token"
NO_KEY_TEXT = "Open the dashboard with the link /pipeline-ui printed (it includes a one-time key)."
FILE_TYPES = {"md": "text/plain; charset=utf-8", "json": "application/json; charset=utf-8",
              "html": "text/html; charset=utf-8"}
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def plugin_version():
    try:
        with open(os.path.join(os.path.dirname(HERE), ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            return json.load(fh).get("version", "unknown")
    except (OSError, ValueError):
        return "unknown"


def _ui_dir(cfg=None):
    return os.path.join(cfg or transcripts.config_dir(), "sdlc-pipeline", "ui")


def _digest(project):
    return hashlib.sha1(os.path.normcase(os.path.abspath(project)).encode("utf-8")).hexdigest()[:12]


def state_path(project, cfg=None):
    return os.path.join(_ui_dir(cfg), _digest(project) + ".json")


def log_path(project, cfg=None):
    return os.path.join(_ui_dir(cfg), _digest(project) + ".log")


def read_state(project, cfg=None):
    try:
        with open(state_path(project, cfg), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_state(project, data, cfg=None):
    path = state_path(project, cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        os.remove(tmp)
    except OSError:
        pass
    # 0600 on POSIX (the file holds the dashboard key); on Windows the user profile's ACL applies
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def remove_state(project, cfg=None):
    try:
        os.remove(state_path(project, cfg))
    except OSError:
        pass


def probe(port, key=None, timeout=1.0):
    """("ok", health) when a server on port accepts key; ("foreign", None) when something else
    answers (another key, another program); ("down", None) when nothing answers."""
    if not isinstance(port, int) or port <= 0:
        return "down", None
    request = urllib.request.Request("http://%s:%d/api/health" % (HOST, port))
    if key:
        request.add_header(KEY_HEADER, key)
    try:
        with _NO_PROXY.open(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        err.close()
        return "foreign", None
    except (urllib.error.URLError, OSError):
        return "down", None
    except Exception:  # not HTTP, not JSON
        return "foreign", None
    return ("ok", data) if isinstance(data, dict) else ("foreign", None)


def health(port, key=None, timeout=1.0):
    """The health reply of a server that accepts key, else None."""
    return probe(port, key, timeout)[1]


def _same_project(info, project):
    return (isinstance(info, dict) and isinstance(info.get("project"), str)
            and os.path.normcase(info["project"]) == os.path.normcase(os.path.abspath(project)))


def free_port():
    for port in range(FIRST_PORT, FIRST_PORT + PORT_COUNT):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind((HOST, port))
            return port
        except OSError:
            continue
        finally:
            probe.close()
    return None


def _url(port, key=None):
    """The dashboard address; with the key it is the one-time link that sets the cookie."""
    base = "http://%s:%d/" % (HOST, port)
    return base + "?t=" + urllib.parse.quote(key, safe="") if key else base


class Handler(BaseHTTPRequestHandler):
    server_version = "sdlc-pipeline-ui"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def end_headers(self):
        # every response, the standard library's own errors (400, 404, 501 ...) included
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        BaseHTTPRequestHandler.end_headers(self)

    def _send(self, code, body, content_type, extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload), "application/json; charset=utf-8")

    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def _same_key(self, value):
        expected = self.server.token.encode("utf-8")
        return value is not None and hmac.compare_digest(value.encode("utf-8"), expected)

    def _cookie(self, name):
        for header in self.headers.get_all("Cookie") or []:
            for part in header.split(";"):
                key, sep, value = part.strip().partition("=")
                if sep and key.strip() == name:
                    return value.strip()
        return None

    def _refuse(self, path):
        if path.startswith("/api/"):
            self._json(403, {"error": "missing or wrong dashboard key"})
        else:
            self._send(403, NO_KEY_TEXT, "text/plain; charset=utf-8")

    def _admit(self):
        """Host check, then the key (one-time link, cookie or header). Only an admitted request
        counts as activity. Returns the split URL, or None when the request was already answered."""
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return None
        url = urllib.parse.urlsplit(self.path)
        link = urllib.parse.parse_qs(url.query).get("t") if self.command == "GET" and url.path == "/" else None
        if link:
            if not self._same_key(link[0]):
                self._refuse(url.path)
                return None
            self.server.touch()
            cookie = "%s=%s; HttpOnly; SameSite=Strict; Path=/" % (self.server.cookie_name, self.server.token)
            self._send(303, b"", "text/plain; charset=utf-8", {"Location": "/", "Set-Cookie": cookie})
            return None
        sent = self.headers.get(KEY_HEADER)
        if not (self._same_key(sent) or self._same_key(self._cookie(self.server.cookie_name))):
            self._refuse(url.path)
            return None
        self.server.touch()
        return url

    def do_GET(self):
        url = self._admit()
        if url is None:
            return
        query = urllib.parse.parse_qs(url.query)

        def one(name):
            return (query.get(name) or [""])[0]

        dash = self.server.dashboard
        try:
            if url.path == "/":
                with open(PAGE, "rb") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8", {"Content-Security-Policy": PAGE_CSP})
            elif url.path == "/api/health":
                self._json(200, {"project": dash.repo, "version": plugin_version(), "pid": os.getpid()})
            elif url.path == "/api/runs":
                self._json(200, dash.runs())
            elif url.path.startswith("/api/runs/"):
                detail = dash.run(urllib.parse.unquote(url.path[len("/api/runs/"):]))
                if detail is None:
                    self._json(404, {"error": "unknown run"})
                else:
                    self._json(200, detail)
            elif url.path == "/api/diff":
                text = dash.diff(one("run"), one("commit"))
                if text is None:
                    self._json(404, {"error": "unknown commit for this run"})
                else:
                    self._send(200, text, "text/plain; charset=utf-8")
            elif url.path == "/api/file":
                found = dash.file(one("run"), one("key"))
                if found is None:
                    self._json(404, {"error": "unknown file for this run"})
                else:
                    path, kind = found
                    with open(path, "rb") as fh:
                        data = fh.read()
                    extra = {"Content-Security-Policy": "sandbox allow-scripts"} if kind == "html" else None
                    self._send(200, data, FILE_TYPES.get(kind, "text/plain; charset=utf-8"), extra)
            else:
                self._json(404, {"error": "not found"})
        except Exception as exc:  # never leak a traceback to the page
            try:
                self._json(500, {"error": type(exc).__name__})
            except Exception:
                pass

    def _not_allowed(self):
        if self._admit() is None:
            return
        self._send(405, json.dumps({"error": "method not allowed"}), "application/json; charset=utf-8",
                   {"Allow": "GET"})

    do_HEAD = do_POST = do_PUT = do_DELETE = do_OPTIONS = _not_allowed


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second socket bind a port that is already listening.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        ThreadingHTTPServer.server_bind(self)

    def __init__(self, port, dashboard, token=None):
        ThreadingHTTPServer.__init__(self, (HOST, port), Handler)
        self.dashboard = dashboard
        self.token = token or secrets.token_urlsafe(32)  # the per-launch dashboard key
        self.cookie_name = "pui_%d" % self.server_address[1]  # cookies are not port-scoped
        self.last_request = time.time()
        self.stopping = threading.Event()

    def touch(self):
        self.last_request = time.time()


def make_server(project, port, cfg=None, token=None):
    return Server(port, Dashboard(project, cfg=cfg), token)


def start_idle_watch(server, idle_limit=IDLE_LIMIT_S, interval=60.0):
    def watch():
        while not server.stopping.wait(interval):
            if time.time() - server.last_request > idle_limit:
                server.stopping.set()
                server.shutdown()
                return

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return thread


def serve(project, port, cfg=None, idle_limit=IDLE_LIMIT_S):
    server = make_server(project, port, cfg)
    write_state(project, {"pid": os.getpid(), "port": port, "project": server.dashboard.repo,
                          "token": server.token, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, cfg)
    start_idle_watch(server, idle_limit)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.stopping.set()
        server.server_close()
        state = read_state(project, cfg)
        if state and state.get("pid") == os.getpid():
            remove_state(project, cfg)


def cmd_start(project, open_browser=False, cfg=None):
    project = os.path.abspath(project)
    state = read_state(project, cfg)
    if state:
        info = health(state.get("port"), state.get("token"))
        if _same_project(info, project):
            url = _url(state["port"], state["token"])
            if open_browser:
                webbrowser.open(url)
            return {"url": url, "pid": info.get("pid"), "reused": True}
        remove_state(project, cfg)  # a server that does not take our key is not ours: leave it alone
    port = free_port()
    if port is None:
        return {"error": "no free port in %d-%d" % (FIRST_PORT, FIRST_PORT + PORT_COUNT - 1)}
    os.makedirs(_ui_dir(cfg), exist_ok=True)
    command = [sys.executable, os.path.abspath(__file__), "serve", "--project", project, "--port", str(port)]
    with open(log_path(project, cfg), "ab") as log:
        options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": log, "close_fds": True}
        if os.name == "nt":
            options["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        proc = subprocess.Popen(command, **options)
    deadline = time.time() + 5
    while time.time() < deadline:
        state = read_state(project, cfg) or {}
        if state.get("port") == port and _same_project(health(port, state.get("token"), timeout=0.5), project):
            url = _url(port, state["token"])
            if open_browser:
                webbrowser.open(url)
            return {"url": url, "pid": proc.pid, "reused": False}
        if proc.poll() is not None:
            return {"error": "dashboard exited with code %s; see %s" % (proc.returncode, log_path(project, cfg))}
        time.sleep(0.2)
    return {"error": "dashboard did not answer on port %d within 5 s; see %s" % (port, log_path(project, cfg))}


def cmd_stop(project, cfg=None):
    state = read_state(project, cfg)
    if not state:
        return {"running": False}
    port = state.get("port")
    kind, info = probe(port, state.get("token"))
    if kind == "down":  # nothing answers: the state file is stale
        remove_state(project, cfg)
        return {"running": False}
    if kind != "ok" or not _same_project(info, project) or info.get("pid") != state.get("pid"):
        return {"error": "the server on port %s is not this project's dashboard; not stopped" % port}
    try:
        os.kill(state["pid"], signal.SIGTERM)
    except OSError as exc:
        return {"error": "could not stop pid %s: %s" % (state["pid"], exc)}
    remove_state(project, cfg)
    return {"stopped": True}


def cmd_status(project, cfg=None):
    state = read_state(project, cfg)
    if state:
        info = health(state.get("port"), state.get("token"))
        if _same_project(info, project):
            return {"running": True, "url": _url(state["port"], state["token"]), "pid": info.get("pid")}
    return {"running": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local, read-only dashboard for sdlc-pipeline runs.")
    sub = parser.add_subparsers(dest="command")
    sub.required = True
    for name in ("start", "serve", "stop", "status"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True)
        if name == "start":
            command.add_argument("--open", action="store_true")
        if name == "serve":
            command.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == "serve":
        serve(args.project, args.port)
        return 0
    if args.command == "start":
        result = cmd_start(args.project, args.open)
    elif args.command == "stop":
        result = cmd_stop(args.project)
    else:
        result = cmd_status(args.project)
    print(json.dumps(result))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
