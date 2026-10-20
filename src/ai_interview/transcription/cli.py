"""Command line interface of the transcription pipeline."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from ..platform_utils import configure_console
from .pipeline import PipelineOptions
from .transcriber import InterviewTranscriber

DESCRIPTION = "Video/audio -> FFmpeg -> WhisperX -> transcript.txt (completely locally)."
REQUIRED_BINARIES = [
    ("ffmpeg", "Install FFmpeg first (macOS: brew install ffmpeg; Windows: winget install Gyan.FFmpeg, then restart the terminal)."),
    ("whisperx", "Install WhisperX in your Python environment (pip install whisperx)."),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("file", nargs="?", help="Path to the source video/audio file")
    parser.add_argument("--language", choices=["ru", "en", "auto"], default="ru",
                        help="Interview language (default: ru)")
    parser.add_argument("--model", default="small",
                        help="Whisper model (default: small; medium improves accuracy but is slower)")
    parser.add_argument("--speakers", type=int, default=None,
                        help="Set when the exact number of speakers is known, e.g. 2")
    parser.add_argument("--no-diarize", action="store_true",
                        help="Skip speaker identification; HF_TOKEN is then unnecessary")
    parser.add_argument("--work-dir", type=Path, default=None,
                        help="Keep intermediate results here so a rerun resumes from the last finished stage")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional output folder; by default: <video>_transcript/")
    return parser


def resolve_source(file_arg: str | None) -> Path:
    if not file_arg:
        file_arg = input("Drag or enter the path to the interview file: ").strip().strip('"').strip("'")
    return Path(file_arg).expanduser().resolve()


def missing_binary_error() -> str | None:
    for binary, install_hint in REQUIRED_BINARIES:
        if shutil.which(binary) is None:
            return f"Missing '{binary}'. {install_hint}"
    return None


def main() -> int:
    configure_console()
    parser = build_parser()
    args = parser.parse_args()

    source = resolve_source(args.file)
    if not source.is_file():
        print(f"File not found: {source}", file=sys.stderr)
        return 2
    if args.speakers is not None and args.speakers < 1:
        parser.error("--speakers must be positive")

    if error := missing_binary_error():
        print(error, file=sys.stderr)
        return 2

    token = os.environ.get("HF_TOKEN", "").strip()
    if not args.no_diarize and not token:
        print("HF_TOKEN is not set. To identify speakers, accept the pyannote model terms",
              "and set your Hugging Face read token in HF_TOKEN.",
              "Or rerun with --no-diarize to create a transcript without speakers.",
              sep="\n", file=sys.stderr)
        return 2

    output_dir = (args.output or source.parent / f"{source.stem}_transcript").expanduser().resolve()
    options = PipelineOptions(model=args.model, language=args.language, speakers=args.speakers,
                              diarize=not args.no_diarize, hf_token=token)
    transcriber = InterviewTranscriber(source, output_dir, args.work_dir, options)

    try:
        transcriber.run()
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Processing failed: {exc}", file=sys.stderr)
        return 1

    print(f"\nDone! Transcript: {transcriber.text_path}")
    print(f"JSON with timestamps: {transcriber.json_path}")
    if args.no_diarize:
        print("Speaker labels are disabled (--no-diarize).")
    else:
        print("Check speaker labels manually: SPEAKER_00 etc. are not real names.")
    return 0
