"""FFmpeg/ffprobe wrappers: media duration and mono 16 kHz audio extraction."""

from pathlib import Path
import subprocess
import time

from ..platform_utils import NO_WINDOW
from .formatting import format_timestamp

PROGRESS_INTERVAL = 2  # seconds between progress lines


def probe_duration(source: Path) -> float:
    """Media length in seconds via ffprobe, or 0 when unknown."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(source)],
            capture_output=True, text=True, check=True,
            creationflags=NO_WINDOW).stdout.strip()
        return float(out)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return 0.0


def extract_audio(source: Path, audio: Path, total: float) -> None:
    """Extract mono 16 kHz WAV, printing 'FFmpeg: NN.N% (t / total)' about every 2 s."""
    proc = subprocess.Popen([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-y",
        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", "-progress", "pipe:1", str(audio),
    ], stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    last_report = 0.0
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key not in ("out_time_us", "out_time_ms") or not value.lstrip("-").isdigit():
            continue
        done = max(0, int(value)) / 1e6
        now = time.monotonic()
        if now - last_report >= PROGRESS_INTERVAL:
            last_report = now
            _print_progress(done, total)
    if proc.wait():
        raise subprocess.CalledProcessError(proc.returncode, "ffmpeg")


def _print_progress(done: float, total: float) -> None:
    percent = f"{min(100.0, done / total * 100):.1f}% " if total else ""
    total_text = format_timestamp(total) if total else "?"
    print(f"FFmpeg: {percent}({format_timestamp(done)} / {total_text})", flush=True)
