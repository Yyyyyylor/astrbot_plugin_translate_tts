from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N_ROOT = ROOT / ".astrbot-plugin" / "i18n"


class PluginI18nTests(unittest.TestCase):
    def load_locale(self, locale: str) -> dict:
        with (I18N_ROOT / f"{locale}.json").open(encoding="utf-8") as file:
            return json.load(file)

    def test_english_and_simplified_chinese_resources_are_complete(self):
        for locale in ("en-US", "zh-CN"):
            with self.subTest(locale=locale):
                resource = self.load_locale(locale)
                self.assertEqual(set(resource), {"metadata", "config", "pages"})
                with (ROOT / "_conf_schema.json").open(encoding="utf-8") as file:
                    schema = json.load(file)
                self.assertEqual(set(resource["config"]), set(schema))
                self.assertTrue(resource["metadata"]["display_name"].strip())

    def test_target_language_labels_match_saved_options(self):
        with (ROOT / "_conf_schema.json").open(encoding="utf-8") as file:
            schema = json.load(file)
        option_count = len(schema["target_language"]["options"])

        for locale in ("en-US", "zh-CN"):
            with self.subTest(locale=locale):
                labels = self.load_locale(locale)["config"]["target_language"]["labels"]
                self.assertEqual(len(labels), option_count)

    def test_control_page_and_prompt_guidance_are_bilingual(self):
        english = self.load_locale("en-US")
        chinese = self.load_locale("zh-CN")
        self.assertEqual(
            set(english["pages"]["control"]),
            set(chinese["pages"]["control"]),
        )
        required = {
            "title",
            "intro",
            "prompts_title",
            "translation_guide",
            "emotion_guide",
            "preview_title",
            "cleanup_title",
            "provider_type",
            "last_cleanup",
            "preview_warning",
            "diagnostics_title",
            "diagnostics_refresh",
        }
        self.assertTrue(required.issubset(english["pages"]["control"]))
        with (ROOT / "_conf_schema.json").open(encoding="utf-8") as file:
            schema = json.load(file)
        for key in ("translation_prompt_text", "emotion_prompt_text"):
            self.assertTrue(schema[key]["obvious_hint"])
            for placeholder in (
                "{target_language}",
                "{emotion_options}",
                "{fish_cues}",
            ):
                self.assertIn(placeholder, english["config"][key]["hint"])
                self.assertIn(placeholder, chinese["config"][key]["hint"])

        for field in (
            "tts_selection_mode",
            "fish_model",
            "translation_prompt_mode",
            "emotion_prompt_mode",
            "cleanup_check_period",
            "code_block_mode",
            "markdown_decoration_mode",
            "url_mode",
            "emoji_mode",
            "table_mode",
            "quote_mode",
            "emotion_continuity_mode",
            "preview_emotion",
            "diagnostic_log_level",
        ):
            option_count = len(schema[field]["options"])
            for locale in ("en-US", "zh-CN"):
                labels = self.load_locale(locale)["config"][field]["labels"]
                self.assertEqual(len(labels), option_count)


if __name__ == "__main__":
    unittest.main()
