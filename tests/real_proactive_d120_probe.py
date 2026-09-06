"""Read-only source probe for proactive_chat commit d1203524.

This is intentionally outside pytest's default ``test_*.py`` pattern.  It
validates a source checkout, not a running AstrBot instance or QQ delivery.
Set ``PROACTIVE_CHAT_ROOT`` to the plugin directory before running it.
"""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

BASELINE_COMMIT = "d1203524f29be248a4975bac1f7586e9557434ee"
EXPECTED_SHA256 = {
    "core/message_sender.py": (
        "1C8F614CF0DC33C560AD559D05A6638AA07FE4FA16DA4122394A4A2DE27FDD4E"
    ),
    "core/session_config.py": (
        "9DE96F86A8FF4012F20A063201496F8B49527844F796AC50A2DB29A414C5D2E2"
    ),
    "main.py": "E1399B60656E3D0F0373C5F2B15979772CD77F0822CD69F73FF0BF61049C1001",
    "metadata.yaml": (
        "948A4B3A09C8E20817B8FC24D0DD27859CCFBCEBA2D888C61CDB3DF166B931D7"
    ),
}


def _find_source_root() -> Path:
    configured = os.environ.get("PROACTIVE_CHAT_ROOT")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured).expanduser().resolve())
    astrbot_root = os.environ.get("ASTRBOT_ROOT")
    if astrbot_root:
        candidates.append(
            Path(astrbot_root).expanduser().resolve()
            / "data"
            / "plugins"
            / "astrbot_plugin_proactive_chat"
        )
    for root in (Path.cwd().resolve(), *Path(__file__).resolve().parents):
        candidates.append(root / "astrbot_plugin_proactive_chat")
    for candidate in candidates:
        if all((candidate / relative).is_file() for relative in EXPECTED_SHA256):
            return candidate
    raise RuntimeError(
        "proactive_chat source was not found; set PROACTIVE_CHAT_ROOT to the "
        "plugin directory"
    )


def _method_signature(path: Path, class_name: str, method_name: str) -> tuple[str, ...]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    item.name == method_name
                ):
                    return tuple(argument.arg for argument in item.args.args)
    raise AssertionError(f"{class_name}.{method_name} was not found in {path}")


def main() -> None:
    root = _find_source_root()
    for relative, expected in EXPECTED_SHA256.items():
        actual = hashlib.sha256((root / relative).read_bytes()).hexdigest().upper()
        assert actual == expected, f"source fingerprint mismatch: {relative}"

    assert _method_signature(
        root / "core" / "message_sender.py",
        "SenderMixin",
        "_send_proactive_message",
    ) == ("self", "session_id", "text")
    assert _method_signature(
        root / "core" / "session_config.py",
        "ConfigMixin",
        "_get_session_config",
    ) == ("self", "session_id")
    print(
        "proactive_chat read-only source probe: PASS "
        f"(commit {BASELINE_COMMIT}); source only, not runtime or QQ delivery"
    )


if __name__ == "__main__":
    main()
