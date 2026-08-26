#!/usr/bin/env python3
"""Host protocol tests for the USB-only read-only BROM diagnostic."""
from __future__ import annotations

import pathlib
import struct
import sys
import time
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modules"))

from diagnostic_protocol import (  # noqa: E402
    DIAG_CMD_HELLO,
    DIAG_CMD_READ_DEFAULT_SECTOR0,
    DIAG_PARTITION_UNKNOWN,
    DIAG_PROTOCOL_VERSION,
    DIAG_READY_MAGIC,
    DIAG_REQUEST_MAGIC,
    DIAG_RESPONSE_MAGIC,
    DiagnosticProtocol,
    ProtocolError,
    decode_init_report,
    encode_request,
    read_response,
)


def be32(*words: int) -> bytes:
    return b"".join(struct.pack(">I", word & 0xFFFFFFFF) for word in words)


class ChunkedSerial:
    """Small serial double which returns predefined fragments in order."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = list(chunks)
        self.writes: list[bytes] = []
        self.timeout = 5.0

    def read(self, size: int = 1) -> bytes:
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) > size:
            self.chunks.insert(0, chunk[size:])
            return chunk[:size]
        return chunk

    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        return len(data)


class ShortWriteSerial(ChunkedSerial):
    def write(self, data: bytes) -> int:
        self.writes.append(bytes(data))
        return len(data) - 1


class SlowSerial(ChunkedSerial):
    def __init__(self, chunks: list[bytes], delays: list[float]):
        super().__init__(chunks)
        self.delays = list(delays)

    def read(self, size: int = 1) -> bytes:
        if self.delays:
            time.sleep(self.delays.pop(0))
        return super().read(size)


class DiagnosticProtocolTests(unittest.TestCase):
    def test_request_is_versioned_and_sequence_bound(self) -> None:
        self.assertEqual(
            encode_request(7, DIAG_CMD_READ_DEFAULT_SECTOR0, 0),
            be32(DIAG_REQUEST_MAGIC, DIAG_PROTOCOL_VERSION, 7, DIAG_CMD_READ_DEFAULT_SECTOR0, 0),
        )

    def test_fragmented_sector_response_is_read_exactly(self) -> None:
        payload = bytes(range(256)) * 2
        header = be32(
            DIAG_RESPONSE_MAGIC,
            DIAG_PROTOCOL_VERSION,
            9,
            DIAG_CMD_READ_DEFAULT_SECTOR0,
            DIAG_PARTITION_UNKNOWN,
            0,
            0,
            len(payload),
        )
        serial = ChunkedSerial([header[:3], header[3:19], header[19:], payload[:17], payload[17:300], payload[300:]])
        response = read_response(serial, 9, DIAG_CMD_READ_DEFAULT_SECTOR0, timeout=1.0)
        self.assertEqual(response.selected_partition, DIAG_PARTITION_UNKNOWN)
        self.assertEqual(response.target, 0)
        self.assertEqual(response.status, 0)
        self.assertEqual(response.payload, payload)

    def test_error_response_has_signed_status_and_no_payload(self) -> None:
        serial = ChunkedSerial([
            be32(DIAG_RESPONSE_MAGIC, DIAG_PROTOCOL_VERSION, 4, DIAG_CMD_READ_DEFAULT_SECTOR0,
                 DIAG_PARTITION_UNKNOWN, 0, -110, 0)
        ])
        response = read_response(serial, 4, DIAG_CMD_READ_DEFAULT_SECTOR0, timeout=1.0)
        self.assertEqual(response.status, -110)
        self.assertEqual(response.payload, b"")

    def test_stale_sequence_is_rejected(self) -> None:
        serial = ChunkedSerial([
            be32(DIAG_RESPONSE_MAGIC, DIAG_PROTOCOL_VERSION, 2, DIAG_CMD_HELLO, 0, 0, 0, 0)
        ])
        with self.assertRaisesRegex(ProtocolError, "sequence"):
            read_response(serial, 3, DIAG_CMD_HELLO, timeout=1.0)

    def test_truncated_response_poisoned_session_cannot_send_again(self) -> None:
        serial = ChunkedSerial([be32(DIAG_RESPONSE_MAGIC, DIAG_PROTOCOL_VERSION, 1)])
        protocol = DiagnosticProtocol(serial)
        with self.assertRaisesRegex(ProtocolError, "short response"):
            protocol.hello(timeout=0.01)
        writes_after_failure = list(serial.writes)
        with self.assertRaisesRegex(ProtocolError, "desynchronized"):
            protocol.hello(timeout=0.01)
        self.assertEqual(serial.writes, writes_after_failure)

    def test_short_request_write_poisoned_session_immediately(self) -> None:
        serial = ShortWriteSerial([])
        protocol = DiagnosticProtocol(serial)
        with self.assertRaisesRegex(ProtocolError, "short request write"):
            protocol.hello(timeout=0.01)
        with self.assertRaisesRegex(ProtocolError, "desynchronized"):
            protocol.hello(timeout=0.01)

    def test_one_deadline_covers_header_and_payload(self) -> None:
        payload = b"data"
        header = be32(DIAG_RESPONSE_MAGIC, DIAG_PROTOCOL_VERSION, 1, DIAG_CMD_HELLO, 0, 0, 0, len(payload))
        serial = SlowSerial([header, payload], [0.04, 0.04])
        with self.assertRaisesRegex(ProtocolError, "short response"):
            read_response(serial, 1, DIAG_CMD_HELLO, timeout=0.05)

    def test_ready_marker_is_distinct_from_legacy_all_good(self) -> None:
        self.assertNotEqual(DIAG_READY_MAGIC, 0xB1B2B3B4)
        self.assertEqual(len(be32(DIAG_READY_MAGIC)), 4)

    def test_initialization_report_names_the_first_failed_stage(self) -> None:
        report = decode_init_report(be32(0x1234, 0, 0, 0x00FF8000, 0, -110, 0, 0, 0, 0, 4))
        self.assertEqual(report.msdc_cfg, 0x1234)
        self.assertEqual(report.send_op_cond_ready, -110)
        self.assertEqual(report.first_failed_stage, 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
