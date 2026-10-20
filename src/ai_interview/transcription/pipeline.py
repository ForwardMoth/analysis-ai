"""WhisperX in three checkpointed stages: recognition -> word alignment -> speakers."""

from dataclasses import dataclass
import gc
import json
import os
from pathlib import Path
import platform
import sys
import threading

from ..platform_utils import write_text_atomic

# Set AI_INTERVIEW_DEVICE=cuda for an NVIDIA GPU (needs a CUDA build of torch).
DEVICE = os.environ.get("AI_INTERVIEW_DEVICE", "cpu").strip() or "cpu"
COMPUTE_TYPE = "int8" if DEVICE == "cpu" else "float16"
# Speaker embeddings take ~45 of 60 minutes on CPU for a long recording; pyannote runs on the Apple GPU.
# ctranslate2 (ASR) has no MPS backend, so only diarization moves. Unsupported ops fall back to CPU.
DIARIZE_DEVICE = os.environ.get("AI_INTERVIEW_DIARIZE_DEVICE", "").strip() or (
    "mps" if DEVICE == "cpu" and sys.platform == "darwin" and platform.machine() == "arm64" else DEVICE)
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"


@dataclass(frozen=True)
class PipelineOptions:
    model: str
    language: str  # "ru" | "en" | "auto"
    speakers: int | None
    diarize: bool
    hf_token: str

    @property
    def whisper_language(self) -> str | None:
        return None if self.language == "auto" else self.language


def save_json(path: Path, data: dict) -> None:
    # atomic: an existing file is always a complete one
    write_text_atomic(path, json.dumps(data, ensure_ascii=False), ".part")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class WhisperPipeline:
    """Each finished stage is saved to `work`, so a rerun resumes from the last one."""

    def __init__(self, audio: Path, work: Path, options: PipelineOptions):
        self.audio = audio
        self.options = options
        tag = f"{options.model}_{options.language}"
        self.asr_file = work / f"asr_{tag}.json"
        self.aligned_file = work / f"aligned_{tag}.json"
        self.final_file = (work / f"final_{tag}_s{options.speakers or 0}.json"
                           if options.diarize else self.aligned_file)

    def run(self) -> Path:
        """Returns the JSON file holding the finished result."""
        if self.options.diarize and self.final_file.is_file():
            print("REUSE: final", flush=True)
            return self.final_file

        # Speakers depend on the audio only, so the Apple GPU diarizes while the CPU recognizes and aligns.
        from whisperx.diarize import assign_word_speakers

        self.diarize_percent = 0.0
        background = _Background(self._diarization, lambda: self.diarize_percent) if self.options.diarize else None
        result = self._align(self._recognized_or_aligned())
        if background is None:
            return self.aligned_file
        segments = background.result()
        save_json(self.final_file, assign_word_speakers(segments, result))
        return self.final_file

    # --- stages -------------------------------------------------------------

    def _recognized_or_aligned(self) -> dict:
        if self.asr_file.is_file() or self.aligned_file.is_file():
            print("REUSE: asr", flush=True)
            return load_json(self.asr_file if self.asr_file.is_file() else self.aligned_file)
        return self._recognize()

    def _recognize(self) -> dict:
        import numpy as np
        import whisperx

        print("STAGE: asr", flush=True)
        model = self._load_model(whisperx, np)
        result = model.transcribe(whisperx.load_audio(str(self.audio)), batch_size=4, chunk_size=30,
                                  print_progress=True, verbose=True)
        save_json(self.asr_file, result)
        del model
        gc.collect()
        return result

    def _load_model(self, whisperx, np):
        # Silero finds speech in seconds; pyannote's VAD took minutes on a long recording. Silero comes from
        # torch.hub (downloaded once), so without network on the first run fall back to pyannote.
        for vad_method in ("silero", "pyannote"):
            try:
                return self._build_model(whisperx, np, vad_method)
            except Exception as exc:  # noqa: BLE001
                if vad_method == "pyannote":
                    raise
                print(f"Silero VAD unavailable ({exc}), using pyannote", flush=True)

    def _build_model(self, whisperx, np, vad_method: str):
        return whisperx.load_model(
            self.options.model, DEVICE, compute_type=COMPUTE_TYPE, language=self.options.whisper_language,
            vad_method=vad_method,
            vad_options={"chunk_size": 30, "vad_onset": 0.5, "vad_offset": 0.363},
            asr_options={"beam_size": 5, "patience": 1.0, "length_penalty": 1.0,
                         "temperatures": list(np.arange(0, 1.0 + 1e-6, 0.2)),
                         "compression_ratio_threshold": 2.4, "log_prob_threshold": -1.0,
                         "no_speech_threshold": 0.6, "condition_on_previous_text": False,
                         "initial_prompt": None, "hotwords": None, "suppress_tokens": [-1],
                         "suppress_numerals": False},
            task="transcribe", threads=4)

    def _align(self, result: dict) -> dict:
        if self.aligned_file.is_file():
            print("REUSE: align", flush=True)
            return load_json(self.aligned_file)
        if "word_segments" in result:
            return result

        import whisperx

        print("STAGE: align", flush=True)
        language = result.get("language") or self.options.whisper_language or "en"
        align_model, meta = whisperx.load_align_model(language, DEVICE)
        if result["segments"]:
            result = whisperx.align(result["segments"], align_model, meta,
                                    whisperx.load_audio(str(self.audio)), DEVICE,
                                    interpolate_method="nearest", return_char_alignments=False,
                                    progress_callback=_print_align_progress)
        result["language"] = language
        save_json(self.aligned_file, result)
        del align_model
        gc.collect()
        return result

    def _on_diarize_progress(self, percent: float) -> None:
        self.diarize_percent = percent  # printed by _Background once recognition is done

    def _diarization(self):
        from whisperx.diarize import DiarizationPipeline

        pipeline = DiarizationPipeline(model_name=DIARIZATION_MODEL, token=self.options.hf_token, device=DIARIZE_DEVICE)
        speakers = self.options.speakers
        return pipeline(str(self.audio), min_speakers=speakers, max_speakers=speakers,
                        progress_callback=self._on_diarize_progress)


def _print_align_progress(percent: float) -> None:
    # print_progress=True reports the quick preparation loop; the callback follows the real alignment
    print(f"Progress: {percent:.2f}%...", flush=True)


class _Background:
    """Runs a function in a thread; `result()` waits for it and re-raises its error."""

    def __init__(self, func, progress=None) -> None:
        self._progress = progress
        self._value = self._error = None
        self._thread = threading.Thread(target=self._run, args=(func,), daemon=True)
        self._thread.start()

    def _run(self, func) -> None:
        try:
            self._value = func()
        except BaseException as exc:  # noqa: BLE001
            self._error = exc

    def result(self):
        if self._thread.is_alive():
            print("STAGE: diarize", flush=True)  # recognition is done, only the speakers are left
            while self._thread.is_alive():
                self._thread.join(timeout=2)
                if self._progress:
                    print(f"Diarize: {self._progress():.0f}%", flush=True)
        self._thread.join()
        if self._error:
            raise self._error
        return self._value
