from __future__ import annotations

import unittest
from types import SimpleNamespace

from translate_tts.config import ConfigurationError, TranslationSettings
from translate_tts.emotion import TranslationResult
from translate_tts.fish_emotions import (
    FishSegment,
    normalize_fish_cues,
    normalize_fish_segments,
)
from translate_tts.tts_adapters import prepare_call, resolve_provider


class Provider:
    def __init__(self, provider_id: str, kind: str, model: str = ""):
        self.provider_config = {"id": provider_id, "type": kind}
        self.model_name = model
        self.headers = {"Authorization": "secret"}
        self.voice_setting = {"speed": 1, "emotion": "upstream"}
        self.prefix = "Existing style"
        self.model = model

    def meta(self):
        return SimpleNamespace(
            id=self.provider_config["id"], type=self.provider_config["type"]
        )

    def set_model(self, model: str):
        self.model_name = model

    async def get_audio(self, text: str):
        return text


class ProviderFishAudioTTSAPI(Provider):
    pass


class ProviderMiniMaxTTSAPI(Provider):
    pass


class ProviderGeminiTTSAPI(Provider):
    pass


class Context:
    def __init__(self, providers):
        self.providers = providers

    def get_provider_by_id(self, provider_id):
        return next(
            (p for p in self.providers if p.provider_config["id"] == provider_id),
            None,
        )

    def get_all_tts_providers(self):
        return self.providers


class SettingsTests(unittest.TestCase):
    def test_new_defaults_and_validation(self):
        settings = TranslationSettings.from_mapping({})
        self.assertTrue(settings.emotion_enabled)
        self.assertEqual(settings.tts_selection_mode, "prefer_fish")
        self.assertEqual(settings.fish_model, "s2.1-pro-free")
        with self.assertRaises(ConfigurationError):
            TranslationSettings.from_mapping({"fish_model": "paid-latest"})


class ProviderSelectionTests(unittest.TestCase):
    def test_explicit_provider_wins_and_must_be_real_tts_instance(self):
        upstream = Provider("upstream", "edge_tts")
        eleven = Provider("eleven", "elevenlabs_tts_api", "eleven_v3")
        context = Context([upstream, eleven])
        settings = TranslationSettings(tts_provider_id="eleven")
        self.assertIs(resolve_provider(context, upstream, settings).provider, eleven)

        context.providers = [upstream]
        resolution = resolve_provider(context, upstream, settings)
        self.assertFalse(resolution.translate)
        self.assertEqual(resolution.reason, "invalid_explicit_tts_provider")

    def test_prefer_fish_is_unambiguous_only(self):
        upstream = Provider("upstream", "edge_tts")
        fish = ProviderFishAudioTTSAPI("fish", "fishaudio_tts_api", "s2-pro")
        settings = TranslationSettings()
        self.assertIs(
            resolve_provider(Context([upstream, fish]), upstream, settings).provider,
            fish,
        )
        resolution = resolve_provider(
            Context(
                [
                    upstream,
                    fish,
                    ProviderFishAudioTTSAPI("fish2", "fishaudio_tts_api"),
                ]
            ),
            upstream,
            settings,
        )
        self.assertIs(resolution.provider, upstream)
        self.assertEqual(resolution.reason, "ambiguous_fish_selection")


class AdapterTests(unittest.TestCase):
    def result(self, emotion="happy", fish_cues=()):
        return TranslationResult("原文", "訳文", emotion, True, fish_cues)

    def test_fish_free_model_and_state_are_request_local(self):
        provider = ProviderFishAudioTTSAPI("fish", "fishaudio_tts_api", "s2-pro")
        resolution = resolve_provider(
            Context([provider]), provider, TranslationSettings()
        )
        prepared = prepare_call(resolution, self.result(), TranslationSettings())
        self.assertEqual(prepared.provider.headers["model"], "s2.1-pro-free")
        self.assertEqual(prepared.provider.model_name, "s2.1-pro-free")
        self.assertEqual(prepared.text, "[happy] 訳文")
        self.assertEqual(provider.headers, {"Authorization": "secret"})
        self.assertEqual(provider.model_name, "s2-pro")

    def test_unknown_fish_subclass_fails_closed_instead_of_using_shared_headers(self):
        provider = Provider("fish", "fishaudio_tts_api", "s2-pro")
        with self.assertRaises(TypeError):
            prepare_call(
                resolve_provider(Context([provider]), provider, TranslationSettings()),
                self.result(),
                TranslationSettings(),
            )

    def test_fish_s1_uses_parentheses(self):
        provider = ProviderFishAudioTTSAPI("fish", "fishaudio_tts_api")
        settings = TranslationSettings(fish_model="s1")
        prepared = prepare_call(
            resolve_provider(Context([provider]), provider, settings),
            self.result("fearful"),
            settings,
        )
        self.assertEqual(prepared.text, "(scared) 訳文")

    def test_fish_keeps_primary_emotion_when_physical_cues_fill_the_limit(self):
        provider = ProviderFishAudioTTSAPI("fish", "fishaudio_tts_api")
        settings = TranslationSettings(fish_model="s2.1-pro-free")
        prepared = prepare_call(
            resolve_provider(Context([provider]), provider, settings),
            self.result("sad", ("nostalgic", "whispering", "background laughter")),
            settings,
        )
        self.assertEqual(
            prepared.text,
            "[nostalgic][whispering][sad] 訳文",
        )

    def test_fish_s2_renders_specific_combined_voice_direction(self):
        provider = ProviderFishAudioTTSAPI("fish", "fishaudio_tts_api")
        settings = TranslationSettings()
        cues = normalize_fish_cues(["very angry, high voice,"], "s2.1-pro-free")
        prepared = prepare_call(
            resolve_provider(Context([provider]), provider, settings),
            TranslationResult("你是笨蛋吗？", "あんたバカァ？", "angry", True, cues),
            settings,
        )
        self.assertEqual(cues, ("very angry, high voice",))
        self.assertEqual(prepared.text, "[very angry, high voice] あんたバカァ？")

    def test_fish_segments_place_transitions_without_changing_translation(self):
        provider = ProviderFishAudioTTSAPI("fish", "fishaudio_tts_api")
        settings = TranslationSettings()
        result = TranslationResult(
            "原文",
            "嬉しい。でも少し不安。",
            "happy",
            True,
            (),
            (
                FishSegment("嬉しい。", ("happy",)),
                FishSegment("でも少し不安。", ("uncertain", "soft tone")),
            ),
        )
        prepared = prepare_call(
            resolve_provider(Context([provider]), provider, settings), result, settings
        )
        self.assertEqual(
            prepared.text,
            "[happy]嬉しい。[uncertain][soft tone]でも少し不安。",
        )

    def test_fish_segments_must_reproduce_plain_translation_exactly(self):
        self.assertEqual(
            normalize_fish_segments(
                [{"text": "changed", "cues": ["happy"]}],
                "original",
                "s2.1-pro-free",
            ),
            (),
        )

    def test_s2_segments_must_establish_the_initial_delivery(self):
        self.assertEqual(
            normalize_fish_segments(
                [
                    {"text": "最初。", "cues": []},
                    {"text": "次。", "cues": ["very angry, high voice"]},
                ],
                "最初。次。",
                "s2.1-pro-free",
            ),
            (),
        )

    def test_s1_normalization_rejects_unsupported_and_unknown_cues(self):
        self.assertEqual(
            normalize_fish_cues(
                ["Happy", "emphasis", "clear throat", "UNKNOWN", "sighing"],
                "s1",
            ),
            ("happy", "sighing"),
        )

    def test_s2_direction_validation_rejects_wrappers_and_overlong_text(self):
        self.assertEqual(
            normalize_fish_cues(
                [
                    "[angry]",
                    "very angry, high voice",
                    "x" * 97,
                    "very angry, high voice",
                ],
                "s2.1-pro-free",
            ),
            ("very angry, high voice",),
        )
        self.assertEqual(normalize_fish_cues(["very angry, high voice"], "s1"), ())

    def test_parallel_fish_call_snapshots_do_not_share_headers_or_emotion(self):
        provider = ProviderFishAudioTTSAPI("fish", "fishaudio_tts_api", "s2-pro")
        resolution = resolve_provider(
            Context([provider]), provider, TranslationSettings()
        )
        happy = prepare_call(resolution, self.result("happy"), TranslationSettings())
        sad = prepare_call(resolution, self.result("sad"), TranslationSettings())
        happy.provider.headers["call"] = "happy"
        self.assertEqual(happy.text, "[happy] 訳文")
        self.assertEqual(sad.text, "[sad] 訳文")
        self.assertNotIn("call", sad.provider.headers)
        self.assertNotIn("call", provider.headers)

    def test_eleven_v3_only(self):
        v3 = Provider("eleven", "elevenlabs_tts_api", "eleven_v3")
        prepared = prepare_call(
            resolve_provider(Context([v3]), v3, TranslationSettings()),
            self.result("sad"),
            TranslationSettings(),
        )
        self.assertEqual(prepared.text, "[sad] 訳文")
        v2 = Provider("v2", "elevenlabs_tts_api", "eleven_multilingual_v2")
        prepared = prepare_call(
            resolve_provider(Context([v2]), v2, TranslationSettings()),
            self.result("sad"),
            TranslationSettings(),
        )
        self.assertEqual((prepared.text, prepared.adapter), ("訳文", "plain"))

    def test_minimax_body_state_isolated(self):
        provider = ProviderMiniMaxTTSAPI("mini", "minimax_tts_api", "speech-2.6-hd")
        prepared = prepare_call(
            resolve_provider(Context([provider]), provider, TranslationSettings()),
            self.result("angry"),
            TranslationSettings(),
        )
        self.assertEqual(prepared.provider.voice_setting["emotion"], "angry")
        self.assertEqual(provider.voice_setting["emotion"], "upstream")

    def test_gemini_instruction_isolated_and_model_gated(self):
        provider = ProviderGeminiTTSAPI(
            "gemini", "gemini_tts", "gemini-2.5-flash-preview-tts"
        )
        prepared = prepare_call(
            resolve_provider(Context([provider]), provider, TranslationSettings()),
            self.result("calm"),
            TranslationSettings(),
        )
        self.assertIn("calm", prepared.provider.prefix)
        self.assertEqual(prepared.text, "Transcript: 訳文")
        self.assertEqual(provider.prefix, "Existing style")

    def test_emotion_off_still_selects_fish_free_without_marker(self):
        provider = ProviderFishAudioTTSAPI("fish", "fishaudio_tts_api", "s2-pro")
        settings = TranslationSettings(emotion_enabled=False)
        prepared = prepare_call(
            resolve_provider(Context([provider]), provider, settings),
            self.result(),
            settings,
            dynamic_emotion=False,
        )
        self.assertEqual(prepared.text, "訳文")
        self.assertEqual(prepared.provider.headers["model"], "s2.1-pro-free")
