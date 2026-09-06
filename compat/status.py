"""Shared observable state for runtime compatibility adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CompatibilityState = Literal[
    "signature_compatible_unverified",
    "not_installed",
    "disabled",
    "incompatible",
    "closed",
    "superseded",
]


@dataclass(frozen=True, slots=True)
class CompatibilityStatus:
    adapter: Literal["normal", "proactive"]
    state: CompatibilityState
    detail: str
    version: str = ""
    baseline_commit_verified: bool | None = None
