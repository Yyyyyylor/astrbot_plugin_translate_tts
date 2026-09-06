from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import ClassVar

from translate_tts.compat.astrbot_4_27 import NormalPipelineAdapter
from translate_tts.config import TranslationSettings
from translate_tts.scope import current_translation_scope


class Plain:
    def __init__(self, text: str):
        self.text = text


class Record:
    def __init__(self, file: str, *, text: str = ""):
        self.file = file
        self.url = file
        self.text = text


class Result:
    def __init__(self, chain, content_type="complete"):
        self.chain = chain
        self.result_content_type = content_type


class Event:
    def __init__(self, chain, *, umo="qq:friend:1", plugins_name=None):
        self.result = Result(chain)
        self.unified_msg_origin = umo
        self.plugins_name = plugins_name
        self.should_tts = True

    def get_result(self):
        return self.result


class Provider:
    def __init__(self):
        self.calls = []
        self.fail_translated = False
        self.block = None

    async def get_audio(self, text: str):
        self.calls.append(text)
        if self.block is not None:
            await self.block.wait()
        if self.fail_translated and text.startswith("訳"):
            raise RuntimeError("unsupported language")
        return f"C:/audio/{len(self.calls)}.wav"


class Context:
    def __init__(self, provider):
        self.provider = provider
        self.getter_calls = []

    async def get_using_tts_provider_async(self, umo=None):
        self.getter_calls.append(umo)
        return self.provider


class Stage:
    def __init__(self, context, *, dual_output=False, file_service=False):
        self.context = context
        self.dual_output = dual_output
        self.file_service = file_service
        self.fail_after_audio_indices = set()

    async def process(self, event):
        provider = await self.context.get_using_tts_provider_async(
            event.unified_msg_origin
        )
        if event.should_tts and provider:
            new_chain = []
            for index, component in enumerate(event.get_result().chain):
                if isinstance(component, Plain) and len(component.text) > 1:
                    try:
                        audio = await provider.get_audio(component.text)
                        if index in self.fail_after_audio_indices:
                            raise RuntimeError("downstream Record construction failed")
                        path = (
                            "https://files.invalid/token"
                            if self.file_service
                            else audio
                        )
                        new_chain.append(Record(path, text=component.text))
                        if self.dual_output:
                            new_chain.append(component)
                    except Exception:  # noqa: BLE001 - mirrors the AstrBot stage
                        new_chain.append(component)
                else:
                    new_chain.append(component)
            event.get_result().chain = new_chain
        if False:
            yield None


class SessionPlugins:
    enabled = True
    calls: ClassVar[list[tuple[str, str]]] = []

    @classmethod
    async def is_plugin_enabled_for_session(cls, umo, plugin_name):
        cls.calls.append((umo, plugin_name))
        return cls.enabled


class Translation:
    def __init__(self):
        self.calls = []

    async def translate_for_tts(self, text, scope):
        self.calls.append((text, scope.unified_msg_origin))
        return "訳:" + text


class Logger:
    def warning(self, *args):
        pass


class NormalPipelineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        SessionPlugins.enabled = True
        SessionPlugins.calls = []
        self.provider = Provider()
        self.context = Context(self.provider)
        self.translation = Translation()
        self.plugin = SimpleNamespace(
            context=self.context,
            settings=TranslationSettings(),
        )
        self.adapter = NormalPipelineAdapter(
            self.plugin, self.translation, logger=Logger()
        )
        self.adapter.install(
            stage_class=Stage,
            context_class=Context,
            session_plugin_manager=SessionPlugins,
            plain_type=Plain,
            record_type=Record,
            streaming_result="streaming",
            streaming_finish="stream-finish",
        )

    async def asyncTearDown(self):
        self.adapter.close()

    async def run_stage(self, event, **kwargs):
        stage = Stage(self.context, **kwargs)
        async for _ in stage.process(event):
            pass
        return stage

    async def test_only_real_tts_calls_translate_and_force_one_original(self):
        original = Plain("你好")
        event = Event([original])
        await self.run_stage(event, dual_output=False)
        self.assertEqual(self.provider.calls, ["訳:你好"])
        self.assertEqual([type(item) for item in event.result.chain], [Record, Plain])
        self.assertIs(event.result.chain[1], original)

        self.translation.calls.clear()
        untouched = Event([Plain("不播报")])
        untouched.should_tts = False
        await self.run_stage(untouched)
        self.assertEqual(self.translation.calls, [])
        self.assertEqual(self.provider.calls, ["訳:你好"])
        self.assertEqual([item.text for item in untouched.result.chain], ["不播报"])

    async def test_dual_output_does_not_duplicate_original(self):
        original = Plain("你好")
        event = Event([original])
        await self.run_stage(event, dual_output=True)
        self.assertEqual(event.result.chain.count(original), 1)

    async def test_duplicate_segments_and_existing_record_use_identity_ledger(self):
        old_record = Record("old.wav", text="重复")
        first = Plain("重复")
        second = Plain("重复")
        event = Event([old_record, first, second])
        await self.run_stage(event, file_service=True)
        self.assertIs(event.result.chain[0], old_record)
        self.assertEqual(
            [type(item) for item in event.result.chain],
            [Record, Record, Plain, Record, Plain],
        )
        self.assertIs(event.result.chain[2], first)
        self.assertIs(event.result.chain[4], second)
        for record in (event.result.chain[1], event.result.chain[3]):
            self.assertEqual(record.file, "https://files.invalid/token")
            self.assertEqual(record.url, "https://files.invalid/token")

    async def test_local_record_file_and_url_are_unchanged(self):
        event = Event([Plain("本地")])
        await self.run_stage(event)
        record = event.result.chain[0]
        self.assertEqual(record.file, "C:/audio/1.wav")
        self.assertEqual(record.url, "C:/audio/1.wav")

    async def test_translated_tts_failure_retries_original_once(self):
        self.provider.fail_translated = True
        event = Event([Plain("原文")])
        await self.run_stage(event)
        self.assertEqual(self.provider.calls, ["訳:原文", "原文"])
        self.assertEqual([type(item) for item in event.result.chain], [Record, Plain])

    async def test_translation_fallback_calls_original_tts_exactly_once(self):
        async def return_original(text, scope):
            return text

        self.translation.translate_for_tts = return_original
        event = Event([Plain("原文")])
        await self.run_stage(event)
        self.assertEqual(self.provider.calls, ["原文"])

    async def test_downstream_failure_does_not_shift_later_record_association(self):
        first = Plain("重复")
        second = Plain("重复")
        event = Event([first, second])
        stage = Stage(self.context)
        stage.fail_after_audio_indices = {0}
        async for _ in stage.process(event):
            pass
        self.assertEqual(
            [type(item) for item in event.result.chain], [Plain, Record, Plain]
        )
        self.assertIs(event.result.chain[0], first)
        self.assertIs(event.result.chain[2], second)

    async def test_global_and_session_disable_are_passthrough(self):
        event = Event([Plain("原文")], plugins_name=["another_plugin"])
        await self.run_stage(event)
        self.assertEqual(self.translation.calls, [])
        self.assertEqual(SessionPlugins.calls, [])

        SessionPlugins.enabled = False
        event = Event([Plain("原文")])
        await self.run_stage(event)
        self.assertEqual(self.translation.calls, [])
        self.assertEqual(len(SessionPlugins.calls), 1)

    async def test_streaming_results_are_passthrough(self):
        for content_type in ("streaming", "stream-finish"):
            with self.subTest(content_type=content_type):
                event = Event([Plain("原文")])
                event.result.result_content_type = content_type
                await self.run_stage(event)
        self.assertEqual(self.translation.calls, [])

    async def test_two_sessions_keep_independent_contextvar_scopes(self):
        first = Event([Plain("甲甲")], umo="qq:friend:1")
        second = Event([Plain("乙乙")], umo="qq:friend:2")
        await asyncio.gather(self.run_stage(first), self.run_stage(second))
        self.assertCountEqual(
            self.translation.calls,
            [("甲甲", "qq:friend:1"), ("乙乙", "qq:friend:2")],
        )
        self.assertEqual(first.result.chain[1].text, "甲甲")
        self.assertEqual(second.result.chain[1].text, "乙乙")

    async def test_child_task_does_not_inherit_an_active_translation_scope(self):
        adapter = self.adapter

        class ChildStage:
            async def process(self, event):
                async def child_call():
                    provider = (
                        await adapter.plugin.context.get_using_tts_provider_async(
                            event.unified_msg_origin
                        )
                    )
                    return await provider.get_audio("子任务")

                await asyncio.create_task(child_call())
                if False:
                    yield None

        adapter.close()
        self.adapter = NormalPipelineAdapter(
            self.plugin, self.translation, logger=Logger()
        )
        self.adapter.install(
            stage_class=ChildStage,
            context_class=Context,
            session_plugin_manager=SessionPlugins,
            plain_type=Plain,
            record_type=Record,
            streaming_result="streaming",
            streaming_finish="stream-finish",
        )
        async for _ in ChildStage().process(Event([Plain("父任务")])):
            pass
        self.assertEqual(self.translation.calls, [])
        self.assertEqual(self.provider.calls, ["子任务"])

    async def test_overlapping_plugin_generation_replaces_old_wrappers(self):
        old_translation = self.translation
        new_translation = Translation()
        new_plugin = SimpleNamespace(
            context=self.context,
            settings=TranslationSettings(),
        )
        newer = NormalPipelineAdapter(new_plugin, new_translation, logger=Logger())
        newer.install(
            stage_class=Stage,
            context_class=Context,
            session_plugin_manager=SessionPlugins,
            plain_type=Plain,
            record_type=Record,
            streaming_result="streaming",
            streaming_finish="stream-finish",
        )
        try:
            self.assertFalse(self.adapter.active)
            self.assertEqual(self.adapter.status.state, "superseded")
            await self.run_stage(Event([Plain("仅一次")]))
            self.assertEqual(old_translation.calls, [])
            self.assertEqual(new_translation.calls, [("仅一次", "qq:friend:1")])
            self.adapter.close()
            await self.run_stage(Event([Plain("仍一次")]))
            self.assertEqual(len(new_translation.calls), 2)
        finally:
            newer.close()

    async def test_scope_is_not_visible_at_outward_yield(self):
        class YieldingStage:
            async def process(self, event):
                self.seen_inside = current_translation_scope.get()
                yield "checkpoint"
                self.seen_after = current_translation_scope.get()

        adapter = NormalPipelineAdapter(self.plugin, self.translation, logger=Logger())
        adapter.install(
            stage_class=YieldingStage,
            context_class=type(
                "OtherContext",
                (),
                {"get_using_tts_provider_async": Context.get_using_tts_provider_async},
            ),
            session_plugin_manager=SessionPlugins,
            plain_type=Plain,
            record_type=Record,
            streaming_result="streaming",
            streaming_finish="stream-finish",
        )
        try:
            stage = YieldingStage()
            generator = stage.process(Event([Plain("ok")]))
            self.assertEqual(await generator.__anext__(), "checkpoint")
            self.assertIsNone(current_translation_scope.get())
            with self.assertRaises(StopAsyncIteration):
                await generator.__anext__()
            self.assertIsNotNone(stage.seen_inside)
            self.assertIs(stage.seen_after, stage.seen_inside)
        finally:
            adapter.close()

    async def test_cancellation_cleans_scope_and_does_not_fallback(self):
        self.provider.block = asyncio.Event()
        event = Event([Plain("原文")])
        task = asyncio.create_task(self.run_stage(event))
        while not self.provider.calls:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.provider.calls, ["訳:原文"])
        self.assertIsNone(current_translation_scope.get())

    async def test_compatibility_status_is_observable(self):
        self.assertEqual(self.adapter.status.state, "signature_compatible_unverified")
        self.adapter.close()
        self.assertEqual(self.adapter.status.state, "closed")


if __name__ == "__main__":
    unittest.main()
