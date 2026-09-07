"""Provider-independent translation and basic emotion values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .fish_emotions import FishSegment

Emotion = Literal[
    "neutral",
    "happy",
    "sad",
    "angry",
    "fearful",
    "disgusted",
    "surprised",
    "calm",
]

EMOTIONS: frozenset[str] = frozenset(
    {"neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised", "calm"}
)


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """Validated text plus an optional, provider-independent emotion."""

    source_text: str
    text: str
    emotion: Emotion = "neutral"
    success: bool = True
    fish_cues: tuple[str, ...] = ()
    fish_segments: tuple[FishSegment, ...] = ()

    @classmethod
    def fallback(cls, source_text: str) -> TranslationResult:
        return cls(source_text, source_text, "neutral", False)
