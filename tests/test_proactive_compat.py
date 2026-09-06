from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from translate_tts.compat.proactive_chat import (
    BASELINE_COMMIT,
    PROACTIVE_PLUGIN_NAME,
    ProactiveChatAdapter,
)
from translate_tts.config import TranslationSettings
from translate_tts.scope import current_translation_scope


class Provider:
    def __init__(self):
        self.calls = []
        self.fail_translated = False
        self.block = None

    async def get_audio(self, text: str):
        self.calls.append(text)
        if self.block is not None:
            await self.block.wait()
        if self.fail_translated and text.startswith("訳:"):
            raise RuntimeError("translated voice unsupported")
        return f"audio:{text}"


class Context:
    def __init__(self, provider):
        self.provider = provider
        self.stars = []
        self.getter_calls = []

    def get_all_stars(self):
        return self.stars

    def get_using_tts_provider(self, umo=None):
        self.getter_calls.append(umo)
        return self.provider


class ProactivePlugin:
    def __init__(self, context, configs):
        self.context = context
        self.configs = configs
        self.sent = []
        self.observed_configs = []

    def _get_session_config(self, session_id):
        return self.configs.get(session_id)

    async def _send_proactive_message(self, session_id, text):
        config = self._get_session_config(session_id)
        self.observed_configs.append(config)
        if not config:
            return
        tts = config.get("tts_settings", {})
        segmented = config.get("segmented_reply_settings", {})
        is_tts_sent = False
        if tts.get("enable_tts", True):
            provider = self.context.get_using_tts_provider(umo=session_id)
            if provider:
                audio = await provider.get_audio(text)
                if audio:
                    self.sent.append((session_id, "record", audio))
                    is_tts_sent = True
        if not is_tts_sent or tts.get("always_send_text", True):
            texts = [text]
            if segmented.get("enable", False):
                texts = text.split("|")
            self.sent.extend((session_id, "plain", part) for part in texts)


class Translation:
    def __init__(self):
        self.calls = []

    async def translate_for_tts(self, text, scope):
        self.calls.append((text, scope.unified_msg_origin, scope.source))
        return "訳:" + text


class Logger:
    def __init__(self):
        self.entries = []

    def info(self, *args):
        self.entries.append(("info", args))

    def warning(self, *args):
        self.entries.append(("warning", args))


def metadata(instance, version="v1.2.5", *, activated=True):
    return SimpleNamespace(
        name=PROACTIVE_PLUGIN_NAME,
        version=version,
        activated=activated,
        star_cls=instance,
    )


class ProactiveCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = "qq_official:FriendMessage:1"
        self.provider = Provider()
        self.context = Context(self.provider)
        self.original_config = {
            "tts_settings": {"enable_tts": True, "always_send_text": False},
            "segmented_reply_settings": {"enable": False},
        }
        self.proactive = ProactivePlugin(
            self.context, {self.session: self.original_config}
        )
        self.translation = Translation()
        self.logger = Logger()
        self.owner = SimpleNamespace(
            context=self.context,
            settings=TranslationSettings(),
        )
        self.adapter = ProactiveChatAdapter(
            self.owner, self.translation, logger=self.logger
        )
        self.meta = metadata(self.proactive)
        self.context.stars = [self.meta]
        status = self.adapter.refresh_from_registry()
        self.assertEqual(status.state, "signature_compatible_unverified")
        self.assertFalse(status.baseline_commit_verified)

    async def asyncTearDown(self):
        self.adapter.close()

    async def test_forces_one_original_through_existing_send_chain(self):
        await self.proactive._send_proactive_message(self.session, "原文")
        self.assertEqual(self.provider.calls, ["訳:原文"])
        self.assertEqual(
            self.proactive.sent,
            [
                (self.session, "record", "audio:訳:原文"),
                (self.session, "plain", "原文"),
            ],
        )
        self.assertFalse(self.original_config["tts_settings"]["always_send_text"])
        observed = self.proactive.observed_configs[0]
        self.assertIsNot(observed, self.original_config)
        self.assertIsNot(observed["tts_settings"], self.original_config["tts_settings"])

    async def test_existing_always_text_and_segmentation_are_not_duplicated(self):
        self.original_config["tts_settings"]["always_send_text"] = True
        self.original_config["segmented_reply_settings"]["enable"] = True
        await self.proactive._send_proactive_message(self.session, "甲|乙")
        plain = [item for item in self.proactive.sent if item[1] == "plain"]
        self.assertEqual(
            plain,
            [(self.session, "plain", "甲"), (self.session, "plain", "乙")],
        )
        self.assertEqual(self.provider.calls, ["訳:甲|乙"])

    async def test_disabled_tts_never_translates_and_original_logic_sends_text(self):
        self.original_config["tts_settings"]["enable_tts"] = False
        await self.proactive._send_proactive_message(self.session, "仅文字")
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.translation.calls, [])
        self.assertEqual(self.proactive.sent, [(self.session, "plain", "仅文字")])

    async def test_translated_synthesis_failure_retries_original_once(self):
        self.provider.fail_translated = True
        await self.proactive._send_proactive_message(self.session, "原文")
        self.assertEqual(self.provider.calls, ["訳:原文", "原文"])
        self.assertEqual(len(self.translation.calls), 1)
        self.assertEqual(self.proactive.sent[-1], (self.session, "plain", "原文"))

    async def test_sync_getter_is_scope_and_session_bound(self):
        self.assertIs(self.context.get_using_tts_provider(self.session), self.provider)

        child_provider = None

        async def intercept_send(session_id, text):
            nonlocal child_provider

            async def child():
                return self.context.get_using_tts_provider(session_id)

            child_provider = await asyncio.create_task(child())
            wrong = self.context.get_using_tts_provider("another-session")
            self.assertIs(wrong, self.provider)

        original = self.proactive._send_proactive_message
        self.proactive._send_proactive_message = intercept_send
        self.adapter.close()
        self.adapter.install_metadata(self.meta)
        await self.proactive._send_proactive_message(self.session, "原文")
        self.assertIs(child_provider, self.provider)
        self.proactive._send_proactive_message = original

    async def test_two_sessions_are_isolated(self):
        second = "qq_official:FriendMessage:2"
        self.proactive.configs[second] = {
            "tts_settings": {"enable_tts": True, "always_send_text": False}
        }
        await asyncio.gather(
            self.proactive._send_proactive_message(self.session, "甲"),
            self.proactive._send_proactive_message(second, "乙"),
        )
        self.assertCountEqual(
            self.translation.calls,
            [
                ("甲", self.session, "proactive"),
                ("乙", second, "proactive"),
            ],
        )

    async def test_cancellation_deactivates_scope_without_original_fallback(self):
        self.provider.block = asyncio.Event()
        task = asyncio.create_task(
            self.proactive._send_proactive_message(self.session, "原文")
        )
        while not self.provider.calls:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.provider.calls, ["訳:原文"])
        self.assertIsNone(current_translation_scope.get())

    async def test_late_load_reload_and_unload_restore_instances(self):
        original_first = self.adapter.patches.records[0].original
        second = ProactivePlugin(self.context, {self.session: self.original_config})
        second_meta = metadata(second, version="1.2.5")
        self.adapter.handle_plugin_loaded(second_meta)
        self.assertNotIn("_send_proactive_message", self.proactive.__dict__)
        self.assertIs(
            self.proactive._send_proactive_message.__func__, original_first.__func__
        )
        await self.proactive._send_proactive_message(self.session, "旧实例")
        self.assertEqual(self.translation.calls, [])

        await second._send_proactive_message(self.session, "新实例")
        self.assertEqual(self.translation.calls[0][0], "新实例")
        self.adapter.handle_plugin_unloaded(self.meta)
        self.assertTrue(self.adapter.active)
        self.adapter.handle_plugin_unloaded(second_meta)
        self.assertFalse(self.adapter.active)
        self.assertEqual(self.adapter.status.state, "not_installed")
        self.assertNotIn("_send_proactive_message", second.__dict__)
        self.assertNotIn("_get_session_config", second.__dict__)

    async def test_incompatible_version_and_signature_are_diagnostic(self):
        status = self.adapter.install_metadata(metadata(self.proactive, "v1.2.4"))
        self.assertEqual(status.state, "incompatible")
        self.assertIn("v1.2.4", status.detail)
        self.assertFalse(self.adapter.active)

        class WrongSignature(ProactivePlugin):
            async def _send_proactive_message(self, text):
                pass

        wrong = WrongSignature(self.context, {})
        status = self.adapter.install_metadata(metadata(wrong))
        self.assertEqual(status.state, "incompatible")
        self.assertIn("signature mismatch", status.detail)
        self.assertEqual(len(BASELINE_COMMIT), 40)

    async def test_missing_or_inactive_registry_is_reported_separately(self):
        self.context.stars = []
        status = self.adapter.refresh_from_registry()
        self.assertEqual(status.state, "not_installed")
        self.context.stars = [metadata(self.proactive, activated=False)]
        status = self.adapter.refresh_from_registry()
        self.assertEqual(status.state, "not_installed")

    async def test_close_disable_registry_error_and_new_generation_are_observable(self):
        replacement = ProactiveChatAdapter(
            self.owner, self.translation, logger=self.logger
        )
        replacement.install_metadata(self.meta)
        self.assertEqual(self.adapter.status.state, "superseded")
        self.assertEqual(replacement.status.state, "signature_compatible_unverified")
        replacement.close()
        self.assertEqual(replacement.status.state, "closed")

        self.adapter.mark_disabled()
        self.assertEqual(self.adapter.status.state, "disabled")

        def broken_registry():
            raise RuntimeError("registry unavailable")

        self.context.get_all_stars = broken_registry
        status = self.adapter.refresh_from_registry()
        self.assertEqual(status.state, "incompatible")
        self.assertIn("registry", status.detail)


if __name__ == "__main__":
    unittest.main()
