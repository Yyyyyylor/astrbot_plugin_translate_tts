from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from translate_tts.config import ConfigurationError, TranslationSettings
from translate_tts.scope import TranslationScope
from translate_tts.translation import TranslationService


class FakeContext:
    def __init__(self, response=None):
        self.response = response or SimpleNamespace(
            role="assistant", completion_text="こんにちは"
        )
        self.current_provider_id = "session-provider"
        self.resolve_calls = []
        self.generate_calls = []
        self.generate_hook = None

    async def get_current_chat_provider_id(self, umo: str) -> str:
        self.resolve_calls.append(umo)
        return self.current_provider_id

    async def llm_generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        if self.generate_hook:
            return await self.generate_hook()
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def make_scope(**overrides) -> TranslationScope:
    overrides.setdefault("emotion_enabled", False)
    settings = TranslationSettings.from_mapping(overrides)
    return TranslationScope("normal", "qq_official:FriendMessage:42", settings)


class SettingsTests(unittest.TestCase):
    def test_japanese_is_default(self):
        settings = TranslationSettings.from_mapping({})
        self.assertEqual(settings.target_language_name(), "Japanese")

    def test_custom_language_is_supported(self):
        settings = TranslationSettings.from_mapping(
            {"target_language": "custom", "custom_target_language": "Esperanto"}
        )
        self.assertEqual(settings.target_language_name(), "Esperanto")

    def test_empty_custom_language_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            TranslationSettings.from_mapping({"target_language": "custom"})

    def test_unknown_language_is_rejected_during_mapping(self):
        with self.assertRaises(ConfigurationError):
            TranslationSettings.from_mapping({"target_language": "klingon"})


class TranslationTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_provider_resolves_current_session_and_exact_llm_shape(self):
        context = FakeContext()
        result = await TranslationService(context).translate_for_tts(
            "你好", make_scope()
        )
        self.assertEqual(result.text, "こんにちは")
        self.assertTrue(result.success)
        self.assertEqual(context.resolve_calls, ["qq_official:FriendMessage:42"])
        self.assertEqual(
            context.generate_calls[0],
            {
                "chat_provider_id": "session-provider",
                "prompt": "你好",
                "image_urls": None,
                "audio_urls": None,
                "tools": None,
                "system_prompt": context.generate_calls[0]["system_prompt"],
                "contexts": None,
            },
        )
        self.assertIn("Japanese", context.generate_calls[0]["system_prompt"])

    async def test_explicit_provider_does_not_silently_resolve_another(self):
        context = FakeContext(RuntimeError("provider not found"))
        result = await TranslationService(context).translate_for_tts(
            "原文", make_scope(translation_provider_id="removed-provider")
        )
        self.assertEqual(result.text, "原文")
        self.assertFalse(result.success)
        self.assertEqual(context.resolve_calls, [])
        self.assertEqual(
            context.generate_calls[0]["chat_provider_id"], "removed-provider"
        )

    async def test_empty_tool_and_excessive_outputs_fall_back(self):
        invalid_responses = (
            SimpleNamespace(role="assistant", completion_text="  "),
            SimpleNamespace(
                role="tool",
                completion_text="ignored",
                tools_call_name=["some_tool"],
            ),
            SimpleNamespace(role="assistant", completion_text="123456"),
        )
        for response in invalid_responses:
            with self.subTest(response=response):
                context = FakeContext(response)
                result = await TranslationService(context).translate_for_tts(
                    "source", make_scope(max_output_chars=5)
                )
                self.assertEqual(result.text, "source")
                self.assertFalse(result.success)

    async def test_refusal_metadata_falls_back(self):
        message = SimpleNamespace(refusal="cannot translate")
        raw = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        context = FakeContext(
            SimpleNamespace(
                role="assistant", completion_text="cannot translate", raw_completion=raw
            )
        )
        result = await TranslationService(context).translate_for_tts(
            "原文", make_scope()
        )
        self.assertEqual(result.text, "原文")

    async def test_whole_response_plain_text_refusals_fall_back(self):
        refusals = (
            "I'm sorry, but I can't assist with that request.",
            "抱歉，我无法帮助完成这项请求。",
            "申し訳ありませんが、そのリクエストには対応できません。",
        )
        for refusal in refusals:
            with self.subTest(refusal=refusal):
                context = FakeContext(
                    SimpleNamespace(role="assistant", completion_text=refusal)
                )
                result = await TranslationService(context).translate_for_tts(
                    "原文", make_scope()
                )
                self.assertEqual(result.text, "原文")

    async def test_normal_text_containing_refusal_words_is_not_rejected(self):
        translations = (
            "I can't believe how beautiful the night sky is.",
            "抱歉让你久等了，我们现在就出发。",
            "申し訳ありませんが、明日は休みます。",
        )
        for translation in translations:
            with self.subTest(translation=translation):
                context = FakeContext(
                    SimpleNamespace(role="assistant", completion_text=translation)
                )
                result = await TranslationService(context).translate_for_tts(
                    "source", make_scope()
                )
                self.assertEqual(result.text, translation)

    async def test_oversized_input_is_not_truncated_or_sent(self):
        context = FakeContext()
        result = await TranslationService(context).translate_for_tts(
            "abcdef", make_scope(max_input_chars=5)
        )
        self.assertEqual(result.text, "abcdef")
        self.assertEqual(context.generate_calls, [])

    async def test_timeout_includes_waiting_for_concurrency_slot(self):
        context = FakeContext()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocked_response():
            entered.set()
            await release.wait()
            return SimpleNamespace(role="assistant", completion_text="translated")

        context.generate_hook = blocked_response
        service = TranslationService(context, max_concurrency=1)
        long_scope = make_scope(translation_timeout_seconds=2)
        waiting_scope = make_scope(translation_timeout_seconds=1)
        first = asyncio.create_task(service.translate_for_tts("first", long_scope))
        await entered.wait()
        result = await service.translate_for_tts("second", waiting_scope)
        self.assertEqual(result.text, "second")
        self.assertEqual(len(context.generate_calls), 1)
        release.set()
        self.assertEqual((await first).text, "translated")

    async def test_concurrency_never_exceeds_limit(self):
        context = FakeContext()
        active = 0
        peak = 0

        async def measured_response():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            return SimpleNamespace(role="assistant", completion_text="ok")

        context.generate_hook = measured_response
        service = TranslationService(context, max_concurrency=2)
        results = await asyncio.gather(
            *(service.translate_for_tts(str(index), make_scope()) for index in range(6))
        )
        self.assertEqual([result.text for result in results], ["ok"] * 6)
        self.assertEqual(peak, 2)

    async def test_cancelled_error_propagates(self):
        context = FakeContext()

        async def cancelled_response():
            raise asyncio.CancelledError

        context.generate_hook = cancelled_response
        with self.assertRaises(asyncio.CancelledError):
            await TranslationService(context).translate_for_tts("原文", make_scope())

    async def test_structured_translation_uses_one_call_and_validates_emotion(self):
        context = FakeContext(
            SimpleNamespace(
                role="assistant",
                completion_text='{"text":"やっと会えたね！","emotion":"happy"}',
            )
        )
        result = await TranslationService(context).translate_for_tts(
            "终于见到你了！", make_scope(emotion_enabled=True)
        )
        self.assertEqual(result.text, "やっと会えたね！")
        self.assertEqual(result.emotion, "happy")
        self.assertTrue(result.success)
        self.assertEqual(len(context.generate_calls), 1)

    async def test_unknown_emotion_fails_closed_to_original(self):
        context = FakeContext(
            SimpleNamespace(
                role="assistant",
                completion_text='{"text":"こんにちは","emotion":"melancholy"}',
            )
        )
        result = await TranslationService(context).translate_for_tts(
            "你好", make_scope(emotion_enabled=True)
        )
        self.assertEqual(
            (result.text, result.emotion, result.success),
            ("你好", "neutral", False),
        )

    async def test_bad_structured_output_never_reads_json_aloud(self):
        context = FakeContext(
            SimpleNamespace(role="assistant", completion_text="```json {} ```")
        )
        result = await TranslationService(context).translate_for_tts(
            "原文", make_scope(emotion_enabled=True)
        )
        self.assertEqual(result.text, "原文")
        self.assertFalse(result.success)

    async def test_fish_structured_output_accepts_full_documented_cues(self):
        context = FakeContext(
            SimpleNamespace(
                role="assistant",
                completion_text=(
                    '{"text":"静かに聞いて。","emotion":"calm",'
                    '"fish_cues":["nostalgic","whispering","sighing","angry"],'
                    '"fish_segments":[]}'
                ),
            )
        )
        scope = make_scope(emotion_enabled=True)
        scope.selected_provider_type = "fishaudio_tts_api"
        scope.selected_fish_model = "s2.1-pro-free"
        result = await TranslationService(context).translate_for_tts("静静听。", scope)
        self.assertEqual(
            result.fish_cues,
            ("nostalgic", "whispering", "sighing"),
        )
        prompt = context.generate_calls[0]["system_prompt"]
        self.assertIn("background laughter", prompt)
        self.assertIn("zero to three", prompt)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_plugin_imports_and_terminates_with_astrbot_api_contract(self):
        astrbot = types.ModuleType("astrbot")
        api = types.ModuleType("astrbot.api")
        event = types.ModuleType("astrbot.api.event")
        star = types.ModuleType("astrbot.api.star")

        class AstrBotConfig(dict):
            pass

        class Star:
            def __init__(self, context):
                self.context = context

        api.AstrBotConfig = AstrBotConfig
        config_errors = []
        api.logger = SimpleNamespace(error=lambda *args: config_errors.append(args))
        event.filter = SimpleNamespace(
            on_plugin_loaded=lambda: lambda function: function,
            on_plugin_unloaded=lambda: lambda function: function,
        )
        star.Context = object
        star.Star = Star
        saved = {
            name: sys.modules.get(name)
            for name in (
                "astrbot",
                "astrbot.api",
                "astrbot.api.event",
                "astrbot.api.star",
            )
        }
        try:
            sys.modules.update(
                {
                    "astrbot": astrbot,
                    "astrbot.api": api,
                    "astrbot.api.event": event,
                    "astrbot.api.star": star,
                }
            )
            module = importlib.import_module("translate_tts.main")
            plugin = module.TranslateTTSPlugin(FakeContext(), AstrBotConfig())
            self.assertTrue(plugin.translation_service._active)
            confirmation = plugin._issue_confirmation("admin", {"operation": "preview"})
            self.assertEqual(
                plugin._consume_confirmation(confirmation, "admin")["operation"],
                "preview",
            )
            with self.assertRaises(PermissionError):
                plugin._consume_confirmation(confirmation, "admin")
            await plugin.terminate()
            self.assertFalse(plugin.translation_service._active)

            invalid_plugin = module.TranslateTTSPlugin(
                FakeContext(),
                AstrBotConfig(target_language="custom"),
            )
            self.assertFalse(invalid_plugin.settings.enabled)
            self.assertFalse(invalid_plugin.translation_service._active)
            configuration_errors = [
                args for args in config_errors if "configuration is invalid" in args[0]
            ]
            self.assertEqual(len(configuration_errors), 1)
        finally:
            sys.modules.pop("translate_tts.main", None)
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
