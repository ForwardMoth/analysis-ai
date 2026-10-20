"""Wiring and startup of the local web server."""

import argparse
from http.server import ThreadingHTTPServer
import threading
import webbrowser

from ..platform_utils import IS_WINDOWS, configure_console
from . import config
from .analysis import AnalysisService
from .handler import AppContext, Handler
from .jobs import JobRegistry, JobRunner
from .practice import PracticeAnalyzer
from .roles import RoleRepository
from .storage import MetaStore, TranscriptLibrary

DESCRIPTION = """Local web UI for interview_to_transcript.py (stdlib only, listens on 127.0.0.1).

    python app.py            # then open http://127.0.0.1:8765
"""


class LocalServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second process bind a port that is already in use.
    allow_reuse_address = not IS_WINDOWS


def build_context() -> AppContext:
    store = MetaStore()
    roles = RoleRepository()
    jobs = JobRegistry()
    return AppContext(
        page=config.INDEX_HTML.read_bytes(),
        store=store,
        library=TranscriptLibrary(store),
        roles=roles,
        analyses=AnalysisService(store, roles, PracticeAnalyzer(store, roles)),
        jobs=jobs,
        runner=JobRunner(jobs),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true",
                        help="Open the browser; if the server is already running, only open the browser")
    args = parser.parse_args()

    configure_console()
    config.ensure_data_dirs()
    url = f"http://127.0.0.1:{args.port}"
    try:
        server = LocalServer(("127.0.0.1", args.port), Handler)
    except OSError:
        if not args.open:
            raise
        print(f"Port {args.port} is busy, assuming the server is already running: {url}")
        webbrowser.open(url)
        return
    server.ctx = build_context()
    if args.open:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"Open {url}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
