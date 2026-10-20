#!/usr/bin/env python3
"""Convert a local video/audio interview to a timestamped transcript using FFmpeg + WhisperX.

Install FFmpeg and WhisperX once, then run:
    python interview_to_transcript.py "/path/to/interview.mp4" --language ru --speakers 2

For speaker diarization, set HF_TOKEN before launch and accept the pyannote
speaker-diarization-community-1 model terms on Hugging Face.
"""

import sys

from ai_interview.transcription.cli import main

if __name__ == "__main__":
    sys.exit(main())
