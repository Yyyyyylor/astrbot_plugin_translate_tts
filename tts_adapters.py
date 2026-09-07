"""Resolve TTS instances and prepare request-local provider calls."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .config import TranslationSettings
from .emotion import Emotion, TranslationResult

FISH_TYPE = "fishaudio_tts_api"
ELEVEN_TYPE = "elevenlabs_tts_api"
MINIMAX_TYPE = "minimax_tts_api"
GEMINI_TYPE = "gemini_tts"

MINIMAX_EMOTION_MODELS = {
    "speech-02-hd",
    "speech-02-turbo",
    "speech-2.6-hd",
    "speech-2.6-turbo",
}
GEMINI_TTS_MODELS = {
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
    "gemini-3.1-flash-preview-tts",
}

_FISH_S2 = {
    "happy": "[happy]",
    "sad": "[sad]",
    "angry": "[angry]",
    "fearful": "[scared]",
    "disgusted": "[disgusted]",
    "surprised": "[surprised]",
    "calm": "[calm]",
}
_FISH_S1 = {
    "happy": "(happy)",
    "sad": "(sad)",
    "angry": "(angry)",
    "fearful": "(scared)",
    "disgusted": "(disgusted)",
    "surprised": "(surprised)",
    "calm": "(relaxed)",
}
_ELEVEN = {
    "happy": "[excited]",
    "sad": "[sad]",
    "angry": "[angry]",
    "fearful": "[fearful]",
    "disgusted": "[disgusted]",
    "surprised": "[surprised]",
    "calm": "[calm]",
}
_MINIMAX = {
    "happy": "happy",
    "sad": "sad",
    "angry": "angry",
    "fearful": "fearful",
    "disgusted": "disgusted",
    "surprised": "surprised",
    "calm": "calm",
}
_GEMINI = {
    "happy": "Speak in a clearly happy tone.",
    "sad": "Speak in a clearly sad tone.",
    "angry": "Speak in a controlled angry tone.",
    "fearful": "Speak in a fearful tone.",
    "disgusted": "Speak with a disgusted tone.",
    "surprised": "Speak in a surprised tone.",
    "calm": "Speak in a calm tone.",
}


def provider_type(provider: Any) -> str:
    try:
        value = provider.meta().type
    except (AttributeError, KeyError, TypeError, ValueError):
        value = getattr(provider, "provider_config", {}).get("type", "")
    return value if isinstance(value, str) else ""


@dataclass(frozen=True, slots=True)
class ProviderResolution:
    provider: Any
    kind: str
    translate: bool = True
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PreparedCall:
    provider: Any
    text: str
    adapter: str
    reason: str = ""


def resolve_provider(
    context: Any, upstream: Any, settings: TranslationSettings
) -> ProviderResolution:
    """Resolve an actual configured TTS instance without guessing credentials."""
    if settings.tts_provider_id:
        if context is None or not hasattr(context, "get_provider_by_id"):
            return ProviderResolution(
                upstream, provider_type(upstream), False, "provider_api_unavailable"
            )
        try:
            selected = context.get_provider_by_id(settings.tts_provider_id)
            all_tts = tuple(context.get_all_tts_providers())
        except (AttributeError, KeyError, TypeError, ValueError):
            return ProviderResolution(
                upstream, provider_type(upstream), False, "provider_api_unavailable"
            )
        if selected is None or not any(selected is item for item in all_tts):
            return ProviderResolution(
                upstream,
                provider_type(upstream),
                False,
                "invalid_explicit_tts_provider",
            )
        return ProviderResolution(selected, provider_type(selected))

    upstream_kind = provider_type(upstream)
    if settings.tts_selection_mode == "follow_upstream":
        return ProviderResolution(upstream, upstream_kind)
    if upstream_kind == FISH_TYPE:
        return ProviderResolution(upstream, upstream_kind)
    if context is None or not hasattr(context, "get_all_tts_providers"):
        return ProviderResolution(
            upstream, upstream_kind, True, "provider_api_unavailable"
        )
    try:
        all_tts = context.get_all_tts_providers()
    except (AttributeError, KeyError, TypeError, ValueError):
        return ProviderResolution(
            upstream, upstream_kind, True, "provider_api_unavailable"
        )
    fish = [provider for provider in all_tts if provider_type(provider) == FISH_TYPE]
    if len(fish) == 1:
        return ProviderResolution(fish[0], FISH_TYPE)
    reason = "fish_not_configured" if not fish else "ambiguous_fish_selection"
    return ProviderResolution(upstream, upstream_kind, True, reason)


def _copy_provider(
    provider: Any, expected_class_name: str, **mutable_copies: str
) -> Any:
    if type(provider).__name__ != expected_class_name or "get_audio" in getattr(
        provider, "__dict__", {}
    ):
        raise TypeError(
            "provider class or instance-patched get_audio cannot be copied safely"
        )
    clone = copy.copy(provider)
    for source_name, target_name in mutable_copies.items():
        value = getattr(provider, source_name)
        setattr(clone, target_name, copy.copy(value))
    return clone


def _prefix(marker: str | None, text: str) -> str:
    return f"{marker} {text}" if marker else text


def prepare_call(
    resolution: ProviderResolution,
    result: TranslationResult,
    settings: TranslationSettings,
    *,
    dynamic_emotion: bool = True,
) -> PreparedCall:
    """Create request-local text/state while leaving the shared instance untouched."""
    provider = resolution.provider
    kind = resolution.kind
    emotion: Emotion = result.emotion if dynamic_emotion else "neutral"

    if kind == FISH_TYPE:
        clone = _copy_provider(provider, "ProviderFishAudioTTSAPI", headers="headers")
        clone.set_model(settings.fish_model)
        clone.headers["model"] = settings.fish_model
        left, right = ("(", ")") if settings.fish_model == "s1" else ("[", "]")
        if dynamic_emotion and result.fish_segments:
            controlled = "".join(
                "".join(f"{left}{cue}{right}" for cue in segment.cues) + segment.text
                for segment in result.fish_segments
            )
            return PreparedCall(clone, controlled, "fish")
        markers: tuple[str, ...] = ()
        if dynamic_emotion and result.fish_cues:
            markers = tuple(f"{left}{cue}{right}" for cue in result.fish_cues)
        elif emotion != "neutral":
            markers = (
                (_FISH_S1 if settings.fish_model == "s1" else _FISH_S2)[emotion],
            )
        marker_text = "".join(markers) or None
        return PreparedCall(clone, _prefix(marker_text, result.text), "fish")

    if kind == ELEVEN_TYPE:
        model = str(getattr(provider, "model_name", ""))
        if model != "eleven_v3":
            return PreparedCall(provider, result.text, "plain", "unsupported_model")
        marker = _ELEVEN.get(emotion) if emotion != "neutral" else None
        return PreparedCall(provider, _prefix(marker, result.text), "elevenlabs_v3")

    if kind == MINIMAX_TYPE:
        model = str(getattr(provider, "model_name", ""))
        if model not in MINIMAX_EMOTION_MODELS:
            return PreparedCall(provider, result.text, "plain", "unsupported_model")
        if emotion == "neutral":
            return PreparedCall(provider, result.text, "minimax")
        try:
            clone = _copy_provider(
                provider,
                "ProviderMiniMaxTTSAPI",
                voice_setting="voice_setting",
            )
        except (AttributeError, TypeError):
            return PreparedCall(provider, result.text, "plain", "unsafe_provider_copy")
        clone.voice_setting["emotion"] = _MINIMAX[emotion]
        return PreparedCall(clone, result.text, "minimax")

    if kind == GEMINI_TYPE:
        model = str(getattr(provider, "model", ""))
        if model not in GEMINI_TTS_MODELS:
            return PreparedCall(provider, result.text, "plain", "unsupported_model")
        if emotion == "neutral":
            return PreparedCall(provider, result.text, "gemini")
        try:
            clone = _copy_provider(provider, "ProviderGeminiTTSAPI")
        except (AttributeError, TypeError):
            return PreparedCall(provider, result.text, "plain", "unsafe_provider_copy")
        existing = str(getattr(provider, "prefix", "") or "").strip()
        instruction = (
            f"{_GEMINI[emotion]} Synthesize speech only for the transcript after "
            "'Transcript:'; do not speak these directions."
        )
        clone.prefix = f"{existing} {instruction}".strip()
        return PreparedCall(clone, f"Transcript: {result.text}", "gemini")

    return PreparedCall(provider, result.text, "plain", "emotion_not_adapted")
