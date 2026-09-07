"""Safe composition for configurable, history-free LLM prompts."""

from __future__ import annotations

from string import Formatter


def validate_custom_prompt(text: str, mode: str, allowed: set[str]) -> None:
    if mode == "replace" and not text.strip():
        raise ValueError("replacement prompt must not be empty")
    try:
        fields = {name for _, name, _, _ in Formatter().parse(text) if name}
    except ValueError as exc:
        raise ValueError("custom prompt has invalid braces") from exc
    unknown = fields - allowed
    if unknown:
        raise ValueError(f"unknown prompt placeholder: {min(unknown)}")


def compose_prompt(builtin: str, custom: str, mode: str, values: dict[str, str]) -> str:
    """Compose one semantic section; validation contracts remain separate."""
    if mode == "builtin":
        value = builtin
    elif mode == "append":
        value = (
            f"{builtin}\n\nAdditional operator instruction:\n{custom}"
            if custom.strip()
            else builtin
        )
    else:
        value = custom
    return value.format_map(values)
