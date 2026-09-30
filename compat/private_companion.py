"""Reversible adapter for private_companion's proactive delivery boundary."""

from __future__ import annotations

import asyncio
import functools
import inspect
import time
from typing import Any

from ..scope import TranslationScope, current_translation_scope
from ..translation import TranslationService
from ..tts_proxy import TranslatedTTSProviderProxy
from .patch_manager import PatchManager
from .status import CompatibilityStatus

PLUGIN_NAME = "astrbot_plugin_private_companion"
SUPPORTED_VERSION = "6.6.2"
REFERENCE_COMMIT = "2313fd12e1bd9b72f6db9aca17cde4359102341e"


def _signature(method: Any, names: tuple[str, ...], *, async_: bool = True) -> bool:
    try:
        return tuple(inspect.signature(method).parameters) == names and (
            inspect.iscoroutinefunction(method) is async_
        )
    except (TypeError, ValueError):
        return False


class PrivateCompanionAdapter:
    """Intercept only synthesis already selected by a real proactive send."""

    def __init__(
        self, plugin: Any, service: TranslationService, *, logger: Any
    ) -> None:
        self.plugin = plugin
        self.service = service
        self.logger = logger
        self.patches: PatchManager | None = None
        self.metadata: Any = None
        self.instance: Any = None
        self._suppress_patch_status = False
        self.status = CompatibilityStatus(
            "private_companion", "not_installed", "private_companion is not loaded"
        )

    @property
    def active(self) -> bool:
        return self.patches is not None and self.patches.active

    def _set_status(self, status: CompatibilityStatus) -> None:
        if status == self.status:
            return
        self.status = status
        warning = getattr(
            self.logger, "warning", getattr(self.logger, "error", lambda *_args: None)
        )
        log = (
            warning
            if status.state == "incompatible"
            else getattr(self.logger, "info", warning)
        )
        log(
            "Translate TTS private_companion compatibility %s: %s",
            status.state,
            status.detail,
        )

    def _on_deactivated(self, reason: str) -> None:
        if not self._suppress_patch_status:
            state = "superseded" if reason == "superseded" else "closed"
            self._set_status(
                CompatibilityStatus(
                    "private_companion",
                    state,
                    f"patches were {state}",
                    self.status.version,
                    False,
                )
            )

    def _drop(self) -> None:
        if self.patches is not None:
            self._suppress_patch_status = True
            try:
                self.patches.close()
            finally:
                self._suppress_patch_status = False
        self.patches = None
        self.metadata = None
        self.instance = None

    def refresh_from_registry(self) -> CompatibilityStatus:
        try:
            stars = self.plugin.context.get_all_stars()
        except Exception as exc:  # noqa: BLE001 - registry failure must disable the adapter
            self._drop()
            self._set_status(
                CompatibilityStatus(
                    "private_companion",
                    "incompatible",
                    f"registry inspection failed: {type(exc).__name__}",
                )
            )
            return self.status
        metadata = next(
            (
                item
                for item in stars
                if getattr(item, "name", None) == PLUGIN_NAME
                and getattr(item, "activated", True)
                and getattr(item, "star_cls", None) is not None
            ),
            None,
        )
        if metadata is None:
            self._drop()
            self._set_status(
                CompatibilityStatus(
                    "private_companion",
                    "not_installed",
                    "private_companion is not loaded or inactive",
                )
            )
            return self.status
        return self.install_metadata(metadata)

    def install_metadata(self, metadata: Any) -> CompatibilityStatus:
        if getattr(metadata, "name", None) != PLUGIN_NAME:
            return self.status
        instance = getattr(metadata, "star_cls", None)
        version = str(getattr(metadata, "version", "") or "")
        if version.removeprefix("v") != SUPPORTED_VERSION:
            self._drop()
            self._set_status(
                CompatibilityStatus(
                    "private_companion",
                    "incompatible",
                    f"unsupported version: {version or 'unknown'}",
                    version,
                    False,
                )
            )
            return self.status
        if instance is None or not getattr(metadata, "activated", True):
            self._drop()
            self._set_status(
                CompatibilityStatus(
                    "private_companion",
                    "not_installed",
                    "private_companion is inactive",
                    version,
                    False,
                )
            )
            return self.status
        if self.instance is instance and self.active:
            return self.status
        required = {
            "_send_chain_components": ("umo", "chain", "apply_decorating_hooks"),
            "_create_voice_record_component": (
                "target",
                "spoken_text",
                "defer_local_playback",
            ),
            "_tts_generate_audio_path": ("tts_provider", "text"),
        }
        mismatches = [
            name
            for name, signature in required.items()
            if not _signature(getattr(instance, name, None), signature)
        ]
        if mismatches:
            self._drop()
            self._set_status(
                CompatibilityStatus(
                    "private_companion",
                    "incompatible",
                    "signature mismatch: " + ", ".join(mismatches),
                    version,
                    False,
                )
            )
            return self.status
        self._drop()
        self.instance = instance
        self.metadata = metadata
        manager = PatchManager(self._on_deactivated)
        self.patches = manager
        try:
            manager.install(
                instance,
                "_send_chain_components",
                self._wrap_send,
                patch_key=f"{PLUGIN_NAME}.instance._send_chain_components",
            )
            manager.install(
                instance,
                "_create_voice_record_component",
                self._wrap_voice,
                patch_key=f"{PLUGIN_NAME}.instance._create_voice_record_component",
            )
            manager.install(
                instance,
                "_tts_generate_audio_path",
                self._wrap_audio,
                patch_key=f"{PLUGIN_NAME}.instance._tts_generate_audio_path",
            )
        except Exception as exc:  # noqa: BLE001 - partial patches must be rolled back
            self._drop()
            self._set_status(
                CompatibilityStatus(
                    "private_companion",
                    "incompatible",
                    f"patch installation failed: {type(exc).__name__}",
                    version,
                    False,
                )
            )
            return self.status
        self._set_status(
            CompatibilityStatus(
                "private_companion",
                "signature_compatible_unverified",
                f"v{SUPPORTED_VERSION} signatures matched; loaded source was not verified as {REFERENCE_COMMIT}",
                version,
                False,
            )
        )
        return self.status

    def handle_plugin_loaded(self, metadata: Any) -> CompatibilityStatus:
        return self.install_metadata(metadata)

    def handle_plugin_unloaded(self, metadata: Any) -> CompatibilityStatus:
        if self.instance is not None and (
            metadata is self.metadata
            or getattr(metadata, "star_cls", None) is self.instance
        ):
            self._drop()
            self._set_status(
                CompatibilityStatus(
                    "private_companion",
                    "not_installed",
                    "private_companion was unloaded",
                )
            )
        return self.status

    def mark_disabled(self) -> None:
        self._drop()
        self._set_status(
            CompatibilityStatus(
                "private_companion",
                "disabled",
                "private_companion compatibility is disabled",
            )
        )

    def close(self) -> None:
        self._drop()
        self._set_status(
            CompatibilityStatus(
                "private_companion",
                "closed",
                "private_companion compatibility is closed",
            )
        )

    async def _in_scope(
        self, umo: str, original: Any, *args: Any, **kwargs: Any
    ) -> Any:
        settings = self.plugin.settings
        if (
            not self.active
            or not settings.enabled
            or not settings.enable_proactive_compat
            or not isinstance(umo, str)
            or not umo
        ):
            return await original(*args, **kwargs)
        existing = current_translation_scope.get()
        if (
            existing is not None
            and existing.active
            and existing.owner is self.instance
            and existing.unified_msg_origin == umo
            and existing.is_owned_by_current_task()
        ):
            return await original(*args, **kwargs)
        scope = TranslationScope(
            "proactive",
            umo,
            settings,
            owner=self.instance,
            owner_task=asyncio.current_task(),
        )
        token = current_translation_scope.set(scope)
        diagnostics = getattr(self.plugin, "diagnostics", None)
        if diagnostics is not None:
            diagnostics.emit(
                "scope_started",
                detail=True,
                trace_id=scope.trace_id,
                source=scope.source,
            )
        try:
            return await original(*args, **kwargs)
        finally:
            if diagnostics is not None:
                diagnostics.emit(
                    "scope_closed",
                    detail=True,
                    trace_id=scope.trace_id,
                    source=scope.source,
                    conversions=len(scope.conversions),
                    produced_audio=sum(
                        entry.produced_audio for entry in scope.conversions
                    ),
                    elapsed_ms=round(
                        (time.monotonic() - scope.started_monotonic) * 1000
                    ),
                )
            scope.deactivate()
            current_translation_scope.reset(token)

    def _wrap_send(self, original: Any) -> Any:
        @functools.wraps(original)
        async def wrapped(
            umo: str, chain: list[Any], *, apply_decorating_hooks: bool = True
        ) -> Any:
            return await self._in_scope(
                umo, original, umo, chain, apply_decorating_hooks=apply_decorating_hooks
            )

        return wrapped

    def _wrap_voice(self, original: Any) -> Any:
        @functools.wraps(original)
        async def wrapped(
            target: str, spoken_text: str, *, defer_local_playback: bool = False
        ) -> Any:
            return await self._in_scope(
                target,
                original,
                target,
                spoken_text,
                defer_local_playback=defer_local_playback,
            )

        return wrapped

    def _wrap_audio(self, original: Any) -> Any:
        @functools.wraps(original)
        async def wrapped(tts_provider: Any, text: str) -> Any:
            scope = current_translation_scope.get()
            if (
                not self.active
                or scope is None
                or not scope.active
                or scope.owner is not self.instance
                or not scope.is_owned_by_current_task()
                or not callable(getattr(tts_provider, "get_audio", None))
            ):
                return await original(tts_provider, text)
            proxy = TranslatedTTSProviderProxy(
                tts_provider, scope, self.service, lambda: self.active
            )
            return await original(proxy, text)

        return wrapped
