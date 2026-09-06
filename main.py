"""AstrBot plugin lifecycle for translated TTS."""

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter
from astrbot.api.star import Context, Star

from .compat.astrbot_4_27 import NormalPipelineAdapter, install_astrbot_4_27_adapter
from .compat.proactive_chat import ProactiveChatAdapter
from .config import ConfigurationError, TranslationSettings
from .translation import TranslationService


class TranslateTTSPlugin(Star):
    """Translate only text already selected for TTS by upstream pipelines."""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        configuration_valid = True
        try:
            self.settings = TranslationSettings.from_mapping(config)
        except ConfigurationError as exc:
            logger.error("Translate TTS configuration is invalid: %s", exc)
            self.settings = TranslationSettings(enabled=False)
            configuration_valid = False
        self.translation_service = TranslationService(
            context,
            max_concurrency=self.settings.max_concurrent_translations,
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
        self.translation_service.close()
        self.proactive_adapter.close()
        self.normal_adapter.close()
