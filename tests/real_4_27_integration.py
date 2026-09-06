"""Targeted integration probe against the locally installed AstrBot 4.27.5.

Run with AstrBot's embedded Python and ``ASTRBOT_ROOT`` pointing at a disposable,
writable directory. This file is deliberately outside pytest's default pattern.
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
        "AstrBot 4.27.5 source was not found; set ASTRBOT_ROOT to its repository "
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
from astrbot.core.star.context import Context
from astrbot.core.star.session_plugin_manager import SessionPluginManager

from translate_tts.compat.astrbot_4_27 import NormalPipelineAdapter
from translate_tts.config import TranslationSettings


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_audio(self, text: str) -> str:
        self.calls.append(text)
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

    def get_result(self):
        return self.result

    def is_stopped(self):
        return False

    def get_platform_name(self):
        return "qq_official"

    def get_extra(self, key):
        return None


class Logger:
    def warning(self, *args):
        pass


async def main() -> None:
    assert astrbot.__version__ == "4.27.5", (
        f"expected AstrBot 4.27.5, found {astrbot.__version__}"
    )
    stage_path = Path(inspect.getsourcefile(ResultDecorateStage) or "")
    stage_sha256 = hashlib.sha256(stage_path.read_bytes()).hexdigest().upper()
    assert stage_sha256 == (
        "C7D09174F080BE1FD4C6B1698AD99AA559EB0DCBF3E09C71C5BC33546C257A1C"
    )
    context_path = Path(inspect.getsourcefile(Context) or "")
    context_sha256 = hashlib.sha256(context_path.read_bytes()).hexdigest().upper()
    assert context_sha256 == (
        "B3B4FF6CC027743ECD6D2D739E785898CEDFC02344C2ADB9F81C63B4D66235AF"
    )
    real_getter = Context.get_using_tts_provider_async
    assert tuple(inspect.signature(real_getter).parameters) == ("self", "umo")
    assert inspect.iscoroutinefunction(real_getter)
    real_getter_source = inspect.getsource(real_getter)
    assert "ProviderType.TEXT_TO_SPEECH" in real_getter_source
    assert "get_using_provider_async" in real_getter_source

    provider = FakeProvider()
    translation = FakeTranslation()
    context = Context.__new__(Context)
    plugin = SimpleNamespace(context=context, settings=TranslationSettings())

    original_getter = real_getter
    original_enablement = SessionPluginManager.is_plugin_enabled_for_session

    async def fake_getter(self, umo=None):
        return provider

    async def enabled(umo, plugin_name):
        return True

    Context.get_using_tts_provider_async = fake_getter
    SessionPluginManager.is_plugin_enabled_for_session = staticmethod(enabled)
    adapter = NormalPipelineAdapter(plugin, translation, logger=Logger())
    try:
        adapter.install(
            stage_class=ResultDecorateStage,
            context_class=Context,
            session_plugin_manager=SessionPluginManager,
            plain_type=Plain,
            record_type=Record,
            streaming_result=ResultContentType.STREAMING_RESULT,
            streaming_finish=ResultContentType.STREAMING_FINISH,
        )
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

        original = Plain("原文")
        event = FakeEvent(FakeResult([original]))
        async for _ in stage.process(event):
            pass

        assert provider.calls == ["訳:原文"]
        assert translation.calls == [("原文", "qq_official:FriendMessage:integration")]
        assert len(event.result.chain) == 2
        assert isinstance(event.result.chain[0], Record)
        assert event.result.chain[1] is original
        print(
            "AstrBot 4.27.5 ResultDecorateStage integration: PASS "
            f"(stage SHA256 {stage_sha256}; context SHA256 {context_sha256})"
        )
    finally:
        adapter.close()
        Context.get_using_tts_provider_async = original_getter
        SessionPluginManager.is_plugin_enabled_for_session = original_enablement


if __name__ == "__main__":
    asyncio.run(main())
