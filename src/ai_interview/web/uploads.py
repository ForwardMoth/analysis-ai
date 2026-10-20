"""Validation and streaming of the POST /api/jobs upload request."""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import BinaryIO
from urllib.parse import unquote

from ..platform_utils import safe_file_name
from . import config

LANGUAGES = ("ru", "en", "auto")


class BadRequest(Exception):
    """Carries the message that is sent back with HTTP 400."""


@dataclass(frozen=True)
class UploadRequest:
    length: int
    file_name: str  # safe for any OS filesystem
    title: str  # what the user sees in the library
    options: dict  # language, model, speakers, diarize

    @classmethod
    def parse(cls, query: dict[str, str], content_length: int) -> "UploadRequest":
        if content_length <= 0:
            raise BadRequest("Пустой файл")
        language = query.get("language", "ru")
        if language not in LANGUAGES:
            raise BadRequest("bad language")
        model = query.get("model", "small")
        if not re.fullmatch(r"[\w.\-]+", model):
            raise BadRequest("bad model")
        speakers = query.get("speakers", "")
        original = unquote(query.get("name", "interview")).replace("\\", "/").rsplit("/", 1)[-1] or "interview"
        options = {"language": language, "model": model,
                   "speakers": int(speakers) if speakers.isdigit() and int(speakers) > 0 else None,
                   "diarize": query.get("diarize", "1") == "1"}
        return cls(content_length, safe_file_name(original), Path(original).stem or original, options)


def stream_to_disk(stream: BinaryIO, length: int, dest: Path) -> None:
    """Videos can be many GB, so the body is copied chunk by chunk."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    remaining = length
    with dest.open("wb") as fh:
        while remaining > 0:
            chunk = stream.read(min(config.UPLOAD_CHUNK, remaining))
            if not chunk:
                break
            fh.write(chunk)
            remaining -= len(chunk)
    if remaining:
        dest.unlink(missing_ok=True)
        raise BadRequest("Загрузка прервана")
