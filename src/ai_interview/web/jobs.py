"""Background transcription jobs: subprocess runner and live progress tracking."""

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

from ..platform_utils import NO_WINDOW, utf8_environment
from ..screen.keyframes import find_keyframes, has_video, save_keyframes
from ..transcription.media import probe_duration
from . import config

LOG_TAIL_CHARS = 30000
HEARTBEAT_SECONDS = 60
PHASE_ETA_MIN_ELAPSED = 20

# Progress-bar floor (%) when a finished stage from an earlier run is reused.
REUSE_FLOORS = {"audio": 20, "asr": 65, "align": 88, "final": 95}
DIARIZE_NOTE = "Сопоставляю голоса по всей записи, подождите."


def fingerprint(path: Path) -> str:
    """Same media file -> same id across uploads, so a rerun finds its saved stages."""
    size, digest = path.stat().st_size, hashlib.sha1()
    with path.open("rb") as f:
        digest.update(f.read(8 << 20))
        f.seek(max(0, size - (8 << 20)))
        digest.update(f.read(8 << 20))
    return f"{digest.hexdigest()[:16]}-{size}"


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class Job:
    """Mutable state of one transcription; all access goes through the shared lock."""

    def __init__(self, lock: threading.Lock):
        self.lock = lock
        self.state = "queued"  # queued | running | done | error
        self.stage = "В очереди…"
        self.progress = 10.0
        self.step = 1
        self.detail = ""
        self.eta: float | None = None
        self.log = ""
        self.work = ""  # fingerprint of the media file, names the checkpoint folder
        self.phase: str | None = None
        self.pass_no = 0  # WhisperX prints progress twice: recognition pass, then alignment pass
        self.last_pct = 0.0
        now = time.monotonic()
        self.phase_start = now
        self.last_output = now
        self.started = now

    def start(self) -> None:
        now = time.monotonic()
        self.state, self.progress = "running", 10
        self.last_pct, self.pass_no = 0.0, 0
        self.phase, self.eta = None, None
        self.phase_start = self.last_output = self.started = now

    def set_phase(self, key: str, step: int, stage: str, progress: float, detail: str = "") -> None:
        """Switch to a new phase (resets the per-phase timer); progress never goes backwards."""
        if self.phase != key:
            self.phase, self.phase_start = key, time.monotonic()
            self.eta = None
        self.step, self.stage, self.detail = step, stage, detail
        self.progress = max(self.progress, progress)

    def set_eta(self, pct: float) -> None:
        """Rough time-left estimate from the share done in the current phase."""
        elapsed = time.monotonic() - self.phase_start
        self.eta = elapsed * (100 - pct) / pct if pct >= 1 and elapsed > PHASE_ETA_MIN_ELAPSED else None

    def snapshot(self) -> dict:
        with self.lock:
            data = {"state": self.state, "stage": self.stage, "progress": self.progress, "log": self.log,
                    "step": self.step, "detail": self.detail, "eta": self.eta}
            if self.state == "running":
                now = time.monotonic()
                data["phase_elapsed"] = now - self.phase_start
                data["idle"] = now - self.last_output
            return data


class ProgressParser:
    """Maps a line printed by the transcription subprocess onto the job's phase and progress."""

    DOWNLOAD_BAR = re.compile(r"(\d+)%\|[^|]*\|\s*([\d.]+\w?)/([\d.]+\w?)\s*\[[^<]*<[^,]*,\s*([^\]]+)\]")

    def __init__(self, job: Job):
        self.job = job
        self._handlers = [
            self._on_reuse, self._on_stage, self._on_extract_start, self._on_ffmpeg, self._on_recognize_start,
            self._on_whisper_progress, self._on_diarize, self._on_download, self._on_finalize,
        ]

    def feed(self, line: str) -> None:
        for handler in self._handlers:
            if handler(line):
                return

    def _on_reuse(self, line: str) -> bool:
        if not line.startswith("REUSE:"):
            return False
        stage = line[6:].strip()
        if floor := REUSE_FLOORS.get(stage):  # finished stage from an earlier run, skipped
            self.job.set_phase("reuse", 2, "Использую сохранённый результат шага…", floor,
                               f"Продолжаю с места остановки ({stage} уже готово)")
            if stage in ("align", "final"):
                self.job.pass_no = 1
        return True

    def _on_stage(self, line: str) -> bool:
        if not line.startswith("STAGE:"):
            return False
        job, stage = self.job, line[6:].strip()
        if stage == "asr":
            job.pass_no, job.last_pct = 0, 0.0
        elif stage == "align":
            job.pass_no, job.last_pct = 1, 0.0
            job.set_phase("align_load", 2, "Загружаю модель выравнивания…", 65)
        elif stage == "diarize":
            job.set_phase("diarize", 2, "Определяю, кто говорит…", 88, DIARIZE_NOTE)
        return True

    def _on_extract_start(self, line: str) -> bool:
        if not line.startswith("[1/3]"):
            return False
        self.job.set_phase("ffmpeg", 1, "Извлекаю звук из видео (FFmpeg)…", 10)
        return True

    def _on_ffmpeg(self, line: str) -> bool:
        if not line.startswith("FFmpeg:"):
            return False
        match = re.search(r"([\d.]+)%\s*\((.+)\)", line)
        if match:
            pct = float(match.group(1))
            self.job.set_phase("ffmpeg", 1, "Извлекаю звук из видео (FFmpeg)…", 10 + pct / 10,
                               f"Обработано {match.group(2)}")
            self.job.set_eta(pct)
        return True

    def _on_recognize_start(self, line: str) -> bool:
        if not line.startswith("[2/3]"):
            return False
        self.job.set_phase("load", 2, "Загружаю модель и ищу речь в записи…", 20,
                           "Пока WhisperX ничего не выводит: загрузка модели и поиск речи (VAD) "
                           "по всей записи. На длинных файлах это может занять несколько минут.")
        return True

    def _on_whisper_progress(self, line: str) -> bool:
        match = re.search(r"Progress:\s*([\d.]+)%", line)
        if not match:
            return False
        job, pct = self.job, float(match.group(1))
        if pct + 1 < job.last_pct:  # percent went back to ~0: next pass started
            job.pass_no += 1
        job.last_pct = pct
        if job.pass_no == 0:
            job.set_phase("asr", 2, "Распознаю речь (WhisperX)…", 25 + pct / 100 * 40,
                          f"Распознано {pct:.0f}% записи")
        else:
            job.set_phase("align", 2, "Привязываю слова к времени…", 65 + pct / 100 * 20,
                          f"Выровнено {pct:.0f}%")
        job.set_eta(pct)
        if job.pass_no == 0 and pct >= 99.9:
            job.set_phase("align_load", 2, "Распознавание готово, загружаю модель выравнивания…", 65,
                          "Без вывода: модель загружается из кэша, а при первом запуске скачивается "
                          "(около 1 ГБ). Если сеть до huggingface.co медленная, шаг может затянуться.")
            job.eta = None
        return True

    def _on_diarize(self, line: str) -> bool:
        if not line.startswith("Diarize:"):
            return False
        match = re.search(r"([\d.]+)%", line)
        if match:
            pct = float(match.group(1))
            self.job.set_phase("diarize", 2, "Определяю, кто говорит…", 88 + pct / 100 * 7,
                               f"Разделение по голосам: {pct:.0f}%")
            self.job.set_eta(pct)
        return True

    def _on_download(self, line: str) -> bool:
        match = self.DOWNLOAD_BAR.search(line)  # huggingface tqdm download bar
        if not match:
            return False
        pct = float(match.group(1))
        self.job.set_phase("download", 2, "Скачиваю модель…", 65 + pct / 100 * 10,
                           f"Скачано {match.group(2)} из {match.group(3)} ({match.group(4).strip()})")
        self.job.set_eta(pct)
        return True

    def _on_finalize(self, line: str) -> bool:
        if not line.startswith("[3/3]"):
            return False
        self.job.set_phase("final", 3, "Собираю транскрипт…", 95)
        return True


class JobRegistry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def create(self, job_id: str) -> Job:
        job = Job(self.lock)
        self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def work_in_use_by_others(self, job: Job) -> bool:
        return any(other is not job and other.work == job.work and other.state not in ("done", "error")
                   for other in self._jobs.values())


class JobRunner:
    """Runs interview_to_transcript.py in a subprocess and mirrors its output into a Job."""

    def __init__(self, registry: JobRegistry):
        self.registry = registry

    def start(self, job_id: str, source: Path, options: dict, hf_token: str) -> None:
        threading.Thread(target=self._run, args=(job_id, source, options, hf_token), daemon=True).start()

    def _run(self, job_id: str, source: Path, options: dict, hf_token: str) -> None:
        job = self.registry.get(job_id)
        job.work = fingerprint(source)
        out_dir = config.RESULTS / job_id
        log_file = (config.LOGS / f"{time.strftime('%Y%m%d-%H%M%S')}-{job_id}.log").open(
            "a", encoding="utf-8", buffering=1)

        def log(line: str) -> None:
            stamped = f"[{time.strftime('%H:%M:%S')}] {line}"
            job.log = (job.log + stamped + "\n")[-LOG_TAIL_CHARS:]
            log_file.write(stamped + "\n")
            print(f"[{job_id}] {stamped}", flush=True)

        job.start()
        job.set_phase("start", 1, "Запуск…", 10)
        log(f"Job started: model={options['model']}, language={options['language']}, "
            f"diarize={options['diarize']}, speakers={options['speakers']}")
        threading.Thread(target=self._heartbeat, args=(job, log), daemon=True).start()
        frames_dir = out_dir / "frames"
        # the screen scan only reads the video, so it runs while the speech is being recognized
        frames = threading.Thread(target=self._save_screen_frames, args=(job, log, source, frames_dir), daemon=True)
        frames.start()
        try:
            code = self._stream_subprocess(job, log, self._command(source, out_dir, options),
                                           self._environment(hf_token))
            if frames.is_alive():
                with self.registry.lock:
                    job.set_phase("screen", 3, "Ищу смены экрана…", 95, "Сохраняю только кадры, где экран менялся")
            frames.join()
            if code != 0 or not (out_dir / "transcript.txt").is_file():
                shutil.rmtree(frames_dir, ignore_errors=True)
            self._finish(job, log, out_dir, code)
        except Exception as exc:  # noqa: BLE001
            with self.registry.lock:
                job.state, job.stage, job.detail = "error", f"Ошибка: {exc}", ""
                log(f"FAILED: {exc}")
        finally:
            log_file.close()
            try:
                source.unlink(missing_ok=True)
                source.parent.rmdir()
            except OSError:  # Windows: the file may still be held briefly by an antivirus scan
                pass

    def _save_screen_frames(self, job: Job, log, source: Path, frames_dir: Path) -> None:
        """Keeps only the moments the screen changed, so live-coding can be analysed after the video is gone."""
        try:
            duration = probe_duration(source)
            if not duration or not has_video(source):
                return
            keyframes = find_keyframes(source, 0, duration)
            saved = save_keyframes(source, keyframes, frames_dir)
            with self.registry.lock:
                log(f"Screen: {saved} frames saved")
        except Exception as exc:  # noqa: BLE001 - the transcript is already done, frames are a bonus
            with self.registry.lock:
                log(f"Screen frames skipped: {exc}")

    @staticmethod
    def _command(source: Path, out_dir: Path, options: dict) -> list[str]:
        cmd = [sys.executable, "-u", str(config.TRANSCRIBE_SCRIPT), str(source),
               "--language", options["language"], "--model", options["model"],
               "--output", str(out_dir), "--work-dir", str(config.WORK / fingerprint(source))]
        if options["speakers"]:
            cmd += ["--speakers", str(options["speakers"])]
        if not options["diarize"]:
            cmd.append("--no-diarize")
        return cmd

    @staticmethod
    def _environment(hf_token: str) -> dict:
        env = os.environ.copy()
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        env["PYTHONUNBUFFERED"] = "1"
        env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows has no symlinks without Developer Mode
        utf8_environment(env)
        # Models are cached after the first run; if huggingface.co is slow or unreachable, fail the
        # freshness check fast and use the cache instead of hanging for minutes.
        env.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
        env.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")
        if hf_token:
            env["HF_TOKEN"] = hf_token
        return env

    def _heartbeat(self, job: Job, log) -> None:
        """A line every minute proves the job is alive even while WhisperX is silent."""
        while job.state == "running":
            time.sleep(HEARTBEAT_SECONDS)
            with self.registry.lock:
                if job.state == "running":
                    now = time.monotonic()
                    log(f"... still working: {job.stage} | phase {format_duration(now - job.phase_start)}, "
                        f"no output for {format_duration(now - job.last_output)}")

    def _stream_subprocess(self, job: Job, log, cmd: list[str], env: dict) -> int:
        parser = ProgressParser(job)
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1,
                                creationflags=NO_WINDOW)
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            with self.registry.lock:
                job.last_output = time.monotonic()
                log(line)
                parser.feed(line)
        return proc.wait()

    def _finish(self, job: Job, log, out_dir: Path, code: int) -> None:
        with self.registry.lock:
            if code == 0 and (out_dir / "transcript.txt").is_file():
                job.state, job.stage, job.detail, job.eta, job.progress = "done", "Готово", "", None, 100
                # checkpoints are needed no longer, unless another job still uses this media file's folder
                if not self.registry.work_in_use_by_others(job):
                    shutil.rmtree(config.WORK / job.work, ignore_errors=True)
                log(f"Done in {format_duration(time.monotonic() - job.started)}")
            else:
                job.state, job.stage, job.detail = "error", "Ошибка — см. лог", ""
                log(f"FAILED with exit code {code}")
