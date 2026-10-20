"""Transcript metadata (meta.json) and the searchable library of finished transcripts."""

import json
from pathlib import Path
import re
import threading
import time
from typing import Callable

from ..platform_utils import write_text_atomic
from . import config


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def new_meta(transcript_id: str, name: str) -> dict:
    return {"id": transcript_id, "name": name, "created": now_iso(),
            "notes": [], "speakers": {}, "analyses": [], "livecoding": []}


class MetaStore:
    """meta.json holds name, notes, speaker names and the analysis list."""

    def __init__(self, results_dir: Path = config.RESULTS):
        self.results_dir = results_dir
        self._lock = threading.Lock()

    def transcript_dir(self, tid: str) -> Path:
        return self.results_dir / tid

    def transcript_file(self, tid: str) -> Path:
        return self.transcript_dir(tid) / "transcript.txt"

    def named_transcript(self, tid: str) -> str:
        """transcript.txt with the speaker names the user typed in instead of SPEAKER_00 and so on."""
        transcript = self.transcript_file(tid).read_text(encoding="utf-8")
        for label, real_name in self.load(tid)["speakers"].items():
            if real_name:
                transcript = transcript.replace(f"] {label}:", f"] {real_name}:")
        return transcript

    def _meta_file(self, tid: str) -> Path:
        return self.transcript_dir(tid) / "meta.json"

    def load(self, tid: str) -> dict | None:
        """Older transcripts without meta.json get default fields lazily."""
        transcript = self.transcript_file(tid)
        if not transcript.is_file():
            return None
        try:
            meta = json.loads(self._meta_file(tid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        created = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(transcript.stat().st_mtime))
        meta.setdefault("id", tid)
        meta.setdefault("name", "Без названия")
        meta.setdefault("created", created)
        meta.setdefault("notes", [])
        meta.setdefault("speakers", {})
        meta.setdefault("analyses", [])
        meta.setdefault("livecoding", [])
        return meta

    def create(self, meta: dict) -> None:
        self.transcript_dir(meta["id"]).mkdir(parents=True, exist_ok=True)
        self._write(meta)

    def update(self, tid: str, change: Callable[[dict], None]) -> dict | None:
        with self._lock:
            meta = self.load(tid)
            if meta is None:
                return None
            change(meta)
            self._write(meta)
            return meta

    def _write(self, meta: dict) -> None:
        path = self._meta_file(meta["id"])
        write_text_atomic(path, json.dumps(meta, ensure_ascii=False, indent=1), ".tmp")


class TranscriptLibrary:
    SNIPPET_BEFORE = 60
    SNIPPET_AFTER = 100

    def __init__(self, store: MetaStore):
        self.store = store

    def search(self, query: str) -> list[dict]:
        needle = query.strip().lower()
        items = []
        for directory in self._transcript_dirs():
            meta = self.store.load(directory.name)
            if not meta:
                continue
            text = (directory / "transcript.txt").read_text(encoding="utf-8", errors="replace")
            snippet = ""
            if needle:
                match_pos = text.lower().find(needle)
                if needle not in self._searchable_meta(meta) and match_pos < 0:
                    continue
                if match_pos >= 0:
                    snippet = self._snippet(text, match_pos)
            items.append(self._summary(meta, text, snippet))
        return sorted(items, key=lambda item: item["created"], reverse=True)

    def _transcript_dirs(self) -> list[Path]:
        results = self.store.results_dir
        if not results.is_dir():
            return []
        return [d for d in results.iterdir() if re.fullmatch(config.ID_PATTERN, d.name)]

    @staticmethod
    def _searchable_meta(meta: dict) -> str:
        return " ".join([meta["name"], *(note["text"] for note in meta["notes"])]).lower()

    @classmethod
    def _snippet(cls, text: str, pos: int) -> str:
        return text[max(0, pos - cls.SNIPPET_BEFORE):pos + cls.SNIPPET_AFTER].replace("\n", " ")

    @staticmethod
    def _summary(meta: dict, text: str, snippet: str) -> dict:
        timestamps = re.findall(r"^\[(\d\d:\d\d:\d\d)\]", text, re.M)
        return {"id": meta["id"], "name": meta["name"], "created": meta["created"],
                "length": timestamps[-1] if timestamps else "", "notes": len(meta["notes"]),
                "analyses": len(meta["analyses"]), "snippet": snippet}
