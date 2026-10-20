"""Practical tasks of an interview (live-coding, SQL, system design, a text task answered aloud, ...):
finds them in the transcript, then analyzes each one from its key screen frames plus the spoken part."""

from pathlib import Path
import re
import uuid

from ..screen.keyframes import frame_path, frame_seconds
from . import cli, config
from .roles import RoleRepository
from .storage import MetaStore
from .uploads import BadRequest

MAX_FRAMES_SENT = 10  # about 1k tokens each; more frames rarely add information
MAX_RANGE_SECONDS = 90 * 60
KEEP_MARGIN_SECONDS = 60  # frames this close to a task stay, in case a later run draws its boundaries a bit differently
VERDICT_RE = re.compile(r"^\W*ВЕРДИКТ:\s*(сильное|среднее|слабое)", re.I | re.M)
KIND_RE = re.compile(r"^\W*ТИП:\s*([\w-]+)", re.I | re.M)
TOKENS_RE = re.compile(r"tokens used\s*([\d\s,.  ]+)")
TURN_RE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\]", re.M)
DETECTED_RE = re.compile(r"^\W*ЗАДАЧА:\s*([\d:]+)\s*\|\s*([\d:]+)\s*\|\s*([\w-]+)\s*\|\s*(.+?)\s*$", re.M)
KINDS = ("livecoding", "sql", "system-design", "text-task", "debugging", "code-review", "other")


def parse_timecode(text: str) -> int:
    """'11:00' is minutes:seconds, '1:05:30' is hours:minutes:seconds."""
    parts = text.strip().split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        raise BadRequest(f"Не понял время «{text}». Формат: 11:00 или 1:05:30")
    numbers = [int(p) for p in parts]
    return numbers[0] * 60 + numbers[1] if len(numbers) == 2 else numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def pick_evenly(items: list[int], count: int) -> list[int]:
    """At most `count` items spread over the whole list, always including the first and the last."""
    if len(items) <= count:
        return items
    step = (len(items) - 1) / (count - 1)
    return [items[round(i * step)] for i in range(count)]


def format_tc(second: int) -> str:
    return f"{second // 3600:02d}:{second % 3600 // 60:02d}:{second % 60:02d}"


def transcript_range(text: str, start: int, end: int) -> str:
    """Turns whose start time falls into [start, end]; a turn without a timestamp belongs to the previous one."""
    kept, inside = [], False
    for block in re.split(r"\n\s*\n", text.strip()):
        match = TURN_RE.match(block)
        if match:
            hours, minutes, seconds = map(int, match.groups())
            inside = start <= hours * 3600 + minutes * 60 + seconds <= end
        if inside:
            kept.append(block.strip())
    return "\n\n".join(kept)


class PracticeAnalyzer:
    """Blocking calls: AnalysisService runs them one after another inside its own worker thread."""

    def __init__(self, store: MetaStore, roles: RoleRepository):
        self.store = store
        self.roles = roles

    def frames_dir(self, tid: str) -> Path:
        return self.store.transcript_dir(tid) / "frames"

    def has_frames(self, tid: str) -> bool:
        return bool(frame_seconds(self.frames_dir(tid)))

    # --- finding the tasks ----------------------------------------------------

    def find_tasks(self, tid: str, provider: str, model: str) -> list[dict]:
        """One text-only request; tasks without a single saved frame are dropped, they cannot be shown to the model."""
        prompt = (f"{config.DETECT_PROMPT_FILE.read_text(encoding='utf-8')}\n\n---\n\n"
                  f"ТРАНСКРИПЦИЯ:\n\n{self.store.named_transcript(tid)}")
        text = self._call_cli(provider, model, prompt, f"detect-{tid}")
        seconds = frame_seconds(self.frames_dir(tid))
        return [task for task in self.parse_detected(text)
                if any(parse_timecode(task["start"]) <= s <= parse_timecode(task["end"]) for s in seconds)]

    @staticmethod
    def parse_detected(text: str) -> list[dict]:
        """Lines 'ЗАДАЧА: start | end | kind | title'; anything unreadable or out of range is skipped."""
        tasks = []
        for match in DETECTED_RE.finditer(text):
            try:
                start, end = parse_timecode(match.group(1)), parse_timecode(match.group(2))
            except BadRequest:
                continue
            if end <= start:
                continue
            kind = match.group(3).lower()
            tasks.append({"id": uuid.uuid4().hex[:12], "start": format_tc(start),
                          "end": format_tc(min(end, start + MAX_RANGE_SECONDS)),
                          "kind": kind if kind in KINDS else "other", "title": match.group(4).strip(" *")[:120]})
        tasks.sort(key=lambda task: task["start"])
        return tasks

    def prune_frames(self, tid: str, tasks: list[dict]) -> int:
        """Deletes the frames outside every task (faces, small talk, slides between tasks): nobody looks at them.
        Without any found task nothing is deleted, an empty answer may just be a model miss. Returns how many went."""
        if not tasks:
            return 0
        ranges = [(parse_timecode(t["start"]) - KEEP_MARGIN_SECONDS, parse_timecode(t["end"]) + KEEP_MARGIN_SECONDS)
                  for t in tasks]
        removed = 0
        for second in frame_seconds(self.frames_dir(tid)):
            if not any(start <= second <= end for start, end in ranges):
                frame_path(self.frames_dir(tid), second).unlink(missing_ok=True)
                removed += 1
        return removed

    # --- analysis of one task --------------------------------------------------

    def analyze(self, tid: str, task: dict, provider: str, model: str, role: str) -> dict:
        """Returns the task with the model's report (`text`) and the verdict / kind the model gave it."""
        start, end = parse_timecode(task["start"]), parse_timecode(task["end"])
        seconds = pick_evenly([s for s in frame_seconds(self.frames_dir(tid)) if start <= s <= end], MAX_FRAMES_SENT)
        frames = [frame_path(self.frames_dir(tid), s) for s in seconds]
        text = self._call_cli(provider, model, self._build_prompt(tid, role, start, end, frames, provider),
                              task["id"], frames)
        (self.store.transcript_dir(tid) / f"practice-{task['id']}.md").write_text(text + "\n", encoding="utf-8")
        verdict, kind = VERDICT_RE.search(text), KIND_RE.search(text)
        return {**task, "text": text, "frames": len(frames),
                "verdict": verdict.group(1).lower() if verdict else "",
                "kind": kind.group(1).lower() if kind else task["kind"]}

    def _call_cli(self, provider: str, model: str, prompt: str, name: str, frames: list[Path] | None = None) -> str:
        cwd = config.WORK / "practice"  # empty folder: the CLI must only see the frames it is handed
        tools = ("Read",) if frames else ()  # text-only requests get no tools at all
        return cli.ask(provider, model, prompt, cwd, cwd / f"{name}.out.md", tools=tools, frames=frames)

    def _build_prompt(self, tid: str, role: str, start: int, end: int, frames: list[Path], provider: str) -> str:
        meta = self.store.load(tid)
        turns = transcript_range(self.store.named_transcript(tid), start, end) or "(в этом диапазоне реплик нет)"
        seconds = ", ".join(str(int(f.stem.removeprefix("f_"))) for f in frames)
        if provider == "claude":
            listing = "Открой кадры инструментом Read по порядку:\n" + "\n".join(str(f) for f in frames)
        else:
            listing = "Кадры приложены к запросу по порядку."
        prompt = config.PRACTICE_PROMPT_FILE.read_text(encoding="utf-8")
        return (f"{prompt}\n\n---\n\nКАДРЫ ЭКРАНА. {listing}\nСекунды от начала записи: {seconds}.\n\n"
                f"ТРАНСКРИПЦИЯ ДИАПАЗОНА {format_tc(start)}–{format_tc(end)} ({meta['name']}):\n\n{turns}"
                f"{self.roles.prompt_block(role)}")
