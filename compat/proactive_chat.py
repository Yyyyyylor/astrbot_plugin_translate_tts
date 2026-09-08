"""Runtime compatibility for proactive_chat v1.2.5.

The adapter patches only live Python objects.  It never edits the proactive
plugin's files or its session configuration dictionaries.
"""

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

PROACTIVE_PLUGIN_NAME = "astrbot_plugin_proactive_chat"
SUPPORTED_VERSION = "1.2.5"
BASELINE_COMMIT = "d1203524f29be248a4975bac1f7586e9557434ee"


def _normalized_version(value: Any) -> str:
    version = str(value or "").strip()
    return version[1:] if version.lower().startswith("v") else version


def _has_bound_signature(callable_: Any, parameter_names: tuple[str, ...]) -> bool:
    try:
        return tuple(inspect.signature(callable_).parameters) == parameter_names
    except (TypeError, ValueError):
        return False


ProactiveCompatibilityStatus = CompatibilityStatus


class ProactiveChatAdapter:
    """Patch one discovered proactive_chat instance and its Context getter."""

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
        self.status = ProactiveCompatibilityStatus(
            "proactive",
            "not_installed",
            "proactive_chat is not loaded",
            baseline_commit_verified=False,
        )

    @property
    def active(self) -> bool:
        return self.patches is not None and self.patches.active

    def refresh_from_registry(self) -> ProactiveCompatibilityStatus:
        """Locate the actual instance through ``StarMetadata.star_cls``."""
        try:
            stars = self.plugin.context.get_all_stars()
        except Exception as exc:  # noqa: BLE001 - registry API failure is diagnostic
            self._drop_patches()
            self._set_status(
                ProactiveCompatibilityStatus(
                    "proactive",
                    "incompatible",
                    f"could not inspect AstrBot plugin registry: {type(exc).__name__}",
                    baseline_commit_verified=False,
                )
            )
            return self.status

        metadata = next(
            (
                item
                for item in stars
                if getattr(item, "name", None) == PROACTIVE_PLUGIN_NAME
                and getattr(item, "activated", True)
                and getattr(item, "star_cls", None) is not None
            ),
            None,
        )
        if metadata is None:
            self._drop_patches()
            self._set_status(
                ProactiveCompatibilityStatus(
                    "proactive",
                    "not_installed",
                    "proactive_chat is not loaded or is inactive",
                    baseline_commit_verified=False,
                )
            )
            return self.status
        return self.install_metadata(metadata)

    def install_metadata(self, metadata: Any) -> ProactiveCompatibilityStatus:
        """Validate and patch a loaded metadata record, or degrade safely."""
        if getattr(metadata, "name", None) != PROACTIVE_PLUGIN_NAME:
            return self.status
        instance = getattr(metadata, "star_cls", None)
        raw_version = str(getattr(metadata, "version", "") or "")
        version = _normalized_version(raw_version)
        if version != SUPPORTED_VERSION:
            self._drop_patches()
            self._set_status(
                ProactiveCompatibilityStatus(
                    "proactive",
                    "incompatible",
                    f"unsupported proactive_chat version: {raw_version or 'unknown'}",
                    raw_version,
                    False,
                )
            )
            return self.status
        if instance is None or not getattr(metadata, "activated", True):
            self._drop_patches()
            self._set_status(
                ProactiveCompatibilityStatus(
                    "proactive",
                    "not_installed",
                    "proactive_chat is inactive",
                    raw_version,
                    False,
                )
            )
            return self.status
        if self.instance is instance and self.active:
            return self.status

        send = getattr(instance, "_send_proactive_message", None)
        get_config = getattr(instance, "_get_session_config", None)
        context = getattr(instance, "context", None)
        sync_getter = getattr(type(context), "get_using_tts_provider", None)
        problems: list[str] = []
        if not _has_bound_signature(send, ("session_id", "text")):
            problems.append("_send_proactive_message(session_id, text)")
        if not inspect.iscoroutinefunction(send):
            problems.append("_send_proactive_message must be async")
        if not _has_bound_signature(get_config, ("session_id",)):
            problems.append("_get_session_config(session_id)")
        if inspect.iscoroutinefunction(get_config):
            problems.append("_get_session_config must be synchronous")
        if not _has_bound_signature(sync_getter, ("self", "umo")):
            problems.append("Context.get_using_tts_provider(self, umo)")
        if problems:
            self._drop_patches()
            self._set_status(
                ProactiveCompatibilityStatus(
                    "proactive",
                    "incompatible",
                    "signature mismatch: " + "; ".join(problems),
                    raw_version,
                    False,
                )
            )
            return self.status

        self._drop_patches()
        self.metadata = metadata
        self.instance = instance
        manager = PatchManager(self._on_patch_deactivated)
        self.patches = manager
        try:
            manager.install(
                instance,
                "_send_proactive_message",
                self._wrap_send,
                patch_key=f"{PROACTIVE_PLUGIN_NAME}.instance._send_proactive_message",
            )
            manager.install(
                instance,
                "_get_session_config",
                self._wrap_session_config,
                patch_key=f"{PROACTIVE_PLUGIN_NAME}.instance._get_session_config",
            )
            manager.install(
                type(context),
                "get_using_tts_provider",
                self._wrap_sync_tts_getter,
                patch_key=(f"{PROACTIVE_PLUGIN_NAME}.Context.get_using_tts_provider"),
            )
        except Exception as exc:  # noqa: BLE001 - partial patches must be reverted
            manager.rollback()
            self.patches = None
            self.metadata = None
            self.instance = None
            self._set_status(
                ProactiveCompatibilityStatus(
                    "proactive",
                    "incompatible",
                    f"runtime patch installation failed: {type(exc).__name__}",
                    raw_version,
                    False,
                )
            )
            return self.status

        self._set_status(
            ProactiveCompatibilityStatus(
                "proactive",
                "signature_compatible_unverified",
                (
                    "v1.2.5 signatures are compatible; installed commit/content "
                    f"was not verified as {BASELINE_COMMIT}"
                ),
                raw_version,
                False,
            )
        )
        return self.status

    def handle_plugin_loaded(self, metadata: Any) -> ProactiveCompatibilityStatus:
        if getattr(metadata, "name", None) == PROACTIVE_PLUGIN_NAME:
            return self.install_metadata(metadata)
        return self.status

    def handle_plugin_unloaded(self, metadata: Any) -> ProactiveCompatibilityStatus:
        if (
            metadata is self.metadata
            or getattr(metadata, "star_cls", None) is self.instance
        ):
            version = str(getattr(metadata, "version", "") or "")
            self._drop_patches()
            self._set_status(
                ProactiveCompatibilityStatus(
                    "proactive",
                    "not_installed",
                    "proactive_chat was unloaded",
                    version,
                    False,
                )
            )
        return self.status

    def close(self) -> None:
        """Deactivate first, then restore attributes that are still ours."""
        if self.patches is not None:
            self.patches.close()
        if self.status.state != "closed":
            self._set_status(
                ProactiveCompatibilityStatus(
                    "proactive",
                    "closed",
                    "proactive compatibility adapter is closed",
                    self.status.version,
                    False,
                )
            )
        self.patches = None
        self.metadata = None
        self.instance = None

    def mark_disabled(
        self, detail: str = "proactive compatibility is disabled"
    ) -> None:
        self._drop_patches()
        self._set_status(
            ProactiveCompatibilityStatus(
                "proactive",
                "disabled",
                detail,
                self.status.version,
                False,
            )
        )

    def _drop_patches(self) -> None:
        if self.patches is not None:
            self._suppress_patch_status = True
            try:
                self.patches.close()
            finally:
                self._suppress_patch_status = False
        self.patches = None
        self.metadata = None
        self.instance = None

    def _on_patch_deactivated(self, reason: str) -> None:
        if self._suppress_patch_status:
            return
        state = "superseded" if reason == "superseded" else "closed"
        self._set_status(
            ProactiveCompatibilityStatus(
                "proactive",
                state,
                f"proactive compatibility patches were {state}",
                self.status.version,
                False,
            )
        )

    def _set_status(self, status: ProactiveCompatibilityStatus) -> None:
        if status == self.status:
            return
        self.status = status
        self._log_status()

    def _log_status(self) -> None:
        warning = getattr(
            self.logger, "warning", getattr(self.logger, "error", lambda *args: None)
        )
        log = (
            warning
            if self.status.state == "incompatible"
            else getattr(self.logger, "info", warning)
        )
        log(
            "Translate TTS proactive compatibility %s: %s",
            self.status.state,
            self.status.detail,
        )

    def _scope_matches(self, scope: TranslationScope | None, session_id: str) -> bool:
        instance = self.instance
        return bool(
            self.active
            and scope is not None
            and scope.active
            and scope.source == "proactive"
            and scope.owner is instance
            and scope.unified_msg_origin == session_id
            and scope.is_owned_by_current_task()
        )

    def _wrap_send(self, original: Any) -> Any:
        adapter = self

        @functools.wraps(original)
        async def wrapped(session_id: str, text: str) -> None:
            if (
                not adapter.active
                or not adapter.plugin.settings.enabled
                or not adapter.plugin.settings.enable_proactive_compat
            ):
                await original(session_id, text)
                return
            scope = TranslationScope(
                "proactive",
                session_id,
                adapter.plugin.settings,
                owner=adapter.instance,
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
            token = current_translation_scope.set(scope)
            try:
                await original(session_id, text)
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

        return wrapped

    def _wrap_session_config(self, original: Any) -> Any:
        adapter = self

        @functools.wraps(original)
        def wrapped(session_id: str) -> Any:
            config = original(session_id)
            scope = current_translation_scope.get()
            if not adapter._scope_matches(scope, session_id) or not isinstance(
                config, dict
            ):
                return config
            copied = config.copy()
            tts_settings = config.get("tts_settings")
            copied_tts = tts_settings.copy() if isinstance(tts_settings, dict) else {}
            copied_tts["always_send_text"] = True
            copied["tts_settings"] = copied_tts
            return copied

        return wrapped

    def _wrap_sync_tts_getter(self, original: Any) -> Any:
        adapter = self

        @functools.wraps(original)
        def wrapped(context: Any, umo: str | None = None) -> Any:
            provider = original(context, umo)
            scope = current_translation_scope.get()
            if (
                provider is None
                or not isinstance(umo, str)
                or not adapter._scope_matches(scope, umo)
                or getattr(adapter.instance, "context", None) is not context
            ):
                return provider
            assert scope is not None
            return TranslatedTTSProviderProxy(
                provider,
                scope,
                adapter.service,
                lambda: adapter.active,
            )

        return wrapped
