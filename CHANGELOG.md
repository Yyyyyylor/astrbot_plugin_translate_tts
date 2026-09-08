# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.2] - 2026-09-08

### Added

- Privacy-safe structured diagnostics with ephemeral trace IDs, phase timings, hashed provider references, provider timeout/proxy-source metadata, a bounded in-memory event buffer, an administrator command, and a bilingual Control Page status card.
- Separate WebUI-configurable translation queue timeout so concurrency waiting no longer consumes the LLM call deadline.

### Fixed

- Distinguish plugin deadline expiry from nested LLM provider HTTP/SDK timeouts; increasing the plugin timeout no longer hides the actual timeout owner in logs.

### Documentation

- Documented Docker proxy reachability and separated AstrBot QQ Official `APIReturnNoneError`/WebSocket recovery from plugin translation failures.

## [Unreleased]

## [1.2.1] - 2026-09-07

### Fixed

- Raised the default translation timeout from 15 to 60 seconds, expanded the supported ceiling to 300 seconds, and included the active limit in timeout logs so ordinary remote LLM latency is less likely to cause original-language TTS fallback.

## [1.2.0] - 2026-09-07

### Added

- Safe built-in/append/replace translation and emotion prompts with controlled placeholders and protected output validation.
- Deterministic pre-translation handling for fenced code, Markdown decoration, URLs, emoji, Markdown tables, quotes, whitespace, and bounded output.
- Reply-scoped emotion continuity modes without confidence fields or cross-message persistence.
- Manifest-only local audio registration, scheduled retention cleanup, status reporting, and confirmed manual cleanup.
- Administrator-only, two-step TTS preview commands and a small AstrBot Plugin Page for prompt reset, preprocessing preview, provider/cost inspection, cancellation, confirmed synthesis, downloads, and cleanup.
- Complete English/Simplified Chinese localization for the Control Page, plus prominent placeholder guidance beneath both custom-prompt fields.

### Safety

- Preview uses the formal provider resolver, translator, emotion adapters, isolated provider copies, timeout, cancellation, original fallback, and two-attempt ceiling.
- Cleanup ignores URLs, directories, symlinks, out-of-root paths, and files absent from the plugin manifest; it never recursively clears shared directories.
- Old configuration remains valid through defaults; active calls retain immutable settings snapshots across WebUI saves and reloads.

## [1.1.0] - 2026-09-07

### Added

- One-call structured translation plus basic emotion classification with a strict eight-value vocabulary.
- Real TTS provider selection and request-local adapters for Fish S2/S1, ElevenLabs v3, supported MiniMax Speech 02/2.6 models, and Gemini TTS.
- Complete documented Fish cue control: 49 emotions, six tone cues, 11 audio effects, five special effects, and safe combinations of up to three cues; S1 automatically uses its smaller fixed set.
- An offline parameter probe using the real AstrBot 4.27.5 provider classes and fake HTTP/SDK transports.

### Changed

- Fish defaults to `s2.1-pro-free` and sends that model in the actual request header on every Fish attempt.
- Emotion is enabled by default but can be disabled independently of translation and provider selection.

### Safety

- Shared provider headers, voice settings, prefixes, clients, voices, endpoints, and credentials are not mutated.
- Unsupported providers/models receive plain translated text; invalid explicit TTS IDs preserve the untouched upstream path.
- Fish free failures never retry a paid Fish model.

## [1.0.0] - 2026-09-07

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

[Unreleased]: https://github.com/Yyyyyylor/astrbot_plugin_translate_tts/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/Yyyyyylor/astrbot_plugin_translate_tts/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/Yyyyyylor/astrbot_plugin_translate_tts/compare/v1.0.0...v1.2.0
[1.0.0]: https://github.com/Yyyyyylor/astrbot_plugin_translate_tts/releases/tag/v1.0.0
