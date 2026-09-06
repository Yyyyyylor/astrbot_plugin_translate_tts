"""Per-call state for isolated TTS translation adapters."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from .config import TranslationSettings


@dataclass(slots=True)
class ConversionEntry:
    """One real upstream ``get_audio`` call and its associated source component."""

    source_text: str
    source_component: Any = None
    translated_text: str | None = None
    audio_result: Any = None

    @property
    def produced_audio(self) -> bool:
        return bool(self.audio_result)


@dataclass(slots=True)
class TranslationScope:
    """Mutable state owned by one pipeline iteration and one conversation."""

    source: Literal["normal", "proactive"]
    unified_msg_origin: str
    settings: TranslationSettings
    owner: Any = None
    event: Any = None
    owner_task: asyncio.Task[Any] | None = None
    active: bool = True
    conversions: list[ConversionEntry] = field(default_factory=list)
    pre_tts_plain_components: list[Any] = field(default_factory=list)
    pre_tts_record_ids: set[int] = field(default_factory=set)
    _next_plain_index: int = 0

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

    def is_owned_by_current_task(self) -> bool:
        return self.owner_task is not None and asyncio.current_task() is self.owner_task


current_translation_scope: ContextVar[TranslationScope | None] = ContextVar(
    "translate_tts_scope",
    default=None,
)
