# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

The working metadata version is `0.1.0`; no release has been published.

### Added

- English and Simplified Chinese settings-panel localization through AstrBot's native WebUI language selector.
- History-free, tool-free translation immediately before existing TTS calls.
- Japanese default plus seven predefined target languages and one custom single-language option.
- Configurable translation provider, timeout, input/output limits, and concurrency bound.
- Original-text TTS fallback for translation errors and one original-text retry when translated synthesis fails or returns no audio.
- Original response preservation for normal non-streaming AstrBot 4.27.5 replies.
- Scoped compatibility adapter for `astrbot_plugin_proactive_chat` v1.2.5, based on commit `d1203524f29be248a4975bac1f7586e9557434ee`.
- Reversible, generation-aware runtime patch management.
- Compatibility status reporting, isolated unit tests, read-only probes, and bilingual documentation.

### Fixed

- Corrected Simplified Chinese README list labels that rendered literal Markdown emphasis markers.
- Kept `_conf_schema.json` as strict JSON and excluded it from Ruff formatting.

### Documentation

- Documented configuration, installation allowlist, reload/disable behavior, diagnostics, privacy boundaries, test commands, and the required live QQ acceptance checklist.
- Recorded the 2026-09-06 offline environment snapshot without treating source fingerprints as runtime or delivery evidence.

### Validation pending

- Live QQ Official private/group delivery and audio playback.
- Real translation LLM output quality and failure behavior.
- Real target-language synthesis for each selected TTS model and voice.
- Confirmation that the future loaded proactive-chat instance uses the source files already verified on disk.

### Security

- No source text, translated text, or credentials are intentionally written to plugin logs or persistent storage.
- Runtime adapters are limited by owner, task, session, source path, and active patch generation.
