"""Serve the EMI-shaped fixture so the page can be checked in a browser.

    python -I tests/pipeline-ui/demo_server.py      (Ctrl+C to stop)
"""
import importlib.util
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixture_builder as fb  # noqa: E402

spec = importlib.util.spec_from_file_location("pipeline_ui_cli", os.path.join(fb.SCRIPTS, "pipeline-ui.py"))
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def main():
    tmp = tempfile.mkdtemp(prefix="pipeline-ui-demo-")
    repo = fb.make_git_repo(os.path.join(tmp, "repo"))
    cfg = os.path.join(tmp, "cfg")
    fb.emi_like(cfg, repo)
    port = cli.free_port()
    server = cli.make_server(repo, port, cfg=cfg)
    print("Demo dashboard: http://127.0.0.1:%d/  (fixture in %s)" % (port, tmp), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
