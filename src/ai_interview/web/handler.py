"""HTTP routing for the local web UI (JSON API + the static page with its css/js)."""

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import re
import shutil
import time
import uuid
from urllib.parse import parse_qs, urlparse

from ..platform_utils import file_manager_name, reveal_in_file_manager
from . import cli, config
from .analysis import AnalysisService
from .jobs import JobRegistry, JobRunner
from .roles import RoleRepository
from .storage import MetaStore, TranscriptLibrary, new_meta, now_iso
from .uploads import BadRequest, UploadRequest, stream_to_disk

ID = config.ID_PATTERN
TIMECODE_RE = re.compile(r"\d{1,2}:\d\d(:\d\d)?")
MODEL_RE = re.compile(r"[\w.\-:]*")
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}


@dataclass
class AppContext:
    """Everything a request handler needs; built once in server.py."""
    page: bytes
    store: MetaStore
    library: TranscriptLibrary
    roles: RoleRepository
    analyses: AnalysisService
    jobs: JobRegistry
    runner: JobRunner


class Handler(BaseHTTPRequestHandler):
    @property
    def ctx(self) -> AppContext:
        return self.server.ctx

    def log_message(self, *args):
        pass

    # --- response helpers ---------------------------------------------------

    def send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8", extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def json(self, code: int, obj) -> None:
        self.send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json")

    def not_found(self) -> None:
        self.send(404, b"not found")

    def host_ok(self) -> bool:
        """Basic DNS-rebinding / cross-site guard."""
        host = self.headers.get("Host", "").split(":")[0]
        origin = self.headers.get("Origin")
        return host in config.LOCAL_HOSTS and (
            origin is None or urlparse(origin).hostname in config.LOCAL_HOSTS)

    def body_json(self) -> dict:
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            return body if isinstance(body, dict) else {}
        except ValueError:
            return {}

    # --- GET ----------------------------------------------------------------

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, b"forbidden")
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path

        if path == "/":
            return self.send(200, self.ctx.page, "text/html; charset=utf-8")
        if path.startswith("/static/"):
            return self.get_static(path.removeprefix("/static/"))
        if path == "/api/library":
            return self.json(200, self.ctx.library.search(query.get("q", "")))
        if path == "/api/roles":
            return self.json(200, self.ctx.roles.catalog())
        if path == "/api/platform":
            return self.json(200, {"fileManager": file_manager_name()})
        if path == "/api/tools":
            return self.json(200, cli.available_tools())
        if m := re.fullmatch(rf"/api/transcripts/({ID})", path):
            return self.get_transcript(m.group(1))
        if m := re.fullmatch(rf"/api/transcripts/({ID})/analyses/({ID})", path):
            return self.get_analysis(m.group(1), m.group(2))
        if m := re.fullmatch(rf"/api/jobs/({ID})/(transcript\.txt|raw_transcript\.json)", path):
            return self.get_job_file(m.group(1), m.group(2), download="dl=1" in url.query)
        if m := re.fullmatch(rf"/api/jobs/({ID})", path):
            return self.get_job(m.group(1))
        self.not_found()

    def get_static(self, relative: str) -> None:
        file = (config.STATIC_DIR / relative).resolve()
        ctype = STATIC_TYPES.get(file.suffix)
        if not ctype or not file.is_relative_to(config.STATIC_DIR) or not file.is_file():
            return self.not_found()
        self.send(200, file.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    def get_transcript(self, tid: str) -> None:
        meta = self.ctx.store.load(tid)
        if not meta:
            return self.not_found()
        meta["text"] = self.ctx.store.transcript_file(tid).read_text(encoding="utf-8")
        self.json(200, meta)

    def get_analysis(self, tid: str, aid: str) -> None:
        analyses = self.ctx.analyses
        state = analyses.state(tid, aid)
        if state and state.state != "done":
            return self.json(200, {"state": state.state, "error": state.error, "stage": state.stage,
                                   "elapsed": time.monotonic() - state.started})
        result = analyses.result_file(tid, aid)
        if result.is_file():
            return self.json(200, {"state": "done", "text": result.read_text(encoding="utf-8")})
        self.not_found()

    def get_job_file(self, job_id: str, name: str, download: bool) -> None:
        file = config.RESULTS / job_id / name
        if not file.is_file():
            return self.not_found()
        ctype = "application/json" if file.suffix == ".json" else "text/plain; charset=utf-8"
        extra = {"Content-Disposition": f'attachment; filename="{file.name}"'} if download else None
        self.send(200, file.read_bytes(), ctype, extra)

    def get_job(self, job_id: str) -> None:
        job = self.ctx.jobs.get(job_id)
        if not job:
            return self.not_found()
        self.json(200, job.snapshot())

    # --- POST ---------------------------------------------------------------

    def do_POST(self):
        if not self.host_ok():
            return self.send(403, b"forbidden")
        url = urlparse(self.path)
        try:
            if m := re.fullmatch(rf"/api/jobs/({ID})/reveal", url.path):
                return self.post_reveal(m.group(1))
            if m := re.fullmatch(rf"/api/transcripts/({ID})/(meta|notes|notes/delete|analyze)", url.path):
                return self.post_transcript(m.group(1), m.group(2))
            if url.path == "/api/jobs":
                return self.post_job(url.query)
            self.not_found()
        except BadRequest as exc:
            self.send(400, str(exc).encode())

    def post_reveal(self, tid: str) -> None:
        transcript = self.ctx.store.transcript_file(tid)
        if not transcript.is_file():
            return self.not_found()
        reveal_in_file_manager(transcript)
        self.send(204, b"")

    def post_transcript(self, tid: str, action: str) -> None:
        body = self.body_json()
        if not self.ctx.store.load(tid):
            return self.not_found()
        handlers = {"meta": self.update_meta, "notes": self.add_note,
                    "notes/delete": self.delete_note, "analyze": self.start_analysis}
        handlers[action](tid, body)

    def update_meta(self, tid: str, body: dict) -> None:
        name = str(body.get("name", "")).strip()[:200]
        speakers = {str(k)[:40]: str(v).strip()[:60] for k, v in (body.get("speakers") or {}).items()}

        def apply(meta: dict) -> None:
            if name:
                meta["name"] = name
            if "speakers" in body:
                meta["speakers"] = speakers

        self.json(200, self.ctx.store.update(tid, apply))

    def add_note(self, tid: str, body: dict) -> None:
        text = str(body.get("text", "")).strip()[:5000]
        if not text:
            raise BadRequest("Пустая заметка")
        timecode = str(body.get("tc", "")).strip()
        note = {"id": uuid.uuid4().hex[:12], "text": text, "created": now_iso(),
                "tc": timecode if TIMECODE_RE.fullmatch(timecode) else ""}
        self.ctx.store.update(tid, lambda meta: meta["notes"].append(note))
        self.json(200, note)

    def delete_note(self, tid: str, body: dict) -> None:
        note_id = body.get("id")
        self.ctx.store.update(tid, lambda meta: meta.update(
            notes=[n for n in meta["notes"] if n["id"] != note_id]))
        self.send(204, b"")

    def start_analysis(self, tid: str, body: dict) -> None:
        provider = body.get("provider")
        model = str(body.get("model", "")).strip()
        role = str(body.get("role", ""))
        if provider not in cli.PROVIDER_BINARIES or not MODEL_RE.fullmatch(model):
            raise BadRequest("bad provider or model")
        if role and role not in self.ctx.roles.names():
            raise BadRequest("Роль не найдена в prompts/roles/")
        if not shutil.which(cli.PROVIDER_BINARIES[provider]):
            raise BadRequest("Не найден CLI (claude / codex)")
        if not config.PROMPT_FILE.is_file():
            raise BadRequest("Не найден prompts/analyze-interview.md")
        self.json(200, {"id": self.ctx.analyses.start(tid, provider, model, role)})

    def post_job(self, raw_query: str) -> None:
        query = {k: v[0] for k, v in parse_qs(raw_query).items()}
        request = UploadRequest.parse(query, int(self.headers.get("Content-Length", 0)))

        job_id = uuid.uuid4().hex[:12]
        dest = config.UPLOADS / job_id / request.file_name
        stream_to_disk(self.rfile, request.length, dest)

        self.ctx.store.create(new_meta(job_id, request.title))
        self.ctx.jobs.create(job_id)
        self.ctx.runner.start(job_id, dest, request.options, self.headers.get("X-HF-Token", "").strip())
        self.json(200, {"id": job_id})
