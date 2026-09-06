"""A scope-bound proxy around the TTS provider selected by AstrBot."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from typing import Any

from .scope import TranslationScope, current_translation_scope
from .translation import TranslationService


class TranslatedTTSProviderProxy:
    """Translate only safe ``get_audio(text)`` calls made in the owning scope."""

    def __init__(
        self,
        provider: Any,
        scope: TranslationScope,
        service: TranslationService,
        is_adapter_active: Callable[[], bool],
    ) -> None:
        self._provider = provider
        self._scope = scope
        self._service = service
        self._is_adapter_active = is_adapter_active

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    def _scope_matches(self) -> bool:
        return (
            self._is_adapter_active()
            and self._scope.active
            and self._scope.is_owned_by_current_task()
            and current_translation_scope.get() is self._scope
        )

    async def get_audio(self, *args: Any, **kwargs: Any) -> Any:
        original = self._provider.get_audio
        if not self._scope_matches():
            return await original(*args, **kwargs)
        try:
            bound = inspect.signature(original).bind(*args, **kwargs)
        except (TypeError, ValueError):
            return await original(*args, **kwargs)
        if "text" not in bound.arguments:
            return await original(*args, **kwargs)
        source_text = bound.arguments["text"]
        if not isinstance(source_text, str):
            return await original(*args, **kwargs)

        entry = self._scope.begin_conversion(source_text)
        translated = await self._service.translate_for_tts(source_text, self._scope)
        entry.translated_text = translated
        bound.arguments["text"] = translated
        try:
            audio = await original(*bound.args, **bound.kwargs)
        except asyncio.CancelledError:
            raise
        except Exception:
            if translated == source_text:
                raise
            bound.arguments["text"] = source_text
            audio = await original(*bound.args, **bound.kwargs)
        else:
            if not audio and translated != source_text:
                bound.arguments["text"] = source_text
                audio = await original(*bound.args, **bound.kwargs)
        entry.audio_result = audio
        return audio
