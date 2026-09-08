"""AstrBot plugin lifecycle, admin preview, and bounded WebUI operations."""

import asyncio
import json
import secrets
import time
from dataclasses import replace
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star

from .admin import is_dashboard_admin
from .compat.astrbot_4_27 import NormalPipelineAdapter, install_astrbot_4_27_adapter
from .compat.proactive_chat import ProactiveChatAdapter
from .config import ConfigurationError, TranslationSettings
from .diagnostics import DiagnosticRecorder
from .emotion import EMOTIONS
from .file_cleanup import AudioFileRegistry, CleanupScheduler
from .preprocess import preprocess_text
from .scope import TranslationScope, current_translation_scope
from .translation import TranslationService
from .tts_adapters import provider_type
from .tts_proxy import TranslatedTTSProviderProxy

_command = getattr(filter, "command", lambda *args, **kwargs: lambda func: func)
_permission_type = getattr(
    filter, "permission_type", lambda *args, **kwargs: lambda func: func
)
_admin = getattr(getattr(filter, "PermissionType", object), "ADMIN", None)


class TranslateTTSPlugin(Star):
    """Translate only text already selected for TTS by upstream pipelines."""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._operation_lock = asyncio.Lock()
        self._confirmations: dict[str, tuple[float, str, dict]] = {}
        self._downloads: dict[str, tuple[float, str, str]] = {}
        self._preview_task: asyncio.Task | None = None
        self.audio_registry = None
        self.cleanup_scheduler = None
        try:
            from astrbot.core.utils.astrbot_path import (
                get_astrbot_data_path,
                get_astrbot_temp_path,
            )

            manifest = (
                Path(get_astrbot_data_path())
                / "plugin_data"
                / "astrbot_plugin_translate_tts"
                / "audio_files.json"
            )
            self.audio_registry = AudioFileRegistry(
                manifest, [Path(get_astrbot_temp_path())]
            )
        except (ImportError, OSError):
            warning = getattr(logger, "warning", None)
            if callable(warning):
                warning("Translate TTS file registry unavailable: runtime_path_api")
        configuration_valid = True
        try:
            self.settings = TranslationSettings.from_mapping(config)
        except ConfigurationError as exc:
            logger.error("Translate TTS configuration is invalid: %s", exc)
            self.settings = TranslationSettings(enabled=False)
            configuration_valid = False
        self.diagnostics = DiagnosticRecorder(
            logger,
            level=self.settings.diagnostic_log_level,
            capacity=self.settings.diagnostic_event_buffer_size,
        )
        self.diagnostics.emit(
            "plugin_initialized",
            configuration_valid=configuration_valid,
            enabled=self.settings.enabled,
            llm_timeout_seconds=self.settings.translation_timeout_seconds,
            queue_timeout_seconds=self.settings.translation_queue_timeout_seconds,
            max_concurrency=self.settings.max_concurrent_translations,
            translation_provider=(
                "configured" if self.settings.translation_provider_id else "session"
            ),
            tts_selection_mode=self.settings.tts_selection_mode,
            emotion_enabled=self.settings.emotion_enabled,
            diagnostic_schema=1,
        )
        self.translation_service = TranslationService(
            context,
            max_concurrency=self.settings.max_concurrent_translations,
            audio_registry=self.audio_registry,
            diagnostics=self.diagnostics,
        )
        if not configuration_valid:
            self.translation_service.close()
        self.normal_adapter = NormalPipelineAdapter(
            self, self.translation_service, logger=logger
        )
        self.proactive_adapter = ProactiveChatAdapter(
            self, self.translation_service, logger=logger
        )
        if configuration_valid and self.settings.enabled:
            try:
                install_astrbot_4_27_adapter(
                    self,
                    self.translation_service,
                    logger,
                    adapter=self.normal_adapter,
                )
            except Exception as exc:  # noqa: BLE001 - compatibility must degrade safely
                self.normal_adapter.mark_incompatible(
                    f"normal adapter unavailable: {type(exc).__name__}: {exc}"
                )
                logger.error(
                    "Translate TTS normal compatibility adapter unavailable: %s",
                    exc,
                )
        else:
            reason = (
                "invalid plugin configuration"
                if not configuration_valid
                else "plugin is disabled"
            )
            self.normal_adapter.mark_disabled(reason)
            self.proactive_adapter.mark_disabled(reason)
        self._register_web_apis()

    async def initialize(self) -> None:
        """Discover proactive_chat instances that loaded before this plugin."""
        if (
            self.settings.enabled
            and self.settings.enable_proactive_compat
            and self.translation_service._active
        ):
            self.proactive_adapter.refresh_from_registry()
        else:
            self.proactive_adapter.mark_disabled()
        if self.audio_registry is not None and self.settings.auto_cleanup_tts_files:
            self.cleanup_scheduler = CleanupScheduler(
                self.audio_registry,
                self.settings.tts_file_retention_days,
                self.settings.cleanup_check_period,
            )
            self.cleanup_scheduler.start()

    @property
    def compatibility_statuses(self):
        """Expose both adapter states in one stable diagnostic mapping."""
        return {
            "normal": self.normal_adapter.status,
            "proactive": self.proactive_adapter.status,
        }

    @filter.on_plugin_loaded()
    async def on_plugin_loaded(self, metadata) -> None:
        """Adapt proactive_chat when it loads after this plugin."""
        if self.settings.enabled and self.settings.enable_proactive_compat:
            self.proactive_adapter.handle_plugin_loaded(metadata)

    @filter.on_plugin_unloaded()
    async def on_plugin_unloaded(self, metadata) -> None:
        """Drop patches as soon as the adapted proactive instance unloads."""
        self.proactive_adapter.handle_plugin_unloaded(metadata)

    async def terminate(self) -> None:
        """Stop accepting new translation work during unload or reload."""
        self.diagnostics.emit("plugin_terminating")
        self.translation_service.close()
        self.proactive_adapter.close()
        self.normal_adapter.close()
        self._confirmations.clear()
        self._downloads.clear()
        if self._preview_task is not None:
            self._preview_task.cancel()
            try:
                await self._preview_task
            except asyncio.CancelledError:
                pass
            self._preview_task = None
        if self.cleanup_scheduler is not None:
            await self.cleanup_scheduler.stop()

    def _provider_info(self, provider) -> dict:
        meta = provider.meta()
        config = getattr(provider, "provider_config", {})
        kind = provider_type(provider)
        model = (
            self.settings.fish_model
            if kind == "fishaudio_tts_api"
            else str(getattr(meta, "model", "") or config.get("model", ""))
        )
        voice = next(
            (
                str(config[key])
                for key in ("voice", "voice_id", "reference_id", "speaker")
                if config.get(key)
            ),
            "",
        )
        emotion_protocol = {
            "fishaudio_tts_api": (
                "Fish S1 parentheses"
                if self.settings.fish_model == "s1"
                else "Fish S2 brackets and segments"
            ),
            "elevenlabs_tts_api": "ElevenLabs v3 audio tags",
            "minimax_tts_api": "MiniMax voice_setting.emotion",
            "gemini_tts": "Gemini style instruction",
        }.get(kind, "plain translated text")
        return {
            "id": str(getattr(meta, "id", "") or config.get("id", "")),
            "type": kind,
            "instance": str(getattr(meta, "id", "") or config.get("id", "")),
            "model": model,
            "voice": voice,
            "target_language": self.settings.target_language_name(),
            "emotion_protocol": emotion_protocol,
            "may_cost": kind != "fishaudio_tts_api"
            or self.settings.fish_model != "s2.1-pro-free",
            "may_consume_quota": True,
        }

    def _preview_provider(self, provider_id: str = ""):
        requested = (
            provider_id
            or self.settings.preview_tts_provider_id
            or self.settings.tts_provider_id
        )
        if requested:
            provider = self.context.get_provider_by_id(requested)
            if provider is not None and any(
                provider is item for item in self.context.get_all_tts_providers()
            ):
                return provider
            raise ValueError("TTS provider is unavailable")
        providers = tuple(self.context.get_all_tts_providers())
        if not providers:
            raise ValueError("No TTS provider is configured")
        return providers[0]

    def _validate_preview_payload(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise TypeError("preview payload must be an object")
        text = str(payload.get("text", "") or "").strip()
        if len(text) > self.settings.max_input_chars:
            raise ValueError("preview text exceeds the configured input limit")
        emotion = str(payload.get("emotion", "neutral") or "neutral").lower()
        if emotion not in EMOTIONS:
            raise ValueError("preview emotion is invalid")
        translate = payload.get("translate", True)
        if not isinstance(translate, bool):
            raise TypeError("preview translate flag must be boolean")
        return {
            "operation": "preview",
            "text": text,
            "emotion": emotion,
            "translate": translate,
            "provider_id": str(payload.get("provider_id", "") or "").strip(),
        }

    async def _generate_preview(self, payload: dict):
        text = (
            str(payload.get("text", "") or "").strip()
            or "Hello. This is a safe text-to-speech preview."
        )
        provider_id = str(payload.get("provider_id", "") or "").strip()
        provider = self._preview_provider(provider_id)
        settings = replace(
            self.settings,
            tts_provider_id=provider_id or self._provider_info(provider)["id"],
        )
        scope = TranslationScope(
            "preview",
            "translate_tts:preview",
            settings,
            owner=self,
            owner_task=asyncio.current_task(),
            skip_translation=not bool(payload.get("translate", True)),
            preview_emotion=str(payload.get("emotion", "neutral") or "neutral"),
        )
        token = current_translation_scope.set(scope)
        try:
            proxy = TranslatedTTSProviderProxy(
                provider, scope, self.translation_service, lambda: True
            )
            return await proxy.get_audio(text)
        finally:
            scope.deactivate()
            current_translation_scope.reset(token)

    def _issue_confirmation(self, username: str, payload: dict) -> str:
        now = time.monotonic()
        self._confirmations = {
            key: item for key, item in self._confirmations.items() if item[0] >= now
        }
        if len(self._confirmations) >= 128:
            self._confirmations.pop(next(iter(self._confirmations)))
        token = secrets.token_urlsafe(24)
        self._confirmations[token] = (now + 120, username, payload)
        return token

    def _consume_confirmation(self, token: str, username: str) -> dict:
        item = self._confirmations.pop(token, None)
        if item is None or item[0] < time.monotonic() or item[1] != username:
            raise PermissionError("confirmation is missing or expired")
        return item[2]

    def _register_web_apis(self) -> None:
        register = getattr(self.context, "register_web_api", None)
        if not callable(register):
            return
        routes = (
            ("/astrbot_plugin_translate_tts/status", self._web_status, ["GET"]),
            (
                "/astrbot_plugin_translate_tts/preprocess",
                self._web_preprocess,
                ["POST"],
            ),
            (
                "/astrbot_plugin_translate_tts/reset-prompts",
                self._web_reset_prompts,
                ["POST"],
            ),
            (
                "/astrbot_plugin_translate_tts/cleanup-plan",
                self._web_cleanup_plan,
                ["POST"],
            ),
            (
                "/astrbot_plugin_translate_tts/cleanup-run",
                self._web_cleanup_run,
                ["POST"],
            ),
            (
                "/astrbot_plugin_translate_tts/preview-plan",
                self._web_preview_plan,
                ["POST"],
            ),
            (
                "/astrbot_plugin_translate_tts/preview-generate",
                self._web_preview_generate,
                ["POST"],
            ),
            (
                "/astrbot_plugin_translate_tts/preview-cancel",
                self._web_preview_cancel,
                ["POST"],
            ),
            (
                "/astrbot_plugin_translate_tts/preview-download",
                self._web_preview_download,
                ["GET"],
            ),
        )
        for route, handler, methods in routes:
            register(route, handler, methods, "Translate TTS administrator operation")

    @staticmethod
    def _web_identity(web) -> str:
        if not is_dashboard_admin(web.request.username):
            return ""
        return web.request.username

    async def _web_status(self):
        from astrbot.api import web

        if not self._web_identity(web):
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        providers = [
            self._provider_info(item) for item in self.context.get_all_tts_providers()
        ]
        cleanup = (
            self.audio_registry.status(self.settings.cleanup_check_period)
            if self.audio_registry
            else None
        )
        return web.json_response(
            {
                "providers": providers,
                "cleanup": cleanup,
                "diagnostics": self._diagnostic_status(limit=50),
            }
        )

    def _diagnostic_status(self, *, limit: int = 20) -> dict:
        status = self.diagnostics.snapshot(limit=limit)
        status["settings"] = {
            "llm_timeout_seconds": self.settings.translation_timeout_seconds,
            "queue_timeout_seconds": self.settings.translation_queue_timeout_seconds,
            "max_concurrency": self.settings.max_concurrent_translations,
            "translation_provider": (
                "configured" if self.settings.translation_provider_id else "session"
            ),
            "diagnostic_log_level": self.settings.diagnostic_log_level,
        }
        status["compatibility"] = {
            name: str(getattr(value, "state", "unknown"))
            for name, value in self.compatibility_statuses.items()
        }
        return status

    async def _web_preprocess(self):
        from astrbot.api import web

        if not self._web_identity(web):
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        payload = await web.request.json({})
        if not isinstance(payload, dict):
            return web.error_response("request body must be an object", status_code=400)
        return web.json_response(
            {"text": preprocess_text(str(payload.get("text", "")), self.settings)}
        )

    async def _web_reset_prompts(self):
        from astrbot.api import web

        if not self._web_identity(web):
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        payload = await web.request.json({})
        if not isinstance(payload, dict):
            return web.error_response("request body must be an object", status_code=400)
        target = str(payload.get("target", "all"))
        if target not in {"translation", "emotion", "all"}:
            return web.error_response("unknown prompt target", status_code=400)
        if target in {"translation", "all"}:
            self.config["translation_prompt_mode"] = "builtin"
            self.config["translation_prompt_text"] = ""
        if target in {"emotion", "all"}:
            self.config["emotion_prompt_mode"] = "builtin"
            self.config["emotion_prompt_text"] = ""
        self.config.save_config()
        return web.json_response({"saved": True, "reload_required": True})

    async def _web_cleanup_plan(self):
        from astrbot.api import web

        username = self._web_identity(web)
        if not username:
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        return web.json_response(
            {
                "confirmation": self._issue_confirmation(
                    username, {"operation": "cleanup"}
                ),
                "warning": "Registered expired files will be deleted.",
            }
        )

    async def _web_cleanup_run(self):
        from astrbot.api import web

        username = self._web_identity(web)
        if not username:
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        payload = await web.request.json({})
        if not isinstance(payload, dict):
            return web.error_response("request body must be an object", status_code=400)
        try:
            confirmed = self._consume_confirmation(
                str(payload.get("confirmation", "")), username
            )
        except PermissionError as exc:
            return web.error_response(str(exc), status_code=403)
        if confirmed.get("operation") != "cleanup":
            return web.error_response(
                "confirmation operation mismatch", status_code=403
            )
        if self.audio_registry is None:
            return web.error_response("file registry unavailable", status_code=503)
        if self._operation_lock.locked():
            return web.error_response("operation already running", status_code=409)
        async with self._operation_lock:
            result = await self.audio_registry.cleanup(
                self.settings.tts_file_retention_days
            )
        return web.json_response(
            {
                "result": result,
                "status": self.audio_registry.status(
                    self.settings.cleanup_check_period
                ),
            }
        )

    async def _web_preview_plan(self):
        from astrbot.api import web

        username = self._web_identity(web)
        if not username:
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        payload = await web.request.json({})
        if not isinstance(payload, dict):
            return web.error_response("request body must be an object", status_code=400)
        try:
            payload = self._validate_preview_payload(payload)
        except (TypeError, ValueError) as exc:
            return web.error_response(str(exc), status_code=400)
        try:
            provider = self._preview_provider(str(payload.get("provider_id", "")))
        except ValueError as exc:
            return web.error_response(str(exc), status_code=400)
        return web.json_response(
            {
                "confirmation": self._issue_confirmation(username, payload),
                "provider": self._provider_info(provider),
                "warning": "Real synthesis may consume provider quota.",
            }
        )

    async def _web_preview_generate(self):
        from astrbot.api import web

        username = self._web_identity(web)
        if not username:
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        payload = await web.request.json({})
        if not isinstance(payload, dict):
            return web.error_response("request body must be an object", status_code=400)
        try:
            preview = self._consume_confirmation(
                str(payload.get("confirmation", "")), username
            )
        except PermissionError as exc:
            return web.error_response(str(exc), status_code=403)
        if preview.get("operation") != "preview":
            return web.error_response(
                "confirmation operation mismatch", status_code=403
            )
        if self._operation_lock.locked():
            return web.error_response("operation already running", status_code=409)
        try:
            async with self._operation_lock, asyncio.timeout(120):
                self._preview_task = asyncio.create_task(
                    self._generate_preview(preview)
                )
                audio = await self._preview_task
        except TimeoutError:
            return web.error_response("preview timed out", status_code=504)
        except ValueError as exc:
            return web.error_response(str(exc), status_code=400)
        except asyncio.CancelledError:
            return web.error_response("preview cancelled", status_code=409)
        finally:
            self._preview_task = None
        path = (
            self.audio_registry.resolve_registered(audio)
            if self.audio_registry
            else None
        )
        if path is None:
            return web.error_response(
                "provider returned no downloadable local audio", status_code=502
            )
        download = secrets.token_urlsafe(24)
        now = time.monotonic()
        self._downloads = {
            key: item for key, item in self._downloads.items() if item[0] >= now
        }
        if len(self._downloads) >= 128:
            self._downloads.pop(next(iter(self._downloads)))
        self._downloads[download] = (now + 300, username, str(path))
        return web.json_response({"download": download})

    async def _web_preview_cancel(self):
        from astrbot.api import web

        if not self._web_identity(web):
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        if self._preview_task is None or self._preview_task.done():
            return web.json_response({"cancelled": False})
        self._preview_task.cancel()
        return web.json_response({"cancelled": True})

    async def _web_preview_download(self):
        from astrbot.api import web

        username = self._web_identity(web)
        if not username:
            return web.error_response(
                "administrator authentication required", status_code=403
            )
        token = str(web.request.query.get("token", ""))
        item = self._downloads.pop(token, None)
        if item is None or item[0] < time.monotonic() or item[1] != username:
            return web.error_response("download is missing or expired", status_code=403)
        path = (
            self.audio_registry.resolve_registered(item[2])
            if self.audio_registry
            else None
        )
        if path is None:
            return web.error_response("download is unavailable", status_code=404)
        return web.file_response(path, filename=path.name)

    @_permission_type(_admin)
    @_command("tts_diagnostics")
    async def tts_diagnostics(self, event):
        """Return a privacy-safe Translate TTS diagnostic snapshot."""
        yield event.plain_result(
            json.dumps(
                self._diagnostic_status(limit=10),
                ensure_ascii=False,
                indent=2,
            )
        )

    @_permission_type(_admin)
    @_command("tts_preview")
    async def tts_preview(self, event, text: str = ""):
        """Create an administrator-bound confirmation token without synthesizing."""
        try:
            payload = self._validate_preview_payload(
                {
                    "text": text,
                    "translate": self.settings.preview_translate,
                    "emotion": self.settings.preview_emotion,
                    "provider_id": self.settings.preview_tts_provider_id,
                }
            )
        except (TypeError, ValueError) as exc:
            yield event.plain_result(f"TTS preview rejected: {type(exc).__name__}")
            return
        token = self._issue_confirmation(str(event.get_sender_id()), payload)
        yield event.plain_result(
            f"This preview may consume provider quota. Confirm within 120 seconds: /tts_preview_confirm {token}"
        )

    @_permission_type(_admin)
    @_command("tts_preview_confirm")
    async def tts_preview_confirm(self, event, token: str):
        """Run a confirmed preview through the formal isolated provider path."""
        if self._operation_lock.locked():
            yield event.plain_result("Another Translate TTS operation is running.")
            return
        try:
            payload = self._consume_confirmation(token, str(event.get_sender_id()))
            if payload.get("operation") != "preview":
                raise PermissionError("confirmation operation mismatch")
            async with self._operation_lock, asyncio.timeout(120):
                self._preview_task = asyncio.create_task(
                    self._generate_preview(payload)
                )
                audio = await self._preview_task
        except (PermissionError, TimeoutError, ValueError) as exc:
            yield event.plain_result(f"TTS preview failed: {type(exc).__name__}")
            return
        except asyncio.CancelledError:
            yield event.plain_result("TTS preview cancelled.")
            return
        finally:
            self._preview_task = None
        yield event.plain_result(f"TTS preview generated: {audio}")

    @_permission_type(_admin)
    @_command("tts_preview_cancel")
    async def tts_preview_cancel(self, event):
        """Cancel the current administrator preview without starting a fallback."""
        if self._preview_task is None or self._preview_task.done():
            yield event.plain_result("No TTS preview is running.")
            return
        self._preview_task.cancel()
        yield event.plain_result("TTS preview cancellation requested.")
