"""A scope-bound proxy around the TTS provider selected by AstrBot."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any

from .diagnostics import exception_type_chain
from .emotion import TranslationResult
from .preprocess import preprocess_text
from .scope import TranslationScope, current_translation_scope
from .translation import TranslationService
from .tts_adapters import prepare_call, resolve_provider

logger = logging.getLogger("astrbot")


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

    async def _register_audio(self, audio: Any) -> None:
        register = getattr(self._service, "register_audio", None)
        if callable(register):
            await register(audio)

    def _emit(self, event: str, **fields: Any) -> None:
        diagnostics = getattr(self._service, "diagnostics", None)
        if diagnostics is not None:
            diagnostics.emit(
                event,
                trace_id=self._scope.trace_id,
                source=self._scope.source,
                **fields,
            )

    @staticmethod
    def _audio_kind(audio: Any) -> str:
        if not audio:
            return "empty"
        if isinstance(audio, str):
            return "url" if audio.startswith(("http://", "https://")) else "local_path"
        return type(audio).__name__

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
        conversion = len(self._scope.conversions)
        started = time.monotonic()
        settings = self._scope.settings
        context = getattr(
            self._service,
            "context",
            getattr(self._scope.owner, "context", None),
        )
        resolution = resolve_provider(context, self._provider, settings)
        entry.provider_type = resolution.kind
        self._scope.selected_provider_type = resolution.kind
        self._scope.selected_fish_model = (
            settings.fish_model if resolution.kind == "fishaudio_tts_api" else ""
        )
        entry.diagnostic = resolution.reason
        self._emit(
            "tts_conversion_started",
            detail=True,
            conversion=conversion,
            input_chars=len(source_text),
            provider_type=resolution.kind or "unknown",
            provider_action=("translate" if resolution.translate else "passthrough"),
        )
        if resolution.reason:
            logger.info(
                "Translate TTS provider selection degraded: reason=%s type=%s source=%s",
                resolution.reason,
                resolution.kind or "unknown",
                self._scope.source,
            )
        if not resolution.translate:
            audio = await original(*bound.args, **bound.kwargs)
            await self._register_audio(audio)
            entry.audio_result = audio
            self._emit(
                "tts_conversion_completed",
                conversion=conversion,
                translated=False,
                attempts=1,
                audio_kind=self._audio_kind(audio),
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
            return audio

        processed_text = preprocess_text(source_text, settings)
        entry.preprocessed_text = processed_text
        if not processed_text:
            entry.diagnostic = "preprocessed_empty"
            self._emit(
                "tts_conversion_skipped",
                severity="warning",
                conversion=conversion,
                reason="preprocessed_empty",
            )
            return None
        if self._scope.skip_translation:
            translated = TranslationResult(
                source_text,
                processed_text,
                self._scope.preview_emotion or "neutral",
                True,
            )
        else:
            translated = await self._service.translate_for_tts(
                processed_text, self._scope
            )
        if isinstance(translated, str):
            translated = TranslationResult(
                source_text, translated, "neutral", translated != source_text
            )
        if not translated.success:
            translated = TranslationResult.fallback(source_text)
        elif self._scope.preview_emotion:
            translated = TranslationResult(
                source_text, translated.text, self._scope.preview_emotion, True
            )
        translated = self._scope.apply_emotion_continuity(translated)
        entry.translated_text = translated.text
        entry.emotion = translated.emotion
        try:
            prepared = prepare_call(resolution, translated, settings)
        except (AttributeError, TypeError) as exc:
            entry.diagnostic = "unsafe_provider_copy"
            logger.warning(
                "Translate TTS request-local provider copy unavailable: type=%s source=%s",
                resolution.kind or "unknown",
                self._scope.source,
            )
            self._emit(
                "tts_conversion_failed",
                severity="warning",
                conversion=conversion,
                reason="unsafe_provider_copy",
                exception_types=exception_type_chain(exc),
            )
            raise
        entry.controlled_text = prepared.text
        entry.adapter = prepared.adapter
        if prepared.reason:
            entry.diagnostic = prepared.reason
            logger.info(
                "Translate TTS emotion adapter degraded: reason=%s type=%s source=%s",
                prepared.reason,
                resolution.kind or "unknown",
                self._scope.source,
            )
        selected_original = prepared.provider.get_audio
        bound.arguments["text"] = prepared.text
        attempts = 1
        try:
            audio = await selected_original(*bound.args, **bound.kwargs)
        except asyncio.CancelledError:
            self._emit(
                "tts_conversion_cancelled",
                conversion=conversion,
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
            raise
        except Exception as exc:
            if not translated.success:
                self._emit(
                    "tts_conversion_failed",
                    severity="warning",
                    conversion=conversion,
                    reason="original_tts_error",
                    attempts=1,
                    exception_types=exception_type_chain(exc),
                )
                raise
            self._emit(
                "tts_retry_original",
                severity="warning",
                conversion=conversion,
                reason="translated_tts_error",
                exception_types=exception_type_chain(exc),
            )
            fallback = prepare_call(
                resolution,
                TranslationResult(source_text, source_text, "neutral", False),
                settings,
                dynamic_emotion=False,
            )
            bound.arguments["text"] = fallback.text
            attempts = 2
            try:
                audio = await fallback.provider.get_audio(*bound.args, **bound.kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as fallback_exc:
                self._emit(
                    "tts_conversion_failed",
                    severity="warning",
                    conversion=conversion,
                    reason="original_retry_error",
                    attempts=2,
                    exception_types=exception_type_chain(fallback_exc),
                )
                raise
        else:
            if not audio and translated.success:
                self._emit(
                    "tts_retry_original",
                    severity="warning",
                    conversion=conversion,
                    reason="translated_tts_empty",
                )
                fallback = prepare_call(
                    resolution,
                    TranslationResult(source_text, source_text, "neutral", False),
                    settings,
                    dynamic_emotion=False,
                )
                bound.arguments["text"] = fallback.text
                attempts = 2
                try:
                    audio = await fallback.provider.get_audio(
                        *bound.args, **bound.kwargs
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as fallback_exc:
                    self._emit(
                        "tts_conversion_failed",
                        severity="warning",
                        conversion=conversion,
                        reason="original_retry_error",
                        attempts=2,
                        exception_types=exception_type_chain(fallback_exc),
                    )
                    raise
        entry.audio_result = audio
        await self._register_audio(audio)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        self._emit(
            "tts_conversion_completed",
            severity=(
                "warning"
                if elapsed_ms >= settings.slow_phase_warning_seconds * 1000
                else "info"
            ),
            conversion=conversion,
            translated=translated.success,
            attempts=attempts,
            provider_type=resolution.kind or "unknown",
            adapter=entry.adapter,
            audio_kind=self._audio_kind(audio),
            elapsed_ms=elapsed_ms,
        )
        return audio
