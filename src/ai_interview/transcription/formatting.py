"""Turning WhisperX segments into readable, timestamped transcript lines."""

from dataclasses import dataclass

MAX_PAUSE_WITHIN_TURN = 3  # seconds of silence after which the same speaker starts a new turn
MAX_TURN_LENGTH = 900  # characters


def format_timestamp(seconds: float) -> str:
    seconds = max(0, int(float(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


@dataclass
class Turn:
    speaker: str
    start: float
    end: float
    text: str

    def can_absorb(self, speaker: str, start: float, text: str) -> bool:
        return (self.speaker == speaker
                and start - self.end <= MAX_PAUSE_WITHIN_TURN
                and len(self.text) + len(text) <= MAX_TURN_LENGTH)

    def render(self) -> str:
        return f"[{format_timestamp(self.start)}] {self.speaker}: {self.text}"


def group_turns(segments: list[dict]) -> list[Turn]:
    """Group adjacent segments from the same speaker into turns."""
    turns: list[Turn] = []
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        speaker = str(segment.get("speaker") or "UNKNOWN")
        start = float(segment.get("start", 0))
        end = float(segment.get("end", start))

        if turns and turns[-1].can_absorb(speaker, start, text):
            turns[-1].text += " " + text
            turns[-1].end = end
        else:
            turns.append(Turn(speaker, start, end, text))
    return turns


def transcript_lines(segments: list[dict]) -> list[str]:
    return [turn.render() for turn in group_turns(segments)]
