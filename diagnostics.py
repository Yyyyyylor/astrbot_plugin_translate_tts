"""Privacy-safe structured diagnostics for Translate TTS calls."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from collections import deque
from datetime import UTC, datetime
from typing import Any

_SAFE_VALUE = re.compile(r"[^A-Za-z0-9_.:/+-]")
_SENSITIVE_FIELD_PARTS = {
    "content",
    "credential",
    "endpoint",
    "key",
    "message",
    "prompt",
    "proxy_address",
    "secret",
    "text",
    "token",
    "url",
}


def exception_type_chain(exc: BaseException, *, limit: int = 4) -> str:
    """Return exception class names without exception messages or request data."""
    names: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen and len(names) < limit:
        seen.add(id(current))
        names.append(f"{type(current).__module__}.{type(current).__name__}")
        current = current.__cause__ or current.__context__
    return ">".join(names)


def identifier_ref(value: str) -> str:
    """Create a stable, non-reversible reference for a provider identifier."""
    if not value:
        return "none"
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def proxy_environment() -> dict[str, bool]:
    """Expose only whether proxy variables exist, never their values."""
    return {
        "http_proxy": bool(
            os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        ),
        "https_proxy": bool(
            os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        ),
        "no_proxy": bool(os.environ.get("NO_PROXY") or os.environ.get("no_proxy")),
    }


class DiagnosticRecorder:
    """Emit logfmt events and retain a bounded, safe in-memory status buffer."""

    def __init__(self, logger: Any, *, level: str = "normal", capacity: int = 100):
        self._logger = logger
        self.level = level
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self.generation = secrets.token_hex(4)
        self.started_at = datetime.now(UTC).isoformat()

    @staticmethod
    def _safe(value: Any) -> str | int | float | bool:
        if isinstance(value, bool | int | float):
            return value
        if value is None:
            return "none"
        text = _SAFE_VALUE.sub("_", str(value).strip())
        return text[:160] or "none"

    def emit(
        self,
        event: str,
        *,
        severity: str = "info",
        detail: bool = False,
        trace_id: str = "",
        source: str = "",
        **fields: Any,
    ) -> None:
        safe_fields = {
            key: (
                "redacted"
                if any(part in key.lower() for part in _SENSITIVE_FIELD_PARTS)
                else self._safe(value)
            )
            for key, value in fields.items()
        }
        record: dict[str, Any] = {
            "at": datetime.now(UTC).isoformat(),
            "event": self._safe(event),
            "trace": self._safe(trace_id),
            "source": self._safe(source),
            **safe_fields,
        }
        self._events.append(record)
        should_log = severity in {"warning", "error"} or (
            self.level == "verbose" or (self.level == "normal" and not detail)
        )
        if not should_log:
            return
        method = getattr(
            self._logger,
            severity if severity != "detail" else "info",
            None,
        )
        if not callable(method):
            return
        pairs = [f"event={record['event']}"]
        if trace_id:
            pairs.append(f"trace={record['trace']}")
        if source:
            pairs.append(f"source={record['source']}")
        pairs.extend(f"{key}={value}" for key, value in safe_fields.items())
        method("Translate TTS diagnostic %s", " ".join(pairs))

    def snapshot(self, *, limit: int = 20) -> dict[str, Any]:
        """Return a bounded administrator-safe diagnostic snapshot."""
        events = list(self._events)[-max(0, min(limit, 100)) :]
        return {
            "generation": self.generation,
            "started_at": self.started_at,
            "level": self.level,
            "proxy_environment": proxy_environment(),
            "recent_events": events,
        }
