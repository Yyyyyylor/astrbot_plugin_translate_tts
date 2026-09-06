from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N_ROOT = ROOT / ".astrbot-plugin" / "i18n"
CONFIG_FIELDS = {
    "enabled",
    "translation_provider_id",
    "target_language",
    "custom_target_language",
    "translation_timeout_seconds",
    "max_input_chars",
    "max_output_chars",
    "max_concurrent_translations",
    "enable_proactive_compat",
}


class PluginI18nTests(unittest.TestCase):
    def load_locale(self, locale: str) -> dict:
        with (I18N_ROOT / f"{locale}.json").open(encoding="utf-8") as file:
            return json.load(file)

    def test_english_and_simplified_chinese_resources_are_complete(self):
        for locale in ("en-US", "zh-CN"):
            with self.subTest(locale=locale):
                resource = self.load_locale(locale)
                self.assertEqual(set(resource), {"metadata", "config"})
                self.assertEqual(set(resource["config"]), CONFIG_FIELDS)
                self.assertTrue(resource["metadata"]["display_name"].strip())

    def test_target_language_labels_match_saved_options(self):
        with (ROOT / "_conf_schema.json").open(encoding="utf-8") as file:
            schema = json.load(file)
        option_count = len(schema["target_language"]["options"])

        for locale in ("en-US", "zh-CN"):
            with self.subTest(locale=locale):
                labels = self.load_locale(locale)["config"]["target_language"]["labels"]
                self.assertEqual(len(labels), option_count)


if __name__ == "__main__":
    unittest.main()
