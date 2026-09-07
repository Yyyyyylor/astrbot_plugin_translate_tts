# Translate TTS for AstrBot

[简体中文](README-zh-CN.md) | English

Translate TTS changes only text that an existing AstrBot TTS path has already decided to synthesize. It keeps the original-language reply visible and sends the translation to a real AstrBot TTS provider instance. Japanese is the default target language. Basic emotion is enabled by default, and an unambiguous Fish instance is preferred with `s2.1-pro-free`.

The plugin does **not** add speech triggers, replace the chat response, mutate shared provider voice/settings, or edit AstrBot/proactive-chat source files.

## Compatibility and verification

| Component | Supported baseline | Current evidence |
| --- | --- | --- |
| AstrBot | `>=4.27.5,<4.28`; implemented against 4.27.5 | Unit tests plus a read-only 4.27.5 source/integration probe with fake translation and TTS providers |
| Platform | `qq_official` | The local configuration snapshot contains one enabled `qq_official` platform; live QQ delivery and playback have not been tested |
| Reply mode | Non-streaming | Unit tested; streaming results intentionally pass through |
| `astrbot_plugin_proactive_chat` | Exactly v1.2.5; reference commit `d1203524f29be248a4975bac1f7586e9557434ee` | The local on-disk source matches all pinned fingerprints; no loaded runtime instance was available to inspect |
| LLM/TTS providers | Configured AstrBot instances; emotion adapters for Fish, ElevenLabs v3, MiniMax Speech 02/2.6, and Gemini TTS | Real 4.27.5 provider serialization tested offline with fake transports; real synthesis and listening remain untested |

See [Compatibility and diagnostics](docs/compatibility.md) for exact runtime states, source probes, and the live acceptance checklist.

The local inspection above is an offline snapshot from 2026-09-06. No AstrBot/Python/uvicorn backend process was observed, and Translate TTS was not installed in the live plugin directory. It therefore proves neither active wrapper status nor actual QQ/model/TTS behavior.

## Behavior

- If the upstream path does not call TTS, this plugin makes no translation call.
- When TTS is called, the original text is kept once and the translation is synthesized by the original TTS provider.
- With emotion enabled, translation and basic emotion classification share one strict JSON `llm_generate` request. It does not invoke tools or append anything to conversation history.
- Provider controls are request-local. Unsupported providers and models receive plain translated text without invented parameters.
- Translation failure, timeout, invalid output, or a length violation falls back to synthesizing the complete original text.
- If translated-text synthesis fails or returns no audio, the original text is attempted once. Cancellation propagates without fallback.
- Existing normal-reply TTS probability/settings remain authoritative.
- Existing proactive-chat TTS enablement, segmentation, hooks, timing, and history remain authoritative. A per-call configuration copy forces original text without mutating session data.

The visible message remains the original-language text; the translation is not displayed. Text/audio ordering is controlled by the upstream path.

## Installation

1. Download `astrbot_plugin_translate_tts-v1.2.1.zip` from the [v1.2.1 release](https://github.com/Yyyyyylor/astrbot_plugin_translate_tts/releases/tag/v1.2.1).
2. In AstrBot WebUI, open the plugin manager and install the downloaded ZIP, or extract its root-level files into `AstrBot/data/plugins/astrbot_plugin_translate_tts`.
3. Do not copy this checkout's local `data`, `temp`, cache, database, or configuration artifacts into production. Documentation and tests are optional for runtime use.
4. Start AstrBot, or reload the plugin in **WebUI > Plugins**.
5. Select the translation LLM and target language in the plugin configuration, save, and reload once.

The settings panel is available in English and Simplified Chinese. Use the AstrBot WebUI language selector to choose **English** or **中文**; the plugin name, descriptions, hints, and target-language labels follow that choice. Reload the plugin after installing or updating the `.astrbot-plugin/i18n` files.

No third-party Python package is required. AstrBot must already have working LLM and TTS providers. Proactive messages require the supported proactive-chat version installed separately.

## Configuration

### Advanced controls added in 1.2

The native settings panel now exposes custom translation/emotion prompt modes, every preprocessing rule, cleanup retention and schedule, preview defaults, and reply-scoped emotion continuity. Custom prompts accept only the documented placeholders (`{target_language}`, `{emotion_options}`, and `{fish_cues}`); unknown placeholders or empty replacement prompts disable the plugin with a configuration error. A non-replaceable output contract and the existing strict JSON/text, refusal, tool-call, enum, and length checks still apply.

The **Translate TTS Control** Plugin Page supplies the operations that schema fields cannot represent safely: separate prompt reset buttons, preprocessing preview (never calls LLM/TTS), current cleanup status, two-step confirmed manual cleanup, and administrator-authenticated TTS preview. Preview first shows provider type, instance ID, model, voice, target language, emotion protocol, and possible-cost status; only its second confirmation performs synthesis. The page supports cancellation and a short-lived authenticated download. Chat administrators can use `/tts_preview [text]`, then `/tts_preview_confirm <token>`, or `/tts_preview_cancel`.

Preprocessing always keeps the untouched source for UI display and original-language fallback. If preprocessing produces an empty string, no translation or new synthesis is attempted. Continuity lives only in the current `TranslationScope`; modes are `off`, `conservative`, `allow_transition`, and `fixed_first`, with a configurable neutral-inheritance rule and segment cap. Fallback and the second synthesis attempt always use neutral, non-dynamic original text.

Cleanup is off by default and retains files for 30 days when enabled. Only real local audio paths returned through this plugin and recorded in its private manifest are eligible. URLs, directories, symlinks, unregistered files, paths outside AstrBot's temporary directory, and newly registered files are excluded. Cleanup unlinks individual files and never recursively empties a shared directory.

| Key | Default | Accepted values and effect |
| --- | --- | --- |
| `enabled` | `true` | Master switch; false makes both adapters pass through. |
| `emotion_enabled` | `true` | Enables structured emotion inference and supported-provider controls. False keeps translation and provider selection. |
| `tts_provider_id` | empty | Native TTS selector. A valid ID overrides selection mode; an invalid explicit ID preserves the untouched upstream path. |
| `tts_selection_mode` | `prefer_fish` | Empty-ID behavior: prefer upstream Fish or one configured Fish; `follow_upstream` keeps the upstream provider. |
| `fish_model` | `s2.1-pro-free` | Strict Fish allowlist. Sent in the actual HTTP `model` header; failures never retry a paid model. |
| `translation_provider_id` | empty | WebUI LLM selector. Empty resolves the current session provider; an explicitly selected unavailable provider falls back to original-text TTS. |
| `target_language` | `ja` | `ja`, `en`, `ko`, `zh-CN`, `zh-TW`, `fr`, `de`, `es`, or `custom`. |
| `custom_target_language` | empty | Required non-empty language name when the target is `custom`. |
| `translation_timeout_seconds` | `60` | Total timeout including concurrency wait; range 1–300 seconds. Remote LLMs commonly need 60–120 seconds. |
| `max_input_chars` | `4000` | Range 1–100000. Longer input bypasses translation without truncation. |
| `max_output_chars` | `12000` | Range 1–200000. Longer model output is rejected. |
| `max_concurrent_translations` | `2` | Range 1–100, scoped to this plugin instance. |
| `enable_proactive_compat` | `true` | Enables the v1.2.5 proactive-chat runtime adapter. |

Example generated AstrBot configuration (edit through WebUI when possible):

```json
{
  "enabled": true,
  "emotion_enabled": true,
  "tts_provider_id": "",
  "tts_selection_mode": "prefer_fish",
  "fish_model": "s2.1-pro-free",
  "translation_provider_id": "",
  "target_language": "ja",
  "custom_target_language": "",
  "translation_timeout_seconds": 60,
  "max_input_chars": 4000,
  "max_output_chars": 12000,
  "max_concurrent_translations": 2,
  "enable_proactive_compat": true
}
```

An empty translation provider requires AstrBot to resolve a current chat provider for the session. The TTS model and voice must support the target language; translation cannot add language support to a monolingual voice.

For Fish free development use, configure the official `https://api.fish.audio/v1` endpoint when appropriate for the account. The plugin preserves the configured endpoint and never moves credentials between domains.

### Emotion adapter matrix

| AstrBot provider type | Adapted models | Request control |
| --- | --- | --- |
| `fishaudio_tts_api` | `s2.1-pro-free`, `s2.1-pro`, `s2-pro`, `s1` | Full documented control set: 49 emotions, 6 tone cues, 11 audio effects, 5 special effects; up to 3 combined cues; S2 brackets or S1 fixed parentheses |
| `elevenlabs_tts_api` | `eleven_v3` only | Whitelisted v3 audio tag |
| `minimax_tts_api` | `speech-02-hd/turbo`, `speech-2.6-hd/turbo` | Request-local `voice_setting.emotion` |
| `gemini_tts` | Gemini 2.5 Flash/Pro Preview TTS and 3.1 Flash TTS Preview | Request-local direction and labeled transcript |
| Other types/models | Translation only | No emotion control is claimed or sent |

For Fish, the same translation call returns allowlisted `fish_cues` and optional `fish_segments`. Segments enable sentence transitions and phrase-local emphasis, but their text must concatenate to the plain translation exactly. Only exact cues from the official [Fish Emotion Control reference](https://docs.fish.audio/developer-guide/core-features/emotions) are accepted. Unknown, duplicate, or excess cues are discarded; effects are requested only when supported by the source text. S1 automatically rejects the S2-only `emphasis` and `clear throat` cues.

## Reloading, disabling, and upgrading

- **Reload:** save configuration and reload in WebUI. Runtime wrappers are generation-tagged; a newer generation deactivates the older one instead of stacking calls.
- **Disable:** set `enabled=false` and reload, or disable/unload in WebUI. Unload restores an attribute only if it still points to this plugin's wrapper, preserving later third-party wrappers.
- **Disable proactive compatibility only:** set `enable_proactive_compat=false` and reload; normal non-streaming replies can remain active.
- **Upgrade:** replace files while stopped, then start/reload and inspect compatibility logs. Check older custom-language configuration in WebUI.

Outside supported versions, the affected adapter fails closed and logs `incompatible`; it does not guess at changed internal APIs.

## Diagnostics and troubleshooting

Search logs for `Translate TTS normal compatibility` and `Translate TTS proactive compatibility`. The healthy runtime state is `signature_compatible_unverified`: required signatures matched, but this does not prove a source commit or successful QQ delivery.

- **No translated audio or translation request:** confirm upstream TTS actually triggered, the result is non-streaming, this plugin is enabled for the session, and a TTS provider is selected.
- **Original-language audio with a `timeout` fallback:** raise `translation_timeout_seconds` to 60–120 seconds and reload the plugin. The timeout includes concurrency waiting and the LLM response. Also verify that the selected translation provider is available.
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
