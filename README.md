# Translate TTS for AstrBot

[简体中文](README-zh-CN.md) | English

Translate TTS changes only text that an existing AstrBot TTS path has already decided to synthesize. It keeps the original-language reply visible and sends the translation to the TTS provider selected by the original path. Japanese is the default target language.

The plugin does **not** add speech triggers, replace the chat response, change the TTS provider or voice, or edit AstrBot/proactive-chat source files.

## Compatibility and verification

| Component | Supported baseline | Current evidence |
| --- | --- | --- |
| AstrBot | `>=4.27.5,<4.28`; implemented against 4.27.5 | Unit tests plus a read-only 4.27.5 source/integration probe with fake translation and TTS providers |
| Platform | `qq_official` | The local configuration snapshot contains one enabled `qq_official` platform; live QQ delivery and playback have not been tested |
| Reply mode | Non-streaming | Unit tested; streaming results intentionally pass through |
| `astrbot_plugin_proactive_chat` | Exactly v1.2.5; reference commit `d1203524f29be248a4975bac1f7586e9557434ee` | The local on-disk source matches all pinned fingerprints; no loaded runtime instance was available to inspect |
| LLM/TTS providers | Providers configured in AstrBot | Fake-provider tests only; real translation and target-language speech have not been tested |

See [Compatibility and diagnostics](docs/compatibility.md) for exact runtime states, source probes, and the live acceptance checklist.

The local inspection above is an offline snapshot from 2026-09-06. No AstrBot/Python/uvicorn backend process was observed, and Translate TTS was not installed in the live plugin directory. It therefore proves neither active wrapper status nor actual QQ/model/TTS behavior.

## Behavior

- If the upstream path does not call TTS, this plugin makes no translation call.
- When TTS is called, the original text is kept once and the translation is synthesized by the original TTS provider.
- Translation uses a separate, history-free `llm_generate` request. It does not invoke tools or append the translation to conversation history.
- Translation failure, timeout, invalid output, or a length violation falls back to synthesizing the complete original text.
- If translated-text synthesis fails or returns no audio, the original text is attempted once. Cancellation propagates without fallback.
- Existing normal-reply TTS probability/settings remain authoritative.
- Existing proactive-chat TTS enablement, segmentation, hooks, timing, and history remain authoritative. A per-call configuration copy forces original text without mutating session data.

The visible message remains the original-language text; the translation is not displayed. Text/audio ordering is controlled by the upstream path.

## Installation

1. Download `astrbot_plugin_translate_tts-v1.0.0.zip` from the [v1.0.0 release](https://github.com/Yyyyyylor/astrbot_plugin_translate_tts/releases/tag/v1.0.0).
2. In AstrBot WebUI, open the plugin manager and install the downloaded ZIP, or extract its root-level files into `AstrBot/data/plugins/astrbot_plugin_translate_tts`.
3. Do not copy this checkout's local `data`, `temp`, cache, database, or configuration artifacts into production. Documentation and tests are optional for runtime use.
4. Start AstrBot, or reload the plugin in **WebUI > Plugins**.
5. Select the translation LLM and target language in the plugin configuration, save, and reload once.

The settings panel is available in English and Simplified Chinese. Use the AstrBot WebUI language selector to choose **English** or **中文**; the plugin name, descriptions, hints, and target-language labels follow that choice. Reload the plugin after installing or updating the `.astrbot-plugin/i18n` files.

No third-party Python package is required. AstrBot must already have working LLM and TTS providers. Proactive messages require the supported proactive-chat version installed separately.

## Configuration

| Key | Default | Accepted values and effect |
| --- | --- | --- |
| `enabled` | `true` | Master switch; false makes both adapters pass through. |
| `translation_provider_id` | empty | WebUI LLM selector. Empty resolves the current session provider; an explicitly selected unavailable provider falls back to original-text TTS. |
| `target_language` | `ja` | `ja`, `en`, `ko`, `zh-CN`, `zh-TW`, `fr`, `de`, `es`, or `custom`. |
| `custom_target_language` | empty | Required non-empty language name when the target is `custom`. |
| `translation_timeout_seconds` | `15` | Total timeout including concurrency wait; range 1–120 seconds. |
| `max_input_chars` | `4000` | Range 1–100000. Longer input bypasses translation without truncation. |
| `max_output_chars` | `12000` | Range 1–200000. Longer model output is rejected. |
| `max_concurrent_translations` | `2` | Range 1–100, scoped to this plugin instance. |
| `enable_proactive_compat` | `true` | Enables the v1.2.5 proactive-chat runtime adapter. |

Example generated AstrBot configuration (edit through WebUI when possible):

```json
{
  "enabled": true,
  "translation_provider_id": "",
  "target_language": "ja",
  "custom_target_language": "",
  "translation_timeout_seconds": 15,
  "max_input_chars": 4000,
  "max_output_chars": 12000,
  "max_concurrent_translations": 2,
  "enable_proactive_compat": true
}
```

An empty translation provider requires AstrBot to resolve a current chat provider for the session. The TTS model and voice must support the target language; translation cannot add language support to a monolingual voice.

## Reloading, disabling, and upgrading

- **Reload:** save configuration and reload in WebUI. Runtime wrappers are generation-tagged; a newer generation deactivates the older one instead of stacking calls.
- **Disable:** set `enabled=false` and reload, or disable/unload in WebUI. Unload restores an attribute only if it still points to this plugin's wrapper, preserving later third-party wrappers.
- **Disable proactive compatibility only:** set `enable_proactive_compat=false` and reload; normal non-streaming replies can remain active.
- **Upgrade:** replace files while stopped, then start/reload and inspect compatibility logs. Check older custom-language configuration in WebUI.

Outside supported versions, the affected adapter fails closed and logs `incompatible`; it does not guess at changed internal APIs.

## Diagnostics and troubleshooting

Search logs for `Translate TTS normal compatibility` and `Translate TTS proactive compatibility`. The healthy runtime state is `signature_compatible_unverified`: required signatures matched, but this does not prove a source commit or successful QQ delivery.

- **No translated audio or translation request:** confirm upstream TTS actually triggered, the result is non-streaming, this plugin is enabled for the session, and a TTS provider is selected.
- **Original-language audio:** inspect nearby `TTS translation fallback` logs; check provider availability, timeout, limits, and custom target name.
- **Translated synthesis retries original:** the voice may not support the target language or returned no audio.
- **No visible original text:** confirm the adapter is not `incompatible`. For proactive chat, metadata must report exactly `1.2.5`.
- **Proactive is `not_installed`:** load/enable proactive-chat and reload this plugin if needed.
- **Repeated speech after reload:** unload both plugins once, load proactive-chat first, then this plugin; retain `superseded`/signature logs for diagnosis.

The plugin intentionally logs source category, fallback reason, error type, and compatibility state without source text, translation, or credentials. AstrBot and providers may log separately.

## Privacy and security

TTS-selected text is sent to the configured translation LLM; its translation (or fallback source) is sent to the TTS provider. Review both providers' retention and network policies. The translation request contains no conversation history, images, audio, tools, or persona, but source text can still be sensitive.

The plugin does not persist translations. Its runtime wrappers do not edit AstrBot/proactive-chat files or shared session configuration dictionaries.

## Development and tests

From the directory containing the `translate_tts` package:

```powershell
python -m pytest translate_tts\tests
ruff check translate_tts
ruff format --check translate_tts
```

The opt-in read-only source probes and their limits are documented in [Compatibility and diagnostics](docs/compatibility.md). Neither unit tests nor probes contact a real LLM, TTS service, or QQ.

## License

MIT. See [LICENSE](LICENSE).
