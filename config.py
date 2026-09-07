"""Validated, immutable configuration snapshots for a TTS translation call."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .prompts import validate_custom_prompt

LANGUAGE_NAMES = {
    "ja": "Japanese",
    "en": "English",
    "ko": "Korean",
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
}

TTS_SELECTION_MODES = {"prefer_fish", "follow_upstream"}
FISH_MODELS = {"s2.1-pro-free", "s2.1-pro", "s2-pro", "s1"}
PROMPT_MODES = {"builtin", "append", "replace"}
CLEANUP_PERIODS = {"startup", "12h", "daily", "weekly"}
CODE_BLOCK_MODES = {"preserve", "skip", "replace"}
MARKDOWN_MODES = {"preserve", "remove"}
URL_MODES = {"full", "domain", "replace", "skip"}
EMOJI_MODES = {"preserve", "name", "skip"}
TABLE_MODES = {"lines", "summary", "skip"}
QUOTE_MODES = {"preserve", "skip"}
CONTINUITY_MODES = {"off", "conservative", "allow_transition", "fixed_first"}


class ConfigurationError(ValueError):
    """A configuration value cannot be used safely."""


def _bounded_int(
    config: Mapping[str, Any], key: str, default: int, minimum: int, maximum: int
) -> int:
    value = config.get(key, default)
    if isinstance(value, bool):
        raise ConfigurationError(f"{key} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"{key} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigurationError(f"{key} must be between {minimum} and {maximum}")
    return parsed


@dataclass(frozen=True, slots=True)
class TranslationSettings:
    """Settings copied for one call so live config edits cannot leak into it."""

    enabled: bool = True
    emotion_enabled: bool = True
    tts_provider_id: str = ""
    tts_selection_mode: str = "prefer_fish"
    fish_model: str = "s2.1-pro-free"
    translation_provider_id: str = ""
    target_language: str = "ja"
    custom_target_language: str = ""
    translation_timeout_seconds: int = 60
    max_input_chars: int = 4000
    max_output_chars: int = 12000
    max_concurrent_translations: int = 2
    enable_proactive_compat: bool = True
    custom_prompts_enabled: bool = False
    translation_prompt_mode: str = "builtin"
    translation_prompt_text: str = ""
    emotion_prompt_mode: str = "builtin"
    emotion_prompt_text: str = ""
    auto_cleanup_tts_files: bool = False
    tts_file_retention_days: int = 30
    cleanup_check_period: str = "daily"
    preprocessing_enabled: bool = False
    code_block_mode: str = "preserve"
    code_block_replacement: str = "code block omitted"
    markdown_decoration_mode: str = "preserve"
    url_mode: str = "full"
    url_replacement: str = "link"
    emoji_mode: str = "preserve"
    table_mode: str = "lines"
    table_summary_text: str = "table omitted"
    quote_mode: str = "preserve"
    collapse_whitespace: bool = True
    max_preprocessed_chars: int = 4000
    emotion_continuity_enabled: bool = False
    emotion_continuity_mode: str = "off"
    neutral_inherits: bool = True
    max_continuity_segments: int = 20
    preview_text: str = ""
    preview_emotion: str = "neutral"
    preview_translate: bool = True
    preview_tts_provider_id: str = ""

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> TranslationSettings:
        settings = cls(
            enabled=bool(config.get("enabled", True)),
            emotion_enabled=bool(config.get("emotion_enabled", True)),
            tts_provider_id=str(config.get("tts_provider_id", "") or "").strip(),
            tts_selection_mode=str(
                config.get("tts_selection_mode", "prefer_fish") or "prefer_fish"
            ).strip(),
            fish_model=str(
                config.get("fish_model", "s2.1-pro-free") or "s2.1-pro-free"
            ).strip(),
            translation_provider_id=str(
                config.get("translation_provider_id", "") or ""
            ).strip(),
            target_language=str(config.get("target_language", "ja") or "ja").strip(),
            custom_target_language=str(
                config.get("custom_target_language", "") or ""
            ).strip(),
            translation_timeout_seconds=_bounded_int(
                config, "translation_timeout_seconds", 60, 1, 300
            ),
            max_input_chars=_bounded_int(config, "max_input_chars", 4000, 1, 100_000),
            max_output_chars=_bounded_int(
                config, "max_output_chars", 12000, 1, 200_000
            ),
            max_concurrent_translations=_bounded_int(
                config, "max_concurrent_translations", 2, 1, 100
            ),
            enable_proactive_compat=bool(config.get("enable_proactive_compat", True)),
            custom_prompts_enabled=bool(config.get("custom_prompts_enabled", False)),
            translation_prompt_mode=str(
                config.get("translation_prompt_mode", "builtin") or "builtin"
            ).strip(),
            translation_prompt_text=str(
                config.get("translation_prompt_text", "") or ""
            ),
            emotion_prompt_mode=str(
                config.get("emotion_prompt_mode", "builtin") or "builtin"
            ).strip(),
            emotion_prompt_text=str(config.get("emotion_prompt_text", "") or ""),
            auto_cleanup_tts_files=bool(config.get("auto_cleanup_tts_files", False)),
            tts_file_retention_days=_bounded_int(
                config, "tts_file_retention_days", 30, 1, 365
            ),
            cleanup_check_period=str(
                config.get("cleanup_check_period", "daily") or "daily"
            ).strip(),
            preprocessing_enabled=bool(config.get("preprocessing_enabled", False)),
            code_block_mode=str(
                config.get("code_block_mode", "preserve") or "preserve"
            ).strip(),
            code_block_replacement=str(
                config.get("code_block_replacement", "code block omitted") or ""
            ),
            markdown_decoration_mode=str(
                config.get("markdown_decoration_mode", "preserve") or "preserve"
            ).strip(),
            url_mode=str(config.get("url_mode", "full") or "full").strip(),
            url_replacement=str(config.get("url_replacement", "link") or ""),
            emoji_mode=str(config.get("emoji_mode", "preserve") or "preserve").strip(),
            table_mode=str(config.get("table_mode", "lines") or "lines").strip(),
            table_summary_text=str(
                config.get("table_summary_text", "table omitted") or ""
            ),
            quote_mode=str(config.get("quote_mode", "preserve") or "preserve").strip(),
            collapse_whitespace=bool(config.get("collapse_whitespace", True)),
            max_preprocessed_chars=_bounded_int(
                config, "max_preprocessed_chars", 4000, 1, 100_000
            ),
            emotion_continuity_enabled=bool(
                config.get("emotion_continuity_enabled", False)
            ),
            emotion_continuity_mode=str(
                config.get("emotion_continuity_mode", "off") or "off"
            ).strip(),
            neutral_inherits=bool(config.get("neutral_inherits", True)),
            max_continuity_segments=_bounded_int(
                config, "max_continuity_segments", 20, 1, 100
            ),
            preview_text=str(config.get("preview_text", "") or ""),
            preview_emotion=str(config.get("preview_emotion", "neutral") or "neutral")
            .strip()
            .lower(),
            preview_translate=bool(config.get("preview_translate", True)),
            preview_tts_provider_id=str(
                config.get("preview_tts_provider_id", "") or ""
            ).strip(),
        )
        if settings.tts_selection_mode not in TTS_SELECTION_MODES:
            raise ConfigurationError(
                f"unsupported tts_selection_mode: {settings.tts_selection_mode}"
            )
        if settings.fish_model not in FISH_MODELS:
            raise ConfigurationError(f"unsupported fish_model: {settings.fish_model}")
        enum_fields = (
            ("translation_prompt_mode", settings.translation_prompt_mode, PROMPT_MODES),
            ("emotion_prompt_mode", settings.emotion_prompt_mode, PROMPT_MODES),
            ("cleanup_check_period", settings.cleanup_check_period, CLEANUP_PERIODS),
            ("code_block_mode", settings.code_block_mode, CODE_BLOCK_MODES),
            (
                "markdown_decoration_mode",
                settings.markdown_decoration_mode,
                MARKDOWN_MODES,
            ),
            ("url_mode", settings.url_mode, URL_MODES),
            ("emoji_mode", settings.emoji_mode, EMOJI_MODES),
            ("table_mode", settings.table_mode, TABLE_MODES),
            ("quote_mode", settings.quote_mode, QUOTE_MODES),
            (
                "emotion_continuity_mode",
                settings.emotion_continuity_mode,
                CONTINUITY_MODES,
            ),
        )
        for key, value, allowed in enum_fields:
            if value not in allowed:
                raise ConfigurationError(f"unsupported {key}: {value}")
        if settings.preview_emotion not in {
            "neutral",
            "happy",
            "sad",
            "angry",
            "fearful",
            "disgusted",
            "surprised",
            "calm",
        }:
            raise ConfigurationError(
                f"unsupported preview_emotion: {settings.preview_emotion}"
            )
        if settings.custom_prompts_enabled:
            try:
                validate_custom_prompt(
                    settings.translation_prompt_text,
                    settings.translation_prompt_mode,
                    {"target_language", "emotion_options", "fish_cues"},
                )
                validate_custom_prompt(
                    settings.emotion_prompt_text,
                    settings.emotion_prompt_mode,
                    {"target_language", "emotion_options", "fish_cues"},
                )
            except ValueError as exc:
                raise ConfigurationError(str(exc)) from exc
        settings.target_language_name()
        return settings

    def target_language_name(self) -> str:
        if self.target_language == "custom":
            if not self.custom_target_language:
                raise ConfigurationError(
                    "custom_target_language is required when target_language is custom"
                )
            return self.custom_target_language
        try:
            return LANGUAGE_NAMES[self.target_language]
        except KeyError as exc:
            raise ConfigurationError(
                f"unsupported target_language: {self.target_language}"
            ) from exc
