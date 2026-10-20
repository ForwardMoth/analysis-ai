"""Orchestrates one run: audio extraction -> WhisperX -> transcript.txt."""

import contextlib
import os
from pathlib import Path
import shutil
import tempfile

from ..platform_utils import replace_file
from .formatting import format_timestamp, transcript_lines
from .media import extract_audio, probe_duration
from .pipeline import PipelineOptions, WhisperPipeline, load_json


class InterviewTranscriber:
    def __init__(self, source: Path, output_dir: Path, work_dir: Path | None, options: PipelineOptions):
        self.source = source
        self.output_dir = output_dir
        self.work_dir = work_dir
        self.options = options
        self.text_path = output_dir / "transcript.txt"
        self.json_path = output_dir / "raw_transcript.json"

    def run(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with contextlib.ExitStack() as stack:
            work = self._prepare_work_dir(stack)
            audio = self._extract_audio(work)
            result_file = self._transcribe(audio, work)
            self._write_outputs(result_file)

    # --- steps --------------------------------------------------------------

    def _prepare_work_dir(self, stack: contextlib.ExitStack) -> Path:
        if self.work_dir:  # persistent: finished stages survive a crash and are reused on the next run
            work = self.work_dir.expanduser().resolve()
            work.mkdir(parents=True, exist_ok=True)
            return work
        return Path(stack.enter_context(tempfile.TemporaryDirectory(
            prefix="interview_whisperx_", ignore_cleanup_errors=True)))

    def _extract_audio(self, work: Path) -> Path:
        audio = work / "audio.wav"
        print(f"File: {self.source.name}, {self.source.stat().st_size / 1e9:.2f} GB", flush=True)
        total = probe_duration(self.source)
        if total:
            print(f"Media duration: {format_timestamp(total)}", flush=True)
        print("[1/3] Extracting mono audio with FFmpeg...", flush=True)
        if audio.is_file():
            print("REUSE: audio", flush=True)
        else:
            part = work / "audio.part.wav"
            extract_audio(self.source, part, total)
            replace_file(part, audio)
        print(f"Audio extracted: {audio.stat().st_size / 1e6:.0f} MB", flush=True)
        return audio

    def _transcribe(self, audio: Path, work: Path) -> Path:
        print("[2/3] Transcribing with WhisperX (loading model, then speech detection; "
              "progress lines appear once recognition starts)...", flush=True)
        self._use_certifi_bundle()
        return WhisperPipeline(audio, work, self.options).run()

    def _write_outputs(self, result_file: Path) -> None:
        lines = transcript_lines(load_json(result_file).get("segments", []))
        if not lines:
            raise ValueError("Transcription contains no recognized speech")
        print("[3/3] Creating transcript.txt...", flush=True)
        self.text_path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
        shutil.copy2(result_file, self.json_path)

    @staticmethod
    def _use_certifi_bundle() -> None:
        try:
            import certifi
            os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        except ImportError:
            pass


