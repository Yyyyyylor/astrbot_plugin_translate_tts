"""Validated, immutable configuration snapshots for a TTS translation call."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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
    translation_provider_id: str = ""
    target_language: str = "ja"
    custom_target_language: str = ""
    translation_timeout_seconds: int = 15
    max_input_chars: int = 4000
    max_output_chars: int = 12000
    max_concurrent_translations: int = 2
    enable_proactive_compat: bool = True

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> TranslationSettings:
        settings = cls(
            enabled=bool(config.get("enabled", True)),
            translation_provider_id=str(
                config.get("translation_provider_id", "") or ""
            ).strip(),
            target_language=str(config.get("target_language", "ja") or "ja").strip(),
            custom_target_language=str(
                config.get("custom_target_language", "") or ""
            ).strip(),
            translation_timeout_seconds=_bounded_int(
                config, "translation_timeout_seconds", 15, 1, 120
            ),
            max_input_chars=_bounded_int(config, "max_input_chars", 4000, 1, 100_000),
            max_output_chars=_bounded_int(
                config, "max_output_chars", 12000, 1, 200_000
            ),
            max_concurrent_translations=_bounded_int(
                config, "max_concurrent_translations", 2, 1, 100
            ),
            enable_proactive_compat=bool(config.get("enable_proactive_compat", True)),
        )
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
