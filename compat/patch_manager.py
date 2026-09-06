"""Conservative, reversible runtime patch management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PatchRecord:
    target: Any
    attribute: str
    original: Any
    wrapper: Any
    generation: int
    had_own_attribute: bool


class PatchManager:
    """Install exact-identity patches and never overwrite a later wrapper."""

    _next_generation = 1

    def __init__(self, on_deactivate: Callable[[str], None] | None = None) -> None:
        self._records: list[PatchRecord] = []
        self.active = True
        self._on_deactivate = on_deactivate
        self.generation = PatchManager._next_generation
        PatchManager._next_generation += 1

    @property
    def records(self) -> tuple[PatchRecord, ...]:
        return tuple(self._records)

    def install(
        self,
        target: Any,
        attribute: str,
        wrapper_factory: Callable[[Any], Any],
        *,
        patch_key: str | None = None,
    ) -> Any:
        if not self.active:
            raise RuntimeError("patch manager is inactive")
        for record in self._records:
            if record.target is target and record.attribute == attribute:
                if getattr(target, attribute, None) is record.wrapper:
                    return record.wrapper
                raise RuntimeError(f"{attribute} changed after this manager patched it")
        key = patch_key or (
            f"{getattr(target, '__module__', '')}."
            f"{getattr(target, '__qualname__', type(target).__qualname__)}.{attribute}"
        )
        had_own_attribute = attribute in getattr(target, "__dict__", {})
        original = getattr(target, attribute)
        while getattr(original, "__translate_tts_patch_key__", None) == key:
            previous_manager = getattr(
                original, "__translate_tts_patch_manager__", None
            )
            if previous_manager is None:
                break
            previous_manager.deactivate("superseded")
            previous_records = getattr(previous_manager, "records", ())
            previous_record = next(
                (
                    record
                    for record in previous_records
                    if record.wrapper is original
                    and record.target is target
                    and record.attribute == attribute
                ),
                None,
            )
            if previous_record is None:
                break
            had_own_attribute = previous_record.had_own_attribute
            original = original.__translate_tts_original__
        wrapper = wrapper_factory(original)
        try:
            wrapper.__translate_tts_patch_key__ = key
            wrapper.__translate_tts_patch_manager__ = self
            wrapper.__translate_tts_original__ = original
            wrapper.__translate_tts_generation__ = self.generation
        except (AttributeError, TypeError):
            pass
        setattr(target, attribute, wrapper)
        self._records.append(
            PatchRecord(
                target,
                attribute,
                original,
                wrapper,
                self.generation,
                had_own_attribute,
            )
        )
        return wrapper

    def deactivate(self, reason: str = "closed") -> None:
        if not self.active:
            return
        self.active = False
        if self._on_deactivate is not None:
            self._on_deactivate(reason)

    def rollback(self, reason: str = "closed") -> None:
        self.deactivate(reason)
        for record in reversed(self._records):
            if getattr(record.target, record.attribute, None) is record.wrapper:
                if record.had_own_attribute:
                    setattr(record.target, record.attribute, record.original)
                else:
                    delattr(record.target, record.attribute)
        self._records.clear()

    def close(self) -> None:
        self.rollback("closed")
