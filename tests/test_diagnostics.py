from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from translate_tts.diagnostics import (
    DiagnosticRecorder,
    exception_type_chain,
    identifier_ref,
    proxy_environment,
)


class CapturingLogger:
    def __init__(self):
        self.lines = []

    def info(self, template, value):
        self.lines.append(template % value)

    def warning(self, template, value):
        self.lines.append(template % value)

    def error(self, template, value):
        self.lines.append(template % value)


class DiagnosticTests(unittest.TestCase):
    def test_sensitive_fields_are_redacted_from_buffer_and_logs(self):
        logger = CapturingLogger()
        recorder = DiagnosticRecorder(logger, level="verbose", capacity=20)
        recorder.emit(
            "probe",
            trace_id="abcd1234",
            source="normal",
            message_text="private message",
            endpoint_url="https://secret.invalid/key",
            api_token="secret-token",
            elapsed_ms=12,
        )
        event = recorder.snapshot()["recent_events"][-1]
        self.assertEqual(event["message_text"], "redacted")
        self.assertEqual(event["endpoint_url"], "redacted")
        self.assertEqual(event["api_token"], "redacted")
        self.assertEqual(event["elapsed_ms"], 12)
        joined = "\n".join(logger.lines)
        self.assertNotIn("private message", joined)
        self.assertNotIn("secret.invalid", joined)
        self.assertNotIn("secret-token", joined)

    def test_provider_references_are_stable_and_non_plaintext(self):
        first = identifier_ref("provider-private-name")
        self.assertEqual(first, identifier_ref("provider-private-name"))
        self.assertNotEqual(first, identifier_ref("another-provider"))
        self.assertNotIn("provider-private-name", first)

    def test_exception_chain_excludes_messages(self):
        try:
            try:
                raise TimeoutError("private endpoint")
            except TimeoutError as exc:
                raise RuntimeError("secret response") from exc
        except RuntimeError as exc:
            chain = exception_type_chain(exc)
        self.assertIn("RuntimeError", chain)
        self.assertIn("TimeoutError", chain)
        self.assertNotIn("private endpoint", chain)
        self.assertNotIn("secret response", chain)

    def test_proxy_snapshot_exposes_presence_only(self):
        with patch.dict(
            os.environ,
            {"HTTPS_PROXY": "http://user:password@proxy.invalid:7890"},
            clear=True,
        ):
            snapshot = proxy_environment()
        self.assertEqual(
            snapshot,
            {"http_proxy": False, "https_proxy": True, "no_proxy": False},
        )
        self.assertNotIn("password", str(snapshot))


if __name__ == "__main__":
    unittest.main()
