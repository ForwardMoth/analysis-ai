"""Pick the few frames of a screen recording that show a new, settled state of the screen.
Video-call galleries and webcam tiles are never picked: they hold no task and no solution.

Frames are never written to disk while scanning: ffmpeg streams small grayscale samples through a pipe,
and only the chosen moments are later extracted as compact JPEGs.
"""

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable

import numpy as np

from ..platform_utils import NO_WINDOW

SAMPLE_FPS = 1            # one sample per second is enough: code changes slower than that
SAMPLE_W, SAMPLE_H = 320, 208
TOP_SKIP = 0.20           # menu bar, clock, browser tabs: they change without the code changing
PIXEL_DELTA = 40          # a pixel counts as changed above this brightness step: text edges, not compression noise
CHANGE_THRESHOLD = 0.8    # per mille of changed pixels against the last kept frame that counts as new content
SETTLE_THRESHOLD = 0.4    # per mille between two samples: below this the typing has paused
GALLERY_CHROMA = 20       # a 4x4 block this colorful (max-min of RGB) is skin, sky, a photo, not code on a dark or white editor
GALLERY_TEXTURE = 6       # ... and it is not a flat colored fill
GALLERY_SHARE = 0.08      # share of such blocks that makes a frame a video-call gallery / webcam tiles, not a task
MAX_KEYFRAMES = 400       # per recording; a full interview stays a few MB instead of the video's size
FRAME_WIDTH = 1280
FRAME_QUALITY = 5         # ffmpeg -q:v scale, 2 (best) .. 31
FRAME_NAME = re.compile(r"f_(\d{6})\.jpg")


@dataclass(frozen=True)
class Keyframe:
    second: float
    change: float  # how different it is from the previous keyframe, used to rank when trimming


def has_video(source: Path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_type",
                          "-of", "default=nw=1:nk=1", str(source)],
                         capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    return "video" in out


def frame_seconds(frames_dir: Path) -> list[int]:
    """Seconds (from the start of the recording) of the frames saved for one interview, in order."""
    if not frames_dir.is_dir():
        return []
    return sorted(int(m.group(1)) for f in frames_dir.iterdir() if (m := FRAME_NAME.fullmatch(f.name)))


def frame_path(frames_dir: Path, second: int) -> Path:
    return frames_dir / f"f_{second:06d}.jpg"


def _changed(a: np.ndarray, b: np.ndarray) -> float:
    return float((np.abs(a - b) > PIXEL_DELTA).mean() * 1000)


def _is_gallery(rgb: np.ndarray) -> bool:
    """Faces of a video call: large colorful textured areas. Code, a task text or a query is almost colorless
    (measured on a real interview: 0.13-0.21 for galleries and 0.00-0.05 for the IDE, with syntax highlighting)."""
    block = 4
    rgb = rgb[:rgb.shape[0] // block * block, :rgb.shape[1] // block * block].astype(np.int16)
    h, w = rgb.shape[:2]
    chroma = (rgb.max(2) - rgb.min(2)).reshape(h // block, block, w // block, block).mean((1, 3))
    texture = rgb.mean(2).reshape(h // block, block, w // block, block).std((1, 3))
    return float(((chroma > GALLERY_CHROMA) & (texture > GALLERY_TEXTURE)).mean()) > GALLERY_SHARE


def _samples(video: Path, start: float, end: float):
    """Yields (second, grayscale array, is_gallery) at SAMPLE_FPS without touching disk."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(start), "-to", str(end), "-i", str(video),
           "-vf", f"fps={SAMPLE_FPS},scale={SAMPLE_W}:{SAMPLE_H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    size = SAMPLE_W * SAMPLE_H * 3
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, creationflags=NO_WINDOW) as proc:
        index = 0
        while chunk := proc.stdout.read(size):
            if len(chunk) < size:
                break
            rgb = np.frombuffer(chunk, dtype=np.uint8).reshape(SAMPLE_H, SAMPLE_W, 3)[int(SAMPLE_H * TOP_SKIP):]
            gray = (rgb @ np.array([0.299, 0.587, 0.114])).astype(np.int16)
            yield start + index / SAMPLE_FPS, gray, _is_gallery(rgb)
            index += 1


def find_keyframes(video: Path, start: float, end: float, max_frames: int = MAX_KEYFRAMES,
                   on_progress: Callable[[float], None] | None = None) -> list[Keyframe]:
    kept: list[Keyframe] = []
    reference = None
    previous = None
    pending = None  # (second, change) changed since the last keyframe, not yet settled
    for second, frame, gallery in _samples(video, start, end):
        if on_progress:
            on_progress(second)
        if gallery:  # faces are no task and no solution: skipped as if the moment was not in the recording
            continue
        if reference is None:
            reference = frame
            kept.append(Keyframe(second, 0.0))
        else:
            change = _changed(frame, reference)
            settled = previous is not None and _changed(frame, previous) < SETTLE_THRESHOLD
            if change > CHANGE_THRESHOLD:
                pending = (second, change)
            if pending and settled and change > CHANGE_THRESHOLD:
                kept.append(Keyframe(second, change))
                reference, pending = frame, None
        previous = frame
    if pending:  # the recording ended mid-typing: keep the last state anyway
        kept.append(Keyframe(*pending))
    return _trim(kept, max_frames)


def _trim(frames: list[Keyframe], limit: int) -> list[Keyframe]:
    """Keep the first and the last frame, then the ones that changed the screen the most."""
    if len(frames) <= limit:
        return frames
    middle = sorted(frames[1:-1], key=lambda f: f.change, reverse=True)[: limit - 2]
    return sorted([frames[0], *middle, frames[-1]], key=lambda f: f.second)


def _saved_is_gallery(path: Path) -> bool:
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
                          "-vf", f"scale={SAMPLE_W}:{SAMPLE_H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                         capture_output=True, creationflags=NO_WINDOW).stdout
    if len(raw) != SAMPLE_W * SAMPLE_H * 3:
        return False
    rgb = np.frombuffer(raw, dtype=np.uint8).reshape(SAMPLE_H, SAMPLE_W, 3)
    return _is_gallery(rgb[int(SAMPLE_H * TOP_SKIP):])


# The scan's fps filter picks the frame nearest to each whole second, which is often just after it; at a cut
# that is the difference between the gallery before the cut and the code after it.
def save_keyframes(video: Path, keyframes: list[Keyframe], out_dir: Path) -> int:
    """Compact JPEGs named by second, only for the chosen moments. Returns how many were written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    for frame in keyframes:
        path = frame_path(out_dir, int(frame.second))
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{frame.second + 0.5:.2f}", "-i", str(video),
             "-frames:v", "1", "-vf", f"scale={FRAME_WIDTH}:-2:flags=lanczos", "-q:v", str(FRAME_QUALITY), str(path)],
            creationflags=NO_WINDOW)
        if result.returncode == 0 and path.is_file() and _saved_is_gallery(path):  # seek landed on the cut itself
            path.unlink()
        saved += result.returncode == 0 and path.is_file()
    return saved
