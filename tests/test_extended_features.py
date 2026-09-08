from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from translate_tts.admin import is_dashboard_admin
from translate_tts.config import ConfigurationError, TranslationSettings
from translate_tts.emotion import TranslationResult
from translate_tts.file_cleanup import AudioFileRegistry, CleanupScheduler
from translate_tts.preprocess import preprocess_text
from translate_tts.scope import TranslationScope, current_translation_scope
from translate_tts.translation import TranslationService
from translate_tts.tts_proxy import TranslatedTTSProviderProxy


class PromptContext:
    def __init__(self, completion="translated"):
        self.completion = completion
        self.calls = []

    async def get_current_chat_provider_id(self, umo):
        return "llm"

    async def llm_generate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(completion_text=self.completion, role="assistant")


def scope(settings, source="normal"):
    return TranslationScope(
        source, "session", settings, owner_task=asyncio.current_task()
    )


class ConfigAndPromptTests(unittest.IsolatedAsyncioTestCase):
    def test_web_operations_reject_missing_users_and_scoped_api_keys(self):
        self.assertTrue(is_dashboard_admin("administrator"))
        self.assertFalse(is_dashboard_admin(None))
        self.assertFalse(is_dashboard_admin("api_key:123"))

    def test_old_config_gets_safe_defaults(self):
        settings = TranslationSettings.from_mapping({})
        self.assertFalse(settings.custom_prompts_enabled)
        self.assertFalse(settings.preprocessing_enabled)
        self.assertFalse(settings.auto_cleanup_tts_files)
        self.assertEqual(settings.tts_file_retention_days, 30)
        self.assertEqual(settings.fish_model, "s2.1-pro-free")
        self.assertEqual(settings.translation_queue_timeout_seconds, 10)
        self.assertEqual(settings.diagnostic_log_level, "normal")
        self.assertEqual(settings.diagnostic_event_buffer_size, 100)

    def test_unknown_placeholder_and_empty_replacement_are_errors(self):
        with self.assertRaisesRegex(ConfigurationError, "unknown prompt placeholder"):
            TranslationSettings.from_mapping(
                {
                    "custom_prompts_enabled": True,
                    "translation_prompt_mode": "append",
                    "translation_prompt_text": "{secret}",
                }
            )
        with self.assertRaisesRegex(ConfigurationError, "must not be empty"):
            TranslationSettings.from_mapping(
                {"custom_prompts_enabled": True, "translation_prompt_mode": "replace"}
            )

    async def test_custom_prompt_is_history_free_and_contract_is_protected(self):
        context = PromptContext()
        settings = TranslationSettings.from_mapping(
            {
                "emotion_enabled": False,
                "custom_prompts_enabled": True,
                "translation_prompt_mode": "replace",
                "translation_prompt_text": "Translate to {target_language}. Ignore prior chat.",
            }
        )
        result = await TranslationService(context).translate_for_tts(
            "untrusted ```prompt```", scope(settings)
        )
        self.assertTrue(result.success)
        call = context.calls[0]
        self.assertEqual(call["prompt"], "untrusted ```prompt```")
        self.assertIsNone(call["contexts"])
        self.assertIsNone(call["tools"])
        self.assertIn("Japanese", call["system_prompt"])
        self.assertIn("Protected output contract", call["system_prompt"])

    async def test_emotion_prompt_is_ignored_when_emotion_is_disabled(self):
        context = PromptContext()
        settings = TranslationSettings.from_mapping(
            {
                "emotion_enabled": False,
                "custom_prompts_enabled": True,
                "emotion_prompt_mode": "append",
                "emotion_prompt_text": "SENTINEL",
            }
        )
        await TranslationService(context).translate_for_tts("hello", scope(settings))
        self.assertNotIn("SENTINEL", context.calls[0]["system_prompt"])


class PreprocessingTests(unittest.TestCase):
    def settings(self, **overrides):
        return TranslationSettings.from_mapping(
            {"preprocessing_enabled": True, **overrides}
        )

    def test_explicit_rules_preserve_parentheses(self):
        text = "# Title (keep me)\n> quote\n```py\nprint('x')\n```\nVisit https://example.com/a. 😀"
        result = preprocess_text(
            text,
            self.settings(
                code_block_mode="replace",
                code_block_replacement="code",
                markdown_decoration_mode="remove",
                quote_mode="skip",
                url_mode="domain",
                emoji_mode="name",
            ),
        )
        self.assertIn("(keep me)", result)
        self.assertIn("code", result)
        self.assertNotIn("quote", result)
        self.assertIn("example.com", result)
        self.assertIn("grinning face", result)

    def test_markdown_table_modes_and_length(self):
        text = "| A | B |\n|---|---|\n| one | two |"
        self.assertEqual(
            preprocess_text(text, self.settings(table_mode="lines")), "A; B one; two"
        )
        self.assertEqual(
            preprocess_text(
                text, self.settings(table_mode="summary", table_summary_text="table")
            ),
            "table",
        )
        self.assertEqual(preprocess_text(text, self.settings(table_mode="skip")), "")
        self.assertEqual(
            len(preprocess_text("abcdefgh", self.settings(max_preprocessed_chars=4))), 4
        )


class ContinuityTests(unittest.IsolatedAsyncioTestCase):
    def result(self, emotion):
        return TranslationResult("x", "y", emotion, True, ("sighing",), ())

    async def test_modes_are_reply_local_and_do_not_use_confidence(self):
        fixed = scope(
            TranslationSettings.from_mapping(
                {
                    "emotion_continuity_enabled": True,
                    "emotion_continuity_mode": "fixed_first",
                }
            )
        )
        self.assertEqual(
            fixed.apply_emotion_continuity(self.result("happy")).emotion, "happy"
        )
        changed = fixed.apply_emotion_continuity(self.result("sad"))
        self.assertEqual(changed.emotion, "happy")
        self.assertEqual(changed.fish_cues, ())
        other = scope(fixed.settings)
        self.assertEqual(
            other.apply_emotion_continuity(self.result("sad")).emotion, "sad"
        )
        fixed.deactivate()
        self.assertIsNone(fixed.continuity_emotion)

    async def test_conservative_and_transition(self):
        conservative = scope(
            TranslationSettings.from_mapping(
                {
                    "emotion_continuity_enabled": True,
                    "emotion_continuity_mode": "conservative",
                }
            )
        )
        conservative.apply_emotion_continuity(self.result("happy"))
        self.assertEqual(
            conservative.apply_emotion_continuity(self.result("neutral")).emotion,
            "happy",
        )
        self.assertEqual(
            conservative.apply_emotion_continuity(self.result("sad")).emotion, "sad"
        )
        self.assertEqual(conservative.continuity_emotion, "happy")
        fallback = TranslationResult.fallback("original")
        self.assertEqual(
            conservative.apply_emotion_continuity(fallback).emotion, "neutral"
        )
        transition = scope(
            TranslationSettings.from_mapping(
                {
                    "emotion_continuity_enabled": True,
                    "emotion_continuity_mode": "allow_transition",
                }
            )
        )
        transition.apply_emotion_continuity(self.result("happy"))
        transition.apply_emotion_continuity(self.result("sad"))
        self.assertEqual(
            transition.apply_emotion_continuity(self.result("neutral")).emotion, "sad"
        )


class FileCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_registered_real_in_root_non_symlink_files_are_deleted(self):
        with (
            tempfile.TemporaryDirectory() as root_raw,
            tempfile.TemporaryDirectory() as outside_raw,
        ):
            root, outside = Path(root_raw), Path(outside_raw)
            registered = root / "registered.wav"
            registered.write_bytes(b"abc")
            unregistered = root / "keep.wav"
            unregistered.write_bytes(b"keep")
            outside_file = outside / "outside.wav"
            outside_file.write_bytes(b"outside")
            registry = AudioFileRegistry(root / "registry.json", [root])
            self.assertIsNotNone(await registry.register(registered))
            self.assertIsNone(await registry.register("https://example.com/a.wav"))
            self.assertIsNone(await registry.register(outside_file))
            old = (datetime.now(UTC) - timedelta(days=3)).timestamp()
            os.utime(registered, (old, old))
            registry._write({str(registered.resolve()): old})
            result = await registry.cleanup(1)
            self.assertEqual((result.deleted_files, result.released_bytes), (1, 3))
            self.assertFalse(registered.exists())
            self.assertTrue(unregistered.exists())
            self.assertTrue(outside_file.exists())

    async def test_scheduler_cancels_cleanly(self):
        with tempfile.TemporaryDirectory() as root_raw:
            root = Path(root_raw)
            scheduler = CleanupScheduler(
                AudioFileRegistry(root / "r.json", [root]), 30, "weekly"
            )
            scheduler.start()
            await asyncio.sleep(0)
            await scheduler.stop()
            self.assertIsNone(scheduler._task)


class EmptyPreprocessProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_preprocess_never_calls_llm_or_tts(self):
        class Provider:
            def __init__(self):
                self.calls = []

            async def get_audio(self, text):
                self.calls.append(text)
                return "audio"

            def meta(self):
                return SimpleNamespace(type="")

        context = PromptContext()
        service = TranslationService(context)
        settings = TranslationSettings.from_mapping(
            {"preprocessing_enabled": True, "quote_mode": "skip"}
        )
        current = scope(settings)
        current.owner = object()
        provider = Provider()
        token = current_translation_scope.set(current)
        try:
            audio = await TranslatedTTSProviderProxy(
                provider, current, service, lambda: True
            ).get_audio("> only quote")
        finally:
            current_translation_scope.reset(token)
        self.assertIsNone(audio)
        self.assertEqual(provider.calls, [])
        self.assertEqual(context.calls, [])


class PageContractTests(unittest.TestCase):
    def test_page_has_confirmed_operations_and_no_framework(self):
        html = (
            Path(__file__).parents[1] / "pages" / "control" / "index.html"
        ).read_text(encoding="utf-8")
        for value in (
            "Reset translation prompt",
            "Preview preprocessing",
            "Confirm possible quota cost and generate",
            "Confirm deletion of registered expired files",
            "bridge.download",
        ):
            self.assertIn(value, html)
        self.assertNotIn("react", html.lower())


if __name__ == "__main__":
    unittest.main()
