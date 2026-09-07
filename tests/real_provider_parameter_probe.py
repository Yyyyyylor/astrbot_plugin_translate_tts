"""Offline probe of AstrBot 4.27.5 provider request serialization.

Run with AstrBot's embedded Python and ``PYTHONPATH`` containing both the
AstrBot backend app directory and this package's parent directory. No network,
credentials, paid synthesis, or QQ delivery is used.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from contextlib import ExitStack
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

import ormsgpack
from astrbot.core.provider.sources import elevenlabs_tts_source as eleven_module
from astrbot.core.provider.sources import fishaudio_tts_api_source as fish_module
from astrbot.core.provider.sources import gemini_tts_source as gemini_module
from astrbot.core.provider.sources.elevenlabs_tts_source import ProviderElevenLabsTTSAPI
from astrbot.core.provider.sources.fishaudio_tts_api_source import (
    ProviderFishAudioTTSAPI,
)
from astrbot.core.provider.sources.gemini_tts_source import ProviderGeminiTTSAPI
from astrbot.core.provider.sources.minimax_tts_api_source import ProviderMiniMaxTTSAPI

from translate_tts.config import TranslationSettings
from translate_tts.emotion import TranslationResult
from translate_tts.tts_adapters import ProviderResolution, prepare_call


class FishResponse:
    status_code = 200
    headers: ClassVar[dict[str, str]] = {"content-type": "audio/wav"}

    async def aiter_bytes(self):
        yield b"RIFF"


class FishStream:
    async def __aenter__(self):
        return FishResponse()

    async def __aexit__(self, *args):
        return False


class FishClient:
    captured = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def stream(self, method, path, **kwargs):
        FishClient.captured = (method, path, kwargs)
        return FishStream()


class ElevenClient:
    captured = None

    async def post(self, url, **kwargs):
        ElevenClient.captured = (url, kwargs)
        return SimpleNamespace(status_code=200, content=b"audio", text="")


class GeminiModels:
    captured = None

    async def generate_content(self, **kwargs):
        GeminiModels.captured = kwargs
        data = SimpleNamespace(data=b"\x00\x00")
        part = SimpleNamespace(inline_data=data)
        content = SimpleNamespace(parts=[part])
        return SimpleNamespace(candidates=[SimpleNamespace(content=content)])


async def main() -> None:
    with (
        tempfile.TemporaryDirectory(prefix="translate-tts-provider-probe-") as temp_dir,
        ExitStack() as patches,
    ):
        for module in (fish_module, eleven_module, gemini_module):
            patches.enter_context(
                patch.object(module, "get_astrbot_temp_path", return_value=temp_dir)
            )
        patches.enter_context(patch.object(fish_module, "AsyncClient", FishClient))
        await run_probe()


async def run_probe() -> None:
    settings = TranslationSettings()
    result = TranslationResult(
        "原文",
        "訳文",
        "happy",
        True,
        ("nostalgic", "whispering", "sighing"),
    )

    fish = ProviderFishAudioTTSAPI.__new__(ProviderFishAudioTTSAPI)
    fish.provider_config = {"id": "fish", "type": "fishaudio_tts_api"}
    fish.model_name = "s2-pro"
    fish.headers = {"Authorization": "Bearer fake"}
    fish.api_base = "https://api.fish.audio/v1"
    fish.timeout = 1
    fish.proxy = ""

    async def request(text):
        return fish_module.ServeTTSRequest(text=text, format="wav")

    fish._generate_request = request
    prepared = prepare_call(
        ProviderResolution(fish, "fishaudio_tts_api"), result, settings
    )
    await prepared.provider.get_audio(prepared.text)
    assert FishClient.captured[2]["headers"]["model"] == "s2.1-pro-free"
    assert ormsgpack.unpackb(FishClient.captured[2]["content"])["text"] == (
        "[nostalgic][whispering][sighing] 訳文"
    )
    assert fish.headers == {"Authorization": "Bearer fake"}

    eleven = ProviderElevenLabsTTSAPI.__new__(ProviderElevenLabsTTSAPI)
    eleven.provider_config = {"id": "eleven", "type": "elevenlabs_tts_api"}
    eleven.api_base = "https://api.elevenlabs.io/v1"
    eleven.voice_id = "voice"
    eleven.api_key = "fake"
    eleven.model_name = "eleven_v3"
    eleven.output_format = "mp3_44100_128"
    eleven.voice_settings = {}
    eleven.client = ElevenClient()
    prepared = prepare_call(
        ProviderResolution(eleven, "elevenlabs_tts_api"), result, settings
    )
    await prepared.provider.get_audio(prepared.text)
    assert ElevenClient.captured[1]["json"] == {
        "text": "[excited] 訳文",
        "model_id": "eleven_v3",
    }

    minimax = ProviderMiniMaxTTSAPI.__new__(ProviderMiniMaxTTSAPI)
    minimax.provider_config = {"id": "mini", "type": "minimax_tts_api"}
    minimax.model_name = "speech-2.6-hd"
    minimax.voice_setting = {"speed": 1, "voice_id": "voice"}
    minimax.audio_setting = {"format": "wav"}
    minimax.lang_boost = "auto"
    minimax.is_timber_weight = False
    prepared = prepare_call(
        ProviderResolution(minimax, "minimax_tts_api"), result, settings
    )
    body = json.loads(prepared.provider._build_tts_stream_body(prepared.text))
    assert body["voice_setting"]["emotion"] == "happy"
    assert "emotion" not in minimax.voice_setting

    gemini = ProviderGeminiTTSAPI.__new__(ProviderGeminiTTSAPI)
    gemini.provider_config = {"id": "gemini", "type": "gemini_tts"}
    gemini.model = "gemini-2.5-flash-preview-tts"
    gemini.prefix = "Existing style"
    gemini.voice_name = "Leda"
    gemini.client = SimpleNamespace(models=GeminiModels())
    prepared = prepare_call(ProviderResolution(gemini, "gemini_tts"), result, settings)
    await prepared.provider.get_audio(prepared.text)
    assert GeminiModels.captured["model"] == "gemini-2.5-flash-preview-tts"
    assert "happy" in GeminiModels.captured["contents"]
    assert "Transcript: 訳文" in GeminiModels.captured["contents"]

    print("real AstrBot provider parameter probe passed")


if __name__ == "__main__":
    asyncio.run(main())
