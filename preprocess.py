"""Deterministic, bounded preprocessing for text that may enter translation."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from .config import TranslationSettings

_URL = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _code_fences(text: str, mode: str, replacement: str) -> str:
    if mode == "preserve":
        return text
    output: list[str] = []
    inside = False
    marker = ""
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        opening = stripped.startswith(("```", "~~~"))
        if not inside and opening:
            inside = True
            marker = stripped[:3]
            if mode == "replace" and replacement.strip():
                output.append(replacement.strip() + "\n")
            continue
        if inside:
            if stripped.startswith(marker):
                inside = False
            continue
        output.append(line)
    return "".join(output)


def _tables(text: str, mode: str, summary: str) -> str:
    if mode == "lines":
        transform = lambda line: "; ".join(
            cell.strip() for cell in line.strip().strip("|").split("|") if cell.strip()
        )
    else:
        transform = None
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        is_table = (
            "|" in lines[index]
            and index + 1 < len(lines)
            and bool(_TABLE_SEPARATOR.fullmatch(lines[index + 1]))
        )
        if not is_table:
            output.append(lines[index])
            index += 1
            continue
        block = [lines[index]]
        index += 2
        while index < len(lines) and "|" in lines[index] and lines[index].strip():
            block.append(lines[index])
            index += 1
        if mode == "summary":
            if summary.strip():
                output.append(summary.strip())
        elif mode == "lines" and transform is not None:
            output.extend(transform(line) for line in block)
    return "\n".join(output)


def _urls(text: str, mode: str, replacement: str) -> str:
    if mode == "full":
        return text

    def replace(match: re.Match[str]) -> str:
        raw = match.group(0)
        suffix = ""
        while raw and raw[-1] in ".,;:!?，。；：！？":
            suffix = raw[-1] + suffix
            raw = raw[:-1]
        if mode == "skip":
            value = ""
        elif mode == "replace":
            value = replacement.strip()
        else:
            value = urlsplit(raw).hostname or ""
        return value + suffix

    return _URL.sub(replace, text)


def _emoji(text: str, mode: str) -> str:
    if mode == "preserve":
        return text
    output: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        is_emoji = category == "So" or char in {"\ufe0f", "\u200d"}
        if not is_emoji:
            output.append(char)
        elif mode == "name" and char not in {"\ufe0f", "\u200d"}:
            output.append(f" {unicodedata.name(char, 'emoji').lower()} ")
    return "".join(output)


def _strip_markdown(text: str) -> str:
    # Only recognized decoration tokens are removed; parentheses and prose survive.
    for token in ("**", "__", "~~", "`"):
        text = text.replace(token, "")
    return re.sub(r"(?m)^(\s{0,3})(?:#{1,6}\s+|[-+*]\s+)", r"\1", text)


def preprocess_text(text: str, settings: TranslationSettings) -> str:
    if not settings.preprocessing_enabled:
        return text
    value = _code_fences(
        text, settings.code_block_mode, settings.code_block_replacement
    )
    value = _tables(value, settings.table_mode, settings.table_summary_text)
    if settings.quote_mode == "skip":
        value = "\n".join(
            line for line in value.splitlines() if not line.lstrip().startswith(">")
        )
    value = _urls(value, settings.url_mode, settings.url_replacement)
    value = _emoji(value, settings.emoji_mode)
    if settings.markdown_decoration_mode == "remove":
        value = _strip_markdown(value)
    if settings.collapse_whitespace:
        value = " ".join(value.split())
    return value[: settings.max_preprocessed_chars].strip()
