"""Filesystem layout and shared constants."""

from pathlib import Path

SRC = Path(__file__).resolve().parents[2]
ROOT = SRC.parent
DATA = ROOT / "data"

TRANSCRIBE_SCRIPT = SRC / "interview_to_transcript.py"
STATIC_DIR = SRC / "static"
INDEX_HTML = STATIC_DIR / "index.html"

UPLOADS = DATA / "uploads"
RESULTS = DATA / "transcripts"
LOGS = DATA / "logs"
WORK = DATA / "work"  # per-file checkpoints, removed once a job finishes

PROMPT_FILE = ROOT / "prompts" / "analyze-interview.md"
PRACTICE_PROMPT_FILE = ROOT / "prompts" / "analyze-practice.md"
DETECT_PROMPT_FILE = ROOT / "prompts" / "detect-tasks.md"
ROLES_DIR = ROOT / "prompts" / "roles"

UPLOAD_CHUNK = 1024 * 1024
ANALYSIS_TIMEOUT = 45 * 60
ID_PATTERN = r"[0-9a-f]{12}"
LOCAL_HOSTS = ("127.0.0.1", "localhost")


def ensure_data_dirs() -> None:
    for directory in (UPLOADS, RESULTS, LOGS, WORK):
        directory.mkdir(parents=True, exist_ok=True)
