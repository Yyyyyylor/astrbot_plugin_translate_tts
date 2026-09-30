"""Offline contract tests for private_companion 6.6.2's send and TTS calls."""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from translate_tts.compat.private_companion import (
    PLUGIN_NAME,
    PrivateCompanionAdapter,
)
from translate_tts.config import TranslationSettings
from translate_tts.scope import current_translation_scope


class Provider:
    def __init__(self):
        self.calls = []
        self.fail_translation = False

    async def get_audio(self, text: str):
        self.calls.append(text)
        if self.fail_translation and text.startswith("訳:"):
            raise RuntimeError("translated voice failed")
        return f"audio:{text}"


class Context:
    def __init__(self):
        self.stars = []
        self.sent = []

    def get_all_stars(self):
        return self.stars

    async def send_message(self, umo, chain):
        self.sent.append((umo, chain))
        return True


class Companion:
    """Follow the upstream 6.6.2 boundary: decorate, synthesize, send."""

    def __init__(self, context, provider):
        self.context = context
        self.provider = provider
        self.enable_tts = True

    async def _tts_generate_audio_path(self, tts_provider, text):
        return str(await tts_provider.get_audio(text) or "")

    async def _trigger_proactive_decorating_hooks(self, umo, chain):
        if not self.enable_tts:
            return chain
        audio = await self._tts_generate_audio_path(self.provider, chain[0])
        return [*chain, audio] if audio else chain

    async def _send_chain_components(self, umo, chain, *, apply_decorating_hooks=True):
        processed = (
            await self._trigger_proactive_decorating_hooks(umo, chain)
            if apply_decorating_hooks
            else chain
        )
        return await self.context.send_message(umo, processed)

    async def _create_voice_record_component(
        self, target, spoken_text, *, defer_local_playback=False
    ):
        audio = await self._tts_generate_audio_path(self.provider, spoken_text)
        return [audio] if audio else []


class Translation:
    def __init__(self):
        self.calls = []

    async def translate_for_tts(self, text, scope):
        self.calls.append((text, scope.unified_msg_origin, scope.source))
        return "訳:" + text


class Logger:
    def info(self, *_args):
        pass

    def warning(self, *_args):
        pass


def metadata(instance, version="6.6.2"):
    return SimpleNamespace(
        name=PLUGIN_NAME, version=version, activated=True, star_cls=instance
    )


class PrivateCompanionCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.umo = "aiocqhttp:FriendMessage:123"
        self.context = Context()
        self.provider = Provider()
        self.companion = Companion(self.context, self.provider)
        self.translation = Translation()
        self.owner = SimpleNamespace(
            context=self.context, settings=TranslationSettings()
        )
        self.adapter = PrivateCompanionAdapter(
            self.owner, self.translation, logger=Logger()
        )
        self.meta = metadata(self.companion)
        self.context.stars.append(self.meta)
        self.assertEqual(
            self.adapter.refresh_from_registry().state,
            "signature_compatible_unverified",
        )

    async def asyncTearDown(self):
        self.adapter.close()

    async def test_existing_decorating_and_delivery_preserve_original_text(self):
        await self.companion._send_chain_components(self.umo, ["原文"])
        self.assertEqual(self.context.sent, [(self.umo, ["原文", "audio:訳:原文"])])
        self.assertEqual(self.provider.calls, ["訳:原文"])
        self.assertEqual(self.translation.calls, [("原文", self.umo, "proactive")])
        self.assertIsNone(current_translation_scope.get())

    async def test_no_upstream_tts_never_translates(self):
        self.companion.enable_tts = False
        await self.companion._send_chain_components(self.umo, ["仅文字"])
        self.assertEqual(self.translation.calls, [])
        self.assertEqual(self.provider.calls, [])

    async def test_existing_config_switch_passes_through(self):
        self.owner.settings = TranslationSettings(enable_proactive_compat=False)
        await self.companion._send_chain_components(self.umo, ["原文"])
        self.assertEqual(self.translation.calls, [])
        self.assertEqual(self.context.sent, [(self.umo, ["原文", "audio:原文"])])

    async def test_explicit_voice_path_uses_same_scope_and_fallback(self):
        self.provider.fail_translation = True
        result = await self.companion._create_voice_record_component(self.umo, "原文")
        self.assertEqual(result, ["audio:原文"])
        self.assertEqual(self.provider.calls, ["訳:原文", "原文"])
        self.assertEqual(len(self.translation.calls), 1)

    async def test_session_isolation_and_outside_calls(self):
        await asyncio.gather(
            self.companion._send_chain_components(self.umo, ["甲"]),
            self.companion._send_chain_components(
                "aiocqhttp:FriendMessage:456", ["乙"]
            ),
        )
        self.assertCountEqual(
            self.translation.calls,
            [
                ("甲", self.umo, "proactive"),
                ("乙", "aiocqhttp:FriendMessage:456", "proactive"),
            ],
        )
        self.assertEqual(
            await self.companion._tts_generate_audio_path(self.provider, "被动"),
            "audio:被动",
        )
        self.assertEqual(len(self.translation.calls), 2)

    async def test_version_disable_and_unload_restore_original_methods(self):
        self.adapter.install_metadata(metadata(self.companion, "6.6.1"))
        self.assertEqual(self.adapter.status.state, "incompatible")
        await self.companion._send_chain_components(self.umo, ["原文"])
        self.assertEqual(self.translation.calls, [])
        self.adapter.install_metadata(self.meta)
        self.adapter.handle_plugin_unloaded(self.meta)
        self.assertEqual(self.adapter.status.state, "not_installed")
        self.assertNotIn("_send_chain_components", self.companion.__dict__)
        self.assertNotIn("_tts_generate_audio_path", self.companion.__dict__)


if __name__ == "__main__":
    unittest.main()
