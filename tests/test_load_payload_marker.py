#!/usr/bin/env python3
"""Regression tests for selecting the expected post-load payload marker."""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

from common import Device  # noqa: E402


class ReadOnlyStream:
    def __init__(self, data: bytes):
        self.data = data

    def read(self, size: int = 1) -> bytes:
        result, self.data = self.data[:size], self.data[size:]
        return result


class ChunkedStream:
    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)

    def read(self, size: int = 1) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class PayloadMarkerTests(unittest.TestCase):
    def test_legacy_marker_remains_default(self) -> None:
        device = Device()
        device.dev = ReadOnlyStream(b"\xB1\xB2\xB3\xB4")
        device.wait_payload()

    def test_diagnostic_marker_can_be_required_explicitly(self) -> None:
        device = Device()
        device.dev = ReadOnlyStream(b"LED1")
        device.wait_payload(expected=b"LED1")

    def test_fragmented_marker_is_reassembled(self) -> None:
        device = Device()
        device.dev = ChunkedStream([b"L", b"ED", b"1"])
        device.wait_payload(expected=b"LED1")

    def test_wrong_marker_is_rejected(self) -> None:
        device = Device()
        device.dev = ReadOnlyStream(b"\xB1\xB2\xB3\xB4")
        with self.assertRaisesRegex(RuntimeError, "expected pattern"):
            device.wait_payload(expected=b"LED1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
