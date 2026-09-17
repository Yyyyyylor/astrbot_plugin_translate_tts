"""Fish Audio S1 cues and guarded S2 natural-language directions."""

from __future__ import annotations

import re
from dataclasses import dataclass

FISH_EMOTIONS = frozenset(
    {
        "happy",
        "sad",
        "angry",
        "excited",
        "calm",
        "nervous",
        "confident",
        "surprised",
        "satisfied",
        "delighted",
        "scared",
        "worried",
        "upset",
        "frustrated",
        "depressed",
        "empathetic",
        "embarrassed",
        "disgusted",
        "moved",
        "proud",
        "relaxed",
        "grateful",
        "curious",
        "sarcastic",
        "disdainful",
        "unhappy",
        "anxious",
        "hysterical",
        "indifferent",
        "uncertain",
        "doubtful",
        "confused",
        "disappointed",
        "regretful",
        "guilty",
        "ashamed",
        "jealous",
        "envious",
        "hopeful",
        "optimistic",
        "pessimistic",
        "nostalgic",
        "lonely",
        "bored",
        "contemptuous",
        "sympathetic",
        "compassionate",
        "determined",
        "resigned",
    }
)

FISH_TONE_CUES = frozenset(
    {
        "in a hurry tone",
        "shouting",
        "screaming",
        "whispering",
        "soft tone",
        "emphasis",
    }
)

FISH_AUDIO_EFFECTS = frozenset(
    {
        "laughing",
        "chuckling",
        "sobbing",
        "crying loudly",
        "sighing",
        "groaning",
        "panting",
        "gasping",
        "yawning",
        "snoring",
        "clear throat",
    }
)

FISH_SPECIAL_EFFECTS = frozenset(
    {
        "audience laughing",
        "background laughter",
        "crowd laughing",
        "break",
        "long-break",
    }
)

FISH_S2_CUES = frozenset(
    FISH_EMOTIONS | FISH_TONE_CUES | FISH_AUDIO_EFFECTS | FISH_SPECIAL_EFFECTS
)
FISH_S1_CUES = frozenset(FISH_S2_CUES - {"emphasis", "clear throat"})
MAX_FISH_CUES = 3
MAX_FISH_S2_DIRECTION_CHARS = 96

FISH_S2_DIRECTION_EXAMPLES = (
    "very angry, high voice",
    "warm, gentle, reassuring, slightly slower",
    "quietly devastated, voice slightly trembling",
    "playful, slightly smug, lively pitch",
    "whispering",
    "shouting",
    "sigh",
    "long pause",
    "emphasis",
)

_S2_DIRECTION_PATTERN = re.compile(r"[a-z0-9][a-z0-9 ,.'’/-]*", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FishSegment:
    """A verbatim translated span with request-local cues placed before it."""

    text: str
    cues: tuple[str, ...] = ()


def allowed_fish_cues(model: str) -> frozenset[str]:
    """Return fixed S1 cues or documented S2 reference examples."""
    return FISH_S1_CUES if model == "s1" else FISH_S2_CUES


def normalize_fish_cues(value: object, model: str) -> tuple[str, ...]:
    """Keep safe request-local directions in model-returned order.

    S1 has a closed documented vocabulary. S2 accepts concise natural-language
    directions, so it uses structural validation instead of pretending that the
    S1 reference table is an exhaustive allowlist.
    """
    if not isinstance(value, list):
        return ()
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cue = " ".join(item.strip().lower().split()).strip(" ,.;:!?")
        if model == "s1":
            valid = cue in FISH_S1_CUES
        else:
            valid = (
                bool(cue)
                and len(cue) <= MAX_FISH_S2_DIRECTION_CHARS
                and _S2_DIRECTION_PATTERN.fullmatch(cue) is not None
            )
        if valid and cue not in normalized:
            normalized.append(cue)
        if len(normalized) == MAX_FISH_CUES:
            break
    return tuple(normalized)


def normalize_fish_segments(
    value: object, translated_text: str, model: str
) -> tuple[FishSegment, ...]:
    """Validate cue placement without allowing the controlled text to change."""
    if not isinstance(value, list) or not value:
        return ()
    segments: list[FishSegment] = []
    for item in value:
        if not isinstance(item, dict):
            return ()
        if set(item) != {"text", "cues"}:
            return ()
        text = item.get("text")
        if not isinstance(text, str) or not text:
            return ()
        segments.append(FishSegment(text, normalize_fish_cues(item.get("cues"), model)))
    if "".join(segment.text for segment in segments) != translated_text:
        return ()
    if model != "s1" and not segments[0].cues:
        return ()
    if not any(segment.cues for segment in segments):
        return ()
    return tuple(segments)
