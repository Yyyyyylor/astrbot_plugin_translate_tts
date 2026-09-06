# Compatibility and diagnostics

This document separates runtime signature compatibility, pinned-source verification, simulated integration, and live end-to-end acceptance. Passing one level is not evidence for the levels after it.

## Supported matrix

| Path | Supported baseline | Required runtime surface | Unsupported/degraded behavior |
| --- | --- | --- | --- |
| Normal reply | AstrBot 4.27.5, non-streaming | Async-generator `ResultDecorateStage.process(self, event)` and async `Context.get_using_tts_provider_async(self, umo)` | Streaming replies pass through. Signature mismatch disables the normal adapter. |
| Proactive reply | `astrbot_plugin_proactive_chat` v1.2.5, reference commit `d1203524f29be248a4975bac1f7586e9557434ee` | Async bound `_send_proactive_message(session_id, text)`, synchronous bound `_get_session_config(session_id)`, and synchronous `Context.get_using_tts_provider(self, umo)` | Missing/inactive reports `not_installed`; any other version or signature mismatch reports `incompatible`. |
| Delivery | AstrBot 4.27.5 `qq_official` | Existing AstrBot/proactive-chat sending and media-upload paths | No platform-specific upload or retry code is added. Other platforms are not declared supported. |

`metadata.yaml` declares `astrbot_version: ">=4.27.5,<4.28"`, only `qq_official`, and the project repository `https://github.com/Yyyyyylor/astrbot_plugin_translate_tts`.

## Local offline inspection snapshot

The following facts were checked read-only on 2026-09-06. They describe files and process state on this machine, not a deployed or live-validated plugin:

- `C:\.D\code\AstrBot\backend\app\astrbot` reports AstrBot `4.27.5`.
- A non-secret projection of `C:\Users\25861\.astrbot\data\cmd_config.json` contains exactly one platform entry: type `qq_official`, enabled. Platform IDs, credentials, and other secret-bearing values were not copied into this document.
- `C:\Users\25861\.astrbot\data\plugins\astrbot_plugin_proactive_chat` reports v1.2.5. SHA-256 values for `main.py`, `metadata.yaml`, `core/message_sender.py`, and `core/session_config.py` all match the d120 probe constants.
- No AstrBot/Python/uvicorn backend process was observed, and `astrbot_plugin_translate_tts` was not present in the live plugin directory.

Consequently, the proactive-chat disk checkout is source-verified, but there is no loaded proactive instance to which that result can be attributed. Runtime adapter state, provider access, real model output, QQ delivery, and audio playback remain unverified.

## Runtime adaptation boundary

The plugin applies reversible runtime wrappers and never edits AstrBot or `astrbot_plugin_proactive_chat` files. The normal adapter patches two AstrBot class attributes. The proactive adapter patches two attributes on the actual registered proactive-chat instance and the synchronous getter on its Context class.

Scopes are bound to the current asyncio task, owner, source path, session identifier, configuration snapshot, and active patch generation. A provider proxy retained outside its matching scope transparently calls the original provider. Proactive `always_send_text` is changed only in a per-call copy whose nested `tts_settings` is copied separately.

Unload/reload restores an attribute only while it still points to this plugin's wrapper. Later third-party wrappers are preserved. A newer Translate TTS generation deactivates and unwraps an older generation to avoid stacked translation calls.

## Observable adapter states

`TranslateTTSPlugin.compatibility_statuses` exposes `normal` and `proactive` `CompatibilityStatus` values. Transitions are also logged under `Translate TTS normal compatibility` and `Translate TTS proactive compatibility`.

| State | Meaning | Operator action |
| --- | --- | --- |
| `signature_compatible_unverified` | Required signatures matched and wrappers are active. It does not authenticate source content or prove delivery. | Continue with a source probe and live acceptance if those assurances are required. |
| `not_installed` | Adapter/dependency was not found or is inactive. | For proactive chat, install/enable v1.2.5 and reload it; reload Translate TTS if no load event was observed. |
| `disabled` | Configuration disabled the adapter, or configuration was invalid. | Check `enabled`, `enable_proactive_compat`, custom language, and numeric ranges; save and reload. |
| `incompatible` | Registry access, signatures, version, or patch installation did not meet the guarded baseline. | Do not force the patch. Restore supported versions and collect the complete detail. |
| `closed` | Adapter was unloaded or explicitly closed. | Expected during disable/unload; reload for a new generation. |
| `superseded` | A newer Translate TTS generation replaced old wrappers. | Expected during overlapping reload; confirm the new generation is signature-compatible. |

The proactive status always has `baseline_commit_verified=false` at runtime. AstrBot plugin metadata exposes a version and instance, not a trustworthy Git commit or content fingerprint. A source probe result must not be automatically attributed to the loaded instance.

## Configuration compatibility checks

The authoritative defaults are in `_conf_schema.json`; the complete operator-facing table is in the [README configuration section](../README.md#configuration). Invalid values fail closed instead of partially installing adapters.

| Keys | Accepted runtime contract | Diagnostic effect |
| --- | --- | --- |
| `enabled`, `enable_proactive_compat` | Booleans; both default to `true` | The master switch disables both paths; the proactive switch disables only proactive compatibility. Save and reload after changing either value. |
| `translation_provider_id` | Provider ID string or empty | Empty asks AstrBot to resolve the current session provider. A non-empty unavailable ID falls back to original-text TTS without silently selecting another model. |
| `target_language`, `custom_target_language` | One predefined language code, or `custom` with a non-empty name | Unknown codes and an empty custom name mark configuration invalid. Only one target language is active per plugin configuration. |
| `translation_timeout_seconds` | Integer 1–120 | Covers both semaphore waiting and the LLM request. |
| `max_input_chars` | Integer 1–100000 | Longer source text bypasses translation intact. |
| `max_output_chars` | Integer 1–200000 | Longer model output is rejected and the complete source is used. |
| `max_concurrent_translations` | Integer 1–100 | Bounds translation calls for this plugin instance; a change takes effect after reload. |

## Read-only source and integration probes

### AstrBot 4.27.5

Run with AstrBot's embedded Python and a disposable writable runtime location:

```powershell
$env:ASTRBOT_ROOT = 'C:\path\to\AstrBot'
$env:ASTRBOT_PROBE_RUNTIME_ROOT = "$env:TEMP\translate-tts-probe"
C:\path\to\AstrBot\backend\python\python.exe tests\real_4_27_integration.py
```

The probe requires `astrbot.__version__ == "4.27.5"`, verifies fixed SHA-256 fingerprints for `ResultDecorateStage` and `Context`, checks the getter shape, and exercises the real decoration stage with a fake translator and fake TTS provider. It does not call a model, synthesize audio, upload media, or send QQ messages. Do not use a live data directory for `ASTRBOT_PROBE_RUNTIME_ROOT`.

### proactive-chat v1.2.5 reference source

```powershell
$env:PROACTIVE_CHAT_ROOT = 'C:\path\to\astrbot_plugin_proactive_chat'
python tests\real_proactive_d120_probe.py
```

This probe checks SHA-256 fingerprints for `core/message_sender.py`, `core/session_config.py`, `main.py`, and `metadata.yaml`, then checks the two required AST method signatures. It is read-only. A pass means only that the specified checkout matches the reference; it does not prove AstrBot loaded that directory or QQ received a message.

Remove the variables after probing if the same shell will start a live instance:

```powershell
Remove-Item Env:ASTRBOT_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:ASTRBOT_PROBE_RUNTIME_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:PROACTIVE_CHAT_ROOT -ErrorAction SilentlyContinue
```

## Automated test scope

From the package parent directory:

```powershell
python -m pytest translate_tts\tests
ruff check translate_tts
ruff format --check translate_tts
```

The suite covers configuration, exact history-free LLM request shape, provider selection, output rejection, timeout including semaphore wait, concurrency, cancellation, normal trigger/text restoration, duplicate source text, file-service URLs, synthesis fallback, cross-session isolation, proactive segmentation/text retention, load/reload/unload, incompatible APIs, and patch ownership.

Automated tests do not establish translation quality, spoken-language accuracy, provider permissions, QQ media upload, delivery, or playback.

## Required live acceptance (not yet run)

These checks require a disposable QQ test conversation, explicit user authorization, credentials, network access, configured real LLM/TTS providers, and the user's actual proactive-chat installation. Do not send a live message without explicit authorization.

1. Record AstrBot 4.27.5, QQ Official adapter type (including Webhook use), plugin versions/source, provider IDs, TTS model/voice, and target language without secrets.
2. In private chat, exercise a normal reply with upstream voice-only output and verify exactly one original-language text plus one playable Japanese audio message.
3. Repeat in an enabled test group and verify actual delivery/playback, not only internal return values.
4. Repeat normal and proactive paths with upstream text/dual output enabled; confirm original text appears exactly once.
5. Disable proactive TTS and confirm zero translation requests and unchanged original text behavior.
6. Select another language supported by the TTS model/voice and verify pronunciation.
7. Make the translation provider unavailable; confirm original-language audio plus text and no silent switch from an explicitly selected model.
8. Use a TTS voice that rejects translated text; confirm at most one original-text synthesis retry.
9. Disable/unload and reload Translate TTS; confirm pass-through while disabled and no duplicate translation/audio afterward.
10. Preserve redacted logs and record whether each message was delivered and playable. Internal “sent” flags are insufficient evidence.

Until both normal and proactive paths pass this checklist, the plugin is an implemented, simulated-tested candidate rather than a fully live-validated deployment.

## Privacy and failure diagnosis

TTS-selected text is disclosed to the translation LLM provider; the translation or fallback source is disclosed to the TTS provider. The translation request omits conversation history, images, audio, tools, and persona. The plugin does not persist translation content and does not intentionally log source/translated text. AstrBot, proactive-chat, LLM, and TTS logs may behave differently.

Fallback logs use `TTS translation fallback` with timeout, length, provider/generation, empty/refusal/tool output, or excessive-output reasons. Compatibility logs include state and detail. Collect error types and state, but redact credentials and user content before sharing logs.
