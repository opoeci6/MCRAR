"""The rule-based query parser: pure, deterministic, no model and no network.

Hard-constraint phrases (BPM, vocals, duration, licence) are recognised, turned into filters and
removed from the text that is embedded. Soft cues (energy and tempo words, genre and mood
labels) become preferences and stay in the text. Filters set explicitly in the request win over
parsed ones, group by group (the BPM pair and the duration pair are never mixed). The one
exception is the licence: when both set a limit, the stricter one applies.

``QueryParser`` is the seam for a smarter parser (M7's LLM parser) with the same contract.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Protocol

from mcrar.licensing import RISK_ORDER
from mcrar.recommend.query import ParsedQuery, Preferences, SearchRequest, Vocal
from mcrar.recommend.vocab import GENRE, MOODTHEME, Vocabulary

BPM_AROUND_SPREAD = 10.0
JINGLE_MAX_S = 20.0
LOW_ENERGY, HIGH_ENERGY = 0.3, 0.8
TEMPO_WORDS = {"slow": 75.0, "upbeat": 125.0, "fast": 145.0}
ENERGY_LOW_WORDS = ("calm", "relaxing", "relaxed", "chill", "peaceful", "soft", "quiet")
ENERGY_LOW_WORDS += ("ambient", "sleepy")
ENERGY_HIGH_WORDS = ("energetic", "intense", "aggressive", "powerful", "epic", "driving")
ENERGY_HIGH_WORDS += ("fast", "action")

_NUM = r"(\d+(?:\.\d+)?)"
_DASH = r"(?:-|–|—|to)"
_BPM = r"\s*bpm(?!\w)"
_UNDER = r"(?:(?<!\w)(?:under|below|less\s+than|slower\s+than|up\s+to|at\s+most)\s*|<=?\s*)"
_OVER = r"(?:(?<!\w)(?:over|above|more\s+than|faster\s+than|at\s+least)\s*|>=?\s*)"
_UNITS = r"(seconds?|secs?|minutes?|mins?|s)(?!\w)"


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


BPM_BETWEEN = _rx(rf"(?<!\w)between\s+{_NUM}\s*(?:bpm\s*)?and\s*{_NUM}{_BPM}")
BPM_RANGE = _rx(rf"(?<![\w.]){_NUM}\s*(?:bpm\s*)?{_DASH}\s*{_NUM}{_BPM}")
BPM_MAX = _rx(rf"{_UNDER}{_NUM}{_BPM}")
BPM_MIN = _rx(rf"{_OVER}{_NUM}{_BPM}")
BPM_AROUND = _rx(
    rf"(?:(?<!\w)(?:around|about|approx\.?|approximately|roughly)\s+|~\s*)?(?<![\w.]){_NUM}{_BPM}"
)
DURATION_MAX = _rx(
    rf"(?:(?<!\w)(?:under|shorter\s+than|less\s+than|below|within|up\s+to|at\s+most)\s*|<=?\s*)"
    rf"{_NUM}\s*{_UNITS}"
)
DURATION_MIN = _rx(
    rf"(?:(?<!\w)(?:longer\s+than|over|more\s+than|above|at\s+least)\s*|>=?\s*){_NUM}\s*{_UNITS}"
)
JINGLE = _rx(r"(?<!\w)(?:jingles?|stingers?|stings?|short\s+cues?)(?!\w)")
INSTRUMENTAL = _rx(
    r"(?<!\w)(?:(?:no|without)\s+(?:vocals?|voices?|singing|lyrics)|instrumentals?)(?!\w)"
)
VOCAL = _rx(r"(?<!\w)(?:(?:with|female|male)\s+vocals?|vocals?|singing|sung)(?!\w)")
COMMERCIAL = _rx(
    r"(?<!\w)(?:safe\s+for\s+commercial(?:\s+use)?|for\s+(?:my|a)\s+commercial\s+game"
    r"|(?:for\s+)?commercial\s+use|royalty[- ]free\s+for\s+games?)(?!\w)"
)
NO_ATTRIBUTION = _rx(r"(?<!\w)(?:no\s+attribution|cc0|public\s+domain)(?!\w)")

_WORD_CHARS = r"[\w-]"
ENERGY_LOW = _rx(rf"(?<!{_WORD_CHARS})(?:{'|'.join(ENERGY_LOW_WORDS)})(?!{_WORD_CHARS})")
ENERGY_HIGH = _rx(rf"(?<!{_WORD_CHARS})(?:{'|'.join(ENERGY_HIGH_WORDS)})(?!{_WORD_CHARS})")
TEMPO = {w: _rx(rf"(?<!{_WORD_CHARS}){w}(?!{_WORD_CHARS})") for w in TEMPO_WORDS}

# Words that do not make a query descriptive on their own, and connectors left dangling at the
# ends of the text once a constraint phrase was cut out of it.
_DANGLING = frozenset("and with for but or at in of to that is a an the some".split())
_FILLER = frozenset("music track tracks song songs tune tunes sound sounds something".split())


class QueryParser(Protocol):
    """Turns a request into a :class:`ParsedQuery` (the LLM parser of M7 implements this too)."""

    def parse(self, request: SearchRequest, vocab: Vocabulary) -> ParsedQuery: ...


def _cut(rx: re.Pattern[str], text: str) -> tuple[re.Match[str] | None, str]:
    """The first match of ``rx`` and ``text`` with every match of it removed."""
    return rx.search(text), rx.sub(" ", text)


def _number(value: float) -> str:
    return f"{value:g}"


def _seconds(value: float) -> str:
    return f"{value / 60:g} min" if value >= 120 else f"{value:g} s"


def _to_seconds(amount: str, unit: str) -> float:
    return float(amount) * (60.0 if unit.lower().startswith("m") else 1.0)


def _parse_bpm(text: str) -> tuple[str, tuple[float | None, float | None] | None, str | None]:
    for rx in (BPM_BETWEEN, BPM_RANGE):
        m, cut = _cut(rx, text)
        if m:
            low, high = sorted((float(m.group(1)), float(m.group(2))))
            return cut, (low, high), f"BPM {_number(low)}-{_number(high)}"
    low = high = None
    m_max, text = _cut(BPM_MAX, text)
    m_min, text = _cut(BPM_MIN, text)
    if m_max:
        high = float(m_max.group(1))
    if m_min:
        low = float(m_min.group(1))
    if low is not None and high is not None and low > high:
        low, high = high, low
    if low is not None or high is not None:
        parts = []
        if low is not None:
            parts.append(f"BPM ≥ {_number(low)}")
        if high is not None:
            parts.append(f"BPM ≤ {_number(high)}")
        return text, (low, high), ", ".join(parts)
    m, text = _cut(BPM_AROUND, text)
    if m:
        centre = float(m.group(1))
        low, high = max(centre - BPM_AROUND_SPREAD, 0.0), centre + BPM_AROUND_SPREAD
        note = f"BPM around {_number(centre)} ({_number(low)}-{_number(high)})"
        return text, (low, high), note
    return text, None, None


def _parse_duration(
    text: str,
) -> tuple[str, tuple[float | None, float | None] | None, str | None]:
    m_max, text = _cut(DURATION_MAX, text)
    m_min, text = _cut(DURATION_MIN, text)
    high = _to_seconds(m_max.group(1), m_max.group(2)) if m_max else None
    low = _to_seconds(m_min.group(1), m_min.group(2)) if m_min else None
    if low is not None and high is not None and low > high:
        low, high = high, low
    jingle, text = _cut(JINGLE, text)
    parts = []
    if low is not None:
        parts.append(f"duration ≥ {_seconds(low)}")
    if high is not None:
        parts.append(f"duration ≤ {_seconds(high)}")
    if jingle and high is None:
        high = JINGLE_MAX_S
        parts.append(f"jingle: duration ≤ {_seconds(JINGLE_MAX_S)}")
    if low is None and high is None:
        return text, None, None
    return text, (low, high), ", ".join(parts)


def _clean(text: str) -> str | None:
    """Tidy what is left of the text after cutting; None when nothing descriptive remains."""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?:\s*[,;:]\s*){2,}", ", ", text)
    previous = None
    while previous != text:
        previous = text
        text = text.strip(" ,;:.!-")
        words = text.split(" ")
        if words and words[0].lower() in _DANGLING:
            text = " ".join(words[1:])
        elif words and words[-1].lower() in _DANGLING:
            text = " ".join(words[:-1])
    words = re.findall(r"[\w'&-]+", text.lower())
    if not words or all(w in _FILLER or w in _DANGLING for w in words):
        return None
    return text


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


class RuleParser:
    """The default parser (see the module docstring)."""

    def parse(self, request: SearchRequest, vocab: Vocabulary) -> ParsedQuery:
        ui = request.filters
        raw = (request.text or "").strip()
        notes: list[str] = []

        text = raw
        text, bpm, bpm_note = _parse_bpm(text)
        text, duration, duration_note = _parse_duration(text)
        instrumental, text = _cut(INSTRUMENTAL, text)
        vocal, text = _cut(VOCAL, text)
        commercial, text = _cut(COMMERCIAL, text)
        no_attr, text = _cut(NO_ATTRIBUTION, text)

        parsed_vocal: Vocal | None = None
        vocal_note: str | None = None
        if instrumental and vocal:
            vocal_note = "both instrumental and vocal were asked: no vocal filter applied"
        elif instrumental:
            parsed_vocal, vocal_note = "instrumental", "instrumental only"
        elif vocal:
            parsed_vocal, vocal_note = "vocal", "vocal tracks only"

        parsed_risk = None
        risk_note = None
        if commercial or no_attr:
            parsed_risk = "green"
            risk_note = "licence: green only (safe for commercial use)"
            if no_attr:
                risk_note = (
                    "licence: green only; no attribution asked, but CC BY tracks still need credit"
                )

        # Explicit filters win, group by group; the licence is the exception: the stricter wins.
        max_risk = ui.max_risk
        risk_suffix = ""
        if parsed_risk and (ui.max_risk == "unknown" or ui.max_risk == parsed_risk):
            max_risk = parsed_risk
        elif parsed_risk and RISK_ORDER.index(parsed_risk) < RISK_ORDER.index(ui.max_risk):
            max_risk = parsed_risk
            risk_suffix = f" (stricter than your max_risk={ui.max_risk}, so it applies)"
        elif parsed_risk:
            risk_suffix = f" (ignored: your stricter max_risk={ui.max_risk} applies)"
        bpm_set = ui.bpm_min is not None or ui.bpm_max is not None
        duration_set = ui.duration_min_s is not None or ui.duration_max_s is not None
        filters = replace(
            ui,
            max_risk=max_risk,
            vocal=ui.vocal or parsed_vocal,
            bpm_min=ui.bpm_min if bpm_set else (bpm[0] if bpm else None),
            bpm_max=ui.bpm_max if bpm_set else (bpm[1] if bpm else None),
            duration_min_s=ui.duration_min_s
            if duration_set
            else (duration[0] if duration else None),
            duration_max_s=ui.duration_max_s
            if duration_set
            else (duration[1] if duration else None),
        )
        override = " (ignored: the filter you set wins)"
        for found, note, overridden in (
            (bpm, bpm_note, bpm_set),
            (duration, duration_note, duration_set),
            (parsed_vocal, vocal_note, ui.vocal is not None and ui.vocal != parsed_vocal),
        ):
            if note:
                notes.append(note + (override if found and overridden else ""))
        if risk_note:
            notes.append(risk_note + risk_suffix)

        semantic = _clean(text) if raw else None

        # Soft cues, read from the text that is left (constraint phrases no longer count).
        cues = semantic or ""
        energies = []
        if ENERGY_LOW.search(cues):
            energies.append(LOW_ENERGY)
        if ENERGY_HIGH.search(cues):
            energies.append(HIGH_ENERGY)
        energy = _mean(energies) if energies else None
        if energy is not None:
            notes.append(f"energy preference {energy:.2f}")
        bpm_target = None
        has_bpm_filter = filters.bpm_min is not None or filters.bpm_max is not None
        if not has_bpm_filter:
            targets = [value for word, value in TEMPO_WORDS.items() if TEMPO[word].search(cues)]
            if targets:
                bpm_target = _mean(targets)
                notes.append(f"tempo preference ~{_number(bpm_target)} BPM")
        hints = vocab.match(cues) if cues else {}
        genre_hints = hints.get(GENRE, ())
        mood_hints = hints.get(MOODTHEME, ())
        if genre_hints:
            notes.append("genre: " + ", ".join(genre_hints))
        if mood_hints:
            notes.append("mood: " + ", ".join(mood_hints))

        return ParsedQuery(
            semantic_text=semantic,
            filters=filters,
            preferences=Preferences(
                energy_target=energy,
                bpm_target=bpm_target,
                genre_hints=tuple(genre_hints),
                mood_hints=tuple(mood_hints),
            ),
            notes=notes,
        )


def parse(request: SearchRequest, vocab: Vocabulary) -> ParsedQuery:
    """Parse with the rule parser."""
    return RuleParser().parse(request, vocab)
