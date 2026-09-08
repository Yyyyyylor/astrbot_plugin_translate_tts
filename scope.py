"""Per-call state for isolated TTS translation adapters."""

from __future__ import annotations

import asyncio
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from .config import TranslationSettings
from .emotion import TranslationResult


@dataclass(slots=True)
class ConversionEntry:
    """One real upstream ``get_audio`` call and its associated source component."""

    source_text: str
    source_component: Any = None
    translated_text: str | None = None
    preprocessed_text: str | None = None
    emotion: str = "neutral"
    controlled_text: str | None = None
    provider_type: str = ""
    adapter: str = "plain"
    diagnostic: str = ""
    audio_result: Any = None
    started_monotonic: float = field(default_factory=time.monotonic)

    @property
    def produced_audio(self) -> bool:
        return bool(self.audio_result)


@dataclass(slots=True)
class TranslationScope:
    """Mutable state owned by one pipeline iteration and one conversation."""

    source: Literal["normal", "proactive", "preview"]
    unified_msg_origin: str
    settings: TranslationSettings
    owner: Any = None
    event: Any = None
    owner_task: asyncio.Task[Any] | None = None
    active: bool = True
    selected_provider_type: str = ""
    selected_fish_model: str = ""
    conversions: list[ConversionEntry] = field(default_factory=list)
    pre_tts_plain_components: list[Any] = field(default_factory=list)
    pre_tts_record_ids: set[int] = field(default_factory=set)
    _next_plain_index: int = 0
    continuity_emotion: str | None = None
    continuity_segment_count: int = 0
    skip_translation: bool = False
    preview_emotion: str | None = None
    trace_id: str = field(default_factory=lambda: secrets.token_hex(4))
    started_monotonic: float = field(default_factory=time.monotonic)
    diagnostic_phase: str = "scope_created"
    translation_provider_ref: str = "none"

    def snapshot_before_tts(self, *, plain_type: type, record_type: type) -> None:
        """Capture component identities at the getter call immediately before TTS."""
        if self.event is None:
            return
        result = self.event.get_result()
        chain = getattr(result, "chain", ()) if result is not None else ()
        self.pre_tts_plain_components = [
            component
            for component in chain
            if isinstance(component, plain_type) and len(component.text) > 1
        ]
        self.pre_tts_record_ids = {
            id(component) for component in chain if isinstance(component, record_type)
        }
        self._next_plain_index = 0

    def begin_conversion(self, source_text: str) -> ConversionEntry:
        source_component = None
        if self._next_plain_index < len(self.pre_tts_plain_components):
            candidate = self.pre_tts_plain_components[self._next_plain_index]
            if getattr(candidate, "text", None) == source_text:
                source_component = candidate
            self._next_plain_index += 1
        entry = ConversionEntry(source_text, source_component=source_component)
        self.conversions.append(entry)
        return entry

    def deactivate(self) -> None:
        self.active = False
        self.continuity_emotion = None
        self.continuity_segment_count = 0

    def apply_emotion_continuity(self, result: TranslationResult) -> TranslationResult:
        """Resolve emotion only within this reply-scoped object."""
        settings = self.settings
        mode = settings.emotion_continuity_mode
        if (
            not result.success
            or not settings.emotion_enabled
            or not settings.emotion_continuity_enabled
            or mode == "off"
            or self.continuity_segment_count >= settings.max_continuity_segments
        ):
            return result
        self.continuity_segment_count += 1
        incoming = result.emotion
        previous = self.continuity_emotion
        resolved = incoming
        if previous is None:
            self.continuity_emotion = incoming
        elif mode == "fixed_first":
            resolved = previous
        elif mode == "conservative":
            if incoming == "neutral" and settings.neutral_inherits:
                resolved = previous
        elif mode == "allow_transition":
            if incoming == "neutral" and settings.neutral_inherits:
                resolved = previous
            elif incoming != "neutral":
                self.continuity_emotion = incoming
        if resolved == incoming:
            return result
        return TranslationResult(
            result.source_text,
            result.text,
            resolved,
            result.success,
            (),
            (),
        )

    def is_owned_by_current_task(self) -> bool:
        return self.owner_task is not None and asyncio.current_task() is self.owner_task


current_translation_scope: ContextVar[TranslationScope | None] = ContextVar(
    "translate_tts_scope",
    default=None,
)
