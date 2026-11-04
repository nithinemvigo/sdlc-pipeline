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
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
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
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def remove_state(project, cfg=None):
    try:
        os.remove(state_path(project, cfg))
    except OSError:
        pass


def health(port, timeout=1.0):
    if not isinstance(port, int) or port <= 0:
        return None
    try:
        with _NO_PROXY.open("http://%s:%d/api/health" % (HOST, port), timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


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


def _url(port):
    return "http://%s:%d/" % (HOST, port)


class Handler(BaseHTTPRequestHandler):
    server_version = "sdlc-pipeline-ui"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, code, body, content_type, extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload), "application/json; charset=utf-8")

    def _host_ok(self):
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in ("127.0.0.1:%d" % port, "localhost:%d" % port)

    def do_GET(self):
        self.server.touch()
        if not self._host_ok():
            self._json(403, {"error": "forbidden host"})
            return
        url = urllib.parse.urlsplit(self.path)
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


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, dashboard):
        ThreadingHTTPServer.__init__(self, (HOST, port), Handler)
        self.dashboard = dashboard
        self.last_request = time.time()
        self.stopping = threading.Event()

    def touch(self):
        self.last_request = time.time()


def make_server(project, port, cfg=None):
    return Server(port, Dashboard(project, cfg=cfg))


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
                          "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}, cfg)
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
        info = health(state.get("port"))
        if _same_project(info, project):
            if open_browser:
                webbrowser.open(_url(state["port"]))
            return {"url": _url(state["port"]), "pid": info.get("pid"), "reused": True}
        remove_state(project, cfg)
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
        if _same_project(health(port, timeout=0.5), project):
            if open_browser:
                webbrowser.open(_url(port))
            return {"url": _url(port), "pid": proc.pid, "reused": False}
        if proc.poll() is not None:
            return {"error": "dashboard exited with code %s; see %s" % (proc.returncode, log_path(project, cfg))}
        time.sleep(0.2)
    return {"error": "dashboard did not answer on port %d within 5 s; see %s" % (port, log_path(project, cfg))}


def cmd_stop(project, cfg=None):
    state = read_state(project, cfg)
    if not state:
        return {"running": False}
    info = health(state.get("port"))
    if _same_project(info, project) and info.get("pid") == state.get("pid"):
        try:
            os.kill(state["pid"], signal.SIGTERM)
        except OSError as exc:
            return {"error": "could not stop pid %s: %s" % (state["pid"], exc)}
    remove_state(project, cfg)
    return {"stopped": True}


def cmd_status(project, cfg=None):
    state = read_state(project, cfg)
    if state:
        info = health(state.get("port"))
        if _same_project(info, project):
            return {"running": True, "url": _url(state["port"]), "pid": info.get("pid")}
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
