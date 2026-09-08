"""AstrBot 4.27.5 normal ResultDecorateStage integration."""

from __future__ import annotations

import asyncio
import functools
import inspect
import time
from collections.abc import AsyncGenerator, Callable
from typing import Any

from ..diagnostics import exception_type_chain
from ..scope import TranslationScope, current_translation_scope
from ..translation import TranslationService
from ..tts_proxy import TranslatedTTSProviderProxy
from .patch_manager import PatchManager
from .status import CompatibilityStatus

PLUGIN_NAME = "astrbot_plugin_translate_tts"


def _has_signature(callable_: Any, parameter_names: tuple[str, ...]) -> bool:
    try:
        return tuple(inspect.signature(callable_).parameters) == parameter_names
    except (TypeError, ValueError):
        return False


class NormalPipelineAdapter:
    """Own the two class patches required for the normal non-streaming path."""

    def __init__(
        self, plugin: Any, service: TranslationService, *, logger: Any
    ) -> None:
        self.plugin = plugin
        self.service = service
        self.logger = logger
        self.patches = PatchManager(self._on_patch_deactivated)
        self.status = CompatibilityStatus(
            "normal",
            "not_installed",
            "normal pipeline compatibility is not installed",
            baseline_commit_verified=None,
        )
        self.plain_type: type | None = None
        self.record_type: type | None = None
        self.streaming_types: tuple[Any, Any] | None = None
        self.session_plugin_manager: Any = None

    @property
    def active(self) -> bool:
        return self.patches.active

    def install(
        self,
        *,
        stage_class: type,
        context_class: type,
        session_plugin_manager: Any,
        plain_type: type,
        record_type: type,
        streaming_result: Any,
        streaming_finish: Any,
    ) -> None:
        process = getattr(stage_class, "process", None)
        getter = getattr(context_class, "get_using_tts_provider_async", None)
        if not _has_signature(process, ("self", "event")):
            raise RuntimeError("unsupported ResultDecorateStage.process signature")
        if not _has_signature(getter, ("self", "umo")):
            raise RuntimeError(
                "unsupported Context.get_using_tts_provider_async signature"
            )
        if not inspect.isasyncgenfunction(process):
            raise RuntimeError("ResultDecorateStage.process is not an async generator")
        if not inspect.iscoroutinefunction(getter):
            raise RuntimeError("Context TTS getter is not async")

        self.plain_type = plain_type
        self.record_type = record_type
        self.streaming_types = (streaming_result, streaming_finish)
        self.session_plugin_manager = session_plugin_manager
        try:
            self.patches.install(stage_class, "process", self._wrap_process)
            self.patches.install(
                context_class,
                "get_using_tts_provider_async",
                self._wrap_tts_getter,
            )
        except Exception:
            self.patches.rollback()
            raise
        self._set_status(
            CompatibilityStatus(
                "normal",
                "signature_compatible_unverified",
                "AstrBot 4.27 normal pipeline signatures are compatible",
                "4.27.x",
                None,
            )
        )

    def close(self) -> None:
        self.patches.close()
        self._set_status(
            CompatibilityStatus(
                "normal", "closed", "normal compatibility adapter is closed"
            )
        )

    def mark_disabled(self, detail: str = "normal compatibility is disabled") -> None:
        self.patches.rollback()
        self._set_status(CompatibilityStatus("normal", "disabled", detail))

    def mark_incompatible(self, detail: str) -> None:
        if self.patches.active:
            self.patches.rollback()
        self._set_status(CompatibilityStatus("normal", "incompatible", detail))

    def _on_patch_deactivated(self, reason: str) -> None:
        state = "superseded" if reason == "superseded" else "closed"
        self._set_status(
            CompatibilityStatus(
                "normal", state, f"normal compatibility patches were {state}"
            )
        )

    def _set_status(self, status: CompatibilityStatus) -> None:
        if status == self.status:
            return
        self.status = status
        warning = getattr(
            self.logger, "warning", getattr(self.logger, "error", lambda *args: None)
        )
        log = (
            warning
            if status.state == "incompatible"
            else getattr(self.logger, "info", warning)
        )
        log("Translate TTS normal compatibility %s: %s", status.state, status.detail)

    async def _eligible(self, event: Any) -> bool:
        if not self.active or not self.plugin.settings.enabled:
            return False
        result = event.get_result()
        if result is None or not getattr(result, "chain", None):
            return False
        assert self.streaming_types is not None
        if getattr(result, "result_content_type", None) in self.streaming_types:
            return False
        plugins_name = getattr(event, "plugins_name", None)
        if (
            plugins_name is not None
            and plugins_name != ["*"]
            and PLUGIN_NAME not in plugins_name
        ):
            return False
        try:
            return await self.session_plugin_manager.is_plugin_enabled_for_session(
                event.unified_msg_origin,
                PLUGIN_NAME,
            )
        except Exception as exc:  # noqa: BLE001 - enablement storage must fail closed
            self.logger.warning(
                "Translate TTS session enablement check failed; passing through: %s",
                type(exc).__name__,
            )
            return False

    def _wrap_process(self, original: Callable[..., AsyncGenerator[Any, None]]) -> Any:
        adapter = self

        @functools.wraps(original)
        async def wrapped(stage: Any, event: Any) -> AsyncGenerator[Any, None]:
            if not await adapter._eligible(event):
                async for item in original(stage, event):
                    yield item
                return

            scope = TranslationScope(
                "normal",
                event.unified_msg_origin,
                adapter.plugin.settings,
                owner=adapter.plugin,
                event=event,
                owner_task=asyncio.current_task(),
            )
            diagnostics = getattr(adapter.plugin, "diagnostics", None)
            if diagnostics is not None:
                diagnostics.emit(
                    "scope_started",
                    detail=True,
                    trace_id=scope.trace_id,
                    source=scope.source,
                )
            generator = original(stage, event)
            completed = False
            try:
                while True:
                    token = current_translation_scope.set(scope)
                    try:
                        item = await generator.__anext__()
                    except StopAsyncIteration:
                        completed = True
                        break
                    finally:
                        current_translation_scope.reset(token)
                    yield item
            except asyncio.CancelledError:
                if diagnostics is not None:
                    diagnostics.emit(
                        "scope_cancelled",
                        trace_id=scope.trace_id,
                        source=scope.source,
                        elapsed_ms=round(
                            (time.monotonic() - scope.started_monotonic) * 1000
                        ),
                    )
                raise
            except Exception as exc:
                if diagnostics is not None:
                    diagnostics.emit(
                        "scope_failed",
                        severity="warning",
                        trace_id=scope.trace_id,
                        source=scope.source,
                        exception_types=exception_type_chain(exc),
                    )
                raise
            finally:
                if diagnostics is not None:
                    diagnostics.emit(
                        "scope_closed",
                        detail=True,
                        trace_id=scope.trace_id,
                        source=scope.source,
                        completed=completed,
                        conversions=len(scope.conversions),
                        produced_audio=sum(
                            entry.produced_audio for entry in scope.conversions
                        ),
                        elapsed_ms=round(
                            (time.monotonic() - scope.started_monotonic) * 1000
                        ),
                    )
                scope.deactivate()
                await generator.aclose()
            if completed:
                adapter._restore_original_text(scope)

        return wrapped

    def _wrap_tts_getter(self, original: Callable[..., Any]) -> Any:
        adapter = self

        @functools.wraps(original)
        async def wrapped(context: Any, umo: str | None = None) -> Any:
            provider = await original(context, umo)
            scope = current_translation_scope.get()
            if (
                provider is None
                or not adapter.active
                or scope is None
                or not scope.active
                or scope.source != "normal"
                or scope.owner is not adapter.plugin
                or not scope.is_owned_by_current_task()
                or umo != scope.unified_msg_origin
                or getattr(scope.owner, "context", None) is not context
            ):
                return provider
            assert adapter.plain_type is not None
            assert adapter.record_type is not None
            scope.snapshot_before_tts(
                plain_type=adapter.plain_type,
                record_type=adapter.record_type,
            )
            return TranslatedTTSProviderProxy(
                provider,
                scope,
                adapter.service,
                lambda: adapter.active,
            )

        return wrapped

    def _restore_original_text(self, scope: TranslationScope) -> None:
        if scope.event is None or self.record_type is None:
            return
        result = scope.event.get_result()
        if result is None or not getattr(result, "chain", None):
            return

        final_component_ids = {id(component) for component in result.chain}
        missing_entries = [
            entry
            for entry in scope.conversions
            if entry.produced_audio
            and entry.source_component is not None
            and id(entry.source_component) not in final_component_ids
        ]
        if not missing_entries:
            return
        new_records = [
            component
            for component in result.chain
            if isinstance(component, self.record_type)
            and id(component) not in scope.pre_tts_record_ids
        ]
        record_to_entry = {
            id(record): entry for record, entry in zip(new_records, missing_entries)
        }
        restored: list[Any] = []
        restored_entry_ids: set[int] = set()
        for component in result.chain:
            restored.append(component)
            entry = record_to_entry.get(id(component))
            if entry is not None:
                restored.append(entry.source_component)
                restored_entry_ids.add(id(entry))
        for entry in missing_entries:
            if id(entry) not in restored_entry_ids:
                restored.append(entry.source_component)
                self.logger.warning(
                    "Translate TTS could not associate a converted Record; "
                    "the original text was appended safely."
                )
        result.chain = restored


def install_astrbot_4_27_adapter(
    plugin: Any,
    service: TranslationService,
    logger: Any,
    *,
    adapter: NormalPipelineAdapter | None = None,
) -> NormalPipelineAdapter:
    """Import and patch only the exact 4.27.5 integration surfaces."""
    from astrbot.core.message.components import Plain, Record
    from astrbot.core.message.message_event_result import ResultContentType
    from astrbot.core.pipeline.result_decorate.stage import ResultDecorateStage
    from astrbot.core.star.context import Context
    from astrbot.core.star.session_plugin_manager import SessionPluginManager

    adapter = adapter or NormalPipelineAdapter(plugin, service, logger=logger)
    adapter.install(
        stage_class=ResultDecorateStage,
        context_class=Context,
        session_plugin_manager=SessionPluginManager,
        plain_type=Plain,
        record_type=Record,
        streaming_result=ResultContentType.STREAMING_RESULT,
        streaming_finish=ResultContentType.STREAMING_FINISH,
    )
    return adapter
