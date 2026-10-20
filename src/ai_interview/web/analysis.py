"""LLM analysis of a transcript through the user's own claude / codex CLI login."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import threading
import time
from typing import TYPE_CHECKING
import uuid

from . import cli, config
from .roles import RoleRepository
from .storage import MetaStore, now_iso

if TYPE_CHECKING:
    from .practice import PracticeAnalyzer

TASK_WORKERS = 3  # practical tasks are independent, so a few CLI runs go side by side
ANALYSIS_TOOLS = ("WebSearch", "WebFetch")


@dataclass
class AnalysisState:
    state: str = "running"  # running | done | error
    error: str | None = None
    stage: str = ""  # what the worker is doing now, shown next to the progress bar
    started: float = field(default_factory=time.monotonic)


class AnalysisService:
    """One run covers the whole interview: practical tasks (screen + voice) first, then the full report."""

    def __init__(self, store: MetaStore, roles: RoleRepository, practice: "PracticeAnalyzer"):
        self.store = store
        self.roles = roles
        self.practice = practice
        self._states: dict[str, AnalysisState] = {}

    def start(self, tid: str, provider: str, model: str, role: str) -> str:
        aid = uuid.uuid4().hex[:12]
        self._states[f"{tid}/{aid}"] = AnalysisState()
        threading.Thread(target=self._run, args=(tid, aid, provider, model, role), daemon=True).start()
        return aid

    def state(self, tid: str, aid: str) -> AnalysisState | None:
        return self._states.get(f"{tid}/{aid}")

    def result_file(self, tid: str, aid: str) -> Path:
        return self.store.transcript_dir(tid) / f"analysis-{aid}.md"

    # --- worker -------------------------------------------------------------

    def _run(self, tid: str, aid: str, provider: str, model: str, role: str) -> None:
        state = self._states[f"{tid}/{aid}"]
        out_file = self.result_file(tid, aid)
        try:
            tasks = self._analyze_tasks(tid, state, provider, model, role)
            state.stage = "Собираю итоговый разбор собеседования…"
            text = self._ask_llm(tid, provider, model, role, out_file, self._practice_block(tasks))
            out_file.write_text(text + "\n", encoding="utf-8")
            entry = {"id": aid, "provider": provider, "model": model, "role": role, "created": now_iso(),
                     "seconds": int(time.monotonic() - state.started),
                     "tasks": [{k: task.get(k, "") for k in ("start", "end", "kind", "verdict", "title")}
                               for task in tasks if "text" in task]}
            self.store.update(tid, lambda meta: meta["analyses"].append(entry))
            state.state = "done"
        except subprocess.TimeoutExpired:
            state.state, state.error = "error", "Анализ шёл дольше 45 минут и был остановлен."
        except Exception as exc:  # noqa: BLE001
            state.state, state.error = "error", str(exc)

    def _analyze_tasks(self, tid: str, state: AnalysisState, provider: str, model: str, role: str) -> list[dict]:
        """Recordings without saved screen frames (audio, old transcripts) skip this and are analyzed by voice only.
        A task that fails is kept with its error, so the final report can say that it was not examined."""
        if not self.practice.has_frames(tid) or not config.DETECT_PROMPT_FILE.is_file() \
                or not config.PRACTICE_PROMPT_FILE.is_file():
            return []
        state.stage = "Ищу практические задания по разговору…"
        tasks = self.practice.find_tasks(tid, provider, model)
        done = 0

        def analyze(task: dict) -> dict:
            nonlocal done
            try:
                result = self.practice.analyze(tid, task, provider, model, role)
            except Exception as exc:  # noqa: BLE001
                result = {**task, "error": str(exc)[-300:]}
            done += 1
            state.stage = f"Разобрано заданий: {done} из {len(tasks)}"
            return result

        state.stage = f"Разбираю практические задания ({len(tasks)}) параллельно…"
        with ThreadPoolExecutor(max_workers=TASK_WORKERS) as pool:
            results = list(pool.map(analyze, tasks))  # map keeps the order of the tasks
        self.practice.prune_frames(tid, tasks)
        return results

    @staticmethod
    def _practice_block(tasks: list[dict]) -> str:
        if not tasks:
            return ""
        parts = []
        for number, task in enumerate(tasks, 1):
            title = f"### Задание {number}. {task['start']}–{task['end']}: {task['title']}"
            body = task.get("text") or f"(разобрать не удалось: {task.get('error', 'ошибка')})"
            parts.append(f"{title}\n\n{body}")
        return ("\n\n---\n\nРАЗБОР ПРАКТИЧЕСКИХ ЗАДАНИЙ. Каждое задание уже разобрано отдельным проходом "
                "по кадрам экрана и голосу:\n\n" + "\n\n".join(parts))

    def _ask_llm(self, tid: str, provider: str, model: str, role: str, out_file: Path, practice: str) -> str:
        return cli.ask(provider, model, self._build_prompt(tid, role, practice), config.WORK / "analysis",
                       out_file, tools=ANALYSIS_TOOLS)

    def _build_prompt(self, tid: str, role: str, practice: str = "") -> str:
        meta = self.store.load(tid)
        transcript = self.store.named_transcript(tid)
        prompt = config.PROMPT_FILE.read_text(encoding="utf-8")
        return f"{prompt}\n\n---\n\nТРАНСКРИПЦИЯ ({meta['name']}):\n\n{transcript}{practice}{self.roles.prompt_block(role)}"
