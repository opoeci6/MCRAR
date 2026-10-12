"""The built-in game-scene queries for the blind rating set."""

from __future__ import annotations

from pathlib import Path

from mcrar.ml.bakeoff.common import BakeoffError

DEFAULT_QUERIES: tuple[str, ...] = (
    "tense stealth level, no vocals",
    "cozy village or town theme for a farming game",
    "epic orchestral boss battle",
    "8-bit chiptune for a retro platformer level",
    "calm exploration music for a forest",
    "dark ambient horror atmosphere",
    "cheerful upbeat main menu music",
    "sad emotional piano for a cutscene",
    "fast electronic music for a racing game",
    "medieval tavern music with folk instruments",
    "mysterious and quirky puzzle level music",
    "retro 80s synthwave for a night drive",
    "triumphant victory music",
    "relaxing lo-fi beats for a management sim",
    "spacey ambient synth pads for space exploration",
)


def load_queries(path: Path | None) -> list[str]:
    """The queries of ``path`` (one per line, blank lines ignored) or the built-in list."""
    if path is None:
        return list(DEFAULT_QUERIES)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise BakeoffError(f"cannot read queries file {path} ({type(exc).__name__})") from None
    queries = [line.strip() for line in text.splitlines() if line.strip()]
    if not queries:
        raise BakeoffError(f"queries file {path} has no queries")
    return queries


def query_ids(count: int) -> list[str]:
    """``q01``, ``q02``, ... (wider than two digits only when there are more than 99)."""
    width = max(2, len(str(count)))
    return [f"q{i:0{width}d}" for i in range(1, count + 1)]
