"""Manifest-based cleanup for audio files actually returned by this plugin."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger("astrbot")


@dataclass(frozen=True, slots=True)
class CleanupResult:
    checked_at: str
    deleted_files: int
    released_bytes: int
    error_types: tuple[str, ...] = ()


class AudioFileRegistry:
    def __init__(self, manifest: Path, allowed_roots: list[Path]) -> None:
        self.manifest = manifest
        self.allowed_roots = tuple(root.resolve() for root in allowed_roots)
        self._lock = asyncio.Lock()
        self._active: set[str] = set()
        self.last_result: CleanupResult | None = None

    def _safe_file(self, value: Any) -> Path | None:
        if not isinstance(value, (str, os.PathLike)):
            return None
        raw = os.fspath(value)
        if urlsplit(raw).scheme.lower() in {"http", "https"}:
            return None
        candidate = Path(raw)
        try:
            if candidate.is_symlink() or not candidate.is_file():
                return None
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if not any(resolved.is_relative_to(root) for root in self.allowed_roots):
            return None
        return resolved

    def _read(self) -> dict[str, float]:
        try:
            payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {
            str(path): float(created)
            for path, created in payload.get("files", {}).items()
            if isinstance(path, str) and isinstance(created, (int, float))
        }

    def _write(self, files: dict[str, float]) -> None:
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        temp = self.manifest.with_suffix(".tmp")
        temp.write_text(
            json.dumps({"files": files}, ensure_ascii=False), encoding="utf-8"
        )
        os.replace(temp, self.manifest)

    async def register(self, value: Any) -> Path | None:
        path = self._safe_file(value)
        if path is None:
            return None
        async with self._lock:
            files = self._read()
            files[str(path)] = datetime.now(UTC).timestamp()
            self._write(files)
        return path

    def resolve_registered(self, value: Any) -> Path | None:
        path = self._safe_file(value)
        if path is None or str(path) not in self._read():
            return None
        return path

    async def cleanup(
        self, retention_days: int, *, now: datetime | None = None
    ) -> CleanupResult:
        current = now or datetime.now(UTC)
        cutoff = (current - timedelta(days=retention_days)).timestamp()
        deleted = released = 0
        errors: set[str] = set()
        async with self._lock:
            files = self._read()
            retained: dict[str, float] = {}
            for raw, created in files.items():
                path = self._safe_file(raw)
                if path is None:
                    continue
                try:
                    freshest = max(created, path.stat().st_mtime)
                except OSError as exc:
                    errors.add(type(exc).__name__)
                    retained[raw] = created
                    continue
                if freshest > cutoff or raw in self._active:
                    retained[raw] = created
                    continue
                try:
                    size = path.stat().st_size
                    path.unlink()
                except OSError as exc:
                    errors.add(type(exc).__name__)
                    retained[raw] = created
                else:
                    deleted += 1
                    released += size
            self._write(retained)
        result = CleanupResult(
            current.isoformat(), deleted, released, tuple(sorted(errors))
        )
        self.last_result = result
        logger.info(
            "Translate TTS cleanup: deleted=%d bytes=%d errors=%s",
            deleted,
            released,
            ",".join(result.error_types) or "none",
        )
        return result

    def status(self, period: str) -> dict[str, Any]:
        intervals = {
            "12h": timedelta(hours=12),
            "daily": timedelta(days=1),
            "weekly": timedelta(days=7),
        }
        result = asdict(self.last_result) if self.last_result else None
        next_check = None
        if self.last_result and period in intervals:
            next_check = (
                datetime.fromisoformat(self.last_result.checked_at) + intervals[period]
            ).isoformat()
        return {"last": result, "next_check": next_check}


class CleanupScheduler:
    def __init__(
        self, registry: AudioFileRegistry, retention_days: int, period: str
    ) -> None:
        self.registry = registry
        self.retention_days = retention_days
        self.period = period
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="translate-tts-cleanup")

    async def _run(self) -> None:
        await self.registry.cleanup(self.retention_days)
        if self.period == "startup":
            return
        seconds = {"12h": 43200, "daily": 86400, "weekly": 604800}[self.period]
        while True:
            await asyncio.sleep(seconds)
            await self.registry.cleanup(self.retention_days)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
