"""Targeted integration probe against pinned AstrBot 4.27.5/4.28.1/4.28.2 sources.

Run with AstrBot dependencies and ``ASTRBOT_ROOT`` pointing at its source.
Runtime data is redirected to a disposable directory before importing AstrBot.
This file is deliberately outside pytest's default pattern.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

PLUGIN_PARENT = Path(__file__).resolve().parents[2]


def _find_astrbot_app() -> Path:
    """Accept an AstrBot repository/app path, then try nearby checkouts."""
    candidates: list[Path] = []
    configured = os.environ.get("ASTRBOT_ROOT")
    if configured:
        root = Path(configured).expanduser().resolve()
        candidates.extend((root, root / "backend" / "app"))
    search_roots = (Path.cwd().resolve(), *Path(__file__).resolve().parents)
    for root in search_roots:
        candidates.extend(
            (
                root / "backend" / "app",
                root / "AstrBot" / "backend" / "app",
            )
        )
    for candidate in candidates:
        if (candidate / "astrbot" / "core" / "star" / "context.py").is_file():
            return candidate
    raise RuntimeError(
        "AstrBot source was not found; set ASTRBOT_ROOT to its repository "
        "root or backend/app directory"
    )


ASTRBOT_APP = _find_astrbot_app()
# Importing AstrBot initializes its database.  Keep that probe state away from
# both the plugin checkout and the user's live AstrBot data directory.
PROBE_RUNTIME_ROOT = Path(
    os.environ.get("ASTRBOT_PROBE_RUNTIME_ROOT")
    or tempfile.mkdtemp(prefix="translate-tts-astrbot-probe-")
).resolve()
os.environ["ASTRBOT_ROOT"] = str(PROBE_RUNTIME_ROOT)
sys.path[:0] = [str(PLUGIN_PARENT), str(ASTRBOT_APP)]

import astrbot
from astrbot.core.message.components import Plain, Record
from astrbot.core.message.message_event_result import ResultContentType
from astrbot.core.pipeline.result_decorate.stage import (
    ResultDecorateStage,
)
from astrbot.core.provider.provider import TTSProvider
from astrbot.core.star.context import Context
from astrbot.core.star.star_manager import PluginManager

from translate_tts.compat.astrbot_4_27 import install_astrbot_4_27_adapter
from translate_tts.config import TranslationSettings


class FakeProvider(TTSProvider):
    def __init__(self) -> None:
        super().__init__({"id": "probe", "type": "probe_tts"}, {})
        self.calls: list[str] = []
        self.fail_translated = False

    async def get_audio(self, text: str) -> str:
        self.calls.append(text)
        if self.fail_translated and text.startswith("訳:"):
            raise ValueError("simulated target-language failure")
        return r"C:\probe\voice.wav"


class FakeTranslation:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def translate_for_tts(self, text, scope):
        self.calls.append((text, scope.unified_msg_origin))
        return "訳:" + text


class FakeResult:
    def __init__(self, chain):
        self.chain = chain
        self.result_content_type = ResultContentType.LLM_RESULT
        self.use_t2i_ = None

    def is_llm_result(self):
        return True


class FakeEvent:
    unified_msg_origin = "qq_official:FriendMessage:integration"
    plugins_name: ClassVar[list[str]] = ["*"]

    def __init__(self, result):
        self.result = result
        self.extras = {}

    def get_result(self):
        return self.result

    def is_stopped(self):
        return False

    def get_platform_name(self):
        return "qq_official"

    def get_extra(self, key):
        return self.extras.get(key)


class Logger:
    def warning(self, *args):
        pass


async def main() -> None:
    stage_hashes = {
        "4.27.5": "C7D09174F080BE1FD4C6B1698AD99AA559EB0DCBF3E09C71C5BC33546C257A1C",
        "4.28.1": "6FCD8891A37BE0A2318C44E4E5D64EEA4AEE443502449B327F16ADCB3689A376",
        "4.28.2": "6FCD8891A37BE0A2318C44E4E5D64EEA4AEE443502449B327F16ADCB3689A376",
    }
    assert astrbot.__version__ in stage_hashes, astrbot.__version__
    stage_path = Path(inspect.getsourcefile(ResultDecorateStage) or "")
    stage_sha256 = hashlib.sha256(stage_path.read_bytes()).hexdigest().upper()
    assert stage_sha256 == stage_hashes[astrbot.__version__]
    context_path = Path(inspect.getsourcefile(Context) or "")
    context_sha256 = hashlib.sha256(context_path.read_bytes()).hexdigest().upper()
    assert context_sha256 == (
        "B3B4FF6CC027743ECD6D2D739E785898CEDFC02344C2ADB9F81C63B4D66235AF"
    )
    metadata = (PLUGIN_PARENT / "translate_tts" / "metadata.yaml").read_text(
        encoding="utf-8"
    )
    version_spec = next(
        line.split(":", 1)[1].strip().strip('"')
        for line in metadata.splitlines()
        if line.startswith("astrbot_version:")
    )
    assert PluginManager._validate_astrbot_version_specifier(version_spec)[0]
    assert not PluginManager._validate_astrbot_version_specifier(
        ">=4.27.5,<4.28" if astrbot.__version__.startswith("4.28.") else ">=4.29"
    )[0]
    real_getter = Context.get_using_tts_provider_async
    assert tuple(inspect.signature(real_getter).parameters) == ("self", "umo")
    assert inspect.iscoroutinefunction(real_getter)

    provider = FakeProvider()
    translation = FakeTranslation()
    context = Context.__new__(Context)
    plugin = SimpleNamespace(context=context, settings=TranslationSettings())

    getter_calls = []

    async def selected_provider(*, provider_type, umo):
        getter_calls.append(umo)
        return provider

    context.provider_manager = SimpleNamespace(
        get_using_provider_async=selected_provider,
        tts_provider_insts=[provider],
    )
    adapter = install_astrbot_4_27_adapter(plugin, translation, Logger())
    assert adapter.status.version == astrbot.__version__
    try:
        config = {
            "provider_tts_settings": {
                "enable": True,
                "dual_output": False,
                "use_file_service": False,
            },
            "callback_api_base": "",
            "t2i": False,
            "platform_settings": {"forward_threshold": 10_000},
        }
        stage = ResultDecorateStage.__new__(ResultDecorateStage)
        stage.ctx = SimpleNamespace(
            astrbot_config=config,
            plugin_manager=SimpleNamespace(context=context),
        )
        stage.content_safe_check_reply = False
        stage.content_safe_check_stage = None
        stage.reply_prefix = ""
        stage.enable_segmented_reply = False
        stage.show_reasoning = False
        stage.tts_trigger_probability = 1.0
        stage.reply_with_mention = False
        stage.reply_with_quote = False

        scenarios = 0
        for dual_output in (False, True):
            config["provider_tts_settings"]["dual_output"] = dual_output
            provider.calls.clear()
            translation.calls.clear()
            original = Plain("原文")
            event = FakeEvent(FakeResult([original]))
            async for _ in stage.process(event):
                pass
            assert provider.calls == ["訳:原文"]
            assert translation.calls == [("原文", event.unified_msg_origin)]
            assert len(event.result.chain) == 2
            assert isinstance(event.result.chain[0], Record)
            assert event.result.chain[1] is original
            scenarios += 1

        provider.fail_translated = True
        provider.calls.clear()
        event = FakeEvent(FakeResult([Plain("原文")]))
        async for _ in stage.process(event):
            pass
        assert provider.calls == ["訳:原文", "原文"]
        assert len(event.result.chain) == 2
        provider.fail_translated = False
        scenarios += 1

        for mode in ("disabled", "probability", "session", "streaming"):
            provider.calls.clear()
            translation.calls.clear()
            event = FakeEvent(FakeResult([Plain("原文")]))
            config["provider_tts_settings"]["enable"] = mode != "disabled"
            stage.tts_trigger_probability = 0.0 if mode == "probability" else 1.0
            if mode == "session":
                event.plugins_name = []
            if mode == "streaming":
                event.result.result_content_type = ResultContentType.STREAMING_RESULT
            with patch("random.random", return_value=0.5):
                async for _ in stage.process(event):
                    pass
            assert not translation.calls
            assert len(provider.calls) == (1 if mode == "session" else 0)
            scenarios += 1

        if astrbot.__version__.startswith("4.28."):
            stage.show_reasoning = True
            for enabled_reasoning in (False, True):
                event = FakeEvent(FakeResult([Plain("原文")]))
                event.extras = {
                    "enable_reasoning": enabled_reasoning,
                    "_llm_reasoning_content": "reasoning",
                }
                config["provider_tts_settings"]["enable"] = False
                async for _ in stage.process(event):
                    pass
                assert len(event.result.chain) == (2 if enabled_reasoning else 1)
                scenarios += 1

        assert getter_calls
        print(
            f"AstrBot {astrbot.__version__} real stage/getter: PASS ({scenarios} scenarios; "
            f"stage SHA256 {stage_sha256}; context SHA256 {context_sha256})"
        )
    finally:
        adapter.close()
        assert Context.get_using_tts_provider_async is real_getter


if __name__ == "__main__":
    asyncio.run(main())
