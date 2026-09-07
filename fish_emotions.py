"""Documented Fish Audio S2/S1 emotion and delivery cue allowlists."""

from __future__ import annotations

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


@dataclass(frozen=True, slots=True)
class FishSegment:
    """A verbatim translated span with request-local cues placed before it."""

    text: str
    cues: tuple[str, ...] = ()


def allowed_fish_cues(model: str) -> frozenset[str]:
    """Return the documented fixed cue vocabulary for the selected model."""
    return FISH_S1_CUES if model == "s1" else FISH_S2_CUES


def normalize_fish_cues(value: object, model: str) -> tuple[str, ...]:
    """Keep at most three distinct documented cues, in model-returned order."""
    if not isinstance(value, list):
        return ()
    allowed = allowed_fish_cues(model)
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cue = " ".join(item.strip().lower().split())
        if cue in allowed and cue not in normalized:
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
        text = item.get("text")
        if not isinstance(text, str) or not text:
            return ()
        segments.append(FishSegment(text, normalize_fish_cues(item.get("cues"), model)))
    if "".join(segment.text for segment in segments) != translated_text:
        return ()
    if not any(segment.cues for segment in segments):
        return ()
    return tuple(segments)
