"""The tag vocabulary: genre and mood/theme labels with display names and synonyms.

The label ids are the ones the tagging models (M3b) predict. When ``models/registry.json``
exists its label sets win (schema in ``docs/handover/M3b-tagging.md`` section 4.1); a missing or
unreadable registry silently falls back to the built-in lists, which hold the same ids.
Matching is on whole words, case-insensitive, with ``-`` and a space interchangeable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcrar.config import Settings

GENRE = "genre"
MOODTHEME = "moodtheme"
LABEL_SETS = (GENRE, MOODTHEME)

# FMA top-level genres.
DEFAULT_GENRES = (
    "blues classical country easy-listening electronic experimental folk hip-hop instrumental "
    "international jazz old-time-historic pop rock soul-rnb spoken"
).split()
# MTG-Jamendo mood/theme tags.
DEFAULT_MOODTHEMES = (
    "action adventure advertising background ballad calm children christmas commercial cool "
    "corporate dark deep documentary drama dramatic dream emotional energetic epic fast film fun "
    "funny game groovy happy heavy holiday hopeful inspiring love meditative melancholic melodic "
    "motivational movie nature party positive powerful relaxing retro romantic sad sexy slow soft "
    "soundscape space sport summer trailer travel upbeat uplifting"
).split()

DEFAULT_DISPLAY = {
    "hip-hop": "Hip-Hop",
    "soul-rnb": "Soul / R&B",
    "old-time-historic": "Old-Time / Historic",
    "easy-listening": "Easy Listening",
}

# phrase -> (label set, label) pairs. A phrase may point at labels of several sets.
SYNONYMS: dict[str, tuple[tuple[str, str], ...]] = {
    "hip hop": ((GENRE, "hip-hop"),),
    "hiphop": ((GENRE, "hip-hop"),),
    "rap": ((GENRE, "hip-hop"),),
    "r&b": ((GENRE, "soul-rnb"),),
    "rnb": ((GENRE, "soul-rnb"),),
    "soul": ((GENRE, "soul-rnb"),),
    "edm": ((GENRE, "electronic"),),
    "electronica": ((GENRE, "electronic"),),
    "spooky": ((MOODTHEME, "dark"),),
    "creepy": ((MOODTHEME, "dark"),),
    "scary": ((MOODTHEME, "dark"),),
    "chill": ((MOODTHEME, "relaxing"),),
    "chiptune": ((GENRE, "electronic"), (MOODTHEME, "game")),
    "8-bit": ((GENRE, "electronic"), (MOODTHEME, "game")),
    "8 bit": ((GENRE, "electronic"), (MOODTHEME, "game")),
    "sci-fi": ((MOODTHEME, "space"),),
}

_ID = re.compile(r"[a-z0-9-]+")


def _display(label: str) -> str:
    return DEFAULT_DISPLAY.get(label) or label.replace("-", " ").title()


def _phrase_pattern(phrase: str) -> str:
    """Regex for a phrase on word boundaries, where ``-`` and a space are interchangeable."""
    parts = re.split(r"[-\s]+", phrase.strip().lower())
    return r"[-\s]+".join(re.escape(p) for p in parts if p)


@dataclass(frozen=True)
class LabelSet:
    """The labels of one set: ids in a stable order and their display names."""

    name: str
    labels: tuple[str, ...]
    display: Mapping[str, str]

    def display_name(self, label: str) -> str:
        return self.display.get(label) or _display(label)


class Vocabulary:
    """Genre and mood/theme labels, with synonym matching over free text."""

    def __init__(self, label_sets: Mapping[str, LabelSet]) -> None:
        self._sets = dict(label_sets)
        self._phrases: list[tuple[re.Pattern[str], str, str]] = []
        seen: set[tuple[str, str, str]] = set()

        def add(phrase: str, set_name: str, label: str) -> None:
            pattern = _phrase_pattern(phrase)
            if pattern and (pattern, set_name, label) not in seen:
                seen.add((pattern, set_name, label))
                self._phrases.append(
                    (re.compile(rf"(?<![\w-]){pattern}(?![\w-])", re.IGNORECASE), set_name, label)
                )

        for set_name, label_set in self._sets.items():
            for label in label_set.labels:
                add(label, set_name, label)
                add(label_set.display_name(label), set_name, label)
        for phrase, targets in SYNONYMS.items():
            for set_name, label in targets:
                if set_name in self._sets and label in self._sets[set_name].labels:
                    add(phrase, set_name, label)

    # -- construction ----------------------------------------------------------------------

    @classmethod
    def default(cls) -> Vocabulary:
        return cls(
            {
                GENRE: LabelSet(GENRE, tuple(DEFAULT_GENRES), {}),
                MOODTHEME: LabelSet(MOODTHEME, tuple(DEFAULT_MOODTHEMES), {}),
            }
        )

    @classmethod
    def from_registry(cls, path: Path) -> Vocabulary:
        """Labels from ``registry.json``; sets it lacks (or a missing/broken file) use defaults."""
        sets = dict(cls.default()._sets)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            declared = data["label_sets"]
        except (OSError, ValueError, KeyError, TypeError):
            return cls(sets)
        if not isinstance(declared, dict):
            return cls(sets)
        for name in LABEL_SETS:
            entry = declared.get(name)
            if not isinstance(entry, dict):
                continue
            labels = entry.get("labels")
            if not isinstance(labels, list):
                continue
            ids = tuple(dict.fromkeys(x for x in labels if isinstance(x, str) and _ID.fullmatch(x)))
            if not ids:
                continue
            display = entry.get("display")
            names = (
                {k: v for k, v in display.items() if isinstance(k, str) and isinstance(v, str)}
                if isinstance(display, dict)
                else {}
            )
            sets[name] = LabelSet(name, ids, names)
        return cls(sets)

    @classmethod
    def load(cls, settings: Settings) -> Vocabulary:
        return cls.from_registry(settings.models_dir / "registry.json")

    # -- lookups ---------------------------------------------------------------------------

    @property
    def label_set_names(self) -> tuple[str, ...]:
        return tuple(self._sets)

    def labels(self, label_set: str) -> tuple[str, ...]:
        return self._sets[label_set].labels

    def display_name(self, label_set: str, label: str) -> str:
        return self._sets[label_set].display_name(label)

    def has(self, label_set: str, label: str) -> bool:
        return label_set in self._sets and label in self._sets[label_set].labels

    def match(self, text: str) -> dict[str, tuple[str, ...]]:
        """The labels named in ``text`` (ids, display names or synonyms), per label set, in
        order of first appearance."""
        found: list[tuple[int, str, str]] = []
        for pattern, set_name, label in self._phrases:
            hit = pattern.search(text)
            if hit:
                found.append((hit.start(), set_name, label))
        found.sort()
        out: dict[str, list[str]] = {name: [] for name in self._sets}
        for _, set_name, label in found:
            if label not in out[set_name]:
                out[set_name].append(label)
        return {name: tuple(labels) for name, labels in out.items()}

    def resolve(self, label_set: str, names: Sequence[str]) -> tuple[str, ...]:
        """Map user-given names (ids, display names, synonyms) to label ids of one set.

        Raises ``ValueError`` listing the valid ids when a name is unknown.
        """
        resolved: list[str] = []
        for name in names:
            name = name.strip()
            if not name:
                continue
            labels = self.match(name).get(label_set, ())
            if not labels:
                valid = ", ".join(self.labels(label_set))
                raise ValueError(f"unknown {label_set} label '{name}'; choose from: {valid}")
            resolved.extend(label for label in labels if label not in resolved)
        return tuple(resolved)
