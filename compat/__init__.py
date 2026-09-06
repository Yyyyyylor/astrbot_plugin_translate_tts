"""Version-guarded runtime compatibility adapters."""

from .proactive_chat import ProactiveChatAdapter, ProactiveCompatibilityStatus
from .status import CompatibilityStatus

__all__ = [
    "CompatibilityStatus",
    "ProactiveChatAdapter",
    "ProactiveCompatibilityStatus",
]
